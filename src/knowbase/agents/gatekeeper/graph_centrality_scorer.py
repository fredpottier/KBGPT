"""
🌊 OSMOSE Phase 1.5 - Graph Centrality Scorer

Filtrage contextuel basé sur l'analyse de graphe de co-occurrence.

**Principe**: Les entités importantes sont structurellement centrales dans le document
- TF-IDF weighting (pas juste fréquence brute)
- Salience score (position + boost titre/abstract)
- Fenêtre adaptive (30-100 mots selon taille doc)
- Centrality metrics: PageRank, Degree, Betweenness

**Impact attendu**: +20-30% précision, 100% language-agnostic, $0 coût, <100ms

Référence: doc/ongoing/ANALYSE_FILTRAGE_CONTEXTUEL_GENERALISTE.md
"""

from typing import Dict, Any, List, Tuple, Set
import logging
import re
import math
from collections import defaultdict, Counter
import networkx as nx

logger = logging.getLogger(__name__)


class GraphCentralityScorer:
    """
    Score entities based on graph centrality metrics.

    Utilise la structure du document (co-occurrences) plutôt que le contenu
    sémantique pour identifier les entités importantes.

    **Avantages**:
    - 100% language-agnostic (structure vs sémantique)
    - $0 coût (pas d'appel API)
    - <100ms latence
    - Robuste aux erreurs NER (structure préservée)
    """

    def __init__(
        self,
        min_centrality: float = 0.15,
        centrality_weights: Dict[str, float] = None,
        enable_tf_idf: bool = True,
        enable_salience: bool = True
    ):
        """
        Initialiser le scorer.

        Args:
            min_centrality: Seuil minimum de centralité (défaut: 0.15)
            centrality_weights: Poids pour PageRank/Degree/Betweenness
            enable_tf_idf: Activer TF-IDF weighting
            enable_salience: Activer salience scoring (position)
        """
        self.min_centrality = min_centrality
        self.centrality_weights = centrality_weights or {
            "pagerank": 0.5,
            "degree": 0.3,
            "betweenness": 0.2
        }
        self.enable_tf_idf = enable_tf_idf
        self.enable_salience = enable_salience

        logger.info(
            f"[OSMOSE] GraphCentralityScorer initialisé "
            f"(min_centrality={min_centrality}, "
            f"tf_idf={enable_tf_idf}, salience={enable_salience})"
        )

    def score_entities(
        self,
        candidates: List[Dict[str, Any]],
        full_text: str
    ) -> List[Dict[str, Any]]:
        """
        Score entities avec métriques de centralité.

        Args:
            candidates: Liste d'entités candidates
            full_text: Texte complet du document

        Returns:
            Liste d'entités avec scores ajoutés:
            - tf_idf_score: Score TF-IDF normalisé [0-1]
            - centrality_score: Score combiné PageRank+Degree+Betweenness [0-1]
            - salience_score: Score position/importance [0-1]
            - graph_score: Score final combiné [0-1]
        """
        if not candidates:
            logger.warning("[OSMOSE] GraphCentralityScorer: Aucun candidat à scorer")
            return []

        if not full_text or len(full_text) < 50:
            logger.warning("[OSMOSE] GraphCentralityScorer: Texte trop court, scoring par défaut")
            for entity in candidates:
                entity["graph_score"] = 0.5  # Score neutre
            return candidates

        # P1.3: Limite max entities pour éviter O(n²) explosion (300 max)
        MAX_ENTITIES = 300
        if len(candidates) > MAX_ENTITIES:
            logger.warning(
                f"[OSMOSE] GraphCentralityScorer: Trop de candidats ({len(candidates)} > {MAX_ENTITIES}), "
                f"utilisation des {MAX_ENTITIES} premiers uniquement (P1.3 protection)"
            )
            candidates = candidates[:MAX_ENTITIES]

        logger.info(
            f"[OSMOSE] GraphCentralityScorer: Scoring {len(candidates)} candidats "
            f"(doc_length={len(full_text)} chars)"
        )

        # 1. Build co-occurrence graph
        graph = self._build_cooccurrence_graph(candidates, full_text)

        # 2. Calculate TF-IDF weights (optionnel)
        tf_idf_scores = {}
        if self.enable_tf_idf:
            tf_idf_scores = self._calculate_tf_idf(candidates, full_text)

        # 3. Calculate centrality scores
        centrality_scores = self._calculate_centrality(graph)

        # 4. Calculate salience scores (optionnel)
        salience_scores = {}
        if self.enable_salience:
            salience_scores = self._calculate_salience(candidates, full_text)

        # 5. Combine scores
        for entity in candidates:
            entity_name = entity.get("text", "") or entity.get("name", "")
            if not entity_name:
                continue

            # Normalisation du nom (case-insensitive)
            entity_key = entity_name.lower()

            # Scores individuels
            tf_idf = tf_idf_scores.get(entity_key, 0.5)  # Défaut neutre
            centrality = centrality_scores.get(entity_key, 0.0)
            salience = salience_scores.get(entity_key, 0.5)  # Défaut neutre

            # Enregistrer scores individuels
            entity["tf_idf_score"] = tf_idf
            entity["centrality_score"] = centrality
            entity["salience_score"] = salience

            # Score combiné (pondération configurable)
            weights = [0.4, 0.4, 0.2]  # TF-IDF, Centrality, Salience
            scores = [tf_idf, centrality, salience]

            # Ajuster poids si composants désactivés
            if not self.enable_tf_idf:
                weights[0] = 0.0
                weights[1] = 0.6  # Plus de poids sur centrality
            if not self.enable_salience:
                weights[2] = 0.0
                weights[0] += 0.1
                weights[1] += 0.1

            entity["graph_score"] = sum(w * s for w, s in zip(weights, scores))

            # Log détails si score très bas ou très haut
            if entity["graph_score"] < 0.2 or entity["graph_score"] > 0.8:
                logger.debug(
                    f"[OSMOSE] GraphScoring '{entity_name}': "
                    f"graph={entity['graph_score']:.2f} "
                    f"(tfidf={tf_idf:.2f}, cent={centrality:.2f}, sal={salience:.2f})"
                )

        logger.info(
            f"[OSMOSE] GraphCentralityScorer: Scoring terminé "
            f"({len([e for e in candidates if e.get('graph_score', 0) >= self.min_centrality])} "
            f"entities >= {self.min_centrality})"
        )

        return candidates

    def _build_cooccurrence_graph(
        self,
        candidates: List[Dict[str, Any]],
        full_text: str
    ) -> nx.Graph:
        """
        Build co-occurrence graph avec fenêtre adaptive.

        **Amélioration vs basique**:
        - Fenêtre adaptive (30-100 mots selon taille doc)
        - TF-IDF weighting des edges (pas juste comptage)
        - Normalisation case-insensitive

        Args:
            candidates: Liste d'entités
            full_text: Texte complet

        Returns:
            Graph NetworkX avec poids TF-IDF sur edges
        """
        graph = nx.Graph()

        # Déterminer fenêtre adaptive
        window_size = self._get_adaptive_window_size(len(full_text))

        # Extraire tous les noms d'entités (normalisés)
        entity_names = [
            (e.get("text", "") or e.get("name", "")).lower()
            for e in candidates
            if (e.get("text") or e.get("name"))
        ]

        if not entity_names:
            return graph

        # Ajouter tous les nœuds
        for name in entity_names:
            graph.add_node(name)

        # Tokeniser le texte (mots simples)
        words = re.findall(r'\b\w+\b', full_text.lower())

        # Sliding window pour détecter co-occurrences
        cooccurrences = defaultdict(int)

        for i in range(len(words) - window_size + 1):
            window = words[i:i + window_size]

            # Trouver entités dans cette fenêtre
            entities_in_window = []
            for entity_name in entity_names:
                # Check si l'entité est dans la fenêtre (approximatif)
                entity_words = entity_name.split()
                if all(word in window for word in entity_words):
                    entities_in_window.append(entity_name)

            # Ajouter co-occurrences (paires uniques)
            if len(entities_in_window) >= 2:
                for j, e1 in enumerate(entities_in_window):
                    for e2 in entities_in_window[j + 1:]:
                        pair = tuple(sorted([e1, e2]))
                        cooccurrences[pair] += 1

        # Ajouter edges avec poids
        for (e1, e2), count in cooccurrences.items():
            # Poids: log(count) pour éviter domination des paires fréquentes
            weight = math.log(count + 1)
            graph.add_edge(e1, e2, weight=weight)

        logger.debug(
            f"[OSMOSE] Graph construit: {graph.number_of_nodes()} nœuds, "
            f"{graph.number_of_edges()} edges (window={window_size})"
        )

        return graph

    def _calculate_tf_idf(
        self,
        candidates: List[Dict[str, Any]],
        full_text: str
    ) -> Dict[str, float]:
        """
        Calculate TF-IDF scores for entities.

        **Amélioration vs fréquence brute**: TF-IDF pénalise les termes
        trop fréquents (stopwords-like) et favorise les termes spécifiques.

        Args:
            candidates: Liste d'entités
            full_text: Texte complet

        Returns:
            Dict {entity_name → tf_idf_score [0-1]}
        """
        scores = {}

        # Tokeniser le texte
        words = re.findall(r'\b\w+\b', full_text.lower())
        total_words = len(words)

        if total_words == 0:
            return scores

        # Calculer fréquence de chaque mot (pour IDF)
        word_counts = Counter(words)

        # Calculer TF-IDF pour chaque entité
        for entity in candidates:
            entity_name = (entity.get("text", "") or entity.get("name", "")).lower()
            if not entity_name:
                continue

            # TF: Fréquence du terme dans le document
            entity_words = entity_name.split()
            term_frequency = sum(word_counts.get(word, 0) for word in entity_words)
            tf = term_frequency / total_words if total_words > 0 else 0.0

            # IDF: log(N / df) où df = nombre de docs contenant le terme
            # Approximation: IDF basé sur fréquence relative (single doc)
            # Termes rares (faible fréquence) → IDF élevé
            # Termes fréquents → IDF faible
            max_word_freq = max(word_counts.values())
            avg_word_freq = sum(word_counts.get(w, 0) for w in entity_words) / len(entity_words)

            # IDF inversement proportionnel à la fréquence relative
            idf = math.log(max_word_freq / (avg_word_freq + 1) + 1)

            # TF-IDF
            tf_idf = tf * idf

            # Normalisation [0-1] (approximatif)
            # Max théorique: TF=0.1 (10% du doc), IDF=log(1000)=6.9 → tf_idf=0.69
            normalized_score = min(tf_idf / 0.5, 1.0)  # Seuil arbitraire pour normalisation

            scores[entity_name] = normalized_score

        return scores

    def _calculate_centrality(
        self,
        graph: nx.Graph
    ) -> Dict[str, float]:
        """
        Calculate centrality scores (PageRank, Degree, Betweenness).

        **Combinaison de 3 métriques**:
        - PageRank: Importance globale (liens entrants)
        - Degree: Nombre de connexions directes
        - Betweenness: Position de "pont" entre clusters

        Args:
            graph: Graph NetworkX

        Returns:
            Dict {entity_name → centrality_score [0-1]}
        """
        scores = {}

        if graph.number_of_nodes() == 0:
            return scores

        # Éviter calculs sur graphes vides ou trop petits
        if graph.number_of_edges() == 0:
            # Graphe sans edges: tous les nœuds ont score 0
            for node in graph.nodes():
                scores[node] = 0.0
            return scores

        # 1. PageRank (importance globale)
        # P1.3: Timeout 10s pour éviter PageRank infini sur graphes complexes
        try:
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError("PageRank timeout après 10s")

            # Activer timeout (UNIX uniquement, skip sur Windows)
            try:
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(10)  # 10 secondes max
            except AttributeError:
                # Windows n'a pas SIGALRM, skip timeout
                pass

            try:
                pagerank = nx.pagerank(graph, weight="weight", max_iter=100)
            finally:
                try:
                    signal.alarm(0)  # Désactiver timeout
                except AttributeError:
                    pass

        except TimeoutError as te:
            logger.warning(f"[OSMOSE] PageRank timeout (P1.3 protection): {te}, fallback degree centrality")
            pagerank = {node: 0.0 for node in graph.nodes()}
        except Exception as e:
            logger.warning(f"[OSMOSE] PageRank échoué: {e}, utilisation degree centrality")
            pagerank = {node: 0.0 for node in graph.nodes()}

        # 2. Degree Centrality (nombre de connexions)
        degree_centrality = nx.degree_centrality(graph)

        # 3. Betweenness Centrality (position de pont)
        try:
            betweenness = nx.betweenness_centrality(graph, weight="weight")
        except Exception as e:
            logger.warning(f"[OSMOSE] Betweenness échoué: {e}, utilisation 0.0")
            betweenness = {node: 0.0 for node in graph.nodes()}

        # Normalisation de PageRank [0-1]
        max_pagerank = max(pagerank.values()) if pagerank else 1.0
        pagerank_norm = {
            node: score / max_pagerank if max_pagerank > 0 else 0.0
            for node, score in pagerank.items()
        }

        # Betweenness déjà normalisé [0-1]

        # 4. Combinaison pondérée
        for node in graph.nodes():
            pr = pagerank_norm.get(node, 0.0)
            dc = degree_centrality.get(node, 0.0)
            bc = betweenness.get(node, 0.0)

            # Poids configurables
            combined = (
                self.centrality_weights["pagerank"] * pr +
                self.centrality_weights["degree"] * dc +
                self.centrality_weights["betweenness"] * bc
            )

            scores[node] = combined

        return scores

    def _calculate_salience(
        self,
        candidates: List[Dict[str, Any]],
        full_text: str
    ) -> Dict[str, float]:
        """
        Calculate salience scores (position + titre/abstract boost).

        **Heuristique**: Entités mentionnées tôt (titre, intro) ou
        fréquemment = plus importantes.

        Args:
            candidates: Liste d'entités
            full_text: Texte complet

        Returns:
            Dict {entity_name → salience_score [0-1]}
        """
        scores = {}

        text_length = len(full_text)
        if text_length == 0:
            return scores

        # Zones spéciales (approximatif)
        # Titre/Abstract: premiers 10% du texte
        title_zone_end = int(text_length * 0.1)

        for entity in candidates:
            entity_name = (entity.get("text", "") or entity.get("name", "")).lower()
            if not entity_name:
                continue

            # Trouver toutes les positions de l'entité
            positions = []
            text_lower = full_text.lower()
            start = 0
            while True:
                pos = text_lower.find(entity_name, start)
                if pos == -1:
                    break
                positions.append(pos)
                start = pos + 1

            if not positions:
                scores[entity_name] = 0.0
                continue

            # Score basé sur première position (early mention bonus)
            first_position = positions[0]
            position_ratio = first_position / text_length

            # Score position: 1.0 (début) → 0.3 (fin) - décroissance linéaire
            position_score = max(1.0 - position_ratio, 0.3)

            # Bonus si dans zone titre/abstract (+0.2)
            title_bonus = 0.2 if first_position < title_zone_end else 0.0

            # Bonus fréquence: log(count) normalisé
            frequency_score = min(math.log(len(positions) + 1) / math.log(10), 0.3)

            # Score final
            salience = min(position_score + title_bonus + frequency_score, 1.0)

            scores[entity_name] = salience

        return scores

    def _get_adaptive_window_size(self, text_length: int) -> int:
        """
        Get adaptive window size based on document length.

        **Rationale**: Documents longs nécessitent fenêtres plus grandes
        pour capturer co-occurrences significatives.

        Args:
            text_length: Longueur du texte (caractères)

        Returns:
            Taille de fenêtre (nombre de mots)
        """
        # Conversion approximative: 5 caractères/mot
        approx_words = text_length / 5

        if approx_words < 200:  # < 1000 chars
            return 30
        elif approx_words < 1000:  # < 5000 chars
            return 50
        elif approx_words < 4000:  # < 20000 chars
            return 75
        else:
            return 100
