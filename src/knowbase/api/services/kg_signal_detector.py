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
# Counter supprime — IDF mutualisé dans corpus_stats.py
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

    # Signal 5 — Question-Context Gap (lexical, soft signal only)
    if question and chunks:
        gap = _detect_question_context_gap(question, chunks, kg_claims=kg_claims)
        if gap:
            signals.append(gap)

    # Signal 6 — Dense Answerability (ne sert que pour hors-domaine total)
    if chunks:
        dense_ans = _detect_dense_answerability(chunks)
        if dense_ans:
            signals.append(dense_ans)

    # Signal 7 — QA-Class Answerability (Qwen/vLLM, multilingue)
    # DESACTIVE — cause 62 faux rejets sur 246 questions (31%).
    # Le QA-Class rejette trop de questions answerable (temporal 60%, negation 40%, set_list 36%).
    # A reactiver quand le prompt sera ameliore pour reduire les faux rejets.
    # gap_signal = next((s for s in signals if s.type == "question_context_gap"), None)
    # if question and chunks:
    #     qa_signal = _detect_qa_answerability(question, chunks, gap_signal=gap_signal)
    #     if qa_signal:
    #         signals.append(qa_signal)

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

# IDF mutualisé — remplace la liste figée _STOPWORDS (149 items FR+EN)
# Le filtrage se fait désormais par seuil IDF dans _extract_specific_terms()
from knowbase.common.corpus_stats import get_corpus_idf, get_corpus_size, is_in_corpus


def _tokenize_simple(text: str) -> list[str]:
    """Tokenisation basique multilingue : lowercase, split, filtre courts."""
    return re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]{3,}", text.lower())


def _is_foreign_stopword(term: str, question_lang: str | None = None) -> bool:
    """Verifie si un terme est un stopword dans la langue de la question.

    Utilise les stopwords built-in de spaCy comme oracle de derniere instance
    pour distinguer un mot-outil etranger d'un vrai terme manquant.
    """
    if not question_lang:
        return False
    try:
        from spacy.lang import get_lang_class
        lang_cls = get_lang_class(question_lang)
        return term.lower() in lang_cls.Defaults.stop_words
    except Exception:
        return False


def _detect_question_language(question: str) -> str | None:
    """Detection de langue legere sur la question (fasttext si disponible)."""
    try:
        from knowbase.semantic.utils.language_detector import get_language_detector
        from knowbase.config.settings import get_settings
        settings = get_settings()
        detector = get_language_detector(settings.semantic)
        return detector.detect(question)
    except Exception:
        return None


def _extract_specific_terms(question: str, top_n: int = 5, min_idf: float = 2.0) -> list[str]:
    """Extrait les termes les plus specifiques de la question (IDF eleve = rare dans le corpus).

    Post-review : les termes absents du corpus ne sont plus automatiquement
    consideres comme "tres specifiques". Distinction :
    - Absent ET stopword dans la langue question → ignore (mot-outil etranger)
    - Absent ET PAS stopword → conserve comme gap potentiel (ex: "TLS 1.3")
    """
    idf = get_corpus_idf()
    tokens = _tokenize_simple(question)

    if not idf:
        # Fallback sans IDF : garder les tokens de 4+ chars
        return [t for t in tokens if len(t) >= 4][:top_n]

    corpus_n = get_corpus_size()
    question_lang = _detect_question_language(question)

    scored = []
    for token in set(tokens):
        idf_score = idf.get(token)

        if idf_score is not None:
            # Terme present dans le corpus : filtrer par seuil IDF
            if idf_score >= min_idf:
                scored.append((token, idf_score))
        else:
            # Terme ABSENT du corpus : stopword etranger ou vrai gap ?
            if _is_foreign_stopword(token, question_lang):
                continue  # mot-outil etranger (ex: "che" en italien)
            # Vrai terme absent = gap potentiel, score eleve
            scored.append((token, math.log(corpus_n + 1)))

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


# ── Signal 6 : Dense Answerability ───────────────────────────────────

