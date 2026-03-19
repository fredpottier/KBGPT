"""Règles Layer 1 — Entités structurelles + stoplist domain context."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
    HygieneRunScope,
)
from knowbase.hygiene.rules.base import HygieneRule

logger = logging.getLogger("[OSMOSE] kg_hygiene_l1_entities")

# Regex pour entités structurelles (artefacts de mise en page)
STRUCTURAL_ENTITY_PATTERN = re.compile(
    r"^(Figure|Table|Appendix|Exhibit|Annexe?|Tableau|Chart|Diagram|Supplement)\s+(\d+\S*|[A-Z]\b|[A-Z]\.\d+|S\d+)"
    r"|^Supplementary\s+(?:Table|Figure|Data|Material|Appendix)\s+\S+",
    re.IGNORECASE,
)


# Mots-outils qui ne doivent jamais commencer un nom d'entité
_LEADING_FUNCTION_WORDS = frozenset({
    "a", "an", "the", "this", "that", "these", "those", "it", "its",
    "to", "of", "in", "on", "at", "by", "for", "with", "from",
    "and", "or", "but", "not", "no", "nor",
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must",
    "he", "she", "we", "they", "you", "me", "him", "us", "them",
    "which", "where", "when", "how", "what", "who", "whom",
    "also", "than", "very", "only", "just",
    "different", "certain", "other", "various", "several",
})

# Pattern pour détecter les références bibliographiques
_BIBLIO_PATTERN = re.compile(r"\bet\s+al[.,]", re.IGNORECASE)

# Pattern pour détecter les noms purement numériques
_NUMERIC_ONLY_PATTERN = re.compile(r"^[\d\s\-_./]+$")


def _classify_invalid_name(name: str) -> Optional[str]:
    """
    Classifie un nom d'entité comme invalide s'il est clairement un artefact.

    Retourne la raison du rejet, ou None si le nom est acceptable.
    Plus conservateur que is_valid_entity_name() — ne rejette que les cas évidents.
    """
    stripped = name.strip()
    if not stripped:
        return "nom vide"

    # Trop long (>100 chars = quasi-certainement une phrase ou un titre d'article)
    if len(stripped) > 100:
        return "phrase ou titre d'article (>100 caractères)"

    # Référence bibliographique
    if _BIBLIO_PATTERN.search(stripped):
        return "référence bibliographique (et al.)"

    # Purement numérique
    if _NUMERIC_ONLY_PATTERN.match(stripped):
        return "code purement numérique"

    # Compter les mots significatifs (hors parenthèses)
    text_no_parens = re.sub(r"\([^)]*\)", "", stripped).strip()
    words = text_no_parens.split()

    # Trop de mots significatifs hors parenthèses (>8 = phrase)
    if len(words) > 8:
        return "trop de mots, probablement une phrase"

    # Premier mot est un mot-outil pur (préposition, pronom, article)
    if words:
        first_lower = words[0].lower()
        if first_lower in _LEADING_FUNCTION_WORDS:
            return f"commence par un mot-outil ('{words[0]}')"

    # Contient des verbes indicateurs de phrase (mais pas dans des parenthèses)
    _PHRASE_VERBS = {"is", "are", "was", "were", "has", "have", "had",
                     "will", "would", "can", "could", "should", "must",
                     "does", "do", "did"}
    words_lower = {w.lower() for w in text_no_parens.split()}
    phrase_verbs_found = words_lower & _PHRASE_VERBS
    # Seulement si le nom a aussi >4 mots (sinon "PD-L1 expression" serait rejeté à tort)
    if phrase_verbs_found and len(words) > 4:
        return f"fragment de phrase (contient '{', '.join(phrase_verbs_found)}')"

    return None


class StructuralEntityRule(HygieneRule):
    """Détecte les entités structurelles (Figure 2, Table 3, Appendix A, etc.)."""

    @property
    def name(self) -> str:
        return "structural_entity"

    @property
    def layer(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Supprime les entités qui sont des artefacts de mise en page (Figure, Table, Appendix...)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        actions = []
        entities = self._load_entities(neo4j_driver, tenant_id, scope, scope_params)

        for entity in entities:
            name = entity.get("name", "")
            entity_id = entity.get("entity_id", "")

            if STRUCTURAL_ENTITY_PATTERN.match(name):
                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_ENTITY,
                    target_node_id=entity_id,
                    target_node_type="Entity",
                    layer=1,
                    confidence=1.0,
                    reason=f"Entité structurelle détectée: '{name}' (artefact de mise en page)",
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.APPLIED,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} entités structurelles détectées")
        return actions

    def _load_entities(
        self, neo4j_driver, tenant_id: str, scope: str, scope_params: dict | None
    ) -> list:
        """Charge les entités selon le scope."""
        with neo4j_driver.session() as session:
            if scope == HygieneRunScope.DOCUMENT_SET.value and scope_params and scope_params.get("doc_ids"):
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity {tenant_id: $tid})
                    WHERE c.doc_id IN $doc_ids
                      AND e._hygiene_status IS NULL
                    RETURN DISTINCT e.entity_id AS entity_id, e.name AS name,
                           e.normalized_name AS normalized_name
                    """,
                    tid=tenant_id,
                    doc_ids=scope_params["doc_ids"],
                )
            else:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})
                    WHERE e._hygiene_status IS NULL
                    RETURN e.entity_id AS entity_id, e.name AS name,
                           e.normalized_name AS normalized_name
                    """,
                    tid=tenant_id,
                )
            return [dict(r) for r in result]


class InvalidEntityNameRule(HygieneRule):
    """
    Détecte les entités dont le nom est clairement un artefact.

    Plus conservatrice que is_valid_entity_name() — ne cible que les cas
    à très haute certitude d'être du bruit :
    - Phrases longues (>80 chars ou >8 mots significatifs)
    - Noms commençant par un verbe/pronom/préposition
    - Références bibliographiques ("et al.", "et al,")
    - Noms purement numériques

    Préserve les patterns scientifiques légitimes :
    - "Concept (Acronyme)" ex: "VAP (Ventilator-Associated Pneumonia)"
    - Noms avec points taxonomiques ex: "B. animalis subsp. lactis BB-12"
    - Noms avec virgules chimiques ex: "(1,3)-beta-D-Glucan"
    - Sites/URLs ex: "ClinicalTrials.gov"
    """

    @property
    def name(self) -> str:
        return "invalid_entity_name"

    @property
    def layer(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Supprime les entités clairement invalides (phrases, refs biblio, fragments)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        actions = []
        entities = self._load_entities(neo4j_driver, tenant_id, scope, scope_params)

        for entity in entities:
            name = entity.get("name", "")
            entity_id = entity.get("entity_id", "")

            if not name:
                continue

            rejection = _classify_invalid_name(name)
            if rejection:
                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_ENTITY,
                    target_node_id=entity_id,
                    target_node_type="Entity",
                    layer=1,
                    confidence=1.0,
                    reason=f"Nom d'entité invalide: '{name}' ({rejection})",
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.APPLIED,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} entités avec noms invalides détectées")
        return actions

    def _load_entities(
        self, neo4j_driver, tenant_id: str, scope: str, scope_params: dict | None
    ) -> list:
        """Charge les entités selon le scope."""
        with neo4j_driver.session() as session:
            if scope == HygieneRunScope.DOCUMENT_SET.value and scope_params and scope_params.get("doc_ids"):
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity {tenant_id: $tid})
                    WHERE c.doc_id IN $doc_ids
                      AND e._hygiene_status IS NULL
                    RETURN DISTINCT e.entity_id AS entity_id, e.name AS name
                    """,
                    tid=tenant_id,
                    doc_ids=scope_params["doc_ids"],
                )
            else:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})
                    WHERE e._hygiene_status IS NULL
                    RETURN e.entity_id AS entity_id, e.name AS name
                    """,
                    tid=tenant_id,
                )
            return [dict(r) for r in result]


class DomainStoplistRule(HygieneRule):
    """Détecte les entités qui matchent la stoplist domain-specific du Domain Context."""

    @property
    def name(self) -> str:
        return "domain_stoplist"

    @property
    def layer(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Supprime les entités matchant la hygiene_entity_stoplist du Domain Context"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        stoplist = self._load_stoplist(neo4j_driver, tenant_id)
        if not stoplist:
            logger.info("  → Pas de hygiene_entity_stoplist configurée")
            return []

        # Normaliser la stoplist pour comparaison case-insensitive
        stoplist_lower = {s.strip().lower() for s in stoplist if s.strip()}

        actions = []
        entities = self._load_entities(neo4j_driver, tenant_id, scope, scope_params)

        for entity in entities:
            name = entity.get("name", "")
            entity_id = entity.get("entity_id", "")
            normalized = entity.get("normalized_name", name).lower().strip()

            if normalized in stoplist_lower or name.lower().strip() in stoplist_lower:
                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_ENTITY,
                    target_node_id=entity_id,
                    target_node_type="Entity",
                    layer=1,
                    confidence=1.0,
                    reason=f"Entité '{name}' dans la stoplist domain-specific",
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.APPLIED,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} entités dans la stoplist domain-specific")
        return actions

    def _load_stoplist(self, neo4j_driver, tenant_id: str) -> List[str]:
        """Charge la stoplist depuis le DomainContextProfile."""
        import json

        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (dc:DomainContextProfile {tenant_id: $tid})
                RETURN dc.hygiene_entity_stoplist AS stoplist
                """,
                tid=tenant_id,
            )
            record = result.single()
            if not record or not record["stoplist"]:
                return []
            try:
                return json.loads(record["stoplist"])
            except (json.JSONDecodeError, TypeError):
                return []

    def _load_entities(
        self, neo4j_driver, tenant_id: str, scope: str, scope_params: dict | None
    ) -> list:
        """Charge les entités selon le scope."""
        with neo4j_driver.session() as session:
            if scope == HygieneRunScope.DOCUMENT_SET.value and scope_params and scope_params.get("doc_ids"):
                result = session.run(
                    """
                    MATCH (c:Claim {tenant_id: $tid})-[:ABOUT]->(e:Entity {tenant_id: $tid})
                    WHERE c.doc_id IN $doc_ids
                      AND e._hygiene_status IS NULL
                    RETURN DISTINCT e.entity_id AS entity_id, e.name AS name,
                           e.normalized_name AS normalized_name
                    """,
                    tid=tenant_id,
                    doc_ids=scope_params["doc_ids"],
                )
            else:
                result = session.run(
                    """
                    MATCH (e:Entity {tenant_id: $tid})
                    WHERE e._hygiene_status IS NULL
                    RETURN e.entity_id AS entity_id, e.name AS name,
                           e.normalized_name AS normalized_name
                    """,
                    tid=tenant_id,
                )
            return [dict(r) for r in result]
