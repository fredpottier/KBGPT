"""
Phase 1.3 - Extraction des Information

Extrait les Information (N0) pour chaque ConceptSitue:
- Avec ANCHOR valide (pointeur vers texte source)
- Type: DEFINITION, FACT, CAPABILITY, CONSTRAINT, etc.
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from poc.models.schemas import (
    Information,
    InfoType,
    Anchor,
    ConceptSitue
)
from poc.validators.anchor_validator import AnchorValidator


class InformationExtractor:
    """
    Extrait les Information pour chaque concept.
    Chaque Information est un pointeur ANCHOR vers le texte source.

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
        self.anchor_validator = AnchorValidator()
        self.allow_fallback = allow_fallback

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML"""
        import yaml

        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "poc_prompts.yaml"

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def extract_for_concept(
        self,
        concept: ConceptSitue,
        chunks: Dict[str, str],
        theme_name: str
    ) -> List[Information]:
        """
        Extrait les Information pour un concept donne.

        Args:
            concept: Le ConceptSitue a enrichir
            chunks: Dictionnaire chunk_id -> texte
            theme_name: Nom du theme parent

        Returns:
            Liste des Information extraites
        """
        # Trouver les chunks contenant ce concept
        relevant_chunks = self._find_relevant_chunks(concept.name, chunks)

        if not relevant_chunks:
            return []

        # Construire le prompt
        prompt_config = self.prompts.get("information_extraction", {})
        system_prompt = prompt_config.get("system", "")
        user_template = prompt_config.get("user", "")

        chunks_content = self._format_chunks(relevant_chunks)

        user_prompt = user_template.format(
            concept_name=concept.name,
            concept_role=concept.role.value,
            theme_name=theme_name,
            concept_id=concept.id,
            chunks_content=chunks_content
        )

        # Appeler le LLM - PAS DE FALLBACK SILENCIEUX
        if self.llm_client:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=1500  # Reduit pour contexte 8k
            )
            informations = self._parse_response(response, concept.id)
        elif self.allow_fallback:
            # Mode test uniquement - fallback explicitement autorisé
            informations = self._fallback_extraction(concept, relevant_chunks, theme_name)
        else:
            # PAS DE FALLBACK - erreur explicite
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        # Valider les anchors
        valid_informations = self._validate_anchors(informations, chunks)

        return valid_informations

    def extract_all(
        self,
        concepts: List[ConceptSitue],
        chunks: Dict[str, str]
    ) -> Tuple[List[Information], Dict[str, List[str]]]:
        """
        Extrait les Information pour tous les concepts.

        Args:
            concepts: Liste des ConceptSitue
            chunks: Dictionnaire chunk_id -> texte

        Returns:
            (all_informations, concept_to_info_ids)
        """
        all_informations = []
        concept_to_info_ids: Dict[str, List[str]] = {}

        for concept in concepts:
            infos = self.extract_for_concept(
                concept,
                chunks,
                concept.theme_ref
            )

            info_ids = [info.id for info in infos]
            concept_to_info_ids[concept.id] = info_ids

            all_informations.extend(infos)

        return all_informations, concept_to_info_ids

    def _find_relevant_chunks(
        self,
        concept_name: str,
        chunks: Dict[str, str]
    ) -> Dict[str, str]:
        """Trouve les chunks mentionnant le concept"""
        relevant = {}
        pattern = re.compile(re.escape(concept_name), re.IGNORECASE)

        for chunk_id, text in chunks.items():
            if pattern.search(text):
                relevant[chunk_id] = text

        return relevant

    def _format_chunks(self, chunks: Dict[str, str], max_total_chars: int = 3000) -> str:
        """Formate les chunks pour le prompt avec limite de taille"""
        lines = []
        total_chars = 0
        max_chunks = 3  # Limiter a 3 chunks max par concept

        for i, (chunk_id, text) in enumerate(chunks.items()):
            if i >= max_chunks:
                break

            # Limiter la taille de chaque chunk
            remaining = max_total_chars - total_chars
            if remaining <= 100:
                break

            truncated = text[:min(1000, remaining)]
            lines.append(f"[CHUNK {chunk_id}]\n{truncated}\n")
            total_chars += len(truncated) + 20  # +20 pour le header

        return '\n'.join(lines)

    def _parse_response(self, response: str, concept_id: str) -> List[Information]:
        """Parse la reponse JSON du LLM"""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            return self._convert_to_informations(data, concept_id)
        except json.JSONDecodeError as e:
            # Log error but continue
            print(f"Warning: Reponse LLM non parseable: {e}")
            return []

    def _convert_to_informations(self, data: Dict, concept_id: str) -> List[Information]:
        """Convertit les donnees JSON en objets Information"""
        informations = []

        for info_data in data.get("informations", []):
            try:
                # Parser le type
                type_str = info_data.get("info_type", "FACT")
                try:
                    info_type = InfoType(type_str)
                except ValueError:
                    info_type = InfoType.FACT

                # Parser l'anchor
                anchor_data = info_data.get("anchor", {})
                anchor = Anchor(
                    chunk_id=anchor_data.get("chunk_id", "unknown"),
                    start_char=anchor_data.get("start_char", 0),
                    end_char=anchor_data.get("end_char", 0)
                )

                info = Information(
                    info_type=info_type,
                    anchor=anchor,
                    concept_refs=[concept_id],
                    theme_ref=info_data.get("theme_ref", "")
                )
                informations.append(info)

            except Exception as e:
                print(f"Warning: Information invalide: {e}")
                continue

        return informations

    def _fallback_extraction(
        self,
        concept: ConceptSitue,
        chunks: Dict[str, str],
        theme_name: str
    ) -> List[Information]:
        """
        Extraction de secours sans LLM.
        Extrait les phrases contenant le concept.
        """
        informations = []
        pattern = re.compile(re.escape(concept.name), re.IGNORECASE)

        for chunk_id, text in chunks.items():
            # Trouver toutes les occurrences
            for match in pattern.finditer(text):
                # Trouver la phrase englobante
                start, end = self._find_sentence_bounds(text, match.start(), match.end())

                if end - start < 10:
                    continue

                # Determiner le type heuristiquement
                sentence = text[start:end].lower()
                info_type = self._detect_info_type(sentence)

                info = Information(
                    info_type=info_type,
                    anchor=Anchor(
                        chunk_id=chunk_id,
                        start_char=start,
                        end_char=end
                    ),
                    concept_refs=[concept.id],
                    theme_ref=theme_name
                )
                informations.append(info)

        return informations

    def _find_sentence_bounds(
        self,
        text: str,
        match_start: int,
        match_end: int
    ) -> Tuple[int, int]:
        """Trouve les bornes de la phrase contenant le match"""
        # Chercher le debut de phrase
        start = match_start
        while start > 0 and text[start - 1] not in '.!?\n':
            start -= 1

        # Chercher la fin de phrase
        end = match_end
        while end < len(text) and text[end] not in '.!?\n':
            end += 1

        # Inclure le point final si present
        if end < len(text) and text[end] in '.!?':
            end += 1

        return start, end

    def _detect_info_type(self, sentence: str) -> InfoType:
        """Detecte le type d'Information par heuristique"""
        sentence_lower = sentence.lower()

        if any(w in sentence_lower for w in ['est defini', 'definit', 'designe', 'refers to']):
            return InfoType.DEFINITION
        elif any(w in sentence_lower for w in ['permet', 'enable', 'allow', 'can be used']):
            return InfoType.CAPABILITY
        elif any(w in sentence_lower for w in ['doit', 'must', 'shall', 'required', 'obligatoire']):
            return InfoType.CONSTRAINT
        elif any(w in sentence_lower for w in ['option', 'peut', 'may', 'possible']):
            return InfoType.OPTION
        elif any(w in sentence_lower for w in ['limite', 'cannot', 'ne peut pas', 'impossible']):
            return InfoType.LIMITATION
        elif any(w in sentence_lower for w in ['si', 'if', 'when', 'lorsque', 'condition']):
            return InfoType.CONDITION
        elif any(w in sentence_lower for w in ['resulte', 'leads to', 'consequence', 'therefore']):
            return InfoType.CONSEQUENCE
        else:
            return InfoType.FACT

    def _validate_anchors(
        self,
        informations: List[Information],
        chunks: Dict[str, str]
    ) -> List[Information]:
        """Filtre les Information avec anchors valides"""
        valid = []
        for info in informations:
            is_valid, _ = self.anchor_validator.validate_single(info.anchor, chunks)
            if is_valid:
                valid.append(info)
        return valid
