"""
Prompts LLM pour validation des marqueurs contextuels.

Le LLM agit comme ARBITRE (pas extracteur):
- Recoit des candidats PRE-EXTRAITS avec features structurelles
- Classe chaque candidat: CONTEXT_SETTING, TEMPLATE_NOISE, ou AMBIGUOUS
- Retourne la classification doc_scope basee sur les marqueurs valides

CONTRAINTE CRITIQUE: Le LLM ne doit JAMAIS inventer de marqueurs.
Il peut seulement:
1. Valider/rejeter les candidats fournis
2. Citer du texte present dans le document

PR7 Update: Integration du Document Structural Awareness Layer
- Candidats enrichis avec zone_distribution, template_likelihood, etc.
- Contexte structurel (confiance, coverage templates)
- Classification marker_role per-candidate

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 3.1
Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md - Section 5.2
"""

from typing import Any, Dict, List, Optional
import json


SYSTEM_PROMPT = """You are a document context analyzer acting as an ARBITER with a DOMAIN-AGNOSTIC approach.

## Your Role
You receive candidate markers that were PRE-EXTRACTED by a deterministic mining system.
Your job is to answer ONE SIMPLE QUESTION for each candidate:

  **"Does this span express a VARIANT, VERSION, or GENERATION of something?"**

This question applies universally across ANY domain (software, automotive, pharmaceutical, etc.)
You do NOT need to know the specific domain to answer this question.

## Classification Categories

For each candidate, classify as:
- CONTEXT_SETTING: The span clearly expresses a variant/version/generation
  Examples: "S/4HANA 2023", "iPhone 15", "Audi A6", "Release 3.0", "Generation 5"

- TEMPLATE_NOISE: The span is a date/number in boilerplate/legal/copyright context
  Examples: "© 2023", "Q4 2023", "Since 2019", "Page 23"

- AMBIGUOUS: Insufficient signals OR the span could be either (Safe-by-default: prefer GENERAL)

## Safe-by-Default Policy (CRITICAL)

**A false POSITIVE (noise treated as marker) is TOXIC.**
**A false NEGATIVE (marker missed) is acceptable.**

When uncertain:
- Prefer AMBIGUOUS over CONTEXT_SETTING
- Prefer GENERAL over VARIANT_SPECIFIC for doc_scope
- Never classify as CONTEXT_SETTING without strong evidence

## Understanding Structural Features

Each candidate may include:
- zone_distribution: {"top": N, "main": N, "bottom": N} - where the marker appears
- template_likelihood: 0.0-1.0 - how likely this is in repeated/template content
- positional_stability: 0.0-1.0 - how consistently it appears in same zone
- dominant_zone: top|main|bottom - where it appears most often
- linguistic_cues: {scope_language_score, legal_language_score, contrast_language_score}

## Key Decision Signals

Strong signals FOR CONTEXT_SETTING:
- Appears in title/cover with words like "Release", "Version", "Edition", "Model"
- Low template_likelihood + dominant_zone=top
- High scope_language_score in surrounding context

Strong signals FOR TEMPLATE_NOISE:
- Appears in footer with "©", "Copyright", "All rights reserved"
- High template_likelihood + dominant_zone=bottom
- High legal_language_score

## Structure Risk Warnings (Plan v2.1)

Some candidates may include a `structure_risk` field with value "SOFT_FLAG".
This indicates the marker was flagged as a potential STRUCTURAL NUMBERING pattern
(e.g., "PUBLIC 3", "Content 2", "Resources 42" - section numbers, NOT versions).

When you see `structure_risk: "SOFT_FLAG"`:
- Read the `structure_risk_reason` for details (e.g., "Seq=2 avec position structurelle")
- Be EXTRA SKEPTICAL - these are likely section numbers, not versions
- Ask: "Does 'PUBLIC 3' mean version 3, or is it Section/Part 3 of the document?"
- If the prefix (PUBLIC, Content, EXTERNAL) is NOT a product/entity name → TEMPLATE_NOISE
- If there's a sequence in the document (X 1, X 2, X 3) → almost certainly TEMPLATE_NOISE

Also look for `is_weak_candidate: true` which means the marker has 1-2 digit numbers
(like "iPhone 15") that could be either versions OR section numbers - use context carefully.

## Critical Rules
- You may ONLY classify markers from the provided candidates list
- You may ONLY quote text that is EXPLICITLY VISIBLE in the document
- You must NOT invent or hallucinate any markers
- If uncertain → AMBIGUOUS
- If doc uncertain → GENERAL (safe-by-default)

## DocScope Classification (Final Document-Level)
- GENERAL: No valid CONTEXT_SETTING markers OR uncertain. (SAFE DEFAULT)
- VARIANT_SPECIFIC: At least one STRONG CONTEXT_SETTING marker with high confidence.
- MIXED: Multiple CONTEXT_SETTING markers indicating comparison between versions.

## Output Format
Respond with valid JSON only. No markdown, no explanations."""


