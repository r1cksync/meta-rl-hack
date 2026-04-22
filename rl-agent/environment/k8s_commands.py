"""kubectl command dispatcher for IncidentCommander's real-K8s backend.

Mirrors kube-sre-gym's :class:`CommandHandler` — parses a kubectl-style command
string, routes the verb to a typed handler, and returns kubectl-formatted text
output. No subprocess calls; everything goes through the official `kubernetes`
Python client, so it works identically against kind, minikube, GKE, EKS, etc.

Supported verbs: get, describe, logs, rollout, set, scale, delete, patch, top, events.
"""

from __future__ import annotations

import logging
import shlex
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _format_age(ts) -> str:
    if ts is None:
        return "?"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return "?"
    delta = datetime.now(timezone.utc) - ts
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _pod_status(p) -> str:
    # Mirror kubectl's STATUS column logic.
    if p.metadata.deletion_timestamp:
        return "Terminating"
    phase = p.status.phase or "Unknown"
    for cs in (p.status.container_statuses or []):
        ws = cs.state and cs.state.waiting
        if ws and ws.reason:
            return ws.reason  # CrashLoopBackOff, ImagePullBackOff, ContainerCreating, ...
        ts = cs.state and cs.state.terminated
        if ts and ts.reason and ts.reason not in ("Completed",):
            return ts.reason  # OOMKilled, Error
    return phase


def _tabulate(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "No resources found."
    widths = [max(len(h), max((len(r[i]) for r in rows), default=0)) for i, h in enumerate(headers)]
    def _fmt(row):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))
    return "\n".join([_fmt(headers), *[_fmt(r) for r in rows]])


