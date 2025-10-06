"""
FastAPI dependencies pour authentification, autorisation, et configuration.
"""

from .auth import require_admin, get_tenant_id

__all__ = ["require_admin", "get_tenant_id"]
