# Spec Implémentation - Classes et Modules MVP V1

**Status:** Référence pour implémentation
**Date:** 2026-01-25
**Référence:** SPEC_TECHNIQUE_MVP_V1_USAGE_B.md
**Objectif:** Vision exhaustive des classes à créer/modifier pour éviter effets de bord

---

## 0. Vue d'Ensemble des Fichiers

### Fichiers à CRÉER

| Fichier | Module | Description |
|---------|--------|-------------|
| `src/knowbase/stratified/models/information.py` | Models | Modèle Pydantic Information |
| `src/knowbase/stratified/models/claimkey.py` | Models | Modèle Pydantic ClaimKey |
| `src/knowbase/stratified/models/contradiction.py` | Models | Modèle Pydantic Contradiction |
| `src/knowbase/stratified/pass1/promotion_policy.py` | Pass1 | Politique de promotion |
| `src/knowbase/stratified/pass1/value_extractor.py` | Pass1 | Extraction de valeurs |
| `src/knowbase/stratified/claimkey/patterns.py` | ClaimKey | Patterns Niveau A |
| `src/knowbase/stratified/claimkey/status_manager.py` | ClaimKey | Gestion statuts ClaimKey |
| `src/knowbase/stratified/context/propagation.py` | Context | Propagation contexte |
| `src/knowbase/api/routers/challenge.py` | API | Endpoint challenge |
| `src/knowbase/api/services/challenge_service.py` | API | Service TextChallenger |
| `src/knowbase/logging/extraction_logger.py` | Logging | Logger exhaustif |

### Fichiers à MODIFIER

| Fichier | Modifications |
|---------|---------------|
| `src/knowbase/stratified/models/__init__.py` | Exports nouveaux modèles |
| `src/knowbase/stratified/pass1/assertion_extractor.py` | Nouveau prompt, appel ValueExtractor |
| `src/knowbase/stratified/pass1/orchestrator.py` | Intégration PromotionPolicy, Logger |
| `src/knowbase/api/main.py` | Ajout router challenge |
| `config/prompts.yaml` | Nouveau prompt Pass 1.3 |

### Fichiers NON MODIFIÉS (existants à réutiliser)

| Fichier | Réutilisation |
|---------|---------------|
| `src/knowbase/common/clients/neo4j_client.py` | Client Neo4j existant |
| `src/knowbase/stratified/models/schemas.py` | Modèles existants (Subject, Theme, etc.) |

---

## 1. Module Models

### 1.1 `information.py` - CRÉER

```python
# src/knowbase/stratified/models/information.py
"""
Modèle Information pour MVP V1.
Représente une assertion factuelle extraite d'un document.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
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
    normalized: Optional[float | str | bool] = None
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

    def to_context_key(self) -> str:
        """Clé de contexte pour fingerprint."""
        parts = [
            self.edition or "any",
            self.version or "any",
            ":".join(sorted(self.region))
        ]
        return ":".join(parts)


@dataclass
class Information:
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
    def from_neo4j_record(cls, record: dict) -> "Information":
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
```

### 1.2 `claimkey.py` - CRÉER

```python
# src/knowbase/stratified/models/claimkey.py
"""
Modèle ClaimKey pour MVP V1.
Représente une question factuelle canonique.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ClaimKeyStatus(str, Enum):
    """Statuts de ClaimKey."""
    EMERGENT = "emergent"        # < 3 infos ou 1 seul doc
    COMPARABLE = "comparable"    # >= 2 docs avec valeurs comparables
    DEPRECATED = "deprecated"    # Remplacé par autre ClaimKey
    ORPHAN = "orphan"            # Aucune info récente


@dataclass
class ClaimKey:
    """
    Modèle ClaimKey MVP V1.

    Représente une question factuelle canonique,
    indépendante du vocabulaire des documents.
    """
    # Identifiants
    claimkey_id: str
    tenant_id: str

    # Question factuelle
    key: str  # Identifiant machine (ex: "tls_min_version")
    canonical_question: str  # Question en langage naturel

    # Domaine
    domain: str  # Ex: "security.encryption"

    # Statut
    status: ClaimKeyStatus = ClaimKeyStatus.EMERGENT

    # Métriques
    info_count: int = 0
    doc_count: int = 0
    has_contradiction: bool = False

    # Méthode d'inférence
    inference_method: str = "pattern_level_a"

    # Métadonnées
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "claimkey_id": self.claimkey_id,
            "tenant_id": self.tenant_id,
            "key": self.key,
            "canonical_question": self.canonical_question,
            "domain": self.domain,
            "status": self.status.value,
            "info_count": self.info_count,
            "doc_count": self.doc_count,
            "has_contradiction": self.has_contradiction,
            "inference_method": self.inference_method,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "ClaimKey":
        """Construit depuis un record Neo4j."""
        return cls(
            claimkey_id=record["claimkey_id"],
            tenant_id=record["tenant_id"],
            key=record["key"],
            canonical_question=record.get("canonical_question", ""),
            domain=record.get("domain", ""),
            status=ClaimKeyStatus(record.get("status", "emergent")),
            info_count=record.get("info_count", 0),
            doc_count=record.get("doc_count", 0),
            has_contradiction=record.get("has_contradiction", False),
            inference_method=record.get("inference_method", "pattern_level_a"),
            created_at=datetime.fromisoformat(record["created_at"]) if record.get("created_at") else datetime.utcnow(),
            updated_at=datetime.fromisoformat(record["updated_at"]) if record.get("updated_at") else datetime.utcnow()
        )

    def update_metrics(self, info_count: int, doc_count: int):
        """Met à jour les métriques et recalcule le statut."""
        self.info_count = info_count
        self.doc_count = doc_count
        self.updated_at = datetime.utcnow()

        # Recalculer le statut
        if info_count == 0:
            self.status = ClaimKeyStatus.ORPHAN
        elif doc_count < 2:
            self.status = ClaimKeyStatus.EMERGENT
        else:
            self.status = ClaimKeyStatus.COMPARABLE
```

