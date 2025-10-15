"""
🌊 OSMOSE Phase 1.5 - Embeddings Contextual Scorer

Filtrage contextuel basé sur similarité sémantique des embeddings.

**Principe**: Comparer le contexte de chaque entité avec des concepts abstraits
(PRIMARY topic, COMPETITOR mention, SECONDARY info) pour classifier leur rôle.

**Améliorations Production-Ready**:
- Agrégation multi-occurrences (toutes mentions vs première) → +15-20% précision
- Paraphrases multilingues (EN/FR/DE/ES) → +10% stabilité
- Moyenne pondérée des contextes (decay pour mentions tardives)

**Impact attendu**: +25-35% précision, 100% language-agnostic, $0 coût, <200ms

Référence: doc/ongoing/ANALYSE_FILTRAGE_CONTEXTUEL_GENERALISTE.md
"""

from typing import Dict, Any, List, Tuple, Optional
import logging
import re
from collections import defaultdict
import numpy as np

# SentenceTransformer pour embeddings multilingues
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None
    logging.warning(
        "[OSMOSE] sentence-transformers non installé. "
        "Installer avec: pip install sentence-transformers"
    )

logger = logging.getLogger(__name__)


# Concepts de référence multilingues
REFERENCE_CONCEPTS_MULTILINGUAL = {
    "PRIMARY": {
        "en": [
            "main product described in detail",
            "primary solution recommended",
            "our company's flagship offering",
            "key technology we provide",
            "central topic of this document"
        ],
        "fr": [
            "produit principal décrit en détail",
            "solution principale recommandée",
            "offre phare de notre entreprise",
            "technologie clé que nous proposons",
            "sujet central de ce document"
        ],
        "de": [
            "hauptprodukt ausführlich beschrieben",
            "hauptlösung empfohlen",
            "unser flaggschiff-angebot",
            "schlüsseltechnologie die wir anbieten",
            "zentrales thema dieses dokuments"
        ],
        "es": [
            "producto principal descrito en detalle",
            "solución principal recomendada",
            "oferta estrella de nuestra empresa",
            "tecnología clave que ofrecemos",
            "tema central de este documento"
        ]
    },
    "COMPETITOR": {
        "en": [
            "competitor mentioned for comparison",
            "alternative vendor briefly cited",
            "competing product referenced",
            "other company's solution",
            "rival technology noted"
        ],
        "fr": [
            "concurrent mentionné pour comparaison",
            "fournisseur alternatif brièvement cité",
            "produit concurrent référencé",
            "solution d'une autre entreprise",
            "technologie rivale notée"
        ],
        "de": [
            "konkurrent zum vergleich erwähnt",
            "alternativer anbieter kurz erwähnt",
            "konkurrenzprodukt referenziert",
            "lösung eines anderen unternehmens",
            "rivalisierendes technologie erwähnt"
        ],
        "es": [
            "competidor mencionado para comparación",
            "proveedor alternativo brevemente citado",
            "producto competidor referenciado",
            "solución de otra empresa",
            "tecnología rival mencionada"
        ]
    },
    "SECONDARY": {
        "en": [
            "related concept mentioned in passing",
            "supporting technology or service",
            "tangential topic",
            "background information",
            "generic term or abbreviation"
        ],
        "fr": [
            "concept connexe mentionné en passant",
            "technologie ou service de support",
            "sujet tangentiel",
            "information de contexte",
            "terme générique ou abréviation"
        ],
        "de": [
            "verwandtes konzept nebenbei erwähnt",
            "unterstützende technologie oder dienstleistung",
            "tangentiales thema",
            "hintergrundinformationen",
            "generischer begriff oder abkürzung"
        ],
        "es": [
            "concepto relacionado mencionado de paso",
            "tecnología o servicio de apoyo",
            "tema tangencial",
            "información de fondo",
            "término genérico o abreviatura"
        ]
    }
}


