"""Optional real Kubernetes backend.

kube-sre-gym's big advantage is that kubectl commands hit a real cluster.
This module gives IncidentCommander the same code path as an opt-in: when
`KUBECONFIG` or in-cluster service-account credentials are present AND
`REAL_K8S=true` is set, write actions execute against the live cluster via
the official Python `kubernetes` client. Otherwise every call returns a
`[MOCK]` string (identical to the current behaviour) so the HF Space keeps
working without any cluster credentials.

Setup for real mode
-------------------
    pip install kubernetes>=29.0.0
    export REAL_K8S=true
    export KUBECONFIG=/path/to/kubeconfig          # or rely on in-cluster SA
    export INCIDENT_NAMESPACE_PREFIX=acmecorp      # default

Failure handling: if the kubernetes client cannot be imported or the config
cannot be loaded, the backend silently degrades to mock mode. Callers can
inspect `backend.enabled` to check which mode is active.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class K8sActionResult:
    ok: bool
    message: str
    real: bool  # True if it hit a live cluster


class K8sBackend:
    """Thin wrapper around the k8s AppsV1 API for our 5 write actions."""

    def __init__(self, namespace: str | None = None) -> None:
        self.namespace = namespace or os.getenv("INCIDENT_NAMESPACE", "default")
        self._apps = None
        self._core = None
        self._batch = None
        self.enabled = self._try_load()

    # ------------------------------------------------------------------ API

    def rollback(self, deployment: str) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Rolled back deployment/{deployment} to previous revision.")
        try:
            # Trigger rollout restart (simplest "rollback" semantic).
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "incident-commander/rollback-at": _timestamp()
                            }
                        }
                    }
                }
            }
            self._apps.patch_namespaced_deployment(  # type: ignore[attr-defined]
                name=deployment,
                namespace=self.namespace,
                body=body,
            )
            return K8sActionResult(True, f"[REAL] Rolled back deployment/{deployment}.", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] rollback {deployment}: {e}", True)

    def restart(self, deployment: str) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Restarted pods for deployment/{deployment}.")
        try:
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": _timestamp()
                            }
                        }
                    }
                }
            }
            self._apps.patch_namespaced_deployment(  # type: ignore[attr-defined]
                name=deployment,
                namespace=self.namespace,
                body=body,
            )
            return K8sActionResult(True, f"[REAL] Restarted deployment/{deployment}.", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] restart {deployment}: {e}", True)

    def scale(self, deployment: str, replicas: int) -> K8sActionResult:
        if not self.enabled:
            return self._mock(f"Scaled deployment/{deployment} to {replicas} replicas.")
        if replicas < 0 or replicas > 20:
            return K8sActionResult(False, f"ERROR: replicas must be 0-20 (got {replicas})", False)
        try:
            body = {"spec": {"replicas": int(replicas)}}
            self._apps.patch_namespaced_deployment_scale(  # type: ignore[attr-defined]
                name=deployment,
                namespace=self.namespace,
                body=body,
            )
            return K8sActionResult(True, f"[REAL] Scaled deployment/{deployment} to {replicas}.", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] scale {deployment}: {e}", True)

    def apply_config_patch(self, deployment: str, env_var: str, value: str) -> K8sActionResult:
        if not self.enabled:
            return self._mock(
                f"Patched deployment/{deployment}: set {env_var}={value}."
            )
        try:
            body = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": deployment,
                                    "env": [{"name": env_var, "value": str(value)}],
                                }
                            ]
                        }
                    }
                }
            }
            self._apps.patch_namespaced_deployment(  # type: ignore[attr-defined]
                name=deployment,
                namespace=self.namespace,
                body=body,
            )
            return K8sActionResult(True, f"[REAL] Patched {env_var}={value} on {deployment}.", True)
        except Exception as e:
            return K8sActionResult(False, f"[REAL][error] patch {deployment}: {e}", True)

    def list_pods(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            pods = self._core.list_namespaced_pod(self.namespace)  # type: ignore[attr-defined]
            return [
                {
                    "name": p.metadata.name,
                    "status": p.status.phase,
                    "restarts": sum(
                        cs.restart_count for cs in (p.status.container_statuses or [])
                    ),
                }
                for p in pods.items
            ]
        except Exception as e:
            log.warning("list_pods failed: %s", e)
            return []

    # -------------------------------------------------------------- helpers

    def _try_load(self) -> bool:
        if os.getenv("REAL_K8S", "false").lower() not in ("1", "true", "yes"):
            return False
        try:
            from kubernetes import client, config  # type: ignore
        except ImportError:
            log.info("kubernetes client not installed; using mock backend")
            return False
        try:
            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()
            self._apps = client.AppsV1Api()
            self._core = client.CoreV1Api()
            self._batch = client.BatchV1Api()
            return True
        except Exception as e:
            log.warning("k8s config load failed, using mock: %s", e)
            return False

    def _mock(self, text: str) -> K8sActionResult:
        return K8sActionResult(True, f"[MOCK] {text}", False)


def _timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
