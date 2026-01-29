"""
OSMOSE Sprint 3+4 — Trigger Enricher (TF-IDF + Embedding + Cross-Filter)
=========================================================================

Enrichit les lexical_triggers des concepts à faible activation
en minant les n-grams discriminants du document et en les matchant
par similarité cosine (embeddings locaux sentence-transformers).

Sprint 4 — Discrimination croisée (Étape 1):
Après calcul des similarités pour TOUS les concepts, un filtre z-score
croisé assigne chaque n-gram de manière exclusive ou partagée:
- Exclusif: z-score ≥ 1.0 + unique winner + delta ≥ 0.05 → bonus normal
- Partagé: z-score ≥ 1.0 + 2+ winners + delta < 0.05 → shared=True, bonus plafonné
- Rejeté: 0 concepts au-dessus du z-score 1.0 → n-gram non-discriminant

Point d'insertion: après Phase 1.2 (concept identification),
avant Phase 1.3 (assertion extraction).

Pas d'appel API. Tout local (sentence-transformers GPU).
"""

import re
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from knowbase.stratified.models import Concept, ConceptRole

logger = logging.getLogger(__name__)

# Seuils de sélection des n-grams candidats
MIN_NGRAM_CHUNK_FREQ = 2       # Apparaît dans au moins 2 chunks
MAX_NGRAM_CHUNK_RATIO = 0.10   # Apparaît dans max 10% des chunks
MAX_CANDIDATES = 500           # Cap sur les candidats (perf)
MIN_TOKEN_LENGTH = 3           # Longueur min d'un token dans un n-gram

# Seuils d'enrichissement
MIN_SIMILARITY = 0.45          # Similarité cosine minimum pour adopter un trigger
MAX_NEW_TRIGGERS = 3           # Max triggers ajoutés par concept
MAX_TOTAL_TRIGGERS = 7         # Max triggers total par concept (existants + nouveaux)

# Sprint 4: Seuils de discrimination croisée (z-score)
CROSS_FILTER_ZSCORE_THRESHOLD = 1.0   # z-score minimum pour être assigné
CROSS_FILTER_DELTA_MIN = 0.05         # Écart min top1/top2 pour exclusivité
SHARED_TRIGGER_BONUS_CAP = 1.05       # Bonus plafonné pour triggers partagés

# Stopwords multilingues (filtrage n-grams)
STOPWORDS = frozenset({
    # EN
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was',
    'not', 'can', 'will', 'have', 'has', 'been', 'being', 'other', 'their',
    'more', 'also', 'such', 'which', 'these', 'than', 'into', 'each',
    'all', 'any', 'may', 'its', 'use', 'used', 'using', 'only', 'between',
    'both', 'does', 'did', 'should', 'would', 'could', 'must', 'shall',
    'they', 'them', 'our', 'your', 'who', 'how', 'what', 'when', 'where',
    # FR
    'les', 'des', 'une', 'par', 'pour', 'dans', 'sur', 'avec', 'qui', 'que',
    'est', 'sont', 'aux', 'ces', 'ont', 'mais', 'comme', 'tout', 'tous',
    'cette', 'ses', 'son', 'nos', 'leur', 'leurs', 'elle', 'elles',
    # Domaine générique (trop fréquent en IT/SAP)
    'data', 'system', 'service', 'services', 'management', 'process',
    'security', 'customer', 'customers', 'information', 'based',
    'cloud', 'application', 'access', 'support',
})


@dataclass
class EnrichedTrigger:
    """Trigger enrichi avec métadonnées de discrimination croisée (Sprint 4)."""
    text: str
    concept_id: str
    similarity: float
    shared: bool = False  # True si partagé entre 2+ concepts (bonus plafonné 1.05)


@dataclass
class CrossFilterResult:
    """Résultat du filtrage croisé des triggers."""
    exclusive: List[EnrichedTrigger] = field(default_factory=list)
    shared: List[EnrichedTrigger] = field(default_factory=list)
    rejected: int = 0


