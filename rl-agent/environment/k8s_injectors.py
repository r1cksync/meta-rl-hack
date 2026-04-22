"""Real fault injectors — modify live K8s deployments to create realistic incidents.

Each method mutates a Deployment through the Kubernetes Python client so that the
cluster's actual reconciler produces the failure (OOMKilled, ImagePullBackOff,
CrashLoopBackOff, ...). That real cluster state is what the agent then investigates
via the `exec_kubectl` action.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .k8s_constants import FAULT_DEFAULT_TARGETS, HEALTHY_STATE, INJECT_WAIT_DEFAULT, SUPPORTED_FAULTS

log = logging.getLogger(__name__)


@dataclass
class InjectionResult:
    ok: bool
    fault_type: str
    namespace: str
    deployment: str
    message: str


class FailureInjector:
    """Inject failures into a live K8s cluster via the Apps/Core V1 APIs."""

    def __init__(self, core_v1, apps_v1):
        self.v1 = core_v1
        self.apps_v1 = apps_v1

    # ---- public entry point ------------------------------------------

    def inject(self, fault_type: str, namespace: str | None = None,
               deployment: str | None = None) -> InjectionResult:
        if fault_type not in SUPPORTED_FAULTS:
            return InjectionResult(False, fault_type, namespace or "-", deployment or "-",
                                   f"unknown fault type: {fault_type}")
        if not namespace or not deployment:
            ns_d = FAULT_DEFAULT_TARGETS.get(fault_type)
            if ns_d:
                namespace = namespace or ns_d[0]
                deployment = deployment or ns_d[1]
        if not namespace or not deployment:
            return InjectionResult(False, fault_type, namespace or "-", deployment or "-",
                                   "namespace/deployment not provided and no default")
        method = getattr(self, f"_inject_{fault_type}", None)
        if not method:
            return InjectionResult(False, fault_type, namespace, deployment,
                                   f"no injector impl for {fault_type}")
        try:
            msg = method(namespace, deployment)
            time.sleep(INJECT_WAIT_DEFAULT)
            return InjectionResult(True, fault_type, namespace, deployment, msg)
        except Exception as e:
            log.exception("injection failed")
            return InjectionResult(False, fault_type, namespace, deployment, f"error: {e}")

    # ---- individual faults -------------------------------------------

    def _inject_oom_kill(self, ns: str, deploy: str) -> str:
        from kubernetes.client import V1ResourceRequirements  # type: ignore
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        for c in d.spec.template.spec.containers:
            if not c.resources:
                c.resources = V1ResourceRequirements()
            c.resources.limits = {**(c.resources.limits or {}), "memory": "4Mi"}
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"set memory limit=4Mi on {ns}/{deploy} → expect OOMKilled"

    def _inject_crashloop(self, ns: str, deploy: str) -> str:
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        c = d.spec.template.spec.containers[0]
        c.command = ["sh", "-c", "exit 1"]
        c.args = []
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"overrode command on {ns}/{deploy} → expect CrashLoopBackOff"

    def _inject_image_pull(self, ns: str, deploy: str) -> str:
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        d.spec.template.spec.containers[0].image = "nginx:this-tag-definitely-does-not-exist-99999"
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"set non-existent image on {ns}/{deploy} → expect ImagePullBackOff"

    def _inject_bad_config(self, ns: str, deploy: str) -> str:
        from kubernetes.client import V1EnvVar  # type: ignore
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        for c in d.spec.template.spec.containers:
            env_map = {e.name: e.value for e in (c.env or [])}
            # Point DATABASE_URL (or REDIS_HOST) at an unresolvable host.
            if "DATABASE_URL" in env_map:
                env_map["DATABASE_URL"] = "postgres://wrong-host.invalid.local:5432/payments"
            elif "REDIS_HOST" in env_map:
                env_map["REDIS_HOST"] = "wrong-host.invalid.local"
            else:
                env_map["DATABASE_URL"] = "postgres://wrong-host.invalid.local:5432/payments"
            c.env = [V1EnvVar(name=k, value=str(v)) for k, v in env_map.items()]
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"corrupted env vars on {ns}/{deploy} → expect app-level connection errors"

    def _inject_scale_zero(self, ns: str, deploy: str) -> str:
        self.apps_v1.patch_namespaced_deployment_scale(deploy, ns, {"spec": {"replicas": 0}})
        return f"scaled {ns}/{deploy} to 0 replicas → no pods running"

    def _inject_liveness_probe(self, ns: str, deploy: str) -> str:
        from kubernetes.client import V1Probe, V1HTTPGetAction  # type: ignore
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        for c in d.spec.template.spec.containers:
            c.liveness_probe = V1Probe(
                http_get=V1HTTPGetAction(path="/nonexistent-probe", port=8080),
                initial_delay_seconds=3, period_seconds=5, failure_threshold=2,
            )
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"broke liveness probe on {ns}/{deploy} → expect probe failures + restarts"

    def _inject_resource_quota(self, ns: str, _deploy: str) -> str:
        from kubernetes.client import V1ResourceQuota, V1ResourceQuotaSpec, V1ObjectMeta  # type: ignore
        from kubernetes.client.rest import ApiException  # type: ignore
        quota = V1ResourceQuota(
            metadata=V1ObjectMeta(name="ic-tight-quota", namespace=ns),
            spec=V1ResourceQuotaSpec(hard={"pods": "1", "requests.memory": "64Mi"}),
        )
        try:
            self.v1.create_namespaced_resource_quota(ns, quota)
        except ApiException as e:
            if e.status == 409:
                self.v1.replace_namespaced_resource_quota("ic-tight-quota", ns, quota)
            else:
                raise
        return f"created tight ResourceQuota in {ns} → new pods will be blocked"

    def _inject_secret_mismatch(self, ns: str, deploy: str) -> str:
        from kubernetes.client import V1EnvVar  # type: ignore
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        for c in d.spec.template.spec.containers:
            env_map = {e.name: e.value for e in (c.env or [])}
            env_map["JWT_SECRET"] = "rotated-but-not-propagated"
            c.env = [V1EnvVar(name=k, value=str(v)) for k, v in env_map.items()]
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"rotated JWT_SECRET on {ns}/{deploy} without cascading → signature verification will fail"

    def _inject_wrong_image_tag(self, ns: str, deploy: str) -> str:
        d = self.apps_v1.read_namespaced_deployment(deploy, ns)
        # Valid registry, wrong tag — pulls successfully but runs buggy "old" app version.
        d.spec.template.spec.containers[0].image = "nginxinc/nginx-unprivileged:1.19-alpine"
        self.apps_v1.replace_namespaced_deployment(deploy, ns, d)
        return f"rolled out older image on {ns}/{deploy} → silent regression"

    # ---- reset -------------------------------------------------------

    def reset_to_healthy(self) -> list[str]:
        """Patch all tracked deployments back to HEALTHY_STATE. Returns log lines."""
        from kubernetes.client import (  # type: ignore
            V1EnvVar, V1Probe, V1HTTPGetAction, V1ResourceRequirements,
        )
        from kubernetes.client.rest import ApiException  # type: ignore
        logs: list[str] = []
        for ns, deploys in HEALTHY_STATE.items():
            for deploy_name, spec in deploys.items():
                try:
                    d = self.apps_v1.read_namespaced_deployment(deploy_name, ns)
                except ApiException as e:
                    logs.append(f"[skip] {ns}/{deploy_name}: {e.reason}")
                    continue
                for c in d.spec.template.spec.containers:
                    c.image = spec["image"]
                    if not c.resources:
                        c.resources = V1ResourceRequirements()
                    c.resources.limits = {"memory": spec["memory_limit"]}
                    c.env = [V1EnvVar(name=k, value=v) for k, v in spec["env"].items()]
                    probe = spec.get("liveness_probe")
                    if probe:
                        c.liveness_probe = V1Probe(
                            http_get=V1HTTPGetAction(path=probe["path"], port=probe["port"]),
                            initial_delay_seconds=5, period_seconds=10,
                        )
                    else:
                        c.liveness_probe = None
                    # Clear any injected command/args so sample-app defaults apply.
                    if spec.get("container_name") == c.name:
                        c.command = None
                        c.args = None
                d.spec.replicas = spec["replicas"]
                try:
                    self.apps_v1.replace_namespaced_deployment(deploy_name, ns, d)
                    logs.append(f"[ok] reset {ns}/{deploy_name}")
                except ApiException as e:
                    logs.append(f"[err] {ns}/{deploy_name}: {e.reason}")

            # Clean up injected quotas + stuck pods.
            try:
                for q in self.v1.list_namespaced_resource_quota(ns).items:
                    if q.metadata.name == "ic-tight-quota":
                        self.v1.delete_namespaced_resource_quota(q.metadata.name, ns)
                        logs.append(f"[ok] removed quota {q.metadata.name} in {ns}")
            except ApiException:
                pass
            try:
                for p in self.v1.list_namespaced_pod(ns).items:
                    phase = (p.status.phase or "")
                    if phase not in ("Running", "Succeeded", "Pending"):
                        self.v1.delete_namespaced_pod(p.metadata.name, ns)
            except ApiException:
                pass
        return logs
