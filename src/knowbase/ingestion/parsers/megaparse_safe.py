"""
MegaParse Safe Wrapper - Circuit Breaker Pattern

Exécute MegaParse dans un subprocess isolé pour éviter les OOM qui crashent l'app principale.
En cas de timeout ou crash, fallback automatique sur pdftotext.

Architecture:
- Subprocess avec limite mémoire (8 Go par défaut)
- Timeout configurable (5 min par défaut)
- Fallback automatique sur pdftotext si échec
- L'app principale survit même si MegaParse OOM

Author: OSMOSE
Date: 2026-01
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Configuration par défaut
DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes
DEFAULT_MAX_MEMORY_MB = 8192   # 8 Go


def parse_pdf_with_megaparse_safe(
    pdf_path: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
    use_vision: bool = False
) -> Optional[List[Dict[str, Any]]]:
    """
    Wrapper sécurisé pour MegaParse avec isolation subprocess.

    En cas d'échec (timeout, OOM, crash), retourne None pour déclencher le fallback.

    Args:
        pdf_path: Chemin vers le fichier PDF
        timeout: Timeout en secondes (défaut: 300s = 5 min)
        max_memory_mb: Limite mémoire en Mo (défaut: 8192 = 8 Go)
        use_vision: Mode Vision (non utilisé actuellement)

    Returns:
        Liste de blocs sémantiques si succès, None si échec (déclenche fallback)
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        logger.error(f"[MEGAPARSE_SAFE] Fichier non trouvé: {pdf_path}")
        return None

    # Créer un fichier temporaire pour la sortie JSON
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_out:
        output_path = tmp_out.name

    try:
        logger.info(
            f"[MEGAPARSE_SAFE] Lancement subprocess pour {pdf_path.name} "
            f"(timeout={timeout}s, max_mem={max_memory_mb}MB)"
        )

        # Script Python à exécuter dans le subprocess
        # Utilise le même environnement Python que l'app principale
        subprocess_script = f'''
import sys
import json
import resource
from pathlib import Path

# Limite mémoire (soft limit)
try:
    # Convertir MB en bytes
    mem_bytes = {max_memory_mb} * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
except Exception as e:
    print(f"Warning: Could not set memory limit: {{e}}", file=sys.stderr)

# Import MegaParse
try:
    from megaparse import MegaParse
    from megaparse_sdk.schema.parser_config import StrategyEnum
    MEGAPARSE_AVAILABLE = True
    STRATEGY_ENUM_AVAILABLE = True
except ImportError:
    MEGAPARSE_AVAILABLE = False
    STRATEGY_ENUM_AVAILABLE = False

if not MEGAPARSE_AVAILABLE:
    print("MegaParse not available", file=sys.stderr)
    sys.exit(1)

# Import PyMuPDF pour analyse
try:
    import fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

pdf_path = Path("{str(pdf_path).replace(chr(92), chr(92)+chr(92))}")
output_path = Path("{output_path.replace(chr(92), chr(92)+chr(92))}")

# Analyser le PDF
has_native_text = False
if PYMUPDF_AVAILABLE:
    try:
        doc = fitz.open(str(pdf_path))
        pages_to_check = min(5, doc.page_count)
        total_chars = sum(len(doc[i].get_text()) for i in range(pages_to_check))
        avg_chars = total_chars / pages_to_check if pages_to_check > 0 else 0
        has_native_text = avg_chars >= 100
        doc.close()
        print(f"PDF analysis: {{doc.page_count}} pages, native_text={{has_native_text}} ({{avg_chars:.0f}} chars/page)", file=sys.stderr)
    except Exception as e:
        print(f"PDF analysis failed: {{e}}", file=sys.stderr)

# Parser avec MegaParse
try:
    if has_native_text and STRATEGY_ENUM_AVAILABLE:
        parser = MegaParse(unstructured_strategy=StrategyEnum.FAST)
        print("Using FAST strategy (native text)", file=sys.stderr)
    else:
        parser = MegaParse()
        print("Using AUTO strategy (OCR)", file=sys.stderr)

    document = parser.load(str(pdf_path))

    # Convertir en blocs
    blocks = []

    if hasattr(document, 'chunks'):
        for idx, chunk in enumerate(document.chunks):
            blocks.append({{
                "block_type": "text",
                "block_index": idx,
                "title": None,
                "content": chunk.text if hasattr(chunk, 'text') else str(chunk),
                "page_range": (1, 1),
                "metadata": {{"length": len(chunk.text) if hasattr(chunk, 'text') else 0}}
            }})
    elif hasattr(document, 'sections'):
        for idx, section in enumerate(document.sections):
            blocks.append({{
                "block_type": "section",
                "block_index": idx,
                "title": getattr(section, 'title', None),
                "content": section.text if hasattr(section, 'text') else str(section),
                "page_range": (1, 1),
                "metadata": {{}}
            }})
    elif isinstance(document, str):
        # MegaParse retourne directement un string
        paragraphs = document.split('\\n\\n')
        for idx, para in enumerate(paragraphs):
            para = para.strip()
            if para and len(para) >= 20:
                blocks.append({{
                    "block_type": "paragraph",
                    "block_index": idx,
                    "title": None,
                    "content": para,
                    "page_range": (1, 1),
                    "metadata": {{"length": len(para)}}
                }})
    else:
        print(f"Unknown document format: {{type(document)}}", file=sys.stderr)
        sys.exit(1)

    # Écrire le résultat
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(blocks, f, ensure_ascii=False)

    print(f"Success: {{len(blocks)}} blocks extracted", file=sys.stderr)
    sys.exit(0)

except Exception as e:
    print(f"MegaParse error: {{e}}", file=sys.stderr)
    sys.exit(1)
'''

        # Exécuter le subprocess
        result = subprocess.run(
            [sys.executable, '-c', subprocess_script],
            timeout=timeout,
            capture_output=True,
            text=True,
            env={**os.environ, 'PYTHONPATH': os.environ.get('PYTHONPATH', '')}
        )

        # Log stderr (info de debug)
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                if line:
                    logger.debug(f"[MEGAPARSE_SAFE:subprocess] {line}")

        if result.returncode != 0:
            logger.warning(
                f"[MEGAPARSE_SAFE] Subprocess failed (exit={result.returncode}): "
                f"{result.stderr[:500] if result.stderr else 'no stderr'}"
            )
            return None

        # Lire le résultat
        output_file = Path(output_path)
        if not output_file.exists():
            logger.warning("[MEGAPARSE_SAFE] Output file not created")
            return None

        with open(output_file, 'r', encoding='utf-8') as f:
            blocks = json.load(f)

        logger.info(f"[MEGAPARSE_SAFE] Succès: {len(blocks)} blocs extraits")
        return blocks

    except subprocess.TimeoutExpired:
        logger.warning(
            f"[MEGAPARSE_SAFE] TIMEOUT après {timeout}s pour {pdf_path.name} - "
            f"fallback sur pdftotext"
        )
        return None

    except MemoryError:
        logger.warning(
            f"[MEGAPARSE_SAFE] OOM pour {pdf_path.name} - fallback sur pdftotext"
        )
        return None

    except Exception as e:
        logger.warning(
            f"[MEGAPARSE_SAFE] Erreur inattendue pour {pdf_path.name}: {e} - "
            f"fallback sur pdftotext"
        )
        return None

    finally:
        # Nettoyer le fichier temporaire
        try:
            if os.path.exists(output_path):
                os.unlink(output_path)
        except Exception:
            pass


