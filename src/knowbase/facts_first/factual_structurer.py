"""
OSMOSIS V4 — FactualStructurer (composant [C], CH-41 Tranche 2 factual).

Transforme un EvidenceBundle en `facts_first_v1` JSON conforme au schéma
`schemas/facts_first/facts_first_v1_factual.json`.

Le LLM extrait des FACTS structurés (subject-predicate-object + qualifiers + source)
avec verbatim quote (D-FF1).

D-FF13 chunk-extractive fallback (intégré ici) :
  Activation si TOUTES les conditions cumulatives :
    - primary_type=factual avec confidence ≥ 0.7
    - FactualStructurer 0 fact OU max confidence < seuil (default 0.7)
    - Top chunk Qdrant score ≥ seuil
    - object.kind ∈ {date, number, identifier, name, currency, duration, boolean}
    - Pas de LOGICAL_RELATION critique signalée
    - Pas de désaccord explicite chunk vs fact

  Sortie : facts_first_v1 valide avec `diagnostic.fallback_mode = "factual_simple_chunk_extractive"`.

Charte D-FF1 : every fact.object.raw + fact.source.quote MUST be from evidence pool.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from knowbase.facts_first.evidence_collector import EvidenceBundle
from knowbase.runtime_v3.llm_client import RuntimeLLMClient, get_runtime_llm_client

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "facts_first_v1"
DEFAULT_TOP_EVIDENCE = 15  # un peu moins que list (factual = single fait, focus)
DEFAULT_CONFIDENCE_THRESHOLD = 0.7  # D-FF13 activation
MIN_QUOTE_CHARS = 10
SHORT_OBJECT_KINDS = {"date", "number", "identifier", "name", "currency", "duration", "boolean"}

# CH-41.4 optim — Composer = Gemma-3-12b-it ; Structurer reste Qwen2.5-72B (raisonnement)
# mais on permet override via env.
# Levier 4 — env unifié FACTS_FIRST_STRUCTURER_MODEL (override appliqué à TOUS les Structurer
# si défini) ; FACTUAL_STRUCTURER_MODEL reste comme alias spécifique factual rétro-compat.
DEFAULT_STRUCTURER_MODEL = (
    os.getenv("FACTS_FIRST_STRUCTURER_MODEL")
    or os.getenv("FACTUAL_STRUCTURER_MODEL")
    or ""
)
DEFAULT_FALLBACK_MODEL = os.getenv("D_FF13_FALLBACK_MODEL", "google/gemma-3-12b-it")  # extract-only, modèle léger ok


SYSTEM_PROMPT = """You are a factual-extraction component for a multi-domain Q&A system. You extract facts that answer the user's question, strictly grounded in the provided evidence pool.

Your output is JSON ONLY (no prose, no markdown), with this exact schema:
{
  "facts": [
    {
      "fact_id": "F1",   // F1, F2, ... unique sequential
      "subject": "<entity / concept / document the fact is about>",
      "predicate": "<short relation/action, e.g. 'was adopted on', 'requires', 'has value'>",
      "object": {
        "raw": "<EXACT verbatim string from evidence (date/number/name/identifier as it appears)>",
        "normalized": "<safe normalized form (e.g. ISO date '2021-05-20') or null>",
        "kind": "<one of: date | number | identifier | name | currency | duration | boolean | text | unknown>",
        "unit": "<unit string if applicable (J, m, kg, %, days), or null>"
      },
      "qualifiers": {
        "condition": "<applicability condition or null>",
        "scope": "<scope of fact (e.g. 'turbine-powered Large Aeroplanes') or null>",
        "time_anchor": "<date/version/amendment anchor or null>",
        "lifecycle_status": "<ACTIVE | DEPRECATED | UNKNOWN>"
      },
      "source": {
        "doc_id": "<doc_id from evidence>",
        "claim_id": "<claim_id from evidence or null>",
        "chunk_id": "<chunk_id from evidence or null>",
        "page_no": <integer or null>,
        "section_id": null,
        "quote": "<EXACT verbatim sentence ≥10 chars supporting this fact>"
      },
      "confidence": <float 0-1>
    }
  ],
  "direct_answer_fact_ids": ["F1", ...]   // subset of facts that directly answer the user's question
}

