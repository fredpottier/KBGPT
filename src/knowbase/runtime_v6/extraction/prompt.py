"""V6 — Prompt LLM universel pour extraction structurée.

Charte domain-agnostic STRICTE : ce prompt ne mentionne aucun domaine,
ne donne aucun exemple SAP/légal/médical/aerospace. Il instruit le LLM
sur la TÂCHE GÉNÉRIQUE d'extraction structurée — à appliquer à
n'importe quel texte structuré.

Test ex-post de neutralité : ce prompt doit pouvoir s'appliquer tel quel
sur un document de droit, un manuel d'OS, un protocole médical, un
règlement aérospatial — sans modification.

Output attendu : JSON conforme à `SectionExtraction` Pydantic schema.
"""
from __future__ import annotations

from textwrap import dedent


# ─────────────────────────────────────────────────────────────────────────────
# Prompt système (instructions générales, invariantes)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = dedent("""\
    You are an expert document analyst tasked with extracting structured
    information from a document section. Your goal is to enable someone to
    later search and reason about the content without re-reading the
    document.

    You extract FIVE archetypes of information that are universal to any
    structured document (technical, legal, medical, procedural, ...):

    1. NAMED ENTITIES
       Any proper noun, code, identifier, or named concept referenced in
       the text. Examples (illustrative, not domain-specific):
       - Codes / identifiers (alphanumeric, with or without prefix)
       - Person names, place names, organization names
       - Standards, regulations, certifications
       - Named tools, products, components
       - Named abstract concepts (not common nouns)

       Classify each entity by its kind: "code", "person", "place",
       "organization", "concept", "tool", "standard", "regulation",
       "product", "event", "other".

    2. ATOMIC FACTS
       Simple verifiable assertions in the form subject + verb + object.
       One assertion per fact (no compound sentences).
       Stay strictly grounded in the text — do not infer beyond what
       is written.
       Classify each fact's modality:
       - "asserted" : direct claim ("X is Y")
       - "conditional" : "if A then X is Y"
       - "negated" : "X is NOT Y" / "X must not Y"
       - "example" : "for example, X is Y"
       - "hypothetical" : "X could be Y" / "may be"

    3. PROCEDURES
       Any sequence of steps describing how to accomplish a goal.
       Extract: name (short), goal (what is achieved), steps (ordered
       list), prerequisites (if mentioned).

    4. CONSTRAINTS
       Rules, requirements, prohibitions, conditions, or exceptions
       explicitly stated. Classify each:
       - "requirement" : X MUST be Y
       - "prohibition" : X MUST NOT be Y
       - "exception" : exception to a rule
       - "condition" : condition for a rule to apply
       - "exclusion" : case excluded from scope

    5. REFERENCES
       Pointers to other information (internal sections, external
       documents, standards, regulations, URLs). Capture the exact
       reference text. Classify the target kind:
       - "internal_section" : reference to another section of the same doc
       - "external_document" : reference to another named document
       - "standard" : reference to a standard/specification
       - "regulation" : reference to a legal/regulatory text
       - "url" : URL reference
       - "other" : fallback

    RULES:
    - Stay strictly grounded in the provided text. Do NOT invent.
    - For each fact, you MUST provide an `evidence_text` containing the
      verbatim or quasi-verbatim text that supports the assertion.
    - Use lowercase for predicates (e.g. "initializes", "requires", "is_a").
    - Keep entries concise but complete.
    - If nothing of a given type is present, return an empty list for it.
    - Do NOT use domain-specific vocabulary in field names or types.
    - Output strict JSON, no markdown, no comments, no preamble.
""")


# ─────────────────────────────────────────────────────────────────────────────
# Template user (par section à extraire)
# ─────────────────────────────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = dedent("""\
    Document ID: {doc_id}
    Section ID: {section_id}
    Section title: {section_title}

    Section content:
    \"\"\"
    {section_text}
    \"\"\"

    Extract structured information following the schema below.
    Return ONLY valid JSON, no markdown fences, no comments.

    Required JSON shape (omit a list if empty, but keep the key):

    {{
      "entities": [
        {{
          "canonical_name": "<string>",
          "aliases": ["<string>", ...],
          "entity_kind": "<one of: code|person|place|organization|concept|tool|standard|regulation|product|event|other>",
          "domain_type": null,
          "description": "<short description or null>"
        }}
      ],
      "facts": [
        {{
          "subject": "<string>",
          "predicate": "<lowercase verb or relation>",
          "object": "<string>",
          "modality": "<one of: asserted|conditional|negated|example|hypothetical>",
          "evidence_text": "<verbatim snippet from the section>"
        }}
      ],
      "procedures": [
        {{
          "name": "<short name>",
          "goal": "<what the procedure achieves>",
          "steps": [
            {{"step_number": 1, "action": "<action>", "notes": "<optional or null>"}}
          ],
          "prerequisites": ["<string>", ...]
        }}
      ],
      "constraints": [
        {{
          "constraint_type": "<one of: requirement|prohibition|exception|condition|exclusion>",
          "statement": "<verbatim or quasi-verbatim>",
          "applies_to": ["<entity or procedure name>", ...]
        }}
      ],
      "references": [
        {{
          "reference_text": "<text of reference as appears in section>",
          "target_kind": "<one of: internal_section|external_document|standard|regulation|url|other>"
        }}
      ]
    }}

    Do NOT include evidence_section_id in your output — it will be added
    automatically.
""")


def build_extraction_messages(
    doc_id: str,
    section_id: str,
    section_title: str,
    section_text: str,
) -> list[dict]:
    """Construit la liste de messages [system, user] pour l'extraction.

    Args:
        doc_id : identifiant document
        section_id : identifiant section
        section_title : titre de la section (peut être vide)
        section_text : contenu textuel de la section

    Returns:
        list[dict] : messages format OpenAI chat completions
    """
    user_content = USER_PROMPT_TEMPLATE.format(
        doc_id=doc_id,
        section_id=section_id,
        section_title=section_title or "(no title)",
        section_text=section_text,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