### 1.3 `contradiction.py` - CRÉER

```python
# src/knowbase/stratified/models/contradiction.py
"""
Modèle Contradiction pour MVP V1.
Représente une tension détectée entre deux Informations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ContradictionNature(str, Enum):
    """Types de contradictions."""
    VALUE_CONFLICT = "value_conflict"
    VALUE_EXCEEDS_MINIMUM = "value_exceeds_minimum"  # Soft
    VALUE_BELOW_MAXIMUM = "value_below_maximum"      # Soft
    SCOPE_CONFLICT = "scope_conflict"
    TEMPORAL_CONFLICT = "temporal_conflict"
    MISSING_CLAIM = "missing_claim"


class TensionLevel(str, Enum):
    """Niveaux de tension."""
    NONE = "none"
    SOFT = "soft"    # Compatible mais différent
    HARD = "hard"    # Incompatible
    UNKNOWN = "unknown"


@dataclass
class Contradiction:
    """
    Modèle Contradiction MVP V1.

    Représente une tension entre deux Informations
    sur le même ClaimKey.
    """
    # Identifiants
    contradiction_id: str
    claimkey_id: str

    # Informations en conflit
    info_a_id: str
    info_a_document: str
    info_a_value_raw: Optional[str]
    info_a_context: dict

    info_b_id: str
    info_b_document: str
    info_b_value_raw: Optional[str]
    info_b_context: dict

    # Classification
    nature: ContradictionNature
    tension_level: TensionLevel
    explanation: str

    # Métadonnées
    detected_at: datetime = field(default_factory=datetime.utcnow)
    detection_method: str = "value_normalized_comparison"

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés Neo4j."""
        return {
            "contradiction_id": self.contradiction_id,
            "claimkey_id": self.claimkey_id,
            "info_a_id": self.info_a_id,
            "info_a_document": self.info_a_document,
            "info_a_value_raw": self.info_a_value_raw,
            "info_b_id": self.info_b_id,
            "info_b_document": self.info_b_document,
            "info_b_value_raw": self.info_b_value_raw,
            "nature": self.nature.value,
            "tension_level": self.tension_level.value,
            "explanation": self.explanation,
            "detected_at": self.detected_at.isoformat(),
            "detection_method": self.detection_method
        }
```

### 1.4 `models/__init__.py` - MODIFIER

```python
# src/knowbase/stratified/models/__init__.py
"""
Modèles Stratified pour MVP V1.
"""

# Modèles existants
from .schemas import (
    Pass1Result,
    DocumentMeta,
    Subject,
    Theme,
    Concept,
    ConceptRole,
    # ... autres existants
)

# Nouveaux modèles MVP V1
from .information import (
    Information,
    InformationType,
    RhetoricalRole,
    PromotionStatus,
    ValueKind,
    ValueComparable,
    InheritanceMode,
    ValueInfo,
    SpanInfo,
    ContextInfo,
)

from .claimkey import (
    ClaimKey,
    ClaimKeyStatus,
)

from .contradiction import (
    Contradiction,
    ContradictionNature,
    TensionLevel,
)

__all__ = [
    # Existants
    "Pass1Result",
    "DocumentMeta",
    "Subject",
    "Theme",
    "Concept",
    "ConceptRole",
    # Nouveaux MVP V1
    "Information",
    "InformationType",
    "RhetoricalRole",
    "PromotionStatus",
    "ValueKind",
    "ValueComparable",
    "InheritanceMode",
    "ValueInfo",
    "SpanInfo",
    "ContextInfo",
    "ClaimKey",
    "ClaimKeyStatus",
    "Contradiction",
    "ContradictionNature",
    "TensionLevel",
]
```

---

## 2. Module Pass1

### 2.1 `value_extractor.py` - CRÉER

