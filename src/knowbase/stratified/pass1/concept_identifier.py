"""
OSMOSE Pipeline V2 - Phase 1.2 Concept Identifier
==================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Identification des concepts avec surface conceptuelle élargie:
- Maximum 30 concepts par document (V2.1 - augmenté depuis 15)
- Rôle: CENTRAL, STANDARD, CONTEXTUAL
- Rattachement aux thèmes
- Lexical triggers obligatoires (C1)

Adapté du POC: poc/extractors/concept_identifier.py
"""

import json
import re
import logging
import math
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
import yaml

from knowbase.stratified.models import (
    Concept,
    ConceptRole,
    Theme,
)

logger = logging.getLogger(__name__)

# Patterns valeur (autorisés même si < 3 chars) - C1b
VALUE_PATTERN = re.compile(r'^\d+(\.\d+)*[%°]?[CFc]?$|^\d+[:\-]\d+$')


# ============================================================================
# BUDGET ADAPTATIF (2026-01-27)
# ============================================================================
# Formule: MAX_CONCEPTS = clamp(MIN, MAX, 15 + sqrt(sections) * 3)
# - Croissance sub-linéaire: 4x sections → ~2x concepts
# - Plancher 20: assez pour petits documents
# - Plafond 40: limité par contexte vLLM (8192 tokens input+output)

CONCEPT_BUDGET_MIN = 20      # Minimum concepts (petits documents)
CONCEPT_BUDGET_MAX = 40      # Maximum concepts (limité par vLLM context)
CONCEPT_BUDGET_BASE = 15     # Base fixe
CONCEPT_BUDGET_FACTOR = 3    # Facteur multiplicateur de sqrt(sections)


