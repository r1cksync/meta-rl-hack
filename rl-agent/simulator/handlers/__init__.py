"""Handlers package — one file per AWS service that we model bespokely.

Every module exposes `handle(spec: dict, params: dict, state: SimState) -> ActionResult`.
`spec` is the action catalog entry, `params` is the agent-supplied dict.
"""
