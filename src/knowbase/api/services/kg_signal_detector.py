"""
OSMOSIS KG Signal Detector — Signal-driven KG injection.

Detecte les signaux documentaires sur le sujet de la question
a partir des claims KG deja en memoire (zero appel Neo4j supplementaire).

Signaux :
- tension : REFINES/QUALIFIES/CONTRADICTS cross-doc
- temporal_evolution : meme entite, valeurs differentes, docs differents
- coverage_gap : docs avec claims absents des chunks Qdrant
- exactness : QD match avec extracted_value
- question_context_gap : termes specifiques de la question absents des chunks
- silence : aucun signal (= RAG pur, defaut)

Le silence du KG est un resultat normal, pas un echec.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """Un signal documentaire detecte par le KG."""
    type: str  # "tension", "temporal_evolution", "coverage_gap", "exactness"
    strength: float  # 0.0-1.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalReport:
    """Rapport de signaux KG sur le sujet de la question."""
    signals: list[Signal] = field(default_factory=list)
    claims_analyzed: int = 0

    @property
    def is_silent(self) -> bool:
        """Aucun signal = RAG pur."""
        return len(self.signals) == 0

    def has_signal(self, signal_type: str) -> bool:
        return any(s.type == signal_type for s in self.signals)

    def get_signal(self, signal_type: str) -> Signal | None:
        for s in self.signals:
            if s.type == signal_type:
                return s
        return None


def detect_signals(
    kg_claims: list[dict],
    retrieval_doc_ids: set[str],
    qs_crossdoc_data: list[dict] | None = None,
    question: str = "",
    chunks: list[dict] | None = None,
) -> SignalReport:
    """
    Detecte les signaux KG a partir des claims deja en memoire.

    Zero appel Neo4j supplementaire — tout est calcule sur les claims
    retournes par _search_claims_vector() qui est deja dans le flux.

    Args:
        kg_claims: Claims retournes par _search_claims_vector()
        retrieval_doc_ids: Doc IDs presents dans les chunks Qdrant
        qs_crossdoc_data: Donnees QS cross-doc (optionnel)

    Returns:
        SignalReport (peut etre vide = silence = RAG pur)
    """
    if not kg_claims:
        return SignalReport(claims_analyzed=0)

    signals: list[Signal] = []

    # Signal 1 — Tension
    tension = _detect_tension(kg_claims)
    if tension:
        signals.append(tension)

    # Signal 2 — Evolution temporelle
    evolution = _detect_temporal_evolution(kg_claims)
    if evolution:
        signals.append(evolution)

    # Signal 3 — Couverture
    coverage = _detect_coverage_gap(kg_claims, retrieval_doc_ids)
    if coverage:
        signals.append(coverage)

    # Signal 4 — Exactitude
    if qs_crossdoc_data:
        exactness = _detect_exactness(qs_crossdoc_data)
        if exactness:
            signals.append(exactness)

    # Signal 5 — Question-Context Gap
    if question and chunks:
        gap = _detect_question_context_gap(question, chunks, kg_claims=kg_claims)
        if gap:
            signals.append(gap)

    report = SignalReport(signals=signals, claims_analyzed=len(kg_claims))

    if report.is_silent:
        logger.info(f"[SIGNAL] Silence — {len(kg_claims)} claims analyzed, no signals. RAG pure.")
    else:
        signal_names = [s.type for s in signals]
        logger.info(f"[SIGNAL] Detected {len(signals)} signals: {signal_names} from {len(kg_claims)} claims")

    return report


def _detect_tension(kg_claims: list[dict]) -> Signal | None:
    """Detecte des tensions (REFINES/QUALIFIES/CONTRADICTS) cross-doc."""
    tension_docs: set[str] = set()
    tension_texts: list[str] = []

    for claim in kg_claims:
        contradictions = claim.get("contradiction_texts", [])
        has_tension = any(t for t in contradictions if t)
        if has_tension:
            tension_docs.add(claim.get("source_file", ""))
            for t in contradictions:
                if t and t not in tension_texts:
                    tension_texts.append(t)

    if len(tension_docs) < 2 or not tension_texts:
        return None

    return Signal(
        type="tension",
        strength=min(1.0, len(tension_texts) / 5),  # normalise sur 5 tensions max
        evidence={
            "tension_doc_ids": tension_docs,
            "tension_count": len(tension_texts),
            "tension_texts": tension_texts[:5],
        },
    )


def _detect_temporal_evolution(kg_claims: list[dict]) -> Signal | None:
    """Detecte des evolutions temporelles (meme entite, docs differents)."""
    # Grouper les entites par nom et collecter les docs
    entity_docs: dict[str, set[str]] = {}
    for claim in kg_claims:
        doc_id = claim.get("source_file", "")
        for entity_name in claim.get("entity_names", []):
            if entity_name and doc_id:
                entity_docs.setdefault(entity_name, set()).add(doc_id)

    # Entites presentes dans 2+ documents distincts
    multi_doc_entities = {
        name: docs for name, docs in entity_docs.items()
        if len(docs) >= 2
    }

    if not multi_doc_entities:
        return None

    return Signal(
        type="temporal_evolution",
        strength=min(1.0, len(multi_doc_entities) / 3),
        evidence={
            "multi_doc_entities": {name: list(docs) for name, docs in list(multi_doc_entities.items())[:5]},
            "entity_count": len(multi_doc_entities),
        },
    )


def _detect_coverage_gap(kg_claims: list[dict], retrieval_doc_ids: set[str]) -> Signal | None:
    """Detecte des docs avec claims sur le sujet absents des chunks Qdrant."""
    claim_doc_ids = set()
    for claim in kg_claims:
        doc_id = claim.get("source_file", "")
        if doc_id:
            claim_doc_ids.add(doc_id)

    missing_docs = claim_doc_ids - retrieval_doc_ids - {""}

    if not missing_docs:
        return None

    return Signal(
        type="coverage_gap",
        strength=min(1.0, len(missing_docs) / 3),
        evidence={
            "missing_doc_ids": missing_docs,
            "missing_count": len(missing_docs),
            "total_claim_docs": len(claim_doc_ids),
            "total_retrieval_docs": len(retrieval_doc_ids),
        },
    )


def _detect_exactness(qs_crossdoc_data: list[dict]) -> Signal | None:
    """Detecte un match QD exact avec extracted_value."""
    exact_matches = []
    for qs in qs_crossdoc_data:
        if qs.get("extracted_value") and qs.get("confidence", 0) >= 0.7:
            exact_matches.append({
                "dimension_key": qs.get("dimension_key", ""),
                "canonical_question": qs.get("canonical_question", ""),
                "extracted_value": qs.get("extracted_value"),
                "doc_id": qs.get("doc_id", ""),
            })

    if not exact_matches:
        return None

    return Signal(
        type="exactness",
        strength=min(1.0, max(qs.get("confidence", 0) for qs in qs_crossdoc_data)),
        evidence={
            "matches": exact_matches[:5],
            "match_count": len(exact_matches),
        },
    )


# ── Signal 5 : Question-Context Gap ─────────────────────────────────

# Stopwords universels FR+EN (domain-agnostic)
_STOPWORDS = frozenset({
    # FR
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "en", "est",
    "que", "qui", "dans", "pour", "par", "sur", "avec", "ce", "cette", "ces",
    "son", "sa", "ses", "au", "aux", "ou", "ne", "pas", "plus", "se", "il",
    "elle", "on", "nous", "vous", "ils", "elles", "etre", "avoir", "faire",
    "dit", "peut", "doit", "sont", "ont", "faut", "tout", "tous", "bien",
    "aussi", "entre", "comme", "mais", "donc", "car", "si", "quand",
    "comment", "quel", "quelle", "quels", "quelles",
    # EN
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "must", "of", "in", "to",
    "for", "with", "on", "at", "from", "by", "about", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "each", "every",
    "both", "all", "any", "few", "more", "most", "other", "some", "such",
    "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "and", "but", "or", "if", "while", "that", "this", "what", "which",
    "who", "whom", "how", "when", "where", "why", "it", "its", "they",
    "their", "them", "there", "here",
})

# Cache IDF global (calcule une fois a partir du corpus Qdrant)
_idf_cache: dict[str, float] | None = None
_idf_corpus_size: int = 0


def _tokenize_simple(text: str) -> list[str]:
    """Tokenisation basique multilingue : lowercase, split, filtre stopwords + courts."""
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]{3,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def _get_corpus_idf() -> dict[str, float]:
    """Retourne l'IDF du corpus (calcule une fois, cache en memoire)."""
    global _idf_cache, _idf_corpus_size

    if _idf_cache is not None:
        return _idf_cache

    # Calculer l'IDF a partir de Qdrant (tous les chunks)
    try:
        from knowbase.retrieval.qdrant_layer_r import get_qdrant_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        client = get_qdrant_client()
        collection = settings.qdrant_collection

        # Compter le nombre total de chunks
        info = client.get_collection(collection)
        total_chunks = info.points_count
        if total_chunks == 0:
            _idf_cache = {}
            return _idf_cache

        # Echantillonner des chunks pour construire l'IDF
        # On ne peut pas lire tous les chunks — on en prend un echantillon
        from qdrant_client.models import ScrollRequest
        sample_size = min(total_chunks, 2000)
        results, _ = client.scroll(
            collection_name=collection,
            limit=sample_size,
            with_payload=True,
            with_vectors=False,
        )

        doc_freq: Counter = Counter()
        n_docs = len(results)

        for point in results:
            text = point.payload.get("text", "")
            tokens = set(_tokenize_simple(text))
            for token in tokens:
                doc_freq[token] += 1

        # Calculer IDF : log(N / df) — les termes rares ont un IDF eleve
        _idf_cache = {}
        for token, df in doc_freq.items():
            _idf_cache[token] = math.log(n_docs / df) if df > 0 else 0
        _idf_corpus_size = n_docs

        logger.info(f"[SIGNAL:GAP] IDF index built: {len(_idf_cache)} terms from {n_docs} chunks")

    except Exception as e:
        logger.warning(f"[SIGNAL:GAP] Failed to build IDF index: {e}")
        _idf_cache = {}

    return _idf_cache


