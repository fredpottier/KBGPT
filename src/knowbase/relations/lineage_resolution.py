"""
LineageResolution — résolution des contradictions par lignée documentaire.

Implémente ADR_RESOLUTION_CONTRADICTIONS (04/06/2026), niveaux 1-2 de la cascade :

  1. `infer_version_convention_lineage` — NIVEAU 2 : infère des edges
     `SUPERSEDES_DOC` depuis la convention de versionnage des identifiants
     (« AC 25.785-1A → 1B », « ETSO-C127a → b → c »), avec CORROBORATION
     obligatoire (§7.A) : même base-ID + même autorité + ordre des suffixes
     concordant avec l'ordre des dates documentaires quand elles existent.
     Désaccord ou dates absentes → PAS d'edge (pas d'invalidation possible).

  2. `resolve_contradictions_by_lineage` — niveau (a) : pour chaque paire
     `CONTRADICTS` dont les documents sont reliés par `SUPERSEDES_DOC`
     (scope='full', direct ou transitif), le claim du document superséd é PERD :
     `invalidated_at` + `valid_until` + `invalidation_reason='doc_lineage'`,
     et l'arête est CONVERTIE `CONTRADICTS` → `SUPERSEDES` (§7.C — préserve
     l'exclusion mutuelle et la visibilité lifecycle runtime).

  3. `apply_container_withdrawn` — niveau (b) : les AUTRES claims d'un document
     intégralement superséd é reçoivent le marqueur lifecycle ÉPISTÉMIQUE
     (`lifecycle_status_current='withdrawn'`) — PAS `invalidated_at` : « le
     document porteur a été annulé et aucun successeur ne se prononce sur ce
     point », jamais « ce claim n'est plus valide » (§7.D).

Domain-agnostic : la convention de suffixe et l'autorité sont des heuristiques
étiquetées (locus cible Domain Pack). Zéro appel LLM — 100 % déterministe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from knowbase.relations.explicit_lineage_detector import (
    normalize_reg_key,
    regulatory_authority,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Convention de versionnage (heuristique étiquetée — locus cible : Domain Pack)
# ============================================================================


def family_and_suffix(reg_key: Optional[str]) -> Optional[Tuple[str, str]]:
    """Décompose une clé réglementaire en (base, suffixe de révision).

        "AC 25.785-1A" -> ("AC 25.785-1", "A")
        "ETSO-C127C"   -> ("ETSO-C127", "C")
        "AC 21-25"     -> ("AC 21-25", "")      # pas de suffixe
        "AC 21-49"     -> ("AC 21-49", "")      # le 9 final n'est pas un suffixe

    Le suffixe n'est reconnu que s'il s'agit d'UNE lettre finale précédée d'un
    chiffre (le mécanisme formel de révision des autorités réglementaires).
    """
    if not reg_key:
        return None
    m = re.match(r"^(.*[0-9])([A-Z])$", reg_key.strip())
    if m:
        return m.group(1), m.group(2)
    return reg_key.strip(), ""


def suffix_order(suffix: str) -> int:
    """Ordre de révision : '' (édition originale) < 'A' < 'B' < …"""
    return 0 if not suffix else (ord(suffix.upper()) - ord("A") + 1)


# ============================================================================
# Résultats
# ============================================================================


@dataclass
class LineageResolutionReport:
    convention_edges_proposed: List[Dict[str, Any]] = field(default_factory=list)
    convention_edges_written: int = 0
    convention_rejected: List[str] = field(default_factory=list)
    pairs_resolved: int = 0
    claims_invalidated: int = 0
    edges_converted: int = 0
    container_withdrawn: int = 0

    def summary(self) -> Dict[str, Any]:
        return {
            "convention_edges_written": self.convention_edges_written,
            "convention_rejected": len(self.convention_rejected),
            "pairs_resolved": self.pairs_resolved,
            "claims_invalidated": self.claims_invalidated,
            "edges_converted": self.edges_converted,
            "container_withdrawn": self.container_withdrawn,
        }


# ============================================================================
# Moteur
# ============================================================================


class LineageResolver:
    def __init__(self, driver, tenant_id: str = "default") -> None:
        self.driver = driver
        self.tenant_id = tenant_id

    # ------------------------------------------------ helpers lecture
    def _doc_keys_and_dates(self) -> Dict[str, Dict[str, Any]]:
        """{doc_id: {reg_key, authority, date}} pour les docs avec claims.

        `date` = valid_from MODAL des claims du doc (héritage documentaire) —
        None si aucun claim daté.
        """
        out: Dict[str, Dict[str, Any]] = {}
        with self.driver.session() as s:
            for r in s.run(
                """
                MATCH (c:Claim {tenant_id: $t}) WHERE c.doc_id IS NOT NULL
                WITH c.doc_id AS d, toString(c.valid_from) AS vf, count(*) AS n
                ORDER BY d, (vf IS NULL), n DESC
                WITH d, collect({vf: vf, n: n})[0] AS top
                RETURN d AS doc_id, top.vf AS date
                """,
                t=self.tenant_id,
            ):
                doc_id = r["doc_id"]
                key = normalize_reg_key(doc_id)
                out[doc_id] = {
                    "reg_key": key,
                    "authority": regulatory_authority(doc_id),
                    "date": r["date"],
                }
        return out

    # ------------------------------------------------ 1. NIVEAU 2 : convention
    def infer_version_convention_lineage(
        self, report: LineageResolutionReport, dry_run: bool = False
    ) -> None:
        """Crée les SUPERSEDES_DOC inférés par convention de version, AVEC
        corroboration (§7.A) : même base + même autorité + ordre suffixes
        concordant avec l'ordre des dates (les DEUX dates requises).
        """
        docs = self._doc_keys_and_dates()
        # Regrouper par (base, autorité)
        families: Dict[Tuple[str, Optional[str]], List[Tuple[str, str, Optional[str]]]] = {}
        for doc_id, info in docs.items():
            fs = family_and_suffix(info["reg_key"])
            if not fs or not info["reg_key"]:
                continue
            base, suffix = fs
            families.setdefault((base, info["authority"]), []).append(
                (doc_id, suffix, info["date"])
            )

        for (base, authority), members in families.items():
            if len(members) < 2:
                continue
            members.sort(key=lambda m: suffix_order(m[1]))
            # Paires ADJACENTES successeur → prédécesseur
            for (old_id, old_sfx, old_date), (new_id, new_sfx, new_date) in zip(
                members, members[1:]
            ):
                label = f"{base}{new_sfx} ▶ {base}{old_sfx or ''}"
                if suffix_order(new_sfx) <= suffix_order(old_sfx):
                    continue
                # CORROBORATION dates : les deux requises ET ordre concordant
                if not (old_date and new_date and new_date > old_date):
                    report.convention_rejected.append(
                        f"{label} (dates non corroborantes: {old_date} vs {new_date})"
                    )
                    continue
                report.convention_edges_proposed.append({
                    "superseder": new_id, "superseded": old_id,
                    "base": base, "authority": authority,
                    "dates": (old_date, new_date),
                })
                if not dry_run:
                    with self.driver.session() as s:
                        s.run(
                            """
                            MERGE (sup:Document {doc_id: $new, tenant_id: $t})
                              ON CREATE SET sup.created_at = datetime()
                            SET sup.ingested = coalesce(sup.ingested, true),
                                sup.reg_key = coalesce(sup.reg_key, $new_key)
                            MERGE (old:Document {doc_id: $old, tenant_id: $t})
                              ON CREATE SET old.created_at = datetime()
                            SET old.ingested = coalesce(old.ingested, true),
                                old.reg_key = coalesce(old.reg_key, $old_key)
                            MERGE (sup)-[r:SUPERSEDES_DOC]->(old)
                              ON CREATE SET r.explicit = false,
                                            r.scope = 'full',
                                            r.detected_at = datetime(),
                                            r.detection_source = 'version_convention',
                                            r.confidence = 0.85,
                                            r.corroborated_by_dates = true
                            """,
                            t=self.tenant_id, new=new_id, old=old_id,
                            new_key=normalize_reg_key(new_id),
                            old_key=normalize_reg_key(old_id),
                        )
                    report.convention_edges_written += 1

    # ------------------------------------------------ 2. Résolution des paires
    _RESOLVE_CYPHER = """
    MATCH (a:Claim {tenant_id: $t})-[x:CONTRADICTS]->(b:Claim {tenant_id: $t})
    MATCH (da:Document {tenant_id: $t, doc_id: a.doc_id})
    MATCH (db:Document {tenant_id: $t, doc_id: b.doc_id})
    OPTIONAL MATCH pa = (da)-[ra:SUPERSEDES_DOC*1..4]->(db)
    OPTIONAL MATCH pb = (db)-[rb:SUPERSEDES_DOC*1..4]->(da)
    WITH a, b, x,
         pa IS NOT NULL AND all(r IN relationships(pa) WHERE coalesce(r.scope,'full') = 'full') AS a_wins,
         pb IS NOT NULL AND all(r IN relationships(pb) WHERE coalesce(r.scope,'full') = 'full') AS b_wins
    WHERE a_wins OR b_wins
    WITH a, b, x,
         CASE WHEN a_wins THEN a ELSE b END AS winner,
         CASE WHEN a_wins THEN b ELSE a END AS loser
    WHERE loser.invalidated_at IS NULL
    SET loser.invalidated_at = datetime(),
        loser.valid_until = coalesce(loser.valid_until, winner.valid_from),
        loser.invalidated_by = winner.claim_id,
        loser.invalidation_reason = 'doc_lineage'
    MERGE (winner)-[s:SUPERSEDES]->(loser)
      ON CREATE SET s.detected_at = datetime(),
                    s.marker_type = 'inferred',
                    s.detection_method = 'doc_lineage',
                    s.detection_source = 'lineage_resolution',
                    s.confidence = coalesce(x.confidence, 0.85)
    DELETE x
    RETURN count(*) AS resolved
    """

    # Cascade §2.3 (ADR ex-I4) : estampiller les arêtes restantes des perdants.
    _CASCADE_CYPHER = """
    MATCH (loser:Claim {tenant_id: $t})
    WHERE loser.invalidation_reason = 'doc_lineage' AND loser.invalidated_at IS NOT NULL
    MATCH (loser)-[r:SAME_AS|EVOLUTION_OF|CONTRADICTS|REFINES|QUALIFIES|CHAINS_TO|COMPLEMENTS|SPECIALIZES]-(:Claim)
    WHERE r.invalidated_relation_at IS NULL
    SET r.invalidated_relation_at = loser.invalidated_at
    RETURN count(r) AS stamped
    """

    def resolve_contradictions_by_lineage(
        self, report: LineageResolutionReport, dry_run: bool = False
    ) -> None:
        if dry_run:
            with self.driver.session() as s:
                n = s.run(
                    """
                    MATCH (a:Claim {tenant_id: $t})-[x:CONTRADICTS]->(b:Claim {tenant_id: $t})
                    MATCH (da:Document {tenant_id: $t, doc_id: a.doc_id})
                    MATCH (db:Document {tenant_id: $t, doc_id: b.doc_id})
                    WHERE (da)-[:SUPERSEDES_DOC*1..4]->(db) OR (db)-[:SUPERSEDES_DOC*1..4]->(da)
                    RETURN count(x) AS n
                    """,
                    t=self.tenant_id,
                ).single()["n"]
            report.pairs_resolved = n  # prévision
            return
        with self.driver.session() as s:
            rec = s.run(self._RESOLVE_CYPHER, t=self.tenant_id).single()
            resolved = rec["resolved"] if rec else 0
            report.pairs_resolved = resolved
            report.claims_invalidated = resolved  # 1 perdant par paire (idempotent)
            report.edges_converted = resolved
            s.run(self._CASCADE_CYPHER, t=self.tenant_id)

    # ------------------------------------------------ 3. Marqueur souple (b)
    _WITHDRAWN_CYPHER = """
    MATCH (sup:Document {tenant_id: $t})-[r:SUPERSEDES_DOC]->(old:Document {tenant_id: $t})
    WHERE coalesce(r.scope, 'full') = 'full'
    MATCH (c:Claim {tenant_id: $t, doc_id: old.doc_id})
    WHERE c.invalidated_at IS NULL AND c.lifecycle_status_current IS NULL
    SET c.lifecycle_status_current = 'withdrawn',
        c.lifecycle_status_reason = 'container_cancelled_by:' + sup.doc_id,
        c.lifecycle_status_change_date = coalesce(r.stated_date, toString(sup.created_at))
    RETURN count(c) AS n
    """

    def apply_container_withdrawn(
        self, report: LineageResolutionReport, dry_run: bool = False
    ) -> None:
        """Marqueur ÉPISTÉMIQUE (§7.D.b) : « document porteur annulé, successeur
        muet sur ce point » — jamais une assertion d'invalidité du claim.
        """
        cypher = self._WITHDRAWN_CYPHER if not dry_run else self._WITHDRAWN_CYPHER.replace(
            "SET c.lifecycle_status_current", "WITH c, sup, r SET c.__dry__"
        )
        if dry_run:
            with self.driver.session() as s:
                n = s.run(
                    """
                    MATCH (sup:Document {tenant_id: $t})-[r:SUPERSEDES_DOC]->(old:Document {tenant_id: $t})
                    WHERE coalesce(r.scope, 'full') = 'full'
                    MATCH (c:Claim {tenant_id: $t, doc_id: old.doc_id})
                    WHERE c.invalidated_at IS NULL AND c.lifecycle_status_current IS NULL
                    RETURN count(c) AS n
                    """,
                    t=self.tenant_id,
                ).single()["n"]
            report.container_withdrawn = n  # prévision
            return
        with self.driver.session() as s:
            rec = s.run(self._WITHDRAWN_CYPHER, t=self.tenant_id).single()
            report.container_withdrawn = rec["n"] if rec else 0

    # ------------------------------------------------ orchestration
    def run(self, dry_run: bool = False) -> LineageResolutionReport:
        report = LineageResolutionReport()
        self.infer_version_convention_lineage(report, dry_run=dry_run)
        self.resolve_contradictions_by_lineage(report, dry_run=dry_run)
        self.apply_container_withdrawn(report, dry_run=dry_run)
        logger.info(f"[LineageResolution] {report.summary()} (dry_run={dry_run})")
        return report
