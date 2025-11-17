"""
Architecture modulaire pour l'ingestion de documents.

Modules extraits de pptx_pipeline.py (2871 lignes) pour réutilisabilité et testabilité.

Structure:
    extractors/  - Extraction données brutes (checksum, metadata, binary parsing, cleaning)
    converters/  - Conversion formats (PPTX→PDF, PDF→Images)
    transformers/ - Enrichissement LLM (chunking, summarization, analysis)
    sinks/       - Écriture données enrichies (Qdrant, Neo4j)
    utils/       - Utilitaires réutilisables (text, image, subprocess)

Exemples d'usage:

    # Pipeline PPTX complet
    from knowbase.ingestion.components.extractors import (
        remove_hidden_slides_inplace,
        extract_pptx_metadata,
        extract_notes_and_text
    )
    from knowbase.ingestion.components.converters import (
        convert_pptx_to_pdf,
        convert_pdf_to_images_pymupdf
    )

    # Pipeline PDF (skip conversion PPTX→PDF)
    from knowbase.ingestion.components.converters import convert_pdf_to_images_pymupdf

    # Pipeline DOCX (skip PPTX cleaning, utilise DOCX→PDF)
    # etc.

Avantages:
    - Réutilisabilité: Chaque composant indépendant
    - Testabilité: Tests unitaires par composant
    - Composition: Pipeline adaptable par type de fichier
    - Maintenabilité: ~200 lignes par fichier vs 2871 monolithique
"""

# Version de l'architecture modulaire
__version__ = "1.0.0"

# Exports optionnels des modules principaux
from . import extractors
from . import converters
from . import transformers
from . import sinks
from . import utils

__all__ = [
    "extractors",
    "converters",
    "transformers",
    "sinks",
    "utils",
]
