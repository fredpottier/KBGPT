"""V6-J2 — Extracteur Reference typée (LLM dédié).

Calque architectural de `procedure_extractor.py` (V6-J1) : appel LLM
focalisé sur l'archétype `Reference` du schéma V6 universel
(runtime_v6.schemas.Reference).

Une Reference est un POINTEUR du texte vers une autre information :
- internal_section : référence vers une autre section du même doc
- external_document : référence vers un autre document nommé
- standard : ref vers norme/standard (ISO, IEC, RFC, ...)
- regulation : ref vers texte réglementaire (GDPR, CS-25, ...)
- url : URL externe
- other : fallback

Charte respectée :
- Prompt universel (aucun exemple corpus-spécifique)
- Open-source serverless (DeepInfra DS-V3.1, fallback Together si présent)
- Output Pydantic strict, verbatim grounded
- Évidence section_id propagée automatiquement

`resolved_target` est laissé à None lors de l'extraction : la résolution
effective (lookup vers la cible) est un post-traitement séparé (non livré
dans V6-J2).
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

from knowbase.runtime_v6.schemas import Reference

logger = logging.getLogger(__name__)


# ─── LLM endpoints (priorité Together → DeepInfra, comme V6-J1) ───────────────

_TOGETHER_URL = "https://api.together.xyz/v1/chat/completions"
_DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"

# Modèle par défaut : DS-V3.1 (plafond mesuré au bake-off 2026-05-15).
_DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"


# ─── Prompt Reference-only ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert document analyst tasked with extracting STRUCTURED
REFERENCES from a single document section.

A REFERENCE is any explicit pointer in the text toward another piece of
information. References appear in every kind of structured document
(technical, legal, medical, operational, ...).

You classify each reference's target into ONE of these kinds :
- "internal_section" : pointer to another section of the SAME document
                      (e.g. "see Section 3.2", "refer to chapter 4",
                      "as described in §5.1.2")
- "external_document" : pointer to another NAMED document
                      (e.g. "see SAP Note 1234567", "refer to Operations
                       Guide", "as in the User Manual")
- "standard" : pointer to a published standard / specification
              (e.g. "ISO 27001", "IEEE 802.11", "RFC 5424")
- "regulation" : pointer to a legal / regulatory text
              (e.g. "GDPR Article 32", "HIPAA §164.502", "CS-25 §25.105")
- "url" : URL reference (full or partial)
- "other" : fallback when none of the above clearly fits

For each reference you identify, extract :
- reference_text : the exact text of the reference as it appears in the
                   section (verbatim, including any number/code)
- target_kind : one of the kinds above

RULES :
- Extract ONLY references that point to something IDENTIFIABLE outside
  of the current sentence. Skip generic pronouns like "above", "below",
  "this" unless they explicitly name a target.
- Stay strictly grounded in the provided text. Do NOT invent references
  and do NOT extract the same reference twice.
- Keep `reference_text` short (the pointer itself, not the surrounding
  sentence). Trim leading "see ", "refer to ", "cf. " — they are noise.
- If a reference is repeated identically in the section, output it once.
- If no reference is present, return an empty list.
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

Required JSON shape :

{{
  "references": [
    {{
      "reference_text": "<short verbatim pointer>",
      "target_kind": "<one of: internal_section|external_document|standard|regulation|url|other>"
    }}
  ]
}}

Do NOT include `evidence_section_id` or `resolved_target` — they will be
injected automatically.
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _strip_to_json(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    m = _JSON_OBJ_RE.search(t)
    return m.group(0) if m else t


def _endpoint_key(model: str) -> tuple[str, str, str]:
    """Retourne (url, api_key, provider). Priorité Together → DeepInfra."""
    together_key = os.getenv("TOGETHER_API_KEY", "").strip()
    if together_key:
        return _TOGETHER_URL, together_key, "together"
    deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not deepinfra_key:
        raise RuntimeError(
            "V6-J2: ni TOGETHER_API_KEY ni DEEPINFRA_API_KEY défini — "
            "impossible d'extraire des references (charte open-source serverless)."
        )
    return _DEEPINFRA_URL, deepinfra_key, "deepinfra"


# ─── Extracteur ───────────────────────────────────────────────────────────────


class ReferenceExtractor:
    """Extracteur LLM dédié aux Reference typées."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        timeout_s: int = 120,
        max_retries: int = 1,
        min_text_chars: int = 4,
    ):
        self.model = model or os.getenv("V6_EXTRACT_MODEL", _DEFAULT_MODEL)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.min_text_chars = min_text_chars

        self.stats = {
            "calls": 0,
            "llm_errors": 0,
            "parse_errors": 0,
            "validation_errors": 0,
            "references_extracted": 0,
            "references_filtered_short": 0,
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
    ) -> list[Reference]:
        """Extrait toutes les Reference d'une section donnée."""
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
                    "[V6-J2] LLM call failed (attempt %d/%d) section=%s: %s",
                    attempt + 1, self.max_retries + 1, section_id, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        self.stats["llm_errors"] += 1
        return {"error": f"{type(last_exc).__name__}: {last_exc}"}

    def _parse_and_filter(
        self, content: str, section_id: str
    ) -> list[Reference]:
        cleaned = _strip_to_json(content)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                "[V6-J2] JSON decode failed section=%s: %s (raw_len=%d)",
                section_id, exc, len(content),
            )
            self.stats["parse_errors"] += 1
            return []

        raw_refs = (
            data.get("references") if isinstance(data, dict) else None
        ) or []
        if not isinstance(raw_refs, list):
            return []

        # Dédup intra-section : same reference_text + target_kind = un seul output
        seen: set[tuple[str, str]] = set()
        out: list[Reference] = []
        for idx, item in enumerate(raw_refs):
            if not isinstance(item, dict):
                continue

            ref_text = (item.get("reference_text") or "").strip()
            if len(ref_text) < self.min_text_chars:
                self.stats["references_filtered_short"] += 1
                continue

            target_kind = (item.get("target_kind") or "other").strip().lower()
            # Normalize unknown kinds → "other"
            VALID_KINDS = {
                "internal_section", "external_document", "standard",
                "regulation", "url", "other",
            }
            if target_kind not in VALID_KINDS:
                target_kind = "other"

            key = (ref_text.lower(), target_kind)
            if key in seen:
                continue
            seen.add(key)

            item_norm = {
                "reference_text": ref_text,
                "target_kind": target_kind,
                "resolved_target": None,
                "evidence_section_id": section_id,
            }

            try:
                ref = Reference(**item_norm)
            except ValidationError as exc:
                logger.warning(
                    "[V6-J2] Reference validation failed (section=%s, idx=%d): %s",
                    section_id, idx, exc,
                )
                self.stats["validation_errors"] += 1
                continue

            out.append(ref)
            self.stats["references_extracted"] += 1

        return out


