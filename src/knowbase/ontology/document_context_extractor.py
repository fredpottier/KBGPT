"""
Document Context Extractor

Phase 1.6+: Extraction automatique de contextes documentaires (version, edition, etc.)
pour modélisation Neo4j contextuelle.

Fix 2025-10-20: Système de contextualisation universelle pour éviter doublons
et capturer spécificités version/edition.
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import json
import logging
import re

logger = logging.getLogger(__name__)


class DocumentContext(BaseModel):
    """Contexte extrait d'un document."""

    version: Optional[str] = Field(None, description="Version du produit (ex: '2023', '2025', 'Q2 2024')")
    edition: Optional[str] = Field(None, description="Edition/deployment (ex: 'Cloud Private', 'On-Premise')")
    industry: Optional[str] = Field(None, description="Industrie cible (ex: 'Retail', 'Manufacturing')")
    use_case: Optional[str] = Field(None, description="Cas d'usage (ex: 'Security', 'Integration')")
    temporal_scope: Optional[str] = Field(None, description="Période temporelle (ex: 'Q1 2024', 'Printemps 2025')")
    geographic_scope: Optional[str] = Field(None, description="Zone géographique (ex: 'EU', 'Global')")

    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiance extraction (0-1)")
    is_version_agnostic: bool = Field(True, description="True si document généraliste (pas de version)")
    extraction_method: str = Field("unknown", description="Méthode extraction (heuristic/llm/manual)")

    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées additionnelles")


