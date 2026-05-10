"""
OSMOSIS V4 — EvidenceCollector (composant [B], CH-41.2).

Collecte d'evidence pour le pipeline Facts-First :
  - Source primaire : Claims atomiques Neo4j (verbatim_quote, source_doc_id via DocumentContext)
  - Source secondaire : chunks Qdrant (full passages)
  - Flux :
      1. Qdrant top-K via ClaimRetriever (CH-35 hybrid + rerank existant)
      2. Pour chaque hit, enrichir via Neo4j si claim_id présent (verbatim_quote, page_no, etc.)
      3. Sinon, fallback chunk-only (passage_text du payload)
      4. Si 0 evidence ou top-K ne dépasse aucun seuil → answerability_hint=unanswerable
  - Output : `EvidenceBundle` (claims enrichis + raw chunks + answerability_hint)

Pour Tranche 1 (list), le bundle alimente directement ListStructurer.
LOGICAL_RELATION/LIFECYCLE_RELATION sont enrichies dans CH-41.3+ pour les types
qui en ont besoin (comparison, temporal, causal). Pas dans CH-41.2 pour rester simple.

Charte D-FF1 : tout claim a son `quote` non vide (auditable). Si la quote est
absente ou trop courte, on rejette le claim.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Seuils par défaut (override via config plus tard)
MIN_QUOTE_CHARS = 10  # cohérent avec schema common $defs.Source.quote.minLength
DEFAULT_TOP_K = 20
MIN_SCORE_KEEP = 0.0

# Modes de collecte (Couche A — paramétrable par type de question)
# - "single"        : 1 query unique (default — comportement Tranche 1)
# - "exhaustive"    : 2-3 sub-queries diverses + fusion RRF (list questions)
# - "comparative"   : N queries par entité comparée (comparison)
# - "chronological" : retrieve par doc_id sorted par publication_date (temporal)
COLLECTION_MODE_SINGLE = "single"
COLLECTION_MODE_EXHAUSTIVE = "exhaustive"
COLLECTION_MODE_COMPARATIVE = "comparative"
COLLECTION_MODE_CHRONOLOGICAL = "chronological"

# Graph traversal hints
GRAPH_LOGICAL = "LOGICAL_RELATION"      # CONTRADICTS, REAFFIRMS, COMPLEMENTARY (comparison)
GRAPH_LIFECYCLE = "LIFECYCLE_RELATION"  # SUPERSEDES, EVOLVES_FROM (temporal)


@dataclass
class EvidenceClaim:
    """Un claim enrichi prêt pour le Structurer."""
    claim_id: Optional[str]  # None si fallback chunk-only
    doc_id: str
    chunk_id: Optional[str]
    page_no: Optional[int]
    quote: str  # OBLIGATOIRE D-FF1, ≥ MIN_QUOTE_CHARS chars
    score: float
    publication_date: Optional[str] = None
    section_id: Optional[str] = None
    enriched_from_neo4j: bool = False  # True si verbatim_quote vient de Neo4j

    def is_valid(self) -> bool:
        return bool(self.quote) and len(self.quote.strip()) >= MIN_QUOTE_CHARS and bool(self.doc_id)


@dataclass
class EvidenceBundle:
    """Résultat structuré d'une collecte d'evidence."""
    question: str
    claims: list[EvidenceClaim] = field(default_factory=list)
    answerability_hint: str = "answerable"  # answerable | partial | unanswerable
    n_qdrant_hits: int = 0
    n_neo4j_enriched: int = 0
    n_chunk_fallback: int = 0
    n_rejected_invalid_quote: int = 0
    latency_ms: int = 0
    diagnostic: dict = field(default_factory=dict)

    def doc_ids(self) -> list[str]:
        seen, out = set(), []
        for c in self.claims:
            if c.doc_id not in seen:
                seen.add(c.doc_id)
                out.append(c.doc_id)
        return out

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answerability_hint": self.answerability_hint,
            "n_qdrant_hits": self.n_qdrant_hits,
            "n_neo4j_enriched": self.n_neo4j_enriched,
            "n_chunk_fallback": self.n_chunk_fallback,
            "n_rejected_invalid_quote": self.n_rejected_invalid_quote,
            "latency_ms": self.latency_ms,
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "doc_id": c.doc_id,
                    "chunk_id": c.chunk_id,
                    "page_no": c.page_no,
                    "quote": c.quote,
                    "score": c.score,
                    "publication_date": c.publication_date,
                    "section_id": c.section_id,
                    "enriched_from_neo4j": c.enriched_from_neo4j,
                }
                for c in self.claims
            ],
            "diagnostic": self.diagnostic,
        }


class EvidenceCollector:
    """Collecte d'evidence Claims Neo4j + chunks Qdrant pour Facts-First.

    Args:
        retriever: ClaimRetriever (ou compat avec `.retrieve(question, doc_ids, top_k)`)
        neo4j_driver: driver Neo4j (optional — si None, on reste en mode chunk-only)
        tenant_id: tenant pour multi-tenancy
        top_k: nombre max d'hits Qdrant
        min_score_keep: filtre des hits dont score < seuil
    """

    def __init__(
        self,
        retriever,
        neo4j_driver=None,
        tenant_id: str = "default",
        top_k: int = DEFAULT_TOP_K,
        min_score_keep: float = MIN_SCORE_KEEP,
    ) -> None:
        self.retriever = retriever
        self.driver = neo4j_driver
        self.tenant_id = tenant_id
        self.top_k = top_k
        self.min_score_keep = min_score_keep

    def collect(
        self,
        question: str,
        doc_ids: Optional[list[str]] = None,
        top_k: Optional[int] = None,
        mode: str = COLLECTION_MODE_SINGLE,
        graph_traversal: Optional[str] = None,
    ) -> EvidenceBundle:
        """Collecte l'evidence pour la question.

        Args:
            question: question utilisateur
            doc_ids: scope autoritaire (None = tous docs)
            top_k: override du top_k par défaut
            mode: stratégie de retrieval — single | exhaustive | comparative | chronological
                Le QuestionAnalyzer décide via primary_type (list→exhaustive, factual→single, etc.)
            graph_traversal: hint Neo4j — LOGICAL_RELATION | LIFECYCLE_RELATION | None
                Étend le pool via traversée de relations sur le subject de la question.
        """
        import time
        t0 = time.time()
        bundle = EvidenceBundle(question=question)
        k = top_k or self.top_k

        # 1. Qdrant retrieval — stratégie selon mode
        all_hits: list = []
        try:
            if mode == COLLECTION_MODE_EXHAUSTIVE:
                # Multi-query : query original + 2 reformulations LLM (génération synthétique
                # via le retriever. Si l'embedder n'a pas de generator, fallback single).
                # Pragma : pour rester simple, on génère 2 sous-queries via heuristiques light
                # (pas de LLM call additionnel — économie latence).
                sub_queries = [question] + self._derive_subqueries(question)
                seen_ids = set()
                for sq in sub_queries:
                    try:
                        h = self.retriever.retrieve(question=sq, doc_ids=doc_ids, top_k=k)
                    except Exception:
                        continue
                    for hit in h:
                        hid = getattr(hit, "id", None) or getattr(hit, "claim_id", None)
                        if hid and hid in seen_ids:
                            continue
                        if hid:
                            seen_ids.add(hid)
                        all_hits.append(hit)
                # Limit final pool à k (top par score)
                all_hits = sorted(all_hits, key=lambda h: getattr(h, "score", 0.0), reverse=True)[:k]
            else:
                # Mode single (default), comparative et chronological — une seule query directe
                # (la stratégie comparative/chronological additionnelle est gérée par graph_traversal)
                all_hits = self.retriever.retrieve(question=question, doc_ids=doc_ids, top_k=k)
        except Exception as exc:  # noqa: BLE001
            logger.error("Retriever failed: %s", exc)
            bundle.diagnostic["retriever_error"] = str(exc)
            bundle.answerability_hint = "unanswerable"
            bundle.latency_ms = int((time.time() - t0) * 1000)
            return bundle

        # 1b. Graph traversal Neo4j (étend le pool via LOGICAL/LIFECYCLE relations)
        if graph_traversal and self.driver and all_hits:
            try:
                expanded = self._expand_via_graph(all_hits, graph_traversal)
                # Ajout sans dédup brutal (les expand peuvent ramener des claim_id hors pool initial)
                existing_ids = {getattr(h, "claim_id", None) for h in all_hits}
                for e in expanded:
                    if e.claim_id and e.claim_id not in existing_ids:
                        all_hits.append(e)
                        existing_ids.add(e.claim_id)
                bundle.diagnostic["graph_expansion_count"] = len(expanded)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Graph traversal failed: %s", exc)
                bundle.diagnostic["graph_error"] = str(exc)

        hits = all_hits
        bundle.n_qdrant_hits = len(hits)
        bundle.diagnostic["mode"] = mode
        bundle.diagnostic["graph_traversal"] = graph_traversal
        if not hits:
            bundle.answerability_hint = "unanswerable"
            bundle.diagnostic["reason"] = "no_qdrant_hits"
            bundle.latency_ms = int((time.time() - t0) * 1000)
            return bundle

        # Filtre des hits avec score trop bas
        kept_hits = [h for h in hits if (getattr(h, "score", 0.0) or 0.0) >= self.min_score_keep]
        if not kept_hits:
            bundle.answerability_hint = "unanswerable"
            bundle.diagnostic["reason"] = f"all_hits_below_min_score:{self.min_score_keep}"
            bundle.latency_ms = int((time.time() - t0) * 1000)
            return bundle

        # 2. Enrichissement Neo4j (claim_id → verbatim_quote, page_no, section_id)
        claim_ids_to_enrich = [h.claim_id for h in kept_hits if getattr(h, "claim_id", None)]
        neo4j_data = self._enrich_from_neo4j(claim_ids_to_enrich) if self.driver else {}

        # 3. Construction des EvidenceClaim
        for h in kept_hits:
            cid = getattr(h, "claim_id", None)
            doc_id = getattr(h, "doc_id", "unknown")
            chunk_text = getattr(h, "text", "") or ""
            score = float(getattr(h, "score", 0.0) or 0.0)
            pub_date = getattr(h, "publication_date", None)

            n4j = neo4j_data.get(cid) if cid else None
            if n4j and n4j.get("verbatim_quote"):
                ec = EvidenceClaim(
                    claim_id=cid,
                    doc_id=doc_id,
                    chunk_id=n4j.get("chunk_id"),
                    page_no=n4j.get("page_no"),
                    quote=n4j["verbatim_quote"],
                    score=score,
                    publication_date=pub_date or n4j.get("publication_date"),
                    section_id=n4j.get("section_id"),
                    enriched_from_neo4j=True,
                )
                if ec.is_valid():
                    bundle.claims.append(ec)
                    bundle.n_neo4j_enriched += 1
                else:
                    bundle.n_rejected_invalid_quote += 1
            else:
                # Fallback chunk-only : utiliser le passage_text du payload Qdrant
                ec = EvidenceClaim(
                    claim_id=None,
                    doc_id=doc_id,
                    chunk_id=cid,  # cid est le chunk_id si pas de claim_id
                    page_no=None,
                    quote=chunk_text.strip(),
                    score=score,
                    publication_date=pub_date,
                    section_id=None,
                    enriched_from_neo4j=False,
                )
                if ec.is_valid():
                    bundle.claims.append(ec)
                    bundle.n_chunk_fallback += 1
                else:
                    bundle.n_rejected_invalid_quote += 1

        # 4. Verdict answerability
        if not bundle.claims:
            bundle.answerability_hint = "unanswerable"
            bundle.diagnostic["reason"] = "all_claims_rejected_invalid_quote"
        elif len(bundle.claims) < 3:
            bundle.answerability_hint = "partial"
            bundle.diagnostic["reason"] = f"low_evidence_count:{len(bundle.claims)}"

        bundle.latency_ms = int((time.time() - t0) * 1000)
        return bundle

    @staticmethod
    def _derive_subqueries(question: str) -> list[str]:
        """Génère 2 sub-queries diverses (heuristique légère, sans LLM).

        Stratégie : reformulations syntaxiques simples qui élargissent le rayon
        sémantique (synonymes communs, formes interrogatives → affirmatives).
        Charte anti-V2 : pas de regex métier, juste manipulations linguistiques.
        """
        q = question.strip()
        subs = []
        # Forme déclarative : retire l'interrogatif initial
        lower = q.lower()
        for prefix in ("quels ", "quelles ", "quel ", "quelle ", "what are the ", "what is the ", "list the ", "list "):
            if lower.startswith(prefix):
                subs.append(q[len(prefix):].rstrip("?."))
                break
        # Variante sans ponctuation finale + sans "the"
        no_q = q.rstrip("?").strip()
        if no_q != q:
            subs.append(no_q)
        return [s for s in subs if s and s != q][:2]

    def _expand_via_graph(self, hits: list, traversal: str) -> list[EvidenceClaim]:
        """Étend le pool via traversée Neo4j sur LOGICAL_RELATION ou LIFECYCLE_RELATION.

        Pour chaque claim_id du pool initial, cherche les claims liés via la
        relation demandée (1 hop), enrichit avec verbatim_quote.
        """
        seed_ids = [h.claim_id for h in hits[:10] if getattr(h, "claim_id", None)]
        if not seed_ids:
            return []
        relation_label = "LOGICAL_RELATION" if traversal == GRAPH_LOGICAL else "LIFECYCLE_RELATION"
        try:
            with self.driver.session() as session:
                rows = session.run(
                    f"""
                    MATCH (c1:Claim)-[r:{relation_label}]-(c2:Claim)
                    WHERE c1.tenant_id = $tenant_id AND c1.claim_id IN $seed_ids
                    RETURN DISTINCT c2.claim_id AS claim_id,
                           c2.verbatim_quote AS verbatim_quote,
                           c2.passage_text AS passage_text,
                           c2.publication_date AS publication_date,
                           type(r) AS rel_type
                    LIMIT 20
                    """,
                    tenant_id=self.tenant_id,
                    seed_ids=seed_ids,
                ).data()
        except Exception as exc:
            logger.warning("Graph expansion query failed: %s", exc)
            return []

        out: list[EvidenceClaim] = []
        for r in rows:
            cid = r.get("claim_id")
            quote = (r.get("verbatim_quote") or r.get("passage_text") or "").strip()
            if not cid or len(quote) < MIN_QUOTE_CHARS:
                continue
            out.append(EvidenceClaim(
                claim_id=cid,
                doc_id="graph_expanded",  # le doc_id réel demanderait une query supplémentaire
                chunk_id=None,
                page_no=None,
                quote=quote[:1000],
                score=0.5,  # score moyen — ce n'est pas Qdrant
                publication_date=r.get("publication_date"),
                section_id=None,
                enriched_from_neo4j=True,
            ))
        return out

    def _enrich_from_neo4j(self, claim_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Récupère verbatim_quote, page_no, section_id depuis Neo4j pour chaque claim_id.

        Charte : domain-agnostic, pas de filtre métier.
        """
        if not self.driver or not claim_ids:
            return {}
        # Filtre les valeurs falsy pour éviter MATCH avec None
        claim_ids = [cid for cid in claim_ids if cid]
        if not claim_ids:
            return {}

        try:
            with self.driver.session() as session:
                rows = session.run(
                    """
                    MATCH (c:Claim)
                    WHERE c.tenant_id = $tenant_id AND c.claim_id IN $claim_ids
                    RETURN c.claim_id AS claim_id,
                           c.verbatim_quote AS verbatim_quote,
                           c.passage_text AS passage_text,
                           c.passage_char_start AS passage_char_start,
                           c.passage_char_end AS passage_char_end,
                           c.publication_date AS publication_date,
                           c.chunk_ids AS chunk_ids,
                           c.unit_ids AS unit_ids,
                           c.language AS language
                    """,
                    tenant_id=self.tenant_id,
                    claim_ids=claim_ids,
                ).data()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Neo4j enrichment failed: %s", exc)
            return {}

        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            cid = r["claim_id"]
            quote = (r.get("verbatim_quote") or "").strip()
            # Si verbatim_quote absent, fallback passage_text
            if not quote:
                quote = (r.get("passage_text") or "").strip()
            chunk_ids = r.get("chunk_ids") or []
            chunk_id = chunk_ids[0] if chunk_ids else None
            out[cid] = {
                "verbatim_quote": quote,
                "publication_date": r.get("publication_date"),
                "chunk_id": chunk_id,
                "page_no": None,  # pas trivialement dispo sur Claim ; à enrichir via DocumentContext si besoin
                "section_id": None,
                "language": r.get("language"),
            }
        return out


# ---------------------------------------------------------------------------
# Singleton helper (lazy : pas de connexion par défaut, à wirer côté app)
# ---------------------------------------------------------------------------

_default_collector: Optional[EvidenceCollector] = None


def get_evidence_collector(
    retriever=None,
    neo4j_driver=None,
    tenant_id: str = "default",
) -> EvidenceCollector:
    """Singleton (à wirer côté app/runtime)."""
    global _default_collector
    if _default_collector is None and retriever is not None:
        _default_collector = EvidenceCollector(
            retriever=retriever,
            neo4j_driver=neo4j_driver,
            tenant_id=tenant_id,
        )
    if _default_collector is None:
        raise RuntimeError(
            "EvidenceCollector not initialized. Call get_evidence_collector(retriever, neo4j_driver) first."
        )
    return _default_collector


def reset_evidence_collector() -> None:
    global _default_collector
    _default_collector = None