def enrich_triggers(
    concepts: List[Concept],
    chunks: Dict[str, str],
    activation_threshold: float = 0.01,
) -> Tuple[List[Concept], Dict[str, List[str]]]:
    """
    Enrichit les triggers des concepts à faible activation.

    Sprint 4: Après calcul des similarités, applique un filtre z-score croisé
    pour assigner les n-grams de manière exclusive ou partagée.

    Args:
        concepts: Liste des concepts (modifiés in-place)
        chunks: Dict chunk_id → texte du document
        activation_threshold: Seuil d'activation en-dessous duquel enrichir

    Returns:
        - concepts: Liste modifiée (même référence, triggers enrichis)
        - enrichment_log: {concept_id: [nouveaux_triggers_ajoutés]}
    """
    if not concepts or not chunks:
        logger.info("[OSMOSE:TriggerEnricher] Skip: concepts=%d, chunks=%d", len(concepts or []), len(chunks or {}))
        return concepts, {}

    logger.info(
        f"[OSMOSE:TriggerEnricher] Entrée: {len(concepts)} concepts, "
        f"{len(chunks)} chunks, seuil activation={activation_threshold:.2%}"
    )

    # Sprint 4 (2d): Exclure SINK de l'enrichissement
    enrichable_concepts = [
        c for c in concepts
        if getattr(c, 'role', None) != ConceptRole.SINK
    ]
    sink_excluded = len(concepts) - len(enrichable_concepts)
    if sink_excluded:
        logger.info(f"[OSMOSE:TriggerEnricher] {sink_excluded} concept(s) SINK exclus")

    # Identifier les concepts à enrichir
    concepts_to_enrich = _find_low_activation_concepts(enrichable_concepts, chunks, activation_threshold)

    if not concepts_to_enrich:
        # Sprint 4.1 Fix 4: Logger les activations pour comprendre le skip
        activations = _compute_activations(enrichable_concepts, chunks)
        if activations:
            min_act = min(activations.values())
            max_act = max(activations.values())
            low_count = sum(1 for v in activations.values() if v < activation_threshold)
            logger.info(
                f"[OSMOSE:TriggerEnricher] Aucun concept à enrichir (tous activés). "
                f"Activations: min={min_act:.3f}, max={max_act:.3f}, "
                f"sous seuil={low_count}/{len(activations)}"
            )
        else:
            logger.info("[OSMOSE:TriggerEnricher] Aucun concept à enrichir (pas d'activations calculées)")
        return concepts, {}

    logger.info(
        f"[OSMOSE:TriggerEnricher] {len(concepts_to_enrich)} concepts à enrichir "
        f"(activation < {activation_threshold:.0%})"
    )

    # Extraire les n-grams candidats du document
    candidates = _extract_candidate_ngrams(chunks)

    if not candidates:
        logger.info("[OSMOSE:TriggerEnricher] Aucun n-gram candidat extrait")
        return concepts, {}

    logger.info(f"[OSMOSE:TriggerEnricher] {len(candidates)} n-grams candidats extraits")

    # Encoder concepts et candidats via embeddings
    try:
        from knowbase.common.clients.embeddings import get_embedding_manager
        manager = get_embedding_manager()
    except ImportError:
        logger.warning("[OSMOSE:TriggerEnricher] Embeddings non disponibles, enrichissement ignoré")
        return concepts, {}

    # Encoder les candidats (batch)
    candidate_texts = list(candidates.keys())
    try:
        candidate_embeddings = manager.encode(candidate_texts)
    except Exception as e:
        logger.warning(f"[OSMOSE:TriggerEnricher] Encodage candidats échoué: {e}")
        return concepts, {}

    # Encoder les concepts à enrichir (batch)
    concept_reprs = []
    concept_ids_to_enrich = []
    for c in concepts_to_enrich:
        repr_text = c.name
        if c.definition:
            repr_text += " " + c.definition[:100]
        concept_reprs.append(repr_text)
        concept_ids_to_enrich.append(c.concept_id)

    try:
        concept_embeddings = manager.encode(concept_reprs)
    except Exception as e:
        logger.warning(f"[OSMOSE:TriggerEnricher] Encodage concepts échoué: {e}")
        return concepts, {}

    # ─── Sprint 4: Matrice de similarités croisée (Étape 1) ───
    # Construire la matrice (n_concepts × n_candidates) en batch
    sim_matrix = _build_similarity_matrix(concept_embeddings, candidate_embeddings)

    # Appliquer le filtre z-score croisé
    cross_filter_result = _cross_filter_triggers(
        sim_matrix, concept_ids_to_enrich, candidate_texts
    )

    logger.info(
        f"[OSMOSE:TriggerEnricher:CrossFilter] "
        f"{len(cross_filter_result.exclusive)} exclusifs, "
        f"{len(cross_filter_result.shared)} partagés, "
        f"{cross_filter_result.rejected} rejetés"
    )

    # ─── Assigner les triggers filtrés aux concepts ───
    concept_map = {c.concept_id: c for c in concepts}
    existing_triggers_lower = {
        c.concept_id: {t.lower() for t in (c.lexical_triggers or [])}
        for c in concepts
    }

    enrichment_log: Dict[str, List[str]] = {}

    # Grouper les triggers par concept_id
    triggers_by_concept: Dict[str, List[EnrichedTrigger]] = {}
    for et in cross_filter_result.exclusive + cross_filter_result.shared:
        if et.concept_id not in triggers_by_concept:
            triggers_by_concept[et.concept_id] = []
        triggers_by_concept[et.concept_id].append(et)

    for concept_id, enriched_triggers in triggers_by_concept.items():
        concept = concept_map.get(concept_id)
        if not concept:
            continue

        existing_lower = existing_triggers_lower.get(concept_id, set())
        current_trigger_count = len(concept.lexical_triggers or [])

        # Trier par similarité décroissante
        enriched_triggers.sort(key=lambda t: -t.similarity)

        new_triggers = []
        for et in enriched_triggers:
            if len(new_triggers) >= MAX_NEW_TRIGGERS:
                break
            if current_trigger_count + len(new_triggers) >= MAX_TOTAL_TRIGGERS:
                break

            candidate = et.text

            # Vérifier doublons
            if candidate.lower() in existing_lower:
                continue
            if any(candidate.lower() in t for t in existing_lower):
                continue
            if any(t in candidate.lower() for t in existing_lower):
                continue

            new_triggers.append(candidate)
            existing_lower.add(candidate.lower())

        if new_triggers:
            concept.lexical_triggers = list(concept.lexical_triggers or []) + new_triggers
            enrichment_log[concept_id] = new_triggers

            # Stocker les métadonnées shared pour usage downstream (Sprint 4)
            _mark_shared_triggers(concept, enriched_triggers)

            logger.info(
                f"[OSMOSE:TriggerEnricher] {concept.name}: "
                f"+{len(new_triggers)} triggers → {new_triggers}"
            )

    # Résumé
    total_added = sum(len(t) for t in enrichment_log.values())
    logger.info(
        f"[OSMOSE:TriggerEnricher] Résumé: {len(enrichment_log)}/{len(concepts_to_enrich)} "
        f"concepts enrichis, {total_added} triggers ajoutés"
    )

    return concepts, enrichment_log


