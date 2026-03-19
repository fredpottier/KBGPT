"""Modèles du système d'hygiène KG."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_action_id() -> str:
    return f"hyg_{uuid.uuid4().hex[:12]}"


class HygieneActionType(str, Enum):
    SUPPRESS_ENTITY = "SUPPRESS_ENTITY"
    HARD_DELETE_ENTITY = "HARD_DELETE_ENTITY"
    MERGE_CANONICAL = "MERGE_CANONICAL"
    MERGE_ENTITY = "MERGE_ENTITY"
    SUPPRESS_AXIS = "SUPPRESS_AXIS"
    MERGE_AXIS = "MERGE_AXIS"


class HygieneActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    REJECTED = "REJECTED"


class HygieneRunScope(str, Enum):
    TENANT = "tenant"
    DOCUMENT_SET = "document_set"


class HygieneAction(BaseModel):
    """Action d'hygiène sur le KG — snapshot complet pour rollback."""

    action_id: str = Field(default_factory=_gen_action_id)
    action_type: HygieneActionType
    target_node_id: str
    target_node_type: str  # "Entity", "CanonicalEntity", "ApplicabilityAxis"
    before_state: dict = Field(default_factory=dict)
    after_state: dict = Field(default_factory=dict)
    layer: int  # 1 or 2
    confidence: float = 1.0
    reason: str
    rule_name: str
    batch_id: str
    scope: str  # "tenant" | "document_set"
    status: HygieneActionStatus = HygieneActionStatus.APPLIED
    decision_source: str = "rule"  # "rule" | "llm_auto_apply" | "admin_approved"
    applied_at: Optional[str] = None
    rolled_back_at: Optional[str] = None
    tenant_id: str = "default"

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "target_node_id": self.target_node_id,
            "target_node_type": self.target_node_type,
            "before_state_json": json.dumps(self.before_state),
            "after_state_json": json.dumps(self.after_state),
            "layer": self.layer,
            "confidence": self.confidence,
            "reason": self.reason,
            "rule_name": self.rule_name,
            "batch_id": self.batch_id,
            "scope": self.scope,
            "status": self.status.value,
            "decision_source": self.decision_source,
            "applied_at": self.applied_at,
            "rolled_back_at": self.rolled_back_at,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "HygieneAction":
        """Construit depuis un record Neo4j."""
        before_state = {}
        if record.get("before_state_json"):
            try:
                before_state = json.loads(record["before_state_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        after_state = {}
        if record.get("after_state_json"):
            try:
                after_state = json.loads(record["after_state_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        return cls(
            action_id=record["action_id"],
            action_type=HygieneActionType(record["action_type"]),
            target_node_id=record["target_node_id"],
            target_node_type=record["target_node_type"],
            before_state=before_state,
            after_state=after_state,
            layer=record.get("layer", 1),
            confidence=record.get("confidence", 1.0),
            reason=record.get("reason", ""),
            rule_name=record.get("rule_name", ""),
            batch_id=record.get("batch_id", ""),
            scope=record.get("scope", "tenant"),
            status=HygieneActionStatus(record.get("status", "APPLIED")),
            decision_source=record.get("decision_source", "rule"),
            applied_at=record.get("applied_at"),
            rolled_back_at=record.get("rolled_back_at"),
            tenant_id=record.get("tenant_id", "default"),
        )


class HygieneRunResult(BaseModel):
    """Résultat d'un run d'hygiène."""

    batch_id: str
    total_actions: int = 0
    applied: int = 0
    proposed: int = 0
    skipped_already_suppressed: int = 0
    actions: List[HygieneAction] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    dry_run: bool = False