```python
# src/knowbase/stratified/pass1/value_extractor.py
"""
Extracteur de valeurs bornées pour MVP V1.
Types supportés: number, percent, version, enum, boolean.
"""

from __future__ import annotations
import re
from typing import Optional

from ..models.information import ValueInfo, ValueKind, ValueComparable


class ValueExtractor:
    """
    Extracteur de valeurs bornées.

    Extrait et normalise les valeurs depuis le texte.
    MVP V1: number, percent, version, enum, boolean uniquement.
    """

    def extract(self, text: str) -> Optional[ValueInfo]:
        """
        Extrait et normalise une valeur depuis le texte.

        Args:
            text: Texte à analyser

        Returns:
            ValueInfo ou None si pas de valeur détectée
        """
        text_lower = text.lower().strip()

        # Tenter chaque extracteur dans l'ordre de spécificité
        extractors = [
            self._extract_percent,
            self._extract_version,
            self._extract_number_with_unit,
            self._extract_boolean,
            self._extract_enum,
        ]

        for extractor in extractors:
            result = extractor(text_lower, text)
            if result:
                return result

        return None

    def _extract_percent(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait un pourcentage."""
        patterns = [
            r"(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*percent",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                raw_value = match.group(1)
                normalized = float(raw_value) / 100.0
                return ValueInfo(
                    kind=ValueKind.PERCENT,
                    raw=f"{raw_value}%",
                    normalized=normalized,
                    unit="%",
                    operator="=",
                    comparable=ValueComparable.STRICT
                )
        return None

    def _extract_version(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait une version."""
        patterns = [
            (r"(?:tls|ssl)\s*(\d+(?:\.\d+)?)", "tls"),
            (r"(?:v|version\s*)(\d+(?:\.\d+)*)", "version"),
            (r"(\d+\.\d+(?:\.\d+)?)", "generic"),
        ]

        for pattern, pattern_type in patterns:
            match = re.search(pattern, text_lower)
            if match:
                version_str = match.group(1)
                # Normaliser en gardant max 3 niveaux
                parts = version_str.split(".")
                normalized = ".".join(parts[:3])

                # Détecter opérateur
                operator = self._detect_operator(text_lower)

                return ValueInfo(
                    kind=ValueKind.VERSION,
                    raw=version_str,
                    normalized=normalized,
                    unit="version",
                    operator=operator,
                    comparable=ValueComparable.STRICT
                )
        return None

    def _extract_number_with_unit(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait un nombre avec unité."""
        units = {
            r"tib": ("TiB", 1),
            r"tb": ("TB", 1),
            r"gib": ("GiB", 1),
            r"gb": ("GB", 1),
            r"hours?": ("hours", 1),
            r"days?": ("days", 1),
            r"weeks?": ("weeks", 1),
            r"months?": ("months", 1),
            r"years?": ("years", 1),
        }

        for unit_pattern, (unit_name, multiplier) in units.items():
            pattern = rf"(\d+(?:\.\d+)?)\s*{unit_pattern}"
            match = re.search(pattern, text_lower)
            if match:
                raw_value = match.group(1)
                normalized = float(raw_value) * multiplier
                operator = self._detect_operator(text_lower)

                return ValueInfo(
                    kind=ValueKind.NUMBER,
                    raw=f"{raw_value} {unit_name}",
                    normalized=normalized,
                    unit=unit_name,
                    operator=operator,
                    comparable=ValueComparable.STRICT
                )
        return None

    def _extract_boolean(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait un booléen."""
        true_patterns = [
            r"\b(enabled|required|mandatory|enforced|supported|available)\b",
            r"\b(must|shall)\b",
            r"\bis\s+(enabled|required|mandatory)\b",
        ]
        false_patterns = [
            r"\b(disabled|not required|optional|not supported|unavailable)\b",
            r"\bnot\s+(enabled|required|mandatory)\b",
        ]

        for pattern in true_patterns:
            if re.search(pattern, text_lower):
                return ValueInfo(
                    kind=ValueKind.BOOLEAN,
                    raw="true",
                    normalized=True,
                    unit=None,
                    operator="=",
                    comparable=ValueComparable.STRICT
                )

        for pattern in false_patterns:
            if re.search(pattern, text_lower):
                return ValueInfo(
                    kind=ValueKind.BOOLEAN,
                    raw="false",
                    normalized=False,
                    unit=None,
                    operator="=",
                    comparable=ValueComparable.STRICT
                )

        return None

    def _extract_enum(self, text_lower: str, text_raw: str) -> Optional[ValueInfo]:
        """Extrait une valeur énumérée."""
        enums = {
            "frequency": ["daily", "weekly", "monthly", "hourly", "yearly", "continuous"],
            "responsibility": ["customer", "sap", "vendor", "shared", "third-party"],
            "severity": ["critical", "high", "medium", "low"],
            "edition": ["private", "public", "enterprise", "standard"],
        }

        for enum_type, values in enums.items():
            for value in values:
                if re.search(rf"\b{value}\b", text_lower):
                    return ValueInfo(
                        kind=ValueKind.ENUM,
                        raw=value,
                        normalized=value.lower(),
                        unit=enum_type,
                        operator="=",
                        comparable=ValueComparable.STRICT
                    )

        return None

    def _detect_operator(self, text_lower: str) -> str:
        """Détecte l'opérateur de comparaison."""
        if any(kw in text_lower for kw in ["above", "over", "exceeds", "greater than", "more than"]):
            return ">"
        if any(kw in text_lower for kw in ["below", "under", "less than"]):
            return "<"
        if any(kw in text_lower for kw in ["at least", "minimum", "min"]):
            return ">="
        if any(kw in text_lower for kw in ["at most", "maximum", "max"]):
            return "<="
        if any(kw in text_lower for kw in ["approximately", "about", "around"]):
            return "approx"
        return "="
```

### 2.2 `promotion_policy.py` - CRÉER

