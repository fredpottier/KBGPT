# Phase 2 OSMOSE - Pattern-Based Relation Extraction
# J4-J7 : Regex patterns + spaCy dependency parsing

import re
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime
import uuid

from knowbase.relations.types import (
    RelationType,
    TypedRelation,
    RelationMetadata,
    ExtractionMethod,
    RelationStrength,
    RelationStatus
)

logger = logging.getLogger(__name__)


# ===================================================================
# PATTERNS MULTILINGUES (EN, FR, DE, ES)
# Référence: PHASE2_RELATION_TYPES_REFERENCE.md
# ===================================================================

PATTERNS_PART_OF = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:is a |is an )?(?:component|module|part|element)\s+of\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:includes|contains|comprises)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:consists of|is composed of)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:est un |est une )?(?:composant|module|partie)\s+de\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:inclut|contient|comprend)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:ist ein |ist eine )?(?:Komponente|Modul|Teil)\s+von\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:enthält|umfasst|beinhaltet)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:es un |es una )?(?:componente|módulo|parte)\s+de\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:incluye|contiene|comprende)\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_SUBTYPE_OF = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:is a |is an )(?:type of|kind of|form of|variant of)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:belongs to|falls under)\s+(?:the )?(?:category|class)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:est un |est une )?(?:type de|sorte de|forme de|variante de)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:appartient à|relève de)\s+(?:la |le )?(?:catégorie|classe)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:ist ein |ist eine )?(?:Art von|Typ von|Form von|Variante von)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:gehört zur|fällt unter)\s+(?:Kategorie|Klasse)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:es un |es una )?(?:tipo de|clase de|forma de|variante de)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:pertenece a|cae bajo)\s+(?:la |el )?(?:categoría|clase)\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_REQUIRES = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:requires|needs|depends on|necessitates)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:is )?(?:mandatory|essential|prerequisite)\s+for\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:nécessite|requiert|dépend de|a besoin de)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:est )?(?:obligatoire|essentiel|prérequis)\s+pour\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:erfordert|benötigt|setzt voraus|hängt ab von)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:ist )?(?:obligatorisch|zwingend|Voraussetzung)\s+für\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:requiere|necesita|depende de)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:es )?(?:obligatorio|esencial|requisito previo)\s+para\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_USES = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:uses|utilizes|leverages|employs)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:can use|optionally uses|may integrate with)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:utilise|exploite|emploie|se sert de)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:peut utiliser|utilise optionnellement)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:nutzt|verwendet|benutzt|setzt ein)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:kann nutzen|optional verwendet)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:usa|utiliza|emplea|aprovecha)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:puede usar|usa opcionalmente)\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_INTEGRATES_WITH = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:integrates with|interfaces with|connects to)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:is compatible with|works with)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:s'intègre avec|se connecte à|interface avec)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:est compatible avec|fonctionne avec)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:integriert sich mit|verbindet sich mit|schnittstellt mit)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:ist kompatibel mit|funktioniert mit)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:se integra con|se conecta a|interfaz con)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:es compatible con|funciona con)\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_VERSION_OF = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:version |release |V|v)(\d+(?:\.\d+)*)",
        r"(\w+(?:\s+\w+){0,3})\s+(\d{4}(?:\.\w+)?)\s+(?:version|release|edition)",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:version |release |V|v)(\d+(?:\.\d+)*)",
        r"(\w+(?:\s+\w+){0,3})\s+(\d{4}(?:\.\w+)?)\s+(?:version|édition)",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:Version |Release |V|v)(\d+(?:\.\d+)*)",
        r"(\w+(?:\s+\w+){0,3})\s+(\d{4}(?:\.\w+)?)\s+(?:Version|Ausgabe)",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:versión |release |V|v)(\d+(?:\.\d+)*)",
        r"(\w+(?:\s+\w+){0,3})\s+(\d{4}(?:\.\w+)?)\s+(?:versión|edición)",
    ],
}

PATTERNS_REPLACES = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:replaces|supersedes|succeeds)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:is the successor to|comes after)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:remplace|succède à|supplante)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:est le successeur de|vient après)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:ersetzt|löst ab|folgt auf)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:ist der Nachfolger von|kommt nach)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:reemplaza|sustituye|sucede a)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:es el sucesor de|viene después de)\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_DEPRECATES = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:deprecates|obsoletes|discontinues)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:is deprecated|is obsolete|is end-of-life)",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:déprécié|obsolète|abandonné)",
        r"(\w+(?:\s+\w+){0,3})\s+(?:rend obsolète|met fin à)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:veraltet|überholt|eingestellt)",
        r"(\w+(?:\s+\w+){0,3})\s+(?:macht veraltet|stellt ein)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:obsoleto|descontinuado|deprecado)",
        r"(\w+(?:\s+\w+){0,3})\s+(?:hace obsoleto|discontinúa)\s+(\w+(?:\s+\w+){0,3})",
    ],
}

PATTERNS_PRECEDES = {
    "EN": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:precedes|comes before|is before)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:followed by|succeeded by)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "FR": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:précède|vient avant)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:suivi de|succédé par)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "DE": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:geht voraus|kommt vor)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:gefolgt von)\s+(\w+(?:\s+\w+){0,3})",
    ],
    "ES": [
        r"(\w+(?:\s+\w+){0,3})\s+(?:precede|viene antes de)\s+(\w+(?:\s+\w+){0,3})",
        r"(\w+(?:\s+\w+){0,3})\s+(?:seguido de|sucedido por)\s+(\w+(?:\s+\w+){0,3})",
    ],
}