# Seuil de score dense sous lequel on considere que le retrieval n'a rien trouve de pertinent.
# e5-large renvoie des scores cosine entre 0 et 1. En dessous de 0.35, le chunk est
# thematiquement distant de la question.
DENSE_LOW_THRESHOLD = 0.35


def _detect_dense_answerability(chunks: list[dict]) -> Signal | None:
    """Detecte un faible score dense = le retriever n'a rien trouve de semantiquement proche.

    Avantage majeur vs gap lexical : multilingue par nature (e5-large est cross-lingual).
    "cout" en francais et "cost" en anglais ont des embeddings proches → pas de faux gap.

    Signal asymetrique :
    - score dense faible = forte indication que la question est hors-corpus
    - score dense eleve = pas de conclusion (ne prouve pas que la reponse existe)
    """
    if not chunks:
        return None

    # Extraire les scores denses des top chunks
    dense_scores = []
    for chunk in chunks[:10]:
        ds = chunk.get("_dense_score") or chunk.get("payload", {}).get("_dense_score", 0)
        if ds and isinstance(ds, (int, float)) and ds > 0:
            dense_scores.append(float(ds))

    if not dense_scores:
        return None  # Pas de score dense disponible (fallback dense-only ou ancien format)

    max_dense = max(dense_scores)
    avg_dense = sum(dense_scores) / len(dense_scores)

    # Ne signaler que les cas ou le score dense est clairement faible
    if max_dense >= DENSE_LOW_THRESHOLD:
        return None  # Au moins un chunk est semantiquement proche → pas de signal negatif

    logger.info(
        f"[SIGNAL:DENSE] Low dense answerability: "
        f"max={max_dense:.3f}, avg={avg_dense:.3f}, threshold={DENSE_LOW_THRESHOLD}"
    )

    return Signal(
        type="dense_answerability",
        strength=1.0 - max_dense,  # Plus le score est bas, plus le signal est fort
        evidence={
            "max_dense_score": round(max_dense, 4),
            "avg_dense_score": round(avg_dense, 4),
            "chunks_analyzed": len(dense_scores),
            "threshold": DENSE_LOW_THRESHOLD,
        },
    )


# ── Signal 7 : QA-Class Answerability (Qwen/vLLM) ───────────────────

def _detect_qa_answerability(
    question: str,
    chunks: list[dict],
    gap_signal: Signal | None = None,
) -> Signal | None:
    """Evalue si les chunks permettent de repondre via Qwen/vLLM.

    DECLENCHEMENT CONDITIONNEL : appele uniquement si gap_signal indique
    un doute (gap >= 0.6). Sur les questions ou le gap est faible, on
    ne consomme pas de ressource LLM — le pipeline normal suffit.

    Historique de la decision (1er avril 2026) :
    - V3 prompt tuning : +30pp unanswerable mais -18pp false_premise
    - V4 gap lexical IDF : +54pp mais -67pp multi_hop (cross-lingue)
    - V5 dense score pre-RRF : indiscernable (ecart 0.04)
    - V6 QA-Class Qwen/vLLM : 100% sur 8 paires test, multilingue, 100ms/chunk
    Le QA-Class est la SEULE approche validee experimentalement.
    """
    # Condition de declenchement : gap signal present et >= 0.6
    if not gap_signal:
        return None
    gap_score = gap_signal.evidence.get("gap_score", 0)
    if gap_score < 0.6:
        return None

    try:
        from .qa_class import evaluate_answerability

        result = evaluate_answerability(question, chunks)
        if result is None:
            return None  # vLLM non disponible → pas de signal

        if result.answerable:
            return None  # Au moins 1 chunk repond → pas de signal negatif

        # Aucun chunk ne repond → signal negatif fort
        return Signal(
            type="qa_answerability",
            strength=1.0 - result.max_score,
            evidence={
                "votes": result.votes,
                "scores": result.scores,
                "max_score": result.max_score,
                "latency_ms": result.latency_ms,
                "answerable": result.answerable,
                "triggered_by_gap": round(gap_score, 3),
            },
        )

    except Exception as e:
        logger.debug(f"[SIGNAL:QA] QA-Class failed: {e}")
        return None
