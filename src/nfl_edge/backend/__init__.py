"""NFL EDGE persistent backend V1."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .settings import BackendSettings

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(settings: BackendSettings | None = None) -> "FastAPI":
    """Lazily import the FastAPI assembly so bounded utilities avoid model imports."""
    from .app import create_app as build_app

    return build_app(settings)


__all__ = ["BackendSettings", "create_app"]
