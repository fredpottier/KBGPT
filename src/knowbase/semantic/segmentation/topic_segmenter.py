"""
🌊 OSMOSE Semantic Intelligence V2.1 - Topic Segmenter

Segmentation sémantique de documents en topics cohérents
"""

from typing import List, Dict, Optional
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
import logging
import re

try:
    from hdbscan import HDBSCAN
    HDBSCAN_AVAILABLE = True
except ImportError:
    HDBSCAN_AVAILABLE = False
    logging.warning("[OSMOSE] HDBSCAN not installed, will use Agglomerative only")

from ..models import Topic, Window
from ..utils.embeddings import get_embedder
from ..utils.ner_manager import get_ner_manager
from ..utils.language_detector import get_language_detector

logger = logging.getLogger(__name__)


class TopicSegmenter:
    """
    Segmente documents en topics sémantiquement cohérents.

    Pipeline:
    1. Structural segmentation (headers H1-H3)
    2. Semantic windowing (3000 chars, 25% overlap)
    3. Embeddings multilingues (cached)
    4. Clustering (HDBSCAN primary + Agglomerative fallback)
    5. Anchor extraction (NER multilingue + TF-IDF)
    6. Cohesion validation (threshold 0.65)

    Phase 1 V2.1 - Semaines 3-4
    """

    def __init__(self, config):
        """
        Initialise le segmenteur de topics.

        Args:
            config: Configuration SemanticConfig
        """
        self.config = config
        self.segmentation_config = config.segmentation

        # Composants utils
        self.embedder = get_embedder(config)
        self.ner = get_ner_manager(config)
        self.language_detector = get_language_detector(config)

        logger.info(
            f"[OSMOSE] TopicSegmenter initialisé "
            f"(window_size={self.segmentation_config.window_size}, "
            f"overlap={self.segmentation_config.overlap})"
        )

    async def segment_document(
        self,
        document_id: str,
        text: str,
        detect_language: bool = True
    ) -> List[Topic]:
        """
        Segmente un document en topics sémantiquement cohérents.

        Args:
            document_id: ID unique du document
            text: Contenu textuel complet
            detect_language: Détecter langue automatiquement (default: True)

        Returns:
            List[Topic]: Liste de topics identifiés
        """
        logger.info(f"[OSMOSE] Segmenting document: {document_id} ({len(text)} chars)")

        # Détection langue globale (optionnel)
        doc_language = None
        if detect_language:
            doc_language = self.language_detector.detect(text[:2000])
            logger.info(f"[OSMOSE] Document language detected: {doc_language}")

        # 1. Structural segmentation (sections via headers)
        sections = self._extract_sections(text)
        logger.info(f"[OSMOSE] Extracted {len(sections)} structural sections")

        all_topics = []

        for section in sections:
            section_text = section["text"]

            if len(section_text) < 500:  # Skip sections trop courtes
                logger.debug(f"[OSMOSE] Skipping short section: {section['path']}")
                continue

            # 2. Windowing
            windows = self._create_windows(
                section_text,
                size=self.segmentation_config.window_size,
                overlap=self.segmentation_config.overlap
            )

            if not windows:
                continue

            logger.debug(
                f"[OSMOSE] Section '{section['path']}': {len(windows)} windows"
            )

            # 3. Embeddings
            window_texts = [w.text for w in windows]
            embeddings = self.embedder.encode(window_texts)

            # 4. Clustering (HDBSCAN + fallback)
            clusters = self._cluster_with_fallbacks(windows, embeddings)
            logger.debug(f"[OSMOSE] Found {len(clusters)} clusters")

            # 5. Pour chaque cluster → créer topic
            for cluster_id, cluster_windows in clusters.items():
                if len(cluster_windows) == 0:
                    continue

                # Anchors (NER multilingue + TF-IDF)
                anchors = self._extract_anchors_multilingual(
                    cluster_windows,
                    language=doc_language
                )

                # Cohesion score
                cluster_indices = [windows.index(w) for w in cluster_windows]
                cluster_embeddings = embeddings[cluster_indices]
                cohesion = self._calculate_cohesion(cluster_embeddings)

                # Filter par cohesion threshold
                if cohesion < self.segmentation_config.cohesion_threshold:
                    logger.debug(
                        f"[OSMOSE] Skipping low cohesion topic: {cohesion:.2f} < "
                        f"{self.segmentation_config.cohesion_threshold}"
                    )
                    continue

                # Créer Topic
                topic = Topic(
                    topic_id=f"{document_id}_sec{section['id']}_c{cluster_id}",
                    document_id=document_id,
                    section_path=section["path"],
                    windows=cluster_windows,
                    anchors=anchors,
                    cohesion_score=cohesion
                )

                all_topics.append(topic)

        logger.info(
            f"[OSMOSE] ✅ Segmentation complete: {len(all_topics)} topics "
            f"(avg cohesion: {np.mean([t.cohesion_score for t in all_topics]):.2f})"
        )

        return all_topics

    def _extract_sections(self, text: str) -> List[Dict]:
        """
        Extraction sections structurelles via headers (Markdown-style).

        Détecte:
        - Headers Markdown: # H1, ## H2, ### H3
        - Headers style: 1., 1.1, 1.1.1

        Args:
            text: Texte complet

        Returns:
            List[Dict]: [{id, path, text, start, end}]
        """
        sections = []

        # Pattern Markdown headers
        header_pattern = r'^(#{1,3})\s+(.+)$'

        # Pattern numérotation (1., 1.1, 1.1.1)
        numbering_pattern = r'^(\d+(?:\.\d+)*)\.\s+(.+)$'

        lines = text.split('\n')
        current_section = {
            "id": 0,
            "path": "root",
            "text": "",
            "start": 0,
            "end": 0
        }
        current_pos = 0
        section_id = 0

        for i, line in enumerate(lines):
            line_len = len(line) + 1  # +1 pour \n

            # Check Markdown header
            md_match = re.match(header_pattern, line, re.MULTILINE)
            if md_match:
                # Sauvegarder section précédente si non-vide
                if current_section["text"].strip():
                    current_section["end"] = current_pos
                    sections.append(current_section.copy())

                # Nouvelle section
                section_id += 1
                level = len(md_match.group(1))
                title = md_match.group(2).strip()
                current_section = {
                    "id": section_id,
                    "path": f"{'#' * level} {title}",
                    "text": "",
                    "start": current_pos + line_len,
                    "end": 0
                }

            # Check numérotation
            elif re.match(numbering_pattern, line, re.MULTILINE):
                num_match = re.match(numbering_pattern, line, re.MULTILINE)
                if current_section["text"].strip():
                    current_section["end"] = current_pos
                    sections.append(current_section.copy())

                section_id += 1
                numbering = num_match.group(1)
                title = num_match.group(2).strip()
                current_section = {
                    "id": section_id,
                    "path": f"{numbering} {title}",
                    "text": "",
                    "start": current_pos + line_len,
                    "end": 0
                }

            else:
                # Ajouter ligne à section courante
                current_section["text"] += line + "\n"

            current_pos += line_len

        # Dernière section
        if current_section["text"].strip():
            current_section["end"] = current_pos
            sections.append(current_section)

        # Si aucun header détecté → tout le texte = 1 section
        if not sections:
            sections = [{
                "id": 0,
                "path": "root",
                "text": text,
                "start": 0,
                "end": len(text)
            }]

        return sections

    def _create_windows(
        self,
        text: str,
        size: int,
        overlap: float
    ) -> List[Window]:
        """
        Crée fenêtres sliding avec overlap.

        Args:
            text: Texte à découper
            size: Taille fenêtre (chars)
            overlap: Pourcentage overlap (0.0 - 1.0)

        Returns:
            List[Window]: Fenêtres créées
        """
        windows = []
        step = int(size * (1 - overlap))

        for i in range(0, len(text), step):
            window_text = text[i:i + size]

            # Skip fenêtres trop petites (< 50% size)
            if len(window_text) < size * 0.5:
                continue

            window = Window(
                text=window_text,
                start=i,
                end=i + len(window_text)
            )
            windows.append(window)

        return windows

    def _cluster_with_fallbacks(
        self,
        windows: List[Window],
        embeddings: np.ndarray
    ) -> Dict[int, List[Window]]:
        """
        Clustering avec stratégie robuste (HDBSCAN → Agglomerative).

        Args:
            windows: Liste fenêtres
            embeddings: Embeddings correspondants

        Returns:
            Dict[int, List[Window]]: {cluster_id: [windows]}
        """
        if len(windows) < self.segmentation_config.min_cluster_size:
            # Trop peu de windows → 1 cluster unique
            return {0: windows}

        cluster_labels = None

        # Tentative HDBSCAN (si disponible)
        if HDBSCAN_AVAILABLE and self.segmentation_config.clustering_method == "HDBSCAN":
            try:
                # HDBSCAN avec euclidean sur embeddings normalisés
                # (équivalent à distance cosine car embeddings sont normalisés)
                clusterer = HDBSCAN(
                    min_cluster_size=self.segmentation_config.min_cluster_size,
                    metric='euclidean',
                    cluster_selection_method='eom',
                    min_samples=1
                )
                cluster_labels = clusterer.fit_predict(embeddings)

                # Calculer et logger le taux d'outliers (recommandation OpenAI)
                outliers = cluster_labels == -1
                outlier_count = outliers.sum()
                outlier_rate = outlier_count / len(cluster_labels) if len(cluster_labels) > 0 else 0.0

                logger.info(
                    f"[OSMOSE] HDBSCAN metrics: outlier_rate={outlier_rate:.2%} "
                    f"({outlier_count}/{len(cluster_labels)} windows)"
                )

                # Vérifier si clusters trouvés (pas que du bruit -1)
                unique_labels = set(cluster_labels)
                if len(unique_labels) > 1 and -1 in unique_labels:
                    unique_labels.remove(-1)

                if len(unique_labels) >= 1:
                    logger.debug(f"[OSMOSE] HDBSCAN: {len(unique_labels)} clusters found")

                    # Warning si taux d'outliers élevé (calibration à ajuster)
                    if outlier_rate > 0.3:
                        logger.warning(
                            f"[OSMOSE] High HDBSCAN outlier rate ({outlier_rate:.2%}). "
                            "Consider adjusting min_cluster_size or using Agglomerative on outliers."
                        )
                else:
                    logger.debug("[OSMOSE] HDBSCAN found only noise, fallback")
                    cluster_labels = None

            except Exception as e:
                logger.warning(f"[OSMOSE] HDBSCAN failed: {e}, fallback to Agglomerative")
                cluster_labels = None

        # Fallback Agglomerative
        if cluster_labels is None:
            n_clusters = max(2, min(len(windows) // 5, self.segmentation_config.max_windows_per_topic))

            try:
                # AgglomerativeClustering avec euclidean sur embeddings normalisés
                # (équivalent à distance cosine car embeddings sont normalisés)
                clusterer = AgglomerativeClustering(
                    n_clusters=n_clusters,
                    metric='euclidean',
                    linkage='ward'  # ward est optimal pour euclidean
                )
                cluster_labels = clusterer.fit_predict(embeddings)
                logger.debug(f"[OSMOSE] Agglomerative: {n_clusters} clusters")

            except Exception as e:
                logger.error(f"[OSMOSE] Agglomerative clustering failed: {e}")
                # Ultimate fallback: tout dans 1 cluster
                return {0: windows}

        # Construire dict clusters
        clusters = {}
        for i, label in enumerate(cluster_labels):
            if label == -1:  # Noise HDBSCAN
                continue

            if label not in clusters:
                clusters[label] = []

            clusters[label].append(windows[i])

        return clusters

    def _extract_anchors_multilingual(
        self,
        windows: List[Window],
        language: Optional[str] = None
    ) -> List[str]:
        """
        Extrait anchors (entités clés + keywords) multilingue.

        Méthode:
        1. NER multilingue (primary)
        2. TF-IDF keywords (fallback si NER insuffisant)

        Args:
            windows: Fenêtres du topic
            language: Langue détectée (optionnel)

        Returns:
            List[str]: Anchors uniques (max 20)
        """
        # Concaténer tout le texte
        all_text = " ".join([w.text for w in windows])

        # Détection langue si non fournie
        if language is None:
            language = self.language_detector.detect(all_text[:1000])

        # NER multilingue
        entities = self.ner.extract_entities(all_text, language=language)
        anchors = [ent["text"] for ent in entities]

        logger.debug(f"[OSMOSE] NER found {len(anchors)} entities (lang: {language})")

        # TF-IDF keywords (fallback si NER < 5)
        if len(anchors) < 5:
            tfidf_keywords = self._tfidf_keywords(windows, top_k=10)
            anchors.extend(tfidf_keywords)
            logger.debug(f"[OSMOSE] TF-IDF added {len(tfidf_keywords)} keywords")

        # Dédupliquer + limiter à 20
        unique_anchors = sorted(set(anchors))[:20]

        return unique_anchors

    def _tfidf_keywords(self, windows: List[Window], top_k: int = 10) -> List[str]:
        """
        Extrait keywords TF-IDF.

        Args:
            windows: Fenêtres du topic
            top_k: Nombre de keywords

        Returns:
            List[str]: Top keywords
        """
        texts = [w.text for w in windows]

        if len(texts) < 2:
            # Fallback: split simple
            words = " ".join(texts).split()
            # Retirer stop words basiques
            stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
            keywords = [w for w in words if len(w) > 3 and w.lower() not in stop_words]
            return list(set(keywords))[:top_k]

        try:
            vectorizer = TfidfVectorizer(
                max_features=top_k,
                stop_words='english',  # Basic stop words
                ngram_range=(1, 2)
            )
            tfidf_matrix = vectorizer.fit_transform(texts)
            feature_names = vectorizer.get_feature_names_out()

            # Top keywords par score TF-IDF moyen
            tfidf_scores = tfidf_matrix.mean(axis=0).A1
            top_indices = tfidf_scores.argsort()[-top_k:][::-1]

            keywords = [feature_names[i] for i in top_indices]
            return keywords

        except Exception as e:
            logger.warning(f"[OSMOSE] TF-IDF extraction failed: {e}")
            return []

    def _calculate_cohesion(self, embeddings: np.ndarray) -> float:
        """
        Calcule cohésion intra-cluster (similarité cosine moyenne).

        Args:
            embeddings: Embeddings du cluster

        Returns:
            float: Cohesion score [0.0, 1.0]
        """
        if len(embeddings) < 2:
            return 1.0

        # Similarité pairwise
        sim_matrix = cosine_similarity(embeddings)

        # Moyenne (exclure diagonale)
        np.fill_diagonal(sim_matrix, 0)
        n = len(embeddings)
        mean_similarity = sim_matrix.sum() / (n * (n - 1))

        return float(mean_similarity)


# ===================================
# FACTORY PATTERN
# ===================================

_segmenter_instance: Optional[TopicSegmenter] = None


def get_topic_segmenter(config) -> TopicSegmenter:
    """
    Récupère l'instance singleton du segmenteur.

    Args:
        config: Configuration SemanticConfig

    Returns:
        TopicSegmenter: Instance unique
    """
    global _segmenter_instance

    if _segmenter_instance is None:
        _segmenter_instance = TopicSegmenter(config)

    return _segmenter_instance
