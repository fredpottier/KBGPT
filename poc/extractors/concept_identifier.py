"""
Phase 1.2 - Identification des Concepts Situes

Extrait les concepts FRUGAUX du document en respectant:
- Maximum 60 concepts (coupe-circuit dur)
- Minimum 3 Information par concept
- Role: CENTRAL, CONTEXTUAL, STANDARD
"""

import json
import re
from typing import Dict, List, Optional
from pathlib import Path

from poc.models.schemas import (
    ConceptSitue,
    ConceptRole,
    RefusedTerm,
    ConceptExtractionResult,
    Theme
)
from poc.validators.frugality_guard import FrugalityGuard, FrugalityStatus
from poc.validators.concept_quality_validator import ConceptQualityValidator
from poc.validators.refusal_rate_validator import RefusalRateValidator, DocumentComplexity


class ConceptIdentifier:
    """
    Identifie les concepts situes d'un document.
    Applique les regles de frugalite STRICTES.

    IMPORTANT: Pas de fallback silencieux - si pas de LLM, erreur explicite.
    """

    def __init__(self, llm_client=None, prompts_path: Optional[Path] = None, allow_fallback: bool = False):
        """
        Args:
            llm_client: Client LLM (QwenClient ou mock)
            prompts_path: Chemin vers poc_prompts.yaml
            allow_fallback: Si True, autorise le fallback heuristique (mode test uniquement)
        """
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)
        self.frugality_guard = FrugalityGuard()
        self.concept_quality_validator = ConceptQualityValidator()
        self.refusal_rate_validator = RefusalRateValidator()
        self.allow_fallback = allow_fallback

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML"""
        import yaml

        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "poc_prompts.yaml"

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def identify(
        self,
        subject: str,
        structure: str,
        themes: List[Theme],
        content: str,
        doc_type: str = "NORMAL",
        language: str = "en"
    ) -> ConceptExtractionResult:
        """
        Identifie les concepts situes du document.

        Args:
            subject: Sujet du document (de Phase 1.1)
            structure: Structure de dependance (CENTRAL, TRANSVERSAL, CONTEXTUAL)
            themes: Hierarchie thematique (de Phase 1.1)
            content: Contenu textuel complet
            doc_type: Type de document (NORMAL, HOSTILE)
            language: Langue du document (en, fr, de)

        Returns:
            ConceptExtractionResult avec concepts et termes refuses
        """
        # Construire le prompt
        prompt_config = self.prompts.get("concept_identification", {})
        system_prompt = prompt_config.get("system", "")
        user_template = prompt_config.get("user", "")

        themes_str = self._format_themes(themes)

        # Format user prompt avec langue si template v2
        try:
            user_prompt = user_template.format(
                subject=subject,
                structure=structure,
                themes=themes_str,
                content=content[:5000],  # Reduit pour contexte 8k
                language=language
            )
        except KeyError:
            # Template v1 sans {language}
            user_prompt = user_template.format(
                subject=subject,
                structure=structure,
                themes=themes_str,
                content=content[:5000]
            )

        # Appeler le LLM - PAS DE FALLBACK SILENCIEUX
        if self.llm_client:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2500  # Augmenté pour éviter JSON tronqué
            )
            result = self._parse_response(response)
        elif self.allow_fallback:
            # Mode test uniquement - fallback explicitement autorisé
            print("[WARN] Mode fallback activé - résultats non fiables")
            result = self._fallback_identification(subject, themes, content)
        else:
            # PAS DE FALLBACK - erreur explicite
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        # GARDE-FOU 1: Filtrage qualité conceptuelle (anti-bruit)
        valid_concepts = []
        noise_rejected = []
        for concept in result.concepts:
            quality_result = self.concept_quality_validator.validate_concept(
                concept.name, concept.role.value
            )
            if quality_result.is_valid:
                valid_concepts.append(concept)
            else:
                # Ajouter aux refusés avec la raison
                noise_rejected.append(RefusedTerm(
                    term=concept.name,
                    reason=f"[BRUIT] {quality_result.reason}"
                ))

        # Mettre à jour le résultat
        result.concepts = valid_concepts
        result.refused_terms.extend(noise_rejected)
        result.concept_count = len(valid_concepts)

        # GARDE-FOU 2: Frugalité (max 60 concepts)
        frugality_result = self.frugality_guard.validate(result.concepts, doc_type)
        if frugality_result.status == FrugalityStatus.FAIL:
            raise ValueError(frugality_result.message)

        # GARDE-FOU 3: Taux de refus (anti-sur-structuration)
        doc_complexity = self.refusal_rate_validator.detect_document_complexity(
            structure, subject
        )
        refusal_result = self.refusal_rate_validator.validate(
            concept_count=len(result.concepts),
            refusal_count=len(result.refused_terms),
            doc_complexity=doc_complexity
        )
        if not refusal_result.is_valid:
            print(f"[WARN] {refusal_result.message}")
            # Warning, pas erreur - mais signal important

        return result

    def _format_themes(self, themes: List[Theme]) -> str:
        """Formate les themes pour le prompt"""
        lines = []
        for theme in themes:
            lines.append(f"- {theme.name}")
            for child in theme.children:
                lines.append(f"  - {child.name}")
        return '\n'.join(lines)

    def _parse_response(self, response: str) -> ConceptExtractionResult:
        """Parse la reponse JSON du LLM"""
        # Extraire le JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            return self._validate_and_convert(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Reponse LLM invalide: {e}\nReponse: {response[:500]}")

    def _validate_and_convert(self, data: Dict) -> ConceptExtractionResult:
        """Valide et convertit la reponse en objets Pydantic"""
        concepts = []
        for c_data in data.get("concepts", []):
            role_str = c_data.get("role", "STANDARD")
            try:
                role = ConceptRole(role_str)
            except ValueError:
                role = ConceptRole.STANDARD

            concept = ConceptSitue(
                name=c_data.get("name", ""),
                role=role,
                theme_ref=c_data.get("theme", ""),
            )
            concepts.append(concept)

        refused_terms = []
        for r_data in data.get("refused_terms", []):
            refused = RefusedTerm(
                term=r_data.get("term", ""),
                reason=r_data.get("reason", "Non specifie")
            )
            refused_terms.append(refused)

        return ConceptExtractionResult(
            concepts=concepts,
            refused_terms=refused_terms
        )

    def _fallback_identification(
        self,
        subject: str,
        themes: List[Theme],
        content: str
    ) -> ConceptExtractionResult:
        """
        Identification de secours sans LLM.
        Utilise extraction de termes frequents.
        """
        # Extraction naive basee sur la frequence
        words = re.findall(r'\b[A-Z][a-zA-Z]{3,}\b', content)
        word_freq = {}
        for word in words:
            word_lower = word.lower()
            if word_lower not in ['this', 'that', 'with', 'from', 'have', 'been']:
                word_freq[word] = word_freq.get(word, 0) + 1

        # Garder les top 20 termes (frugalite)
        sorted_terms = sorted(word_freq.items(), key=lambda x: -x[1])[:20]

        concepts = []
        for i, (term, freq) in enumerate(sorted_terms):
            role = ConceptRole.STANDARD
            if i == 0:
                role = ConceptRole.CENTRAL

            concept = ConceptSitue(
                name=term,
                role=role,
                theme_ref=themes[0].name if themes else "General"
            )
            concepts.append(concept)

        # Termes refuses (les moins frequents)
        refused = [
            RefusedTerm(term=t, reason=f"Frequence trop faible ({f})")
            for t, f in sorted_terms[20:30]
        ] if len(sorted_terms) > 20 else []

        return ConceptExtractionResult(
            concepts=concepts,
            refused_terms=refused
        )

    def assign_concept_to_theme(
        self,
        concept_name: str,
        themes: List[Theme],
        content: str
    ) -> str:
        """
        Assigne un concept au theme le plus pertinent.
        Heuristique basee sur la co-occurrence.
        """
        # Chercher dans quel theme le concept apparait le plus
        best_theme = themes[0].name if themes else "General"
        best_score = 0

        for theme in themes:
            # Compter co-occurrences concept + theme name
            pattern = rf'{re.escape(concept_name)}.*{re.escape(theme.name)}|{re.escape(theme.name)}.*{re.escape(concept_name)}'
            matches = len(re.findall(pattern, content, re.IGNORECASE))
            if matches > best_score:
                best_score = matches
                best_theme = theme.name

        return best_theme
