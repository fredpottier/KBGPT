"""
OSMOSE Pipeline V2.2 - Pass 1.C: Structuration a posteriori
============================================================
Nommage LLM post-clustering: concepts, thèmes, sujet.

Invariant I1: Set-before-Name — les ensembles (clusters) sont formés
AVANT d'être nommés. Le LLM ne crée pas les groupements, il les nomme.
"""

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from knowbase.stratified.models import (
    Subject,
    Theme,
    Concept,
    ConceptRole,
    DocumentStructure,
)
from knowbase.stratified.pass1_v22.models import AssertionCluster, ZonedAssertion

logger = logging.getLogger(__name__)


class StructureBuilder:
    """
    Pass 1.C — Nommage LLM des clusters.

    Phase C.1: Nommage des concepts (par cluster, parallélisé)
    Phase C.2: Regroupement en thèmes (un appel LLM)
    Phase C.3: Sujet (un appel LLM)
    """

    def __init__(
        self,
        llm_client=None,
        max_workers: int = 8,
    ):
        self.llm_client = llm_client
        self.max_workers = max_workers

    def build(
        self,
        clusters: List[AssertionCluster],
        assertions: List[ZonedAssertion],
        doc_id: str,
        doc_title: str,
        doc_language: str,
        global_view_summary: str,
    ) -> Tuple[Subject, List[Theme], List[Concept]]:
        """
        Construit la structure sémantique depuis les clusters.

        Args:
            clusters: Clusters d'assertions (sortie de Pass 1.B)
            assertions: Toutes les assertions
            doc_id: ID du document
            doc_title: Titre du document
            doc_language: Langue du document
            global_view_summary: Résumé du meta-document

        Returns:
            (Subject, list[Theme], list[Concept])
        """
        logger.info(
            f"[OSMOSE:Pass1:V2.2:1C] Structuration de {len(clusters)} clusters"
        )

        # Phase C.1: Nommage des concepts
        self._name_concepts(clusters, assertions, doc_language)

        # Phase C.2: Regroupement en thèmes
        themes = self._group_into_themes(
            clusters, assertions, doc_id, doc_title, doc_language
        )

        # Phase C.3: Sujet
        subject = self._derive_subject(
            themes, doc_id, doc_title, doc_language, global_view_summary
        )

        # Construire les Concept depuis les clusters
        concepts = self._build_concepts(clusters, doc_id)

        logger.info(
            f"[OSMOSE:Pass1:V2.2:1C] Résultat: 1 subject, "
            f"{len(themes)} thèmes, {len(concepts)} concepts"
        )

        return subject, themes, concepts

    def _name_concepts(
        self,
        clusters: List[AssertionCluster],
        assertions: List[ZonedAssertion],
        doc_language: str,
    ) -> None:
        """
        Phase C.1: Nommer chaque cluster via LLM (parallélisé).

        Modifie les clusters in-place (concept_name, definition, variants, keywords).
        """
        if not self.llm_client:
            # Fallback: nommage heuristique
            for i, cluster in enumerate(clusters):
                sample_texts = self._get_sample_texts(cluster, assertions, max_n=3)
                cluster.concept_name = f"Concept_{i + 1}"
                cluster.definition = sample_texts[0][:100] if sample_texts else ""
                cluster.keywords = self._extract_keywords_heuristic(sample_texts)
            return

        def _name_one(cluster: AssertionCluster) -> None:
            sample_texts = self._get_sample_texts(cluster, assertions, max_n=7)
            prompt = self._build_naming_prompt(sample_texts, doc_language)
            try:
                response = self.llm_client.generate(
                    system_prompt=(
                        "Tu es un expert en analyse sémantique. "
                        "Réponds UNIQUEMENT en JSON valide."
                    ),
                    user_prompt=prompt,
                    max_tokens=500,
                    temperature=0.2,
                )
                parsed = self._parse_naming_response(response)
                cluster.concept_name = parsed.get("name", f"Concept_{cluster.cluster_id}")
                cluster.definition = parsed.get("definition", "")
                cluster.variants = parsed.get("variants", [])
                cluster.keywords = parsed.get("keywords", [])
            except Exception as e:
                logger.warning(
                    f"[OSMOSE:Pass1:V2.2:1C] Naming failed for {cluster.cluster_id}: {e}"
                )
                cluster.concept_name = f"Concept_{cluster.cluster_id}"
                cluster.definition = sample_texts[0][:100] if sample_texts else ""

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(_name_one, cl): cl for cl in clusters}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    cl = futures[future]
                    logger.warning(
                        f"[OSMOSE:Pass1:V2.2:1C] Error naming {cl.cluster_id}: {e}"
                    )

    def _group_into_themes(
        self,
        clusters: List[AssertionCluster],
        assertions: List[ZonedAssertion],
        doc_id: str,
        doc_title: str,
        doc_language: str,
    ) -> List[Theme]:
        """Phase C.2: Regrouper les concepts en thèmes."""
        if not clusters:
            return []

        if not self.llm_client:
            # Fallback: un thème par zone
            zone_groups: Dict[str, List[AssertionCluster]] = {}
            for cl in clusters:
                primary_zone = cl.zone_ids[0] if cl.zone_ids else "z1"
                zone_groups.setdefault(primary_zone, []).append(cl)

            themes = []
            for zone_id, group in zone_groups.items():
                theme_id = f"theme_{doc_id}_{zone_id}"
                theme_name = f"Thème {zone_id}"
                if group and group[0].concept_name:
                    theme_name = f"Thème: {group[0].concept_name}"
                themes.append(Theme(
                    theme_id=theme_id,
                    name=theme_name,
                    scoped_to_sections=[],
                ))
                for cl in group:
                    cl.theme_id = theme_id
            return themes

        # Préparer le prompt
        concept_descriptions = []
        for i, cl in enumerate(clusters):
            sample = self._get_sample_texts(cl, assertions, max_n=2)
            desc = (
                f"- Concept «{cl.concept_name}» (zones: {', '.join(cl.zone_ids)}, "
                f"support: {cl.support_count}): "
                f"{'; '.join(sample[:2])}"
            )
            concept_descriptions.append(desc)

        prompt = (
            f"Document: \"{doc_title}\"\n"
            f"Langue: {doc_language}\n\n"
            f"Voici {len(clusters)} concepts identifiés dans ce document:\n"
            + "\n".join(concept_descriptions) + "\n\n"
            "Regroupe ces concepts en 3-15 thèmes cohérents.\n"
            "Chaque thème = un axe de lecture du document.\n\n"
            "Réponds en JSON:\n"
            '{"themes": [{"name": "...", "concept_indices": [0, 2, 5]}]}'
        )

        try:
            response = self.llm_client.generate(
                system_prompt=(
                    "Tu es un expert en structuration sémantique de documents. "
                    "Réponds UNIQUEMENT en JSON valide."
                ),
                user_prompt=prompt,
                max_tokens=2000,
                temperature=0.3,
            )
            parsed = self._parse_json_response(response)
            theme_defs = parsed.get("themes", [])
        except Exception as e:
            logger.warning(
                f"[OSMOSE:Pass1:V2.2:1C] Theme grouping failed: {e}, using fallback"
            )
            theme_defs = [{"name": "Thème principal", "concept_indices": list(range(len(clusters)))}]

        # Construire les objets Theme
        themes = []
        for t_idx, t_def in enumerate(theme_defs):
            theme_id = f"theme_{doc_id}_{t_idx}"
            themes.append(Theme(
                theme_id=theme_id,
                name=t_def.get("name", f"Thème {t_idx + 1}"),
                scoped_to_sections=[],
            ))
            # Assigner le theme_id aux clusters
            for ci in t_def.get("concept_indices", []):
                if 0 <= ci < len(clusters):
                    clusters[ci].theme_id = theme_id

        # Clusters sans thème: assigner au premier thème
        if themes:
            for cl in clusters:
                if not cl.theme_id:
                    cl.theme_id = themes[0].theme_id

        return themes

    def _derive_subject(
        self,
        themes: List[Theme],
        doc_id: str,
        doc_title: str,
        doc_language: str,
        global_view_summary: str,
    ) -> Subject:
        """Phase C.3: Dériver le sujet du document."""
        if not self.llm_client:
            return Subject(
                subject_id=f"subject_{doc_id}",
                name=doc_title or "Document sans titre",
                text=doc_title or "Document sans titre",
                structure=DocumentStructure.CENTRAL,
                language=doc_language,
            )

        theme_names = [t.name for t in themes]
        prompt = (
            f"Document: \"{doc_title}\"\n"
            f"Résumé: {global_view_summary[:2000]}\n"
            f"Thèmes identifiés: {', '.join(theme_names)}\n\n"
            "Propose un sujet résumant ce document en 1 phrase (max 15 mots).\n"
            "Réponds en JSON:\n"
            '{"subject": "...", "structure": "CENTRAL|TRANSVERSAL|CONTEXTUAL"}'
        )

        try:
            response = self.llm_client.generate(
                system_prompt="Tu es un expert en analyse documentaire. Réponds en JSON.",
                user_prompt=prompt,
                max_tokens=300,
                temperature=0.2,
            )
            parsed = self._parse_json_response(response)
            subject_text = parsed.get("subject", doc_title or "Document")
            structure_str = parsed.get("structure", "CENTRAL")
            try:
                structure = DocumentStructure(structure_str)
            except ValueError:
                structure = DocumentStructure.CENTRAL
        except Exception as e:
            logger.warning(f"[OSMOSE:Pass1:V2.2:1C] Subject derivation failed: {e}")
            subject_text = doc_title or "Document"
            structure = DocumentStructure.CENTRAL

        return Subject(
            subject_id=f"subject_{doc_id}",
            name=subject_text,
            text=subject_text,
            structure=structure,
            language=doc_language,
        )

    def _build_concepts(
        self,
        clusters: List[AssertionCluster],
        doc_id: str,
    ) -> List[Concept]:
        """Construit les Concept depuis les clusters nommés."""
        concepts = []
        for i, cl in enumerate(clusters):
            try:
                role = ConceptRole(cl.role)
            except ValueError:
                role = ConceptRole.STANDARD

            concepts.append(Concept(
                concept_id=f"concept_{doc_id}_{i}",
                theme_id=cl.theme_id or "",
                name=cl.concept_name or f"Concept_{i}",
                definition=cl.definition,
                role=role,
                variants=cl.variants,
                lex_key=(cl.concept_name or "").lower().replace(" ", "_"),
                # V2.2: lexical_triggers vide (pas de matching lexical)
                # mais keywords conservés dans variants pour navigation UI
                lexical_triggers=[],
            ))
        return concepts

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _get_sample_texts(
        self,
        cluster: AssertionCluster,
        assertions: List[ZonedAssertion],
        max_n: int = 5,
    ) -> List[str]:
        """Récupère N assertions représentatives du cluster."""
        texts = []
        for idx in cluster.assertion_indices[:max_n]:
            if 0 <= idx < len(assertions):
                texts.append(assertions[idx].text)
        return texts

    def _extract_keywords_heuristic(self, texts: List[str]) -> List[str]:
        """Extraction de mots-clés par fréquence (heuristique sans LLM)."""
        from collections import Counter

        words = []
        stop_words = {
            "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou",
            "en", "à", "au", "aux", "pour", "par", "sur", "dans", "avec",
            "est", "sont", "a", "ont", "the", "is", "are", "of", "and",
            "to", "in", "for", "with", "that", "this", "it", "on", "be",
        }
        for text in texts:
            for word in text.lower().split():
                word = word.strip(".,;:!?()[]{}\"'")
                if len(word) > 3 and word not in stop_words:
                    words.append(word)

        counter = Counter(words)
        return [w for w, _ in counter.most_common(5)]

    def _build_naming_prompt(
        self, sample_texts: List[str], doc_language: str
    ) -> str:
        """Construit le prompt de nommage d'un cluster."""
        assertions_block = "\n".join(f"- {t}" for t in sample_texts)
        return (
            f"Voici un groupe d'assertions extraites d'un document technique "
            f"(langue: {doc_language}):\n\n"
            f"{assertions_block}\n\n"
            "1. Propose un nom court et descriptif (max 5 mots)\n"
            "2. Propose une définition en 1 phrase\n"
            "3. Propose 2-3 alias/variantes\n"
            "4. Propose 3-5 mots-clés\n\n"
            "Réponds en JSON:\n"
            '{"name": "...", "definition": "...", "variants": ["..."], "keywords": ["..."]}'
        )

    def _parse_naming_response(self, response: str) -> Dict:
        """Parse la réponse JSON de nommage."""
        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> Dict:
        """Parse une réponse JSON, avec gestion des blocs markdown."""
        text = response.strip()

        # Retirer les blocs markdown ```json ... ```
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Essayer de trouver le premier { ... }
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                try:
                    return json.loads(text[brace_start:brace_end + 1])
                except json.JSONDecodeError:
                    pass
            logger.warning(
                f"[OSMOSE:Pass1:V2.2:1C] Failed to parse JSON response: {text[:200]}"
            )
            return {}