def fallback_pdftotext(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Extraction de secours via pdftotext.
    Plus léger et ne provoque jamais d'OOM.

    Args:
        pdf_path: Chemin vers le fichier PDF

    Returns:
        Liste de blocs (paragraphes) extraits du texte
    """
    logger.info(f"[MEGAPARSE_SAFE:FALLBACK] Extraction pdftotext pour {pdf_path.name}")

    try:
        txt_output = pdf_path.with_suffix(".txt")

        # Exécuter pdftotext
        subprocess.run(
            ["pdftotext", str(pdf_path), str(txt_output)],
            check=True,
            stderr=subprocess.DEVNULL,
            timeout=60  # 1 minute max pour pdftotext
        )

        text = txt_output.read_text(encoding="utf-8", errors="ignore")

        # Nettoyer
        txt_output.unlink(missing_ok=True)

        # Découper en paragraphes
        blocks = []
        paragraphs = text.split('\n\n')

        for idx, para in enumerate(paragraphs):
            para = para.strip()
            if not para or len(para) < 20:
                continue

            # Détecter les titres
            is_title = (
                len(para) < 100 and
                (para.isupper() or para[0].isdigit() or para.startswith('•'))
            )

            blocks.append({
                "block_type": "section" if is_title else "paragraph",
                "block_index": idx,
                "title": para if is_title else None,
                "content": para,
                "page_range": (1, 1),
                "metadata": {
                    "length": len(para),
                    "fallback": True,
                    "extractor": "pdftotext"
                }
            })

        logger.info(f"[MEGAPARSE_SAFE:FALLBACK] pdftotext: {len(blocks)} paragraphes extraits")
        return blocks

    except subprocess.TimeoutExpired:
        logger.error("[MEGAPARSE_SAFE:FALLBACK] pdftotext timeout")
        return []

    except Exception as e:
        logger.error(f"[MEGAPARSE_SAFE:FALLBACK] pdftotext failed: {e}")
        return []


def parse_pdf_safe(
    pdf_path: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
    use_vision: bool = False
) -> List[Dict[str, Any]]:
    """
    Point d'entrée principal - MegaParse avec fallback automatique.

    Essaie MegaParse dans un subprocess isolé. En cas d'échec (timeout, OOM, crash),
    bascule automatiquement sur pdftotext.

    Args:
        pdf_path: Chemin vers le fichier PDF
        timeout: Timeout MegaParse en secondes (défaut: 300s)
        max_memory_mb: Limite mémoire MegaParse en Mo (défaut: 8192)
        use_vision: Mode Vision (non utilisé)

    Returns:
        Liste de blocs sémantiques (garantie non-vide sauf erreur totale)
    """
    # Essayer MegaParse (isolé)
    blocks = parse_pdf_with_megaparse_safe(
        pdf_path,
        timeout=timeout,
        max_memory_mb=max_memory_mb,
        use_vision=use_vision
    )

    if blocks is not None and len(blocks) > 0:
        return blocks

    # Fallback pdftotext
    logger.info(f"[MEGAPARSE_SAFE] MegaParse failed, using pdftotext fallback")
    return fallback_pdftotext(pdf_path)
