# src/knowbase/claimfirst/resolution/subject_resolver_v2.py
"""
SubjectResolver v2 - Résolution domain-agnostic du sujet comparable.

INV-25: Domain-agnostic strict - aucun vocabulaire IT/SAP.

Ce resolver utilise un prompt contractuel pour classifier les candidats
extraits d'un document en:
- COMPARABLE_SUBJECT: sujet stable comparable entre documents
- AXIS_VALUE: valeur discriminante avec rôle (temporal, geographic, etc.)
- DOC_TYPE: type/genre documentaire
- NOISE: bruit à ignorer

Le prompt contractuel garantit:
- Aucune connaissance externe (domain-agnostic)
- Evidence-locked: chaque décision est justifiée par des citations
- Conservatisme: préférer NOISE ou "unknown" plutôt que deviner
- Test de stabilité: le sujet doit rester identique si le doc est révisé
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from knowbase.claimfirst.models.comparable_subject import ComparableSubject
from knowbase.claimfirst.models.subject_resolver_output import (
    DiscriminatingRole,
    SubjectResolverOutput,
    AbstainInfo,
)
from knowbase.ontology.domain_context_injector import get_domain_context_injector

logger = logging.getLogger(__name__)


# ============================================================================
# PROMPT CONTRACTUEL v2.1 - Knowledge-Informed Classification
# ============================================================================

SYSTEM_PROMPT_V2 = """You are an expert CLASSIFIER responsible for identifying the MAIN SUBJECT
of a document and separating it from contextual discriminators.

YOU MAY USE YOUR GENERAL KNOWLEDGE to understand what candidates represent.
However, every classification decision MUST be justified with evidence from the provided text.

────────────────────────────────────────
CLASSIFICATION CATEGORIES
────────────────────────────────────────

(A) COMPARABLE_SUBJECT
    The core entity that this document is fundamentally ABOUT.

    Key test: If someone created another document about the SAME thing but for
    a different time period, version, or purpose, what would be the common denominator?

    Pattern: "[Core Entity]" not "[Core Entity] [Version] [Document Genre]"

    The subject is the THING being documented, not the document itself.

(B) AXIS_VALUE
    A contextual discriminator that VARIES between documents about the SAME subject.
    These help distinguish THIS document from OTHER documents about the same subject.

    Discriminating roles (use your knowledge to identify which applies):
    - temporal: dates, years, quarters, periods
    - revision: version numbers, release identifiers, edition markers
    - geographic: regions, countries, jurisdictions
    - status: lifecycle states, approval stages, phases
    - applicability_scope: target audience, market segment, use case

(C) DOC_TYPE
    The genre, format, or purpose of the document - WHAT KIND of document it is.

    Use your knowledge to recognize document genres (guides, reports, specifications,
    notes, manuals, summaries, analyses, etc.)

(D) NOISE
    Anything that doesn't clearly fit the above categories, or is too specific/generic
    to be useful for document comparison.

────────────────────────────────────────
CRITICAL RULES
────────────────────────────────────────

1. DECOMPOSE COMPOSITE CANDIDATES
   When a candidate combines multiple concepts, use your knowledge to decompose it.
   A string like "[Entity] [Version/Date] [DocumentType]" should be split into:
   - subject = the core entity (THE THING, not the document about it)
   - axis_value = the version, date, or other discriminator
   - doc_type = the document genre

   DECOMPOSITION EXAMPLES (domain-agnostic):
   - "Product X Release 2023 User Guide" → subject="Product X", axis="2023", doc_type="User Guide"
   - "Platform Y Business Scope v5.0" → subject="Platform Y", axis="v5.0", doc_type="Business Scope"
   - "Framework Z Feature Description Q3" → subject="Framework Z", axis="Q3", doc_type="Feature Description"
   - "Tool ABC 1809 Technical Overview" → subject="Tool ABC", axis="1809", doc_type="Technical Overview"

   CRITICAL: Terms like "Business Scope", "Feature Description", "User Guide", "Technical Overview",
   "Release Notes", "Administration Guide" are ALWAYS doc_type, NEVER part of the subject.

2. SUBJECT STABILITY TEST
   Ask: "If this document were updated next year, what part would stay the same?"
   - The STABLE part is the COMPARABLE_SUBJECT
   - The part that would CHANGE is an AXIS_VALUE