# Mapping patterns → relation types
PATTERN_REGISTRY = {
    RelationType.PART_OF: PATTERNS_PART_OF,
    RelationType.SUBTYPE_OF: PATTERNS_SUBTYPE_OF,
    RelationType.REQUIRES: PATTERNS_REQUIRES,
    RelationType.USES: PATTERNS_USES,
    RelationType.INTEGRATES_WITH: PATTERNS_INTEGRATES_WITH,
    RelationType.VERSION_OF: PATTERNS_VERSION_OF,
    RelationType.REPLACES: PATTERNS_REPLACES,
    RelationType.DEPRECATES: PATTERNS_DEPRECATES,
    RelationType.PRECEDES: PATTERNS_PRECEDES,
}


class PatternMatcher:
    """
    Pattern-based relation extraction (regex + spaCy).

    Stratégies :
    - Regex patterns multilingues (EN, FR, DE, ES)
    - spaCy dependency parsing (TODO J5)
    - Co-occurrence scoring
    - Decision trees (PART_OF vs SUBTYPE_OF, REQUIRES vs USES)

    Phase 2 OSMOSE - J4-J7
    """

    def __init__(self, languages: List[str] = None):
        """
        Initialise PatternMatcher.

        Args:
            languages: Langues à supporter (default: ["EN", "FR", "DE", "ES"])
        """
        self.languages = languages or ["EN", "FR", "DE", "ES"]

        # Compiler regex patterns
        self.compiled_patterns = self._compile_patterns()

        logger.info(
            f"[OSMOSE:PatternMatcher] Initialized "
            f"(languages={self.languages}, patterns={len(self.compiled_patterns)})"
        )

    def _compile_patterns(self) -> Dict[RelationType, List[re.Pattern]]:
        """Compiler tous les patterns regex."""
        compiled = {}

        for rel_type, lang_patterns in PATTERN_REGISTRY.items():
            compiled[rel_type] = []

            for lang in self.languages:
                if lang in lang_patterns:
                    for pattern_str in lang_patterns[lang]:
                        try:
                            pattern = re.compile(pattern_str, re.IGNORECASE)
                            compiled[rel_type].append(pattern)
                        except re.error as e:
                            logger.warning(
                                f"[OSMOSE:PatternMatcher] Invalid pattern for {rel_type}/{lang}: {e}"
                            )

        return compiled

    def extract_relations(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> List[TypedRelation]:
        """
        Extraire relations via patterns regex.

        Args:
            concepts: Liste concepts canoniques
            full_text: Texte complet document
            document_id: ID document
            document_name: Nom document
            chunk_ids: IDs chunks Qdrant (optionnel)

        Returns:
            Liste relations candidates (confidence 0.5-0.8)
        """
        logger.info(
            f"[OSMOSE:PatternMatcher] Extracting from {len(concepts)} concepts, "
            f"{len(full_text)} chars"
        )

        relations = []

        # Pour chaque type de relation, appliquer patterns
        for rel_type, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                matches = pattern.finditer(full_text)

                for match in matches:
                    # Extraire source et target depuis regex groups
                    if len(match.groups()) >= 2:
                        source_text = match.group(1).strip()
                        target_text = match.group(2).strip()

                        # Matcher avec concepts connus
                        source_concept = self._match_concept(source_text, concepts)
                        target_concept = self._match_concept(target_text, concepts)

                        if source_concept and target_concept:
                            # Créer relation
                            relation = self._create_relation(
                                relation_type=rel_type,
                                source_concept=source_concept,
                                target_concept=target_concept,
                                evidence=match.group(0),
                                document_id=document_id,
                                document_name=document_name,
                                chunk_ids=chunk_ids
                            )
                            relations.append(relation)

        logger.info(
            f"[OSMOSE:PatternMatcher] Extracted {len(relations)} relations "
            f"({len(set(r.relation_type for r in relations))} types)"
        )

        return relations

    def _match_concept(
        self,
        text: str,
        concepts: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Matcher texte extrait avec concept connu.

        Args:
            text: Texte extrait du pattern (ex: "SAP S/4HANA")
            concepts: Liste concepts disponibles

        Returns:
            concept_id si match trouvé, None sinon
        """
        text_lower = text.lower()

        for concept in concepts:
            # Match exact sur canonical_name
            if concept["canonical_name"].lower() == text_lower:
                return concept["concept_id"]

            # Match sur surface_forms
            surface_forms = concept.get("surface_forms", [])
            for form in surface_forms:
                if form.lower() == text_lower:
                    return concept["concept_id"]

        return None

    def _create_relation(
        self,
        relation_type: RelationType,
        source_concept: str,
        target_concept: str,
        evidence: str,
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> TypedRelation:
        """Créer TypedRelation depuis match pattern."""
        relation_id = f"rel-{uuid.uuid4()}"

        # Confidence pattern-based : 0.6-0.7 (sera ajustée par LLM)
        confidence = 0.65

        metadata = RelationMetadata(
            confidence=confidence,
            extraction_method=ExtractionMethod.PATTERN,
            source_doc_id=document_id,
            source_chunk_ids=chunk_ids or [],
            language="MULTI",  # Patterns multilingues
            created_at=datetime.utcnow(),
            strength=RelationStrength.MODERATE,
            status=RelationStatus.ACTIVE,
            require_validation=False
        )

        relation = TypedRelation(
            relation_id=relation_id,
            source_concept=source_concept,
            target_concept=target_concept,
            relation_type=relation_type,
            metadata=metadata,
            evidence=evidence[:200],  # Limiter evidence à 200 chars
            context=None  # Sera rempli par LLM si nécessaire
        )

        return relation
