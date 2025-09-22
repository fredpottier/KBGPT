"""
Service de gestion des solutions SAP avec support pour les nouvelles solutions.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from knowbase.common.llm_router import LLMRouter, TaskType
from knowbase.common.logging import setup_logging
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

logger = setup_logging(Path(__file__).parent.parent.parent.parent.parent / "data" / "logs", "sap_solutions.log")

class SAPSolutionsManager:
    """Gestionnaire des solutions SAP avec YAML persistant et découverte automatique."""

    def __init__(self):
        self.config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "sap_solutions.yaml"
        self.llm_router = LLMRouter()
        self._solutions_cache = None

    def _load_solutions(self) -> Dict[str, Any]:
        """Charge les solutions depuis le fichier YAML."""
        if self._solutions_cache is None:
            try:
                with open(self.config_path, 'r', encoding='utf-8') as file:
                    data = yaml.safe_load(file)
                    self._solutions_cache = data.get('solutions', {})
                    logger.info(f"📋 Chargé {len(self._solutions_cache)} solutions SAP depuis YAML")
            except Exception as e:
                logger.error(f"❌ Erreur chargement solutions SAP: {e}")
                self._solutions_cache = {}
        return self._solutions_cache

    def _save_solutions(self, solutions: Dict[str, Any]) -> None:
        """Sauvegarde les solutions dans le fichier YAML."""
        try:
            # Charger la structure complète du YAML
            with open(self.config_path, 'r', encoding='utf-8') as file:
                data = yaml.safe_load(file)

            # Mettre à jour les solutions
            data['solutions'] = solutions
            data['metadata']['total_solutions'] = len(solutions)
            data['metadata']['last_updated'] = "2025-01-20"

            # Sauvegarder avec tri alphabétique
            with open(self.config_path, 'w', encoding='utf-8') as file:
                yaml.dump(data, file, default_flow_style=False, allow_unicode=True, indent=2)

            # Invalider le cache
            self._solutions_cache = None
            logger.info(f"💾 Sauvegardé {len(solutions)} solutions SAP dans YAML")

        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde solutions SAP: {e}")

    def get_solutions_list(self) -> List[Tuple[str, str]]:
        """Retourne la liste des solutions triées alphabétiquement (canonical_name, id)."""
        solutions = self._load_solutions()

        # Créer liste (canonical_name, id) triée alphabétiquement
        solutions_list = [
            (solution_data['canonical_name'], solution_id)
            for solution_id, solution_data in solutions.items()
        ]

        return sorted(solutions_list, key=lambda x: x[0])  # Tri par canonical_name

    def find_solution_by_name(self, search_name: str) -> Optional[Tuple[str, str]]:
        """Trouve une solution par nom exact ou alias (canonical_name, id)."""
        solutions = self._load_solutions()
        search_name_lower = search_name.lower().strip()

        for solution_id, solution_data in solutions.items():
            # Vérifier nom canonique
            if solution_data['canonical_name'].lower() == search_name_lower:
                return (solution_data['canonical_name'], solution_id)

            # Vérifier alias
            for alias in solution_data.get('aliases', []):
                if alias.lower() == search_name_lower:
                    return (solution_data['canonical_name'], solution_id)

        return None

    def canonicalize_with_llm(self, user_input: str) -> str:
        """Utilise le LLM pour canonicaliser un nom de solution SAP."""
        try:
            solutions = self._load_solutions()
            known_solutions = [data['canonical_name'] for data in solutions.values()]

            system_message: ChatCompletionSystemMessageParam = {
                "role": "system",
                "content": (
                    "You are an expert in SAP product naming conventions. "
                    "Given a user input that might be a SAP solution name or abbreviation, "
                    "determine the official SAP product name. "
                    "Only reply with the official SAP solution name, without quotes, explanations, or any extra text."
                ),
            }

            user_message: ChatCompletionUserMessageParam = {
                "role": "user",
                "content": (
                    f"Here is a solution name or abbreviation: {user_input}\n"
                    f"Known SAP solutions include: {', '.join(known_solutions[:10])}...\n"
                    "What is the official SAP product name? Only reply with the name itself."
                ),
            }

            messages: List[ChatCompletionMessageParam] = [system_message, user_message]
            content = self.llm_router.complete(TaskType.CANONICALIZATION, messages)

            if not isinstance(content, str):
                raise ValueError("Missing completion content")

            canonical_name = content.strip()
            logger.info(f"🤖 LLM canonicalization: '{user_input}' → '{canonical_name}'")
            return canonical_name

        except Exception as e:
            logger.warning(f"⚠️ LLM canonicalization error: {e}")
            return user_input.strip()

    def add_new_solution(self, user_input: str, canonical_name: str, category: str = "custom") -> str:
        """Ajoute une nouvelle solution au dictionnaire."""
        try:
            solutions = self._load_solutions()

            # Générer un ID unique basé sur le nom canonique
            solution_id = self._generate_solution_id(canonical_name)

            # Vérifier si elle existe déjà
            if solution_id in solutions:
                logger.info(f"📋 Solution '{canonical_name}' existe déjà avec ID '{solution_id}'")
                return solution_id

            # Ajouter la nouvelle solution
            new_solution = {
                'canonical_name': canonical_name,
                'aliases': [user_input] if user_input != canonical_name else [],
                'category': category
            }

            solutions[solution_id] = new_solution
            self._save_solutions(solutions)

            logger.info(f"✅ Nouvelle solution ajoutée: '{canonical_name}' (ID: {solution_id})")
            return solution_id

        except Exception as e:
            logger.error(f"❌ Erreur ajout nouvelle solution: {e}")
            raise

    def _generate_solution_id(self, canonical_name: str) -> str:
        """Génère un ID unique basé sur le nom canonique."""
        # Nettoyer le nom pour créer un ID
        clean_name = canonical_name.upper()
        clean_name = clean_name.replace("SAP ", "SAP_")
        clean_name = clean_name.replace(" ", "_")
        clean_name = clean_name.replace("/", "")
        clean_name = clean_name.replace("(", "").replace(")", "")
        clean_name = clean_name.replace(",", "")
        clean_name = clean_name.replace("-", "_")
        clean_name = clean_name.replace("&", "AND")

        # Limiter la longueur
        if len(clean_name) > 50:
            clean_name = clean_name[:50]

        return clean_name

    def resolve_solution(self, user_input: str) -> Tuple[str, str]:
        """
        Résout une solution SAP depuis l'input utilisateur.
        Retourne (canonical_name, solution_id).
        """
        # 1. Chercher dans les solutions existantes
        existing = self.find_solution_by_name(user_input)
        if existing:
            return existing

        # 2. Utiliser LLM pour canonicaliser
        canonical_name = self.canonicalize_with_llm(user_input)

        # 3. Vérifier si le nom canonique existe maintenant
        existing_canonical = self.find_solution_by_name(canonical_name)
        if existing_canonical:
            # Ajouter l'alias si pas déjà présent
            self._add_alias_to_existing(existing_canonical[1], user_input)
            return existing_canonical

        # 4. Créer nouvelle solution
        solution_id = self.add_new_solution(user_input, canonical_name)
        return (canonical_name, solution_id)

    def _add_alias_to_existing(self, solution_id: str, new_alias: str) -> None:
        """Ajoute un alias à une solution existante."""
        try:
            solutions = self._load_solutions()
            if solution_id in solutions:
                aliases = solutions[solution_id].get('aliases', [])
                if new_alias not in aliases and new_alias != solutions[solution_id]['canonical_name']:
                    aliases.append(new_alias)
                    solutions[solution_id]['aliases'] = aliases
                    self._save_solutions(solutions)
                    logger.info(f"📝 Alias '{new_alias}' ajouté à la solution '{solution_id}'")
        except Exception as e:
            logger.warning(f"⚠️ Erreur ajout alias: {e}")


def get_sap_solutions_manager() -> SAPSolutionsManager:
    """Retourne une nouvelle instance du gestionnaire de solutions SAP."""
    return SAPSolutionsManager()