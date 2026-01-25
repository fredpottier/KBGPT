"""
Phase 1.1 - Analyse Structurelle du Document

Determine:
- Le SUJET du document
- La STRUCTURE DE DEPENDANCE (CENTRAL, TRANSVERSAL, CONTEXTUAL)
- La hierarchie THEMATIQUE
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from poc.models.schemas import (
    DependencyStructure,
    StructureJustification,
    Theme
)
from poc.validators.justification_validator import JustificationValidator


class DocumentAnalyzer:
    """
    Analyse la structure d'un document pour determiner:
    - Son sujet principal
    - Sa structure de dependance
    - Ses themes majeurs

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
        self.justification_validator = JustificationValidator()
        self.allow_fallback = allow_fallback

    def _load_prompts(self, prompts_path: Optional[Path]) -> Dict:
        """Charge les prompts depuis le fichier YAML"""
        import yaml

        if prompts_path is None:
            prompts_path = Path(__file__).parent.parent / "prompts" / "poc_prompts.yaml"

        with open(prompts_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def analyze(
        self,
        doc_title: str,
        content: str,
        toc: Optional[str] = None,
        char_limit: int = 4000  # Reduit pour contexte 8k
    ) -> Dict:
        """
        Analyse un document et retourne sa structure.

        Args:
            doc_title: Titre du document
            content: Contenu textuel complet
            toc: Table des matieres (si disponible)
            char_limit: Limite de caracteres pour le preview

        Returns:
            Dict avec subject, structure_decision, themes
        """
        # Preparer le preview
        content_preview = content[:char_limit]
        toc_text = toc if toc else "Non disponible"

        # Construire le prompt
        prompt_config = self.prompts.get("document_analysis", {})
        system_prompt = prompt_config.get("system", "")
        user_template = prompt_config.get("user", "")

        user_prompt = user_template.format(
            doc_title=doc_title,
            char_limit=char_limit,
            content_preview=content_preview,
            toc=toc_text
        )

        # Appeler le LLM - PAS DE FALLBACK SILENCIEUX
        if self.llm_client:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=1500  # Limite pour contexte 8k
            )
            result = self._parse_response(response)
        elif self.allow_fallback:
            # Mode test uniquement - fallback explicitement autorisé
            print("[WARN] Mode fallback activé - résultats non fiables")
            result = self._fallback_analysis(doc_title, content)
        else:
            # PAS DE FALLBACK - erreur explicite
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        # GARDE-FOU: Valider la justification
        structure_decision = result.get("structure_decision")
        if structure_decision:
            justification_result = self.justification_validator.validate_structure_justification(
                chosen=structure_decision.chosen.value,
                justification=structure_decision.justification,
                rejected=structure_decision.rejected
            )
            if not justification_result.is_valid:
                print(f"[WARN] Justification invalide (score={justification_result.score:.2f}):")
                for issue in justification_result.issues:
                    print(f"  - {issue}")
                # Warning, pas erreur - mais signal important

        return result

    def _parse_response(self, response: str) -> Dict:
        """Parse la reponse JSON du LLM"""
        # Extraire le JSON du bloc de code
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Essayer de parser directement
            json_str = response

        try:
            data = json.loads(json_str)
            return self._validate_and_convert(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Reponse LLM invalide: {e}\nReponse: {response[:500]}")

    def _validate_and_convert(self, data: Dict) -> Dict:
        """Valide et convertit la reponse en objets Pydantic"""
        # Valider la structure
        structure_data = data.get("structure", {})
        chosen = structure_data.get("chosen", "TRANSVERSAL")

        # Construire rejected dict
        all_structures = {"CENTRAL", "TRANSVERSAL", "CONTEXTUAL"}
        rejected_structures = all_structures - {chosen}
        rejected_dict = {}
        for struct in rejected_structures:
            rejected_dict[struct] = structure_data.get("rejected", {}).get(
                struct, f"Non selectionne car {chosen} est plus approprie"
            )

        structure_decision = StructureJustification(
            chosen=DependencyStructure(chosen),
            justification=structure_data.get("justification", "Analyse automatique"),
            rejected=rejected_dict
        )

        # Construire les themes
        themes = []
        for theme_data in data.get("themes", []):
            theme = Theme(
                name=theme_data.get("name", "Theme inconnu"),
                children=[
                    Theme(name=sub, parent_id=None)
                    for sub in theme_data.get("sub_themes", [])
                ]
            )
            themes.append(theme)

        return {
            "subject": data.get("subject", "Sujet non identifie"),
            "structure_decision": structure_decision,
            "themes": themes
        }

    def _fallback_analysis(self, doc_title: str, content: str) -> Dict:
        """Analyse de secours sans LLM (heuristiques simples)"""
        # Heuristique basique sur le titre
        title_lower = doc_title.lower()

        # Detecter structure par mots-cles
        if any(kw in title_lower for kw in ["guide", "product", "solution", "sap"]):
            chosen = DependencyStructure.CENTRAL
            justification = "Document centre sur un produit/solution specifique"
        elif any(kw in title_lower for kw in ["regulation", "gdpr", "cnil", "standard"]):
            chosen = DependencyStructure.TRANSVERSAL
            justification = "Document de reference applicable independamment"
        else:
            chosen = DependencyStructure.CONTEXTUAL
            justification = "Structure par defaut pour document mixte"

        # Construire rejected
        all_structures = {"CENTRAL", "TRANSVERSAL", "CONTEXTUAL"}
        rejected_structures = all_structures - {chosen.value}
        rejected = {s: f"Moins pertinent que {chosen.value}" for s in rejected_structures}

        structure_decision = StructureJustification(
            chosen=chosen,
            justification=justification,
            rejected=rejected
        )

        # Themes par defaut
        themes = [
            Theme(name="Introduction"),
            Theme(name="Contenu Principal"),
            Theme(name="Conclusion")
        ]

        return {
            "subject": f"Analyse de {doc_title}",
            "structure_decision": structure_decision,
            "themes": themes
        }

    def extract_toc_from_content(self, content: str) -> Optional[str]:
        """
        Tente d'extraire une table des matieres du contenu.
        Heuristique basee sur les patterns courants.
        """
        # Pattern: lignes numerotees ou avec points de suspension
        toc_patterns = [
            r'(?:table\s+of\s+contents?|sommaire|table\s+des\s+mati[eè]res)',
            r'^\d+\.\s+.+(?:\.\.\.|\.{3,}|\s+\d+)$',
        ]

        lines = content.split('\n')
        toc_lines = []
        in_toc = False

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                if in_toc and len(toc_lines) > 3:
                    break
                continue

            # Detecter debut de TOC
            if re.search(toc_patterns[0], line_stripped, re.IGNORECASE):
                in_toc = True
                continue

            # Dans le TOC, collecter les lignes numerotees
            if in_toc or re.match(r'^\d+\.', line_stripped):
                if re.match(r'^[\d\.]+\s+\w', line_stripped):
                    toc_lines.append(line_stripped)
                    in_toc = True

        return '\n'.join(toc_lines) if toc_lines else None
