"""
Audit trail pour opérations critiques (merge, undo, etc.)
"""

from .audit_logger import AuditLogger, MergeAuditEntry

__all__ = ["AuditLogger", "MergeAuditEntry"]
