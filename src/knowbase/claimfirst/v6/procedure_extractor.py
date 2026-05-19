"""V6-J1 — Extracteur Procedure multi-step (LLM dédié).

Appelle DeepSeek-V3.1 (DeepInfra) avec un prompt focalisé sur l'archétype
PROCEDURE uniquement. La sortie est validée via le schéma Pydantic
`runtime_v6.schemas.Procedure`.

Charte respectée :
- Prompt universel (aucun exemple corpus-spécifique)
- Open-source serverless (DeepInfra ou Together AI, jamais Sonnet/GPT-4o)
- Output Pydantic strict, verbatim grounded
- Évidence section_id propagée automatiquement

Stratégie : ce module est ADDITIF — il ne touche ni au prompt ClaimFirst
(claim_extractor) ni au persister Claim. Il consomme les sections déjà
structurées (V5 structure_loader) et produit des nodes Neo4j séparés
`:Procedure` / `:ProcedureStep` reliés à `:V5Section` par evidence.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import requests
from pydantic import ValidationError

from knowbase.runtime_v6.schemas import Procedure, ProcedureStep

logger = logging.getLogger(__name__)


# ─── LLM endpoints (priorité Together → DeepInfra, comme POC V6-P1.3) ─────────

_TOGETHER_URL = "https://api.together.xyz/v1/chat/completions"
_DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"

# Modèle par défaut : DS-V3.1 (plafond mesuré au bake-off 2026-05-15).
# Override possible via env V6_EXTRACT_MODEL pour le double-bench (Qwen-72B).
_DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"


# ─── Prompt Procedure-only ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert document analyst tasked with extracting STRUCTURED
PROCEDURES from a single document section.

A PROCEDURE is any sequence of ORDERED STEPS that describes HOW to
accomplish a defined goal. Procedures appear in every kind of
structured document (technical, legal, medical, operational, ...).

For each procedure you identify, extract :
- name : a short noun phrase that names the procedure
- goal : what the procedure achieves (one short sentence)
- steps : ordered list of action steps
          each step has a step_number (>= 1, contiguous), an `action`
          sentence (imperative), and optional `notes`
- prerequisites : conditions, authorizations, prior procedures that
                  MUST be satisfied BEFORE starting (omit if not stated)

RULES :
- Extract ONLY procedures that have AT LEAST 2 explicit steps. Single
  actions, isolated commands, and one-off mentions are facts, NOT
  procedures — ignore them here.
- Stay strictly grounded in the provided text. Do NOT invent steps
  and do NOT reorder them.
- Use the imperative voice for `action` ("Open X", "Verify Y", "Set Z to ...").
- If the same procedure is described multiple times, output it once.
- If no procedure is present, return an empty list.
- Output STRICT JSON conforming to the shape below. No markdown fences,
  no comments, no preamble.
"""

_USER_TMPL = """\
Document ID: {doc_id}
Section ID: {section_id}
Section title: {section_title}

Section content:
\"\"\"
{section_text}
\"\"\"

Required JSON shape (omit prerequisites if not stated, but keep the key):

{{
  "procedures": [
    {{
      "name": "<short name>",
      "goal": "<what the procedure achieves>",
      "steps": [
        {{"step_number": 1, "action": "<imperative action>", "notes": null}}
      ],
      "prerequisites": []
    }}
  ]
}}

Do NOT include `evidence_section_id` — it will be injected automatically.
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _strip_to_json(text: str) -> str:
    """Strip markdown fences / preamble, return premier objet JSON."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    m = _JSON_OBJ_RE.search(t)
    return m.group(0) if m else t


def _endpoint_key(model: str) -> tuple[str, str, str]:
    """Retourne (url, api_key, provider_name).

    Priorité Together AI → DeepInfra. Si TOGETHER_API_KEY non défini,
    fallback DeepInfra (charte open-source serverless respectée).
    """
    together_key = os.getenv("TOGETHER_API_KEY", "").strip()
    if together_key:
        return _TOGETHER_URL, together_key, "together"
    deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not deepinfra_key:
        raise RuntimeError(
            "V6-J1: ni TOGETHER_API_KEY ni DEEPINFRA_API_KEY défini — impossible "
            "d'extraire des procedures (charte open-source serverless)."
        )
    return _DEEPINFRA_URL, deepinfra_key, "deepinfra"


# ─── Extracteur ───────────────────────────────────────────────────────────────


