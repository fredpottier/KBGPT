"""
OSMOSE Pipeline V2 - Phase 1.2 Concept Identifier
==================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Identification des concepts FRUGAUX:
- Maximum 15 concepts par document (garde-fou strict)
- Rôle: CENTRAL, STANDARD, CONTEXTUAL
- Rattachement aux thèmes

Adapté du POC: poc/extractors/concept_identifier.py
"""

import json
import re
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml

from knowbase.stratified.models import (
    Concept,
    ConceptRole,
    Theme,
)

logger = logging.getLogger(__name__)


class ConceptIdentifierV2:
    """
    Identificateur de concepts pour Pipeline V2.

    FRUGALITÉ STRICTE:
    - Maximum 15 concepts par document (invariant V2-007)
    - Minimum pertinence requis pour être retenu

    IMPORTANT: Pas de fallback silencieux - erreur explicite si LLM absent.
    """

    # Garde-fou frugalité (invariant V2-007)
    MAX_CONCEPTS = 15
    MAX_CONCEPTS_HOSTILE = 5  # Pour documents HOSTILE

    def __init__(
        self,
        llm_client=None,
        prompts_path: Optional[Path] = None,
        allow_fallback: bool = False
    ):
        """
        Args:
            llm_client: Client LLM compatible (generate method)
            prompts_path: Chemin vers prompts YAML
            allow_fallback: Si True, autorise le fallback heuristique (test only)
        """
        self.llm_client = llm_client
        self.prompts = self._load_prompts(prompts_path)
        self.allow_fallback = allow_fallback

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML."""
        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "pass1_prompts.yaml"

        if not prompts_path.exists():
            logger.warning(f"Prompts file not found: {prompts_path}")
            return self._default_prompts()

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _default_prompts(self) -> Dict:
        """Prompts par défaut si fichier absent."""
        return {
            "concept_identification": {
                "system": self._default_system_prompt(),
                "user": self._default_user_prompt()
            }
        }

    def identify(
        self,
        doc_id: str,
        subject_text: str,
        structure: str,
        themes: List[Theme],
        content: str,
        is_hostile: bool = False,
        language: str = "fr"
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Identifie les concepts situés du document.

        Args:
            doc_id: Identifiant du document
            subject_text: Texte du sujet (de Phase 1.1)
            structure: Structure (CENTRAL, TRANSVERSAL, CONTEXTUAL)
            themes: Thèmes identifiés (de Phase 1.1)
            content: Contenu textuel complet
            is_hostile: True si document HOSTILE (limite 5 concepts)
            language: Langue du document

        Returns:
            Tuple[List[Concept], List[Dict]]
            - concepts: Liste des concepts identifiés
            - refused_terms: Termes refusés avec raisons
        """
        max_concepts = self.MAX_CONCEPTS_HOSTILE if is_hostile else self.MAX_CONCEPTS

        # Construire le prompt
        prompt_config = self.prompts.get("concept_identification", {})
        system_prompt = prompt_config.get("system", self._default_system_prompt())
        user_template = prompt_config.get("user", self._default_user_prompt())

        themes_str = self._format_themes(themes)

        user_prompt = user_template.format(
            subject=subject_text,
            structure=structure,
            themes=themes_str,
            content=content[:5000],  # Limite pour contexte LLM
            language=language,
            max_concepts=max_concepts
        )

        # Appeler le LLM
        if self.llm_client:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2500
            )
            concepts, refused = self._parse_response(response, doc_id, themes)
        elif self.allow_fallback:
            logger.warning("[OSMOSE:Pass1:1.2] Mode fallback activé - résultats non fiables")
            concepts, refused = self._fallback_identification(doc_id, subject_text, themes, content)
        else:
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        # GARDE-FOU: Appliquer limite frugalité
        if len(concepts) > max_concepts:
            logger.warning(
                f"[OSMOSE:Pass1:1.2] Frugalité: {len(concepts)} concepts → {max_concepts}"
            )
            # Garder les CENTRAL d'abord, puis STANDARD, puis CONTEXTUAL
            concepts = self._apply_frugality(concepts, max_concepts)

        logger.info(
            f"[OSMOSE:Pass1:1.2] {len(concepts)} concepts identifiés, "
            f"{len(refused)} termes refusés"
        )

        return concepts, refused

    def _format_themes(self, themes: List[Theme]) -> str:
        """Formate les thèmes pour le prompt."""
        return '\n'.join(f"- {theme.name}" for theme in themes)

    def _parse_response(
        self,
        response: str,
        doc_id: str,
        themes: List[Theme]
    ) -> Tuple[List[Concept], List[Dict]]:
        """Parse la réponse JSON du LLM."""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            return self._validate_and_convert(data, doc_id, themes)
        except json.JSONDecodeError as e:
            logger.error(f"Réponse LLM invalide: {e}")
            raise ValueError(f"Réponse LLM invalide: {e}\nRéponse: {response[:500]}")

    def _validate_and_convert(
        self,
        data: Dict,
        doc_id: str,
        themes: List[Theme]
    ) -> Tuple[List[Concept], List[Dict]]:
        """Valide et convertit la réponse en objets Pydantic V2."""
        concepts = []
        theme_map = {t.name.lower(): t.theme_id for t in themes}

        for idx, c_data in enumerate(data.get("concepts", [])):
            # Mapper le rôle
            role_str = c_data.get("role", "STANDARD").upper()
            try:
                role = ConceptRole(role_str)
            except ValueError:
                role = ConceptRole.STANDARD

            # Trouver le theme_id correspondant
            theme_ref = c_data.get("theme", "")
            theme_id = theme_map.get(theme_ref.lower(), themes[0].theme_id if themes else "")

            # Générer lex_key (clé lexicale normalisée)
            name = c_data.get("name", f"Concept_{idx}")
            lex_key = self._generate_lex_key(name)

            concept = Concept(
                concept_id=f"concept_{doc_id}_{idx}",
                theme_id=theme_id,
                name=name,
                definition=c_data.get("definition"),  # Définition courte du concept
                role=role,
                variants=c_data.get("variants", []),
                lex_key=lex_key
            )
            concepts.append(concept)

        # Termes refusés
        refused = [
            {"term": r.get("term", ""), "reason": r.get("reason", "Non spécifié")}
            for r in data.get("refused_terms", [])
        ]

        return concepts, refused

    def _generate_lex_key(self, name: str) -> str:
        """Génère une clé lexicale normalisée."""
        # Normaliser: lowercase, remplacer espaces, supprimer accents simples
        lex = name.lower().strip()
        lex = re.sub(r'\s+', '_', lex)
        lex = re.sub(r'[^a-z0-9_]', '', lex)
        return lex

    def _apply_frugality(self, concepts: List[Concept], max_count: int) -> List[Concept]:
        """Applique la limite de frugalité en priorisant par rôle."""
        # Trier par rôle: CENTRAL > STANDARD > CONTEXTUAL
        role_order = {ConceptRole.CENTRAL: 0, ConceptRole.STANDARD: 1, ConceptRole.CONTEXTUAL: 2}
        sorted_concepts = sorted(concepts, key=lambda c: role_order.get(c.role, 1))
        return sorted_concepts[:max_count]

    def _fallback_identification(
        self,
        doc_id: str,
        subject_text: str,
        themes: List[Theme],
        content: str
    ) -> Tuple[List[Concept], List[Dict]]:
        """Identification de secours sans LLM."""
        # Extraction naive basée sur la fréquence
        words = re.findall(r'\b[A-Z][a-zA-Z]{3,}\b', content)
        word_freq = {}
        stop_words = {'this', 'that', 'with', 'from', 'have', 'been', 'would', 'should'}

        for word in words:
            word_lower = word.lower()
            if word_lower not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1

        # Garder les top termes (frugalité)
        sorted_terms = sorted(word_freq.items(), key=lambda x: -x[1])[:self.MAX_CONCEPTS]

        concepts = []
        default_theme_id = themes[0].theme_id if themes else "theme_default"

        for idx, (term, freq) in enumerate(sorted_terms):
            role = ConceptRole.CENTRAL if idx == 0 else ConceptRole.STANDARD

            concept = Concept(
                concept_id=f"concept_{doc_id}_{idx}",
                theme_id=default_theme_id,
                name=term,
                role=role,
                variants=[],
                lex_key=self._generate_lex_key(term)
            )
            concepts.append(concept)

        # Termes refusés (les moins fréquents)
        refused = [
            {"term": t, "reason": f"Fréquence trop faible ({f})"}
            for t, f in sorted_terms[self.MAX_CONCEPTS:self.MAX_CONCEPTS + 10]
        ] if len(sorted_terms) > self.MAX_CONCEPTS else []

        return concepts, refused

    def _default_system_prompt(self) -> str:
        return """Tu es un expert en extraction de concepts pour OSMOSE.
Tu dois identifier les CONCEPTS CLÉS d'un document de manière FRUGALE.

RÈGLES DE FRUGALITÉ:
- Maximum {max_concepts} concepts par document
- Chaque concept doit être SIGNIFICATIF et DISTINCT
- Éviter les termes génériques (ex: "système", "méthode", "processus")
- Éviter les termes trop spécifiques/locaux

RÔLES des concepts:
- CENTRAL: Concept au cœur du document, tout tourne autour
- STANDARD: Concept important mais pas central
- CONTEXTUAL: Concept de contexte, mentionné mais pas le focus

Tu dois aussi identifier les VARIANTES de chaque concept (synonymes, traductions).
"""

    def _default_user_prompt(self) -> str:
        return """Identifie les concepts de ce document.

SUJET: {subject}
STRUCTURE: {structure}
LANGUE: {language}

THÈMES:
{themes}

CONTENU:
{content}

ATTENTION: Maximum {max_concepts} concepts!

Réponds UNIQUEMENT avec ce JSON:
```json
{{
  "concepts": [
    {{
      "name": "Nom du concept",
      "role": "CENTRAL|STANDARD|CONTEXTUAL",
      "theme": "Nom du thème rattaché",
      "variants": ["Variante 1", "Variante 2"]
    }}
  ],
  "refused_terms": [
    {{
      "term": "Terme refusé",
      "reason": "Raison du refus"
    }}
  ]
}}
```"""
