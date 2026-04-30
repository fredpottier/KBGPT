"""
LLM extracteur sémantique pur evidence-locked pour LIFECYCLE_RELATION Doc→Doc.

V2-S1 (version stricte) — VISION_RECENTREE §1bis :
- Aucun regex/keyword (multilingue par construction)
- Output evidence_quote obligatoire (validator post-LLM substring match)
- Pas de score hybride : extraction sémantique unique sur déclaration textuelle
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from knowbase.lifecycle.models import (
    LifecycleDeclarationCandidate,
    LifecycleExtractionResult,
    LifecycleType,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a document analyst extracting **lifecycle declarations** from documents in any language and any domain (regulatory, technical, legal, medical, IT, business, etc.).

A lifecycle declaration is a textual statement in this document where the author EXPLICITLY states that this document has a relationship with another document in terms of succession, evolution, or reaffirmation.

## Three types of relations to look for

### SUPERSEDES
This document repeals, abrogates, or makes the WHOLE OF the cited document obsolete. After this declaration, the cited document is no longer in force as a whole.
Critical scope test: the declaration must concern the cited document AS A WHOLE, not a sub-part of it.
Linguistic markers (illustrative, across languages): "Document X is repealed", "Document X is hereby repealed", "Cette directive abroge la directive Y", "Diese Verordnung ersetzt die Verordnung Y".

### EVOLVES_FROM
This document amends, modifies, extends, revises, or REPLACES A SUB-PART of another document. The cited document remains in force overall — only the listed sub-element changes.
Critical scope test: if the declaration replaces or modifies a NAMED SUB-PART (Annex, Article, Section, Paragraph, Schedule, Appendix, Table) of the cited document, this is EVOLVES_FROM — NOT SUPERSEDES, even if the verb "replaced" is used.
Linguistic markers (illustrative): "Annex I to Document X is replaced by ...", "Article 5 of Directive Y is amended", "Schedule B of Standard Z is updated".

### Disambiguation between SUPERSEDES and EVOLVES_FROM
- "Regulation X is repealed."           → SUPERSEDES (whole doc)
- "Annex I to Regulation X is replaced" → EVOLVES_FROM (sub-part only — Regulation X stays in force)
- "Article 5 of Directive Y is amended" → EVOLVES_FROM (sub-part only)
- "This Regulation supersedes Regulation Y entirely" → SUPERSEDES
- "Schedule B of Standard Z is updated" → EVOLVES_FROM

The presence of a NAMED sub-part identifier (Annex, Article, Section, Schedule, Appendix, Part, Chapter, Title, Paragraph) before the cited document name is the strongest signal that the relation is EVOLVES_FROM, not SUPERSEDES.

### REAFFIRMS
This document explicitly reaffirms, restates, or confirms the rules/principles of another document, typically in a confirming or supplementary capacity.
Examples:
- "This document reaffirms the principles set out in Directive 95/46/EC."
- "Cette note réaffirme les dispositions de la circulaire 2015-12."

## Critical extraction rules

1. **Only extract TEXTUALLY EXPLICIT declarations**. Do NOT infer based on dates, version numbers, topic similarity, or chronology. If the document does not contain a statement of relation, return an empty array.

2. **The `evidence_quote` MUST be the verbatim sentence from the input**, exactly as it appears (preserve casing, punctuation, spacing). The validator will perform a substring match — if your quote does not match the source character-for-character (modulo whitespace), the declaration will be rejected as a hallucination.

3. **The `target_doc_reference` is the verbatim citation as it appears in the text** (e.g., "Regulation (EC) No 428/2009", "Directive 95/46/EC", "CS-25 Amendment 27", "ISO 9001:2015"). Do NOT normalize or paraphrase.

4. **Be conservative on confidence**:
   - 0.95+ : the sentence unambiguously declares the relation type
   - 0.80-0.94 : the relation is clearly stated but the type is slightly ambiguous (could be SUPERSEDES or EVOLVES_FROM)
   - 0.50-0.79 : the relation is implied by the wording but not crystal clear
   - < 0.50 : DO NOT extract — too uncertain

5. **If multiple distinct declarations exist in the input, extract all of them** (one entry per declaration). A document can simultaneously SUPERSEDE one doc and EVOLVE_FROM another.

6. **Return JSON only, no commentary, no markdown fences**:

```
{
  "declarations": [
    {
      "type": "SUPERSEDES",
      "target_doc_reference": "Regulation (EC) No 428/2009",
      "evidence_quote": "This Regulation repeals Regulation (EC) No 428/2009.",
      "confidence": 0.98,
      "reasoning": "Explicit repeal clause in final dispositions."
    }
  ]
}
```

If no declarations are found, return:
```
{"declarations": []}
```
"""


