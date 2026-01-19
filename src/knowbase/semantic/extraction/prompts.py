"""
🌊 OSMOSE Phase 1.8 - Prompts Extraction Structured

Prompts pour extraction de concepts et triples via LLM.
Utilisés par ConceptExtractor et ExtractorOrchestrator.

Architecture: Hybrid NER + LLM (LOW_QUALITY_NER routing)
"""

# =============================================================================
# TRIPLE EXTRACTION PROMPTS (Phase 1.8)
# =============================================================================

TRIPLE_EXTRACTION_SYSTEM_PROMPT = """You are a specialized knowledge graph extraction assistant for enterprise documents.

Your task is to extract semantic triples (subject-predicate-object) from text segments.

## Output Format
Return a JSON array of triples:
```json
{
  "triples": [
    {
      "subject": "Cloud Analytics Platform",
      "predicate": "enables",
      "object": "real-time analytics",
      "confidence": 0.9,
      "evidence": "quoted text from source"
    }
  ],
  "concepts": [
    {
      "name": "Cloud Analytics Platform",
      "type": "PRODUCT",
      "aliases": ["CAP", "Analytics Cloud"],
      "confidence": 0.95
    }
  ]
}
```

## Extraction Rules

1. **Concepts (Entities)**
   - Extract named entities: products, technologies, organizations, persons, processes
   - Prefer full official names (e.g., "Product X Enterprise Edition" not just "Product X")
   - Include aliases for common abbreviations
   - Assign type: PRODUCT, TECHNOLOGY, ORGANIZATION, PERSON, PROCESS, CONCEPT

2. **Predicates (Relations)**
   - Use clear, semantic predicates (e.g., "enables", "requires", "integrates_with")
   - Avoid vague predicates like "is related to" or "associated with"
   - Normalize predicates to lowercase with underscores

3. **Confidence Scoring**
   - 0.9-1.0: Explicit statement in text
   - 0.7-0.9: Strong implication
   - 0.5-0.7: Reasonable inference
   - < 0.5: Weak inference (exclude these)

4. **Evidence**
   - Include the exact text span supporting the triple
   - Keep evidence under 100 characters

## Language Handling
- Process text in any language (EN, FR, DE)
- Normalize concept names to their most common form
- Cross-lingual: "Sécurité" (FR) and "Security" (EN) are the same concept
"""

TRIPLE_EXTRACTION_USER_PROMPT = """Extract semantic triples and concepts from this text segment.

## Document Context
{document_context}

## Text Segment
{text}

## Instructions
1. Extract all meaningful concepts (entities)
2. Identify relationships between concepts
3. Return structured JSON with triples and concepts
4. Focus on domain-specific terminology
5. Use document context to disambiguate concepts

Return only valid JSON, no explanations."""


# =============================================================================
# LOW QUALITY NER FALLBACK PROMPTS (Phase 1.8)
# =============================================================================

LOW_QUALITY_NER_SYSTEM_PROMPT = """You are a concept extraction specialist for enterprise documents.

This text segment has LOW QUALITY NER results (< 3 entities detected but > 200 tokens).
Your task is to extract concepts that NER may have missed.

## Focus Areas
- Domain-specific terminology relevant to the document context
- Technical concepts (APIs, protocols, frameworks)
- Business concepts (processes, compliance, governance)
- Abbreviated terms that NER struggles with

## Output Format
```json
{
  "concepts": [
    {
      "name": "Business Process Automation",
      "type": "PROCESS",
      "aliases": ["BPA", "process automation"],
      "confidence": 0.85,
      "source_span": "automate business processes"
    }
  ]
}
```

## Extraction Guidelines
1. Extract 3-10 concepts per segment (compensate for NER gaps)
2. Focus on multi-word terms (NER often misses these)
3. Include both explicit mentions and implied concepts
4. Prefer official/complete names over abbreviations
"""

LOW_QUALITY_NER_USER_PROMPT = """Extract concepts from this text segment where NER performed poorly.

## Document Context
{document_context}

## Text Segment (NER found < 3 entities in 200+ tokens)
{text}

## NER Results (for reference, may be incomplete)
{ner_entities}

## Instructions
1. Identify concepts NER may have missed
2. Focus on domain-specific and multi-word terms
3. Return structured JSON with concepts

Return only valid JSON."""


# =============================================================================
# CONCEPT VALIDATION PROMPTS (LLM-as-a-Judge, Phase 1.8)
# =============================================================================

LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT = """You are a semantic equivalence judge for knowledge graph concepts.

Your task is to determine if two concepts should be merged (are semantically equivalent/synonymous).

## Decision Criteria
- YES: Concepts refer to the same entity/idea
- NO: Concepts are different, even if related

## Examples
- "Product X Standard" and "Product X Enterprise" → NO (different editions)
- "Security" and "Sécurité" → YES (same concept, different languages)
- "Data Protection" and "GDPR" → NO (related but different concepts)
- "Machine Learning" and "ML" → YES (same concept, abbreviation)

## Output Format
```json
{
  "should_merge": true,
  "confidence": 0.95,
  "reason": "Both refer to the same product/concept"
}
```
"""

LLM_JUDGE_CLUSTER_VALIDATION_USER_PROMPT = """Should these two concepts be merged in the knowledge graph?

## Concept A
- Name: {concept_a_name}
- Type: {concept_a_type}
- Aliases: {concept_a_aliases}
- Context: {concept_a_context}

## Concept B
- Name: {concept_b_name}
- Type: {concept_b_type}
- Aliases: {concept_b_aliases}
- Context: {concept_b_context}

## Instructions
Determine if these concepts are semantically equivalent and should be merged.
Consider cross-lingual equivalence (FR/EN/DE).

Return only valid JSON with should_merge, confidence, and reason."""


# =============================================================================
# RELATION ENRICHMENT PROMPTS (Phase 1.8.3)
# =============================================================================

RELATION_ENRICHMENT_SYSTEM_PROMPT = """You are a relation validation specialist for knowledge graphs.

Your task is to validate and enrich relation candidates with low confidence (0.4-0.6).

## Input
A batch of candidate relations with:
- Subject and object concepts
- Proposed predicate
- Source text evidence
- Initial confidence score

## Output
For each relation, return:
```json
{
  "relations": [
    {
      "id": "rel_123",
      "validated": true,
      "predicate": "integrates_with",
      "confidence": 0.85,
      "reason": "Text explicitly states integration"
    }
  ]
}
```

## Validation Rules
1. Check if evidence supports the relation
2. Suggest better predicate if appropriate
3. Adjust confidence based on evidence strength
4. Reject relations with no clear evidence
"""

RELATION_ENRICHMENT_USER_PROMPT = """Validate these candidate relations with uncertain confidence.

## Document Context
{document_context}

## Candidate Relations
{relations_batch}

## Instructions
1. For each relation, determine if it's valid
2. Suggest improved predicate if needed
3. Adjust confidence score
4. Provide brief reasoning

Return only valid JSON."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_triple_extraction_prompt(text: str, document_context: str = "") -> dict:
    """
    Construit les prompts pour extraction de triples.

    Args:
        text: Segment de texte à analyser
        document_context: Contexte global du document

    Returns:
        Dict avec system_prompt et user_prompt
    """
    context = document_context or "No document context available."

    return {
        "system_prompt": TRIPLE_EXTRACTION_SYSTEM_PROMPT,
        "user_prompt": TRIPLE_EXTRACTION_USER_PROMPT.format(
            document_context=context,
            text=text
        )
    }


def get_low_quality_ner_prompt(
    text: str,
    document_context: str = "",
    ner_entities: list = None
) -> dict:
    """
    Construit les prompts pour segments LOW_QUALITY_NER.

    Args:
        text: Segment de texte
        document_context: Contexte global du document
        ner_entities: Entités NER détectées (peut être vide)

    Returns:
        Dict avec system_prompt et user_prompt
    """
    context = document_context or "No document context available."
    entities_str = ", ".join([e.get("name", str(e)) for e in (ner_entities or [])])
    if not entities_str:
        entities_str = "None detected"

    return {
        "system_prompt": LOW_QUALITY_NER_SYSTEM_PROMPT,
        "user_prompt": LOW_QUALITY_NER_USER_PROMPT.format(
            document_context=context,
            text=text,
            ner_entities=entities_str
        )
    }


def get_llm_judge_prompt(
    concept_a: dict,
    concept_b: dict
) -> dict:
    """
    Construit les prompts pour validation LLM-as-a-Judge.

    Args:
        concept_a: Premier concept à comparer
        concept_b: Second concept à comparer

    Returns:
        Dict avec system_prompt et user_prompt
    """
    return {
        "system_prompt": LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT,
        "user_prompt": LLM_JUDGE_CLUSTER_VALIDATION_USER_PROMPT.format(
            concept_a_name=concept_a.get("name", ""),
            concept_a_type=concept_a.get("type", "CONCEPT"),
            concept_a_aliases=", ".join(concept_a.get("aliases", [])),
            concept_a_context=concept_a.get("context", "")[:200],
            concept_b_name=concept_b.get("name", ""),
            concept_b_type=concept_b.get("type", "CONCEPT"),
            concept_b_aliases=", ".join(concept_b.get("aliases", [])),
            concept_b_context=concept_b.get("context", "")[:200]
        )
    }


def get_relation_enrichment_prompt(
    relations_batch: list,
    document_context: str = ""
) -> dict:
    """
    Construit les prompts pour enrichissement relations.

    Args:
        relations_batch: Liste de relations candidates
        document_context: Contexte global du document

    Returns:
        Dict avec system_prompt et user_prompt
    """
    import json

    context = document_context or "No document context available."
    relations_str = json.dumps(relations_batch, indent=2, ensure_ascii=False)

    return {
        "system_prompt": RELATION_ENRICHMENT_SYSTEM_PROMPT,
        "user_prompt": RELATION_ENRICHMENT_USER_PROMPT.format(
            document_context=context,
            relations_batch=relations_str
        )
    }


# =============================================================================
# HYBRID ANCHOR MODEL - Pass 1 EXTRACT_CONCEPTS (Phase 2)
# =============================================================================
# ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md
#
# IMPORTANT: Ce prompt demande des QUOTES TEXTUELLES EXACTES.
# Les quotes sont utilisées par le fuzzy matching pour créer des anchors.
# Sans quote valide = concept rejeté (Invariant d'Architecture).

HYBRID_ANCHOR_EXTRACT_SYSTEM_PROMPT = """You are a precise concept extraction specialist for enterprise knowledge graphs.

