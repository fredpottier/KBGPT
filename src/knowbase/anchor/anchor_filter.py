"""
Anchor Filter — V2-S2.

Restreint les DocumentContext (et donc les claims) au cadre porté par l'anchor
extrait par AnchorExtractor.

Conformément à VISION_RECENTREE §4.2 :
- Domain-agnostic : aucun champ specifique. Match structurel sur ApplicabilityFrame V2
  (scope.product_version, scope.edition, scope.region, scope.conditions, scope.subject_class)
  + TemporalFrame (publication_date, validity_start, validity_end).
- Conventions de fallback runtime explicites :
  * claim sans validity_start → hérite de doc.publication_date
  * claim sans applicability_frame_v2 → considéré intemporel (toujours inclus)
- CURRENT_DEFAULT : pas de filtre — délègue au Current Resolver (V2-S3)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from neo4j import Driver
from pydantic import BaseModel, Field

from knowbase.anchor.models import AnchorType, ResolvedAnchor

logger = logging.getLogger(__name__)


class AnchorFilterResult(BaseModel):
    """Résultat du filtrage."""

    matched_doc_ids: Optional[list[str]] = Field(
        default=None,
        description="None = pas de filtre (CURRENT_DEFAULT); liste vide = aucun match.",
    )
    anchor_type: AnchorType
    method: str
    n_matched: int = 0
    diagnostic: dict = Field(default_factory=dict)


def _normalize(s: str) -> str:
    """Normalisation tolérante (lowercase + collapse whitespace)."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _digit_tokens(text: str) -> list[str]:
    """Sous-tokens contenant ≥ 1 chiffre (cohérent avec LifecycleValidator)."""
    parts = re.split(r"[\s,()\[\]/\-:.]+", text or "")
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        p = p.strip(".:;'\"").lower()
        if not p:
            continue
        if not any(c.isdigit() for c in p):
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _parse_year(text: str) -> Optional[int]:
    """Tente d'extraire une année 4 chiffres d'un texte arbitraire (run-of-4-digits).

    Domain-agnostic : un identifiant temporel courant dans toutes les pratiques
    de citation est une année à 4 chiffres. Pour V2-S2, c'est la heuristique
    minimale pour évaluer un range temporel. Si le user passe une version
    (ex: "1809") qui ressemble à une année, c'est traité comme tel — c'est OK
    car l'Anchor Filter retombe ensuite sur le matching version structurel.
    """
    if not text:
        return None
    m = re.search(r"\b(19|20|21)\d{2}\b", text)
    if m:
        try:
            return int(m.group(0))
        except ValueError:
            return None
    return None


