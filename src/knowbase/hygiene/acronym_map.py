"""AcronymMapBuilder — Mining multi-source des équivalences acronyme ↔ nom complet.

Sources :
  1. Entity names : pattern "NomComplet (ACRONYME)" ou "ACRONYME (NomComplet)"
  2. Claim texts : mêmes patterns dans le texte des claims
  3. DomainContextProfile.common_acronyms

100% déterministe, pas de LLM.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from knowbase.claimfirst.models.entity import Entity

logger = logging.getLogger("[OSMOSE] kg_hygiene_acronym_map")

# ---------------------------------------------------------------------------
# Regex domain-agnostic
# ---------------------------------------------------------------------------

# "Procalcitonin (PCT)" → expansion=Procalcitonin, acronym=PCT
FULL_NAME_THEN_ACRONYM = re.compile(
    r"^(.{3,80}?)\s*\(([A-Z][A-Za-z0-9\-/]{0,10})\)\s*$"
)

# "PCT (Procalcitonin)" → acronym=PCT, expansion=Procalcitonin
ACRONYM_THEN_FULL_NAME = re.compile(
    r"^([A-Z]{2,10})\s*\((.{3,80}?)\)\s*$"
)

# Patterns à exclure des parenthèses (unités, références, p-values)
NOISE_PARENS = re.compile(
    r"^\("
    r"(?:"
    r"[a-z]{0,3}[/·]"          # unités : mg/L, µg/dL
    r"|[nN]\s*=\s*\d"          # (n=42)
    r"|[pP]\s*[<>=]"           # (p<0.05)
    r"|\d+\s*%"                # (95%)
    r"|[Ff]ig(?:ure)?\.?\s*\d" # (Fig. 3)
    r"|[Tt]able\s*\d"          # (Table 1)
    r"|[Ss]ee\s"               # (see above)
    r"|[Ee]\.?g\.?"            # (e.g.)
    r"|[Ii]\.?e\.?"            # (i.e.)
    r"|[Rr]ef\.?\s"            # (ref. 12)
    r"|[Cc]f\.?"               # (cf.)
    r"|\d{4}\s*[-–]\s*\d{4}"  # (2010-2020)
    r"|\d+\s*[-–]\s*\d+\s*%"  # (10-15%)
    r")"
)


def _is_plausible_acronym(text: str) -> bool:
    """Vérifie qu'un texte est un acronyme plausible (2-10 lettres majuscules, tirets/slashs autorisés)."""
    return bool(re.match(r"^[A-Z][A-Za-z0-9\-/]{0,9}$", text)) and len(text) >= 2


def _is_plausible_expansion(text: str) -> bool:
    """Vérifie qu'un texte est une expansion plausible (pas trop long, contient des lettres)."""
    text = text.strip()
    if len(text) < 3 or len(text) > 60:
        return False
    # Doit contenir au moins 2 lettres
    if len(re.findall(r"[a-zA-Z]", text)) < 2:
        return False
    return True


def _normalize_expansion(expansion: str) -> str:
    """Normalise une expansion pour comparaison."""
    return Entity.normalize(expansion)


@dataclass
class AcronymEntry:
    """Entrée de la map acronyme → expansion(s)."""

    acronym: str
    expansions: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    confidence: float = 0.0
    ambiguous: bool = False

    @property
    def primary_expansion(self) -> str:
        """Retourne l'expansion principale (première)."""
        return self.expansions[0] if self.expansions else ""

    @property
    def normalized_expansions(self) -> List[str]:
        """Retourne les expansions normalisées."""
        return [_normalize_expansion(e) for e in self.expansions]


