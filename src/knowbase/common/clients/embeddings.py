from __future__ import annotations

from functools import lru_cache
from typing import Optional

from sentence_transformers import SentenceTransformer

from knowbase.config.settings import get_settings


@lru_cache(maxsize=None)
def get_sentence_transformer(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    cache_folder: Optional[str] = None,
) -> SentenceTransformer:
    settings = get_settings()
    name = model_name or settings.embeddings_model
    kwargs: dict[str, object] = {}
    if device is not None:
        kwargs["device"] = device
    if cache_folder is not None:
        kwargs["cache_folder"] = cache_folder
    return SentenceTransformer(name, **kwargs)
