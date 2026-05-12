"""
Validator post-LLM pour LIFECYCLE_RELATION Doc→Doc V2-S1 strict.

Deux validations obligatoires (cf. ADR §4 Discovery doc-doc, version stricte) :
1. evidence_quote DOIT être substring du source full_text (anti-hallucination)
2. target_doc_reference DOIT pouvoir être résolu vers un DocumentContext du KG

Si l'une des deux échoue → REJECTED, pas de persistence.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from neo4j import Driver

from knowbase.lifecycle.models import (
    LifecycleDeclarationCandidate,
    LifecycleExtractionResult,
    ValidatedLifecycleRelation,
    ValidationOutcome,
    ValidationReport,
)

logger = logging.getLogger(__name__)


def _normalize_for_substring_match(text: str) -> str:
    """Normalise pour comparaison robuste : whitespace collapse + lowercase."""
    return re.sub(r"\s+", " ", text).strip().lower()


class LifecycleDeclarationValidator:
    """Validator post-LLM pour les candidates extraites.

    Args:
        driver: Neo4j driver pour résolution target_doc_reference → DocumentContext
        tenant_id: tenant courant (default 'default')
    """

    def __init__(self, driver: Driver, tenant_id: str = "default") -> None:
        self.driver = driver
        self.tenant_id = tenant_id

    def validate_extraction(
        self,
        extraction: LifecycleExtractionResult,
        source_full_text: str,
    ) -> ValidationReport:
        """Valide les candidates d'une extraction.

        Returns:
            ValidationReport avec accepted (à persister) et rejected (audit forensics)
        """
        report = ValidationReport(source_doc_id=extraction.source_doc_id)

        normalized_source = _normalize_for_substring_match(source_full_text)

        for candidate in extraction.declarations:
            # 1. Validation evidence_quote substring
            normalized_quote = _normalize_for_substring_match(candidate.evidence_quote)
            if normalized_quote not in normalized_source:
                report.rejected.append(
                    {
                        "candidate": candidate.model_dump(),
                        "outcome": ValidationOutcome.REJECTED_QUOTE_NOT_IN_SOURCE.value,
                        "reason": f"evidence_quote not found in source full_text (quote_len={len(candidate.evidence_quote)})",
                    }
                )
                continue

            # 2. Résolution target_doc_reference → doc_id
            target_resolution = self._resolve_target_doc(candidate.target_doc_reference)
            if target_resolution["status"] == "not_found":
                report.rejected.append(
                    {
                        "candidate": candidate.model_dump(),
                        "outcome": ValidationOutcome.REJECTED_TARGET_NOT_RESOLVED.value,
                        "reason": f"target_doc_reference '{candidate.target_doc_reference}' not in corpus",
                    }
                )
                continue
            if target_resolution["status"] == "ambiguous":
                report.rejected.append(
                    {
                        "candidate": candidate.model_dump(),
                        "outcome": ValidationOutcome.REJECTED_TARGET_AMBIGUOUS.value,
                        "reason": f"multiple candidates: {target_resolution['candidates']}",
                    }
                )
                continue

            # 3. ACCEPTÉ
            target_doc_id = target_resolution["doc_id"]
            if target_doc_id == extraction.source_doc_id:
                # Self-reference impossible
                report.rejected.append(
                    {
                        "candidate": candidate.model_dump(),
                        "outcome": ValidationOutcome.REJECTED_TARGET_NOT_RESOLVED.value,
                        "reason": "target == source (self-reference)",
                    }
                )
                continue

            validated = ValidatedLifecycleRelation(
                source_doc_id=extraction.source_doc_id,
                target_doc_id=target_doc_id,
                type=candidate.type,
                evidence_quote=candidate.evidence_quote,
                confidence=candidate.confidence,
                reasoning=candidate.reasoning,
                model_id=extraction.model_id,
                derivation_path="lifecycle_extractor.v1.evidence_locked",
            )
            report.accepted.append(validated)

        return report

    def _resolve_target_doc(self, reference: str) -> dict:
        """Résout une référence textuelle en doc_id de DocumentContext.

        Stratégie domain-agnostic en 4 étapes :
        1. Extraire les "tokens identifiants" du reference
        2. Décomposer les tokens en sous-tokens atomiques (split sur '/', '-', ':')
           ex: "428/2009" → ["428", "2009"], "CS-25" → ["cs", "25"]
        3. Pour chaque DocumentContext, normaliser le searchable text :
           - Strip les hash suffixes (segments alphanumériques de 8+ chars contenant des hex)
           - Remplacer '_' par espace
           - Splitter en mots, lowercase
        4. Matcher : ALL atomic_token doit apparaître comme mot entier dans searchable_words

        Returns:
            {"status": "resolved" | "not_found" | "ambiguous", ...}
        """
        atomic_tokens = self._atomize_tokens(self._extract_identifying_tokens(reference))
        if not atomic_tokens:
            return {"status": "not_found"}

        with self.driver.session() as session:
            # Récupérer tous les DocumentContexts + primary_subject
            cypher = """
            MATCH (dc:DocumentContext)
            WHERE dc.tenant_id = $tenant_id
            RETURN dc.doc_id AS doc_id, coalesce(dc.primary_subject, '') AS subject
            """
            rows = session.run(cypher, tenant_id=self.tenant_id).data()

        # Matching côté Python en 2 tiers :
        # Tier 1 = tous les tokens dans le doc_id seul (racine = match fort)
        # Tier 2 = tokens dans doc_id + primary_subject (peut inclure docs dérivés)
        tier1_candidates: list[str] = []
        tier2_candidates: list[str] = []
        for row in rows:
            words_doc_id = self._tokenize_searchable(row["doc_id"], "")
            words_combined = self._tokenize_searchable(row["doc_id"], row["subject"])
            if all(tok in words_doc_id for tok in atomic_tokens):
                tier1_candidates.append(row["doc_id"])
            elif all(tok in words_combined for tok in atomic_tokens):
                tier2_candidates.append(row["doc_id"])

        # Préférer Tier 1 (racine) si non vide
        if tier1_candidates:
            if len(tier1_candidates) == 1:
                return {"status": "resolved", "doc_id": tier1_candidates[0]}
            return {"status": "ambiguous", "candidates": tier1_candidates[:5]}

        # Sinon Tier 2 (référence indirecte via subject)
        if tier2_candidates:
            if len(tier2_candidates) == 1:
                return {"status": "resolved", "doc_id": tier2_candidates[0]}
            return {"status": "ambiguous", "candidates": tier2_candidates[:5]}

        return {"status": "not_found"}

    @staticmethod
    def _atomize_tokens(tokens: list[str]) -> list[str]:
        """Décompose les tokens en sous-tokens atomiques (split sur séparateurs intra-token).

        Domain-agnostic : on ne garde que les sous-tokens contenant au moins un
        chiffre — règle uniforme avec _extract_identifying_tokens.
        Les sous-tokens purement alphabétiques (ex: 'CS' dans 'CS-25', 'EC' dans
        '95/46/EC', 'V' dans 'V27', 'ISO' dans 'ISO/9001:2015') sont éliminés
        car non discriminants pour identifier un artefact.

        Exemples (cross-domain, structurels) :
            ["428/2009"]      → ["428", "2009"]
            ["CS-25", "27"]   → ["25", "27"]   ('CS' filtré, alpha-only)
            ["95/46/EC"]      → ["95", "46"]   ('EC' filtré)
            ["9001:2015"]     → ["9001", "2015"]
            ["V27"]           → ["v27"]        (mixte alpha+chiffre conservé)
            ["MIL-STD-810H"]  → ["810h"]       ('MIL', 'STD' filtrés)
        """
        atomic: list[str] = []
        seen: set[str] = set()
        for tok in tokens:
            for sub in re.split(r"[/\-:.]+", tok):
                sub = sub.strip().lower()
                if not sub:
                    continue
                # Filtre uniforme : ne garder que les sous-tokens contenant ≥ 1 chiffre
                if not any(c.isdigit() for c in sub):
                    continue
                if sub not in seen:
                    seen.add(sub)
                    atomic.append(sub)
        return atomic

    @staticmethod
    def _tokenize_searchable(doc_id: str, subject: str) -> set[str]:
        """Tokenise un doc_id + subject en mots discriminants.

        - Split sur '_', espace, '-'
        - Strip les hash suffixes (mot alphanumérique de 8+ chars contenant ≥ 4 chiffres hex)
        - Lowercase
        - Returns un set pour O(1) lookup
        """
        raw = (doc_id + " " + subject).lower()
        words = re.split(r"[_\s\-/]+", raw)
        result: set[str] = set()
        for w in words:
            w = w.strip()
            if not w:
                continue
            # Filtre hash suffix : 8+ chars alphanumériques avec ≥ 4 chiffres hex
            if len(w) >= 8 and re.match(r"^[0-9a-f]+$", w) and sum(c.isdigit() for c in w) >= 2:
                # C'est probablement un hash → ignorer
                continue
            result.add(w)
        return result

    @staticmethod
    def _extract_identifying_tokens(reference: str) -> list[str]:
        """Extrait les tokens identifiants d'une référence textuelle.

        Règle structurelle unique et domain-agnostic : **un token est gardé si
        et seulement si il contient au moins un chiffre**. Dans toutes les pratiques
        de citation documentaire (réglementaire, technique, normative, médicale,
        IT, légale, interne corporate...), les artefacts documentaires sont
        identifiés par des numéros (numéro de doc, année, révision, version,
        identifiant alphanumérique mixte). Les mots purement alphabétiques
        descriptifs sont du bruit non discriminant pour le matching.

        Exemples (cross-domain, illustratifs uniquement) :
            "<DESCRIPTOR> 428/2009"     → ["428/2009"]
            "<DESCRIPTOR> 2021/821"     → ["2021/821"]
            "<STANDARD> 9001:2015"      → ["9001:2015"]
            "<ID> CS-25 V27"            → ["CS-25", "V27"]
            "<ID> Title 21 CFR 820"     → ["21", "820"]
            "<DESCRIPTOR> RFC 7231"     → ["7231"]
            "Geneva Convention"          → []  (aucun chiffre → pas identifiable)

        Le matching ALL(token in searchable) reste strict : tous les tokens
        identifiants doivent apparaître dans le doc cible.
        """
        # Split sur séparateurs typiques de citation (espaces, virgules, parenthèses, crochets)
        # mais on garde les "/" et "-" intra-token (ex: 95/46, CS-25)
        raw_parts = re.split(r"[\s,()\[\]]+", reference)
        tokens: list[str] = []
        for part in raw_parts:
            part = part.strip(".:;'\"")
            if not part:
                continue
            # Filtre principal : conserver uniquement les tokens contenant ≥ 1 chiffre
            if not any(c.isdigit() for c in part):
                continue
            tokens.append(part)
        # Dédupliquer en préservant l'ordre
        seen: set[str] = set()
        out: list[str] = []
        for tok in tokens:
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
        return out
