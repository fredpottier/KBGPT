"""Extracteur de KeyPoint : normalise un claim en la QUESTION neutre qu'il adresse.

Cœur de la couche KeyPoint. Deux claims qui donnent des réponses OPPOSÉES à la
même interrogation doivent produire une `normative_question` IDENTIQUE → bucket
exact → la contradiction devient visible par construction.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class KeyPointSignature(BaseModel):
    """Signature « même question » d'un claim."""

    normative_question: str = Field(default="")
    predicate: str = Field(default="")
    object: str = Field(default="")
    stance: str = Field(default="none")  # affirms|denies|increases|decreases|equals|none
    answer: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


_SYSTEM_PROMPT = """You normalize a scientific CLAIM into the neutral QUESTION it answers, so that
claims giving OPPOSITE answers to the same matter share an IDENTICAL question string.

Return ONLY valid JSON:
{
  "normative_question": "neutral question the claim addresses (lowercase, NO answer/value inside)",
  "predicate": "normalized relation verb in snake_case",
  "object": "the outcome/entity the predicate acts on",
  "stance": "one of: affirms | denies | increases | decreases | equals | none",
  "answer": "the claim's specific answer (may include the value/direction)",
  "confidence": 0.0
}

RULES
1. NEUTRAL question: two claims with OPPOSITE conclusions about the same matter MUST yield the
   SAME normative_question. Put the answer/value in "answer", NEVER inside the question.
2. Expand acronyms/abbreviations using the DOMAIN GLOSSARY when available (e.g. "TMREL" ->
   "theoretical minimum risk exposure level"). Use the generic expanded concept in the question.
3. Frame at the COMPARABLE DIMENSION level, not the surface subject. Prefer
   "what level of alcohol consumption minimises health risk?" over "alcohol consumption".
4. Boilerplate/metadata (funding, grant id, study selection, authorship, methodology housekeeping)
   -> normative_question: "" and stance: "none".
5. CONCISE: question <= 16 words, lowercase, end with "?".

EXAMPLES
Claim: "The level of alcohol consumption that minimised harm across health outcomes was zero."
-> {"normative_question":"what level of alcohol consumption minimises health risk?","predicate":"has_minimum_risk_level","object":"alcohol consumption","stance":"equals","answer":"zero","confidence":0.95}

Claim: "The TMREL among individuals aged 40 and older ranged from 0.114 to 1.87 drinks per day."
-> {"normative_question":"what level of alcohol consumption minimises health risk?","predicate":"has_minimum_risk_level","object":"alcohol consumption","stance":"equals","answer":"non-zero for ages 40 and older","confidence":0.9}

Claim: "Consumption of small amounts of alcohol lowers the risk of cardiovascular disease."
-> {"normative_question":"does light-to-moderate alcohol consumption affect cardiovascular disease risk?","predicate":"affects_risk_of","object":"cardiovascular disease","stance":"decreases","answer":"lowers risk at small amounts","confidence":0.9}

Claim: "Mendelian randomization shows alcohol intake monotonically increases cardiovascular risk."
-> {"normative_question":"does light-to-moderate alcohol consumption affect cardiovascular disease risk?","predicate":"affects_risk_of","object":"cardiovascular disease","stance":"increases","answer":"monotonic increase, no protective level","confidence":0.9}

Claim: "This work was supported by grant ID-585-CTR."
-> {"normative_question":"","predicate":"","object":"","stance":"none","answer":"","confidence":0.95}
"""


class KeyPointExtractor:
    """Appelle le LLM (burst) pour produire la signature KeyPoint d'un claim."""

    def __init__(self, llm_router: Any = None):
        if llm_router is None:
            from knowbase.common.llm_router import get_llm_router
            llm_router = get_llm_router()
        self.llm_router = llm_router
        try:
            from knowbase.ontology.domain_context_injector import get_domain_context_injector
            self.context_injector = get_domain_context_injector()
        except Exception:
            self.context_injector = None

    def _system_prompt(self, tenant_id: str) -> str:
        if self.context_injector:
            try:
                return self.context_injector.inject_context(_SYSTEM_PROMPT, tenant_id)
            except Exception:
                pass
        return _SYSTEM_PROMPT

    def extract(
        self,
        claim_text: str,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
        passage: Optional[str] = None,
        tenant_id: str = "default",
    ) -> Optional[KeyPointSignature]:
        from knowbase.common.llm_router import TaskType

        ctx = []
        if subject:
            ctx.append(f"subject (may be coarse): {subject}")
        if predicate:
            ctx.append(f"predicate: {predicate}")
        if obj:
            ctx.append(f"object: {obj}")
        if passage:
            ctx.append(f"source passage: {passage[:400]}")
        user = f"Claim: \"{claim_text}\""
        if ctx:
            user += "\n\nContext:\n- " + "\n- ".join(ctx)
        user += "\n\nReturn the JSON now."

        try:
            resp = self.llm_router.complete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": self._system_prompt(tenant_id)},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = _parse_json(resp)
            if data is None:
                return None
            sig = KeyPointSignature(**{k: data.get(k) for k in KeyPointSignature.model_fields if data.get(k) is not None})
            # Normalisation finale de la question (clé de bucket)
            sig.normative_question = normalize_question(sig.normative_question)
            return sig
        except Exception as e:
            logger.warning(f"[KeyPoint] extract failed: {e}")
            return None


# Normalisation orthographique britannique -> américaine (les corpus mêlent les
# deux : « minimise » GBD2018 vs « minimize » GBD2020 sépareraient un même KeyPoint).
_SPELLING = {
    "minimise": "minimize", "minimised": "minimized", "minimises": "minimizes",
    "minimising": "minimizing", "maximise": "maximize", "maximised": "maximized",
    "maximises": "maximizes", "characterise": "characterize",
    "characterised": "characterized", "hospitalisation": "hospitalization",
    "behaviour": "behavior", "favourable": "favorable", "haemorrhagic": "hemorrhagic",
    "oesophageal": "esophageal", "ageing": "aging", "foetal": "fetal",
    "paediatric": "pediatric", "tumour": "tumor", "analyse": "analyze",
    "analysed": "analyzed",
}


def normalize_question(q: Optional[str]) -> str:
    """Normalise la question pour servir de clé de bucket exact (casse, espaces,
    orthographe FR/US, ponctuation finale)."""
    if not q:
        return ""
    words = str(q).strip().lower().split()
    words = [_SPELLING.get(w.strip("?.,;:"), w) for w in words]
    q = " ".join(words)
    q = q.rstrip(" .")
    if q and not q.endswith("?"):
        q += "?"
    return q


def _parse_json(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    # retirer fences éventuels
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s.strip("`")
        s = s.replace("json", "", 1).strip() if s.lower().startswith("json") else s
    try:
        return json.loads(s)
    except Exception:
        # tenter d'isoler le 1er objet {...}
        i, j = s.find("{"), s.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except Exception:
                return None
    return None
