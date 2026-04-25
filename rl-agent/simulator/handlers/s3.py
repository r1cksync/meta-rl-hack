"""S3 handler — buckets, objects, policies."""

from __future__ import annotations

from ..state import ActionResult, SimState
from . import generic


def handle(spec: dict, params: dict, state: SimState) -> ActionResult:
    verb = spec["verb"]
    name = params.get("resource_id") or params.get("name") \
        or params.get("bucket")

    if verb == "create":
        nm = params.get("name") or name
        state.s3[nm] = {"name": nm, "objects": {}, "policy": None,
                        "versioning": False, "encryption": None}
        return ActionResult(ok=True, payload={"bucket": nm},
                            tags=["s3.create"])
    if verb in ("describe", "head", "get", "get_status"):
        b = state.s3.get(name) if name else None
        if b is None:
            return ActionResult(ok=False, error="NoSuchBucket",
                                error_message=f"bucket {name} not found",
                                tags=["s3.describe"])
        return ActionResult(ok=True,
                            payload={"name": name,
                                     "objects": len(b["objects"]),
                                     "encryption": b["encryption"],
                                     "versioning": b["versioning"]},
                            tags=["s3.describe"])
    if verb == "get_policy":
        b = state.s3.get(name) if name else None
        if b is None:
            return ActionResult(ok=False, error="NoSuchBucket",
                                error_message=f"bucket {name} not found",
                                tags=["s3.get_policy"])
        return ActionResult(ok=True, payload={"policy": b.get("policy")},
                            tags=["s3.get_policy", "resource_policy"])
    if verb == "put_policy":
        b = state.s3.get(name) if name else None
        if b is None:
            return ActionResult(ok=False, error="NoSuchBucket",
                                error_message=f"bucket {name} not found",
                                tags=["s3.put_policy"])
        b["policy"] = params.get("policy")
        state.emit_cloudtrail("PutBucketPolicy", resources=[name])
        state.mitigation_applied = True
        return ActionResult(ok=True, payload={"bucket": name},
                            tags=["s3.put_policy", "remediation"])
    if verb == "delete_policy":
        b = state.s3.get(name) if name else None
        if b is None:
            return ActionResult(ok=False, error="NoSuchBucket",
                                error_message=f"bucket {name} not found",
                                tags=["s3.delete_policy"])
        b["policy"] = None
        return ActionResult(ok=True, payload={"bucket": name},
                            tags=["s3.delete_policy"])
    return generic.handle(spec, params, state)
