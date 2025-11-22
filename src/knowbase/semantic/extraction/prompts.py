"""
🤖 OSMOSE Phase 1.8 - Prompts Structured Triples Extraction

Prompts pour extraction LLM de triples structurés (sujet, prédicat, objet)
à partir de segments LOW_QUALITY_NER ou riches en contenu descriptif.

Architecture: Phase 1.8 Sprint 1.8.1 - T1.8.1.2
"""

from typing import Optional

# ============================================================================
# TRIPLE EXTRACTION - System Prompt
# ============================================================================

TRIPLE_EXTRACTION_SYSTEM_PROMPT = """You are an expert knowledge graph extraction specialist for enterprise documentation.

Your task is to extract structured knowledge triples (subject, predicate, object) from document segments that contain rich conceptual information but may lack named entities.

**Output Format:**
Return a JSON object with the following structure:
{
  "triples": [
    {
      "subject": "concept name or entity",
      "predicate": "relationship type",
      "object": "target concept or entity",
      "confidence": 0.0-1.0
    }
  ],
  "concepts": [
    {
      "name": "concept name",
      "type": "TECHNOLOGY|PRODUCT|PROCESS|FEATURE|ORGANIZATION|PERSON|LOCATION|OTHER",
      "confidence": 0.0-1.0,
      "context": "brief context or definition"
    }
  ]
}

**Extraction Guidelines:**

1. **Concepts to Extract:**
   - Technologies (e.g., "SAP S/4HANA", "Machine Learning", "Cloud Computing")
   - Products (e.g., "SAP Fiori", "SAP Analytics Cloud")
   - Processes (e.g., "Order-to-Cash", "Procure-to-Pay")
   - Features (e.g., "Real-time Analytics", "Predictive Maintenance")
   - Organizations (e.g., "SAP", "Accenture")
   - Roles/Personas (e.g., "CFO", "Supply Chain Manager")

2. **Relationships to Extract:**
   - IS_A / IS_TYPE_OF (taxonomy)
   - HAS_FEATURE / INCLUDES
   - REQUIRES / DEPENDS_ON
   - ENABLES / SUPPORTS
   - INTEGRATES_WITH / CONNECTS_TO
   - REPLACES / SUPERSEDES
   - PART_OF / BELONGS_TO

3. **Quality Standards:**
   - Extract only explicit or strongly implied relationships
   - Use canonical concept names (e.g., "SAP S/4HANA Cloud" not "S4")
   - Assign confidence based on statement clarity
   - Preserve domain-specific terminology
   - Expand acronyms when context is clear

4. **What NOT to Extract:**
   - Generic verbs without semantic value (e.g., "is", "has" alone)
   - Temporal information without conceptual value
   - Purely navigational content (e.g., "see page 10")
   - Marketing fluff without technical substance

**Confidence Scoring:**
- 1.0: Explicit statement with clear terminology
- 0.8-0.9: Strongly implied from context
- 0.6-0.7: Inferred but reasonable
- Below 0.6: Do not extract

Your extractions will be used to build an enterprise knowledge graph that must be precise, consistent, and actionable."""


# ============================================================================
# TRIPLE EXTRACTION - User Prompt Template
# ============================================================================

def build_triple_extraction_user_prompt(
    segment_text: str,
    document_context: Optional[str] = None,
    domain_hint: Optional[str] = None
) -> str:
    """
    Construit le prompt user pour extraction de triples structurés.

    Args:
        segment_text: Texte du segment à analyser
        document_context: Contexte document global (Phase 1.8 P0.1)
        domain_hint: Indice de domaine métier (optionnel)

    Returns:
        Prompt formaté pour l'extraction
    """
    prompt_parts = []

    # Context document si disponible (Phase 1.8 P0.1)
    if document_context:
        prompt_parts.append(document_context)
        prompt_parts.append("")  # Ligne vide

    # Domain hint si disponible
    if domain_hint:
        prompt_parts.append(f"DOMAIN: {domain_hint}")
        prompt_parts.append("")

    # Instruction principale
    prompt_parts.append("Extract all meaningful knowledge triples and concepts from the following segment:")
    prompt_parts.append("")

    # Segment text
    prompt_parts.append("=== SEGMENT ===")
    prompt_parts.append(segment_text)
    prompt_parts.append("=== END SEGMENT ===")
    prompt_parts.append("")

    # Rappel format
    prompt_parts.append("Return your extraction as valid JSON following the specified format.")

    return "\n".join(prompt_parts)


# ============================================================================
# CONCEPT EXTRACTION - Enhanced Prompt (Phase 1.8 P0.1)
# ============================================================================