```python
# src/knowbase/stratified/pass1/promotion_policy.py
"""
Politique de promotion Information-First pour MVP V1.
"""

from __future__ import annotations
import re
from typing import Tuple

from ..models.information import (
    InformationType,
    RhetoricalRole,
    PromotionStatus,
)


class PromotionPolicy:
    """
    Politique de promotion Information-First.

    Règles:
    - ALWAYS_PROMOTE: Types et rôles qui sont toujours promus
    - REJECT_PATTERNS: Patterns de texte méta à rejeter
    - Défaut: PROMOTED_UNLINKED (jamais de rejet silencieux)
    """

    # Types toujours promus
    ALWAYS_PROMOTE_TYPES = [
        InformationType.PRESCRIPTIVE,
        InformationType.DEFINITIONAL,
    ]

    # Rôles toujours promus avec ClaimKey
    ALWAYS_PROMOTE_ROLES = [
        RhetoricalRole.FACT,
        RhetoricalRole.DEFINITION,
        RhetoricalRole.INSTRUCTION,
    ]

    # Rôles promus mais sans ClaimKey
    PROMOTE_NO_CLAIMKEY_ROLES = [
        RhetoricalRole.EXAMPLE,
        RhetoricalRole.CAUTION,
    ]

    # Patterns de texte méta à rejeter
    REJECT_PATTERNS = [
        r"^this\s+(page|section|chapter|document)\s+(describes|shows|presents|explains|covers)",
        r"^see\s+also\b",
        r"^refer\s+to\b",
        r"^for\s+more\s+information",
        r"^note\s*:",
        r"^disclaimer\s*:",
        r"^copyright\b",
        r"^table\s+of\s+contents",
        r"^\d+\.\s*$",  # Numéros de section seuls
    ]

    def evaluate(
        self,
        assertion: dict
    ) -> Tuple[PromotionStatus, str]:
        """
        Évalue une assertion et retourne son statut de promotion.

        Args:
            assertion: Dict avec keys: text, type, rhetorical_role, value, confidence

        Returns:
            (PromotionStatus, reason)
        """
        text = assertion.get("text", "").strip()
        text_lower = text.lower()
        assertion_type = assertion.get("type")
        rhetorical_role = assertion.get("rhetorical_role")
        has_value = assertion.get("value") is not None

        # 1. Rejet explicite par pattern
        for pattern in self.REJECT_PATTERNS:
            if re.match(pattern, text_lower, re.IGNORECASE):
                return PromotionStatus.REJECTED, f"meta_pattern:{pattern[:30]}"

        # 2. Rejet si texte trop court
        if len(text) < 15:
            return PromotionStatus.REJECTED, "text_too_short"

        # 3. Promotion automatique par type
        if assertion_type:
            try:
                info_type = InformationType(assertion_type)
                if info_type in self.ALWAYS_PROMOTE_TYPES:
                    return PromotionStatus.PROMOTED_LINKED, f"type:{info_type.value}"
            except ValueError:
                pass

        # 4. Promotion automatique par rôle
        if rhetorical_role:
            try:
                role = RhetoricalRole(rhetorical_role)
                if role in self.ALWAYS_PROMOTE_ROLES:
                    return PromotionStatus.PROMOTED_LINKED, f"role:{role.value}"
                if role in self.PROMOTE_NO_CLAIMKEY_ROLES:
                    return PromotionStatus.PROMOTED_UNLINKED, f"role_no_claimkey:{role.value}"
            except ValueError:
                pass

        # 5. Promotion si valeur présente
        if has_value:
            return PromotionStatus.PROMOTED_LINKED, "has_value"

        # 6. Défaut: PROMOTED_UNLINKED (jamais de rejet silencieux)
        return PromotionStatus.PROMOTED_UNLINKED, "no_clear_category"


# Instance singleton
_promotion_policy: PromotionPolicy | None = None


def get_promotion_policy() -> PromotionPolicy:
    """Retourne l'instance singleton."""
    global _promotion_policy
    if _promotion_policy is None:
        _promotion_policy = PromotionPolicy()
    return _promotion_policy
```

### 2.3 `assertion_extractor.py` - MODIFIER (sections clés)

```python
# src/knowbase/stratified/pass1/assertion_extractor.py
"""
MODIFICATIONS MVP V1:
- Nouveau prompt avec exact_quote + span obligatoires
- Intégration ValueExtractor
- Intégration PromotionPolicy
- Création Information au lieu de AssertionLog
"""

# IMPORTS À AJOUTER
from ..models.information import (
    Information,
    InformationType,
    RhetoricalRole,
    SpanInfo,
    ContextInfo,
)
from .value_extractor import ValueExtractor
from .promotion_policy import get_promotion_policy
from ...logging.extraction_logger import get_extraction_logger

# NOUVELLE MÉTHODE
class AssertionExtractor:
    """Extracteur d'assertions MVP V1."""

    def __init__(self, tenant_id: str, llm_client):
        self.tenant_id = tenant_id
        self.llm_client = llm_client
        self.value_extractor = ValueExtractor()
        self.promotion_policy = get_promotion_policy()
        self.logger = get_extraction_logger(tenant_id)

    async def extract_from_chunk(
        self,
        chunk_text: str,
        document_id: str,
        page_number: int,
        doc_context: ContextInfo,
        theme_id: str | None = None
    ) -> list[Information]:
        """
        Extrait les assertions d'un chunk.

        Returns:
            Liste d'Information (jamais vide si assertions détectées)
        """
        # 1. Appel LLM avec nouveau prompt
        llm_response = await self._call_llm(chunk_text, page_number, doc_context)

        # 2. Parser les assertions
        assertions = llm_response.get("assertions", [])

        # 3. Convertir en Information avec promotion
        informations = []
        for assertion in assertions:
            info = self._process_assertion(
                assertion=assertion,
                document_id=document_id,
                page_number=page_number,
                doc_context=doc_context,
                theme_id=theme_id
            )
            if info:
                informations.append(info)

        return informations

    def _process_assertion(
        self,
        assertion: dict,
        document_id: str,
        page_number: int,
        doc_context: ContextInfo,
        theme_id: str | None
    ) -> Information | None:
        """
        Convertit une assertion LLM en Information.

        Applique:
        - Extraction de valeur
        - Politique de promotion
        - Propagation de contexte
        """
        # 1. Vérifier champs obligatoires
        if not assertion.get("exact_quote"):
            self.logger.log_reject(
                document_id=document_id,
                chunk_id=f"page_{page_number}",
                assertion=assertion,
                reason="missing_exact_quote",
                llm_metadata={}
            )
            return None

        # 2. Extraire valeur
        value = self.value_extractor.extract(assertion.get("text", ""))

        # 3. Appliquer politique de promotion
        assertion_with_value = {**assertion, "value": value}
        status, reason = self.promotion_policy.evaluate(assertion_with_value)

        # 4. Si REJECTED, logger et retourner None
        if status == PromotionStatus.REJECTED:
            self.logger.log_reject(
                document_id=document_id,
                chunk_id=f"page_{page_number}",
                assertion=assertion,
                reason=reason,
                llm_metadata={}
            )
            return None

        # 5. Construire l'Information
        span = SpanInfo(
            page=assertion.get("span", {}).get("page", page_number),
            paragraph=assertion.get("span", {}).get("paragraph"),
            line=assertion.get("span", {}).get("line")
        )

        # 6. Propager contexte
        context = self._propagate_context(assertion, doc_context)

        # 7. Créer Information
        info = Information(
            information_id=f"info_{uuid.uuid4().hex[:12]}",
            tenant_id=self.tenant_id,
            document_id=document_id,
            text=assertion.get("text", ""),
            exact_quote=assertion["exact_quote"],
            type=InformationType(assertion.get("type", "DEFINITIONAL")),
            rhetorical_role=RhetoricalRole(assertion.get("rhetorical_role", "fact")),
            span=span,
            value=value or ValueInfo(),
            context=context,
            promotion_status=status,
            promotion_reason=reason,
            theme_id=theme_id,
            confidence=assertion.get("confidence", 0.0)
        )

        # 8. Logger
        self.logger.log_accept(
            document_id=document_id,
            chunk_id=f"page_{page_number}",
            assertion=assertion,
            value=value.to_dict() if value else None,
            claimkey_id=None,  # Sera assigné par ClaimKeyPatterns
            context=context.to_dict(),
            promotion_status=status.value,
            promotion_reason=reason,
            llm_metadata={}
        )

        return info

    def _propagate_context(
        self,
        assertion: dict,
        doc_context: ContextInfo
    ) -> ContextInfo:
        """Propage le contexte documentaire."""
        context = ContextInfo(
            edition=doc_context.edition,
            region=doc_context.region.copy(),
            version=doc_context.version,
            product=doc_context.product,
            deployment=doc_context.deployment,
            inheritance_mode=InheritanceMode.INHERITED
        )

        # Override par assertion locale
        override = assertion.get("context_override", {})
        if override:
            if override.get("edition"):
                context.edition = override["edition"]
                context.inheritance_mode = InheritanceMode.MIXED
            if override.get("region"):
                context.region = override["region"]
                context.inheritance_mode = InheritanceMode.MIXED

        return context
```

