"""
OSMOSIS Mode Classifier — Classification few-shot par embedding similarity.

Remplace le substring matching (fragile, FR-only) par un classificateur
multilingue base sur e5-large (meme modele que le retrieval).

Usage :
    classifier = get_mode_classifier()
    mode, confidence = classifier.classify(question, embedding_model)
    # mode = "TENSION" | "STRUCTURED_FACT" | "DIRECT"
    # confidence = 0.0 - 1.0 (cosine similarity)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import yaml

logger = logging.getLogger(__name__)

# Singleton
_classifier_instance = None


class ModeClassifier:
    """Classificateur few-shot par embedding similarity."""

    def __init__(self, config: dict):
        self._config = config
        self._thresholds = config.get("thresholds", {})
        self._mode_examples: dict[str, list[str]] = {}
        self._mode_embeddings: dict[str, np.ndarray] = {}
        self._initialized = False

        # Charger les exemples
        for mode_name, mode_data in config.get("modes", {}).items():
            examples = mode_data.get("examples", [])
            if examples:
                self._mode_examples[mode_name] = examples
                logger.info(
                    f"[MODE_CLASSIFIER] Loaded {len(examples)} examples for {mode_name}"
                )

    def _ensure_initialized(self, embedding_model) -> None:
        """Lazy init : embed tous les exemples au premier appel."""
        if self._initialized:
            return

        for mode_name, examples in self._mode_examples.items():
            embeddings = embedding_model.encode(
                examples, normalize_embeddings=True, show_progress_bar=False
            )
            self._mode_embeddings[mode_name] = np.array(embeddings)
            logger.info(
                f"[MODE_CLASSIFIER] Embedded {len(examples)} examples for {mode_name} "
                f"(shape: {self._mode_embeddings[mode_name].shape})"
            )

        self._initialized = True
        logger.info(f"[MODE_CLASSIFIER] Initialized with modes: {list(self._mode_embeddings.keys())}")

    def classify(self, question: str, embedding_model) -> tuple[str, float]:
        """Classifie une question par similarity avec les exemples.

        Returns:
            (mode, confidence) — mode est "DIRECT" si aucun mode non-DIRECT
            ne depasse son seuil.
        """
        self._ensure_initialized(embedding_model)

        if not self._mode_embeddings:
            return "DIRECT", 0.0

        # Embed la question
        q_embedding = embedding_model.encode(
            [question], normalize_embeddings=True, show_progress_bar=False
        )[0]

        all_scores: dict[str, float] = {}

        for mode_name, mode_embeds in self._mode_embeddings.items():
            # Cosine similarity avec chaque exemple (embeddings deja normalises)
            similarities = mode_embeds @ q_embedding
            # Prendre la moyenne des top-3 (plus robuste que le max)
            top_k = min(3, len(similarities))
            top_scores = np.sort(similarities)[-top_k:]
            avg_score = float(np.mean(top_scores))
            all_scores[mode_name] = avg_score

        # Le mode gagnant doit :
        # 1. Depasser son seuil absolu
        # 2. Battre DIRECT par une marge (le mode doit etre CLAIREMENT plus proche)
        direct_score = all_scores.get("DIRECT", 0.0)
        MIN_MARGIN_OVER_DIRECT = 0.03  # le mode non-DIRECT doit battre DIRECT d'au moins 3%

        best_mode = "DIRECT"
        best_score = direct_score

        for mode_name, score in all_scores.items():
            if mode_name == "DIRECT":
                continue
            threshold = self._thresholds.get(mode_name.lower(), 0.75)
            margin = score - direct_score
            if score >= threshold and margin >= MIN_MARGIN_OVER_DIRECT and score > best_score:
                best_mode = mode_name
                best_score = score

        logger.info(
            f"[MODE_CLASSIFIER] Q=\"{question[:60]}\" → {best_mode} "
            f"(scores: {', '.join(f'{m}={s:.3f}' for m, s in all_scores.items())}, "
            f"margin_over_direct={best_score - direct_score:+.3f})"
        )

        return best_mode, best_score


def _load_config() -> dict:
    """Charge la config des exemples depuis YAML."""
    config_paths = [
        Path("/app/config/mode_examples.yaml"),
        Path(__file__).parent.parent.parent.parent / "config" / "mode_examples.yaml",
    ]
    for p in config_paths:
        if p.exists():
            config = yaml.safe_load(p.read_text(encoding="utf-8"))
            logger.info(f"[MODE_CLASSIFIER] Config loaded from {p}")
            return config

    logger.warning("[MODE_CLASSIFIER] No mode_examples.yaml found")
    return {"thresholds": {}, "modes": {}}


def get_mode_classifier() -> ModeClassifier:
    """Singleton — retourne le classificateur (lazy init des embeddings)."""
    global _classifier_instance
    if _classifier_instance is None:
        config = _load_config()
        _classifier_instance = ModeClassifier(config)
    return _classifier_instance