def _build_similarity_matrix(
    concept_embeddings: np.ndarray,
    candidate_embeddings: np.ndarray,
) -> np.ndarray:
    """
    Construit la matrice de similarités cosine (n_concepts × n_candidates).

    Args:
        concept_embeddings: (n_concepts, dim)
        candidate_embeddings: (n_candidates, dim)

    Returns:
        Matrice (n_concepts, n_candidates) de similarités cosine
    """
    # Normaliser les embeddings
    concept_norms = np.linalg.norm(concept_embeddings, axis=1, keepdims=True)
    concept_norms = np.where(concept_norms < 1e-8, 1e-8, concept_norms)
    concept_normed = concept_embeddings / concept_norms

    candidate_norms = np.linalg.norm(candidate_embeddings, axis=1, keepdims=True)
    candidate_norms = np.where(candidate_norms < 1e-8, 1e-8, candidate_norms)
    candidate_normed = candidate_embeddings / candidate_norms

    # Matrice de similarités (n_concepts × n_candidates)
    return concept_normed @ candidate_normed.T


def _cross_filter_triggers(
    sim_matrix: np.ndarray,
    concept_ids: List[str],
    candidate_texts: List[str],
) -> CrossFilterResult:
    """
    Sprint 4 Étape 1: Filtre z-score croisé pour discrimination des triggers.

    Pour chaque candidat (colonne), calcule le z-score de chaque concept.
    Règles:
    - z-score ≥ 1.0 + unique winner + delta ≥ 0.05 → exclusif
    - z-score ≥ 1.0 + 2+ winners + delta < 0.05 → partagé (shared=True)
    - 0 concepts au-dessus du z-score 1.0 → rejeté

    Args:
        sim_matrix: Matrice (n_concepts × n_candidates)
        concept_ids: IDs des concepts (lignes)
        candidate_texts: Textes des candidats (colonnes)

    Returns:
        CrossFilterResult avec les triggers exclusifs, partagés, et le nombre de rejetés
    """
    n_concepts, n_candidates = sim_matrix.shape
    result = CrossFilterResult()

    if n_concepts < 2:
        # Avec 1 seul concept, pas de discrimination possible → tout exclusif au-dessus du seuil
        for j in range(n_candidates):
            sim = float(sim_matrix[0, j])
            if sim >= MIN_SIMILARITY:
                result.exclusive.append(EnrichedTrigger(
                    text=candidate_texts[j],
                    concept_id=concept_ids[0],
                    similarity=sim,
                    shared=False,
                ))
            else:
                result.rejected += 1
        return result

    for j in range(n_candidates):
        col = sim_matrix[:, j]  # Similarités de tous les concepts pour ce candidat

        # Z-score par colonne
        mean_val = float(np.mean(col))
        std_val = float(np.std(col))

        if std_val < 0.001:
            # Tous les concepts ont la même similarité → non-discriminant
            result.rejected += 1
            continue

        z_scores = (col - mean_val) / std_val

        # Identifier les concepts au-dessus du seuil z-score
        above_threshold = [
            (i, float(z_scores[i]), float(col[i]))
            for i in range(n_concepts)
            if z_scores[i] >= CROSS_FILTER_ZSCORE_THRESHOLD
            and col[i] >= MIN_SIMILARITY  # Aussi vérifier la similarité absolue
        ]

        if not above_threshold:
            # Aucun concept au-dessus → rejeté
            result.rejected += 1
            continue

        # Trier par z-score décroissant
        above_threshold.sort(key=lambda x: -x[1])

        if len(above_threshold) == 1:
            # Un seul concept → exclusif
            idx, z, sim = above_threshold[0]
            result.exclusive.append(EnrichedTrigger(
                text=candidate_texts[j],
                concept_id=concept_ids[idx],
                similarity=sim,
                shared=False,
            ))
        else:
            # 2+ concepts au-dessus du seuil
            top1_z = above_threshold[0][1]
            top2_z = above_threshold[1][1]
            delta = top1_z - top2_z

            if delta >= CROSS_FILTER_DELTA_MIN:
                # Top1 domine → exclusif pour le top1
                idx, z, sim = above_threshold[0]
                result.exclusive.append(EnrichedTrigger(
                    text=candidate_texts[j],
                    concept_id=concept_ids[idx],
                    similarity=sim,
                    shared=False,
                ))
            else:
                # Pas de dominance → partagé entre tous les concepts au-dessus du seuil
                for idx, z, sim in above_threshold:
                    result.shared.append(EnrichedTrigger(
                        text=candidate_texts[j],
                        concept_id=concept_ids[idx],
                        similarity=sim,
                        shared=True,
                    ))

    return result