---

## 3. Module ClaimKey

### 3.1 `patterns.py` - CRÉER

```python
# src/knowbase/stratified/claimkey/patterns.py
"""
Patterns ClaimKey Niveau A pour MVP V1.
Inférence déterministe sans LLM.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from ..models.claimkey import ClaimKey, ClaimKeyStatus


@dataclass
class PatternMatch:
    """Résultat d'un match de pattern."""
    claimkey_id: str
    key: str
    domain: str
    canonical_question: str
    value_kind: str
    match_text: str
    inference_method: str = "pattern_level_a"


class ClaimKeyPatterns:
    """
    Patterns lexicaux pour inference ClaimKey Niveau A.

    Pas de LLM - patterns déterministes uniquement.
    """

    PATTERNS = [
        # SLA / Availability
        {
            "pattern": r"(\d+(?:\.\d+)?)\s*%\s*(sla|availability|uptime)",
            "key_template": "sla_{context}_availability",
            "domain": "sla.availability",
            "question": "What is the SLA availability percentage?",
            "value_kind": "percent"
        },

        # TLS / Encryption
        {
            "pattern": r"tls\s*(\d+(?:\.\d+)?)",
            "key_template": "tls_min_version",
            "domain": "security.encryption",
            "question": "What is the minimum TLS version required?",
            "value_kind": "version"
        },
        {
            "pattern": r"(encryption|encrypted)\s*(at\s*rest|in\s*transit)",
            "key_template": "encryption_{match}",
            "domain": "security.encryption",
            "question": "Is encryption {match} enabled?",
            "value_kind": "boolean"
        },

        # Backup / Retention
        {
            "pattern": r"backup[s]?\s*(daily|weekly|hourly|\d+\s*(hours?|days?))",
            "key_template": "backup_frequency",
            "domain": "operations.backup",
            "question": "How often are backups performed?",
            "value_kind": "enum"
        },
        {
            "pattern": r"retention\s*(?:period)?\s*(?:of|:)?\s*(\d+)\s*(days?|months?|years?)",
            "key_template": "data_retention_period",
            "domain": "compliance.retention",
            "question": "What is the data retention period?",
            "value_kind": "number"
        },

        # Data Residency
        {
            "pattern": r"data\s*(?:must|shall)?\s*(?:remain|stay|stored?)\s*(?:in|within)\s*(\w+)",
            "key_template": "data_residency_{country}",
            "domain": "compliance.residency",
            "question": "Must data remain in {country}?",
            "value_kind": "boolean"
        },

        # Size Thresholds
        {
            "pattern": r"(?:above|over|exceeds?|greater\s+than)\s*(\d+)\s*(tib|tb|gb)",
            "key_template": "{context}_size_threshold",
            "domain": "infrastructure.sizing",
            "question": "What is the size threshold for {context}?",
            "value_kind": "number"
        },

        # Responsibility
        {
            "pattern": r"(customer|sap|vendor)\s*(?:is)?\s*(?:responsible|responsibility|manages?)",
            "key_template": "{topic}_responsibility",
            "domain": "operations.responsibility",
            "question": "Who is responsible for {topic}?",
            "value_kind": "enum"
        },

        # Version Requirements
        {
            "pattern": r"(?:minimum|required|supported)\s*version\s*:?\s*(\d+(?:\.\d+)*)",
            "key_template": "{product}_min_version",
            "domain": "compatibility.version",
            "question": "What is the minimum version required for {product}?",
            "value_kind": "version"
        },

        # Patch / Update
        {
            "pattern": r"(?:patch|update)[s]?\s*(?:applied|installed)?\s*(daily|weekly|monthly|quarterly)",
            "key_template": "patch_frequency",
            "domain": "operations.patching",
            "question": "How often are patches applied?",
            "value_kind": "enum"
        },
    ]

    # Questions canoniques pour claimkeys connus
    CANONICAL_QUESTIONS = {
        "tls_min_version": "What is the minimum TLS version required?",
        "sla_availability": "What is the SLA availability percentage?",
        "backup_frequency": "How often are backups performed?",
        "data_retention_period": "What is the data retention period?",
        "data_residency_china": "Must data remain in China?",
        "patch_frequency": "How often are patches applied?",
        "encryption_at_rest": "Is encryption at rest enabled?",
        "encryption_in_transit": "Is encryption in transit enabled?",
    }

    def infer_claimkey(
        self,
        text: str,
        context: dict
    ) -> Optional[PatternMatch]:
        """
        Tente d'inférer un ClaimKey depuis le texte.

        Args:
            text: Texte à analyser
            context: Contexte (product, topic, etc.)

        Returns:
            PatternMatch ou None si pas de match
        """
        text_lower = text.lower()

        for pattern_def in self.PATTERNS:
            match = re.search(pattern_def["pattern"], text_lower, re.IGNORECASE)
            if match:
                # Résoudre le template
                key = self._resolve_template(
                    pattern_def["key_template"],
                    match,
                    context
                )
                claimkey_id = f"ck_{key}"

                # Résoudre la question
                question = self._resolve_question(
                    pattern_def["question"],
                    match,
                    context
                )

                return PatternMatch(
                    claimkey_id=claimkey_id,
                    key=key,
                    domain=pattern_def["domain"],
                    canonical_question=question,
                    value_kind=pattern_def["value_kind"],
                    match_text=match.group(0)
                )

        return None

    def _resolve_template(
        self,
        template: str,
        match: re.Match,
        context: dict
    ) -> str:
        """Résout un template de clé."""
        result = template

        # {context} → product ou "general"
        if "{context}" in result:
            ctx = context.get("product", "general").lower()
            ctx = re.sub(r"[^a-z0-9]", "_", ctx)
            result = result.replace("{context}", ctx)

        # {country} → groupe capturé ou "unknown"
        if "{country}" in result:
            country = "unknown"
            for group in match.groups():
                if group and re.match(r"^[a-z]+$", group.lower()):
                    country = group.lower()
                    break
            result = result.replace("{country}", country)

        # {match} → premier groupe non-numérique
        if "{match}" in result:
            for group in match.groups():
                if group and not group.replace(".", "").isdigit():
                    clean = re.sub(r"[^a-z]", "_", group.lower())
                    result = result.replace("{match}", clean)
                    break

        # {topic} → theme courant ou "general"
        if "{topic}" in result:
            topic = context.get("current_theme", "general").lower()
            topic = re.sub(r"[^a-z0-9]", "_", topic)
            result = result.replace("{topic}", topic)

        # {product} → product ou "unknown"
        if "{product}" in result:
            product = context.get("product", "unknown").lower()
            product = re.sub(r"[^a-z0-9]", "_", product)
            result = result.replace("{product}", product)

        return result

    def _resolve_question(
        self,
        template: str,
        match: re.Match,
        context: dict
    ) -> str:
        """Résout un template de question."""
        result = template

        # Mêmes substitutions que _resolve_template
        for placeholder in ["{context}", "{country}", "{match}", "{topic}", "{product}"]:
            if placeholder in result:
                key = placeholder[1:-1]
                value = context.get(key, "")
                if not value and match.groups():
                    for group in match.groups():
                        if group:
                            value = group
                            break
                result = result.replace(placeholder, value or "unknown")

        return result

    def get_canonical_question(self, claimkey_id: str) -> str:
        """Retourne la question canonique pour un ClaimKey."""
        key = claimkey_id.replace("ck_", "")
        return self.CANONICAL_QUESTIONS.get(key, f"Question for {claimkey_id}")


# Instance singleton
_claimkey_patterns: ClaimKeyPatterns | None = None


def get_claimkey_patterns() -> ClaimKeyPatterns:
    """Retourne l'instance singleton."""
    global _claimkey_patterns
    if _claimkey_patterns is None:
        _claimkey_patterns = ClaimKeyPatterns()
    return _claimkey_patterns
```

