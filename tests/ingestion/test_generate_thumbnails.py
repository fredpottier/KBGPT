from __future__ import annotations

import importlib
from pathlib import Path

from PIL import Image


cli = importlib.import_module("knowbase.ingestion.cli.generate_thumbnails")
cli = importlib.reload(cli)


def test_iter_images_filters_supported_extensions(tmp_path: Path) -> None:
    images_dir = tmp_path
    valid = {
        images_dir / "slide1.png",
        images_dir / "slide2.JPG",
        images_dir / "slide3.webp",
    }
    for path in valid:
        path.write_bytes(b"binary")
    (images_dir / "ignored.txt").write_text("nope", encoding="utf-8")
    (images_dir / "folder").mkdir()

    found = set(cli.iter_images(images_dir))
    assert found == {path for path in valid}


def test_generate_thumbnail_creates_png(tmp_path: Path) -> None:
    image_path = tmp_path / "input.jpg"
    Image.new("RGB", (100, 100), color="red").save(image_path)

    output_dir = tmp_path / "output"
    cli.generate_thumbnail(image_path, output_dir, (50, 50))

    thumbnail = output_dir / "input.png"
    assert thumbnail.exists()


def test_main_uses_default_directories(runtime_env, monkeypatch) -> None:
    module = importlib.reload(cli)
    settings = runtime_env.settings_module.get_settings()

    slides_dir = settings.slides_dir
    slides_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color="blue").save(slides_dir / "demo.png")

    captured = []

    def fake_generate(image_path: Path, output_dir: Path, max_size: tuple[int, int]) -> None:
        captured.append((image_path, output_dir, max_size))

    monkeypatch.setattr(module, "generate_thumbnail", fake_generate)

    module.main([])

    assert captured, "generate_thumbnail should be invoked for discovered images"
    first_call = captured[0]
    assert first_call[0].parent == slides_dir
    assert first_call[1] == settings.thumbnails_dir
