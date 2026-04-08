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
        domain_packs: Optional[List[Any]] = None,
    ):
        """
        Initialise le resolver v2.

        Args:
            tenant_id: Tenant ID
            llm_client: Client LLM (optionnel, utilise LLMRouter si None)
            domain_packs: Liste de DomainPack explicites (optionnel, pour tests).
                Si None, charges automatiquement via le registry en utilisant
                tenant_id.
        """
        self.tenant_id = tenant_id
        self._llm_client = llm_client
        self._explicit_packs = domain_packs

        # Gazetteer agrege (cache lazy — voir _get_gazetteer_context)
        self._gazetteer_cache: Optional[Dict[str, Any]] = None

        # Stats
        self._stats = {
            "calls": 0,
            "successes": 0,
            "abstentions": 0,
            "parse_errors": 0,
            "validation_errors": 0,
        }

    def _get_gazetteer_context(self) -> Dict[str, Any]:
        """Retourne le gazetteer agrege des domain packs actifs (avec cache).

        Charge lazily au premier appel. Agrège tous les active_packs du tenant
        (ou les packs explicites fournis au constructor) et construit :
        - products : liste unique de canonicals, triee par longueur croissante
          (les plus courts en premier pour que le LLM prefere les parents
          hierarchiques quand plusieurs matchent)
        - aliases : dict fusionne de tous les canonical_aliases des packs

        Returns:
            dict {"products": list[str], "aliases": dict[str, str]}.
            Dict vide si aucun pack n'a de gazetteer.
        """
        if self._gazetteer_cache is not None:
            return self._gazetteer_cache

        # Charger les packs actifs
        packs = self._explicit_packs
        if packs is None:
            try:
                from knowbase.domain_packs.registry import get_pack_registry
                registry = get_pack_registry()
                packs = registry.get_active_packs(self.tenant_id) or []
            except Exception as e:
                logger.warning(
                    f"[SubjectResolverV2] Could not load domain packs: {e} — "
                    f"resolver will run without gazetteer context"
                )
                self._gazetteer_cache = {"products": [], "aliases": {}}
                return self._gazetteer_cache

        # Agreger
        products_set: Dict[str, None] = {}  # ordered dict for unique + stable order
        aliases: Dict[str, str] = {}
        for pack in packs:
            try:
                gaz = pack.get_product_gazetteer()
                for item in gaz:
                    products_set[item] = None
                aliases.update(pack.get_canonical_aliases())
            except Exception as e:
                logger.warning(
                    f"[SubjectResolverV2] Error reading gazetteer from pack "
                    f"{getattr(pack, 'name', '?')}: {e}"
                )
                continue

        # Exclure de la liste des canonicals injectes au LLM les entrees qui
        # sont en fait des alias connus (apparaissent comme cles dans
        # canonical_aliases). Ces entrees ne doivent pas etre proposees comme
        # canonical final — elles doivent etre resolues vers leur canonical
        # cible via le post-processing. Defensive strategy pour gerer les
        # incoherences dans context_defaults.json (ex: "RISE with SAP" present
        # a la fois dans product_gazetteer et dans canonical_aliases).
        alias_keys_lower = {k.lower() for k in aliases.keys()}
        n_before = len(products_set)
        products_set = {
            p: None for p in products_set
            if p.lower() not in alias_keys_lower
        }
        n_removed = n_before - len(products_set)
        if n_removed > 0:
            logger.debug(
                f"[SubjectResolverV2] Removed {n_removed} alias entries from "
                f"canonicals list (they will be resolved via post-processing)"
            )

        # Trier par longueur croissante (parents hierarchiques en premier)
        products_list = sorted(products_set.keys(), key=lambda s: (len(s), s))

        self._gazetteer_cache = {
            "products": products_list,
            "aliases": aliases,
        }
        if products_list:
            logger.info(
                f"[SubjectResolverV2] Gazetteer loaded : {len(products_list)} "
                f"canonical products, {len(aliases)} aliases (tenant={self.tenant_id})"
            )
        return self._gazetteer_cache

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

        # Post-processing : resoudre les alias connus vers leurs canonicals
        # (defensive : si le LLM retourne un alias comme label de subject, on
        # le remplace par la forme canonique finale)
        resolver_output = self._apply_canonical_aliases(resolver_output)

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
        base_prompt = USER_PROMPT_TEMPLATE.format(
            filename=filename,
            title=title,
            header_snippets_json=json.dumps(header_snippets, ensure_ascii=False),
            cover_snippets_json=json.dumps(cover_snippets, ensure_ascii=False),
            global_view_excerpt=global_view_excerpt,
            candidates_json=json.dumps(candidates, ensure_ascii=False),
        )

        # Injection du gazetteer du domaine (domain pack actif) en section USER
        # (pas system — le prompt system reste domain-agnostic par construction).
        # Le LLM recoit une liste de canonicals connus et doit preferer ceux-ci
        # quand ils matchent. Le gazetteer est PRE-FILTRE sur la pertinence au
        # document courant pour eviter un prompt geant et biaiser correctement
        # le LLM vers les canonicals qui ont une chance de matcher.
        document_context = self._build_relevance_context(
            candidates=candidates,
            filename=filename,
            title=title,
            header_snippets=header_snippets,
            cover_snippets=cover_snippets,
            global_view_excerpt=global_view_excerpt,
        )
        gazetteer_section = self._build_gazetteer_section(document_context)
        if gazetteer_section:
            return base_prompt + "\n\n" + gazetteer_section
        return base_prompt

    def _build_relevance_context(
        self,
        candidates: List[str],
        filename: str,
        title: str,
        header_snippets: List[str],
        cover_snippets: List[str],
        global_view_excerpt: str,
    ) -> str:
        """Concatene tout le contexte textuel disponible pour filtrage lexical.

        Utilise pour pre-filtrer le gazetteer : ne garder que les canonicals
        dont au moins une partie significative apparait dans ce contexte.
        """
        parts = [filename, title]
        parts.extend(candidates)
        parts.extend(header_snippets)
        parts.extend(cover_snippets)
        if global_view_excerpt:
            parts.append(global_view_excerpt[:2000])
        return " ".join(str(p) for p in parts if p).lower()

    @staticmethod
    def _canonical_matches_context(canonical: str, context_lower: str) -> bool:
        """Teste si un canonical est pertinent pour le document courant.

        Un canonical est pertinent si tous ses mots significatifs (>=3 chars,
        non-stopword) apparaissent dans le contexte. C'est volontairement
        permissif : on prefere inclure trop plutot que rater un match.
        """
        # Mots significatifs du canonical (on ignore les mots courts)
        STOPWORDS = {"sap", "the", "and", "for", "with", "in", "of", "on", "to", "a", "an"}
        words = [w for w in re.split(r"[\s\-_/]+", canonical.lower()) if len(w) >= 3]
        if not words:
            return False
        # Retirer les stopwords, mais si tous les mots sont des stopwords,
        # on garde le canonical tel quel (ex: "SAP FI" => ["sap", "fi"], tous
        # filtrés, on test alors la chaine entiere)
        significant = [w for w in words if w not in STOPWORDS]
        if not significant:
            # Tous stopwords — test la chaine complete (ex: "SAP FI")
            return canonical.lower() in context_lower
        # Tous les mots significatifs doivent apparaitre dans le contexte
        return all(w in context_lower for w in significant)

    def _build_gazetteer_section(self, document_context: str = "") -> str:
        """Construit la section `KNOWN CANONICAL ENTITIES` a ajouter au user prompt.

        Filtre le gazetteer pour ne garder que les canonicals pertinents pour
        le document courant (au moins un mot significatif present dans le
        contexte textuel du document). Cela evite un prompt geant et biaise
        correctement le LLM vers les canonicals qui ont une chance de matcher.

        Retourne une chaine vide si :
        - aucun pack actif n'a de gazetteer
        - aucun canonical ne matche le contexte du document
        """
        ctx = self._get_gazetteer_context()
        products = ctx.get("products", [])
        aliases = ctx.get("aliases", {})

        if not products:
            return ""

        # Pre-filtrage par pertinence lexicale
        if document_context:
            relevant = [p for p in products if self._canonical_matches_context(p, document_context)]
        else:
            relevant = products

        if not relevant:
            logger.debug(
                "[SubjectResolverV2] No relevant canonical matches document context, "
                "falling back to top 50 shortest canonicals"
            )
            relevant = products[:50]

        # Cap final pour protection : 80 canonicals max injectes
        MAX_PRODUCTS = 80
        products_display = relevant[:MAX_PRODUCTS]
        truncated_note = ""
        if len(relevant) > MAX_PRODUCTS:
            truncated_note = f"\n(+ {len(relevant) - MAX_PRODUCTS} other relevant canonicals not shown)"

        products_lines = "\n".join(f"- {p}" for p in products_display)

        # Alias : inclure seulement ceux dont la valeur (canonical) est dans
        # les relevants ou dont la cle (alias) apparait dans le contexte
        relevant_aliases = {}
        if aliases:
            relevant_canonicals_set = set(products_display)
            for alias, canonical in aliases.items():
                if canonical in relevant_canonicals_set:
                    relevant_aliases[alias] = canonical
                elif document_context and alias.lower() in document_context:
                    relevant_aliases[alias] = canonical

        aliases_text = ""
        if relevant_aliases:
            MAX_ALIASES = 30
            alias_lines = "\n".join(
                f"- {alias} -> {canonical}"
                for alias, canonical in list(relevant_aliases.items())[:MAX_ALIASES]
            )
            aliases_text = f"\n\nRelevant alias mapping (use them to resolve variants to their canonical form):\n{alias_lines}"

        section = f"""KNOWN CANONICAL ENTITIES IN THIS DOMAIN (filtered to those relevant to this document):
The following is a catalogue of canonical entities known in the current
domain, pre-filtered to keep only those that share keywords with the
document context. When a candidate in the input MATCHES one of these
canonicals (exactly, via an alias, or as a superstring/substring), you
SHOULD use the catalogue canonical as the label of the COMPARABLE_SUBJECT
rather than inventing a new one.

When multiple canonicals match, prefer the SHORTEST one (which is typically
the parent in a hierarchy). For example, if the document is a general
guide discussing "Product X" but mentions a deployment variant like
"Product X Cloud Edition" in passing, the subject is "Product X", not the
variant. The variant should be classified as an AXIS_VALUE with role
`applicability_scope` or `revision`.

Relevant canonicals for this document (sorted shortest first):
{products_lines}{truncated_note}{aliases_text}

IMPORTANT :
- This catalogue is advisory, not mandatory. If no canonical clearly fits
  the document, fall back to the standard decomposition rules.
- Deployment variants, editions, sub-products are AXIS_VALUES, not
  subjects — the subject is the parent product they belong to.
- Always cite your decision via evidence from the document (title,
  filename, headers) as usual, whether or not you use a catalogue canonical.
"""
        return section

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

    def _apply_canonical_aliases(
        self,
        resolver_output: SubjectResolverOutput,
    ) -> SubjectResolverOutput:
        """Resolu les alias du gazetteer vers leurs canonicals finaux.

        Defensive post-processing : si le LLM retourne un label qui est en
        realite un alias connu (present dans canonical_aliases), on le remplace
        par la forme canonique finale. Exemple : "RISE with SAP" ->
        "SAP S/4HANA Cloud Private Edition".

        Cette normalisation est appliquee au comparable_subject uniquement
        (pas aux axis_values, qui peuvent legitimement contenir des variantes).

        Matching case-insensitive pour robustesse.
        """
        if resolver_output is None or resolver_output.comparable_subject is None:
            return resolver_output

        ctx = self._get_gazetteer_context()
        aliases = ctx.get("aliases", {})
        if not aliases:
            return resolver_output

        # Index case-insensitive pour lookup
        aliases_ci = {k.lower(): v for k, v in aliases.items()}

        current_label = resolver_output.comparable_subject.label or ""
        resolved = aliases_ci.get(current_label.lower())
        if resolved and resolved != current_label:
            logger.info(
                f"[SubjectResolverV2] Alias resolution : '{current_label}' -> '{resolved}'"
            )
            # Pydantic model : on doit creer une nouvelle instance avec le label mis a jour
            from knowbase.claimfirst.models.subject_resolver_output import (
                ComparableSubjectOutput,
            )
            new_cs = ComparableSubjectOutput(
                label=resolved,
                confidence=resolver_output.comparable_subject.confidence,
                rationale=(
                    f"[alias resolved from '{current_label}'] "
                    + (resolver_output.comparable_subject.rationale or "")
                )[:240],
                support=resolver_output.comparable_subject.support,
            )
            resolver_output.comparable_subject = new_cs

        return resolver_output

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
