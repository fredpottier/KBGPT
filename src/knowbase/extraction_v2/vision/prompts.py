"""
Prompts Vision canoniques pour Extraction V2.

Prompt agnostique avec Domain Context injectable.

Spécification: VISION_PROMPT_CANONICAL.md

Implémentation complète en Phase 4.
"""

from __future__ import annotations
from typing import Optional

from knowbase.extraction_v2.models import VisionDomainContext

# === SYSTEM PROMPT ===

VISION_SYSTEM_PROMPT = """You are a **visual analysis engine** used in an automated document processing pipeline.

Your role is **NOT** to explain, summarize, or interpret content beyond what is explicitly visible.

Your role is to:

* extract **only what is visually explicit** in the image,
* respect a provided **Domain Context** as a *constraint*, not as a source of new information,
* output **ONLY valid JSON**, strictly conforming to the provided schema.

You must avoid:

* hallucinations,
* assumptions,
* domain knowledge not visually supported.

If something is not explicitly visible, **do not infer it**.

## VERY IMPORTANT CONSTRAINTS

You MUST follow all rules below:

1. **No inference without visual evidence**
   * Do NOT use general knowledge or best practices.

2. **No domain expansion**
   * The Domain Context is a constraint, not knowledge to be applied.

3. **Every relation must reference visual evidence**
   * arrow
   * line
   * grouping
   * alignment
   * proximity

4. **Ambiguity must be declared, never resolved implicitly**

5. **If unsure, declare uncertainty**

6. **No prose, no explanation, no commentary**

7. **Output ONLY JSON**

8. **The JSON must strictly conform to the schema**

This output will be ingested into a **Knowledge Graph**.
Accuracy and traceability are more important than completeness."""


# === JSON SCHEMA ===

VISION_JSON_SCHEMA = """{
  "diagram_type": "string",
  "elements": [
    {
      "id": "string",
      "type": "box | label | arrow | group | icon | other",
      "text": "string",
      "confidence": 0.0
    }
  ],
  "relations": [
    {
      "source_id": "string",
      "target_id": "string",
      "relation_type": "contains | flows_to | integrates_with | depends_on | grouped_with | other",
      "evidence": "arrow | line | grouping | alignment | proximity | label_near_line",
      "confidence": 0.0
    }
  ],
  "ambiguities": [
    {
      "term": "string",
      "possible_interpretations": ["string"],
      "reason": "string"
    }
  ],
  "uncertainties": [
    {
      "item": "string",
      "reason": "string"
    }
  ]
}"""


# === USER PROMPT TEMPLATE ===

VISION_USER_PROMPT_TEMPLATE = """You are given:

1. An **image** representing a document page or slide
   (this image may contain diagrams made of boxes, text, arrows, shapes, or embedded pictures)

2. Optional **local text snippets** extracted from the same page or slide
   (titles, labels, captions, surrounding text)

3. A **Domain Context** (injected dynamically by the system)
   → This context constrains interpretation and disambiguation
   → It must NOT be treated as a source of facts

4. A **strict JSON schema** that your output must follow exactly

Your task is to:

* identify **visually explicit structural elements** (boxes, labels, arrows, groups, icons),
* identify **explicit visual relationships** between these elements,
* use the Domain Context **only to disambiguate terms already visible**,
* declare ambiguities and uncertainties explicitly,
* return a JSON object that strictly matches the schema.

## DOMAIN CONTEXT

{domain_context}

## LOCAL TEXT CONTEXT

{local_snippets}

## OUTPUT JSON SCHEMA (STRICT)

```json
{json_schema}
```

## OUTPUT RULES

* `diagram_type` must be a **generic structural classification**, e.g.:
  * `"architecture_diagram"`
  * `"process_workflow"`
  * `"system_landscape"`
  * `"organizational_diagram"`

* `confidence` values must be between `0.0` and `1.0`

* All `id` values must be **unique**

* If no relations are visible, return an empty `relations` array

* If no ambiguities exist, return an empty `ambiguities` array

* If no uncertainties exist, return an empty `uncertainties` array

## FINAL REMINDER

* Do not invent.
* Do not assume.
* Do not generalize.
* Declare uncertainty explicitly.

Only what is **visibly supported** may appear in the output."""


def build_vision_prompt(
    domain_context: Optional[VisionDomainContext] = None,
    local_snippets: str = "",
) -> str:
    """
    Construit le prompt Vision avec injection du Domain Context.

    Args:
        domain_context: Contexte métier (optionnel)
        local_snippets: Texte local de la page (optionnel)

    Returns:
        Prompt complet prêt pour l'API Vision
    """
    # Domain Context section
    if domain_context:
        domain_section = domain_context.to_prompt_section()
    else:
        domain_section = "(No domain context provided - interpret terms generically)"

    # Local snippets section
    if local_snippets:
        snippets_section = local_snippets
    else:
        snippets_section = "(No local text provided)"

    # Build prompt
    prompt = VISION_USER_PROMPT_TEMPLATE.format(
        domain_context=domain_section,
        local_snippets=snippets_section,
        json_schema=VISION_JSON_SCHEMA,
    )

    return prompt


