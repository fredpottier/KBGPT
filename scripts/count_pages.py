#!/usr/bin/env python3
"""Script temporaire pour compter les pages des documents."""

import os
from pathlib import Path

# PDFs
try:
    import fitz
    pdf_method = 'pymupdf'
except:
    try:
        from pypdf import PdfReader
        pdf_method = 'pypdf'
    except:
        pdf_method = None

# PPTX
try:
    from pptx import Presentation
    pptx_ok = True
except:
    pptx_ok = False

docs_done = Path('/app/data/docs_done')
results = []

for f in docs_done.iterdir():
    name = f.name
    # Skip debug copies (Joule_L0_debug.pdf, etc.)
    if name.startswith('Joule_L0_'):
        if name != 'Joule_L0.pdf':
            continue

    pages = None
    if f.suffix.lower() == '.pdf' and pdf_method:
        try:
            if pdf_method == 'pymupdf':
                doc = fitz.open(str(f))
                pages = len(doc)
                doc.close()
            else:
                reader = PdfReader(str(f))
                pages = len(reader.pages)
        except Exception as e:
            pages = -1
    elif f.suffix.lower() == '.pptx' and pptx_ok:
        try:
            prs = Presentation(str(f))
            pages = len(prs.slides)
        except Exception as e:
            pages = -1

    if pages is not None and pages > 0:
        results.append((pages, name))

# Sort by page count
results.sort(key=lambda x: x[0])

print("\n=== Documents triés par nombre de pages/slides ===\n")
for pages, name in results:
    print(f'{pages:>4} pages | {name}')
print()