# ─── Convenience batch helper ─────────────────────────────────────────────────


def extract_references_for_doc(
    doc_id: str,
    sections: list[dict],
    extractor: Optional[ReferenceExtractor] = None,
    section_min_chars: int = 200,
    progress_cb=None,
) -> tuple[list[tuple[str, Reference]], dict]:
    """Boucle d'extraction Reference pour toutes les sections d'un doc.

    Args:
        doc_id : identifiant du document
        sections : list[{"section_id", "title", "text"}]
        extractor : optionnel
        section_min_chars : skip les sections plus courtes
        progress_cb : optionnel, callable(i, total, section_id, n_extracted)

    Returns:
        (results, stats) :
            results = list[(section_id, Reference)] aplati
            stats = dict des stats accumulées
    """
    extr = extractor or ReferenceExtractor()
    results: list[tuple[str, Reference]] = []
    total = len(sections)
    for i, sec in enumerate(sections):
        section_id = sec.get("section_id") or sec.get("id") or ""
        section_title = sec.get("title") or sec.get("section_title") or ""
        section_text = sec.get("text") or sec.get("section_text") or ""
        if not section_id or len(section_text) < section_min_chars:
            if progress_cb:
                progress_cb(i + 1, total, section_id, 0)
            continue
        refs = extr.extract_for_section(
            doc_id=doc_id,
            section_id=section_id,
            section_title=section_title,
            section_text=section_text,
        )
        for r in refs:
            results.append((section_id, r))
        if progress_cb:
            progress_cb(i + 1, total, section_id, len(refs))
    return results, dict(extr.stats)