class AcronymMapBuilder:
    """Construit la map acronyme → expansion depuis plusieurs sources."""

    def build(self, neo4j_driver, tenant_id: str) -> Dict[str, AcronymEntry]:
        """Construit la map complète depuis Neo4j + DomainContext."""
        entries: Dict[str, AcronymEntry] = {}

        # Source 1 : Entity names (confidence=1.0)
        self._mine_entity_names(neo4j_driver, tenant_id, entries)

        # Source 2 : Claim texts (confidence=0.8)
        self._mine_claim_texts(neo4j_driver, tenant_id, entries)

        # Source 3 : DomainContext common_acronyms (confidence=0.9)
        self._mine_domain_context(neo4j_driver, tenant_id, entries)

        # Calculer confidence finale et détecter ambiguïtés
        self._finalize(entries)

        logger.info(
            f"AcronymMap: {len(entries)} acronymes extraits "
            f"({sum(1 for e in entries.values() if e.ambiguous)} ambigus)"
        )
        return entries

    def _mine_entity_names(
        self, neo4j_driver, tenant_id: str, entries: Dict[str, AcronymEntry]
    ) -> None:
        """Source 1 : scanner les noms d'Entity avec pattern parenthèses."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})
                WHERE e._hygiene_status IS NULL
                  AND e.name CONTAINS '('
                RETURN e.name AS name
                """,
                tid=tenant_id,
            )
            for record in result:
                name = record["name"]
                self._extract_from_text(name, "entity", entries, confidence=1.0)

    def _mine_claim_texts(
        self, neo4j_driver, tenant_id: str, entries: Dict[str, AcronymEntry]
    ) -> None:
        """Source 2 : scanner les textes de Claims avec pattern parenthèses."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tid})
                WHERE c.text CONTAINS '('
                RETURN c.text AS text
                LIMIT 5000
                """,
                tid=tenant_id,
            )
            for record in result:
                text = record["text"]
                # Extraire tous les segments "mot(s) (ACRONYME)" du texte
                self._extract_inline_acronyms(text, entries)

    def _mine_domain_context(
        self, neo4j_driver, tenant_id: str, entries: Dict[str, AcronymEntry]
    ) -> None:
        """Source 3 : charger common_acronyms du DomainContextProfile."""
        import json

        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (dc:DomainContextProfile {tenant_id: $tid})
                RETURN dc.common_acronyms AS acronyms
                """,
                tid=tenant_id,
            )
            record = result.single()
            if not record or not record["acronyms"]:
                return

            acronyms_raw = record["acronyms"]
            if isinstance(acronyms_raw, str):
                try:
                    acronyms_raw = json.loads(acronyms_raw)
                except (json.JSONDecodeError, TypeError):
                    return

            if not isinstance(acronyms_raw, dict):
                return

            for acr, expansion in acronyms_raw.items():
                if not _is_plausible_acronym(acr) or not _is_plausible_expansion(expansion):
                    continue
                source = f"domain_context:{acr}={expansion}"
                self._add_entry(entries, acr, expansion, source, confidence=0.9)

    def _extract_from_text(
        self,
        text: str,
        source_type: str,
        entries: Dict[str, AcronymEntry],
        confidence: float,
    ) -> None:
        """Tente d'extraire un couple acronyme/expansion depuis un texte entier."""
        text = text.strip()

        # Pattern 1 : "NomComplet (ACRONYME)"
        m = FULL_NAME_THEN_ACRONYM.match(text)
        if m:
            expansion = m.group(1).strip()
            acronym = m.group(2).strip()
            if _is_plausible_acronym(acronym) and _is_plausible_expansion(expansion):
                if not NOISE_PARENS.match(f"({acronym})"):
                    source = f"{source_type}:{text}"
                    self._add_entry(entries, acronym, expansion, source, confidence)
                    return

        # Pattern 2 : "ACRONYME (NomComplet)"
        m = ACRONYM_THEN_FULL_NAME.match(text)
        if m:
            acronym = m.group(1).strip()
            expansion = m.group(2).strip()
            if _is_plausible_acronym(acronym) and _is_plausible_expansion(expansion):
                source = f"{source_type}:{text}"
                # Confidence plus basse pour ce pattern (plus rare, plus risqué)
                self._add_entry(entries, acronym, expansion, source, confidence * 0.7)

    def _extract_inline_acronyms(
        self, text: str, entries: Dict[str, AcronymEntry]
    ) -> None:
        """Extrait les patterns inline 'Expansion (ACRONYME)' depuis un texte libre."""
        # Chercher tous les "mot(s) (CONTENU_PARENS)" dans le texte
        for m in re.finditer(
            r"(\b[A-Z][a-zA-Z\-\s]{2,60}?)\s*\(([A-Z][A-Za-z0-9\-/]{0,10})\)",
            text,
        ):
            expansion = m.group(1).strip()
            acronym = m.group(2).strip()

            # Filtrer le bruit
            if not _is_plausible_acronym(acronym):
                continue
            if not _is_plausible_expansion(expansion):
                continue
            if NOISE_PARENS.match(f"({acronym})"):
                continue

            source = f"claim:{expansion} ({acronym})"
            self._add_entry(entries, acronym, expansion, source, confidence=0.8)

    def _add_entry(
        self,
        entries: Dict[str, AcronymEntry],
        acronym: str,
        expansion: str,
        source: str,
        confidence: float,
    ) -> None:
        """Ajoute ou met à jour une entrée dans la map."""
        acr_upper = acronym.upper()

        if acr_upper not in entries:
            entries[acr_upper] = AcronymEntry(
                acronym=acronym,
                expansions=[expansion],
                sources=[source],
                confidence=confidence,
            )
        else:
            entry = entries[acr_upper]
            # Ajouter la source si pas déjà présente
            if source not in entry.sources:
                entry.sources.append(source)
            # Vérifier si c'est une nouvelle expansion
            norm_new = _normalize_expansion(expansion)
            existing_norms = entry.normalized_expansions
            if norm_new not in existing_norms:
                entry.expansions.append(expansion)
            # Mettre à jour la confidence (max des sources)
            entry.confidence = max(entry.confidence, confidence)

    def _finalize(self, entries: Dict[str, AcronymEntry]) -> None:
        """Calcule confidence finale et détecte les ambiguïtés."""
        for acr, entry in entries.items():
            # Multi-source boost : corpus + domain_context = 1.0
            source_types = set()
            for s in entry.sources:
                if s.startswith("entity:"):
                    source_types.add("entity")
                elif s.startswith("claim:"):
                    source_types.add("claim")
                elif s.startswith("domain_context:"):
                    source_types.add("domain_context")

            if len(source_types) >= 2:
                entry.confidence = max(entry.confidence, 1.0)

            # Ambiguïté : >1 expansion normalisée différente
            unique_norms = set(entry.normalized_expansions)
            if len(unique_norms) > 1:
                entry.ambiguous = True
                logger.info(
                    f"  Acronyme ambigu '{acr}': {entry.expansions} — pas de merge"
                )
