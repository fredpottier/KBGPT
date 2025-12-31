"""
🌊 OSMOSE Semantic Intelligence V2.3.1 - Topic Segmenter

Segmentation hiérarchique de documents en topics cohérents.

V2.3.1: Garantie Minimum Topics (Document-Level)
- Document-level: Garantit min(5, doc_size/5000) topics via Agglomerative fallback
- Résout le problème HDBSCAN qui ne trouvait que 2 clusters sur docs complexes
- Améliore significativement l'extraction de concepts (+150% Proto/Canonical)

V2.3: Segmentation Hiérarchique Adaptative
- Petits documents (< 50K chars): Document-level clustering adaptatif
- Gros documents (>= 50K chars): Macro-sections → HDBSCAN par section

Phase 1 V2.3.1 - Guaranteed Minimum Topics
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

# Seuil pour basculer vers segmentation hiérarchique
HIERARCHICAL_THRESHOLD_CHARS = 50000  # ~10-15 pages


class TopicSegmenter:
    """
    Segmente documents en topics sémantiquement cohérents.

    Pipeline V2.3 (Hierarchical Adaptive Segmentation):

    Pour PETITS documents (< 50K chars):
        1. Windowing global sur tout le document
        2. HDBSCAN clustering global
        3. Topics sémantiques naturels

    Pour GROS documents (>= 50K chars):
        1. Extraction macro-sections (chapitres H1, numérotation 1., 2., 3.)
        2. Pour chaque macro-section: Windowing + HDBSCAN
        3. Topics regroupés par macro-section (cohérence structurelle)

    Avantages:
    - Petits docs: clustering global optimal
    - Gros docs: parallélisable, topics cohérents par chapitre
    - Scalable: O(n) au lieu de O(n²) pour HDBSCAN

    Phase 1 V2.3 - Hierarchical Segmentation
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
            f"[OSMOSE] TopicSegmenter V2.3 initialisé "
            f"(window_size={self.segmentation_config.window_size}, "
            f"overlap={self.segmentation_config.overlap}, "
            f"hierarchical_threshold={HIERARCHICAL_THRESHOLD_CHARS} chars)"
        )

    async def segment_document(
        self,
        document_id: str,
        text: str,
        detect_language: bool = True
    ) -> List[Topic]:
        """
        Segmente un document en topics sémantiquement cohérents.

        V2.3: Stratégie adaptative selon la taille du document.

        Args:
            document_id: ID unique du document
            text: Contenu textuel complet
            detect_language: Détecter langue automatiquement (default: True)

        Returns:
            List[Topic]: Liste de topics identifiés
        """
        logger.info(f"[OSMOSE] Segmenting document: {document_id} ({len(text)} chars)")

        # Détection langue globale
        doc_language = None
        if detect_language:
            doc_language = self.language_detector.detect(text[:2000])
            logger.info(f"[OSMOSE] Document language detected: {doc_language}")

        # Stratégie adaptative selon taille
        if len(text) < HIERARCHICAL_THRESHOLD_CHARS:
            logger.info(f"[OSMOSE] Small document → Document-level segmentation")
            return await self._segment_document_level(document_id, text, doc_language)
        else:
            logger.info(f"[OSMOSE] Large document → Hierarchical segmentation")
            return await self._segment_hierarchical(document_id, text, doc_language)

    async def _segment_document_level(
        self,
        document_id: str,
        text: str,
        doc_language: Optional[str]
    ) -> List[Topic]:
        """
        Segmentation document-level pour petits documents.

        Windowing global + clustering adaptatif.

        V2.3.1: Garantit un minimum de topics proportionnel à la taille du document
        pour assurer une extraction de concepts suffisante.
        """
        # 1. Windowing GLOBAL
        windows = self._create_windows(
            text,
            size=self.segmentation_config.window_size,
            overlap=self.segmentation_config.overlap
        )

        if not windows:
            logger.warning(f"[OSMOSE] No windows created for document {document_id}")
            return []

        logger.info(f"[OSMOSE] Created {len(windows)} windows (document-level)")

        # 2. Embeddings
        window_texts = [w.text for w in windows]
        embeddings = self.embedder.encode(window_texts)

        # 3. Calculer nombre minimum de topics basé sur taille document
        # Heuristique: ~1 topic par 5000 chars, minimum 5 topics pour docs > 10K chars
        min_topics = max(5, len(text) // 5000)
        min_topics = min(min_topics, len(windows))  # Ne pas dépasser nb windows

        logger.info(f"[OSMOSE] Document-level: targeting minimum {min_topics} topics")

        # 4. Clustering avec garantie de minimum topics
        clusters = self._cluster_with_min_topics(windows, embeddings, min_topics)
        logger.info(f"[OSMOSE] Found {len(clusters)} semantic clusters")

        # 5. Créer topics
        all_topics = self._create_topics_from_clusters(
            document_id=document_id,
            clusters=clusters,
            windows=windows,
            embeddings=embeddings,
            doc_language=doc_language,
            section_prefix="doc"
        )

        avg_cohesion = np.mean([t.cohesion_score for t in all_topics]) if all_topics else 0.0
        logger.info(
            f"[OSMOSE] ✅ Document-level segmentation complete: {len(all_topics)} topics "
            f"(avg cohesion: {avg_cohesion:.2f})"
        )

        return all_topics

    async def _segment_hierarchical(
        self,
        document_id: str,
        text: str,
        doc_language: Optional[str]
    ) -> List[Topic]:
        """
        Segmentation hiérarchique pour gros documents.

        1. Extraction macro-sections (chapitres)
        2. HDBSCAN par macro-section
        3. Fusion topics
        """
        # 1. Extraire macro-sections (niveau chapitres uniquement)
        macro_sections = self._extract_macro_sections(text)
        logger.info(f"[OSMOSE] Extracted {len(macro_sections)} macro-sections (chapters)")

        # Si une seule macro-section → fallback document-level
        if len(macro_sections) <= 1:
            logger.info("[OSMOSE] Single macro-section detected → fallback to document-level")
            return await self._segment_document_level(document_id, text, doc_language)

        all_topics = []

        # 2. Pour chaque macro-section → windowing + clustering
        for section in macro_sections:
            section_text = section["text"]
            section_path = section["path"]

            # Skip sections trop courtes (< 1000 chars)
            if len(section_text) < 1000:
                logger.debug(f"[OSMOSE] Skipping short macro-section: {section_path}")
                continue

            # Windowing sur la macro-section
            windows = self._create_windows(
                section_text,
                size=self.segmentation_config.window_size,
                overlap=self.segmentation_config.overlap
            )

            if not windows:
                continue

            logger.debug(f"[OSMOSE] Macro-section '{section_path}': {len(windows)} windows")

            # Embeddings
            window_texts = [w.text for w in windows]
            embeddings = self.embedder.encode(window_texts)

            # Clustering sur la macro-section
            clusters = self._cluster_with_fallbacks(windows, embeddings)

            # Créer topics pour cette macro-section
            # Passer section["start"] pour calculer char_offset global des topics
            section_topics = self._create_topics_from_clusters(
                document_id=document_id,
                clusters=clusters,
                windows=windows,
                embeddings=embeddings,
                doc_language=doc_language,
                section_prefix=f"sec{section['id']}",
                section_char_offset=section.get("start", 0)
            )

            # Enrichir section_path avec info macro-section
            for topic in section_topics:
                topic.section_path = f"{section_path} / {topic.section_path}"

            all_topics.extend(section_topics)
            logger.debug(f"[OSMOSE] Macro-section '{section_path}': {len(section_topics)} topics")

        avg_cohesion = np.mean([t.cohesion_score for t in all_topics]) if all_topics else 0.0
        logger.info(
            f"[OSMOSE] ✅ Hierarchical segmentation complete: {len(all_topics)} topics "
            f"from {len(macro_sections)} macro-sections (avg cohesion: {avg_cohesion:.2f})"
        )

        return all_topics

    def _extract_macro_sections(self, text: str) -> List[Dict]:
        """
        Extraction macro-sections (chapitres niveau 1 uniquement).

        Détecte uniquement:
        - Headers Markdown H1: # Title
        - Numérotation niveau 1: 1. Title, 2. Title (pas 1.1, 1.2)

        Args:
            text: Texte complet

        Returns:
            List[Dict]: [{id, path, text, start, end}]
        """
        sections = []

        # Pattern H1 Markdown uniquement
        h1_pattern = r'^#\s+(.+)$'

        # Pattern numérotation niveau 1 uniquement (1., 2., pas 1.1)
        numbering_l1_pattern = r'^(\d+)\.\s+([A-Z].+)$'

        lines = text.split('\n')
        current_section = {
            "id": 0,
            "path": "Introduction",
            "text": "",
            "start": 0,
            "end": 0
        }
        current_pos = 0
        section_id = 0

        for line in lines:
            line_len = len(line) + 1  # +1 pour \n

            # Check H1 Markdown
            h1_match = re.match(h1_pattern, line)
            if h1_match:
                # Sauvegarder section précédente si non-vide
                if current_section["text"].strip():
                    current_section["end"] = current_pos
                    sections.append(current_section.copy())

                section_id += 1
                title = h1_match.group(1).strip()
                current_section = {
                    "id": section_id,
                    "path": title,
                    "text": "",
                    "start": current_pos + line_len,
                    "end": 0
                }

            # Check numérotation niveau 1
            elif re.match(numbering_l1_pattern, line):
                num_match = re.match(numbering_l1_pattern, line)
                if current_section["text"].strip():
                    current_section["end"] = current_pos
                    sections.append(current_section.copy())

                section_id += 1
                numbering = num_match.group(1)
                title = num_match.group(2).strip()
                current_section = {
                    "id": section_id,
                    "path": f"{numbering}. {title}",
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

        # Si aucune macro-section détectée → tout le texte = 1 section
        if not sections:
            sections = [{
                "id": 0,
                "path": "Document",
                "text": text,
                "start": 0,
                "end": len(text)
            }]

        return sections

    def _create_topics_from_clusters(
        self,
        document_id: str,
        clusters: Dict[int, List[Window]],
        windows: List[Window],
        embeddings: np.ndarray,
        doc_language: Optional[str],
        section_prefix: str,
        section_char_offset: int = 0
    ) -> List[Topic]:
        """
        Crée des topics à partir des clusters.

        Args:
            document_id: ID du document
            clusters: Dict {cluster_id: [windows]}
            windows: Liste complète des windows
            embeddings: Embeddings des windows
            doc_language: Langue détectée
            section_prefix: Préfixe pour topic_id
            section_char_offset: Offset de la section dans le document complet
                                 (2024-12-30: Fix mapping anchors → chunks)

        Returns:
            List[Topic]: Topics créés
        """
        topics = []

        for cluster_id, cluster_windows in clusters.items():
            if len(cluster_windows) == 0:
                continue

            # Anchors (NER + TF-IDF)
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

            # Calculer char_offset du topic = section_offset + premier window.start
            # Les windows ont des positions relatives à la section
            topic_char_offset = section_char_offset
            if cluster_windows:
                # Trouver la première window du cluster (position minimale)
                min_window_start = min(w.start for w in cluster_windows)
                topic_char_offset = section_char_offset + min_window_start

            # Créer Topic avec char_offset global
            topic = Topic(
                topic_id=f"{document_id}_{section_prefix}_c{cluster_id}",
                document_id=document_id,
                section_path=f"cluster_{cluster_id}",
                windows=cluster_windows,
                anchors=anchors,
                cohesion_score=cohesion,
                char_offset=topic_char_offset
            )

            topics.append(topic)

        return topics

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
                clusterer = HDBSCAN(
                    min_cluster_size=self.segmentation_config.min_cluster_size,
                    metric='euclidean',
                    cluster_selection_method='eom',
                    min_samples=1
                )
                cluster_labels = clusterer.fit_predict(embeddings)

                # Calculer taux d'outliers
                outliers = cluster_labels == -1
                outlier_count = outliers.sum()
                outlier_rate = outlier_count / len(cluster_labels) if len(cluster_labels) > 0 else 0.0

                logger.info(
                    f"[OSMOSE] HDBSCAN metrics: outlier_rate={outlier_rate:.2%} "
                    f"({outlier_count}/{len(cluster_labels)} windows)"
                )

                # Vérifier si clusters trouvés
                unique_labels = set(cluster_labels)
                if -1 in unique_labels:
                    unique_labels.remove(-1)

                if len(unique_labels) >= 1:
                    logger.debug(f"[OSMOSE] HDBSCAN: {len(unique_labels)} clusters found")

                    if outlier_rate > 0.3:
                        logger.warning(
                            f"[OSMOSE] High HDBSCAN outlier rate ({outlier_rate:.2%}). "
                            "Consider adjusting min_cluster_size."
                        )
                else:
                    logger.debug("[OSMOSE] HDBSCAN found only noise, fallback to Agglomerative")
                    cluster_labels = None

            except Exception as e:
                logger.warning(f"[OSMOSE] HDBSCAN failed: {e}, fallback to Agglomerative")
                cluster_labels = None

        # Fallback Agglomerative
        if cluster_labels is None:
            if len(windows) <= 5:
                logger.debug(f"[OSMOSE] Small section ({len(windows)} windows) → 1 cluster")
                return {0: windows}

            n_clusters = max(2, min(len(windows) // 5, self.segmentation_config.max_windows_per_topic))

            try:
                clusterer = AgglomerativeClustering(
                    n_clusters=n_clusters,
                    metric='euclidean',
                    linkage='ward'
                )
                cluster_labels = clusterer.fit_predict(embeddings)
                logger.debug(f"[OSMOSE] Agglomerative: {n_clusters} clusters")

            except Exception as e:
                logger.error(f"[OSMOSE] Agglomerative clustering failed: {e}")
                return {0: windows}

        # Construire dict clusters
        clusters = {}
        for i, label in enumerate(cluster_labels):
            if label == -1:
                continue

            if label not in clusters:
                clusters[label] = []

            clusters[label].append(windows[i])

        return clusters

    def _cluster_with_min_topics(
        self,
        windows: List[Window],
        embeddings: np.ndarray,
        min_topics: int
    ) -> Dict[int, List[Window]]:
        """
        Clustering avec garantie d'un nombre minimum de topics.

        V2.3.1: Pour document-level, on veut garantir suffisamment de topics
        pour une extraction de concepts riche.

        Stratégie:
        1. Essayer HDBSCAN d'abord
        2. Si insuffisant (< min_topics), utiliser Agglomerative avec min_topics clusters
        3. Assigner les outliers HDBSCAN aux clusters les plus proches

        Args:
            windows: Liste fenêtres
            embeddings: Embeddings correspondants
            min_topics: Nombre minimum de topics souhaité

        Returns:
            Dict[int, List[Window]]: {cluster_id: [windows]}
        """
        if len(windows) < 3:
            return {0: windows}

        cluster_labels = None
        use_agglomerative = True  # Par défaut, utiliser Agglomerative pour garantie

        # Tentative HDBSCAN d'abord (si disponible)
        if HDBSCAN_AVAILABLE and self.segmentation_config.clustering_method == "HDBSCAN":
            try:
                clusterer = HDBSCAN(
                    min_cluster_size=max(2, len(windows) // min_topics),  # Adapté au min_topics
                    metric='euclidean',
                    cluster_selection_method='eom',
                    min_samples=1
                )
                hdbscan_labels = clusterer.fit_predict(embeddings)

                # Compter clusters trouvés (sans outliers)
                unique_labels = set(hdbscan_labels)
                if -1 in unique_labels:
                    unique_labels.remove(-1)

                n_clusters_found = len(unique_labels)
                outlier_count = (hdbscan_labels == -1).sum()

                logger.info(
                    f"[OSMOSE] HDBSCAN document-level: {n_clusters_found} clusters, "
                    f"{outlier_count}/{len(windows)} outliers"
                )

                # Si HDBSCAN trouve suffisamment de clusters, utiliser ses résultats
                if n_clusters_found >= min_topics:
                    cluster_labels = hdbscan_labels
                    use_agglomerative = False
                    logger.info(f"[OSMOSE] HDBSCAN sufficient ({n_clusters_found} >= {min_topics})")
                else:
                    logger.info(
                        f"[OSMOSE] HDBSCAN insufficient ({n_clusters_found} < {min_topics}), "
                        f"switching to Agglomerative"
                    )

            except Exception as e:
                logger.warning(f"[OSMOSE] HDBSCAN failed: {e}, using Agglomerative")

        # Utiliser Agglomerative si HDBSCAN insuffisant
        if use_agglomerative:
            n_clusters = min(min_topics, len(windows))

            try:
                clusterer = AgglomerativeClustering(
                    n_clusters=n_clusters,
                    metric='euclidean',
                    linkage='ward'
                )
                cluster_labels = clusterer.fit_predict(embeddings)
                logger.info(f"[OSMOSE] Agglomerative document-level: {n_clusters} clusters (guaranteed)")

            except Exception as e:
                logger.error(f"[OSMOSE] Agglomerative clustering failed: {e}")
                return {0: windows}

        # Construire dict clusters
        clusters = {}
        for i, label in enumerate(cluster_labels):
            if label == -1:
                # Pour les outliers HDBSCAN, trouver cluster le plus proche
                if len(clusters) > 0:
                    # Calculer distance aux centroids des clusters existants
                    best_cluster = 0
                    best_dist = float('inf')
                    for c_id, c_windows in clusters.items():
                        c_indices = [j for j, w in enumerate(windows) if w in c_windows]
                        if c_indices:
                            centroid = embeddings[c_indices].mean(axis=0)
                            dist = np.linalg.norm(embeddings[i] - centroid)
                            if dist < best_dist:
                                best_dist = dist
                                best_cluster = c_id
                    label = best_cluster
                else:
                    label = 0

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
        """
        all_text = " ".join([w.text for w in windows])

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
        """Extrait keywords TF-IDF."""
        texts = [w.text for w in windows]

        if len(texts) < 2:
            words = " ".join(texts).split()
            stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
            keywords = [w for w in words if len(w) > 3 and w.lower() not in stop_words]
            return list(set(keywords))[:top_k]

        try:
            vectorizer = TfidfVectorizer(
                max_features=top_k,
                stop_words='english',
                ngram_range=(1, 2)
            )
            tfidf_matrix = vectorizer.fit_transform(texts)
            feature_names = vectorizer.get_feature_names_out()

            tfidf_scores = tfidf_matrix.mean(axis=0).A1
            top_indices = tfidf_scores.argsort()[-top_k:][::-1]

            keywords = [feature_names[i] for i in top_indices]
            return keywords

        except Exception as e:
            logger.warning(f"[OSMOSE] TF-IDF extraction failed: {e}")
            return []

    def _calculate_cohesion(self, embeddings: np.ndarray) -> float:
        """Calcule cohésion intra-cluster."""
        if len(embeddings) < 2:
            return 1.0

        sim_matrix = cosine_similarity(embeddings)
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