EXTRACTION RULES (mandatory, no exception):
1. Each fact MUST be supported by a verbatim quote actually in the EVIDENCE POOL. Do not invent.
2. object.raw MUST appear verbatim in the source.quote. Preserve identifiers, dates, numbers, units exactly.
3. If you cannot find ANY fact supported by evidence → return facts=[] and direct_answer_fact_ids=[].
4. If the question asks a single fact, prefer 1 high-confidence fact in direct_answer_fact_ids. Multiple facts only if the question genuinely covers several.
5. confidence reflects evidence strength: 0.9+ if the source quote contains the answer literally; 0.6-0.8 if requires light interpretation; <0.6 if uncertain.
6. lifecycle_status: ACTIVE unless evidence explicitly says deprecated/superseded/withdrawn.

Return only the JSON object, no markdown fences."""


FALLBACK_SYSTEM_PROMPT = """You are a chunk-extractive component. Given a user question and ONE source chunk, extract the verbatim answer if present. Do NOT synthesize, do NOT interpret beyond what the chunk literally says.

Output JSON ONLY:
{
  "found": <true | false>,
  "subject": "<entity the answer is about>",
  "predicate": "<short relation>",
  "object_raw": "<exact verbatim string answering the question>",
  "object_kind": "<date | number | identifier | name | currency | duration | boolean>",
  "object_unit": "<unit or null>",
  "supporting_quote": "<verbatim sentence ≥10 chars from the chunk that contains the answer>",
  "confidence": <float 0-1>
}

Rules:
- Set found=false if the chunk does not contain a clear factual answer.
- supporting_quote MUST be a substring of the chunk text.
- object_raw MUST appear verbatim in supporting_quote.
- No multi-step reasoning. No interpretation. Verbatim only.