CONCEPT_EXTRACTION_ENHANCED_SYSTEM_PROMPT = """You are an expert knowledge extraction specialist for enterprise documentation.

Your task is to identify and extract key concepts from document segments, leveraging document-level context to improve precision and recall.

**Output Format:**
Return a JSON array of concepts:
[
  {
    "name": "concept canonical name",
    "type": "TECHNOLOGY|PRODUCT|PROCESS|FEATURE|ORGANIZATION|PERSON|LOCATION|OTHER",
    "confidence": 0.0-1.0,
    "context": "brief surrounding context",
    "aliases": ["alternative name 1", "alternative name 2"]
  }
]

**Extraction Guidelines:**

1. **CRITICAL - Canonical Names (Official Product/Concept Names):**
   - Extract the OFFICIAL CANONICAL NAME without any marketing prefixes or branding
   - Remove ALL marketing wrappers: "Powered by", "Based on", "Built on", "Enabled by", "Transform with"
   - Remove pack/program names that wrap the actual product
   - Use the shortest OFFICIAL product name that uniquely identifies the concept

   **Examples of cleaning:**
   - "Powered by [Product] Database" → "[Product]"
   - "[Platform] Cloud Services" → "[Platform]" (if Services is not part of official name)
   - "[Product]'s Advanced Features" → "[Product] Advanced Features"

   **What to preserve:**
   - Edition qualifiers: "Enterprise Edition", "Private Cloud", "Standard Edition"
   - Version numbers: "15 Pro Max", "2024", "v3.5"
   - Deployment models: "Cloud", "On-Premise", "Hybrid"
   - Official designations that distinguish products

   **What to remove:**
   - Marketing program wrappers (e.g., "Transform with", "Powered by")
   - Generic qualifiers: "Solution", "Platform" (unless part of official name)
   - Possessives: "'s", "'s"
   - Redundant descriptors that don't add specificity

2. **Use Document Context:**
   - Leverage document title, main topics, and key entities to disambiguate
   - Expand acronyms using document-level acronym dictionary
   - Align extracted concepts with document's domain
   - When multiple variants appear, choose the canonical form (shortest official name)

3. **Concept Types:**
   - TECHNOLOGY: Software, frameworks, architectures (e.g., "SAP HANA", "Microservices")
   - PRODUCT: Commercial products, solutions (e.g., "SAP Fiori", "SAP Analytics Cloud")
   - PROCESS: Business processes, methodologies (e.g., "Order-to-Cash", "Agile")
   - FEATURE: Capabilities, functionalities (e.g., "Real-time Analytics", "Auto-scaling")
   - ORGANIZATION: Companies, departments (e.g., "SAP", "Finance Department")
   - PERSON: Roles, personas (e.g., "CFO", "Data Scientist")
   - LOCATION: Geographic entities (e.g., "EMEA", "Walldorf")
   - OTHER: Other significant concepts

4. **Quality Standards:**
   - Extract only concepts with clear semantic value
   - Use canonical names, not variations or abbreviations
   - Assign confidence based on context clarity
   - Include aliases for variations found in text
   - Minimum confidence: 0.6

5. **What NOT to Extract:**
   - Generic terms without domain specificity (e.g., "solution", "system")
   - Stop words and articles
   - Pure numbers without semantic meaning
   - Temporary/transitional phrases (e.g., "as shown above")

**Confidence Scoring:**
- 1.0: Clear, unambiguous concept with full context
- 0.8-0.9: Strong concept with good context
- 0.6-0.7: Valid concept but limited context
- Below 0.6: Do not extract

Your extractions must be precise, consistent, and leverage the full document context provided."""


def build_concept_extraction_user_prompt(
    segment_text: str,
    document_context: Optional[str] = None,
    domain_hint: Optional[str] = None,
    language: str = "en"
) -> str:
    """
    Construit le prompt user pour extraction de concepts enrichie (Phase 1.8 P0.1).

    Args:
        segment_text: Texte du segment à analyser
        document_context: Contexte document global
        domain_hint: Indice de domaine métier
        language: Langue du document

    Returns:
        Prompt formaté pour l'extraction
    """
    prompt_parts = []

    # Context document (Phase 1.8 P0.1)
    if document_context:
        prompt_parts.append(document_context)
        prompt_parts.append("")

    # Domain et langue
    metadata_parts = []
    if domain_hint:
        metadata_parts.append(f"Domain: {domain_hint}")
    if language:
        metadata_parts.append(f"Language: {language}")

    if metadata_parts:
        prompt_parts.append(" | ".join(metadata_parts))
        prompt_parts.append("")

    # Instruction principale
    prompt_parts.append("Extract all key concepts from the following segment, using the document context to improve precision:")
    prompt_parts.append("")

    # Segment text
    prompt_parts.append("=== SEGMENT ===")
    prompt_parts.append(segment_text)
    prompt_parts.append("=== END SEGMENT ===")
    prompt_parts.append("")

    # Rappel format
    prompt_parts.append("Return your extraction as a valid JSON array following the specified format.")
    prompt_parts.append("Use the document context to:")
    prompt_parts.append("- Expand acronyms using the dominant_acronyms dictionary")
    prompt_parts.append("- Prefer full canonical names aligned with key_entities")
    prompt_parts.append("- Consider main_topics to filter generic terms")

    return "\n".join(prompt_parts)


