"""
OSMOSE Verification Module

Text verification against Knowledge Graph claims with fallback to RAG.
"""

from knowbase.verification.assertion_splitter import AssertionSplitter
from knowbase.verification.evidence_matcher import EvidenceMatcher

__all__ = ["AssertionSplitter", "EvidenceMatcher"]