Return only the JSON object."""


@dataclass
class StructurerResult:
    facts_first_json: dict
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    rejected_facts: list[dict] = field(default_factory=list)
    used_fallback: bool = False
    fallback_mode: Optional[str] = None  # "factual_simple_chunk_extractive" | "factual_simple_conflict_suspected"


class FactualStructurer:
    """Extracteur factuel grounded + D-FF13 fallback."""

    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        max_facts: int = 8,
        top_evidence: int = DEFAULT_TOP_EVIDENCE,
        temperature: float = 0.05,
        max_tokens: int = 1500,  # CH-46 L6 : 2000→1500 (sortie observée < 1000 tokens)
        timeout: float = 120.0,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        enable_d_ff13: bool = True,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.max_facts = max_facts
        self.top_evidence = top_evidence
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.confidence_threshold = confidence_threshold
        self.enable_d_ff13 = enable_d_ff13

    def structure(
        self,
        question: str,
        evidence: EvidenceBundle,
        language: str = "en",
        analyzer_confidence: float = 0.0,
        domain_pack: Optional[str] = None,
        tenant_id: str = "default",
        feedback_for_retry: Optional[str] = None,
    ) -> StructurerResult:
        """Extract facts grounded dans evidence ; activate D-FF13 si conditions remplies.

        Args:
            analyzer_confidence: confidence du QuestionAnalyzer (≥ 0.7 single-label = condition D-FF13)
            feedback_for_retry: retour du verifier sur la précédente tentative (SelfCorrector)
        """
        t0 = time.time()

        if not evidence.claims:
            return self._make_empty_result(
                question=question, evidence=evidence, language=language,
                domain_pack=domain_pack, tenant_id=tenant_id,
                reason="no_evidence", t0=t0,
            )

        # 1. Appel principal Structurer LLM
        ev_pool = sorted(evidence.claims, key=lambda c: c.score, reverse=True)[: self.top_evidence]
        primary_result = self._extract_facts_llm(question, ev_pool, language, t0, feedback_for_retry=feedback_for_retry)

        # 2. Décider si D-FF13 fallback s'applique
        primary_facts = primary_result["validated_facts"]
        if self.enable_d_ff13 and self._should_trigger_d_ff13(
            primary_facts, ev_pool, analyzer_confidence, evidence
        ):
            logger.info("[FactualStructurer] D-FF13 fallback triggered")
            fallback_result = self._chunk_extractive_fallback(question, ev_pool, language, t0)
            if fallback_result is not None:
                # Si fallback OK et primary 0 fact OR conflict signalé
                fallback_fact = fallback_result.get("fact")
                if fallback_fact:
                    fallback_mode = self._detect_conflict(primary_facts, fallback_fact)
                    return self._make_result(
                        facts=[fallback_fact],
                        question=question, evidence=evidence, language=language,
                        domain_pack=domain_pack, tenant_id=tenant_id,
                        primary_result=primary_result, t0=t0,
                        used_fallback=True, fallback_mode=fallback_mode,
                    )

        # 3. Sortie standard (Structurer principal)
        return self._make_result(
            facts=primary_facts,
            question=question, evidence=evidence, language=language,
            domain_pack=domain_pack, tenant_id=tenant_id,
            primary_result=primary_result, t0=t0,
            used_fallback=False, fallback_mode=None,
        )

    # ------------------------------------------------------------------ extraction

    def _extract_facts_llm(
        self,
        question: str,
        ev_pool,
        language: str,
        t0: float,
        feedback_for_retry: Optional[str] = None,
    ) -> dict:
        """Appel LLM principal pour extraire les facts. Retourne dict avec validated_facts + meta."""
        evidence_block = self._format_evidence_pool(ev_pool)
        feedback_section = ""
        if feedback_for_retry:
            feedback_section = (
                f"\n\nPREVIOUS ATTEMPT FEEDBACK (from verifier — fix these issues):\n"
                f"{feedback_for_retry.strip()[:600]}\n"
            )
        user_prompt = (
            f"QUESTION (language={language}): {question.strip()}\n\n"
            f"EVIDENCE POOL ({len(ev_pool)} candidates ranked by score):\n"
            f"{evidence_block}{feedback_section}\n\n"
            "Extract facts strictly grounded in this evidence. Output JSON only."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            kwargs = {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "json_mode": True,
                "timeout": self.timeout,
            }
            if DEFAULT_STRUCTURER_MODEL:
                kwargs["model_override"] = DEFAULT_STRUCTURER_MODEL
            meta = self.llm.chat_completion_with_meta(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FactualStructurer LLM call failed: %s", exc)
            return {
                "validated_facts": [], "rejected_facts": [],
                "raw": "", "model": "", "provider": "",
                "parse_error": str(exc), "direct_answer_fact_ids": [],
            }

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {
                "validated_facts": [], "rejected_facts": [],
                "raw": raw[:600], "model": meta.get("model", ""), "provider": meta.get("provider", ""),
                "parse_error": f"json_parse: {exc}", "direct_answer_fact_ids": [],
            }

        validated, rejected = self._validate_facts(parsed.get("facts", []), ev_pool)
        direct_ids = [f["fact_id"] for f in validated if f["fact_id"] in (parsed.get("direct_answer_fact_ids") or [])]
        if not direct_ids and validated:
            # Si LLM n'a pas spécifié, prendre le fact le plus confident
            direct_ids = [max(validated, key=lambda f: f["confidence"])["fact_id"]]

        return {
            "validated_facts": validated, "rejected_facts": rejected,
            "raw": raw[:600], "model": meta.get("model", ""), "provider": meta.get("provider", ""),
            "parse_error": None, "direct_answer_fact_ids": direct_ids,
        }

    def _validate_facts(self, raw_facts, ev_pool):
        """Filtre les facts hallucinés (quote pas dans pool, raw pas dans quote)."""
        valid: list[dict] = []
        rejected: list[dict] = []
        pool_quotes_norm = [(c, " ".join((c.quote or "").lower().split())) for c in ev_pool]

        for raw in (raw_facts or [])[: self.max_facts]:
            if not isinstance(raw, dict):
                rejected.append({"reason": "not_object", "raw": str(raw)[:200]})
                continue
            subject = str(raw.get("subject") or "").strip()
            predicate = str(raw.get("predicate") or "").strip()
            obj = raw.get("object") or {}
            if not subject or not predicate:
                rejected.append({"reason": "missing_subject_or_predicate"})
                continue
            obj_raw = str(obj.get("raw") or "").strip()
            if not obj_raw:
                rejected.append({"reason": "missing_object_raw"})
                continue
            src = raw.get("source") or {}
            quote = str(src.get("quote") or "").strip()
            if len(quote) < MIN_QUOTE_CHARS:
                rejected.append({"reason": "quote_too_short"})
                continue
            if not self._quote_grounded(quote, pool_quotes_norm):
                rejected.append({"reason": "quote_not_grounded", "quote": quote[:200]})
                continue
            # Vérification : object.raw doit apparaître dans la quote (sinon halluciné)
            if obj_raw.lower() not in quote.lower() and not self._fuzzy_in_quote(obj_raw, quote):
                rejected.append({"reason": "object_raw_not_in_quote", "obj_raw": obj_raw, "quote": quote[:120]})
                continue

            try:
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5

            kind = str(obj.get("kind") or "unknown").strip()
            qualifiers = raw.get("qualifiers") or {}
            normalized_qualifiers = {
                "condition": qualifiers.get("condition"),
                "scope": qualifiers.get("scope"),
                "time_anchor": qualifiers.get("time_anchor"),
                "lifecycle_status": str(qualifiers.get("lifecycle_status") or "UNKNOWN"),
            }

            valid.append({
                "fact_id": f"F{len(valid) + 1}",
                "subject": subject[:300],
                "predicate": predicate[:200],
                "object": {
                    "raw": obj_raw[:500],
                    "normalized": obj.get("normalized"),
                    "kind": kind,
                    "unit": obj.get("unit"),
                },
                "qualifiers": normalized_qualifiers,
                "source": {
                    "doc_id": str(src.get("doc_id") or "unknown"),
                    "claim_id": src.get("claim_id"),
                    "chunk_id": src.get("chunk_id"),
                    "page_no": src.get("page_no"),
                    "section_id": src.get("section_id"),
                    "quote": quote[:1000],
                },
                "confidence": confidence,
            })
        return valid, rejected

    @staticmethod
    def _quote_grounded(quote: str, pool_quotes_norm) -> bool:
        q_norm = " ".join(quote.lower().split())
        if len(q_norm) < MIN_QUOTE_CHARS:
            return False
        for _, pool_q in pool_quotes_norm:
            if q_norm in pool_q or pool_q in q_norm:
                return True
        item_tokens = set(t for t in q_norm.split() if len(t) > 3)
        if not item_tokens:
            return False
        for _, pool_q in pool_quotes_norm:
            pool_tokens = set(t for t in pool_q.split() if len(t) > 3)
            if not pool_tokens:
                continue
            overlap = len(item_tokens & pool_tokens) / max(1, len(item_tokens))
            if overlap >= 0.5:
                return True
        return False

    @staticmethod
    def _fuzzy_in_quote(value: str, quote: str) -> bool:
        """Tolère petite paraphrase (ex 'May 2021' vs 'May 2021 in OJ').

        Word boundary check (pas substring) : "20" ne match PAS "2021".
        """
        import re
        v = value.lower().strip()
        q_lower = quote.lower()
        if v in q_lower:
            return True
        v_tokens = [t for t in v.split() if len(t) > 1]
        if not v_tokens:
            return False
        # Tokens de la quote (split on non-alphanum) pour word boundary match
        q_tokens = set(re.findall(r"[a-z0-9]+", q_lower))
        return all(t in q_tokens for t in v_tokens)

    # ------------------------------------------------------------------ D-FF13

    def _should_trigger_d_ff13(
        self, primary_facts: list[dict], ev_pool, analyzer_confidence: float, evidence: EvidenceBundle
    ) -> bool:
        """Conditions cumulatives ADR D-FF13."""
        # Cond 1 : analyzer confidence ≥ 0.7 (single-label factual)
        if analyzer_confidence < self.confidence_threshold:
            return False
        # Cond 2 : Structurer 0 fact OR max confidence < threshold
        if primary_facts:
            max_conf = max(f["confidence"] for f in primary_facts)
            if max_conf >= self.confidence_threshold:
                return False  # primary suffisant, pas besoin fallback
        # Cond 3 : top chunk score ≥ threshold (en pratique, ev_pool[0] = top)
        if not ev_pool or ev_pool[0].score < self.confidence_threshold:
            return False
        # Cond 5 : pas de LOGICAL_RELATION critique
        # (on ne vérifie pas activement ici — l'EvidenceBundle.diagnostic pourrait la signaler)
        if (evidence.diagnostic or {}).get("has_critical_logical_relation"):
            return False
        return True

    def _chunk_extractive_fallback(
        self, question: str, ev_pool, language: str, t0: float
    ) -> Optional[dict]:
        """Extract verbatim depuis top chunk uniquement (LLM extract-only mode)."""
        if not ev_pool:
            return None
        top = ev_pool[0]
        top_quote = top.quote or ""

        user_prompt = (
            f"QUESTION (language={language}): {question.strip()}\n\n"
            f"CHUNK (verbatim source):\n{top_quote[:1500]}\n\n"
            "Extract the verbatim answer if present. Output JSON only."
        )
        messages = [
            {"role": "system", "content": FALLBACK_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            meta = self.llm.chat_completion_with_meta(
                messages=messages,
                temperature=0.0, max_tokens=400,
                json_mode=True, timeout=self.timeout,
                model_override=DEFAULT_FALLBACK_MODEL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("D-FF13 fallback LLM failed: %s", exc)
            return None

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not parsed.get("found"):
            return None

        kind = str(parsed.get("object_kind") or "unknown").strip().lower()
        if kind not in SHORT_OBJECT_KINDS:
            # D-FF13 ne traite que les kinds courts
            return None

        obj_raw = str(parsed.get("object_raw") or "").strip()
        supporting = str(parsed.get("supporting_quote") or "").strip()
        if not obj_raw or len(supporting) < MIN_QUOTE_CHARS:
            return None
        # Validation : obj_raw doit être dans supporting + supporting dans top chunk
        if obj_raw.lower() not in supporting.lower():
            return None
        if " ".join(supporting.lower().split()) not in " ".join(top_quote.lower().split()):
            # tolérance
            if not self._fuzzy_in_quote(supporting, top_quote):
                return None

        try:
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.7))))
        except (TypeError, ValueError):
            confidence = 0.7

        fact = {
            "fact_id": "F1",
            "subject": str(parsed.get("subject") or "").strip()[:300] or "the document",
            "predicate": str(parsed.get("predicate") or "").strip()[:200] or "states",
            "object": {
                "raw": obj_raw[:500],
                "normalized": None,
                "kind": kind,
                "unit": parsed.get("object_unit"),
            },
            "qualifiers": {
                "condition": None, "scope": None,
                "time_anchor": None, "lifecycle_status": "UNKNOWN",
            },
            "source": {
                "doc_id": top.doc_id,
                "claim_id": None,  # D-FF13 source = chunk, pas claim
                "chunk_id": top.chunk_id or top.claim_id,
                "page_no": top.page_no,
                "section_id": None,
                "quote": supporting[:1000],
            },
            "confidence": confidence,
        }
        return {"fact": fact, "raw": raw[:600], "model": meta.get("model", "")}

    @staticmethod
    def _detect_conflict(primary_facts: list[dict], fallback_fact: dict) -> str:
        """Détecte désaccord entre primary fact (faible) et fallback fact."""
        if not primary_facts:
            return "factual_simple_chunk_extractive"
        primary_top = max(primary_facts, key=lambda f: f["confidence"])
        # Si même subject mais object.raw diverge → conflit suspect
        same_subject = primary_top["subject"].lower().strip() == fallback_fact["subject"].lower().strip()
        primary_raw = primary_top["object"]["raw"].lower().strip()
        fallback_raw = fallback_fact["object"]["raw"].lower().strip()
        if same_subject and primary_raw and fallback_raw and primary_raw != fallback_raw:
            return "factual_simple_conflict_suspected"
        return "factual_simple_chunk_extractive"

    # ------------------------------------------------------------------ helpers

    def _format_evidence_pool(self, ev_pool) -> str:
        lines = []
        for i, c in enumerate(ev_pool, 1):
            cid = c.claim_id or c.chunk_id or "?"
            quote = (c.quote or "").replace("\n", " ").strip()[:400]
            lines.append(f"EV{i} | doc={c.doc_id} | claim={cid} | quote: {quote}")
        return "\n".join(lines)

    def _make_result(
        self,
        facts: list[dict],
        question: str,
        evidence: EvidenceBundle,
        language: str,
        domain_pack: Optional[str],
        tenant_id: str,
        primary_result: dict,
        t0: float,
        used_fallback: bool,
        fallback_mode: Optional[str],
    ) -> StructurerResult:
        # answerability
        if not facts:
            answerability = "unanswerable"
            coverage = "unknown"
        elif fallback_mode == "factual_simple_conflict_suspected":
            answerability = "partial"
            coverage = "unknown"
        else:
            answerability = "answerable"
            coverage = "not_applicable"  # factual = single-fact, pas d'enum

        direct_ids = primary_result.get("direct_answer_fact_ids") or []
        if used_fallback:
            direct_ids = ["F1"]  # fallback returns one fact

        ff = {
            "schema_version": SCHEMA_VERSION,
            "primary_type": "factual",
            "secondary_type": None,
            "answerability": answerability,
            "coverage_state": coverage,
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": f"{primary_result.get('model') or 'unknown'}@{primary_result.get('provider') or 'unknown'}",
            "tenant_id": tenant_id,
            "domain_pack": domain_pack,
            "factual_specific": {
                "facts": facts,
                "direct_answer_fact_ids": direct_ids,
            },
            "diagnostic": {
                "latency_ms": int((time.time() - t0) * 1000),
                "evidence_count": len(evidence.claims),
                "rejected_facts_count": len(primary_result.get("rejected_facts") or []),
                "fallback_mode": fallback_mode,
            },
        }
        return StructurerResult(
            facts_first_json=ff,
            raw_llm_output=primary_result.get("raw", ""),
            latency_ms=int((time.time() - t0) * 1000),
            model=primary_result.get("model", ""),
            provider=primary_result.get("provider", ""),
            parse_error=primary_result.get("parse_error"),
            rejected_facts=primary_result.get("rejected_facts") or [],
            used_fallback=used_fallback,
            fallback_mode=fallback_mode,
        )

    def _make_empty_result(
        self,
        question: str,
        evidence: EvidenceBundle,
        language: str,
        domain_pack: Optional[str],
        tenant_id: str,
        reason: str,
        t0: float,
    ) -> StructurerResult:
        ff = {
            "schema_version": SCHEMA_VERSION,
            "primary_type": "factual",
            "secondary_type": None,
            "answerability": "unanswerable",
            "coverage_state": "unknown",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": "none@none",
            "tenant_id": tenant_id,
            "domain_pack": domain_pack,
            "factual_specific": {"facts": [], "direct_answer_fact_ids": []},
            "diagnostic": {
                "latency_ms": int((time.time() - t0) * 1000),
                "evidence_count": len(evidence.claims),
                "reason": reason,
                "fallback_mode": None,
            },
        }
        return StructurerResult(facts_first_json=ff, latency_ms=int((time.time() - t0) * 1000))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_default: Optional[FactualStructurer] = None


def get_factual_structurer() -> FactualStructurer:
    global _default
    if _default is None:
        _default = FactualStructurer()
    return _default


def reset_factual_structurer() -> None:
    global _default
    _default = None
