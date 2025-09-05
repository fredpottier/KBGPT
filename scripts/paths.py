from pathlib import Path


def find_project_root() -> Path:
    """
    Retourne la racine du projet (= dossier parent de scripts/) si trouvée,
    sinon Path.cwd().
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "scripts").exists() and (parent / "docs_in").exists():
            return parent  # on veut /app, pas /app/scripts
    root = find_project_root()
    print(f"🔍 ROOT DETECTED = {root}")
    return Path.cwd().resolve()


def get_docs_in() -> Path:
    return find_project_root() / "docs_in"


def get_docs_done() -> Path:
    return find_project_root() / "public_files/presentations"


def get_slides_png() -> Path:
    return find_project_root() / "public_files/slides"


def get_status_dir() -> Path:
    return find_project_root() / "status"


def get_logs_dir() -> Path:
    return find_project_root() / "logs"


def get_cache_models() -> Path:
    return find_project_root() / "models"
