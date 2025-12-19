"""
Memory Layer Module - Phase 2.5

Gestion des sessions de conversation avec:
- Persistence PostgreSQL
- LangChain Memory wrapper pour auto-summarization
- Context Resolver pour références implicites
- Intelligent Summarizer pour comptes-rendus métier
"""

from knowbase.memory.session_manager import (
    SessionManager,
    MessageData,
    get_session_manager
)
from knowbase.memory.context_resolver import (
    ContextResolver,
    ResolvedReference,
    ContextState,
    get_context_resolver
)
from knowbase.memory.intelligent_summarizer import (
    IntelligentSummarizer,
    SessionSummary,
    SummaryFormat,
    get_intelligent_summarizer
)

__all__ = [
    "SessionManager",
    "MessageData",
    "get_session_manager",
    "ContextResolver",
    "ResolvedReference",
    "ContextState",
    "get_context_resolver",
    "IntelligentSummarizer",
    "SessionSummary",
    "SummaryFormat",
    "get_intelligent_summarizer"
]