### 3.2 `status_manager.py` - CRÉER

```python
# src/knowbase/stratified/claimkey/status_manager.py
"""
Gestionnaire de statuts ClaimKey pour MVP V1.
"""

from __future__ import annotations
import logging
from typing import Optional

from ..models.claimkey import ClaimKey, ClaimKeyStatus

logger = logging.getLogger(__name__)


class ClaimKeyStatusManager:
    """
    Gestionnaire de statuts ClaimKey.

    Responsabilités:
    - Créer/récupérer des ClaimKeys
    - Mettre à jour les métriques
    - Recalculer les statuts
    """

    def __init__(self, neo4j_driver, tenant_id: str):
        self.neo4j_driver = neo4j_driver
        self.tenant_id = tenant_id

    def get_or_create(
        self,
        claimkey_id: str,
        key: str,
        domain: str,
        canonical_question: str,
        inference_method: str = "pattern_level_a"
    ) -> ClaimKey:
        """
        Récupère ou crée un ClaimKey.

        Args:
            claimkey_id: ID unique du ClaimKey
            key: Clé machine
            domain: Domaine
            canonical_question: Question canonique
            inference_method: Méthode d'inférence

        Returns:
            ClaimKey existant ou nouvellement créé
        """
        with self.neo4j_driver.session() as session:
            # Tenter de récupérer
            result = session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                RETURN ck
            """, ck_id=claimkey_id, tenant_id=self.tenant_id).single()

            if result:
                return ClaimKey.from_neo4j_record(dict(result["ck"]))

            # Créer
            claimkey = ClaimKey(
                claimkey_id=claimkey_id,
                tenant_id=self.tenant_id,
                key=key,
                canonical_question=canonical_question,
                domain=domain,
                inference_method=inference_method
            )

            session.run("""
                CREATE (ck:ClaimKey $props)
            """, props=claimkey.to_neo4j_properties())

            logger.info(f"[CLAIMKEY] Created: {claimkey_id} ({domain})")
            return claimkey

    def update_metrics(self, claimkey_id: str) -> ClaimKeyStatus:
        """
        Met à jour les métriques d'un ClaimKey et recalcule son statut.

        Returns:
            Nouveau statut
        """
        with self.neo4j_driver.session() as session:
            result = session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                OPTIONAL MATCH (i:Information)-[:ANSWERS]->(ck)
                WHERE i.promotion_status = 'PROMOTED_LINKED'
                OPTIONAL MATCH (i)-[:EXTRACTED_FROM]->(d:Document)
                WITH ck, count(DISTINCT i) as info_count, count(DISTINCT d) as doc_count
                RETURN info_count, doc_count
            """, ck_id=claimkey_id, tenant_id=self.tenant_id).single()

            if not result:
                return ClaimKeyStatus.ORPHAN

            info_count = result["info_count"]
            doc_count = result["doc_count"]

            # Déterminer le statut
            if info_count == 0:
                new_status = ClaimKeyStatus.ORPHAN
            elif doc_count < 2:
                new_status = ClaimKeyStatus.EMERGENT
            else:
                new_status = ClaimKeyStatus.COMPARABLE

            # Mettre à jour
            session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                SET ck.status = $status,
                    ck.info_count = $info_count,
                    ck.doc_count = $doc_count,
                    ck.updated_at = datetime()
            """, ck_id=claimkey_id, tenant_id=self.tenant_id,
                status=new_status.value, info_count=info_count, doc_count=doc_count)

            logger.info(
                f"[CLAIMKEY] Updated {claimkey_id}: "
                f"status={new_status.value}, infos={info_count}, docs={doc_count}"
            )
            return new_status

    def link_information(
        self,
        information_id: str,
        claimkey_id: str
    ) -> bool:
        """
        Lie une Information à un ClaimKey.

        Returns:
            True si lien créé
        """
        with self.neo4j_driver.session() as session:
            result = session.run("""
                MATCH (i:Information {information_id: $info_id, tenant_id: $tenant_id})
                MATCH (ck:ClaimKey {claimkey_id: $ck_id, tenant_id: $tenant_id})
                MERGE (i)-[r:ANSWERS]->(ck)
                SET i.claimkey_id = $ck_id,
                    i.promotion_status = 'PROMOTED_LINKED'
                RETURN r
            """, info_id=information_id, ck_id=claimkey_id, tenant_id=self.tenant_id)

            return result.single() is not None
```

