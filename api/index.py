"""Vercel entrypoint — exposes the Sharp Slate FastAPI app as an ASGI function.

Static frontend files are served directly by Vercel (see vercel.json), so
this only needs to handle /api/* routes.
"""
from backend.main import app

__all__ = ["app"]