def _extract_specific_terms(question: str, top_n: int = 5, min_idf: float = 2.0) -> list[str]:
    """Extrait les termes les plus specifiques de la question (IDF eleve = rare dans le corpus).

    Args:
        question: La question utilisateur
        top_n: Nombre max de termes a retourner
        min_idf: IDF minimum pour qu'un terme soit considere "specifique"
                 (les termes tres courants dans le corpus sont exclus)
    """
    idf = _get_corpus_idf()
    tokens = _tokenize_simple(question)

    if not idf:
        # Fallback sans IDF : garder les tokens non-stopwords de 4+ chars
        return [t for t in tokens if len(t) >= 4][:top_n]

    # Scorer chaque token par son IDF (plus eleve = plus specifique)
    scored = []
    for token in set(tokens):
        idf_score = idf.get(token, math.log(_idf_corpus_size + 1))  # terme inconnu = tres specifique
        # Filtrer les termes trop communs dans le corpus
        if idf_score >= min_idf:
            scored.append((token, idf_score))

    # Trier par IDF decroissant et garder les top_n
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:top_n]]


def _detect_question_context_gap(
    question: str,
    chunks: list[dict],
    kg_claims: list[dict] | None = None,
) -> Signal | None:
    """Detecte un ecart entre les termes specifiques de la question et le contenu des chunks + claims.

    Signal asymetrique :
    - gap eleve = forte indication que les chunks ne repondent pas a la question
    - gap faible = pas de conclusion (les termes sont la mais ca ne prouve pas la repondabilite)

    Verifie dans chunks ET claims (qui peuvent etre dans une autre langue).
    """
    specific_terms = _extract_specific_terms(question, top_n=5)
    if not specific_terms:
        return None

    # Construire le vocabulaire des top chunks + claims KG
    chunk_vocabulary: set[str] = set()
    for chunk in chunks[:10]:
        text = chunk.get("text", "")
        chunk_vocabulary.update(_tokenize_simple(text))

    # Ajouter le vocabulaire des claims KG (souvent en anglais)
    if kg_claims:
        for claim in kg_claims[:20]:
            text = claim.get("text", "")
            chunk_vocabulary.update(_tokenize_simple(text))
            # Aussi les entity_names
            for name in claim.get("entity_names", []):
                chunk_vocabulary.update(_tokenize_simple(name))

    # Verifier la presence de chaque terme specifique
    found_terms = [t for t in specific_terms if t in chunk_vocabulary]
    missing_terms = [t for t in specific_terms if t not in chunk_vocabulary]

    gap_score = len(missing_terms) / len(specific_terms) if specific_terms else 0

    # Seuil : ne signaler que les gaps forts (> 0.6 = majorite des termes absents)
    if gap_score < 0.6:
        return None

    # Score max des chunks (pour la decision combinee dans signal_policy)
    max_chunk_score = max((c.get("score", 0) for c in chunks[:10]), default=0)

    logger.info(
        f"[SIGNAL:GAP] Question-context gap detected: "
        f"gap={gap_score:.2f}, specific={specific_terms}, "
        f"found={found_terms}, missing={missing_terms}, max_chunk_score={max_chunk_score:.3f}"
    )

    return Signal(
        type="question_context_gap",
        strength=gap_score,
        evidence={
            "specific_terms": specific_terms,
            "found_terms": found_terms,
            "missing_terms": missing_terms,
            "gap_score": round(gap_score, 3),
            "max_chunk_score": round(max_chunk_score, 3),
        },
    )
