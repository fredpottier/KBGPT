"""
NormalizationEngine - Moteur de normalisation avec config YAML.

ADR: doc/ongoing/ADR_MARKER_NORMALIZATION_LAYER.md

Fonctionnalités:
1. Parser config YAML tenant (aliases + rules)
2. Moteur de règles (exact alias, regex patterns)
3. Entity Anchor detection depuis les concepts du document
4. Safe-by-default: Si normalisation incertaine → reste "unresolved"

Principe fondamental:
> La normalisation n'a pas pour objectif d'augmenter le recall.
> Elle a pour objectif d'augmenter la cohérence.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import re
import logging
from pathlib import Path

import yaml

from knowbase.consolidation.normalization.models import (
    MarkerMention,
    CanonicalMarker,
    NormalizationRule,
    NormalizationResult,
    NormalizationStatus,
    LexicalShape,
)
from knowbase.consolidation.normalization.normalization_store import (
    NormalizationStore,
    get_normalization_store,
)

logger = logging.getLogger(__name__)


@dataclass
class NormalizationConfig:
    """
    Configuration de normalisation pour un tenant.

    Chargée depuis YAML (config/normalization/{tenant_id}.yaml)
    """
    tenant_id: str = "default"
    version: str = "1.0"

    # Aliases exacts (raw_marker → canonical_form)
    aliases: Dict[str, str] = field(default_factory=dict)

    # Règles regex
    rules: List[NormalizationRule] = field(default_factory=list)

    # Blacklist (faux positifs à rejeter)
    blacklist: List[str] = field(default_factory=list)

    # Contraintes de sécurité
    require_entity_for_ambiguous: bool = True
    auto_apply_threshold: float = 0.95
    max_aliases: int = 100
    single_entity_required: bool = True


class NormalizationEngine:
    """
    Moteur de normalisation des markers.

    Workflow:
    1. Charger config YAML tenant
    2. Pour chaque mention:
       a. Vérifier blacklist → BLACKLISTED
       b. Chercher alias exact → RESOLVED
       c. Appliquer règles regex (avec Entity Anchor si requis)
       d. Si aucune règle ne match → UNRESOLVED

    Safe-by-default: En cas de doute, laisser UNRESOLVED.
    """

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self._config: Optional[NormalizationConfig] = None
        self._store: Optional[NormalizationStore] = None

    def _get_store(self) -> NormalizationStore:
        """Lazy init du store."""
        if self._store is None:
            self._store = get_normalization_store(self.tenant_id)
        return self._store

    # =========================================================================
    # Config Loading
    # =========================================================================

    def load_config(self, config_path: Optional[str] = None) -> NormalizationConfig:
        """
        Charge la configuration depuis un fichier YAML.

        Args:
            config_path: Chemin vers le fichier YAML (ou default)

        Returns:
            NormalizationConfig chargée
        """
        if config_path is None:
            # Default path
            config_path = f"config/normalization/{self.tenant_id}.yaml"

        path = Path(config_path)

        if not path.exists():
            logger.warning(
                f"[NormalizationEngine] Config not found: {config_path}, using defaults"
            )
            self._config = NormalizationConfig(tenant_id=self.tenant_id)
            return self._config

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            self._config = self._parse_config(data)
            logger.info(
                f"[NormalizationEngine] Loaded config: "
                f"{len(self._config.aliases)} aliases, "
                f"{len(self._config.rules)} rules, "
                f"{len(self._config.blacklist)} blacklisted"
            )
            return self._config

        except Exception as e:
            logger.error(f"[NormalizationEngine] Failed to load config: {e}")
            self._config = NormalizationConfig(tenant_id=self.tenant_id)
            return self._config

    def _parse_config(self, data: Dict[str, Any]) -> NormalizationConfig:
        """Parse les données YAML en NormalizationConfig."""
        config = NormalizationConfig(
            tenant_id=data.get("tenant_id", self.tenant_id),
            version=data.get("version", "1.0"),
            aliases=data.get("aliases", {}),
            blacklist=data.get("blacklist", []),
        )

        # Parse rules
        rules_data = data.get("rules", [])
        for rule_data in rules_data:
            rule = NormalizationRule(
                id=rule_data.get("id", ""),
                description=rule_data.get("description", ""),
                pattern=rule_data.get("pattern", ""),
                is_regex=True,  # Les rules sont toujours regex
                requires_entity=rule_data.get("requires_entity", False),
                requires_base_version=rule_data.get("requires_base_version", False),
                output_template=rule_data.get("output_template", ""),
                priority=rule_data.get("priority", 0),
                confidence=rule_data.get("confidence", 1.0),
                enabled=rule_data.get("enabled", True),
            )
            config.rules.append(rule)

        # Sort rules by priority (desc)
        config.rules.sort(key=lambda r: r.priority, reverse=True)

        # Parse constraints
        constraints = data.get("constraints", {})
        config.require_entity_for_ambiguous = constraints.get(
            "require_entity_for_ambiguous", True
        )
        config.auto_apply_threshold = constraints.get("auto_apply_threshold", 0.95)
        config.max_aliases = constraints.get("max_aliases", 100)
        config.single_entity_required = constraints.get("single_entity_required", True)

        return config

    def get_config(self) -> NormalizationConfig:
        """Retourne la config chargée ou la charge si nécessaire."""
        if self._config is None:
            self.load_config()
        return self._config

    # =========================================================================
    # Entity Anchor Detection
    # =========================================================================

    async def find_entity_anchors(
        self,
        doc_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Trouve les Entity Anchors dans un document.

        Un Entity Anchor est un concept du document qui peut servir
        de contexte pour normaliser un marker (ex: "SAP S/4HANA", "Renault Clio").

        Args:
            doc_id: ID du document

        Returns:
            Liste de concepts candidats comme Entity Anchors
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )

        # Chercher les concepts de type "product", "system", "platform"
        # ou avec un nombre élevé de mentions
        query = """
        MATCH (pc:ProtoConcept)-[:EXTRACTED_FROM]->(d:Document {doc_id: $doc_id})
        WHERE pc.tenant_id = $tenant_id

        // Optionnel: lien vers canonical
        OPTIONAL MATCH (pc)-[:INSTANCE_OF]->(cc:CanonicalConcept)

        // Compter les mentions de ce concept dans le doc
        WITH pc, cc, count(pc) AS mentions

        // Filtrer les candidats entity anchor
        // (concept avec beaucoup de mentions ou dans le titre)
        WHERE mentions >= 2
           OR pc.role IN ['primary', 'subject']

        RETURN
            pc.concept_id AS concept_id,
            pc.concept_name AS name,
            COALESCE(cc.canonical_name, pc.concept_name) AS canonical_name,
            mentions,
            pc.role AS role
        ORDER BY mentions DESC
        LIMIT 5
        """

        try:
            with client.driver.session(database="neo4j") as session:
                result = session.run(
                    query,
                    doc_id=doc_id,
                    tenant_id=self.tenant_id
                )
                anchors = [dict(record) for record in result]
                logger.debug(
                    f"[NormalizationEngine] Found {len(anchors)} entity anchors for doc {doc_id}"
                )
                return anchors
        except Exception as e:
            logger.error(f"[NormalizationEngine] Entity anchor search failed: {e}")
            return []

    def _select_best_entity_anchor(
        self,
        anchors: List[Dict[str, Any]],
    ) -> Optional[str]:
        """
        Sélectionne le meilleur Entity Anchor parmi les candidats.

        Args:
            anchors: Liste de candidats

        Returns:
            Nom de l'entity anchor ou None
        """
        if not anchors:
            return None

        config = self.get_config()

        # Si single_entity_required et plusieurs candidats avec mentions égales → None
        if config.single_entity_required and len(anchors) > 1:
            top_mentions = anchors[0].get("mentions", 0)
            ties = [a for a in anchors if a.get("mentions", 0) == top_mentions]
            if len(ties) > 1:
                logger.debug(
                    f"[NormalizationEngine] Multiple entity anchors with same weight, "
                    f"returning None (single_entity_required=True)"
                )
                return None

        # Retourner le canonical_name du premier
        return anchors[0].get("canonical_name") or anchors[0].get("name")

    # =========================================================================
    # Normalization Logic
    # =========================================================================

    async def normalize_mention(
        self,
        mention: MarkerMention,
        entity_anchor: Optional[str] = None,
        base_version: Optional[str] = None,
    ) -> NormalizationResult:
        """
        Normalise une MarkerMention.

        Workflow:
        1. Blacklist check → BLACKLISTED
        2. Alias exact → RESOLVED
        3. Règles regex → RESOLVED si match
        4. Sinon → UNRESOLVED

        Args:
            mention: MarkerMention à normaliser
            entity_anchor: Entity Anchor connu (optionnel)
            base_version: Version de base si connue (pour patches)

        Returns:
            NormalizationResult avec status et canonical si résolu
        """
        config = self.get_config()
        raw_text = mention.raw_text.strip()

        # 1. Blacklist check
        if raw_text in config.blacklist or raw_text.lower() in [b.lower() for b in config.blacklist]:
            logger.debug(f"[NormalizationEngine] '{raw_text}' is blacklisted")
            return NormalizationResult(
                mention=mention,
                status=NormalizationStatus.BLACKLISTED,
                reason="Marker in blacklist",
            )

        # 2. Alias exact
        if raw_text in config.aliases:
            canonical_form = config.aliases[raw_text]
            canonical = await self._get_store().ensure_canonical_marker(
                canonical_form=canonical_form,
                created_by="alias:exact",
                entity_anchor=entity_anchor or "",
            )
            return NormalizationResult(
                mention=mention,
                status=NormalizationStatus.RESOLVED,
                canonical_marker=canonical,
                rule_applied="alias:exact",
                entity_anchor_found=entity_anchor,
                confidence=1.0,
                reason=f"Exact alias: {raw_text} → {canonical_form}",
            )

        # 3. Règles regex
        for rule in config.rules:
            if not rule.enabled:
                continue

            result = self._try_rule(
                mention, rule, entity_anchor, base_version
            )
            if result is not None:
                return result

        # 4. Aucune normalisation possible
        return NormalizationResult(
            mention=mention,
            status=NormalizationStatus.UNRESOLVED,
            reason="No matching rule or alias",
        )

    def _try_rule(
        self,
        mention: MarkerMention,
        rule: NormalizationRule,
        entity_anchor: Optional[str],
        base_version: Optional[str],
    ) -> Optional[NormalizationResult]:
        """
        Tente d'appliquer une règle regex à une mention.

        Args:
            mention: MarkerMention
            rule: NormalizationRule à tester
            entity_anchor: Entity Anchor disponible
            base_version: Version de base si connue

        Returns:
            NormalizationResult si la règle match, None sinon
        """
        raw_text = mention.raw_text.strip()

        # Vérifier les requirements
        if rule.requires_entity and not entity_anchor:
            return None

        if rule.requires_base_version and not base_version:
            return None

        # Tester le pattern
        try:
            match = re.match(rule.pattern, raw_text, re.IGNORECASE)
            if not match:
                return None
        except re.error as e:
            logger.warning(f"[NormalizationEngine] Invalid regex in rule {rule.id}: {e}")
            return None

        # Construire la forme canonique
        canonical_form = self._build_canonical_form(
            rule.output_template,
            match,
            entity_anchor,
            base_version,
        )

        if not canonical_form:
            return None

        # Note: On ne crée pas le canonical ici car on est sync
        # On retourne juste le résultat avec les infos pour création
        return NormalizationResult(
            mention=mention,
            status=NormalizationStatus.RESOLVED,
            canonical_marker=CanonicalMarker(
                canonical_form=canonical_form,
                entity_anchor=entity_anchor or "",
                created_by=f"rule:{rule.id}",
                confidence=rule.confidence,
                tenant_id=self.tenant_id,
            ),
            rule_applied=rule.id,
            entity_anchor_found=entity_anchor,
            confidence=rule.confidence,
            reason=f"Rule {rule.id}: {raw_text} → {canonical_form}",
        )

    def _build_canonical_form(
        self,
        template: str,
        match: re.Match,
        entity_anchor: Optional[str],
        base_version: Optional[str],
    ) -> Optional[str]:
        """
        Construit la forme canonique depuis un template.

        Template placeholders:
        - {entity}: Entity Anchor
        - {base_version}: Version de base
        - {$1}, {$2}, ...: Capture groups du regex

        Args:
            template: Template de sortie
            match: Match object du regex
            entity_anchor: Entity Anchor
            base_version: Version de base

        Returns:
            Forme canonique ou None si construction échoue
        """
        result = template

        # Remplacer {entity}
        if "{entity}" in result:
            if not entity_anchor:
                return None
            result = result.replace("{entity}", entity_anchor)

        # Remplacer {base_version}
        if "{base_version}" in result:
            if not base_version:
                return None
            result = result.replace("{base_version}", base_version)

        # Remplacer capture groups {$1}, {$2}, etc.
        for i, group in enumerate(match.groups(), 1):
            result = result.replace(f"{{${i}}}", group or "")

        return result.strip()

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def normalize_document_mentions(
        self,
        doc_id: str,
    ) -> List[NormalizationResult]:
        """
        Normalise toutes les mentions d'un document.

        1. Récupère les mentions du document
        2. Trouve les Entity Anchors
        3. Normalise chaque mention
        4. Persiste les résultats

        Args:
            doc_id: ID du document

        Returns:
            Liste de NormalizationResult
        """
        store = self._get_store()

        # 1. Récupérer les mentions
        mentions = await store.get_mentions_by_doc(doc_id)
        if not mentions:
            logger.debug(f"[NormalizationEngine] No mentions for doc {doc_id}")
            return []

        # 2. Trouver les Entity Anchors
        anchors = await self.find_entity_anchors(doc_id)
        entity_anchor = self._select_best_entity_anchor(anchors)

        if entity_anchor:
            logger.info(
                f"[NormalizationEngine] Using entity anchor '{entity_anchor}' for doc {doc_id}"
            )

        # 3. Normaliser chaque mention
        results = []
        for mention in mentions:
            result = await self.normalize_mention(
                mention,
                entity_anchor=entity_anchor,
            )
            results.append(result)

            # 4. Persister si résolu
            if result.status == NormalizationStatus.RESOLVED and result.canonical_marker:
                # Créer le canonical dans Neo4j
                canonical = await store.ensure_canonical_marker(
                    canonical_form=result.canonical_marker.canonical_form,
                    marker_type=result.canonical_marker.marker_type,
                    entity_anchor=result.canonical_marker.entity_anchor,
                    created_by=result.canonical_marker.created_by,
                    confidence=result.canonical_marker.confidence,
                )
                # Lier mention → canonical
                await store.link_mention_to_canonical(
                    mention_id=mention.id,
                    canonical_id=canonical.id,
                    rule_id=result.rule_applied or "",
                    confidence=result.confidence,
                )
            elif result.status in (NormalizationStatus.BLACKLISTED, NormalizationStatus.UNRESOLVED):
                # Mettre à jour le statut
                await store.update_mention_status(
                    mention_id=mention.id,
                    status=result.status,
                    reason=result.reason,
                )

        # Stats
        resolved = sum(1 for r in results if r.status == NormalizationStatus.RESOLVED)
        blacklisted = sum(1 for r in results if r.status == NormalizationStatus.BLACKLISTED)
        unresolved = sum(1 for r in results if r.status == NormalizationStatus.UNRESOLVED)

        logger.info(
            f"[NormalizationEngine] Normalized doc {doc_id}: "
            f"{resolved} resolved, {blacklisted} blacklisted, {unresolved} unresolved"
        )

        return results

    # =========================================================================
    # Admin Operations
    # =========================================================================

    async def add_alias(
        self,
        raw_marker: str,
        canonical_form: str,
        persist: bool = True,
    ) -> bool:
        """
        Ajoute un alias à la configuration.

        Args:
            raw_marker: Marker brut
            canonical_form: Forme canonique
            persist: Sauvegarder dans le fichier YAML

        Returns:
            True si succès
        """
        config = self.get_config()

        # Vérifier limite
        if len(config.aliases) >= config.max_aliases:
            logger.warning(
                f"[NormalizationEngine] Max aliases reached ({config.max_aliases})"
            )
            return False

        config.aliases[raw_marker] = canonical_form

        if persist:
            # TODO: Implémenter la persistence YAML
            logger.info(f"[NormalizationEngine] Added alias: {raw_marker} → {canonical_form}")

        return True

    async def add_to_blacklist(
        self,
        marker: str,
        persist: bool = True,
    ) -> bool:
        """
        Ajoute un marker à la blacklist.

        Args:
            marker: Marker à blacklister
            persist: Sauvegarder dans le fichier YAML

        Returns:
            True si succès
        """
        config = self.get_config()

        if marker not in config.blacklist:
            config.blacklist.append(marker)

            if persist:
                # TODO: Implémenter la persistence YAML
                logger.info(f"[NormalizationEngine] Added to blacklist: {marker}")

        return True


# =============================================================================
# Singleton
# =============================================================================

_engine_instances: Dict[str, NormalizationEngine] = {}


def get_normalization_engine(tenant_id: str = "default") -> NormalizationEngine:
    """Retourne l'instance singleton du NormalizationEngine pour un tenant."""
    global _engine_instances
    if tenant_id not in _engine_instances:
        _engine_instances[tenant_id] = NormalizationEngine(tenant_id=tenant_id)
    return _engine_instances[tenant_id]


__all__ = [
    "NormalizationConfig",
    "NormalizationEngine",
    "get_normalization_engine",
]