def compute_concept_budget(n_sections: int, is_hostile: bool = False) -> int:
    """
    Calcule le budget de concepts adaptatif basé sur la structure du document.

    Formule: clamp(20, 40, 15 + sqrt(sections) * 3)

    Args:
        n_sections: Nombre de sections dans le document
        is_hostile: Si True, réduit le budget de moitié

    Returns:
        Nombre maximum de concepts à identifier

    Examples:
        - 20 sections → 28 concepts
        - 50 sections → 36 concepts
        - 200 sections → 57 concepts
        - 500 sections → 80 concepts (cap)
    """
    if n_sections <= 0:
        # Fallback si pas de sections disponibles
        return CONCEPT_BUDGET_MIN if not is_hostile else 10

    raw_budget = CONCEPT_BUDGET_BASE + math.sqrt(n_sections) * CONCEPT_BUDGET_FACTOR
    budget = max(CONCEPT_BUDGET_MIN, min(CONCEPT_BUDGET_MAX, round(raw_budget)))

    if is_hostile:
        # Documents hostiles: budget réduit de moitié
        budget = max(10, budget // 2)

    return budget


class ConceptIdentifierV2:
    """
    Identificateur de concepts pour Pipeline V2.

    BUDGET ADAPTATIF (V2.2 - 2026-01-27):
    - Budget calculé selon: clamp(25, 80, 15 + sqrt(sections) * 3)
    - Croissance sub-linéaire: 4x sections → ~2x concepts
    - Lexical triggers obligatoires (C1)
    - Validation anti-triggers triviaux (C1b)

    IMPORTANT: Pas de fallback silencieux - erreur explicite si LLM absent.
    """

    # Fallback si nombre de sections non fourni (legacy)
    MAX_CONCEPTS_FALLBACK = 30      # Documents normaux sans info sections
    MAX_CONCEPTS_HOSTILE = 10       # Pour documents HOSTILE (garde-fou minimum)

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
        language: str = "fr",
        n_sections: Optional[int] = None
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Identifie les concepts situés du document.

        Args:
            doc_id: Identifiant du document
            subject_text: Texte du sujet (de Phase 1.1)
            structure: Structure (CENTRAL, TRANSVERSAL, CONTEXTUAL)
            themes: Thèmes identifiés (de Phase 1.1)
            content: Contenu textuel complet
            is_hostile: True si document HOSTILE (réduit budget de moitié)
            language: Langue du document
            n_sections: Nombre de sections (pour budget adaptatif)
                        Si None, utilise le fallback fixe

        Returns:
            Tuple[List[Concept], List[Dict]]
            - concepts: Liste des concepts identifiés
            - refused_terms: Termes refusés avec raisons
        """
        # Budget adaptatif basé sur la structure du document
        if n_sections is not None and n_sections > 0:
            max_concepts = compute_concept_budget(n_sections, is_hostile)
            logger.info(
                f"[OSMOSE:Pass1:1.2] Budget adaptatif: {n_sections} sections → "
                f"{max_concepts} concepts max"
            )
        else:
            # Fallback si pas d'info sections
            max_concepts = self.MAX_CONCEPTS_HOSTILE if is_hostile else self.MAX_CONCEPTS_FALLBACK
            logger.debug(f"[OSMOSE:Pass1:1.2] Budget fallback: {max_concepts} concepts max")

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
                max_tokens=4000  # Limité car vLLM context=8192 (input+output)
            )
            # V2.1: Passer le contenu pour validation des lexical_triggers
            concepts, refused = self._parse_response(response, doc_id, themes, content)
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

    def _clean_json_string(self, json_str: str) -> str:
        """
        Nettoie le JSON généré par LLM (trailing commas, comments, etc.).

        Les modèles locaux (Qwen, etc.) génèrent parfois du JSON invalide.
        """
        # Supprimer les commentaires // et /* */
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)

        # Supprimer les trailing commas avant } ou ]
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)

        # Remplacer les single quotes par double quotes (si pas dans une string)
        # Attention: simplification, peut ne pas gérer tous les cas
        json_str = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', json_str)

        return json_str.strip()

    def _parse_response(
        self,
        response: str,
        doc_id: str,
        themes: List[Theme],
        doc_content: str = ""
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Parse la réponse JSON du LLM avec détection de troncature et nettoyage.

        V2.1: Valide également les lexical_triggers si doc_content est fourni.
        """
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        # GUARDRAIL: Détection troncature JSON (ADR: LLM Contract)
        json_str_stripped = json_str.strip()
        if json_str_stripped and not json_str_stripped.endswith(('}', ']')):
            logger.error(
                f"[OSMOSE:Pass1:1.2] TRONCATURE DÉTECTÉE - JSON incomplet. "
                f"Fin: ...{json_str_stripped[-100:]}"
            )
            raise ValueError(
                f"LLM Contract Violation: JSON tronqué détecté. "
                f"Le modèle a probablement atteint sa limite de tokens. "
                f"Fin de réponse: ...{json_str_stripped[-50:]}"
            )

        # Nettoyage JSON pour modèles locaux (trailing commas, etc.)
        json_str_clean = self._clean_json_string(json_str_stripped)

        try:
            data = json.loads(json_str_clean)
            # V2.1: Passer doc_content pour validation C1
            return self._validate_and_convert(data, doc_id, themes, doc_content)
        except json.JSONDecodeError as e:
            logger.error(f"Réponse LLM invalide: {e}")
            logger.debug(f"JSON brut: {json_str_stripped[:500]}")
            logger.debug(f"JSON nettoyé: {json_str_clean[:500]}")
            raise ValueError(f"Réponse LLM invalide: {e}\nRéponse: {response[:500]}")

    def _validate_and_convert(
        self,
        data: Dict,
        doc_id: str,
        themes: List[Theme],
        doc_content: str = "",
        unit_texts: Optional[List[str]] = None
    ) -> Tuple[List[Concept], List[Dict]]:
        """
        Valide et convertit la réponse en objets Pydantic V2.

        V2.1: Valide également les lexical_triggers (C1, C1b, C1c).
        """
        concepts = []
        refused = []
        theme_map = {t.name.lower(): t.theme_id for t in themes}

        # Calculer les top 50 tokens fréquents pour C1b (anti-trivial)
        top_50_tokens = self._get_top_frequent_tokens(doc_content, n=50) if doc_content else set()

        # Préparer unit_texts si non fourni (utiliser le contenu découpé)
        if unit_texts is None and doc_content:
            # Découper en pseudo-unités (paragraphes/phrases)
            unit_texts = [p.strip() for p in re.split(r'\n\n+|\. ', doc_content) if p.strip()]

        valid_idx = 0
        for c_data in data.get("concepts", []):
            name = c_data.get("name", f"Concept_{valid_idx}")
            triggers = c_data.get("lexical_triggers", [])

            # Valider les lexical_triggers (C1, C1b, C1c)
            triggers_audit = {}  # Audit pour validation rôle C1b
            if doc_content and triggers:
                is_valid, triggers_audit = self._validate_lexical_triggers(
                    c_data, doc_content, unit_texts or [], top_50_tokens
                )
                if not is_valid:
                    refused.append({
                        "term": name,
                        "reason": f"Triggers invalides: {triggers_audit.get('rejected', [])}"
                    })
                    logger.debug(f"[OSMOSE:C1] Concept rejeté '{name}': {triggers_audit}")
                    continue
            elif not triggers:
                # Pas de triggers fournis - accepter avec warning (rétrocompatibilité)
                logger.warning(f"[OSMOSE:C1] Concept '{name}' sans triggers (LLM n'a pas respecté le format)")

            # Valider et potentiellement dégrader le rôle selon C1b (2026-01-27)
            # Empêche les concepts "aspirateur" avec triggers génériques d'être CENTRAL
            role = self._validate_role_requirements(c_data, triggers_audit)

            # Trouver le theme_id correspondant
            theme_ref = c_data.get("theme", "")
            theme_id = theme_map.get(theme_ref.lower(), themes[0].theme_id if themes else "")

            # Générer lex_key (clé lexicale normalisée)
            lex_key = self._generate_lex_key(name)

            concept = Concept(
                concept_id=f"concept_{doc_id}_{valid_idx}",
                theme_id=theme_id,
                name=name,
                definition=c_data.get("definition"),
                role=role,
                variants=c_data.get("variants", []),
                lex_key=lex_key,
                lexical_triggers=triggers[:4]  # Max 4 triggers
            )
            concepts.append(concept)
            valid_idx += 1

        # === DÉDUPLICATION PAR NOM (2026-01-27) ===
        # Le LLM (Qwen notamment) peut renvoyer le même concept plusieurs fois
        # On garde uniquement la première occurrence par nom normalisé
        seen_names: Set[str] = set()
        unique_concepts = []
        duplicates_removed = 0

        for concept in concepts:
            normalized_name = concept.name.lower().strip()
            if normalized_name not in seen_names:
                seen_names.add(normalized_name)
                unique_concepts.append(concept)
            else:
                duplicates_removed += 1
                logger.debug(f"[OSMOSE:DEDUP] Doublon éliminé: '{concept.name}'")

        if duplicates_removed > 0:
            logger.warning(
                f"[OSMOSE:DEDUP] {duplicates_removed} concepts dupliqués éliminés "
                f"({len(concepts)} → {len(unique_concepts)})"
            )
            # Réindexer les concept_id après déduplication
            for idx, concept in enumerate(unique_concepts):
                concept.concept_id = f"concept_{doc_id}_{idx}"
            concepts = unique_concepts
        # === FIN DÉDUPLICATION ===

        # Ajouter les termes refusés par le LLM
        for r in data.get("refused_terms", []):
            refused.append({
                "term": r.get("term", ""),
                "reason": r.get("reason", "Non spécifié")
            })

        return concepts, refused

    def _get_top_frequent_tokens(self, content: str, n: int = 50) -> Set[str]:
        """
        Calcule les n tokens les plus fréquents du document.

        Utilisé pour C1b: rejeter les triggers trop fréquents.
        """
        # Tokeniser simplement (mots alphanumériques)
        tokens = re.findall(r'\b\w+\b', content.lower())
        # Filtrer les tokens trop courts
        tokens = [t for t in tokens if len(t) >= 3]
        # Compter les fréquences
        freq = Counter(tokens)
        # Retourner les n plus fréquents
        return {t for t, _ in freq.most_common(n)}

    def _validate_role_requirements(
        self,
        concept: Dict,
        triggers_audit: Dict
    ) -> ConceptRole:
        """
        Valide et ajuste le rôle selon les triggers discriminants.

        Règle C1b renforcée (2026-01-27 - Phase 1 Nettoyage):
        - CENTRAL requiert au moins 1 trigger rare (<1%) ou valeur
        - STANDARD requiert au moins 1 trigger semi-rare (<2%) ou valeur
        - Sinon → CONTEXTUAL

        Ceci empêche les concepts "aspirateur" (ex: "infrastructure SAP")
        avec triggers trop génériques de devenir CENTRAL.

        Args:
            concept: Dict avec 'name' et 'role'
            triggers_audit: Dict retourné par _validate_lexical_triggers

        Returns:
            ConceptRole ajusté
        """
        name = concept.get('name', 'Unknown')
        requested_role = concept.get('role', 'STANDARD').upper()

        # Vérifier si au moins 1 trigger est discriminant
        has_rare = triggers_audit.get('rare_found', False)
        has_semi_rare = any(
            t_info.get('rare') in [True, 'semi-rare', 'fallback_value']
            for t_info in triggers_audit.get('triggers', {}).values()
        )

        # Appliquer les règles de dégradation
        if requested_role == 'CENTRAL':
            if not has_rare:
                if has_semi_rare:
                    logger.info(
                        f"[OSMOSE:C1b] '{name}' dégradé "
                        f"CENTRAL → STANDARD (pas de trigger rare)"
                    )
                    return ConceptRole.STANDARD
                else:
                    logger.info(
                        f"[OSMOSE:C1b] '{name}' dégradé "
                        f"CENTRAL → CONTEXTUAL (pas de trigger discriminant)"
                    )
                    return ConceptRole.CONTEXTUAL

        if requested_role == 'STANDARD':
            if not has_semi_rare and not has_rare:
                logger.info(
                    f"[OSMOSE:C1b] '{name}' dégradé "
                    f"STANDARD → CONTEXTUAL (pas de trigger discriminant)"
                )
                return ConceptRole.CONTEXTUAL

        # Rôle valide - retourner tel quel
        try:
            return ConceptRole(requested_role)
        except ValueError:
            return ConceptRole.STANDARD

    def _validate_lexical_triggers(
        self,
        concept: Dict,
        doc_content: str,
        unit_texts: List[str],
        top_50_tokens: Set[str]
    ) -> Tuple[bool, Dict]:
        """
        Valide les lexical_triggers avec C1, C1b, C1c.

        Args:
            concept: Dict avec 'name' et 'lexical_triggers'
            doc_content: Contenu complet du document
            unit_texts: Liste des textes des unités (pour calcul fréquence)
            top_50_tokens: Set des 50 tokens les plus fréquents

        Returns:
            (is_valid, audit_info)
        """
        triggers = concept.get('lexical_triggers', [])
        audit = {'concept': concept.get('name'), 'triggers': {}, 'rejected': []}

        if len(triggers) < 2:
            audit['rejected'].append('< 2 triggers')
            return False, audit

        valid_triggers = []
        rare_trigger_found = False
        doc_lower = doc_content.lower()
        total_units = len(unit_texts) if unit_texts else 1

        for t in triggers:
            t_lower = t.lower()
            trigger_info = {'trigger': t, 'found': False, 'frequency': 0, 'examples': []}

            # C1b: Refuser < 3 chars sauf patterns valeur
            if len(t) < 3 and not VALUE_PATTERN.match(t):
                audit['rejected'].append(f"'{t}' trop court (<3 chars)")
                continue

            # C1b: Refuser si dans top 50 fréquents
            if t_lower in top_50_tokens:
                audit['rejected'].append(f"'{t}' trop fréquent (top 50)")
                continue

            # C1c: Matching avec word boundary pour alphanum, substring pour valeurs
            is_value = VALUE_PATTERN.match(t)
            if is_value:
                # Substring pour valeurs (8%, 1.2, 2-8°C)
                found_in_content = t_lower in doc_lower
            else:
                # Word boundary pour éviter matchs absurdes ("cat" dans "category")
                pattern = rf'\b{re.escape(t_lower)}\b'
                found_in_content = bool(re.search(pattern, doc_lower))

            if not found_in_content:
                audit['rejected'].append(f"'{t}' absent du document")
                continue

            # Calculer fréquence (nombre d'unités contenant ce trigger)
            if is_value:
                matching_units = [u for u in unit_texts if t_lower in u.lower()]
            else:
                pattern = rf'\b{re.escape(t_lower)}\b'
                matching_units = [u for u in unit_texts if re.search(pattern, u.lower())]

            freq = len(matching_units)
            freq_rate = freq / total_units if total_units > 0 else 0
            trigger_info['found'] = True
            trigger_info['frequency'] = f"{freq}/{total_units} ({freq_rate:.1%})"
            trigger_info['examples'] = [u[:80] for u in matching_units][:2]
            trigger_info['is_value'] = is_value

            # C1b: Au moins 1 trigger rare (< 1% des unités) OU trigger valeur
            if freq_rate < 0.01:
                rare_trigger_found = True
                trigger_info['rare'] = True
            elif freq_rate < 0.02:
                # Fallback semi-rare
                trigger_info['rare'] = 'semi-rare'
            elif is_value:
                # Fallback: triggers valeur considérés comme discriminants
                rare_trigger_found = True
                trigger_info['rare'] = 'fallback_value'

            valid_triggers.append(t)
            audit['triggers'][t] = trigger_info

        # Validation finale
        audit['valid_count'] = len(valid_triggers)
        audit['rare_found'] = rare_trigger_found

        # Vérifier si au moins un trigger semi-rare si pas de rare strict
        has_semi_rare = any(
            info.get('rare') == 'semi-rare'
            for info in audit['triggers'].values()
        )

        is_valid = len(valid_triggers) >= 2 and (rare_trigger_found or has_semi_rare)
        if not rare_trigger_found and not has_semi_rare and valid_triggers:
            audit['rejected'].append("Aucun trigger rare (<1%) ni semi-rare (<2%) ni valeur")

        logger.info(
            f"[OSMOSE:C1] {concept.get('name')}: "
            f"{len(valid_triggers)} triggers valides, rare={rare_trigger_found}"
        )
        return is_valid, audit

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
        # COMPACT OUTPUT (ADR: LLM Contract)
        # System prompt minimaliste pour éviter génération verbose
        return """Expert extraction concepts OSMOSE.

FRUGALITÉ STRICTE:
- Max 10 concepts
- Noms courts (2-4 mots)
- Pas de définitions
- Pas de variantes

RÔLES:
- CENTRAL: Cœur du document
- STANDARD: Important secondaire
- CONTEXTUAL: Contexte

FORMAT: JSON compact uniquement, PAS de texte explicatif.
"""

    def _default_user_prompt(self) -> str:
        # COMPACT OUTPUT (ADR: LLM Contract)
        # Sortie minimaliste pour éviter troncature JSON
        # variants/definition seront enrichis en Pass 2 si nécessaire
        return """Identifie les concepts CLÉS de ce document.

SUJET: {subject}
STRUCTURE: {structure}
LANGUE: {language}

THÈMES DISPONIBLES:
{themes}

CONTENU (extrait):
{content}

RÈGLES STRICTES:
- Maximum {max_concepts} concepts
- Chaque concept DOIT être rattaché à un thème existant
- Éviter les termes génériques (système, méthode, processus)

Réponds UNIQUEMENT avec ce JSON COMPACT:
```json
{{
  "concepts": [
    {{"name": "Nom", "role": "CENTRAL", "theme": "Thème"}},
    {{"name": "Nom2", "role": "STANDARD", "theme": "Thème2"}}
  ],
  "refused_terms": [
    {{"term": "Terme", "reason": "Raison"}}
  ]
}}
```"""