class CommandHandler:
    """Executes a parsed kubectl verb against a live cluster via Kubernetes API."""

    def __init__(self, core_v1, apps_v1, networking_v1=None):
        self.v1 = core_v1
        self.apps_v1 = apps_v1
        self.networking_v1 = networking_v1

    # ---- entry point --------------------------------------------------

    def run(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return f"error: {e}"
        if not parts:
            return "error: empty command"
        if parts[0] == "kubectl":
            parts = parts[1:]
        if not parts:
            return "error: empty command"
        verb = parts[0]
        rest = parts[1:]
        ns = self._ns(rest)
        rest = self._strip_ns(rest)
        try:
            table = {
                "get": self._get, "describe": self._describe, "logs": self._logs,
                "rollout": self._rollout, "set": self._set, "scale": self._scale,
                "delete": self._delete, "patch": self._patch, "top": self._top,
                "events": self._events,
            }
            handler = table.get(verb)
            if not handler:
                return f"error: unknown verb '{verb}'"
            return handler(rest, ns)
        except Exception as e:
            log.exception("kubectl dispatch failed")
            return f"error: {e}"

    # ---- parsers ------------------------------------------------------

    def _ns(self, parts: list[str]) -> str | None:
        for i, p in enumerate(parts):
            if p == "-n" and i + 1 < len(parts):
                return parts[i + 1]
            if p.startswith("--namespace="):
                return p.split("=", 1)[1]
        if "-A" in parts or "--all-namespaces" in parts:
            return "__all__"
        return None

    def _strip_ns(self, parts: list[str]) -> list[str]:
        out = []
        skip = False
        for p in parts:
            if skip:
                skip = False
                continue
            if p == "-n":
                skip = True
                continue
            if p.startswith("--namespace=") or p in ("-A", "--all-namespaces"):
                continue
            out.append(p)
        return out

    def _flag(self, parts: list[str], key: str) -> str | None:
        prefix = f"{key}="
        for p in parts:
            if p.startswith(prefix):
                return p.split("=", 1)[1]
        return None

    def _split_res(self, token: str) -> tuple[str, str | None]:
        if "/" in token:
            return tuple(token.split("/", 1))  # type: ignore[return-value]
        return token, None

    # ---- get ----------------------------------------------------------

    def _get(self, parts: list[str], ns: str | None) -> str:
        if not parts:
            return "error: resource type required"
        kind = parts[0]
        aliases = {
            "po": "pods", "pod": "pods", "pods": "pods",
            "deploy": "deployments", "deployment": "deployments", "deployments": "deployments",
            "svc": "services", "service": "services", "services": "services",
            "ev": "events", "events": "events",
            "ns": "namespaces", "namespace": "namespaces", "namespaces": "namespaces",
            "rs": "replicasets", "replicaset": "replicasets", "replicasets": "replicasets",
            "cm": "configmaps", "configmap": "configmaps", "configmaps": "configmaps",
            "secret": "secrets", "secrets": "secrets",
        }
        kind_norm = aliases.get(kind, kind)
        fn = {
            "pods": self._get_pods, "deployments": self._get_deploys, "services": self._get_svcs,
            "events": self._get_events, "namespaces": self._get_namespaces,
            "replicasets": self._get_replicasets, "configmaps": self._get_configmaps,
            "secrets": self._get_secrets,
        }.get(kind_norm)
        if not fn:
            return f"error: unsupported resource '{kind}'"
        return fn(ns)

    def _get_pods(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.v1.list_pod_for_all_namespaces().items
            show_ns = True
        else:
            items = self.v1.list_namespaced_pod(ns).items
            show_ns = False
        rows = []
        for p in items:
            total = len(p.spec.containers)
            ready = sum(1 for cs in (p.status.container_statuses or []) if cs.ready)
            restarts = sum(cs.restart_count or 0 for cs in (p.status.container_statuses or []))
            row = [p.metadata.namespace] if show_ns else []
            row += [p.metadata.name, f"{ready}/{total}", _pod_status(p), str(restarts),
                    _format_age(p.metadata.creation_timestamp)]
            rows.append(row)
        headers = (["NAMESPACE"] if show_ns else []) + ["NAME", "READY", "STATUS", "RESTARTS", "AGE"]
        return _tabulate(headers, rows)

    def _get_deploys(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.apps_v1.list_deployment_for_all_namespaces().items
            show_ns = True
        else:
            items = self.apps_v1.list_namespaced_deployment(ns).items
            show_ns = False
        rows = []
        for d in items:
            row = [d.metadata.namespace] if show_ns else []
            row += [d.metadata.name, f"{d.status.ready_replicas or 0}/{d.spec.replicas or 0}",
                    str(d.status.updated_replicas or 0), str(d.status.available_replicas or 0),
                    _format_age(d.metadata.creation_timestamp)]
            rows.append(row)
        headers = (["NAMESPACE"] if show_ns else []) + ["NAME", "READY", "UP-TO-DATE", "AVAILABLE", "AGE"]
        return _tabulate(headers, rows)

    def _get_svcs(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.v1.list_service_for_all_namespaces().items
            show_ns = True
        else:
            items = self.v1.list_namespaced_service(ns).items
            show_ns = False
        rows = []
        for s in items:
            ports = ",".join(f"{p.port}/{p.protocol}" for p in (s.spec.ports or []))
            row = [s.metadata.namespace] if show_ns else []
            row += [s.metadata.name, s.spec.type or "ClusterIP", s.spec.cluster_ip or "-", ports]
            rows.append(row)
        headers = (["NAMESPACE"] if show_ns else []) + ["NAME", "TYPE", "CLUSTER-IP", "PORTS"]
        return _tabulate(headers, rows)

    def _get_events(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.v1.list_event_for_all_namespaces(limit=50).items
            show_ns = True
        else:
            items = self.v1.list_namespaced_event(ns, limit=50).items
            show_ns = False
        rows = []
        for e in items[-50:]:
            row = [e.metadata.namespace] if show_ns else []
            involved = e.involved_object.kind + "/" + (e.involved_object.name or "") if e.involved_object else ""
            row += [_format_age(e.last_timestamp or e.event_time or e.metadata.creation_timestamp),
                    e.type or "-", e.reason or "-", involved, (e.message or "")[:80]]
            rows.append(row)
        headers = (["NAMESPACE"] if show_ns else []) + ["LAST", "TYPE", "REASON", "OBJECT", "MESSAGE"]
        return _tabulate(headers, rows)

    def _get_namespaces(self, ns: str | None) -> str:
        items = self.v1.list_namespace().items
        rows = [[n.metadata.name, n.status.phase or "Active",
                 _format_age(n.metadata.creation_timestamp)] for n in items]
        return _tabulate(["NAME", "STATUS", "AGE"], rows)

    def _get_replicasets(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.apps_v1.list_replica_set_for_all_namespaces().items
            show_ns = True
        else:
            items = self.apps_v1.list_namespaced_replica_set(ns).items
            show_ns = False
        rows = []
        for r in items:
            row = [r.metadata.namespace] if show_ns else []
            row += [r.metadata.name, str(r.spec.replicas or 0),
                    str(r.status.ready_replicas or 0),
                    _format_age(r.metadata.creation_timestamp)]
            rows.append(row)
        headers = (["NAMESPACE"] if show_ns else []) + ["NAME", "DESIRED", "READY", "AGE"]
        return _tabulate(headers, rows)

    def _get_configmaps(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.v1.list_config_map_for_all_namespaces().items
            show_ns = True
        else:
            items = self.v1.list_namespaced_config_map(ns).items
            show_ns = False
        rows = []
        for c in items:
            row = [c.metadata.namespace] if show_ns else []
            row += [c.metadata.name, str(len(c.data or {})),
                    _format_age(c.metadata.creation_timestamp)]
            rows.append(row)
        return _tabulate((["NAMESPACE"] if show_ns else []) + ["NAME", "DATA", "AGE"], rows)

    def _get_secrets(self, ns: str | None) -> str:
        if ns in (None, "__all__"):
            items = self.v1.list_secret_for_all_namespaces().items
            show_ns = True
        else:
            items = self.v1.list_namespaced_secret(ns).items
            show_ns = False
        rows = []
        for s in items:
            row = [s.metadata.namespace] if show_ns else []
            row += [s.metadata.name, s.type or "-", str(len(s.data or {})),
                    _format_age(s.metadata.creation_timestamp)]
            rows.append(row)
        return _tabulate((["NAMESPACE"] if show_ns else []) + ["NAME", "TYPE", "DATA", "AGE"], rows)

    # ---- describe / logs / events ------------------------------------

    def _describe(self, parts: list[str], ns: str | None) -> str:
        if len(parts) < 2:
            return "error: describe <kind> <name>"
        kind, name = parts[0], parts[1]
        kind_l = kind.lower().rstrip("s")
        ns = ns or "default"
        try:
            if kind_l in ("pod", "po"):
                p = self.v1.read_namespaced_pod(name, ns)
                lines = [f"Name: {p.metadata.name}", f"Namespace: {p.metadata.namespace}",
                         f"Node: {p.spec.node_name}", f"Status: {_pod_status(p)}",
                         f"IP: {p.status.pod_ip}", "Containers:"]
                for c in p.spec.containers:
                    lines.append(f"  - {c.name}: image={c.image}")
                    if c.resources and c.resources.limits:
                        lines.append(f"    limits: {dict(c.resources.limits)}")
                for cs in (p.status.container_statuses or []):
                    state = list(cs.state.to_dict().items())[0] if cs.state else ("-", {})
                    lines.append(f"  state[{cs.name}]: {state[0]} {state[1] or ''}")
                    if cs.last_state and cs.last_state.terminated:
                        t = cs.last_state.terminated
                        lines.append(f"  last_terminated[{cs.name}]: reason={t.reason} exit={t.exit_code}")
                return "\n".join(lines)
            if kind_l in ("deploy", "deployment"):
                d = self.apps_v1.read_namespaced_deployment(name, ns)
                c0 = d.spec.template.spec.containers[0]
                env = {e.name: e.value for e in (c0.env or [])}
                return (f"Name: {d.metadata.name}\nNamespace: {d.metadata.namespace}\n"
                        f"Replicas: {d.status.ready_replicas or 0}/{d.spec.replicas}\n"
                        f"Image: {c0.image}\nEnv: {env}\n"
                        f"Limits: {dict(c0.resources.limits) if c0.resources and c0.resources.limits else {}}")
            return f"error: describe not implemented for {kind}"
        except Exception as e:
            return f"error: {e}"

    def _logs(self, parts: list[str], ns: str | None) -> str:
        if not parts:
            return "error: logs <pod> [-c container]"
        pod = parts[0]
        container = None
        for i, p in enumerate(parts):
            if p in ("-c", "--container") and i + 1 < len(parts):
                container = parts[i + 1]
        tail = 40
        for p in parts:
            if p.startswith("--tail="):
                try: tail = int(p.split("=", 1)[1])
                except ValueError: pass
        ns = ns or "default"
        try:
            return self.v1.read_namespaced_pod_log(pod, ns, container=container,
                                                   tail_lines=tail, _preload_content=True) or "(empty)"
        except Exception as e:
            return f"error: {e}"

    def _events(self, parts: list[str], ns: str | None) -> str:
        return self._get_events(ns)

    def _top(self, parts: list[str], ns: str | None) -> str:
        # Metrics server may not be installed on kind — best effort.
        return "error: top requires metrics-server; use `kubectl describe` for resource usage."

    # ---- rollout / set / scale / delete / patch ----------------------

    def _rollout(self, parts: list[str], ns: str | None) -> str:
        if len(parts) < 2:
            return "error: rollout <verb> <deployment/NAME>"
        sub = parts[0]
        kind, name = self._split_res(parts[1])
        if kind not in ("deployment", "deploy"):
            return f"error: rollout supports deployment only, got {kind}"
        ns = ns or "default"
        try:
            if sub == "restart":
                from kubernetes.client import V1ObjectMeta  # type: ignore
                body = {"spec": {"template": {"metadata": {"annotations": {
                    "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                }}}}}
                self.apps_v1.patch_namespaced_deployment(name, ns, body)
                return f"deployment.apps/{name} restarted"
            if sub == "undo":
                # Roll back to previous revision by listing RS and switching.
                rss = self.apps_v1.list_namespaced_replica_set(
                    ns, label_selector=f"app={name}").items
                rss.sort(key=lambda r: int((r.metadata.annotations or {})
                                           .get("deployment.kubernetes.io/revision", "0")))
                if len(rss) < 2:
                    # Fall back to rollout restart so the episode can still recover.
                    return self._rollout(["restart", f"deployment/{name}"], ns)
                prev = rss[-2]
                d = self.apps_v1.read_namespaced_deployment(name, ns)
                d.spec.template = prev.spec.template
                self.apps_v1.replace_namespaced_deployment(name, ns, d)
                return f"deployment.apps/{name} rolled back"
            if sub == "status":
                d = self.apps_v1.read_namespaced_deployment(name, ns)
                return f"deployment.apps/{name} ready {d.status.ready_replicas or 0}/{d.spec.replicas}"
            return f"error: rollout {sub} not supported"
        except Exception as e:
            return f"error: {e}"

    def _set(self, parts: list[str], ns: str | None) -> str:
        if not parts:
            return "error: set <resources|image|env>"
        sub = parts[0]
        rest = parts[1:]
        ns = ns or "default"
        if not rest:
            return "error: missing resource target"
        kind, name = self._split_res(rest[0])
        if kind not in ("deployment", "deploy"):
            return f"error: set only supports deployment, got {kind}"
        args = rest[1:]
        try:
            d = self.apps_v1.read_namespaced_deployment(name, ns)
            cname_filter = None
            for i, a in enumerate(args):
                if a == "-c" and i + 1 < len(args):
                    cname_filter = args[i + 1]
            containers = [c for c in d.spec.template.spec.containers
                          if cname_filter is None or c.name == cname_filter]
            if not containers:
                return f"error: no container matches {cname_filter}"

            if sub == "resources":
                mem = self._flag(args, "--limits")
                # kubectl syntax: --limits=memory=128Mi,cpu=200m
                if mem:
                    parsed = dict(kv.split("=", 1) for kv in mem.split(","))
                    from kubernetes.client import V1ResourceRequirements  # type: ignore
                    for c in containers:
                        if not c.resources:
                            c.resources = V1ResourceRequirements()
                        c.resources.limits = {**(c.resources.limits or {}), **parsed}
                self.apps_v1.replace_namespaced_deployment(name, ns, d)
                return f"deployment.apps/{name} resources set"

            if sub == "image":
                # kubectl set image deployment/foo container=image
                for a in args:
                    if "=" in a and not a.startswith("-"):
                        cname, img = a.split("=", 1)
                        for c in containers:
                            if c.name == cname or cname_filter is None:
                                c.image = img
                self.apps_v1.replace_namespaced_deployment(name, ns, d)
                return f"deployment.apps/{name} image set"

            if sub == "env":
                from kubernetes.client import V1EnvVar  # type: ignore
                updates = {}
                for a in args:
                    if "=" in a and not a.startswith("-"):
                        k, v = a.split("=", 1)
                        updates[k] = v
                for c in containers:
                    env_map = {e.name: e.value for e in (c.env or [])}
                    env_map.update(updates)
                    c.env = [V1EnvVar(name=k, value=str(v)) for k, v in env_map.items()]
                self.apps_v1.replace_namespaced_deployment(name, ns, d)
                return f"deployment.apps/{name} env updated"

            return f"error: set {sub} not supported"
        except Exception as e:
            return f"error: {e}"

    def _scale(self, parts: list[str], ns: str | None) -> str:
        if not parts:
            return "error: scale deployment/NAME --replicas=N"
        kind, name = self._split_res(parts[0])
        if kind not in ("deployment", "deploy"):
            return f"error: scale only supports deployment, got {kind}"
        replicas = self._flag(parts, "--replicas")
        if replicas is None:
            return "error: --replicas=N required"
        ns = ns or "default"
        try:
            self.apps_v1.patch_namespaced_deployment_scale(
                name, ns, {"spec": {"replicas": int(replicas)}})
            return f"deployment.apps/{name} scaled to {replicas}"
        except Exception as e:
            return f"error: {e}"

    def _delete(self, parts: list[str], ns: str | None) -> str:
        if len(parts) < 2:
            return "error: delete <kind> <name>"
        kind, name = parts[0].lower().rstrip("s"), parts[1]
        ns = ns or "default"
        try:
            if kind in ("pod", "po"):
                self.v1.delete_namespaced_pod(name, ns)
                return f"pod \"{name}\" deleted"
            if kind in ("resourcequota", "quota"):
                self.v1.delete_namespaced_resource_quota(name, ns)
                return f"resourcequota \"{name}\" deleted"
            return f"error: delete not supported for {kind}"
        except Exception as e:
            return f"error: {e}"

    def _patch(self, parts: list[str], ns: str | None) -> str:
        # Minimal patch: only --patch='{...}' JSON patches for deployments
        if len(parts) < 2:
            return "error: patch deployment/NAME -p '<json>'"
        kind, name = self._split_res(parts[0])
        if kind not in ("deployment", "deploy"):
            return f"error: patch only supports deployment, got {kind}"
        patch_body = None
        for i, p in enumerate(parts):
            if p in ("-p", "--patch") and i + 1 < len(parts):
                patch_body = parts[i + 1]
            elif p.startswith("--patch="):
                patch_body = p.split("=", 1)[1]
        if not patch_body:
            return "error: missing -p '<json>'"
        ns = ns or "default"
        try:
            import json
            body = json.loads(patch_body)
            self.apps_v1.patch_namespaced_deployment(name, ns, body)
            return f"deployment.apps/{name} patched"
        except Exception as e:
            return f"error: {e}"