class LifecycleDeclarationExtractor:
    """LLM extracteur evidence-locked pour LIFECYCLE_RELATION Doc→Doc.

    Usage:
        extractor = LifecycleDeclarationExtractor(vllm_url="http://x.y.z.w:8000")
        result = extractor.extract(doc_id="dualuse_reg_2021_821_...", text_input=full_text_window)
        for cand in result.declarations:
            print(cand.type, cand.target_doc_reference, cand.evidence_quote[:80])
    """

    def __init__(
        self,
        vllm_url: str,
        model_id: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
        timeout: float = 60.0,
        temperature: float = 0.1,
        max_tokens: int = 1500,
    ) -> None:
        self.vllm_url = vllm_url.rstrip("/")
        self.model_id = model_id
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def extract(
        self,
        doc_id: str,
        text_input: str,
        domain_pack_hints: Optional[str] = None,
    ) -> LifecycleExtractionResult:
        """Extrait les déclarations Lifecycle d'un texte source.

        Args:
            doc_id: identifiant du DocumentContext source
            text_input: window de full_text à analyser (typiquement preamble + final dispositions)
            domain_pack_hints: prose contextuelle optionnelle du Domain Pack actif
                (ex: "EU regulations typically state repeal clauses in their final articles").
                **Pas de regex, juste du contexte sémantique** (cf. ADR §3.G.4).

        Returns:
            LifecycleExtractionResult avec liste de candidates (à valider ensuite).
        """
        user_prompt = self._build_user_prompt(text_input, domain_pack_hints)
        raw_json = self._call_llm(user_prompt)
        candidates = self._parse_response(raw_json)

        return LifecycleExtractionResult(
            source_doc_id=doc_id,
            declarations=candidates,
            extraction_method="llm_evidence_locked_v2_strict",
            model_id=self.model_id,
            extracted_at=datetime.utcnow().isoformat() + "Z",
        )

    def _build_user_prompt(self, text_input: str, hints: Optional[str]) -> str:
        sections = []
        if hints:
            sections.append(
                "## Domain context (provided by the active Domain Pack — semantic prose, not rules)\n\n"
                + hints
            )
        sections.append(
            "## Document text to analyze\n\nExtract any lifecycle declarations from the following text. "
            "Remember: only extract textually explicit statements. Return JSON.\n\n"
            "---\n"
            f"{text_input}\n"
            "---"
        )
        return "\n\n".join(sections)

    def _call_llm(self, user_prompt: str) -> str:
        endpoint = f"{self.vllm_url}/v1/chat/completions"
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.error("vLLM call failed for lifecycle extraction: %s", exc)
            return '{"declarations": []}'

    def _parse_response(self, raw_json: str) -> list[LifecycleDeclarationCandidate]:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning("Lifecycle extractor returned invalid JSON: %s", exc)
            return []

        candidates: list[LifecycleDeclarationCandidate] = []
        for item in data.get("declarations", []):
            try:
                # Filtre confidence < 0.5 (LLM doit s'abstenir mais sécurité)
                if float(item.get("confidence", 0.0)) < 0.5:
                    continue
                cand = LifecycleDeclarationCandidate(
                    type=LifecycleType(item["type"]),
                    target_doc_reference=item["target_doc_reference"].strip(),
                    evidence_quote=item["evidence_quote"].strip(),
                    confidence=float(item["confidence"]),
                    reasoning=item.get("reasoning"),
                )
                candidates.append(cand)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed candidate: %s (item=%s)", exc, item)
                continue

        return candidates


def select_text_window(full_text: str, head_chars: int = 8000, tail_chars: int = 8000) -> str:
    """[Legacy 1-window] Sélectionne preamble + final dispositions.

    Conservé pour compatibilité tests. Pour les vrais docs préférer select_scan_windows().
    """
    if len(full_text) <= head_chars + tail_chars:
        return full_text
    head = full_text[:head_chars]
    tail = full_text[-tail_chars:]
    return f"{head}\n\n[... omitted middle section ...]\n\n{tail}"


def select_scan_windows(
    full_text: str,
    window_chars: int = 12000,
    overlap_chars: int = 1500,
    max_head_windows: int = 12,
    tail_windows: int = 1,
) -> list[str]:
    """Découpe un full_text en fenêtres glissantes contigües depuis le début + tail.

    Approche structurelle simple, domain-agnostic :
    - Scan contigu depuis offset 0, fenêtres glissantes de `window_chars` avec
      overlap `overlap_chars`, plafonné à `max_head_windows`.
    - Plus `tail_windows` fenêtres en fin de doc (signatures, annexes finales).
    - Pas de découpage par sections/articles/structure (qui dépendrait du domaine).

    Avec window_chars=12000, overlap_chars=1500, max_head_windows=12 :
    couvre 0..(12 × 10500 + 1500) ≈ 0..127K depuis le début. Pour des docs
    plus courts, scan exhaustif jusqu'à la longueur du doc.

    Le rationale : la majorité des déclarations explicites de relation entre
    documents (selon les pratiques observées cross-domain : reg, normes,
    protocoles, RFC, internal policies, etc.) se trouvent dans les premiers
    paragraphes structurels du document (header / scope / introduction /
    final dispositions courts). Les annexes en fin de doc contiennent
    typiquement des données techniques sans déclarations.

    Si le doc est plus long que la couverture max, les zones non scannées
    sont les sections du milieu (typiquement annexes). Si un doc particulier
    a des déclarations non capturées, augmenter max_head_windows.
    """
    n = len(full_text)
    if n == 0:
        return [""]
    if n <= window_chars:
        return [full_text]

    step = max(1, window_chars - overlap_chars)

    head_windows: list[str] = []
    start = 0
    while start < n and len(head_windows) < max_head_windows:
        end = min(start + window_chars, n)
        head_windows.append(full_text[start:end])
        if end == n:
            break
        start += step

    tail_windows_list: list[str] = []
    if tail_windows > 0 and len(head_windows) < (n // step) + 1:
        # Doc dépasse la couverture head : ajouter fenêtres de fin
        tail_start = max(0, n - window_chars * tail_windows + overlap_chars * (tail_windows - 1))
        for i in range(tail_windows):
            ws = tail_start + i * step
            we = min(ws + window_chars, n)
            if ws >= n:
                break
            # Éviter les doublons avec head_windows
            chunk = full_text[ws:we]
            if chunk not in head_windows:
                tail_windows_list.append(chunk)

    return head_windows + tail_windows_list