class ProcedureExtractor:
    """Extracteur LLM dédié aux Procedure multi-step.

    Usage minimal :
        extr = ProcedureExtractor()
        procs = extr.extract_for_section(
            doc_id="014_SAP_S4HANA_...",
            section_id="sec_84170103ffeadf",
            section_title="10.7.4.1.1.1 Component-Specific Monitoring",
            section_text="The Expert cache is initialized by ...",
        )
    """

    def __init__(
        self,
        model: Optional[str] = None,
        min_steps: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 2500,
        timeout_s: int = 120,
        max_retries: int = 1,
    ):
        self.model = model or os.getenv("V6_EXTRACT_MODEL", _DEFAULT_MODEL)
        self.min_steps = min_steps
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries

        # Stats accumulatives (utile pour batch / debug)
        self.stats = {
            "calls": 0,
            "llm_errors": 0,
            "parse_errors": 0,
            "validation_errors": 0,
            "procedures_extracted": 0,
            "procedures_filtered_min_steps": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_total_s": 0.0,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_for_section(
        self,
        doc_id: str,
        section_id: str,
        section_title: Optional[str],
        section_text: str,
    ) -> list[Procedure]:
        """Extrait toutes les Procedure d'une section donnée.

        Returns une liste (possiblement vide) de Procedure validées Pydantic.
        Toute erreur (LLM, parse, validation) est loggée et l'extraction
        retourne [] pour cette section — pas d'exception remontée.
        """
        if not section_text or not section_text.strip():
            return []

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_TMPL.format(
                    doc_id=doc_id,
                    section_id=section_id,
                    section_title=section_title or "(no title)",
                    section_text=section_text,
                ),
            },
        ]

        resp = self._call_llm(messages, section_id=section_id)
        if "error" in resp:
            return []

        return self._parse_and_filter(resp["content"], section_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call_llm(
        self, messages: list[dict], section_id: str
    ) -> dict[str, Any]:
        """Appel LLM avec retry simple, response_format JSON."""
        url, key, provider = _endpoint_key(self.model)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            try:
                r = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout_s
                )
                r.raise_for_status()
                data = r.json()
                latency = time.time() - t0
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {}) or {}
                self.stats["calls"] += 1
                self.stats["tokens_in"] += int(usage.get("prompt_tokens", 0) or 0)
                self.stats["tokens_out"] += int(usage.get("completion_tokens", 0) or 0)
                self.stats["latency_total_s"] += latency
                return {
                    "content": content,
                    "usage": usage,
                    "latency_s": latency,
                    "provider": provider,
                }
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[V6-J1] LLM call failed (attempt %d/%d) section=%s: %s",
                    attempt + 1, self.max_retries + 1, section_id, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        self.stats["llm_errors"] += 1
        return {"error": f"{type(last_exc).__name__}: {last_exc}"}

    def _parse_and_filter(
        self, content: str, section_id: str
    ) -> list[Procedure]:
        """Parse JSON LLM, valide via Pydantic, filtre par min_steps."""
        cleaned = _strip_to_json(content)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[V6-J1] JSON decode failed section=%s: %s (raw_len=%d)",
                section_id, exc, len(content),
            )
            self.stats["parse_errors"] += 1
            return []

        raw_procs = (
            data.get("procedures") if isinstance(data, dict) else None
        ) or []
        if not isinstance(raw_procs, list):
            return []

        out: list[Procedure] = []
        for idx, item in enumerate(raw_procs):
            if not isinstance(item, dict):
                continue

            # Inject evidence_section_id (LLM est instruit de ne pas le produire)
            item["evidence_section_id"] = section_id

            # Normalise steps (step_number contigu >=1, action non vide)
            steps_raw = item.get("steps") or []
            norm_steps: list[dict[str, Any]] = []
            for s_idx, s in enumerate(steps_raw):
                if not isinstance(s, dict):
                    continue
                action = (s.get("action") or "").strip()
                if not action:
                    continue
                sn = s.get("step_number")
                if not isinstance(sn, int) or sn < 1:
                    sn = s_idx + 1
                norm_steps.append({
                    "step_number": sn,
                    "action": action,
                    "notes": (s.get("notes") or None),
                })
            item["steps"] = norm_steps

            # Validate via Pydantic
            try:
                proc = Procedure(**item)
            except ValidationError as exc:
                logger.warning(
                    "[V6-J1] Procedure validation failed (section=%s, idx=%d): %s",
                    section_id, idx, exc,
                )
                self.stats["validation_errors"] += 1
                continue

            if len(proc.steps) < self.min_steps:
                self.stats["procedures_filtered_min_steps"] += 1
                continue

            out.append(proc)
            self.stats["procedures_extracted"] += 1

        return out


# ─── Convenience batch helper ─────────────────────────────────────────────────


def extract_procedures_for_doc(
    doc_id: str,
    sections: list[dict],
    extractor: Optional[ProcedureExtractor] = None,
    section_min_chars: int = 200,
    progress_cb=None,
) -> tuple[list[tuple[str, Procedure]], dict]:
    """Boucle d'extraction Procedure pour toutes les sections d'un doc.

    Args:
        doc_id : identifiant du document
        sections : list[{"section_id": str, "title": str, "text": str}]
        extractor : optionnel, ProcedureExtractor existant (sinon par défaut)
        section_min_chars : skip les sections plus courtes que ça (procedures
                           rares dans les tout petits blocs)
        progress_cb : optionnel, callable(i, total, section_id, n_extracted)

    Returns:
        (results, stats) :
            results = list[(section_id, Procedure)] aplati
            stats = dict des stats accumulées (du ProcedureExtractor)
    """
    extr = extractor or ProcedureExtractor()
    results: list[tuple[str, Procedure]] = []
    total = len(sections)
    for i, sec in enumerate(sections):
        section_id = sec.get("section_id") or sec.get("id") or ""
        section_title = sec.get("title") or sec.get("section_title") or ""
        section_text = sec.get("text") or sec.get("section_text") or ""
        if not section_id or len(section_text) < section_min_chars:
            if progress_cb:
                progress_cb(i + 1, total, section_id, 0)
            continue
        procs = extr.extract_for_section(
            doc_id=doc_id,
            section_id=section_id,
            section_title=section_title,
            section_text=section_text,
        )
        for p in procs:
            results.append((section_id, p))
        if progress_cb:
            progress_cb(i + 1, total, section_id, len(procs))
    return results, dict(extr.stats)
