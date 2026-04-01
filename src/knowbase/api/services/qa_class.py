"""
OSMOSIS QA-Class — Question-Answerability Classifier.

Evalue si les top chunks permettent de repondre a la question
via le llm_router (route automatiquement vers vLLM/Qwen si burst actif).

Declenchement conditionnel : appele UNIQUEMENT quand le signal
question_context_gap indique un doute (gap >= 0.6). Pas sur toute question.

Historique de la decision (1er avril 2026) :
- V3 prompt tuning : +30pp unanswerable mais -18pp sur false_premise
- V4 gap lexical IDF : +54pp mais -67pp multi_hop (cross-lingue)
- V5 dense score pre-RRF : indiscernable (ecart 0.04)
- V6 QA-Class Qwen/vLLM : 100% sur 8 paires test, multilingue, 100ms/chunk
Le QA-Class est la SEULE approche validee experimentalement.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

QA_CLASS_PROMPT = """Given a question and a text chunk from a document, determine if the chunk contains enough information to answer the question.

Question: "{question}"
Chunk: "{chunk}"

Answer with EXACTLY one word: YES, PARTIAL, or NO.
- YES: the chunk directly answers the question
- PARTIAL: the chunk is related but does not fully answer
- NO: the chunk does not help answer this question"""

MAX_CHUNKS_TO_EVALUATE = 3
MAX_CHUNK_CHARS = 500


@dataclass
class AnswerabilityResult:
    """Resultat du QA-Class sur les top chunks."""
    answerable: bool  # True si au moins 1 chunk YES ou PARTIAL
    votes: list[str]  # ["NO", "PARTIAL", "YES"] pour chaque chunk
    scores: list[float]  # 0=NO, 0.5=PARTIAL, 1.0=YES
    max_score: float
    latency_ms: int
    vllm_available: bool


def evaluate_answerability(
    question: str,
    chunks: list[dict],
) -> AnswerabilityResult | None:
    """Evalue si les top chunks permettent de repondre a la question.

    Utilise le llm_router qui route automatiquement vers vLLM/Qwen si
    le burst est actif, sinon vers le provider par defaut.

    Retourne None si le LLM n'est pas disponible.
    """
    try:
        from knowbase.common.llm_router import LLMRouter, TaskType
        router = LLMRouter()
    except Exception as e:
        logger.debug(f"[QA-CLASS] LLM router not available: {e}")
        return None

    # Verifier que le burst est actif (on ne veut pas consommer des credits API)
    redis_state = router._get_vllm_state_from_redis()
    if not redis_state or not redis_state.get("healthy"):
        logger.debug("[QA-CLASS] vLLM not active, skipping QA-Class")
        return None

    start = time.time()
    votes = []
    scores = []

    top_chunks = chunks[:MAX_CHUNKS_TO_EVALUATE]

    for chunk in top_chunks:
        text = chunk.get("text", "")
        if not text or len(text) < 20:
            votes.append("NO")
            scores.append(0.0)
            continue

        try:
            prompt = QA_CLASS_PROMPT.format(
                question=question[:300],
                chunk=text[:MAX_CHUNK_CHARS],
            )
            answer = router.complete(
                task_type=TaskType.FAST_CLASSIFICATION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=5,
            ).strip().upper()

            # Normaliser
            if "YES" in answer:
                vote = "YES"
            elif "PARTIAL" in answer:
                vote = "PARTIAL"
            else:
                vote = "NO"

            votes.append(vote)
            scores.append({"YES": 1.0, "PARTIAL": 0.5, "NO": 0.0}[vote])

        except Exception as e:
            logger.debug(f"[QA-CLASS] LLM call failed: {e}")
            votes.append("UNKNOWN")
            scores.append(0.5)  # En cas d'erreur, ne pas penaliser

    latency_ms = int((time.time() - start) * 1000)
    max_score = max(scores) if scores else 0
    answerable = max_score > 0  # Au moins 1 YES ou PARTIAL

    logger.info(
        f"[QA-CLASS] votes={votes}, max_score={max_score}, "
        f"answerable={answerable}, latency={latency_ms}ms"
    )

    return AnswerabilityResult(
        answerable=answerable,
        votes=votes,
        scores=scores,
        max_score=max_score,
        latency_ms=latency_ms,
        vllm_available=True,
    )