class DocumentContextExtractor:
    """
    Extrait contextes documentaires de manière universelle.

    Utilise approche hybride :
    1. Heuristiques (patterns regex) pour extraction rapide
    2. LLM pour cas ambigus ou complexes
    """

    def __init__(self, llm_router=None):
        """
        Args:
            llm_router: Router LLM optionnel pour extraction avancée
        """
        self.llm_router = llm_router

        # Patterns heuristiques universels
        self.version_patterns = [
            r'\b(\d{4})\b',                    # Année: 2023, 2025
            r'\b(v?\d+\.\d+(?:\.\d+)?)\b',    # Semantic: v1.2, 2.0.1
            r'\b(Q[1-4]\s*\d{4})\b',          # Quarter: Q2 2024
            r'\b(R\d+)\b',                     # Release: R12, R15
            r'\b(\d{4}\.\d{2})\b',            # Year.Month: 2024.03
        ]

        self.edition_patterns = [
            r'(Cloud\s+(?:Private|Public))',
            r'(On-Premise|On-Prem)',
            r'(Enterprise|Professional|Standard|Community)',
            r'(Private\s+Edition|Public\s+Edition)',
            r'(Hosted|Self-Hosted|SaaS)',
        ]

        logger.info("[ContextExtractor] Initialized with heuristic + LLM extraction")

    def extract(
        self,
        document_title: str,
        document_text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        use_llm: bool = True
    ) -> DocumentContext:
        """
        Extrait contextes d'un document.

        Args:
            document_title: Titre du document
            document_text: Texte complet (optionnel, premiers 1000 chars suffisent)
            metadata: Métadonnées existantes (optionnel)
            use_llm: Utiliser LLM si heuristiques insuffisantes

        Returns:
            DocumentContext avec tous les contextes détectés

        Example:
            >>> extractor = DocumentContextExtractor(llm_router)
            >>> ctx = extractor.extract("S/4HANA 2025 Cloud Private - Security Guide")
            >>> ctx.version
            "2025"
            >>> ctx.edition
            "Cloud Private"
            >>> ctx.use_case
            "Security"
        """
        logger.debug(f"[ContextExtractor] Extracting context from: '{document_title[:100]}'")

        # 1. Extraction heuristique (rapide, pas de coût LLM)
        heuristic_context = self._extract_heuristic(document_title, document_text, metadata)

        # 2. Si heuristiques insuffisantes ET LLM disponible → extraction LLM
        if use_llm and self.llm_router and heuristic_context.confidence < 0.7:
            logger.info(
                f"[ContextExtractor] Heuristic confidence low ({heuristic_context.confidence:.2f}), "
                f"using LLM extraction..."
            )
            llm_context = self._extract_llm(document_title, document_text)

            # Fusionner résultats (heuristique + LLM)
            return self._merge_contexts(heuristic_context, llm_context)

        return heuristic_context

    def _extract_heuristic(
        self,
        document_title: str,
        document_text: Optional[str],
        metadata: Optional[Dict[str, Any]]
    ) -> DocumentContext:
        """
        Extraction via patterns heuristiques universels.

        Rapide, gratuit, mais moins précis que LLM.
        """
        context = DocumentContext(
            extraction_method="heuristic",
            confidence=0.0
        )

        text_to_analyze = document_title
        if document_text:
            # Analyser premiers 500 chars pour contexte
            text_to_analyze += " " + document_text[:500]

        confidence_scores = []

        # 1. Détecter version
        version = self._extract_version_heuristic(text_to_analyze)
        if version:
            context.version = version
            confidence_scores.append(0.9)  # Haute confiance si pattern trouvé
        else:
            confidence_scores.append(0.3)  # Pas de version = probablement agnostic

        # 2. Détecter edition
        edition = self._extract_edition_heuristic(text_to_analyze)
        if edition:
            context.edition = edition
            confidence_scores.append(0.85)
        else:
            confidence_scores.append(0.5)

        # 3. Détecter use case (keywords simples)
        use_case = self._extract_use_case_heuristic(text_to_analyze)
        if use_case:
            context.use_case = use_case
            confidence_scores.append(0.7)
        else:
            confidence_scores.append(0.5)

        # 4. Déterminer si version-agnostic
        context.is_version_agnostic = (context.version is None)

        # Calculer confiance globale
        context.confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0

        logger.debug(
            f"[ContextExtractor:Heuristic] Extracted: version={context.version}, "
            f"edition={context.edition}, use_case={context.use_case}, "
            f"confidence={context.confidence:.2f}"
        )

        return context

    def _extract_version_heuristic(self, text: str) -> Optional[str]:
        """Extrait version via patterns regex."""
        for pattern in self.version_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                version = match.group(1)
                logger.debug(f"[ContextExtractor] Version detected: '{version}' (pattern: {pattern})")
                return version
        return None

    def _extract_edition_heuristic(self, text: str) -> Optional[str]:
        """Extrait edition via patterns regex."""
        for pattern in self.edition_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                edition = match.group(1)
                logger.debug(f"[ContextExtractor] Edition detected: '{edition}' (pattern: {pattern})")
                return edition
        return None

    def _extract_use_case_heuristic(self, text: str) -> Optional[str]:
        """Extrait use case via keywords."""
        use_case_keywords = {
            "Security": ["security", "secure", "authentication", "authorization", "encryption"],
            "Integration": ["integration", "api", "connector", "interface"],
            "Migration": ["migration", "upgrade", "transition"],
            "Configuration": ["configuration", "setup", "settings", "admin"],
            "Development": ["development", "coding", "programming", "sdk"],
            "Operations": ["operations", "monitoring", "maintenance", "ops"],
        }

        text_lower = text.lower()

        for use_case, keywords in use_case_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                logger.debug(f"[ContextExtractor] Use case detected: '{use_case}'")
                return use_case

        return None

    def _extract_llm(
        self,
        document_title: str,
        document_text: Optional[str]
    ) -> DocumentContext:
        """
        Extraction via LLM pour cas complexes.

        Utilise prompt universel pour extraction multi-domaine.
        """
        if not self.llm_router:
            logger.warning("[ContextExtractor:LLM] No LLM router available, returning empty context")
            return DocumentContext(extraction_method="llm_unavailable")

        # Construire prompt universel
        text_sample = document_text[:1000] if document_text else ""

        prompt = self._build_llm_extraction_prompt(document_title, text_sample)

        try:
            from knowbase.common.llm_router import TaskType

            response = self.llm_router.complete(
                task_type=TaskType.CANONICALIZATION,  # Réutilise task type existant
                messages=[
                    {"role": "system", "content": CONTEXT_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            # Parse JSON response
            result = json.loads(response)

            context = DocumentContext(
                version=result.get("version"),
                edition=result.get("edition"),
                industry=result.get("industry"),
                use_case=result.get("use_case"),
                temporal_scope=result.get("temporal_scope"),
                geographic_scope=result.get("geographic_scope"),
                confidence=result.get("confidence", 0.8),
                is_version_agnostic=result.get("is_version_agnostic", False),
                extraction_method="llm",
                metadata=result.get("metadata", {})
            )

            logger.info(
                f"[ContextExtractor:LLM] Extracted: version={context.version}, "
                f"edition={context.edition}, confidence={context.confidence:.2f}"
            )

            return context

        except Exception as e:
            logger.error(f"[ContextExtractor:LLM] Extraction failed: {e}")
            return DocumentContext(
                extraction_method="llm_error",
                confidence=0.0,
                metadata={"error": str(e)}
            )

    def _build_llm_extraction_prompt(self, title: str, text_sample: str) -> str:
        """Construit prompt LLM universel."""
        return f"""
# Document Context Extraction

**Document Title:** {title}

**Document Sample:** {text_sample[:500]}

---

**Task:** Extract contextual metadata from this document.

**Return JSON format matching this structure:**
- version: Product/software version (e.g., "2023", "2025", "Q2 2024") or null if version-agnostic
- edition: Deployment edition (e.g., "Cloud Private", "On-Premise", "SaaS") or null
- industry: Target industry (e.g., "Retail", "Healthcare") or null if generic
- use_case: Primary use case (e.g., "Security", "Integration") or null
- temporal_scope: Temporal period (e.g., "Q1 2024", "Spring 2025") or null
- geographic_scope: Geographic scope (e.g., "EU", "Global", "US") or null
- is_version_agnostic: true if document applies to all versions, false otherwise
- confidence: Confidence score 0.0-1.0
- metadata: {{}} Additional contextual info

**Important:** Be GENERIC - works for ANY industry (SAP, pharma, retail, etc.)
"""

    def _merge_contexts(
        self,
        heuristic: DocumentContext,
        llm: DocumentContext
    ) -> DocumentContext:
        """
        Fusionne résultats heuristiques et LLM.

        Priorité : LLM > Heuristic si confiance LLM > heuristic
        """
        if llm.confidence > heuristic.confidence:
            logger.debug(
                f"[ContextExtractor:Merge] Using LLM result (confidence {llm.confidence:.2f} > "
                f"{heuristic.confidence:.2f})"
            )
            return llm
        else:
            logger.debug(
                f"[ContextExtractor:Merge] Using Heuristic result (confidence {heuristic.confidence:.2f} >= "
                f"{llm.confidence:.2f})"
            )
            return heuristic


# ═══════════════════════════════════════════════════
# SYSTEM PROMPT LLM
# ═══════════════════════════════════════════════════

CONTEXT_EXTRACTION_SYSTEM_PROMPT = """You are a document context extraction expert.

Your task is to extract CONTEXTUAL METADATA from documents across ALL industries.

# Guidelines

1. **Version Detection**: Look for version numbers, release dates, quarters, etc.
   - Examples: "2023", "2025", "Q2 2024", "v1.5", "R12"
   - If no version found → set version=null and is_version_agnostic=true

2. **Edition Detection**: Look for deployment type, edition, tier
   - Examples: "Cloud Private", "On-Premise", "SaaS", "Enterprise", "Community"
   - Common patterns: "Private Edition", "Public Cloud", "Self-Hosted"

3. **Industry Detection**: Identify target industry if mentioned
   - Examples: "Retail", "Healthcare", "Manufacturing", "Finance"
   - Only set if explicitly mentioned, otherwise null

4. **Use Case Detection**: Identify primary topic/use case
   - Examples: "Security", "Integration", "Migration", "Configuration"
   - Extract from title or main themes

5. **Be UNIVERSAL**: Works for SAP, pharma, retail, fashion, legal, etc.

6. **Confidence Scoring**:
   - 0.9+: Explicitly stated in title
   - 0.7-0.9: Clear from context
   - 0.5-0.7: Inferred from keywords
   - < 0.5: Uncertain

# Output Format (JSON)

{
  "version": "2025" | null,
  "edition": "Cloud Private" | null,
  "industry": "Retail" | null,
  "use_case": "Security" | null,
  "temporal_scope": "Q1 2024" | null,
  "geographic_scope": "EU" | null,
  "is_version_agnostic": true | false,
  "confidence": 0.85,
  "metadata": {}
}

# Examples

## Example 1: SAP Document
Title: "S/4HANA 2025 Cloud Private - Security Guide"
→ {
  "version": "2025",
  "edition": "Cloud Private",
  "industry": null,
  "use_case": "Security",
  "temporal_scope": null,
  "geographic_scope": null,
  "is_version_agnostic": false,
  "confidence": 0.95,
  "metadata": {"product": "S/4HANA"}
}

## Example 2: Pharma Document
Title: "Clinical Trial Protocol - Phase III - EU Region"
→ {
  "version": "Phase III",
  "edition": null,
  "industry": "Healthcare",
  "use_case": "Clinical Trial",
  "temporal_scope": null,
  "geographic_scope": "EU",
  "is_version_agnostic": false,
  "confidence": 0.90,
  "metadata": {"trial_phase": "III"}
}

## Example 3: Fashion Document
Title: "Chanel Spring 2025 Collection - Ready-to-Wear"
→ {
  "version": null,
  "edition": "Ready-to-Wear",
  "industry": "Fashion",
  "use_case": null,
  "temporal_scope": "Spring 2025",
  "geographic_scope": null,
  "is_version_agnostic": false,
  "confidence": 0.88,
  "metadata": {"brand": "Chanel", "season": "Spring 2025"}
}

## Example 4: Generic Security Document
Title: "Best Practices for Cloud Security"
→ {
  "version": null,
  "edition": "Cloud",
  "industry": null,
  "use_case": "Security",
  "temporal_scope": null,
  "geographic_scope": null,
  "is_version_agnostic": true,
  "confidence": 0.75,
  "metadata": {}
}
"""