class AnchorFilter:
    """Filtre les DocumentContext selon un anchor résolu.

    Args:
        driver: Neo4j driver
        tenant_id: tenant courant
    """

    def __init__(self, driver: Driver, tenant_id: str = "default") -> None:
        self.driver = driver
        self.tenant_id = tenant_id

    def filter(self, anchor: ResolvedAnchor) -> AnchorFilterResult:
        """Filtre les DocumentContext selon l'anchor.

        Returns AnchorFilterResult :
            - matched_doc_ids = None  → pas de filtre (CURRENT_DEFAULT, délégué au Current Resolver V2-S3)
            - matched_doc_ids = []    → aucun doc ne matche, runtime doit remonter au user
            - matched_doc_ids = [...] → liste de doc_ids dans le scope de l'anchor
        """
        if anchor.anchor_type == AnchorType.CURRENT_DEFAULT:
            return AnchorFilterResult(
                matched_doc_ids=None,
                anchor_type=anchor.anchor_type,
                method="current_default_delegated_to_current_resolver",
                n_matched=0,
                diagnostic={"reason": "Anchor is current_default — Anchor Filter does not narrow."},
            )

        if anchor.anchor_type == AnchorType.POINT:
            return self._filter_point(anchor)

        if anchor.anchor_type == AnchorType.RANGE:
            return self._filter_range(anchor)

        return AnchorFilterResult(
            matched_doc_ids=[],
            anchor_type=anchor.anchor_type,
            method="unknown_anchor_type",
            n_matched=0,
        )

    # ------------------------------------------------------------------
    # POINT filtering
    # ------------------------------------------------------------------

    def _filter_point(self, anchor: ResolvedAnchor) -> AnchorFilterResult:
        """Filtre POINT : match les docs dont l'ApplicabilityFrame V2 contient la version
        OU dont la publication_date matche la date demandée.

        Match strategy domain-agnostic :
        - Si anchor.scope.version est non null → digit_tokens(version) doivent ALL apparaître
          dans le frame text aggregate (scope.* values, edition, product_version, doc_id)
        - Si anchor.scope.date est non null → publication_date du doc doit matcher
          (string equality OU year prefix selon précision)
        - Sinon, fallback : tester scope.extraction_evidence comme version
        """
        all_docs = self._fetch_all_doc_frames()
        if not all_docs:
            return AnchorFilterResult(
                matched_doc_ids=[],
                anchor_type=anchor.anchor_type,
                method="point_no_docs",
                n_matched=0,
            )

        # Construire les tokens cible (priorité version > date > evidence)
        target_tokens = _digit_tokens(anchor.scope.version or "")
        target_date = anchor.scope.date
        if not target_tokens and not target_date and anchor.scope.extraction_evidence:
            # Fallback : utiliser l'evidence comme source de tokens
            target_tokens = _digit_tokens(anchor.scope.extraction_evidence)

        if not target_tokens and not target_date:
            return AnchorFilterResult(
                matched_doc_ids=[],
                anchor_type=anchor.anchor_type,
                method="point_no_target_tokens",
                n_matched=0,
                diagnostic={"reason": "Anchor POINT but no extractable identifier"},
            )

        matched: list[str] = []
        for doc in all_docs:
            if self._point_doc_matches(doc, target_tokens, target_date):
                matched.append(doc["doc_id"])

        return AnchorFilterResult(
            matched_doc_ids=matched,
            anchor_type=anchor.anchor_type,
            method="point_token_and_date_match",
            n_matched=len(matched),
            diagnostic={
                "target_tokens": target_tokens,
                "target_date": target_date,
                "scanned_docs": len(all_docs),
            },
        )

    @staticmethod
    def _point_doc_matches(
        doc: dict, target_tokens: list[str], target_date: Optional[str]
    ) -> bool:
        """Match strict : tous les target_tokens doivent apparaître dans frame_searchable
        OU la date du doc doit matcher target_date.

        Si les deux signaux sont fournis (version + date), on demande au moins UN des deux
        match — plus tolérant mais évite de rater des docs où la date est trouvée
        mais la version n'est pas explicitée dans l'AF.
        """
        frame_searchable = doc["frame_searchable_words"]
        token_match = bool(target_tokens) and all(
            tok in frame_searchable for tok in target_tokens
        )

        date_match = False
        if target_date:
            doc_pub = (doc.get("publication_date") or "").strip()
            if doc_pub and (doc_pub == target_date or doc_pub.startswith(target_date)):
                date_match = True
            # Tolérance sur les années seules
            target_year = _parse_year(target_date)
            doc_year = _parse_year(doc_pub)
            if target_year and doc_year and target_year == doc_year:
                date_match = True

        return token_match or date_match

    # ------------------------------------------------------------------
    # RANGE filtering
    # ------------------------------------------------------------------

    def _filter_range(self, anchor: ResolvedAnchor) -> AnchorFilterResult:
        """Filtre RANGE : match les docs dont publication_date OU validity_start ∈ [start, end].

        Si range_start ou range_end est null → range ouvert (depuis toujours / pour toujours).
        Si les deux sont null → range "toute l'histoire" → retourne tous les docs ACTIVE.

        Pour la sélection runtime : utilise les années si parseable, sinon retombe sur
        le matching version structurel (les versions identifient indirectement une période).
        """
        all_docs = self._fetch_all_doc_frames()
        if not all_docs:
            return AnchorFilterResult(
                matched_doc_ids=[],
                anchor_type=anchor.anchor_type,
                method="range_no_docs",
                n_matched=0,
            )

        start_year = _parse_year(anchor.scope.range_start or "")
        end_year = _parse_year(anchor.scope.range_end or "")

        # Cas 1 : range avec bornes années → filtrage chronologique
        if start_year is not None or end_year is not None:
            matched = []
            for doc in all_docs:
                doc_year = _parse_year(doc.get("publication_date") or "") or _parse_year(
                    doc.get("validity_start") or ""
                )
                if doc_year is None:
                    continue
                if start_year is not None and doc_year < start_year:
                    continue
                if end_year is not None and doc_year > end_year:
                    continue
                matched.append(doc["doc_id"])
            return AnchorFilterResult(
                matched_doc_ids=matched,
                anchor_type=anchor.anchor_type,
                method="range_year_window",
                n_matched=len(matched),
                diagnostic={
                    "start_year": start_year,
                    "end_year": end_year,
                    "scanned_docs": len(all_docs),
                },
            )

        # Cas 2 : range avec bornes versions/identifiants non-année (ex: "1809" et "2023")
        # On applique le matching tokens : on ne peut pas vraiment "ranger" sans ordre
        # connu, donc on retourne les docs matchant l'une des bornes ou l'autre.
        # C'est une approximation V1 — Current Resolver runtime affinera.
        if anchor.scope.range_start or anchor.scope.range_end:
            target_tokens_set: set[str] = set()
            target_tokens_set.update(_digit_tokens(anchor.scope.range_start or ""))
            target_tokens_set.update(_digit_tokens(anchor.scope.range_end or ""))
            if target_tokens_set:
                matched = []
                for doc in all_docs:
                    if any(tok in doc["frame_searchable_words"] for tok in target_tokens_set):
                        matched.append(doc["doc_id"])
                return AnchorFilterResult(
                    matched_doc_ids=matched,
                    anchor_type=anchor.anchor_type,
                    method="range_version_token_match",
                    n_matched=len(matched),
                    diagnostic={
                        "range_tokens_any_match": list(target_tokens_set),
                        "scanned_docs": len(all_docs),
                    },
                )

        # Cas 3 : range sans bornes → toute l'histoire → tous les docs (runtime trie temporellement)
        return AnchorFilterResult(
            matched_doc_ids=[doc["doc_id"] for doc in all_docs],
            anchor_type=anchor.anchor_type,
            method="range_unbounded_full_history",
            n_matched=len(all_docs),
            diagnostic={"reason": "range_start and range_end both null → full history"},
        )

    # ------------------------------------------------------------------
    # Neo4j fetching
    # ------------------------------------------------------------------

    def _fetch_all_doc_frames(self) -> list[dict]:
        """Récupère tous les DocumentContext + leur frame searchable précomputé.

        Le `frame_searchable_words` est l'agrégation des tokens digit-only extraits
        de :
        - applicability_frame_v2_json (scope.product_version, edition, region,
          conditions, subject_class — tous les .value)
        - publication_date / validity_start / validity_end
        - doc_id et primary_subject (pour fallback)

        Tokenization côté Python (pas de regex Cypher).
        """
        cypher = """
        MATCH (dc:DocumentContext)
        WHERE dc.tenant_id = $tenant_id
        RETURN dc.doc_id AS doc_id,
               coalesce(dc.applicability_frame_v2_json, '') AS af2_json,
               coalesce(dc.primary_subject, '') AS subject,
               dc.publication_date AS publication_date,
               dc.validity_start AS validity_start,
               dc.validity_end AS validity_end,
               coalesce(dc.lifecycle_status, 'UNKNOWN') AS lifecycle_status
        """
        with self.driver.session() as session:
            rows = session.run(cypher, tenant_id=self.tenant_id).data()

        docs: list[dict] = []
        for row in rows:
            af2 = self._parse_af2_text(row.get("af2_json", ""))
            # Aggregate searchable words from all sources
            searchable_words: set[str] = set()
            searchable_words.update(_digit_tokens(row["doc_id"]))
            searchable_words.update(_digit_tokens(row.get("subject") or ""))
            searchable_words.update(_digit_tokens(af2))
            searchable_words.update(_digit_tokens(row.get("publication_date") or ""))
            searchable_words.update(_digit_tokens(row.get("validity_start") or ""))

            docs.append(
                {
                    "doc_id": row["doc_id"],
                    "publication_date": row.get("publication_date"),
                    "validity_start": row.get("validity_start"),
                    "validity_end": row.get("validity_end"),
                    "lifecycle_status": row.get("lifecycle_status"),
                    "frame_searchable_words": searchable_words,
                }
            )
        return docs

    @staticmethod
    def _parse_af2_text(af2_json: str) -> str:
        """Extrait toutes les `.value` du JSON ApplicabilityFrame V2 en une string.

        Cherche récursivement les clés "value" dans le JSON et concatène leurs valeurs.
        Méthode purement structurelle, indépendante du domaine.
        """
        if not af2_json:
            return ""
        try:
            data = json.loads(af2_json)
        except json.JSONDecodeError:
            return af2_json

        collected: list[str] = []

        def visit(node):
            if isinstance(node, dict):
                if "value" in node and isinstance(node["value"], (str, int, float)):
                    collected.append(str(node["value"]))
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(data)
        return " ".join(collected)
