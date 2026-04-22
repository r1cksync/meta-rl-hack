"""Optional real Kubernetes backend.

When ``REAL_K8S=true`` is set and the `kubernetes` Python client can load a
config (kubeconfig, in-cluster SA, or bearer-token env vars), this backend
executes write actions and raw ``kubectl`` commands against a live cluster.
Otherwise every call returns a ``[MOCK]`` string — the HF Space path.

Local development target: kind (Kubernetes in Docker). Any cluster with
``kubectl`` access works. See ``scripts/setup_kind.*`` for one-click setup.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class K8sActionResult:
    ok: bool
    message: str
    real: bool


class K8sBackend:
    """Thin wrapper around the K8s Python client with mock fallback."""

    def __init__(self, namespace: str | None = None) -> None:
        self.namespace = namespace or os.getenv("INCIDENT_NAMESPACE", "default")
        self._apps = None
        self._core = None
        self._commands = None
        self._injector = None
        self.enabled = self._try_load()

    # ---- structured action methods (legacy path) ----------------------

    def rollback(self, deployment: str) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Rolled back deployment/{deployment} to previous revision.")
        ns = self._find_namespace(deployment)
        try:
            out = self._commands.run(f"kubectl rollout undo deployment/{deployment} -n {ns}")
            return K8sActionResult("error" not in out, f"[REAL] {out}", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] rollback {deployment}: {e}", True)

    def restart(self, deployment: str) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Restarted pods for deployment/{deployment}.")
        ns = self._find_namespace(deployment)
        try:
            out = self._commands.run(f"kubectl rollout restart deployment/{deployment} -n {ns}")
            return K8sActionResult("error" not in out, f"[REAL] {out}", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] restart {deployment}: {e}", True)

    def scale(self, deployment: str, replicas: int) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Scaled deployment/{deployment} to {replicas} replicas.")
        if replicas < 0 or replicas > 20:
            return K8sActionResult(False, f"ERROR: replicas must be 0-20 (got {replicas})", False)
        ns = self._find_namespace(deployment)
        try:
            out = self._commands.run(f"kubectl scale deployment/{deployment} --replicas={replicas} -n {ns}")
            return K8sActionResult("error" not in out, f"[REAL] {out}", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] scale {deployment}: {e}", True)

    def apply_config_patch(self, deployment: str, env_var: str, value: str) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Patched deployment/{deployment}: set {env_var}={value}.")
        ns = self._find_namespace(deployment)
        try:
            out = self._commands.run(
                f"kubectl set env deployment/{deployment} {env_var}={value} -n {ns}")
            return K8sActionResult("error" not in out, f"[REAL] {out}", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] patch {deployment}: {e}", True)

    # ---- new real-mode methods ----------------------------------------

    def execute(self, kubectl_cmd: str) -> str:
        """Run an arbitrary kubectl command. Returns kubectl-style text output."""
        if not self.enabled:
            return "[MOCK] kubectl passthrough disabled (set REAL_K8S=true and configure kubeconfig)"
        return self._commands.run(kubectl_cmd)

    def inject_failure(self, fault_type: str, namespace: str | None = None,
                       deployment: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "real": False, "message": "[MOCK] fault injection disabled"}
        res = self._injector.inject(fault_type, namespace, deployment)
        return {"ok": res.ok, "real": True, "message": res.message,
                "namespace": res.namespace, "deployment": res.deployment, "fault": res.fault_type}

    def reset_to_healthy(self) -> list[str]:
        if not self.enabled:
            return ["[MOCK] cluster reset disabled"]
        return self._injector.reset_to_healthy()

    def wait_for_healthy(self, namespaces: list[str] | None = None, timeout_s: int = 60) -> bool:
        if not self.enabled:
            return True
        from .k8s_constants import APP_NAMESPACES, RESET_POLL_INTERVAL
        ns_list = namespaces or APP_NAMESPACES
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            unhealthy = []
            for ns in ns_list:
                try:
                    pods = self._core.list_namespaced_pod(ns).items
                except Exception:
                    continue
                for p in pods:
                    phase = (p.status.phase or "")
                    if phase not in ("Running", "Succeeded", "Pending"):
                        unhealthy.append(f"{ns}/{p.metadata.name}={phase}")
            if not unhealthy:
                return True
            time.sleep(RESET_POLL_INTERVAL)
        return False

    def check_health_detailed(self) -> dict[str, dict[str, dict[str, Any]]]:
        if not self.enabled:
            return {}
        from .k8s_constants import APP_NAMESPACES
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for ns in APP_NAMESPACES:
            try:
                pods = self._core.list_namespaced_pod(ns).items
            except Exception:
                out[ns] = {}
                continue
            ns_out = {}
            for p in pods:
                statuses = p.status.container_statuses or []
                ns_out[p.metadata.name] = {
                    "phase": p.status.phase,
                    "restarts": sum(cs.restart_count or 0 for cs in statuses),
                    "oom_killed": any(
                        cs.last_state and cs.last_state.terminated
                        and cs.last_state.terminated.reason == "OOMKilled"
                        for cs in statuses),
                    "waiting_reason": next((cs.state.waiting.reason
                                            for cs in statuses if cs.state and cs.state.waiting), None),
                }
            out[ns] = ns_out
        return out

    def list_pods(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            pods = self._core.list_namespaced_pod(self.namespace).items
            return [{"name": p.metadata.name, "status": p.status.phase,
                     "restarts": sum(cs.restart_count for cs in (p.status.container_statuses or []))}
                    for p in pods]
        except Exception as e:
            log.warning("list_pods failed: %s", e)
            return []

    # ---- internals ----------------------------------------------------

    def _find_namespace(self, deployment: str) -> str:
        from .k8s_constants import HEALTHY_STATE
        for ns, deps in HEALTHY_STATE.items():
            if deployment in deps:
                return ns
        return self.namespace

    def _try_load(self) -> bool:
        if os.getenv("REAL_K8S", "false").lower() not in ("1", "true", "yes"):
            return False
        try:
            from kubernetes import client, config  # type: ignore
        except ImportError:
            log.info("kubernetes client not installed; using mock backend")
            return False
        loaded = False
        try:
            config.load_incluster_config()
            loaded = True
            log.info("K8s auth: in-cluster")
        except Exception:
            try:
                config.load_kube_config()
                loaded = True
                log.info("K8s auth: kubeconfig")
            except Exception:
                endpoint = os.environ.get("K8S_ENDPOINT")
                token = os.environ.get("K8S_TOKEN")
                if endpoint and token:
                    cfg = client.Configuration()
                    cfg.host = endpoint.strip()
                    cfg.api_key = {"BearerToken": token.strip()}
                    cfg.api_key_prefix = {"BearerToken": "Bearer"}
                    ca = os.environ.get("K8S_CA_CERT")
                    if ca:
                        import base64, tempfile, urllib3  # noqa: F401
                        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                        try:
                            raw = base64.b64decode(ca.strip())
                            f = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
                            f.write(raw); f.close()
                            cfg.ssl_ca_cert = f.name
                        except Exception:
                            cfg.verify_ssl = False
                    else:
                        cfg.verify_ssl = False
                    client.Configuration.set_default(cfg)
                    loaded = True
                    log.info("K8s auth: token-based (%s)", endpoint)
        if not loaded:
            log.warning("k8s config load failed, using mock")
            return False
        try:
            self._apps = client.AppsV1Api()
            self._core = client.CoreV1Api()
            from .k8s_commands import CommandHandler
            from .k8s_injectors import FailureInjector
            self._commands = CommandHandler(self._core, self._apps)
            self._injector = FailureInjector(self._core, self._apps)
            return True
        except Exception as e:
            log.warning("k8s API init failed, using mock: %s", e)
            return False

    def _mock(self, text: str) -> K8sActionResult:
        return K8sActionResult(True, f"[MOCK] {text}", False)
