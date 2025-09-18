from __future__ import annotations

import importlib
from unittest.mock import Mock


def test_create_app_mounts_static_assets(runtime_env, monkeypatch) -> None:
    slides_dir = runtime_env.paths.SLIDES_DIR
    thumbnails_dir = runtime_env.paths.THUMBNAILS_DIR
    presentations_dir = runtime_env.paths.PRESENTATIONS_DIR

    for directory in (slides_dir, thumbnails_dir, presentations_dir):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "placeholder.txt").write_text("content", encoding="utf-8")

    dependencies = importlib.import_module("knowbase.api.dependencies")
    importlib.reload(dependencies)
    main = importlib.import_module("knowbase.api.main")
    main = importlib.reload(main)

    mock_warm = Mock()
    monkeypatch.setattr(main, "warm_clients", mock_warm)

    app = main.create_app()

    mock_warm.assert_called_once_with()

    mounted = {route.name for route in app.routes if getattr(route, "name", None)}
    assert {"slides", "thumbnails", "presentations", "static"}.issubset(mounted)

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/search" in paths
    assert "/dispatch" in paths
    assert "/status/{uid}" in paths
