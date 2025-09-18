from __future__ import annotations


def test_ensure_directories_creates_expected_structure(runtime_env) -> None:
    paths = runtime_env.paths

    expected = [
        paths.DATA_DIR,
        paths.DOCS_IN_DIR,
        paths.DOCS_DONE_DIR,
        paths.LOGS_DIR,
        paths.MODELS_DIR,
        paths.STATUS_DIR,
        paths.PUBLIC_FILES_DIR,
        paths.SLIDES_DIR,
        paths.THUMBNAILS_DIR,
        paths.PRESENTATIONS_DIR,
    ]

    for directory in expected:
        assert not directory.exists()

    paths.ensure_directories()

    for directory in expected:
        assert directory.exists()
        assert directory.is_dir()


def test_ensure_directories_migrates_legacy_content(runtime_env, monkeypatch) -> None:
    paths = runtime_env.paths
    legacy_dir = runtime_env.data_dir.parent / "legacy_docs"
    target_dir = runtime_env.data_dir / "docs"
    legacy_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "example.txt"
    legacy_file.write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(paths, "LEGACY_DIRECTORIES", {legacy_dir: target_dir})

    paths.ensure_directories([target_dir])

    migrated_file = target_dir / "example.txt"
    assert migrated_file.exists()
    assert migrated_file.read_text(encoding="utf-8") == "legacy"

    if legacy_dir.exists():
        assert legacy_dir.resolve() == target_dir.resolve()
