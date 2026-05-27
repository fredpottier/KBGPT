"""
decomposition_stage.py — P1.4b-3 : Stage B de l'extraction (décomposition à minimalité
+ décontextualisation), cœur de la refonte ADR_P1_4_BIS.

Prend les unités RETENUES par Stage A (selection_gate) + le contexte du passage, et produit
des claims structurés au schéma « liste-comme-champ » (validé P1.4b-0 sur Qwen2.5-14B) :
    {subject, predicate, objects[], modality, polarity, self_contained_text, source_unit_ids}

Règles (alignées SOTA Volet 1+2 + revue) :
- MINIMALITÉ (#1) : 1 assertion = 1 claim ; une ÉNUMÉRATION d'items partageant
  subject+predicate → UN claim dont `objects` liste les items (PAS N claims). Des prédicats
  DIFFÉRENTS → claims séparés. Ne pas mettre des sujets coordonnés dans `objects`.
- DÉCONTEXTUALISATION (Q2) : résoudre les anaphores via le contexte du passage ; NOMMER le
  sujet (pas « it »/« the system ») ; si irrésoluble, faire au mieux SANS inventer (NULL>faux).
- MODALITÉ (Q6) : préserver must/shall/may/recommended/conditional + la POLARITÉ (négation !).
- IDENTIFIANTS (Q5) : reprendre les codes/nombres VERBATIM (ne pas paraphraser).
- `self_contained_text` = phrase autonome et fluide. `source_unit_ids` = unités d'origine.

LLM INJECTABLE (`llm_call(system, user) -> str` JSON) → testable + portable (vLLM burst
Qwen2.5-14B prod / DeepInfra dev). Le caller fournit le guided decoding (DECOMPOSITION_JSON_SCHEMA).
Défaillance LLM/parse → liste vide + flag (le caller peut retomber sur l'ancien chemin).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MODALITIES = ["assertive", "prescriptive", "permissive", "recommended", "conditional", "procedural"]
_POLARITIES = ["affirmative", "negative"]

DECOMPOSITION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "objects": {"type": "array", "items": {"type": "string"}},
                    "modality": {"type": "string", "enum": _MODALITIES},
                    "polarity": {"type": "string", "enum": _POLARITIES},
                    "self_contained_text": {"type": "string"},
                    "source_unit_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["subject", "predicate", "objects", "modality",
                             "polarity", "self_contained_text"],
            },
        }
    },
    "required": ["claims"],
}

SYSTEM_PROMPT = """You convert text units from a document into atomic knowledge claims for a \
retrieval knowledge base. Produce STRICT JSON: {"claims":[{...}]}.

Each claim has: subject, predicate, objects (array), modality, polarity, self_contained_text, \
source_unit_ids (array of the given unit ids it came from).

RULES:
1. MOLECULAR GRANULARITY (most important): each claim is ONE self-contained, SALIENT fact that \
COMBINES the closely-related details belonging to it (its condition, qualifier, named objects, \
outcome). Do NOT over-split: prose describing a single fact must stay ONE claim — never fragment \
a sentence into multiple sub-claims, one per clause or detail. Produce FEWER, richer claims. \
Emit a SEPARATE claim ONLY for a genuinely DISTINCT fact (different subject, or an independent \
assertion that a user would ask about on its own). Rule of thumb: usually ≤1 claim per sentence; \
emit several from one sentence only when it truly states multiple independent facts.
   - An enumeration of items sharing the SAME subject and predicate → ONE claim whose `objects` \
lists all items (never one claim per item). Never place coordinated SUBJECTS into `objects`.
   - A single fact uses a one-element `objects` array. Keep a condition/qualifier inside the \
claim's text rather than spawning a separate claim for it.
2. DECONTEXTUALIZE: resolve pronouns/anaphora using the passage context; NAME the subject \
explicitly (never leave "it" / "the system" / "this"). If the referent is genuinely unknown, \
keep the best literal subject — do NOT invent one.
3. MODALITY: choose ONE — procedural (an executable ACTION/STEP performed as part of a task or \
sequence: "run X", "execute Y", "click Z", "first do…then…"), prescriptive (an obligation, \
requirement or constraint: must/shall/required), permissive (may/can/allowed), recommended \
(should/recommended), conditional (if/when…), else assertive. Use `procedural` ONLY for an \
executable step/action — NOT for a mere requirement, property or capability (those are \
prescriptive/assertive). PRESERVE it.
4. POLARITY: set polarity = negative if the statement is a negation (not/no/cannot/never), \
else affirmative. NEVER drop a negation.
5. IDENTIFIERS: copy codes, identifiers and numeric values VERBATIM from the source — never \
paraphrase or alter them.
6. self_contained_text = one fluent standalone sentence capturing the whole molecular fact.

Be domain-neutral (software, medical, legal, engineering…). Do not add facts absent from the source.

Examples (note: related details stay in ONE claim, not split):
- Units: "[u1] The kit includes a cable, a charger, and a manual." ->
  {"subject":"The kit","predicate":"includes","objects":["a cable","a charger","a manual"],
   "modality":"assertive","polarity":"affirmative",
   "self_contained_text":"The kit includes a cable, a charger, and a manual.","source_unit_ids":["u1"]}
