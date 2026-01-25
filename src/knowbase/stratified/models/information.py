# src/knowbase/stratified/models/information.py
"""
Modèle Information pour MVP V1.
Représente une assertion factuelle extraite d'un document.

Part of: OSMOSE MVP V1 - Usage B (Challenge de Texte)
Reference: SPEC_IMPLEMENTATION_CLASSES_MVP_V1.md
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Union
import hashlib


class InformationType(str, Enum):
    """Types d'assertions."""
    PRESCRIPTIVE = "PRESCRIPTIVE"      # Obligations, interdictions
    DEFINITIONAL = "DEFINITIONAL"      # Définitions, descriptions
    CAUSAL = "CAUSAL"                  # Relations cause-effet
    COMPARATIVE = "COMPARATIVE"        # Comparaisons


class RhetoricalRole(str, Enum):
    """Rôles rhétoriques."""
    FACT = "fact"
    EXAMPLE = "example"
    DEFINITION = "definition"
    INSTRUCTION = "instruction"
    CLAIM = "claim"
    CAUTION = "caution"


class PromotionStatus(str, Enum):
    """Statuts de promotion."""
    PROMOTED_LINKED = "PROMOTED_LINKED"
    PROMOTED_UNLINKED = "PROMOTED_UNLINKED"
    REJECTED = "REJECTED"


class ValueKind(str, Enum):
    """Types de valeurs."""
    NUMBER = "number"
    PERCENT = "percent"
    VERSION = "version"
    ENUM = "enum"
    BOOLEAN = "boolean"
    STRING = "string"


class ValueComparable(str, Enum):
    """Niveaux de comparabilité."""
    STRICT = "strict"
    LOOSE = "loose"
    NON_COMPARABLE = "non_comparable"


class InheritanceMode(str, Enum):
    """Modes d'héritage de contexte."""
    INHERITED = "inherited"
    ASSERTED = "asserted"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class ValueInfo:
    """Valeur extraite d'une assertion."""
    kind: Optional[ValueKind] = None
    raw: Optional[str] = None
    normalized: Optional[Union[float, str, bool]] = None
    unit: Optional[str] = None
    operator: str = "="  # =, >=, <=, >, <, approx, in
    comparable: ValueComparable = ValueComparable.NON_COMPARABLE

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value if self.kind else None,
            "raw": self.raw,
            "normalized": self.normalized,
            "unit": self.unit,
            "operator": self.operator,
            "comparable": self.comparable.value
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ValueInfo":
        if not data:
            return cls()
        return cls(
            kind=ValueKind(data["kind"]) if data.get("kind") else None,
            raw=data.get("raw"),
            normalized=data.get("normalized"),
            unit=data.get("unit"),
            operator=data.get("operator", "="),
            comparable=ValueComparable(data.get("comparable", "non_comparable"))
        )


@dataclass
class SpanInfo:
    """Position dans le document."""
    page: int
    paragraph: Optional[int] = None
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "paragraph": self.paragraph,
            "line": self.line
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpanInfo":
        if not data:
            return cls(page=0)
        return cls(
            page=data.get("page", 0),
            paragraph=data.get("paragraph"),
            line=data.get("line")
        )