---

## 4. Module API Challenge

### 4.1 `challenge.py` (router) - CRÉER

```python
# src/knowbase/api/routers/challenge.py
"""
Endpoint API Challenge pour MVP V1.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ..services.challenge_service import TextChallenger, ChallengeResponse
from ..dependencies import get_neo4j_driver

router = APIRouter(prefix="/api/v2/challenge", tags=["Challenge"])


class ChallengeRequest(BaseModel):
    """Requête de challenge."""
    text: str = Field(..., description="Texte à challenger", min_length=10)
    tenant_id: str = Field(default="default")
    context: Optional[dict] = Field(
        default=None,
        description="Contexte optionnel (edition, region, product)"
    )
    include_missing: bool = Field(
        default=True,
        description="Inclure les claims non documentés"
    )


@router.post("/", response_model=ChallengeResponse)
async def challenge_text(
    request: ChallengeRequest,
    neo4j_driver=Depends(get_neo4j_driver)
):
    """
    Challenge un texte utilisateur contre le corpus documentaire.

    Retourne pour chaque claim:
    - CONFIRMED: Validé par le corpus
    - CONTRADICTED: Contredit par le corpus
    - PARTIAL: Trouvé mais non comparable
    - MISSING: Sujet documenté, valeur absente
    - UNMAPPED: Pas de pattern reconnu
    """
    challenger = TextChallenger(neo4j_driver, request.tenant_id)

    try:
        result = await challenger.challenge(
            text=request.text,
            context=request.context,
            include_missing=request.include_missing
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "service": "challenge"}
```

### 4.2 `challenge_service.py` - CRÉER

Déjà détaillé dans la spec technique principale. Les modifications par rapport à la spec :
- Utilisation des modèles définis ci-dessus
- Import des singletons (`get_claimkey_patterns`, etc.)

---

## 5. Module Logging

### 5.1 `extraction_logger.py` - CRÉER

