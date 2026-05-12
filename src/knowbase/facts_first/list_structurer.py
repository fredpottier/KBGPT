"""
OSMOSIS V4 — ListStructurer (composant [C], CH-41.3, Tranche 1 list).

Transforme un EvidenceBundle en `facts_first_v1` JSON conforme au schéma
`schemas/facts_first/facts_first_v1_list.json`. Le LLM extrait des items
avec source verbatim quote (D-FF1) — il NE génère AUCUN item depuis les
chunks bruts sans citer la quote source.

Pipeline interne :
  1. Reçoit EvidenceBundle (claims pré-collectés).
  2. Construit un prompt "extractive" avec le pool d'evidences.
  3. Appel LLM en mode json_object → liste d'items {item_id, label, source, confidence}.
  4. Validation déterministe + dedup + annotation enumeration_quality.
  5. Return un `facts_first_v1` strict (validé en aval par Channel 1 Verifier).

Charte D-FF1 : every item.label MUST cite a verbatim source quote drawn from
the provided pool. Si le LLM hallucine un item sans source dans le pool, le
Verifier le rejette ; on ne tente PAS de le réparer ici.
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
DEFAULT_MAX_ITEMS = 30      # cap dur pour éviter explosion LLM
DEFAULT_TOP_EVIDENCE = 25   # nombre max de claims passés au LLM
MIN_LABEL_CHARS = 1
MIN_QUOTE_CHARS = 10        # cohérent avec common.json $defs.Source.quote.minLength

# Levier 4 — override modèle Structurer (Llama-3.3-70B-Turbo bake-off, etc.)
STRUCTURER_MODEL_OVERRIDE = os.getenv("FACTS_FIRST_STRUCTURER_MODEL", "")


SYSTEM_PROMPT = """You are a list-extraction component for a multi-domain Q&A system. You extract the items the user asked about, strictly grounded in the provided evidence pool.

Your output is JSON ONLY (no prose, no markdown), with this exact schema:
{
  "list_subject": "<2-8 word phrase describing what is being listed>",
  "list_scope": {
    "scope_description": "<one short sentence of scope, e.g. 'within Annex I of Regulation 2021/821'>",
    "doc_id": "<doc_id if scope is a single doc, else null>",
    "section_id": "<section/annex id if applicable, else null>",
    "confidence": <float 0-1>
  },
  "items": [
    {
      "item_id": "I1",   // I1, I2, I3, ... unique sequential
      "label": "<verbatim label as it appears in the evidence>",
      "normalized_label": "<lowercase, no accents, dedup key — or null>",
      "item_type": "<one of: category, regulation, entity, concept, value, rule, exemption, unknown>",
      "source": {
        "doc_id": "<doc_id from evidence>",
        "claim_id": "<claim_id from evidence or null>",
        "chunk_id": "<chunk_id from evidence or null>",
        "page_no": <integer or null>,
        "section_id": null,
        "quote": "<EXACT verbatim sentence from the evidence supporting this item, ≥ 10 chars>"
      },
      "confidence": <float 0-1>
    }
  ],
  "enumeration_quality": {
    "expected_exhaustive": <true if the question expects an exhaustive list, else false>,
    "coverage_state": "<complete | partial | unknown>",
    "evidence_count": <integer = number of evidence items you examined>,
    "deduped_count": <integer = items.length>,
    "deduplication_notes": "<one short sentence if you merged duplicates, else null>"
  }
}

EXTRACTION RULES (mandatory, no exception):
1. Each item MUST be supported by a verbatim quote from the EVIDENCE POOL provided in the user message. Do not invent items.
2. Each item.source.quote MUST be a substring or near-paraphrase actually present in one of the evidence quotes. Length ≥ 10 chars.
3. If you cannot find ≥ 1 item supported by evidence → return items=[] and coverage_state="unknown".
4. Deduplicate items with the same normalized_label.
5. coverage_state:
   - "complete" only if you are confident the evidence pool exhaustively covers the requested list.
   - "partial" if you found some items but suspect more exist outside the pool.
   - "unknown" if you cannot tell.
6. Use item_type from the enum above. If none fits, use "unknown".