@dataclass
class ContextInfo:
    """Contexte documentaire."""
    edition: Optional[str] = None
    region: list[str] = field(default_factory=lambda: ["Global"])
    version: Optional[str] = None
    product: Optional[str] = None
    deployment: Optional[str] = None
    inheritance_mode: InheritanceMode = InheritanceMode.INHERITED

    def to_dict(self) -> dict:
        return {
            "edition": self.edition,
            "region": self.region,
            "version": self.version,
            "product": self.product,
            "deployment": self.deployment,
            "inheritance_mode": self.inheritance_mode.value
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextInfo":
        if not data:
            return cls()
        return cls(
            edition=data.get("edition"),
            region=data.get("region", ["Global"]),
            version=data.get("version"),
            product=data.get("product"),
            deployment=data.get("deployment"),
            inheritance_mode=InheritanceMode(data.get("inheritance_mode", "inherited"))
        )

    def to_context_key(self) -> str:
        """Clé de contexte pour fingerprint."""
        parts = [
            self.edition or "any",
            self.version or "any",
            ":".join(sorted(self.region))
        ]
        return ":".join(parts)


@dataclass
class InformationMVP:
    """
    Modèle Information MVP V1.

    Représente une assertion factuelle extraite d'un document,
    avec sa valeur, son contexte et ses liens.
    """
    # Identifiants
    information_id: str
    tenant_id: str
    document_id: str

    # Contenu OBLIGATOIRE
    text: str
    exact_quote: str  # OBLIGATOIRE - verbatim du texte source
    type: InformationType
    rhetorical_role: RhetoricalRole

    # Span OBLIGATOIRE
    span: SpanInfo

    # Valeur (optionnelle mais recommandée)
    value: ValueInfo = field(default_factory=ValueInfo)

    # Contexte
    context: ContextInfo = field(default_factory=ContextInfo)

    # Promotion
    promotion_status: PromotionStatus = PromotionStatus.PROMOTED_UNLINKED
    promotion_reason: str = ""

    # Liens (optionnels en MVP V1)
    claimkey_id: Optional[str] = None
    theme_id: Optional[str] = None
    concept_id: Optional[str] = None  # Exclu MVP V1

    # Déduplication
    fingerprint: str = ""

    # Métadonnées
    confidence: float = 0.0
    language: str = "en"
    extracted_at: datetime = field(default_factory=datetime.utcnow)

    # Anchors
    anchor_docitem_ids: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Calcule le fingerprint après initialisation."""
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """
        Calcule le fingerprint pour déduplication.
        Même fingerprint = même fait, merger les anchors.
        """
        components = [
            self.claimkey_id or "no_claimkey",
            str(self.value.normalized) if self.value.normalized else "no_value",
            self.context.to_context_key(),
            str(self.span.page)  # Page bucket, pas ligne exacte
        ]
        return hashlib.sha256(":".join(components).encode()).hexdigest()[:16]

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "information_id": self.information_id,
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,

            "text": self.text,
            "exact_quote": self.exact_quote,
            "type": self.type.value,
            "rhetorical_role": self.rhetorical_role.value,

            "span_page": self.span.page,
            "span_paragraph": self.span.paragraph,
            "span_line": self.span.line,

            "value_kind": self.value.kind.value if self.value.kind else None,
            "value_raw": self.value.raw,
            "value_normalized": self.value.normalized,
            "value_unit": self.value.unit,
            "value_operator": self.value.operator,
            "value_comparable": self.value.comparable.value,

            "context_edition": self.context.edition,
            "context_region": self.context.region,
            "context_version": self.context.version,
            "context_product": self.context.product,
            "context_deployment": self.context.deployment,
            "context_inheritance_mode": self.context.inheritance_mode.value,

            "promotion_status": self.promotion_status.value,
            "promotion_reason": self.promotion_reason,

            "claimkey_id": self.claimkey_id,
            "theme_id": self.theme_id,

            "fingerprint": self.fingerprint,
            "confidence": self.confidence,
            "language": self.language,
            "extracted_at": self.extracted_at.isoformat()
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "InformationMVP":
        """Construit depuis un record Neo4j."""
        return cls(
            information_id=record["information_id"],
            tenant_id=record["tenant_id"],
            document_id=record["document_id"],
            text=record["text"],
            exact_quote=record["exact_quote"],
            type=InformationType(record["type"]),
            rhetorical_role=RhetoricalRole(record["rhetorical_role"]),
            span=SpanInfo(
                page=record["span_page"],
                paragraph=record.get("span_paragraph"),
                line=record.get("span_line")
            ),
            value=ValueInfo(
                kind=ValueKind(record["value_kind"]) if record.get("value_kind") else None,
                raw=record.get("value_raw"),
                normalized=record.get("value_normalized"),
                unit=record.get("value_unit"),
                operator=record.get("value_operator", "="),
                comparable=ValueComparable(record.get("value_comparable", "non_comparable"))
            ),
            context=ContextInfo(
                edition=record.get("context_edition"),
                region=record.get("context_region", ["Global"]),
                version=record.get("context_version"),
                product=record.get("context_product"),
                deployment=record.get("context_deployment"),
                inheritance_mode=InheritanceMode(record.get("context_inheritance_mode", "inherited"))
            ),
            promotion_status=PromotionStatus(record["promotion_status"]),
            promotion_reason=record.get("promotion_reason", ""),
            claimkey_id=record.get("claimkey_id"),
            theme_id=record.get("theme_id"),
            fingerprint=record.get("fingerprint", ""),
            confidence=record.get("confidence", 0.0),
            language=record.get("language", "en"),
            extracted_at=datetime.fromisoformat(record["extracted_at"]) if record.get("extracted_at") else datetime.utcnow()
        )
