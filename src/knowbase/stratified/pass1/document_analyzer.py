"""
OSMOSE Pipeline V2 - Phase 1.1 Document Analyzer
=================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Analyse structurelle du document:
- Détecte le SUJET (résumé 1 phrase)
- Détermine la STRUCTURE (CENTRAL, TRANSVERSAL, CONTEXTUAL)
- Identifie les THEMES majeurs

Adapté du POC: poc/extractors/document_analyzer.py
"""

import json
import re
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml

from knowbase.stratified.models import (
    DocumentStructure,
    Subject,
    Theme,
)

logger = logging.getLogger(__name__)


class DocumentAnalyzerV2:
    """
    Analyseur de document pour Pipeline V2.

    Détecte:
    - Sujet principal (résumé 1 phrase)
    - Structure de dépendance (CENTRAL/TRANSVERSAL/CONTEXTUAL)
    - Thèmes majeurs (hiérarchie)

    IMPORTANT: Pas de fallback silencieux - erreur explicite si LLM absent.
    """

    # Seuil pour détecter un document HOSTILE (trop de sujets)
    # Augmenté de 10 à 15: les thèmes adaptatifs (7-12) nécessitent plus de marge
    HOSTILE_SUBJECT_THRESHOLD = 15

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
            "document_analysis": {
                "system": self._default_system_prompt(),
                "user": self._default_user_prompt()
            }
        }

    def analyze(
        self,
        doc_id: str,
        doc_title: str,
        content: str,
        toc: Optional[str] = None,
        char_limit: int = 4000,
        sections: Optional[List[Dict]] = None,
        language_override: Optional[str] = None,
    ) -> Tuple[Subject, List[Theme], bool]:
        """
        Analyse un document et retourne sa structure sémantique.

        Args:
            doc_id: Identifiant du document
            doc_title: Titre du document
            content: Contenu textuel complet
            toc: Table des matières (si disponible)
            char_limit: Limite de caractères pour le preview
            sections: Sections Docling (dicts avec title/level) pour coverage cascade

        Returns:
            Tuple[Subject, List[Theme], is_hostile]
            - Subject: sujet avec structure de dépendance
            - List[Theme]: thèmes identifiés
            - is_hostile: True si document détecté comme HOSTILE
        """
        # Préparer le preview
        content_preview = content[:char_limit]
        toc_text = toc if toc else "Non disponible"

        # Construire le prompt
        prompt_config = self.prompts.get("document_analysis", {})
        system_prompt = prompt_config.get("system", self._default_system_prompt())
        user_template = prompt_config.get("user", self._default_user_prompt())

        user_prompt = user_template.format(
            doc_title=doc_title,
            char_limit=char_limit,
            content_preview=content_preview,
            toc=toc_text
        )

        # Issue 3: Si la langue a été détectée sur le document original,
        # injecter un hint explicite pour forcer les thèmes dans la bonne langue.
        # Le meta-document (Pass 0.9) peut être en FR même si le doc original est EN.
        if language_override:
            lang_names = {"en": "English", "fr": "French", "de": "German"}
            lang_name = lang_names.get(language_override, language_override)
            user_prompt += (
                f"\n\nCRITICAL: The original document language is {language_override} ({lang_name}). "
                f"ALL themes MUST be written in {lang_name}. "
                f"Set language to \"{language_override}\"."
            )

        # Appeler le LLM
        if self.llm_client:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=4000  # Docs EN riches produisent beaucoup de thèmes
            )
            result = self._parse_response(response, doc_id)
        elif self.allow_fallback:
            logger.warning("[OSMOSE:Pass1:1.1] Mode fallback activé - résultats non fiables")
            result = self._fallback_analysis(doc_id, doc_title, content)
        else:
            raise RuntimeError(
                "LLM non disponible et fallback non autorisé. "
                "Utilisez allow_fallback=True uniquement pour les tests."
            )

        subject, themes = result

        # Appliquer language_override si fourni (Issue 3: langue détectée sur original)
        if language_override:
            subject.language = language_override

        # Détection HOSTILE: trop de thèmes = document mixte
        is_hostile = len(themes) > self.HOSTILE_SUBJECT_THRESHOLD
        if is_hostile:
            logger.warning(
                f"[OSMOSE:Pass1:1.1] Document HOSTILE détecté: "
                f"{len(themes)} thèmes (seuil: {self.HOSTILE_SUBJECT_THRESHOLD})"
            )

        # Garde-fou coverage: vérifier que les sections majeures du document
        # sont couvertes par au moins un thème. Cascade de signaux :
        # 1. TOC (si disponible) → 2. Headings Docling (H1/H2) → 3. rien
        if not is_hostile:
            themes = self._ensure_major_section_coverage(themes, toc, sections, doc_id)

        return subject, themes, is_hostile

    def _parse_response(self, response: str, doc_id: str) -> Tuple[Subject, List[Theme]]:
        """Parse la réponse JSON du LLM."""
        # Extraire le JSON du bloc de code
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Gérer les fences non-fermées (réponse tronquée)
            fence_start = re.search(r'```json\s*', response)
            if fence_start:
                json_str = response[fence_start.end():]
            else:
                json_str = response

        try:
            data = json.loads(json_str)
            return self._validate_and_convert(data, doc_id)
        except json.JSONDecodeError as e:
            logger.error(f"Réponse LLM invalide: {e}")
            raise ValueError(f"Réponse LLM invalide: {e}\nRéponse: {response[:500]}")

    def _validate_and_convert(self, data: Dict, doc_id: str) -> Tuple[Subject, List[Theme]]:
        """Valide et convertit la réponse en objets Pydantic V2."""
        # Structure du document
        structure_data = data.get("structure", {})
        chosen = structure_data.get("chosen", "TRANSVERSAL")

        try:
            structure = DocumentStructure(chosen)
        except ValueError:
            structure = DocumentStructure.TRANSVERSAL

        # Créer le Subject
        # Extraire le nom court (si fourni) ou le dériver du subject text
        subject_text = data.get("subject", "Sujet non identifié")
        subject_name = data.get("subject_name") or data.get("name")
        if not subject_name and subject_text:
            # Dériver un nom court du texte (premiers mots significatifs)
            subject_name = subject_text.split(",")[0].split(".")[0][:80]

        subject = Subject(
            subject_id=f"subj_{doc_id}",
            name=subject_name,
            text=subject_text,
            structure=structure,
            language=data.get("language", "fr"),
            justification=structure_data.get("justification")
        )

        # Créer les Themes
        themes = []
        for idx, theme_data in enumerate(data.get("themes", [])):
            theme_name = theme_data if isinstance(theme_data, str) else theme_data.get("name", f"Theme_{idx}")
            theme = Theme(
                theme_id=f"theme_{doc_id}_{idx}",
                name=theme_name,
                scoped_to_sections=[]  # Sera rempli après Pass 0
            )
            themes.append(theme)

        return subject, themes

    def _fallback_analysis(
        self,
        doc_id: str,
        doc_title: str,
        content: str
    ) -> Tuple[Subject, List[Theme]]:
        """Analyse de secours sans LLM (heuristiques simples)."""
        title_lower = doc_title.lower()

        # Détecter structure par mots-clés
        if any(kw in title_lower for kw in ["guide", "product", "solution", "sap"]):
            structure = DocumentStructure.CENTRAL
            justification = "Document centré sur un produit/solution spécifique"
        elif any(kw in title_lower for kw in ["regulation", "gdpr", "cnil", "standard", "norme"]):
            structure = DocumentStructure.TRANSVERSAL
            justification = "Document de référence applicable indépendamment"
        else:
            structure = DocumentStructure.CONTEXTUAL
            justification = "Structure par défaut pour document mixte"

        # Détecter la langue
        language = self._detect_language(content)

        subject = Subject(
            subject_id=f"subj_{doc_id}",
            name=doc_title,  # Utiliser le titre comme nom en fallback
            text=f"Analyse de {doc_title}",
            structure=structure,
            language=language,
            justification=justification
        )

        # Thèmes par défaut
        themes = [
            Theme(theme_id=f"theme_{doc_id}_0", name="Introduction"),
            Theme(theme_id=f"theme_{doc_id}_1", name="Contenu Principal"),
            Theme(theme_id=f"theme_{doc_id}_2", name="Conclusion"),
        ]

        return subject, themes

    def _ensure_major_section_coverage(
        self,
        themes: List[Theme],
        toc: Optional[str],
        sections: Optional[List[Dict]],
        doc_id: str
    ) -> List[Theme]:
        """
        Vérifie que les sections majeures du document sont couvertes par un thème.

        Cascade de signaux pour extraire les titres de sections majeures :
        1. TOC textuelle (si disponible) → H1/H2
        2. Headings Docling (sections avec title/level) → level 1-2
        3. Aucun signal → retourne les thèmes tels quels

        Si une section majeure n'a aucun thème correspondant (par similarité lexicale),
        elle est promue en thème supplémentaire.

        Args:
            themes: Thèmes extraits par le LLM
            toc: Table des matières (texte, peut être None)
            sections: Sections Docling (dicts avec title/level, peut être None)
            doc_id: ID du document

        Returns:
            Liste de thèmes enrichie si nécessaire
        """
        # Cascade : essayer TOC d'abord, puis headings Docling
        major_sections = self._extract_major_sections_from_toc(toc)
        source = "TOC"

        if not major_sections and sections:
            major_sections = self._extract_major_sections_from_headings(sections)
            source = "headings"

        if not major_sections:
            return themes

        # Vérifier la couverture : pour chaque section majeure, chercher un thème
        # qui la couvre (par similarité lexicale simple — mots en commun)
        orphan_sections = self._find_orphan_sections(major_sections, themes)

        # Promouvoir les sections orphelines en thèmes
        if orphan_sections:
            next_idx = len(themes)
            for section_title in orphan_sections:
                new_theme = Theme(
                    theme_id=f"theme_{doc_id}_{next_idx}",
                    name=section_title,
                    scoped_to_sections=[],
                )
                themes.append(new_theme)
                next_idx += 1

            logger.info(
                f"[OSMOSE:Pass1:1.1:Coverage] {len(orphan_sections)} sections orphelines "
                f"promues en thèmes (source: {source}): {orphan_sections}"
            )

        return themes

    def _extract_major_sections_from_toc(self, toc: Optional[str]) -> List[str]:
        """Extrait les titres de sections H1/H2 depuis une TOC textuelle."""
        if not toc:
            return []

        toc_sections = []
        for line in toc.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Patterns : "1. Title", "1.1 Title", "## Title"
            if re.match(r'^\d+(\.\d+)?\s+\w', line):
                level_match = re.match(r'^(\d+(?:\.\d+)?)', line)
                if level_match:
                    level_str = level_match.group(1)
                    if level_str.count('.') <= 1:  # H1 ou H2
                        section_title = re.sub(r'^[\d\.]+\s*', '', line).strip()
                        if len(section_title) > 3:
                            toc_sections.append(section_title)
            elif re.match(r'^#{1,2}\s+', line):
                section_title = re.sub(r'^#+\s*', '', line).strip()
                if len(section_title) > 3:
                    toc_sections.append(section_title)

        return toc_sections

    def _extract_major_sections_from_headings(self, sections: List[Dict]) -> List[str]:
        """Extrait les titres de sections majeures depuis les headings Docling (level 1-2)."""
        major_sections = []
        for section in sections:
            level = section.get("level", 99)
            title = section.get("title") or section.get("name", "")
            title = title.strip()
            if level <= 2 and len(title) > 3:
                major_sections.append(title)
        return major_sections

    def _find_orphan_sections(
        self,
        major_sections: List[str],
        themes: List[Theme]
    ) -> List[str]:
        """Identifie les sections majeures non couvertes par un thème existant."""
        theme_names_lower = [t.name.lower() for t in themes]
        orphan_sections = []

        generic_words = {
            "the", "and", "for", "with", "from", "this", "that", "are",
            "overview", "introduction", "conclusion", "appendix", "summary",
            "agenda", "table", "contents",
        }

        for section_title in major_sections:
            section_words = set(
                w.lower() for w in re.findall(r'\w{3,}', section_title)
            )
            section_words -= generic_words

            if not section_words:
                continue

            # Chercher un thème qui partage au moins 1 mot significatif
            covered = False
            for theme_name in theme_names_lower:
                theme_words = set(
                    w.lower() for w in re.findall(r'\w{3,}', theme_name)
                )
                if section_words & theme_words:
                    covered = True
                    break

            if not covered:
                orphan_sections.append(section_title)

        return orphan_sections

    def _detect_language(self, text: str) -> str:
        """Détecte la langue par heuristique."""
        sample = text[:5000].lower()

        fr_words = ['le', 'la', 'les', 'de', 'du', 'des', 'est', 'sont', 'pour', 'avec', 'dans']
        en_words = ['the', 'is', 'are', 'for', 'with', 'in', 'to', 'of', 'and', 'that']
        de_words = ['der', 'die', 'das', 'und', 'ist', 'sind', 'mit', 'von', 'fur', 'auf']

        words = sample.split()
        fr_count = sum(1 for w in words if w in fr_words)
        en_count = sum(1 for w in words if w in en_words)
        de_count = sum(1 for w in words if w in de_words)

        if fr_count > en_count and fr_count > de_count:
            return "fr"
        elif de_count > en_count:
            return "de"
        return "en"

    def extract_toc_from_content(self, content: str) -> Optional[str]:
        """Extrait une table des matières du contenu."""
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

            if re.search(toc_patterns[0], line_stripped, re.IGNORECASE):
                in_toc = True
                continue

            if in_toc or re.match(r'^\d+\.', line_stripped):
                if re.match(r'^[\d\.]+\s+\w', line_stripped):
                    toc_lines.append(line_stripped)
                    in_toc = True

        return '\n'.join(toc_lines) if toc_lines else None

    def _default_system_prompt(self) -> str:
        return """Tu es un expert en analyse documentaire pour OSMOSE.
Tu dois analyser le document et déterminer:
1. Son SUJET principal (résumé en 1 phrase)
2. Sa STRUCTURE de dépendance:
   - CENTRAL: Le document dépend d'un contexte central (ex: guide produit SAP)
   - TRANSVERSAL: Le document est une référence indépendante (ex: réglementation GDPR)
   - CONTEXTUAL: Le document combine plusieurs contextes
3. Ses THEMES majeurs (5-10 maximum)
4. La LANGUE du document (fr, en, de)

IMPORTANT: Sois FRUGAL. Maximum 10 thèmes."""

    def _default_user_prompt(self) -> str:
        return """Analyse ce document:

TITRE: {doc_title}

TABLE DES MATIÈRES:
{toc}

CONTENU (premiers {char_limit} caractères):
{content_preview}

Réponds UNIQUEMENT avec ce JSON:
```json
{{
  "subject": "Résumé du sujet en 1 phrase",
  "structure": {{
    "chosen": "CENTRAL|TRANSVERSAL|CONTEXTUAL",
    "justification": "Pourquoi cette structure"
  }},
  "themes": [
    "Thème 1",
    "Thème 2"
  ],
  "language": "fr|en|de"
}}
```"""