def _mark_shared_triggers(concept: Concept, enriched_triggers: List[EnrichedTrigger]) -> None:
    """
    Stocke les métadonnées de triggers partagés sur le concept.

    Les triggers shared sont identifiés pour que le rerank puisse
    plafonner le bonus lexical à 1.05 (au lieu de 1.15/1.25).
    """
    shared_set = {et.text.lower() for et in enriched_triggers if et.shared}
    if shared_set:
        # Stocker comme attribut dynamique pour usage dans assertion_extractor
        if not hasattr(concept, '_shared_triggers'):
            concept._shared_triggers = set()
        concept._shared_triggers.update(shared_set)


def _compute_activations(
    concepts: List[Concept],
    chunks: Dict[str, str],
) -> Dict[str, float]:
    """
    Sprint 4.1 Fix 4: Calcule les taux d'activation de tous les concepts.

    Returns:
        {concept_id: activation_rate} pour chaque concept
    """
    total_chunks = len(chunks)
    if total_chunks == 0:
        return {}

    chunk_texts_lower = [text.lower() for text in chunks.values()]
    activations = {}

    for concept in concepts:
        triggers = concept.lexical_triggers or []
        if not triggers:
            activations[concept.concept_id] = 0.0
            continue

        matching_chunks = 0
        for text in chunk_texts_lower:
            for trigger in triggers:
                t_lower = trigger.lower()
                if len(t_lower) >= 4:
                    if re.search(rf'\b{re.escape(t_lower)}\b', text):
                        matching_chunks += 1
                        break
                else:
                    if re.search(rf'(?<![a-z]){re.escape(t_lower)}(?![a-z])', text):
                        matching_chunks += 1
                        break

        activations[concept.concept_id] = matching_chunks / total_chunks

    return activations


