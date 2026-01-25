# src/knowbase/logging/extraction_logger.py
"""
Logger exhaustif pour extractions MVP V1.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractionLog:
    """Log d'une extraction."""
    log_id: str
    timestamp: str
    document_id: str
    chunk_id: str
    tenant_id: str

    action: str  # ACCEPT | REJECT
    reason: str

    assertion_text: str
    assertion_type: str
    rhetorical_role: str

    value_extracted: Optional[dict]
    claimkey_inferred: Optional[str]

    context_inherited: dict
    context_override: Optional[dict]

    llm_model: str
    llm_confidence: float
    llm_latency_ms: int

    promotion_status: str
    promotion_reason: str


class ExtractionLogger:
    """
    Logger exhaustif pour les extractions.

    Responsabilités:
    - Logger ACCEPT / REJECT / UNLINKED
    - Persister en fichier JSONL
    - Générer statistiques
    - INVARIANT 1: Alerter si UNLINKED > seuil
    """

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.logs: list[ExtractionLog] = []
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        """Crée le répertoire de logs si nécessaire."""
        os.makedirs("data/logs", exist_ok=True)

    def log_accept(
        self,
        document_id: str,
        chunk_id: str,
        assertion: dict,
        value: Optional[dict],
        claimkey_id: Optional[str],
        context: dict,
        promotion_status: str,
        promotion_reason: str,
        llm_metadata: dict
    ):
        """Log une assertion acceptée."""
        log = ExtractionLog(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.utcnow().isoformat(),
            document_id=document_id,
            chunk_id=chunk_id,
            tenant_id=self.tenant_id,
            action="ACCEPT",
            reason=promotion_reason,
            assertion_text=assertion.get("text", "")[:500],
            assertion_type=assertion.get("type", "unknown"),
            rhetorical_role=assertion.get("rhetorical_role", "unknown"),
            value_extracted=value,
            claimkey_inferred=claimkey_id,
            context_inherited=context,
            context_override=assertion.get("context_override"),
            llm_model=llm_metadata.get("model", "unknown"),
            llm_confidence=assertion.get("confidence", 0.0),
            llm_latency_ms=llm_metadata.get("latency_ms", 0),
            promotion_status=promotion_status,
            promotion_reason=promotion_reason
        )
        self.logs.append(log)
        self._persist(log)

        level = logging.INFO if promotion_status == "PROMOTED_LINKED" else logging.WARNING
        logger.log(
            level,
            f"[EXTRACT:{promotion_status}] doc={document_id} "
            f"type={assertion.get('type')} claimkey={claimkey_id}"
        )

    def log_reject(
        self,
        document_id: str,
        chunk_id: str,
        assertion: dict,
        reason: str,
        llm_metadata: dict
    ):
        """Log une assertion rejetée."""
        log = ExtractionLog(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.utcnow().isoformat(),
            document_id=document_id,
            chunk_id=chunk_id,
            tenant_id=self.tenant_id,
            action="REJECT",
            reason=reason,
            assertion_text=assertion.get("text", "")[:500],
            assertion_type=assertion.get("type", "unknown"),
            rhetorical_role=assertion.get("rhetorical_role", "unknown"),
            value_extracted=None,
            claimkey_inferred=None,
            context_inherited={},
            context_override=None,
            llm_model=llm_metadata.get("model", "unknown"),
            llm_confidence=assertion.get("confidence", 0.0),
            llm_latency_ms=llm_metadata.get("latency_ms", 0),
            promotion_status="REJECTED",
            promotion_reason=reason
        )
        self.logs.append(log)
        self._persist(log)

        logger.warning(
            f"[EXTRACT:REJECT] doc={document_id} reason={reason} "
            f"text={assertion.get('text', '')[:50]}..."
        )

    def _persist(self, log: ExtractionLog):
        """Persiste le log en fichier JSONL."""
        log_file = f"data/logs/extraction_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(log), ensure_ascii=False) + "\n")

    def get_statistics(self) -> dict:
        """Retourne les statistiques des logs."""
        total = len(self.logs)
        if total == 0:
            return {
                "total_assertions": 0,
                "accepted": 0,
                "rejected": 0,
                "promoted_linked": 0,
                "promoted_unlinked": 0,
                "unlinked_rate": 0.0,
                "unlinked_alert": False
            }

        accepted = sum(1 for log in self.logs if log.action == "ACCEPT")
        rejected = sum(1 for log in self.logs if log.action == "REJECT")
        linked = sum(1 for log in self.logs if log.promotion_status == "PROMOTED_LINKED")
        unlinked = sum(1 for log in self.logs if log.promotion_status == "PROMOTED_UNLINKED")

        unlinked_rate = unlinked / accepted if accepted > 0 else 0.0
        unlinked_alert = unlinked_rate > 0.10

        stats = {
            "total_assertions": total,
            "accepted": accepted,
            "rejected": rejected,
            "promoted_linked": linked,
            "promoted_unlinked": unlinked,
            "acceptance_rate": accepted / total if total > 0 else 0,
            "linked_rate": linked / accepted if accepted > 0 else 0,
            "unlinked_rate": unlinked_rate,
            "unlinked_alert": unlinked_alert
        }

        # INVARIANT 1: Alerte si UNLINKED > 10%
        if unlinked_alert:
            logger.warning(
                f"[EXTRACT:ALERT] High UNLINKED rate: {unlinked_rate:.1%} "
                f"({unlinked}/{accepted}). Review missing ClaimKey patterns."
            )
            self._generate_missing_patterns_backlog()

        return stats

    def _generate_missing_patterns_backlog(self):
        """Génère un backlog des patterns manquants."""
        unlinked_logs = [log for log in self.logs if log.promotion_status == "PROMOTED_UNLINKED"]

        keywords: dict[str, int] = {}
        for log in unlinked_logs:
            text_lower = log.assertion_text.lower()
            words = re.findall(r'\b[a-z]{4,}\b', text_lower)
            stopwords = {"that", "this", "with", "from", "have", "been", "will", "would", "could"}
            for word in words:
                if word not in stopwords:
                    keywords[word] = keywords.get(word, 0) + 1

        top_keywords = sorted(keywords.items(), key=lambda x: -x[1])[:10]

        logger.info(f"[EXTRACT:BACKLOG] Top missing pattern keywords: {top_keywords}")

        backlog_file = f"data/logs/missing_patterns_{datetime.utcnow().strftime('%Y%m%d')}.json"
        with open(backlog_file, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.utcnow().isoformat(),
                "unlinked_count": len(unlinked_logs),
                "top_keywords": dict(top_keywords),
                "samples": [log.assertion_text for log in unlinked_logs[:20]]
            }, f, indent=2, ensure_ascii=False)

    def reset(self):
        """Reset les logs en mémoire (pour tests)."""
        self.logs = []


# Instance par tenant
_loggers: dict[str, ExtractionLogger] = {}


def get_extraction_logger(tenant_id: str) -> ExtractionLogger:
    """Retourne le logger pour un tenant."""
    if tenant_id not in _loggers:
        _loggers[tenant_id] = ExtractionLogger(tenant_id)
    return _loggers[tenant_id]
