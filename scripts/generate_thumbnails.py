from pathlib import Path
from PIL import Image

# === CONFIGURATION ===

BASE_DIR = Path(__file__).parent.parent.resolve()
# Répertoire d'entrée contenant les images originales
INPUT_DIR = BASE_DIR / "public_files" / "slides"
# Répertoire de sortie pour les thumbnails
OUTPUT_DIR = BASE_DIR / "public_files" / "thumbnails"
# Dimensions max
MAX_SIZE = (900, 900)

# Extensions d’images acceptées
IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"]


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def generate_thumbnail(image_path: Path, output_path: Path):
    try:
        with Image.open(image_path) as img:
            img.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path.with_suffix(".png"), "PNG")
            print(f"✅ Thumbnail créé : {output_path.name}")
    except Exception as e:
        print(f"❌ Erreur sur {image_path.name} : {e}")


def main():
    if not INPUT_DIR.exists():
        print(f"❌ Le dossier d'entrée n'existe pas : {INPUT_DIR}")
        return

    print(f"📂 Recherche d'images dans : {INPUT_DIR}")

    for image_path in INPUT_DIR.glob("*"):
        if is_image_file(image_path):
            base_name = image_path.stem
            output_file = OUTPUT_DIR / f"{base_name}.png"
            generate_thumbnail(image_path, output_file)

    print("🎉 Génération des thumbnails terminée.")


if __name__ == "__main__":
    main()