3. EVIDENCE LOCKING
   Every decision MUST cite evidence from the provided sources (title, filename, headers, etc.).
   If you cannot find textual evidence, classify as NOISE or ABSTAIN.

4. INTEGRAL vs DISCRIMINATING
   Use your knowledge to distinguish:
   - Identifiers that are INTEGRAL to the subject identity (keep them in subject)
   - Identifiers that DISCRIMINATE between documents (extract as axis_value)

   Rule of thumb: If removing the identifier changes WHAT is being discussed, it's integral.
   If removing it only changes WHICH VERSION/EDITION, it's discriminating.

5. WHEN IN DOUBT
   - Prefer NOISE over wrong classification
   - If confidence < 0.70 for COMPARABLE_SUBJECT, ABSTAIN
   - It's better to have no subject than a wrong subject

────────────────────────────────────────
OUTPUT REQUIREMENTS
────────────────────────────────────────

- There MUST be exactly ONE COMPARABLE_SUBJECT (the decomposed core entity), or ABSTAIN
- Extract ALL relevant AXIS_VALUES from composite candidates
- Identify DOC_TYPE if discernible, otherwise "unknown"
- Every input candidate MUST appear in classified_candidates
- Output ONLY valid JSON, no markdown or explanations"""


USER_PROMPT_TEMPLATE = """INPUT SOURCES:
- filename: "{filename}"
- title: "{title}"
- header_snippets: {header_snippets_json}
- cover_snippets: {cover_snippets_json}
- global_view_excerpt: "{global_view_excerpt}"

CANDIDATES (strings extracted deterministically):
{candidates_json}

TASK:
1) Identify the single COMPARABLE_SUBJECT (or abstain).
2) Identify AXIS_VALUE entries and describe their DISCRIMINATING ROLE
   (choose from: temporal, geographic, revision, applicability_scope, status, unknown).
3) Identify the DOC_TYPE (or "unknown").
4) Classify all candidates accordingly.

Return JSON strictly following this schema:
{{
  "resolver_version": "subject_resolver_v2.0",
  "comparable_subject": {{
    "label": "string",
    "confidence": 0.0,
    "rationale": "string (<= 240 chars)",
    "support": {{
      "signals": ["string"],
      "evidence_spans": [
        {{"source": "title|filename|header|cover|global_view", "quote": "string"}}
      ]
    }}
  }},
  "axis_values": [
    {{
      "value_raw": "string",
      "discriminating_role": "temporal|geographic|revision|applicability_scope|status|unknown",
      "confidence": 0.0,
      "rationale": "string (<= 240 chars)",
      "support": {{
        "signals": ["string"],
        "evidence_spans": [
          {{"source": "title|filename|header|cover|global_view", "quote": "string"}}
        ]
      }}
    }}
  ],
  "doc_type": {{
    "label": "string",
    "confidence": 0.0,
    "rationale": "string (<= 240 chars)",
    "support": {{
      "evidence_spans": [
        {{"source": "title|filename|header|cover|global_view", "quote": "string"}}
      ]
    }}
  }},
  "classified_candidates": [
    {{
      "candidate": "string",
      "class": "COMPARABLE_SUBJECT|AXIS_VALUE|DOC_TYPE|NOISE",
      "mapped_to": "comparable_subject|axis_values[0]|doc_type|none",
      "confidence": 0.0,
      "reason": "string (<= 160 chars)"
    }}
  ],
  "abstain": {{
    "must_abstain": false,
    "reason": "string"
  }}
}}

