from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel


class BaseSettings(BaseModel):
    """Minimal fallback replacement for :mod:`pydantic_settings`."""

    model_config = BaseModel.model_config.copy()

    def __init__(self, **data: Any) -> None:
        env_overrides: dict[str, Any] = {}
        for field_name, field_info in self.__class__.model_fields.items():
            alias = field_info.alias or field_name
            if alias in os.environ and field_name not in data:
                env_overrides[field_name] = os.environ[alias]
        env_overrides.update(data)
        super().__init__(**env_overrides)


__all__ = ["BaseSettings"]