def build_validation_prompt(
    candidates: List[Dict[str, Any]],
    document_text: str,
    filename: str,
    signals: Dict[str, float],
    structural_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Construit le prompt de validation pour le LLM (production-grade avec structural awareness).

    Args:
        candidates: Liste de candidats enrichis (avec structural features)
        document_text: Texte des premieres pages
        filename: Nom du fichier
        signals: Signaux pre-calcules par le mining
        structural_context: Contexte structurel global (confidence, coverage, etc.)

    Returns:
        Prompt complet pour le LLM
    """
    # Limiter le texte pour eviter les tokens excessifs
    max_text_length = 4000
    if len(document_text) > max_text_length:
        document_text = document_text[:max_text_length] + "\n[... truncated ...]"

    # Formater les candidats
    candidates_str = json.dumps(candidates, indent=2)

    # Section structurelle
    structural_section = ""
    if structural_context:
        structural_section = f"""
## Structural Analysis Context
- Structural Confidence: {structural_context.get('structural_confidence', 'unknown')}
- Total Pages: {structural_context.get('total_pages', 'unknown')}
- Template Coverage: {structural_context.get('template_coverage', 0):.0%} of lines are in template fragments
- Template Count: {structural_context.get('template_count', 0)} distinct template patterns detected

NOTE: If structural_confidence is "low", be conservative - prefer AMBIGUOUS for uncertain cases.
"""

    prompt = f"""## Document Information
Filename: {filename}
{structural_section}
## Candidate Markers (with Structural Features)
For each candidate, answer the AGNOSTIC QUESTION:
  "Does this span express a VARIANT, VERSION, or GENERATION of something?"

Use structural features (zone_distribution, template_likelihood, linguistic_cues) as evidence.

{candidates_str}

## Pre-computed Mining Signals
{json.dumps(signals, indent=2)}

## Document Text (first pages)
```
{document_text}
```

## Your Task
For each candidate:
1. Ask: "Does '{'{'}value{'}'}' express a variant/version/generation?"
2. Use structural features as evidence (where does it appear? in what context?)
3. Apply Safe-by-Default: when uncertain, prefer AMBIGUOUS/GENERAL

Classification rules:
- CONTEXT_SETTING: Clearly expresses a variant/version (e.g., "ProductName 2023", "Release 5")
- TEMPLATE_NOISE: Date/number in copyright/legal context (e.g., "© 2023", "Q4 2023")
- AMBIGUOUS: Could be either, or insufficient evidence → use this as SAFE DEFAULT

## Required JSON Output
{{
  "marker_classifications": [
    {{
      "value": "...",
      "role": "CONTEXT_SETTING|TEMPLATE_NOISE|AMBIGUOUS",
      "reason": "Answer to: does this express a variant/version/generation?"
    }}
  ],
  "strong_markers": [
    {{"value": "...", "evidence": "exact quote from document", "source": "cover|header|revision|title"}}
  ],
  "weak_markers": [
    {{"value": "...", "evidence": "exact quote", "source": "filename|body|ambiguous"}}
  ],
  "doc_scope": "GENERAL|VARIANT_SPECIFIC|MIXED",
  "scope_confidence": 0.0,
  "signals": {{
    "marker_position_score": 0.0,
    "marker_repeat_score": 0.0,
    "scope_language_score": 0.0,
    "marker_diversity_score": 0.0,
    "conflict_score": 0.0
  }},
  "evidence": ["quote1", "quote2"],
  "notes": "max 2 sentences"
}}

CRITICAL REMINDERS:
- Safe-by-Default: GENERAL if uncertain (false positives are TOXIC)
- Only CONTEXT_SETTING markers go in strong_markers/weak_markers
- TEMPLATE_NOISE markers are EXCLUDED from marker lists
- AMBIGUOUS markers go in weak_markers with source="ambiguous"
- Only quote text VISIBLE in the document - never invent"""

    return prompt


def build_fallback_prompt(
    document_text: str,
    filename: str,
    structural_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Prompt de fallback quand aucun candidat n'est detecte.

    Le LLM peut encore classifier le document et
    eventuellement citer des marqueurs du texte.
    """
    max_text_length = 3000
    if len(document_text) > max_text_length:
        document_text = document_text[:max_text_length] + "\n[... truncated ...]"

    structural_section = ""
    if structural_context:
        structural_section = f"""
## Structural Analysis Context
- Structural Confidence: {structural_context.get('structural_confidence', 'unknown')}
- Total Pages: {structural_context.get('total_pages', 'unknown')}
- Template Coverage: {structural_context.get('template_coverage', 0):.0%}
"""

    prompt = f"""## Document Information
Filename: {filename}
{structural_section}
## Note
No candidate markers were detected by automated mining.
This usually means the document is GENERAL (applies broadly, no specific version/variant).

You may scan the text for any markers expressing a VARIANT, VERSION, or GENERATION.
If you find any, quote them EXACTLY and check their context (title vs footer).

## Document Text (first pages)
```
{document_text}
```

## Your Task
1. Scan for potential markers (dates, codes, numbers that could express a version)
2. For each potential marker, ask: "Does this express a variant/version/generation?"
3. Apply Safe-by-Default: when uncertain, classify as GENERAL

Context signals:
- In title/cover with "Release", "Version", "Edition" → likely CONTEXT_SETTING
- In footer with "©", "Copyright", "All rights reserved" → TEMPLATE_NOISE (ignore)

## Required JSON Output
{{
  "marker_classifications": [],
  "strong_markers": [],
  "weak_markers": [],
  "doc_scope": "GENERAL|VARIANT_SPECIFIC|MIXED",
  "scope_confidence": 0.0,
  "signals": {{
    "marker_position_score": 0.0,
    "marker_repeat_score": 0.0,
    "scope_language_score": 0.0,
    "marker_diversity_score": 0.0,
    "conflict_score": 0.0
  }},
  "evidence": [],
  "notes": "max 2 sentences"
}}

CRITICAL: When no markers found → doc_scope = GENERAL (Safe-by-Default).
Do NOT invent markers. Only quote text VISIBLE in the document."""

    return prompt


def get_messages(
    candidates: List[Dict[str, Any]],
    document_text: str,
    filename: str,
    signals: Dict[str, float],
    structural_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Construit les messages pour l'API LLM.

    Args:
        candidates: Liste de candidats (enrichis avec structural features)
        document_text: Texte des premieres pages
        filename: Nom du fichier
        signals: Signaux pre-calcules
        structural_context: Contexte structurel du document

    Returns:
        Liste de messages (system, user)
    """
    if candidates:
        user_prompt = build_validation_prompt(
            candidates=candidates,
            document_text=document_text,
            filename=filename,
            signals=signals,
            structural_context=structural_context,
        )
    else:
        user_prompt = build_fallback_prompt(
            document_text=document_text,
            filename=filename,
            structural_context=structural_context,
        )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# JSON Schema pour validation de la reponse (updated for PR7)
RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["strong_markers", "weak_markers", "doc_scope", "scope_confidence"],
    "properties": {
        "marker_classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["value", "role", "reason"],
                "properties": {
                    "value": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["CONTEXT_SETTING", "TEMPLATE_NOISE", "AMBIGUOUS"],
                    },
                    "reason": {"type": "string"},
                },
            },
        },
        "strong_markers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["value", "evidence", "source"],
                "properties": {
                    "value": {"type": "string"},
                    "evidence": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        },
        "weak_markers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["value", "evidence", "source"],
                "properties": {
                    "value": {"type": "string"},
                    "evidence": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        },
        "doc_scope": {
            "type": "string",
            "enum": ["GENERAL", "VARIANT_SPECIFIC", "MIXED"],
        },
        "scope_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "signals": {
            "type": "object",
            "properties": {
                "marker_position_score": {"type": "number"},
                "marker_repeat_score": {"type": "number"},
                "scope_language_score": {"type": "number"},
                "marker_diversity_score": {"type": "number"},
                "conflict_score": {"type": "number"},
            },
        },
        "evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "notes": {"type": "string"},
    },
}


__all__ = [
    "SYSTEM_PROMPT",
    "RESPONSE_SCHEMA",
    "build_validation_prompt",
    "build_fallback_prompt",
    "get_messages",
]