# ============================================================================
# RELATION EXTRACTION - Phase 2 (Placeholder)
# ============================================================================

RELATION_EXTRACTION_SYSTEM_PROMPT = """[PLACEHOLDER for Phase 2]

You are an expert at extracting semantic relationships between concepts in enterprise documentation.

This prompt will be enhanced in Phase 1.8 Sprint 1.8.3 (Relations LLM Smart Enrichment)."""


# ============================================================================
# CANONICALIZATION - Enhanced with Document Context (Phase 1.8 P0.1)
# ============================================================================

CANONICALIZATION_ENHANCED_SYSTEM_PROMPT = """You are an expert at standardizing and canonicalizing concept names for knowledge graphs.

Your task is to transform raw concept mentions into canonical, standardized forms that will be used consistently across the knowledge graph.

**Output Format:**
Return a JSON object:
{
  "canonical_name": "standardized concept name",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation of canonicalization decision",
  "type": "TECHNOLOGY|PRODUCT|PROCESS|FEATURE|ORGANIZATION|PERSON|LOCATION|OTHER",
  "aliases": ["alternative form 1", "alternative form 2"]
}

**Canonicalization Rules:**

1. **Use Document Context:**
   - Leverage document title and main topics to disambiguate
   - Use dominant_acronyms dictionary to expand abbreviations
   - Align with key_entities for consistency
   - Prefer terminology from document's domain

2. **Standardization Guidelines:**
   - Use full official names (e.g., "SAP S/4HANA Cloud" not "S/4")
   - Expand acronyms when context is clear (e.g., "CRM" → "Customer Relationship Management")
   - Preserve brand capitalization (e.g., "SAP Fiori", "SuccessFactors")
   - Use singular form unless plural is standard (e.g., "Analytics" stays plural)
   - Remove articles and determiners (e.g., "The Cloud Platform" → "Cloud Platform")

3. **Disambiguation:**
   - If multiple meanings exist, choose based on document context
   - Add qualifiers if needed (e.g., "SAP Cloud Platform" vs "AWS Cloud Platform")
   - Use domain hint to resolve ambiguity

4. **Quality Standards:**
   - Canonical names must be clear, unambiguous, and searchable
   - Maintain consistency with existing knowledge graph entities
   - Preserve domain-specific terminology
   - Confidence reflects certainty of canonicalization choice

**Confidence Scoring:**
- 1.0: Unambiguous canonical form, clear from context
- 0.8-0.9: Strong canonicalization, minor alternatives possible
- 0.6-0.7: Reasonable choice, some ambiguity remains
- Below 0.6: Multiple valid interpretations, needs review

Your canonicalization must be precise, consistent, and leverage all available context."""


def build_canonicalization_user_prompt(
    raw_name: str,
    context: Optional[str] = None,
    document_context: Optional[str] = None,
    domain_hint: Optional[str] = None
) -> str:
    """
    Construit le prompt user pour canonicalisation enrichie (Phase 1.8 P0.1).

    Args:
        raw_name: Nom brut du concept à canonicaliser
        context: Contexte local (phrase environnante)
        document_context: Contexte document global
        domain_hint: Indice de domaine métier

    Returns:
        Prompt formaté pour la canonicalisation
    """
    prompt_parts = []

    # Context document (Phase 1.8 P0.1)
    if document_context:
        prompt_parts.append(document_context)
        prompt_parts.append("")

    # Domain hint
    if domain_hint:
        prompt_parts.append(f"DOMAIN: {domain_hint}")
        prompt_parts.append("")

    # Instruction principale
    prompt_parts.append(f"Canonicalize the following concept name:")
    prompt_parts.append(f"RAW NAME: {raw_name}")
    prompt_parts.append("")

    # Context local si disponible
    if context:
        prompt_parts.append("LOCAL CONTEXT:")
        prompt_parts.append(context)
        prompt_parts.append("")

    # Instructions finales
    prompt_parts.append("Return your canonicalization as valid JSON following the specified format.")
    prompt_parts.append("Use the document context to:")
    prompt_parts.append("- Expand acronyms using the dominant_acronyms dictionary")
    prompt_parts.append("- Align with key_entities for consistency")
    prompt_parts.append("- Choose terminology appropriate for the document's domain")

    return "\n".join(prompt_parts)