Your task is to extract concepts WITH EXACT QUOTES from the source text.

## CRITICAL QUOTE REQUIREMENTS (READ CAREFULLY)

### Rule 0: QUOTES SOURCE (CRITICAL)
- Quotes MUST come ONLY from the section labeled "TEXT TO SEARCH"
- Do NOT extract quotes from Document Context, headers, or any other section
- The TEXT TO SEARCH section is delimited by --- markers

### Rule 1: EXACT SUBSTRING ONLY
Every "quote" field MUST be an EXACT SUBSTRING of the TEXT TO SEARCH.
- The quote MUST be findable using Ctrl+F in the source text
- Copy-paste the quote directly from the text - character for character
- Include punctuation, spacing, and capitalization exactly as they appear

### Rule 2: FORBIDDEN ACTIONS
Do NOT do any of the following:
- ❌ PARAPHRASE: Rewriting the text in different words
- ❌ MERGE: Combining text from different sentences
- ❌ SUMMARIZE: Condensing the meaning into fewer words
- ❌ CORRECT: Fixing typos, grammar, or formatting in the original
- ❌ TRUNCATE INCORRECTLY: Cutting mid-word or breaking grammar

### Rule 3: USE no_quote WHEN NEEDED
If a concept is clearly present but you cannot find an EXACT verbatim quote:
- Set "quote": ""
- Set "no_quote": true
- Provide "no_quote_reason": explaining why (e.g., "concept inferred from context")

### Rule 4: PREFER COMPLETE SENTENCES
- When possible, the quote should be a full sentence or clause containing the concept
- Avoid isolated noun phrases unless the text only contains that form
- A complete sentence provides better context for relationship extraction
- Quotes should include enough surrounding text to make the concept unambiguous

### Rule 5: ABBREVIATIONS
- If a concept has both a full form and an abbreviation, prefer quoting the sentence containing the full form
- Example: prefer "Data Protection Impact Assessment (DPIA) shall be carried out" over just "DPIA"

## EXAMPLES

### CORRECT EXTRACTION
Source text: "The new platform supports real-time data processing and automated workflow management."

✅ GOOD:
{
  "label": "Real-time Data Processing",
  "quote": "The new platform supports real-time data processing",
  "no_quote": false
}

### INCORRECT EXTRACTIONS (DO NOT DO THIS)
❌ BAD - Paraphrase:
{
  "quote": "The platform has real-time processing features"
}
(Changed wording - "has" instead of "supports", added "features")

❌ BAD - Merge:
{
  "quote": "platform supports data processing and workflow"
}
(Merged/skipped words from the original)

