"""OpenEnv HTTP Server — exposes step/reset/state as a FastAPI app.

This is the entry point for the Hugging Face Space deployment.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from environment.env import IncidentCommanderEnv
from environment.models import Action, ActionType, Observation, StepResult


@asynccontextmanager
async def lifespan(app: FastAPI):
    mock_val = os.getenv("MOCK_MODE", os.getenv("INCIDENT_COMMANDER_MOCK", "true"))
    app.state.env = IncidentCommanderEnv(use_mock=mock_val.lower() == "true")
    yield


app = FastAPI(
    title="IncidentCommander — OpenEnv",
    description="SRE incident response RL environment",
    version="1.0.0",
    lifespan=lifespan,
)


class ResetRequest(BaseModel):
    task_id: str = "task1"


class StepRequest(BaseModel):
    action_type: str
    params: dict = {}


@app.post("/reset")
def reset(req: Optional[ResetRequest] = Body(default=None)) -> dict:
    env: IncidentCommanderEnv = app.state.env
    task_id = req.task_id if req is not None else "task1"
    try:
        obs = env.reset(task_id)
        return obs.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/step")
def step(req: Optional[StepRequest] = Body(default=None)) -> dict:
    env: IncidentCommanderEnv = app.state.env
    if req is None:
        raise HTTPException(status_code=400, detail="action_type is required")
    try:
        action = Action(type=ActionType(req.action_type), params=req.params)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid action type: {req.action_type}")
    try:
        result = env.step(action)
        return result.model_dump(mode="json")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/state")
def state() -> dict:
    env: IncidentCommanderEnv = app.state.env
    return env.state()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {
        "name": "incident-commander",
        "version": "1.0.0",
        "endpoints": ["/reset", "/step", "/state", "/health"],
    }