Return ONLY the JSON, no other text."""


class SubjectResolverV2:
    """
    SubjectResolver v2 - Domain-agnostic subject resolution.

    Utilise un prompt contractuel pour classifier les candidats extraits
    en COMPARABLE_SUBJECT, AXIS_VALUE, DOC_TYPE ou NOISE.

    Attributes:
        tenant_id: Tenant multi-locataire
    """

    def __init__(
        self,
        tenant_id: str = "default",
        llm_client: Any = None,
    ):
        """
        Initialise le resolver v2.

        Args:
            tenant_id: Tenant ID
            llm_client: Client LLM (optionnel, utilise LLMRouter si None)
        """
        self.tenant_id = tenant_id
        self._llm_client = llm_client

        # Stats
        self._stats = {
            "calls": 0,
            "successes": 0,
            "abstentions": 0,
            "parse_errors": 0,
            "validation_errors": 0,
        }

    def resolve(
        self,
        candidates: List[str],
        filename: str = "",
        title: str = "",
        header_snippets: Optional[List[str]] = None,
        cover_snippets: Optional[List[str]] = None,
        global_view_excerpt: str = "",
    ) -> Tuple[Optional[SubjectResolverOutput], Optional[ComparableSubject]]:
        """
        Résout les candidats en ComparableSubject + AxisValues + DocType.

        Args:
            candidates: Liste de candidats extraits
            filename: Nom du fichier
            title: Titre du document
            header_snippets: Snippets d'en-têtes
            cover_snippets: Snippets de couverture
            global_view_excerpt: Extrait de la vue globale (<= 1200 chars)

        Returns:
            Tuple (SubjectResolverOutput, ComparableSubject ou None)
        """
        self._stats["calls"] += 1

        if not candidates:
            logger.warning("[SubjectResolverV2] No candidates provided")
            return SubjectResolverOutput.create_abstain("No candidates provided"), None

        # Construire le prompt user
        user_prompt = self._build_user_prompt(
            candidates=candidates,
            filename=filename,
            title=title,
            header_snippets=header_snippets or [],
            cover_snippets=cover_snippets or [],
            global_view_excerpt=global_view_excerpt[:1200] if global_view_excerpt else "",
        )

        # Appeler le LLM
        try:
            response_text = self._call_llm(SYSTEM_PROMPT_V2, user_prompt)
        except Exception as e:
            logger.error(f"[SubjectResolverV2] LLM call failed: {e}")
            return SubjectResolverOutput.create_abstain(f"LLM error: {e}"), None

        # Parser la réponse
        resolver_output = self._parse_response(response_text)
        if resolver_output is None:
            self._stats["parse_errors"] += 1
            return SubjectResolverOutput.create_abstain("Failed to parse LLM response"), None

        # Post-processing déterministe (règles DomainContext)
        resolver_output = self._apply_reclassification_rules(resolver_output, title)

        # Valider
        if not resolver_output.is_valid():
            self._stats["validation_errors"] += 1
            logger.warning("[SubjectResolverV2] Invalid resolver output")
            return SubjectResolverOutput.create_abstain("Invalid resolver output"), None

        # Vérifier abstention
        if resolver_output.abstain.must_abstain:
            self._stats["abstentions"] += 1
            logger.info(
                f"[SubjectResolverV2] Abstained: {resolver_output.abstain.reason}"
            )
            return resolver_output, None

        # Créer le ComparableSubject
        comparable_subject = None
        if resolver_output.comparable_subject:
            comparable_subject = ComparableSubject.create_new(
                tenant_id=self.tenant_id,
                canonical_name=resolver_output.comparable_subject.label,
                confidence=resolver_output.comparable_subject.confidence,
                rationale=resolver_output.comparable_subject.rationale,
            )
            self._stats["successes"] += 1
            logger.info(
                f"[SubjectResolverV2] Resolved: '{comparable_subject.canonical_name}' "
                f"(confidence={resolver_output.comparable_subject.confidence:.2f})"
            )

        return resolver_output, comparable_subject

    def _build_user_prompt(
        self,
        candidates: List[str],
        filename: str,
        title: str,
        header_snippets: List[str],
        cover_snippets: List[str],
        global_view_excerpt: str,
    ) -> str:
        """
        Construit le prompt utilisateur.

        Args:
            candidates: Candidats à classifier
            filename: Nom du fichier
            title: Titre du document
            header_snippets: Snippets d'en-têtes
            cover_snippets: Snippets de couverture
            global_view_excerpt: Extrait de la vue globale

        Returns:
            Prompt utilisateur formaté
        """
        return USER_PROMPT_TEMPLATE.format(
            filename=filename,
            title=title,
            header_snippets_json=json.dumps(header_snippets, ensure_ascii=False),
            cover_snippets_json=json.dumps(cover_snippets, ensure_ascii=False),
            global_view_excerpt=global_view_excerpt,
            candidates_json=json.dumps(candidates, ensure_ascii=False),
        )

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        Appelle le LLM via LLMRouter (supporte burst mode vLLM).

        Note: Ignore self._llm_client pour toujours utiliser LLMRouter,
        comme le fait ClaimExtractor. Cela garantit le support du burst mode.

        Le prompt système est enrichi avec le contexte métier du tenant via
        DomainContextInjector (domain-specific knowledge injection).

        Args:
            system_prompt: Prompt système (domain-agnostic)
            user_prompt: Prompt utilisateur

        Returns:
            Réponse textuelle du LLM
        """
        from knowbase.common.llm_router import get_llm_router, TaskType

        # Enrichir le prompt système avec le contexte métier du tenant
        injector = get_domain_context_injector()
        enriched_system_prompt = injector.inject_context(
            base_prompt=system_prompt,
            tenant_id=self.tenant_id,
        )

        router = get_llm_router()
        messages = [
            {"role": "system", "content": enriched_system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=0.1,
            max_tokens=1000,
        )
        return response

    def _parse_response(self, response_text: str) -> Optional[SubjectResolverOutput]:
        """
        Parse la réponse JSON du LLM.

        Args:
            response_text: Réponse textuelle du LLM

        Returns:
            SubjectResolverOutput ou None si parsing échoue
        """
        if not response_text:
            return None

        # Extraire le JSON (peut être entouré de texte)
        json_match = re.search(
            r'\{[\s\S]*"resolver_version"[\s\S]*\}',
            response_text,
            re.DOTALL,
        )

        if not json_match:
            logger.warning("[SubjectResolverV2] No JSON found in response")
            return None

        json_str = json_match.group(0)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"[SubjectResolverV2] JSON decode error: {e}")
            return None

        # Normaliser les données avant validation
        data = self._normalize_llm_response(data)

        try:
            return SubjectResolverOutput.model_validate(data)
        except ValidationError as e:
            logger.warning(f"[SubjectResolverV2] Validation error: {e}")
            return None

    def _normalize_llm_response(self, data: dict) -> dict:
        """
        Normalise la réponse LLM pour corriger les variantes courantes.

        Le LLM peut retourner des variantes comme "header_snippets" au lieu de "header",
        "headers" au lieu de "header", etc. Cette méthode normalise ces valeurs.

        Args:
            data: Données JSON brutes du LLM

        Returns:
            Données normalisées
        """
        # Mapping des variantes de source vers les valeurs canoniques
        source_mapping = {
            "header_snippets": "header",
            "headers": "header",
            "cover_snippets": "cover",
            "covers": "cover",
            "global_view_excerpt": "global_view",
            "globalview": "global_view",
            "file_name": "filename",
            "file": "filename",
            # Valeurs combinées - prendre la première
            "title|filename": "title",
            "filename|title": "filename",
            "title|header": "title",
            "header|title": "header",
            "cover|header": "cover",
            "header|cover": "header",
        }

        # Sources valides
        valid_sources = {"title", "filename", "header", "cover", "global_view"}

        def normalize_evidence_spans(obj):
            """Normalise récursivement les evidence_spans."""
            if isinstance(obj, dict):
                # Normaliser le champ "source" si présent
                if "source" in obj:
                    source_val = obj["source"]
                    # D'abord essayer le mapping direct
                    if source_val in source_mapping:
                        obj["source"] = source_mapping[source_val]
                    # Sinon, gérer les valeurs avec "|" (ex: "title|filename")
                    elif "|" in str(source_val):
                        parts = str(source_val).split("|")
                        for part in parts:
                            part = part.strip().lower()
                            if part in valid_sources:
                                obj["source"] = part
                                break
                            elif part in source_mapping:
                                obj["source"] = source_mapping[part]
                                break
                # Récursion
                for key, value in obj.items():
                    obj[key] = normalize_evidence_spans(value)
            elif isinstance(obj, list):
                return [normalize_evidence_spans(item) for item in obj]
            return obj

        return normalize_evidence_spans(data)

    def _apply_reclassification_rules(
        self,
        resolver_output: SubjectResolverOutput,
        title: str,
    ) -> SubjectResolverOutput:
        """Post-processing déterministe piloté par config DomainContext."""
        from knowbase.ontology.domain_context_store import get_domain_context_store

        store = get_domain_context_store()
        profile = store.get_profile(self.tenant_id)
        if not profile or not profile.axis_reclassification_rules:
            return resolver_output

        try:
            rules = json.loads(profile.axis_reclassification_rules)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "[SubjectResolverV2] Invalid JSON in axis_reclassification_rules, skipping"
            )
            return resolver_output
        if not isinstance(rules, list) or not rules:
            return resolver_output

        # Trier par priorité décroissante (plus haute priorité d'abord)
        rules.sort(key=lambda r: r.get("priority", 0), reverse=True)

        title_lower = title.lower() if title else ""
        for av in resolver_output.axis_values:
            for rule in rules:
                if self._rule_matches(av, rule, title_lower):
                    action = rule.get("action", {})
                    new_role_str = action.get("new_role")
                    if not new_role_str:
                        continue

                    try:
                        new_role = DiscriminatingRole(new_role_str)
                    except ValueError:
                        logger.warning(
                            f"[SubjectResolverV2] Invalid role '{new_role_str}' "
                            f"in rule '{rule.get('rule_id', '?')}', skipping"
                        )
                        continue

                    old_role = av.discriminating_role.value
                    av.discriminating_role = new_role
                    if "confidence_boost" in action:
                        av.confidence = min(1.0, av.confidence + action["confidence_boost"])
                    if "confidence_override" in action:
                        av.confidence = action["confidence_override"]
                    av.rationale = (
                        f"[Reclassified {old_role}\u2192{new_role_str} "
                        f"by rule '{rule.get('rule_id', '?')}'] {av.rationale}"
                    )
                    logger.debug(
                        f"[SubjectResolverV2] Reclassified '{av.value_raw}' "
                        f"{old_role}\u2192{new_role_str} (rule={rule.get('rule_id', '?')})"
                    )
                    break  # Première règle qui matche gagne

        return resolver_output

    def _rule_matches(self, av, rule: dict, title_lower: str) -> bool:
        """Évalue si une règle matche un axis_value. Toutes les conditions sont AND."""
        conditions = rule.get("conditions", {})
        if not conditions:
            return False

        # 1. value_pattern: regex sur value_raw
        if "value_pattern" in conditions:
            if not re.match(conditions["value_pattern"], av.value_raw):
                return False

        # 2. current_role: rôle actuel
        if "current_role" in conditions:
            if av.discriminating_role.value != conditions["current_role"]:
                return False

        # 3. title_contains_value: la valeur est dans le titre
        if conditions.get("title_contains_value"):
            if av.value_raw.lower() not in title_lower:
                return False

        # 4. title_context_pattern: regex sur le titre complet
        if "title_context_pattern" in conditions:
            if not re.search(conditions["title_context_pattern"], title_lower):
                return False

        # 5. evidence_quote_contains_any: citation structurée du LLM
        if "evidence_quote_contains_any" in conditions:
            keywords = conditions["evidence_quote_contains_any"]
            quotes = [
                span.quote.lower()
                for span in (av.support.evidence_spans if av.support else [])
            ]
            all_quotes = " ".join(quotes)
            if not any(kw.lower() in all_quotes for kw in keywords):
                return False

        # 6. rationale_contains_any: best-effort sur le rationale LLM
        if "rationale_contains_any" in conditions:
            rationale_lower = av.rationale.lower()
            if not any(kw.lower() in rationale_lower for kw in conditions["rationale_contains_any"]):
                return False

        return True

    def map_role_to_axis_key(self, role: DiscriminatingRole) -> str:
        """
        Mappe un DiscriminatingRole vers un axis_key neutre.

        Args:
            role: Rôle discriminant

        Returns:
            Clé d'axe neutre
        """
        mapping = {
            DiscriminatingRole.TEMPORAL: "temporal_marker",
            DiscriminatingRole.GEOGRAPHIC: "geographic_scope",
            DiscriminatingRole.REVISION: "revision_id",
            DiscriminatingRole.APPLICABILITY_SCOPE: "applicability_scope",
            DiscriminatingRole.STATUS: "status",
            DiscriminatingRole.UNKNOWN: "unknown",
        }
        return mapping.get(role, "unknown")

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        for key in self._stats:
            self._stats[key] = 0


__all__ = [
    "SubjectResolverV2",
    "SYSTEM_PROMPT_V2",
    "USER_PROMPT_TEMPLATE",
]