def _find_low_activation_concepts(
    concepts: List[Concept],
    chunks: Dict[str, str],
    threshold: float,
) -> List[Concept]:
    """
    Identifie les concepts dont les triggers ne matchent presque aucun chunk.

    Un concept est "à faible activation" si ses triggers (non-toxiques)
    matchent moins de `threshold` fraction des chunks.
    """
    total_chunks = len(chunks)
    if total_chunks == 0:
        return []

    chunk_texts_lower = [text.lower() for text in chunks.values()]
    low_activation = []

    for concept in concepts:
        triggers = concept.lexical_triggers or []
        if not triggers:
            low_activation.append(concept)
            continue

        # Compter les chunks qui matchent au moins un trigger
        matching_chunks = 0
        for text in chunk_texts_lower:
            for trigger in triggers:
                t_lower = trigger.lower()
                # Word boundary match pour les triggers >= 4 chars
                if len(t_lower) >= 4:
                    if re.search(rf'\b{re.escape(t_lower)}\b', text):
                        matching_chunks += 1
                        break
                else:
                    if re.search(rf'(?<![a-z]){re.escape(t_lower)}(?![a-z])', text):
                        matching_chunks += 1
                        break

        activation_rate = matching_chunks / total_chunks
        if activation_rate < threshold:
            low_activation.append(concept)

    return low_activation


def _extract_candidate_ngrams(
    chunks: Dict[str, str],
) -> Dict[str, int]:
    """
    Extrait les n-grams (2-3 mots) discriminants du document.

    Returns:
        {ngram_text: chunk_count} trié par discriminance
    """
    total_chunks = len(chunks)
    if total_chunks == 0:
        return {}

    # Compter les n-grams par chunk (document frequency)
    ngram_chunk_counts: Counter = Counter()

    for chunk_text in chunks.values():
        # Extraire les mots significatifs
        words = re.findall(r'\b[a-zA-Z]{3,}\b', chunk_text)

        # N-grams uniques de ce chunk
        chunk_ngrams: Set[str] = set()

        for n in (2, 3):
            for i in range(len(words) - n + 1):
                gram_words = words[i:i + n]

                # Filtrer: au moins un mot non-stopword
                non_stop = [w for w in gram_words if w.lower() not in STOPWORDS]
                if len(non_stop) < max(1, n - 1):
                    continue

                # Filtrer: pas que des mots courts
                if all(len(w) < MIN_TOKEN_LENGTH + 1 for w in gram_words):
                    continue

                ngram = " ".join(gram_words)
                chunk_ngrams.add(ngram.lower())

        # Incrémenter le document frequency
        for ng in chunk_ngrams:
            ngram_chunk_counts[ng] += 1

    # Filtrer par discriminance
    min_freq = MIN_NGRAM_CHUNK_FREQ
    max_freq = max(min_freq + 1, int(total_chunks * MAX_NGRAM_CHUNK_RATIO))

    discriminant = {
        ng: count
        for ng, count in ngram_chunk_counts.items()
        if min_freq <= count <= max_freq
    }

    # Trier par fréquence décroissante (plus fréquent = plus stable)
    # mais plafonner pour la perf
    sorted_candidates = dict(
        sorted(discriminant.items(), key=lambda x: -x[1])[:MAX_CANDIDATES]
    )

    return sorted_candidates