Return only the JSON object, no markdown fences."""


@dataclass
class StructurerResult:
    """Résultat de ListStructurer (avant Verifier)."""
    facts_first_json: dict        # le JSON conforme facts_first_v1 (à valider par Verifier)
    raw_llm_output: str = ""
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    parse_error: Optional[str] = None
    rejected_items: list[dict] = field(default_factory=list)  # items rejetés à la validation déterministe


class ListStructurer:
    """Extracteur d'items list grounded dans un EvidenceBundle."""

    def __init__(
        self,
        llm: Optional[RuntimeLLMClient] = None,
        max_items: int = DEFAULT_MAX_ITEMS,
        top_evidence: int = DEFAULT_TOP_EVIDENCE,
        temperature: float = 0.1,
        max_tokens: int = 2000,  # CH-46 L6 : 3000→2000 (sortie observée < 1500 tokens)
        timeout: float = 120.0,
    ) -> None:
        self.llm = llm or get_runtime_llm_client()
        self.max_items = max_items
        self.top_evidence = top_evidence
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def structure(
        self,
        question: str,
        evidence: EvidenceBundle,
        language: str = "en",
        domain_pack: Optional[str] = None,
        tenant_id: str = "default",
        feedback_for_retry: Optional[str] = None,
    ) -> StructurerResult:
        """Construit le facts_first_v1 JSON depuis l'evidence.

        Args:
            question: question utilisateur
            evidence: bundle pré-collecté (claims atomiques + chunks)
            language: ISO 639-1 langue de la réponse cible
            domain_pack: identifiant Domain Pack actif (optional)
            tenant_id: tenant
            feedback_for_retry: retour du verifier sur la précédente tentative
                (passé par SelfCorrector AlignRAG pattern). Si non-None, ajouté
                au user_prompt pour guider la 2e tentative.
        """
        t0 = time.time()

        # 1. Cas dégénéré : 0 evidence → unanswerable directement
        if not evidence.claims:
            return self._make_empty_result(
                question=question,
                evidence=evidence,
                language=language,
                domain_pack=domain_pack,
                tenant_id=tenant_id,
                reason="no_evidence",
                t0=t0,
            )

        # 2. Préparation du pool d'evidences (top-N par score)
        ev_pool = sorted(evidence.claims, key=lambda c: c.score, reverse=True)[: self.top_evidence]
        evidence_block = self._format_evidence_pool(ev_pool)

        # 3. Construction du prompt (avec feedback retry optionnel)
        feedback_section = ""
        if feedback_for_retry:
            feedback_section = (
                f"\n\nPREVIOUS ATTEMPT FEEDBACK (from verifier — fix these issues):\n"
                f"{feedback_for_retry.strip()[:600]}\n"
            )
        user_prompt = (
            f"QUESTION (language={language}): {question.strip()}\n\n"
            f"EVIDENCE POOL ({len(ev_pool)} candidates, ranked by retrieval score):\n"
            f"{evidence_block}{feedback_section}\n\n"
            f"Extract the items strictly grounded in this evidence. Output JSON only."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 4. Appel LLM
        try:
            kwargs = {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "json_mode": True,
                "timeout": self.timeout,
            }
            if STRUCTURER_MODEL_OVERRIDE:
                kwargs["model_override"] = STRUCTURER_MODEL_OVERRIDE
            meta = self.llm.chat_completion_with_meta(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ListStructurer LLM call failed: %s", exc)
            res = self._make_empty_result(
                question=question, evidence=evidence, language=language,
                domain_pack=domain_pack, tenant_id=tenant_id,
                reason=f"llm_error: {exc.__class__.__name__}", t0=t0,
            )
            res.parse_error = str(exc)
            return res

        raw = (meta.get("content") or "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            res = self._make_empty_result(
                question=question, evidence=evidence, language=language,
                domain_pack=domain_pack, tenant_id=tenant_id,
                reason="json_parse_error", t0=t0,
            )
            res.parse_error = f"json_parse: {exc}"
            res.raw_llm_output = raw[:600]
            return res

        # 5. Validation déterministe (filtre items hallucinés sans evidence support)
        validated_items, rejected = self._validate_items(parsed.get("items", []), ev_pool)

        # 6. Construction facts_first_v1 conforme
        ff = {
            "schema_version": SCHEMA_VERSION,
            "primary_type": "list",
            "secondary_type": None,
            "answerability": self._derive_answerability(validated_items, parsed),
            "coverage_state": self._derive_coverage_state(parsed, validated_items),
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": f"{meta.get('model') or 'unknown'}@{meta.get('provider') or 'unknown'}",
            "tenant_id": tenant_id,
            "domain_pack": domain_pack,
            "list_specific": {
                "list_subject": str(parsed.get("list_subject") or "")[:200] or "items",
                "list_scope": parsed.get("list_scope") or None,
                "items": validated_items,
                "enumeration_quality": {
                    "expected_exhaustive": bool(
                        (parsed.get("enumeration_quality") or {}).get("expected_exhaustive", False)
                    ),
                    "coverage_state": self._derive_coverage_state(parsed, validated_items),
                    "evidence_count": len(ev_pool),
                    "deduped_count": len(validated_items),
                    "deduplication_notes": (parsed.get("enumeration_quality") or {}).get(
                        "deduplication_notes"
                    ),
                },
            },
            "diagnostic": {
                "latency_ms": int((time.time() - t0) * 1000),
                "evidence_count": len(ev_pool),
                "rejected_items_count": len(rejected),
            },
        }

        return StructurerResult(
            facts_first_json=ff,
            raw_llm_output=raw[:600],
            latency_ms=int((time.time() - t0) * 1000),
            model=meta.get("model", ""),
            provider=meta.get("provider", ""),
            parse_error=None,
            rejected_items=rejected,
        )

    # ------------------------------------------------------------------ helpers

    def _format_evidence_pool(self, ev_pool) -> str:
        """Format compact 'EVx | doc=X | claim=Y | quote: <verbatim>'."""
        lines = []
        for i, c in enumerate(ev_pool, 1):
            cid = c.claim_id or c.chunk_id or "?"
            quote = (c.quote or "").replace("\n", " ").strip()[:400]
            lines.append(f"EV{i} | doc={c.doc_id} | claim={cid} | quote: {quote}")
        return "\n".join(lines)

    def _validate_items(self, raw_items: list, ev_pool) -> tuple[list[dict], list[dict]]:
        """Garde uniquement les items dont source.quote est ancrée dans ev_pool.

        Règle anti-hallucination minimale :
          - quote ≥ MIN_QUOTE_CHARS
          - quote présente comme substring (case-insensitive, espaces normalisés) dans
            au moins une quote du pool, OU le doc_id existe dans le pool ET un overlap
            de tokens significatif (≥ 50% des mots non-stopwords de la quote présents
            dans une quote du pool).

        Cette règle est déterministe — pas de LLM judge ici.
        """
        valid: list[dict] = []
        rejected: list[dict] = []
        pool_quotes_norm = [(c, " ".join((c.quote or "").lower().split())) for c in ev_pool]

        seen_norm_labels: set[str] = set()
        for idx, raw in enumerate(raw_items[: self.max_items], start=1):
            if not isinstance(raw, dict):
                rejected.append({"reason": "not_object", "raw": str(raw)[:200]})
                continue
            label = str(raw.get("label") or "").strip()
            if len(label) < MIN_LABEL_CHARS:
                rejected.append({"reason": "label_too_short", "raw": raw})
                continue
            src = raw.get("source") or {}
            quote = str(src.get("quote") or "").strip()
            if len(quote) < MIN_QUOTE_CHARS:
                rejected.append({"reason": "quote_too_short", "label": label})
                continue
            if not self._quote_grounded(quote, pool_quotes_norm):
                rejected.append({"reason": "quote_not_grounded", "label": label, "quote": quote[:200]})
                continue

            normalized = (raw.get("normalized_label") or label).strip().lower()
            if normalized in seen_norm_labels:
                rejected.append({"reason": "duplicate", "label": label})
                continue
            seen_norm_labels.add(normalized)

            # Validation item_type : core minimal universel ; si Domain Pack inconnu, garde tel quel
            item_type = str(raw.get("item_type") or "unknown").strip()
            if not item_type:
                item_type = "unknown"

            confidence_raw = raw.get("confidence")
            try:
                confidence = max(0.0, min(1.0, float(confidence_raw)))
            except (TypeError, ValueError):
                confidence = 0.5

            valid.append({
                "item_id": f"I{len(valid) + 1}",
                "label": label[:500],
                "normalized_label": normalized[:200],
                "item_type": item_type,
                "attributes": raw.get("attributes") or [],
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
        """True si la quote item est ancrée dans le pool (substring OR token overlap ≥ 50%)."""
        q_norm = " ".join(quote.lower().split())
        if len(q_norm) < MIN_QUOTE_CHARS:
            return False
        # Substring direct (case-insensitive, espaces normalisés)
        for _, pool_q in pool_quotes_norm:
            if q_norm in pool_q or pool_q in q_norm:
                return True
        # Fallback : overlap de tokens significatifs (≥ 50% des mots de l'item dans une quote pool)
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

    def _derive_answerability(self, validated_items: list[dict], parsed: dict) -> str:
        if not validated_items:
            return "unanswerable"
        cs = ((parsed.get("enumeration_quality") or {}).get("coverage_state") or "").lower()
        if cs == "partial":
            return "partial"
        return "answerable"

    def _derive_coverage_state(self, parsed: dict, validated_items: list[dict]) -> str:
        cs = ((parsed.get("enumeration_quality") or {}).get("coverage_state") or "").lower()
        if not validated_items:
            return "unknown"
        if cs in ("complete", "partial", "unknown"):
            return cs
        return "partial"  # safe default

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
            "primary_type": "list",
            "secondary_type": None,
            "answerability": "unanswerable",
            "coverage_state": "unknown",
            "language": language,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extraction_model": "none@none",
            "tenant_id": tenant_id,
            "domain_pack": domain_pack,
            "list_specific": {
                "list_subject": "items",
                "list_scope": None,
                "items": [],
                "enumeration_quality": {
                    "expected_exhaustive": False,
                    "coverage_state": "unknown",
                    "evidence_count": len(evidence.claims),
                    "deduped_count": 0,
                    "deduplication_notes": None,
                },
            },
            "diagnostic": {
                "latency_ms": int((time.time() - t0) * 1000),
                "evidence_count": len(evidence.claims),
                "reason": reason,
            },
        }
        return StructurerResult(
            facts_first_json=ff,
            raw_llm_output="",
            latency_ms=int((time.time() - t0) * 1000),
        )


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

_default_structurer: Optional[ListStructurer] = None


def get_list_structurer() -> ListStructurer:
    global _default_structurer
    if _default_structurer is None:
        _default_structurer = ListStructurer()
    return _default_structurer


def reset_list_structurer() -> None:
    global _default_structurer
    _default_structurer = None