- Units: "[u2] The deletion requires the authorization object S_TABU_DIS and cannot be undone." ->
  ONE claim (the deletion's requirement + irreversibility are facets of the same fact), NOT two:
  {"subject":"The deletion","predicate":"requires","objects":["the authorization object S_TABU_DIS"],
   "modality":"prescriptive","polarity":"affirmative",
   "self_contained_text":"The deletion requires the authorization object S_TABU_DIS and cannot be undone.","source_unit_ids":["u2"]}
- Units: "[u3] It must not be used in production." (context: the experimental API) ->
  {"subject":"The experimental API","predicate":"must be used in","objects":["production"],
   "modality":"prescriptive","polarity":"negative",
   "self_contained_text":"The experimental API must not be used in production.","source_unit_ids":["u3"]}
- Units: "[u4] Run the SI-Check before starting the conversion." (an executable step) ->
  {"subject":"the SI-Check","predicate":"run before","objects":["starting the conversion"],
   "modality":"procedural","polarity":"affirmative",
   "self_contained_text":"Run the SI-Check before starting the conversion.","source_unit_ids":["u4"]}
"""


@dataclass
class ClaimCandidate:
    subject: str
    predicate: str
    objects: List[str]
    modality: str
    polarity: str
    self_contained_text: str
    source_unit_ids: List[str] = field(default_factory=list)

    @property
    def is_enumeration(self) -> bool:
        return len(self.objects) > 1


@dataclass
class DecompositionResult:
    claims: List[ClaimCandidate] = field(default_factory=list)
    judge_failed: bool = False

    @property
    def n_claims(self) -> int:
        return len(self.claims)


def build_user_prompt(units: List[Tuple[str, str]], passage_context: str) -> str:
    lines = []
    if passage_context:
        lines.append(f"Passage context (read-only, for disambiguation):\n\"\"\"{passage_context}\"\"\"\n")
    lines.append("Units to convert into claims:")
    for uid, text in units:
        lines.append(f"[{uid}] {text}")
    lines.append("\nJSON:")
    return "\n".join(lines)


def _parse(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        if start >= 0:
            depth = 0
            for k in range(start, len(raw)):
                depth += (raw[k] == "{") - (raw[k] == "}")
                if depth == 0:
                    try:
                        return json.loads(raw[start:k + 1])
                    except Exception:
                        return None
        return None


def _coerce_claim(item: dict, valid_ids: set) -> Optional[ClaimCandidate]:
    subj = str(item.get("subject", "")).strip()
    pred = str(item.get("predicate", "")).strip()
    if not subj or not pred:
        return None
    objs = item.get("objects")
    if isinstance(objs, str):
        objs = [objs]
    objs = [str(o).strip() for o in (objs or []) if str(o).strip()]
    modality = str(item.get("modality", "assertive")).strip().lower()
    if modality not in _MODALITIES:
        modality = "assertive"
    polarity = str(item.get("polarity", "affirmative")).strip().lower()
    if polarity not in _POLARITIES:
        polarity = "affirmative"
    sct = str(item.get("self_contained_text", "")).strip() or f"{subj} {pred} {', '.join(objs)}".strip()
    src = [str(s) for s in (item.get("source_unit_ids") or []) if str(s) in valid_ids]
    return ClaimCandidate(subj, pred, objs, modality, polarity, sct, src)


class DecompositionStage:
    """Stage B : unités retenues → claims structurés (schéma objects[])."""

    def __init__(self, llm_call: Callable[[str, str], str], enabled: bool = True):
        self.llm_call = llm_call
        self.enabled = enabled

    def decompose(
        self, units: List[Tuple[str, str]], passage_context: str = ""
    ) -> DecompositionResult:
        """Variante synchrone (llm_call sync). Utilisée en test/standalone."""
        if not units or not self.enabled:
            return DecompositionResult()
        try:
            raw = self.llm_call(SYSTEM_PROMPT, build_user_prompt(units, passage_context))
            parsed = _parse(raw)
        except Exception as exc:
            logger.warning("[DecompositionStage] LLM/parse échec: %s", exc)
            parsed = None
        return self._result_from_parsed(parsed, units)

    async def adecompose(
        self, units: List[Tuple[str, str]], passage_context: str = ""
    ) -> DecompositionResult:
        """Variante async (llm_call awaitable). Utilisée par le pipeline d'extraction."""
        if not units or not self.enabled:
            return DecompositionResult()
        try:
            raw = await self.llm_call(SYSTEM_PROMPT, build_user_prompt(units, passage_context))
            parsed = _parse(raw)
        except Exception as exc:
            logger.warning("[DecompositionStage] LLM/parse échec (async): %s", exc)
            parsed = None
        return self._result_from_parsed(parsed, units)

    def _result_from_parsed(
        self, parsed, units: List[Tuple[str, str]]
    ) -> DecompositionResult:
        result = DecompositionResult()
        valid_ids = {uid for uid, _ in units}
        if not parsed or "claims" not in parsed:
            result.judge_failed = True
            return result  # caller peut retomber sur l'ancien chemin
        for item in parsed.get("claims", []):
            if not isinstance(item, dict):
                continue
            cand = _coerce_claim(item, valid_ids)
            if cand is not None:
                result.claims.append(cand)
        return result