```python
# src/knowbase/logging/extraction_logger.py
"""
Logger exhaustif pour extractions MVP V1.
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

        accepted = sum(1 for l in self.logs if l.action == "ACCEPT")
        rejected = sum(1 for l in self.logs if l.action == "REJECT")
        linked = sum(1 for l in self.logs if l.promotion_status == "PROMOTED_LINKED")
        unlinked = sum(1 for l in self.logs if l.promotion_status == "PROMOTED_UNLINKED")

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
        unlinked_logs = [l for l in self.logs if l.promotion_status == "PROMOTED_UNLINKED"]

        keywords = {}
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
                "samples": [l.assertion_text for l in unlinked_logs[:20]]
            }, f, indent=2, ensure_ascii=False)


# Instance par tenant
_loggers: dict[str, ExtractionLogger] = {}


def get_extraction_logger(tenant_id: str) -> ExtractionLogger:
    """Retourne le logger pour un tenant."""
    if tenant_id not in _loggers:
        _loggers[tenant_id] = ExtractionLogger(tenant_id)
    return _loggers[tenant_id]
```

---

## 6. Configuration

### 6.1 `config/prompts.yaml` - MODIFIER

Ajouter la section `pass1_3_mvp_v1`:

```yaml
pass1_3_mvp_v1:
  system: |
    Tu es un extracteur de faits documentaires. Tu extrais TOUTES les assertions
    factuelles explicites du texte, sans interprétation ni inférence.

    RÈGLES ABSOLUES:
    1. Citation exacte OBLIGATOIRE (exact_quote = verbatim du texte)
    2. Position OBLIGATOIRE (page, paragraphe si visible)
    3. Ne JAMAIS rejeter une assertion pour "pas de concept"
    4. Ne JAMAIS inférer ce qui n'est pas explicitement écrit

    TYPES:
    - PRESCRIPTIVE: Obligations ("must", "shall", "required")
    - DEFINITIONAL: Définitions ("is", "uses", "provides")
    - CAUSAL: Cause-effet ("because", "therefore")
    - COMPARATIVE: Comparaisons ("more than", "unlike")

    RHETORICAL ROLES:
    - fact: Assertion factuelle
    - example: Illustration (PAS de ClaimKey)
    - definition: Définition de terme
    - instruction: Procédure
    - claim: Affirmation non vérifiée
    - caution: Avertissement

  user: |
    Document: {{document_title}}
    Page: {{page_number}}
    Context: {{doc_context_frame}}

    Texte:
    """
    {{chunk_text}}
    """

    Extrais TOUTES les assertions factuelles. JSON:
    {
      "assertions": [
        {
          "text": "assertion claire",
          "exact_quote": "verbatim exact",
          "type": "PRESCRIPTIVE|DEFINITIONAL|CAUSAL|COMPARATIVE",
          "rhetorical_role": "fact|example|definition|instruction|claim|caution",
          "span": {"page": int, "paragraph": int},
          "context_override": {"edition": "", "region": ""},
          "confidence": 0.0-1.0
        }
      ]
    }
```

---

## 7. Schéma Neo4j

### 7.1 Contraintes et Index à Créer

```cypher
// Contraintes unicité
CREATE CONSTRAINT information_id IF NOT EXISTS
FOR (i:Information) REQUIRE i.information_id IS UNIQUE;

CREATE CONSTRAINT claimkey_id IF NOT EXISTS
FOR (ck:ClaimKey) REQUIRE ck.claimkey_id IS UNIQUE;

CREATE CONSTRAINT contradiction_id IF NOT EXISTS
FOR (c:Contradiction) REQUIRE c.contradiction_id IS UNIQUE;

// Index pour recherche
CREATE INDEX information_tenant IF NOT EXISTS
FOR (i:Information) ON (i.tenant_id);

CREATE INDEX information_status IF NOT EXISTS
FOR (i:Information) ON (i.promotion_status);

CREATE INDEX information_fingerprint IF NOT EXISTS
FOR (i:Information) ON (i.fingerprint);

CREATE INDEX claimkey_tenant IF NOT EXISTS
FOR (ck:ClaimKey) ON (ck.tenant_id);

CREATE INDEX claimkey_status IF NOT EXISTS
FOR (ck:ClaimKey) ON (ck.status);

CREATE INDEX claimkey_key IF NOT EXISTS
FOR (ck:ClaimKey) ON (ck.key);
```

---

## 8. Résumé des Dépendances

### 8.1 Ordre de Création

```
1. Models (pas de dépendances)
   ├── information.py
   ├── claimkey.py
   └── contradiction.py

2. Logging (dépend de Models)
   └── extraction_logger.py

3. Pass1 (dépend de Models, Logging)
   ├── value_extractor.py
   ├── promotion_policy.py
   └── assertion_extractor.py (MODIFIER)

4. ClaimKey (dépend de Models)
   ├── patterns.py
   └── status_manager.py

5. API (dépend de tout)
   ├── challenge.py (router)
   └── challenge_service.py

6. Config
   └── prompts.yaml (MODIFIER)

7. Neo4j
   └── Contraintes et index
```

### 8.2 Imports Critiques

Chaque module doit importer depuis le bon endroit :

```python
# Dans assertion_extractor.py
from ..models.information import Information, InformationType, ...
from .value_extractor import ValueExtractor
from .promotion_policy import get_promotion_policy
from ...logging.extraction_logger import get_extraction_logger

# Dans challenge_service.py
from ..models.information import Information
from ..models.claimkey import ClaimKey, ClaimKeyStatus
from ..stratified.claimkey.patterns import get_claimkey_patterns
from ..stratified.pass1.value_extractor import ValueExtractor
```

---

*Spec Implémentation Classes MVP V1*
*Référence : SPEC_TECHNIQUE_MVP_V1_USAGE_B.md v1.0*
*Date : 2026-01-25*
