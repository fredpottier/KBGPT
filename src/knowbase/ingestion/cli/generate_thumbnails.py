"""Command line utility to generate slide thumbnails.

This CLI replaces the legacy ``scripts/generate_thumbnails.py`` helper while
relying on the central Knowbase configuration.  By default it scans the
configured ``slides`` directory and creates thumbnails in the ``thumbnails``
directory, but custom locations can be provided through command line
arguments.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image

from knowbase.config.settings import Settings, get_settings


IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
)


def iter_images(directory: Path) -> Iterable[Path]:
    """Yield all files in *directory* that look like supported images."""

    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def generate_thumbnail(image_path: Path, output_dir: Path, max_size: tuple[int, int]) -> None:
    """Create a PNG thumbnail for *image_path* inside *output_dir*."""

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{image_path.stem}.png"
    with Image.open(image_path) as img:
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        img.save(destination, "PNG")
    print(f"✅ Thumbnail créé : {destination.name}")


def build_parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate slide thumbnails")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=settings.slides_dir,
        help="Directory containing the original images (default: slides_dir from settings)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=settings.thumbnails_dir,
        help="Directory where thumbnails will be written (default: thumbnails_dir from settings)",
    )
    parser.add_argument(
        "--max-size",
        nargs=2,
        type=int,
        metavar=("WIDTH", "HEIGHT"),
        default=(900, 900),
        help="Maximum width and height for generated thumbnails (default: 900 900)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Entry-point for the thumbnail generation CLI."""

    settings = get_settings()
    parser = build_parser(settings)
    args = parser.parse_args(list(argv) if argv is not None else None)

    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir
    max_size = tuple(args.max_size)

    if not input_dir.exists():
        print(f"❌ Le dossier d'entrée n'existe pas : {input_dir}")
        return

    print(f"📂 Recherche d'images dans : {input_dir}")

    for image_path in iter_images(input_dir):
        try:
            generate_thumbnail(image_path, output_dir, max_size)
        except Exception as exc:  # pragma: no cover - defensive logging only
            print(f"❌ Erreur sur {image_path.name} : {exc}")

    print("🎉 Génération des thumbnails terminée.")


if __name__ == "__main__":
    main()
