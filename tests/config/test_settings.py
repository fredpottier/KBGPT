from __future__ import annotations

import os


def test_configure_runtime_invokes_directory_setup(runtime_env, monkeypatch) -> None:
    settings_module = runtime_env.settings_module
    settings = settings_module.Settings()

    captured_paths = []

    def fake_ensure(paths=None):
        captured_paths.append(list(paths or []))

    monkeypatch.setattr(settings_module, "ensure_directories", fake_ensure)
    monkeypatch.delenv("HF_HOME", raising=False)

    settings.configure_runtime()

    assert captured_paths, "ensure_directories should be called during configuration"
    expected = {
        settings.data_dir,
        settings.docs_in_dir,
        settings.docs_done_dir,
        settings.logs_dir,
        settings.models_dir,
        settings.status_dir,
        settings.presentations_dir,
        settings.slides_dir,
        settings.thumbnails_dir,
    }
    assert set(captured_paths[0]) == expected
    assert os.environ["HF_HOME"] == str(settings.hf_home)
