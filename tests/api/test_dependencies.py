from __future__ import annotations

import importlib
from unittest.mock import Mock


def test_warm_clients_initialises_dependencies(runtime_env, monkeypatch) -> None:
    dependencies = importlib.import_module("knowbase.api.dependencies")
    dependencies = importlib.reload(dependencies)

    settings = runtime_env.settings_module.get_settings()

    ensure_collection = Mock()
    monkeypatch.setattr(dependencies, "ensure_qdrant_collection", ensure_collection)

    embedding_model = Mock()
    embedding_model.get_sentence_embedding_dimension.return_value = 1024
    transformer_factory = Mock(return_value=embedding_model)
    monkeypatch.setattr(dependencies, "get_sentence_transformer", transformer_factory)

    openai_factory = Mock()
    qdrant_factory = Mock()
    monkeypatch.setattr(dependencies, "get_openai_client", openai_factory)
    monkeypatch.setattr(dependencies, "get_qdrant_client", qdrant_factory)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)

    dependencies.warm_clients()

    ensure_collection.assert_called_once_with(settings.qdrant_collection, 1024)
    transformer_factory.assert_called_once_with()
    openai_factory.assert_called_once_with()
    qdrant_factory.assert_called_once_with()
