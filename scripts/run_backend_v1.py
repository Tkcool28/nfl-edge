#!/usr/bin/env python3
"""Run the NFL EDGE backend V1 from environment-backed settings."""
from __future__ import annotations

import uvicorn

from nfl_edge.backend.settings import BackendSettings


def main() -> int:
    settings = BackendSettings.from_env()
    uvicorn.run(
        "nfl_edge.backend.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        proxy_headers=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())