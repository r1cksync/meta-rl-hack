"""IncidentCommander — OpenEnv server entrypoint.

Provides the `main()` function required for multi-mode (pip install) deployment.
When running via Docker, the Dockerfile starts uvicorn directly against server:app.
"""

from __future__ import annotations

import os
import sys

# Ensure rl-agent is on the path when run outside Docker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rl-agent"))

import uvicorn


def main() -> None:
    """Start the IncidentCommander OpenEnv HTTP server."""
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
