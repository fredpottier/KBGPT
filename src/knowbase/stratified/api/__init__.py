"""
OSMOSE Pipeline V2 - API
=========================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

API REST pour Pipeline V2.

Usage:
    from knowbase.stratified.api import router

    app.include_router(router)
"""

from knowbase.stratified.api.router import router

__all__ = ["router"]