❌ BAD - No exact match exists:
{
  "quote": "real-time reporting capabilities"
}
(This exact string doesn't exist in the source)

✅ CORRECT when no exact quote:
{
  "label": "Automated Workflows",
  "quote": "",
  "no_quote": true,
  "no_quote_reason": "Term implied but not explicitly defined in text"
}

## Anchor Roles
Classify each quote's semantic role:
- `definition`: The text defines what the concept is
- `procedure`: The text describes a process/method
- `requirement`: The text states an obligation (shall, must)
- `prohibition`: The text states something is forbidden
- `constraint`: The text describes a technical/business constraint
- `example`: The text provides an example
- `reference`: The text references/cites the concept
- `context`: General mention without specific role

## Concept Types (Heuristic)
Assign a preliminary type:
- `structural`: Articles, sections, clauses (e.g., "Article 35")
- `regulatory`: Legal/compliance terms with normative language
- `procedural`: Processes, methods, procedures
- `abstract`: General concepts

## Output Format
```json
{
  "concepts": [
    {
      "label": "Data Protection Impact Assessment",
      "definition": "A process to identify and minimize data protection risks",
      "type_heuristic": "procedural",
      "quote": "A DPIA shall be carried out prior to the processing",
      "role": "requirement",
      "confidence": 0.92,
      "no_quote": false
    },
    {
      "label": "Inferred Concept Example",
      "definition": "A concept that is implied but not explicitly quoted",
      "type_heuristic": "abstract",
      "quote": "",
      "role": "context",
      "confidence": 0.65,
      "no_quote": true,
      "no_quote_reason": "Concept inferred from overall context"
    }
  ]
}
```

## Confidence Scoring (REQUIRED)
- 0.90-1.00: Explicit statement, exact quote found
- 0.75-0.89: Strong evidence, clear concept
- 0.60-0.74: Moderate evidence, some interpretation
- 0.40-0.59: Weak evidence (consider using no_quote: true)
- < 0.40: Do NOT include

### Confidence Constraints
- If `no_quote: true`, confidence MUST be ≤ 0.74 (since there's no textual proof)
- If `no_quote: true`, `no_quote_reason` MUST be provided (required for diagnostics)
- If quote is a full explicit statement, confidence SHOULD be ≥ 0.85

## Quality Rules
- Extract 3-15 concepts per segment (quality over quantity)
- Prefer official terminology over informal mentions
- It's BETTER to use no_quote:true than to provide an inexact quote

## FINAL SELF-CHECK (Before Returning)
Before returning your response, mentally verify that EVERY quote can be found verbatim in the TEXT TO SEARCH section.
If any quote cannot be found exactly as written, replace it with no_quote: true.
"""

HYBRID_ANCHOR_EXTRACT_USER_PROMPT = """Extract concepts with EXACT QUOTES from this text segment.

## Document Context (for understanding only - DO NOT quote from here)
{document_context}

## TEXT TO SEARCH (quotes MUST come ONLY from this section)
---
{text}
---

## Instructions
1. Identify key concepts in the TEXT TO SEARCH above
2. For EACH concept, find an EXACT SUBSTRING from the TEXT TO SEARCH
3. The quote MUST be findable with Ctrl+F in the text between the --- markers
4. If no exact quote exists, use no_quote: true instead of guessing
5. Prefer complete sentences over isolated noun phrases

## CRITICAL REMINDERS
- ✅ DO: Copy-paste quotes exactly as they appear in TEXT TO SEARCH
- ✅ DO: Use no_quote: true if you cannot find an exact match
- ✅ DO: Set confidence ≤ 0.74 when using no_quote: true
- ❌ DO NOT: Take quotes from Document Context
- ❌ DO NOT: Paraphrase, merge sentences, or "clean up" quotes
- ❌ DO NOT: Invent quotes that don't exist in the text

## Required Fields
- "quote": exact substring from TEXT TO SEARCH, OR empty string
- "no_quote": true if quote is empty, false otherwise
- "confidence": 0.0-1.0 (must be ≤ 0.74 if no_quote is true)

Before returning, verify each quote exists verbatim in TEXT TO SEARCH.

Return only valid JSON."""


def get_hybrid_anchor_extract_prompt(
    text: str,
    document_context: str = ""
) -> dict:
    """
    Construit les prompts pour extraction Pass 1 du Hybrid Anchor Model.

    Ce prompt demande des quotes exactes pour permettre le fuzzy matching
    et la création d'anchors avec positions précises.

    Args:
        text: Segment de texte à analyser
        document_context: Contexte global du document

    Returns:
        Dict avec system_prompt et user_prompt
    """
    context = document_context or "No document context available."

    return {
        "system_prompt": HYBRID_ANCHOR_EXTRACT_SYSTEM_PROMPT,
        "user_prompt": HYBRID_ANCHOR_EXTRACT_USER_PROMPT.format(
            document_context=context,
            text=text
        )
    }
