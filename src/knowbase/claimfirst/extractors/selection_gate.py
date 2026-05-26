"""
selection_gate.py — P1.4b-2 : Stage A de l'extraction (check-worthiness).

Première étape du pipeline multi-étapes (ADR_P1_4_BIS) : AVANT la décomposition en
claims, on filtre les unités d'assertion qui ne valent pas la peine d'être stockées
(boilerplate juridique, méta-document, marketing, énoncés vacants). C'est le levier #3
remonté à l'extraction (validé au smoke utilité : ~5% hard-junk sûr + ~12% vacant flou).

Principes :
- Prompt DOMAIN-AGNOSTIC (critères universels, exemples neutres ; aucune règle SAP).
- « When in doubt, KEEP » (le rappel prime ; on ne jette que le clairement non-pertinent).
- GARDE-FOU : une unité portant un identifiant précis (cf identifier_guard) n'est JAMAIS
  jetée, même si le juge dit DROP (override compté).
- LLM INJECTABLE (`llm_call(system, user) -> str` JSON) → testable + portable
  (vLLM burst Qwen2.5-14B en prod, DeepInfra en dev). Le caller fournit le guided JSON.
- Robustesse : parse tolérant ; toute défaillance → KEEP (sûr, ne perd rien).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from knowbase.claimfirst.quality.identifier_guard import has_specific_identifier

logger = logging.getLogger(__name__)

# JSON schema pour guided decoding (le caller peut le passer au LLM)
SELECTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string", "enum": ["KEEP", "DROP"]},
                    "category": {"type": "string"},
                },
                "required": ["id", "label"],
            },
        }
    },
    "required": ["verdicts"],
}

SYSTEM_PROMPT = """You curate a knowledge base of factual claims extracted from documents \
to answer real user questions via retrieval. For each numbered text unit, decide whether it \
is WORTH STORING as retrievable knowledge.

KEEP if the unit conveys substantive, checkable knowledge: a fact, definition, rule, \
capability, constraint, procedure step, relationship, configuration, or identifier/numeric value.

DROP only if the unit is clearly NOT worth storing:
- legal / liability / warranty / copyright / disclaimer boilerplate;
- document meta-statements (table of contents, "this document describes…", navigation, \
formatting/version notes with no standalone fact);
- generic marketing or filler with no checkable content;
- vacuous statements that assert almost nothing ("X provides many benefits", "this improves \
efficiency"). Only call vacuous when there is essentially NO checkable content — if a specific \
feature/field/object/relationship is named, prefer KEEP;
- pure cross-references ("see the section below").

Be domain-neutral (software, medical, legal, engineering…). WHEN IN DOUBT, KEEP (recall matters).

Return STRICT JSON: {"verdicts":[{"id":"<unit id>","label":"KEEP"|"DROP","category":"<short tag>"}]}.
Include exactly one verdict per unit, using the given ids."""

_EXAMPLES = (
    "Reference examples (neutral, cross-domain):\n"
    "- \"The provider shall not be liable for any damages.\" -> DROP (legal_boilerplate)\n"
    "- \"This guide is organized into five chapters.\" -> DROP (doc_meta)\n"
    "- \"The platform delivers powerful capabilities for success.\" -> DROP (marketing_filler)\n"
    "- \"Water boils at 100 degrees Celsius at sea level.\" -> KEEP (factual)\n"
    "- \"A booster dose is recommended six months after the second injection.\" -> KEEP (rule)\n"
)


@dataclass
class UnitVerdict:
    unit_id: str
    text: str
    label: str          # KEEP | DROP (final, après garde-fou)
    judge_label: str    # ce que le juge a dit (avant garde-fou)
    category: str = ""
    guard_override: bool = False


@dataclass
class SelectionResult:
    kept_ids: List[str] = field(default_factory=list)
    dropped: List[UnitVerdict] = field(default_factory=list)
    verdicts: List[UnitVerdict] = field(default_factory=list)
    guard_overrides: int = 0
    judge_failed: bool = False

    @property
    def n_kept(self) -> int:
        return len(self.kept_ids)

    @property
    def n_dropped(self) -> int:
        return len(self.dropped)


def build_user_prompt(units: List[Tuple[str, str]]) -> str:
    lines = [_EXAMPLES, "\nClassify these units:"]
    for uid, text in units:
        lines.append(f"[{uid}] {text}")
    lines.append("\nJSON:")
    return "\n".join(lines)


def _parse_verdicts(raw: str) -> Optional[dict]:
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


class SelectionGate:
    """Gate de sélection check-worthiness (Stage A).

    Args:
        llm_call: callable (system_prompt, user_prompt) -> str (réponse JSON brute).
                  Le caller décide du modèle + du guided decoding (SELECTION_JSON_SCHEMA).
        enabled: si False, tout est KEEP (no-op).
    """

    def __init__(self, llm_call: Callable[[str, str], str], enabled: bool = True):
        self.llm_call = llm_call
        self.enabled = enabled

    def classify(self, units: List[Tuple[str, str]]) -> SelectionResult:
        result = SelectionResult()
        if not units:
            return result
        if not self.enabled:
            result.kept_ids = [uid for uid, _ in units]
            return result

        text_by_id = {uid: txt for uid, txt in units}

        try:
            raw = self.llm_call(SYSTEM_PROMPT, build_user_prompt(units))
            parsed = _parse_verdicts(raw)
        except Exception as exc:
            logger.warning("[SelectionGate] LLM/parse échec: %s — tout KEEP (sûr)", exc)
            parsed = None

        if not parsed or "verdicts" not in parsed:
            # défaillance → tout KEEP (ne jamais perdre par erreur technique)
            result.judge_failed = True
            for uid, txt in units:
                v = UnitVerdict(uid, txt, "KEEP", "JUDGE_FAILED", "judge_failed")
                result.verdicts.append(v)
                result.kept_ids.append(uid)
            return result

        seen = set()
        verdict_by_id = {}
        for item in parsed.get("verdicts", []):
            uid = str(item.get("id", "")).strip()
            if uid in text_by_id:
                verdict_by_id[uid] = item

        for uid, txt in units:
            item = verdict_by_id.get(uid)
            if item is None:
                # unité non jugée → KEEP par défaut (sûr)
                v = UnitVerdict(uid, txt, "KEEP", "MISSING", "not_judged")
                result.verdicts.append(v)
                result.kept_ids.append(uid)
                continue
            judge_label = "DROP" if str(item.get("label", "")).upper() == "DROP" else "KEEP"
            category = str(item.get("category", ""))[:40]
            # GARDE-FOU : ne jamais jeter une unité portant un identifiant précis
            guard_override = judge_label == "DROP" and has_specific_identifier(txt)
            final = "KEEP" if (judge_label == "KEEP" or guard_override) else "DROP"
            v = UnitVerdict(uid, txt, final, judge_label, category, guard_override)
            result.verdicts.append(v)
            if guard_override:
                result.guard_overrides += 1
            if final == "KEEP":
                result.kept_ids.append(uid)
            else:
                result.dropped.append(v)
        return result