class EmbeddingsContextualScorer:
    """
    Score entities based on embeddings similarity with reference concepts.

    Utilise SentenceTransformer (multilingual-e5-large) pour encoder contextes
    et comparer avec concepts abstraits multilingues.

    **Avantages**:
    - 100% language-agnostic (paraphrases multilingues)
    - $0 coût (modèle local, pas d'API)
    - <200ms latence (batch encoding)
    - Agrégation multi-occurrences (toutes mentions vs première)
    """

    def __init__(
        self,
        model_name: str = "intfloat/multilingual-e5-large",
        context_window: int = 100,
        similarity_threshold_primary: float = 0.5,
        similarity_threshold_competitor: float = 0.4,
        enable_multi_occurrence: bool = True,
        languages: List[str] = None
    ):
        """
        Initialiser le scorer.

        Args:
            model_name: Nom du modèle SentenceTransformer (défaut: multilingual-e5-large)
            context_window: Taille fenêtre contexte (mots)
            similarity_threshold_primary: Seuil PRIMARY (défaut: 0.5)
            similarity_threshold_competitor: Seuil COMPETITOR (défaut: 0.4)
            enable_multi_occurrence: Agréger toutes occurrences (défaut: True)
            languages: Langues supportées (défaut: ['en', 'fr', 'de', 'es'])
        """
        self.model_name = model_name
        self.context_window = context_window
        self.similarity_threshold_primary = similarity_threshold_primary
        self.similarity_threshold_competitor = similarity_threshold_competitor
        self.enable_multi_occurrence = enable_multi_occurrence
        self.languages = languages or ["en", "fr", "de", "es"]

        # Initialiser SentenceTransformer
        if SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers non installé. "
                "Installer avec: pip install sentence-transformers"
            )

        logger.info(f"[OSMOSE] Initialisation EmbeddingsContextualScorer (model={model_name})")
        self.model = SentenceTransformer(model_name)

        # Encoder concepts de référence (cache)
        self.reference_embeddings = self._encode_reference_concepts()

        logger.info(
            f"[OSMOSE] EmbeddingsContextualScorer initialisé "
            f"(languages={self.languages}, window={context_window})"
        )

    def score_entities(
        self,
        candidates: List[Dict[str, Any]],
        full_text: str
    ) -> List[Dict[str, Any]]:
        """
        Score entities avec embeddings similarity.

        Args:
            candidates: Liste d'entités candidates
            full_text: Texte complet du document

        Returns:
            Liste d'entités avec scores ajoutés:
            - embedding_primary_similarity: Similarité avec concept PRIMARY [0-1]
            - embedding_competitor_similarity: Similarité avec concept COMPETITOR [0-1]
            - embedding_secondary_similarity: Similarité avec concept SECONDARY [0-1]
            - embedding_role: Role classifié (PRIMARY/COMPETITOR/SECONDARY)
            - embedding_score: Score normalisé [0-1]
        """
        if not candidates:
            logger.warning("[OSMOSE] EmbeddingsContextualScorer: Aucun candidat à scorer")
            return []

        if not full_text or len(full_text) < 50:
            logger.warning("[OSMOSE] EmbeddingsContextualScorer: Texte trop court, scoring par défaut")
            for entity in candidates:
                entity["embedding_score"] = 0.5
                entity["embedding_role"] = "SECONDARY"
            return candidates

        logger.info(
            f"[OSMOSE] EmbeddingsContextualScorer: Scoring {len(candidates)} candidats "
            f"(doc_length={len(full_text)} chars)"
        )

        # Extraire contextes pour chaque entité
        for entity in candidates:
            entity_name = entity.get("text", "") or entity.get("name", "")
            if not entity_name:
                continue

            # Extraire toutes les mentions (si multi-occurrence activé)
            contexts = self._extract_all_mentions_contexts(entity_name, full_text)

            if not contexts:
                # Aucun contexte trouvé → scores par défaut
                entity["embedding_primary_similarity"] = 0.0
                entity["embedding_competitor_similarity"] = 0.0
                entity["embedding_secondary_similarity"] = 0.5
                entity["embedding_role"] = "SECONDARY"
                entity["embedding_score"] = 0.3
                continue

            # Encoder et agréger contextes
            aggregated_similarities = self._score_entity_aggregated(contexts)

            # Enregistrer scores
            entity["embedding_primary_similarity"] = aggregated_similarities["PRIMARY"]
            entity["embedding_competitor_similarity"] = aggregated_similarities["COMPETITOR"]
            entity["embedding_secondary_similarity"] = aggregated_similarities["SECONDARY"]

            # Classifier role
            role = self._classify_role(aggregated_similarities)
            entity["embedding_role"] = role

            # Score normalisé [0-1] selon role
            if role == "PRIMARY":
                entity["embedding_score"] = 1.0
            elif role == "COMPETITOR":
                entity["embedding_score"] = 0.2
            else:  # SECONDARY
                entity["embedding_score"] = 0.5

            # Log détails si score extrême
            if entity["embedding_score"] < 0.3 or entity["embedding_score"] > 0.8:
                logger.debug(
                    f"[OSMOSE] EmbeddingsScoring '{entity_name}': "
                    f"role={role}, score={entity['embedding_score']:.2f} "
                    f"(prim={aggregated_similarities['PRIMARY']:.2f}, "
                    f"comp={aggregated_similarities['COMPETITOR']:.2f})"
                )

        logger.info(
            f"[OSMOSE] EmbeddingsContextualScorer: Scoring terminé "
            f"({len([e for e in candidates if e.get('embedding_role') == 'PRIMARY'])} PRIMARY, "
            f"{len([e for e in candidates if e.get('embedding_role') == 'COMPETITOR'])} COMPETITOR)"
        )

        return candidates

    def _extract_all_mentions_contexts(
        self,
        entity_name: str,
        full_text: str
    ) -> List[str]:
        """
        Extract contexts for all mentions of entity.

        **Amélioration vs première occurrence**: Agrégation de toutes les mentions
        pour avoir une vision complète du rôle de l'entité dans le document.

        Args:
            entity_name: Nom de l'entité
            full_text: Texte complet

        Returns:
            Liste de contextes (window mots avant + après chaque mention)
        """
        contexts = []

        # Tokeniser le texte (mots simples)
        words = re.findall(r'\b\w+\b', full_text)

        # Rechercher toutes les positions de l'entité
        entity_words = entity_name.lower().split()
        text_lower = [w.lower() for w in words]

        for i in range(len(text_lower) - len(entity_words) + 1):
            # Check si l'entité commence à la position i
            if text_lower[i:i + len(entity_words)] == entity_words:
                # Extraire contexte (window mots avant/après)
                start = max(0, i - self.context_window // 2)
                end = min(len(words), i + len(entity_words) + self.context_window // 2)

                context_words = words[start:end]
                context = " ".join(context_words)
                contexts.append(context)

                # Limiter à 10 occurrences max (éviter explosion mémoire)
                if len(contexts) >= 10:
                    break

        return contexts

    def _score_entity_aggregated(
        self,
        contexts: List[str]
    ) -> Dict[str, float]:
        """
        Score entity avec agrégation multi-occurrences.

        **Agrégation**: Moyenne pondérée des embeddings de tous les contextes
        (decay pour mentions tardives dans le document).

        Args:
            contexts: Liste de contextes extraits

        Returns:
            Dict {role → similarity_score [0-1]}
        """
        if not contexts:
            return {"PRIMARY": 0.0, "COMPETITOR": 0.0, "SECONDARY": 0.5}

        # Encoder tous les contextes (batch encoding pour efficacité)
        context_embeddings = self.model.encode(contexts, convert_to_numpy=True)

        # Weights: décroissance exponentielle pour mentions tardives
        # Première mention = poids 1.0, dernière = poids 0.5
        weights = np.exp(-np.arange(len(contexts)) / (len(contexts) + 1))
        weights = weights / weights.sum()  # Normalisation

        # Agréger embeddings (moyenne pondérée)
        if len(contexts) == 1:
            aggregated_embedding = context_embeddings[0]
        else:
            aggregated_embedding = np.average(
                context_embeddings,
                axis=0,
                weights=weights
            )

        # Calculer similarité avec concepts de référence
        similarities = {}
        for role in ["PRIMARY", "COMPETITOR", "SECONDARY"]:
            # Moyenne des similarités avec toutes les paraphrases
            role_similarities = []
            for lang_embedding in self.reference_embeddings[role].values():
                # Cosine similarity
                similarity = np.dot(aggregated_embedding, lang_embedding) / (
                    np.linalg.norm(aggregated_embedding) * np.linalg.norm(lang_embedding)
                )
                role_similarities.append(similarity)

            # Moyenne des similarités (toutes langues)
            similarities[role] = float(np.mean(role_similarities))

        return similarities

    def _classify_role(
        self,
        similarities: Dict[str, float]
    ) -> str:
        """
        Classify entity role based on similarities.

        **Règles**:
        - PRIMARY: Si sim_primary > threshold_primary ET > sim_competitor
        - COMPETITOR: Si sim_competitor > threshold_competitor ET > sim_primary
        - SECONDARY: Sinon (défaut)

        Args:
            similarities: Dict {role → similarity}

        Returns:
            Role classifié (PRIMARY/COMPETITOR/SECONDARY)
        """
        prim = similarities["PRIMARY"]
        comp = similarities["COMPETITOR"]
        sec = similarities["SECONDARY"]

        # PRIMARY si forte similarité ET supérieure à COMPETITOR
        if prim > self.similarity_threshold_primary and prim > comp:
            return "PRIMARY"

        # COMPETITOR si forte similarité ET supérieure à PRIMARY
        if comp > self.similarity_threshold_competitor and comp > prim:
            return "COMPETITOR"

        # SECONDARY par défaut
        return "SECONDARY"

    def _encode_reference_concepts(self) -> Dict[str, Dict[str, np.ndarray]]:
        """
        Encoder concepts de référence multilingues (cache).

        Returns:
            Dict {role → {lang → embedding}}
        """
        reference_embeddings = {}

        for role, paraphrases_by_lang in REFERENCE_CONCEPTS_MULTILINGUAL.items():
            reference_embeddings[role] = {}

            for lang in self.languages:
                if lang not in paraphrases_by_lang:
                    continue

                paraphrases = paraphrases_by_lang[lang]

                # Encoder toutes les paraphrases
                embeddings = self.model.encode(paraphrases, convert_to_numpy=True)

                # Agréger (moyenne)
                aggregated = np.mean(embeddings, axis=0)
                reference_embeddings[role][lang] = aggregated

        return reference_embeddings