def get_vision_messages(
    domain_context: Optional[VisionDomainContext] = None,
    local_snippets: str = "",
    image_base64: Optional[str] = None,
    image_url: Optional[str] = None,
) -> list:
    """
    Construit les messages pour l'API Vision OpenAI.

    Args:
        domain_context: Contexte métier
        local_snippets: Texte local
        image_base64: Image encodée en base64
        image_url: URL de l'image (alternatif)

    Returns:
        Liste de messages pour l'API Chat Completions

    Raises:
        ValueError: Si ni image_base64 ni image_url n'est fourni
    """
    if not image_base64 and not image_url:
        raise ValueError("Either image_base64 or image_url must be provided")

    # System message
    messages = [
        {
            "role": "system",
            "content": VISION_SYSTEM_PROMPT,
        }
    ]

    # User message with image
    user_content = []

    # Add image
    if image_base64:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_base64}",
                "detail": "high",
            },
        })
    elif image_url:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": image_url,
                "detail": "high",
            },
        })

    # Add text prompt
    user_content.append({
        "type": "text",
        "text": build_vision_prompt(domain_context, local_snippets),
    })

    messages.append({
        "role": "user",
        "content": user_content,
    })

    return messages


# =============================================================================
# QW-3: VISION_LITE prompts (Diagram Interpreter - ADR_REDUCTO_PARSING_PRIMITIVES)
# =============================================================================
# VISION_LITE is a simpler, faster prompt for less complex visual content.
# Used when VNS is moderate (VISION_RECOMMENDED but not VISION_REQUIRED).

VISION_LITE_SYSTEM_PROMPT = """You are a fast visual extraction engine for document processing.

Your task is to quickly identify:
1. The diagram type (architecture, flowchart, table, etc.)
2. All visible text labels and their types (box, arrow label, heading, etc.)

Output ONLY valid JSON. Be fast and accurate."""


VISION_LITE_JSON_SCHEMA = """{
  "diagram_type": "architecture | flowchart | table | org_chart | process | timeline | comparison | hierarchy | other",
  "labels": [
    {
      "id": "string (e.g., 'L1')",
      "text": "string (exact text visible)",
      "type": "box | arrow_label | title | caption | other"
    }
  ],
  "overall_confidence": 0.0
}"""


VISION_LITE_USER_PROMPT_TEMPLATE = """Quickly extract diagram type and all visible text from this image.

## LOCAL TEXT CONTEXT (if available)
{local_snippets}

## OUTPUT JSON SCHEMA (STRICT)
```json
{json_schema}
```

## RULES
- Extract ONLY text that is clearly visible
- Do not invent or assume any content
- Be fast and concise
- Return valid JSON only"""


def build_vision_lite_prompt(local_snippets: str = "") -> str:
    """
    Construit le prompt Vision LITE (extraction rapide).

    Args:
        local_snippets: Texte local de la page (optionnel)

    Returns:
        Prompt LITE pour extraction rapide
    """
    snippets_section = local_snippets if local_snippets else "(No local text provided)"

    return VISION_LITE_USER_PROMPT_TEMPLATE.format(
        local_snippets=snippets_section,
        json_schema=VISION_LITE_JSON_SCHEMA,
    )


def get_vision_lite_messages(
    local_snippets: str = "",
    image_base64: Optional[str] = None,
    image_url: Optional[str] = None,
) -> list:
    """
    Construit les messages pour l'API Vision en mode LITE.

    Args:
        local_snippets: Texte local
        image_base64: Image encodée en base64
        image_url: URL de l'image (alternatif)

    Returns:
        Liste de messages pour l'API Chat Completions
    """
    if not image_base64 and not image_url:
        raise ValueError("Either image_base64 or image_url must be provided")

    messages = [
        {
            "role": "system",
            "content": VISION_LITE_SYSTEM_PROMPT,
        }
    ]

    user_content = []

    # Add image
    if image_base64:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{image_base64}",
                "detail": "low",  # LITE uses low detail for speed
            },
        })
    elif image_url:
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": image_url,
                "detail": "low",
            },
        })

    user_content.append({
        "type": "text",
        "text": build_vision_lite_prompt(local_snippets),
    })

    messages.append({
        "role": "user",
        "content": user_content,
    })

    return messages


__all__ = [
    "VISION_SYSTEM_PROMPT",
    "VISION_JSON_SCHEMA",
    "VISION_USER_PROMPT_TEMPLATE",
    "build_vision_prompt",
    "get_vision_messages",
    # QW-3: VISION_LITE
    "VISION_LITE_SYSTEM_PROMPT",
    "VISION_LITE_JSON_SCHEMA",
    "VISION_LITE_USER_PROMPT_TEMPLATE",
    "build_vision_lite_prompt",
    "get_vision_lite_messages",
]
