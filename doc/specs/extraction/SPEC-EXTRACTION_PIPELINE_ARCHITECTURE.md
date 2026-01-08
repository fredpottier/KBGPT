# Architecture Extraction de Texte - KnowWhere/OSMOSE

*Document de référence pour refactoring du pipeline d'extraction*
*Généré le: 2026-01-02*

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            ENTRÉE: Fichier (PDF ou PPTX)                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
                    ┌───────────────────┴───────────────────┐
                    │                                       │
                    ▼                                       ▼
            ┌──────────────┐                        ┌──────────────┐
            │  PDF Pipeline │                        │ PPTX Pipeline │
            │pdf_pipeline.py│                        │pptx_pipeline.py│
            └──────────────┘                        └──────────────┘
                    │                                       │
                    ▼                                       ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                    SORTIE: full_text (string)                 │
        │            Texte complet prêt pour OSMOSE Agentique           │
        └───────────────────────────────────────────────────────────────┘
```

---

## Pipeline PDF (`pdf_pipeline.py`)

### Flow complet

```
PDF File
    │
    ├──► [1] CACHE CHECK
    │       Si .knowcache.json existe et valide → Skip extraction, utiliser cache
    │
    ├──► [2] DÉCISION MODE
    │       │
    │       ├── MODE VISION (use_vision=True, rarement utilisé)
    │       │       │
    │       │       ├── pdf2image (convert_from_path)
    │       │       │       → Convertit chaque page en PNG
    │       │       │       → Sauvegarde dans SLIDES_PNG/
    │       │       │
    │       │       └── pdftotext (subprocess)
    │       │               → Extraction texte brut
    │       │               → Commande: pdftotext file.pdf file.txt
    │       │
    │       └── MODE TEXT-ONLY (use_vision=False, défaut) ⭐ ACTUEL
    │               │
    │               └── MegaParse (ou fallback pdftotext)
    │                       │
    │                       ├── [A] Analyse PDF (PyMuPDF/fitz)
    │                       │       - Compte les pages
    │                       │       - Détecte texte natif vs scanné
    │                       │       - Calcule chars/page moyens
    │                       │       - Seuil: 100 chars/page = texte natif
    │                       │
    │                       ├── [B] Stratégie d'extraction
    │                       │       │
    │                       │       ├── PDF texte natif (>100 chars/page)
    │                       │       │       → StrategyEnum.FAST (pas d'OCR)
    │                       │       │       → Rapide, léger en mémoire
    │                       │       │
    │                       │       └── PDF scanné (<100 chars/page)
    │                       │               → StrategyEnum.AUTO (OCR DocTR)
    │                       │               → Lent, GOURMAND EN MÉMOIRE ⚠️
    │                       │               → Cause des OOM sur gros PDFs
    │                       │
    │                       ├── [C] Parsing MegaParse
    │                       │       megaparse = MegaParse(strategy)
    │                       │       document = megaparse.load(pdf_path)
    │                       │       │
    │                       │       └── Retourne: str ou object avec chunks/sections
    │                       │
    │                       └── [D] Fallback pdftotext (si MegaParse échoue)
    │                               subprocess.run(["pdftotext", pdf, txt])
    │                               → Extraction basique sans structure
    │
    └──► [3] CONSTRUCTION full_text
            │
            ├── Si MegaParse retourne des blocs:
            │       full_text = "\n\n".join(
            │           f"--- {block_type} ---\n{content}"
            │           for block in semantic_blocks
            │       )
            │
            └── Si fallback pdftotext:
                    full_text = txt_file.read_text()
```

### Points de défaillance PDF

| Point | Cause | Conséquence |
|-------|-------|-------------|
| MegaParse + OCR | PDF scanné > 100 pages | OOM, crash app |
| MegaParse charge | Tout le PDF en mémoire | 8-16 Go pour gros PDFs |
| DocTR (OCR interne) | GPU/CPU intensive | Timeout ou OOM |

---

## Pipeline PPTX (`pptx_pipeline.py`)

### Flow complet

```
PPTX File
    │
    ├──► [1] CACHE CHECK
    │       Si .knowcache.json existe → Skip extraction complète
    │       Retourne: full_text_enriched depuis cache
    │
    ├──► [2] PRÉ-TRAITEMENT
    │       │
    │       ├── validate_pptx_media()
    │       │       → Vérifie intégrité des médias
    │       │
    │       ├── strip_animated_gifs_from_pptx()
    │       │       → Supprime GIFs animés (problématiques)
    │       │
    │       └── remove_hidden_slides_inplace()
    │               → Supprime slides cachées
    │
    ├──► [3] EXTRACTION BINAIRE
    │       │
    │       └── extract_notes_and_text(pptx_path)
    │               │
    │               ├── [A] MegaParse disponible (priorité)
    │               │       │
    │               │       ├── python-pptx pour structure
    │               │       │       prs = Presentation(pptx_path)
    │               │       │       slide_count = len(prs.slides)
    │               │       │
    │               │       ├── MegaParse pour contenu enrichi
    │               │       │       megaparse = MegaParse()
    │               │       │       content = megaparse.load(pptx_path)
    │               │       │
    │               │       └── Division proportionnelle
    │               │               split_megaparse_by_slide_count()
    │               │               → Divise content en N slides
    │               │               → Basé sur nombre de lignes
    │               │
    │               └── [B] Fallback python-pptx seul
    │                       │
    │                       ├── Itère sur chaque slide
    │                       │       for slide in prs.slides:
    │                       │
    │                       ├── Extrait texte des shapes
    │                       │       shape.text
    │                       │
    │                       ├── Extrait notes
    │                       │       slide.notes_slide.notes_text_frame.text
    │                       │
    │                       ├── Extrait tables
    │                       │       shape.table → cells → text
    │                       │
    │                       └── Extrait métadonnées charts
    │                               chart.chart_title
    │
    │       Résultat: slides_data = [
    │           {"slide_index": 1, "text": "...", "notes": "...", "megaparse_content": "..."},
    │           {"slide_index": 2, ...},
    │           ...
    │       ]
    │
    ├──► [4] CONVERSION PPTX → PDF → IMAGES
    │       │
    │       ├── LibreOffice (soffice)
    │       │       convert_pptx_to_pdf(pptx_path, SLIDES_PNG)
    │       │       → Commande: soffice --convert-to pdf
    │       │       → Génère fichier.pdf
    │       │
    │       └── PyMuPDF (fitz)
    │               convert_pdf_to_images_pymupdf(pdf_path, output_dir)
    │               → Convertit chaque page en PNG
    │               → Génère slide_1.png, slide_2.png, ...
    │               → Pour Vision et thumbnails
    │
    ├──► [5] VISION GATING (Decision per slide)
    │       │
    │       └── Pour chaque slide:
    │               result = should_use_vision(
    │                   slide_text,
    │                   slide_notes,
    │                   has_shapes,
    │                   has_images,
    │                   has_charts
    │               )
    │               │
    │               └── Retourne: VisionDecision
    │                       ├── SKIP: Texte suffit (>1200 chars, structuré)
    │                       ├── REQUIRED: Vision nécessaire (images, charts, peu de texte)
    │                       └── OPTIONAL: Cas ambigu
    │
    ├──► [6] ENRICHISSEMENT (selon gating)
    │       │
    │       ├── VISION REQUIRED/OPTIONAL
    │       │       │
    │       │       └── ask_gpt_slide_analysis(image_path, slide_text)
    │       │               │
    │       │               ├── Encode image en base64
    │       │               ├── Appel GPT-4o Vision
    │       │               │       messages = [{
    │       │               │           "type": "image_url",
    │       │               │           "image_url": {"url": f"data:image/png;base64,{b64}"}
    │       │               │       }, ...]
    │       │               │
    │       │               └── Retourne: description visuelle enrichie
    │       │
    │       └── SKIP
    │               → Utilise slide_text brut (pas d'appel Vision)
    │               → Économie ~$0.03/slide
    │
    └──► [7] CONSTRUCTION full_text_enriched
            │
            └── Concaténation de tous les résumés:
                    full_text_enriched = "\n\n".join(
                        f"=== Slide {i} ===\n{enriched_summary}"
                        for i, summary in enumerate(all_summaries)
                    )
```

### Points de défaillance PPTX

| Point | Cause | Conséquence |
|-------|-------|-------------|
| MegaParse sur PPTX géant | PPTX > 100 Mo | OOM, freeze |
| LibreOffice conversion | PPTX corrompu ou trop gros | Timeout, crash soffice |
| python-pptx sur gros PPTX | Charge tout en mémoire | Lent mais stable |

---

## Composants partagés

### MegaParse (Librairie externe)

```
MegaParse = Parser de documents "sémantique"

Entrée: PDF ou PPTX (fichier binaire)
        │
        ├── Unstructured (backend)
        │       → Détection layout
        │       → Segmentation en blocs
        │
        ├── DocTR (pour OCR si nécessaire)
        │       → OCR deep learning
        │       → TRÈS gourmand en mémoire/GPU
        │
        └── Sortie: str ou Document object
                → Texte structuré avec markdown
                → Sections, tables, listes préservées
```

**Problème principal**: MegaParse charge TOUT le document en mémoire avant traitement.

### pdftotext (Poppler, outil système)

```
pdftotext = Extraction texte basique ultra-légère

Entrée: PDF
        │
        └── Poppler (C library)
                → Extraction texte natif uniquement
                → PAS d'OCR
                → Très rapide, très léger

Sortie: fichier .txt avec texte brut
```

### python-pptx (Librairie Python)

```
python-pptx = Manipulation native PPTX

Entrée: PPTX (fichier Office Open XML)
        │
        ├── Parse le ZIP interne
        │       → slides/slide1.xml
        │       → notesSlides/notesSlide1.xml
        │       → etc.
        │
        └── Extraction:
                → Texte des shapes
                → Notes du présentateur
                → Tables
                → Métadonnées charts

Sortie: Objets Python (Presentation, Slide, Shape, etc.)
```

---

## Système de Cache (`extraction_cache.py`)

```
Avant extraction:
    │
    ├── Cherche: data/extraction_cache/{hash}.knowcache.json
    │
    ├── Si trouvé ET valide (< 30 jours):
    │       → Skip TOUTE l'extraction
    │       → Utilise full_text depuis cache
    │       → Économise Vision calls + temps
    │
    └── Si pas trouvé:
            → Extraction normale
            → Sauvegarde cache à la fin

Format cache:
{
    "source_file_hash": "abc123...",
    "extracted_text": { "full_text": "..." },
    "document_metadata": { "title": "...", "pages": 42 },
    "extraction_stats": {
        "duration_seconds": 45.2,
        "vision_calls": 15,
        "cost_usd": 0.45
    }
}
```

---

## Résumé des technologies par étape

| Étape | PDF | PPTX |
|-------|-----|------|
| Parsing binaire | MegaParse ou pdftotext | MegaParse + python-pptx |
| OCR (si nécessaire) | DocTR via MegaParse | N/A |
| Conversion images | pdf2image (Pillow) | LibreOffice → PyMuPDF |
| Enrichissement Vision | GPT-4o Vision | GPT-4o Vision |
| Fallback | pdftotext | python-pptx seul |

---

## Problèmes architecturaux identifiés

1. **MegaParse monolithique**: Charge tout en mémoire, pas de streaming
2. **Pas d'isolation**: Un OOM crash l'app entière
3. **OCR intégré**: DocTR dans le même process = risque OOM
4. **Timeout implicites**: Pas de timeout sur MegaParse.load()
5. **Fallback tardif**: On détecte l'échec après le crash

---

## Fichiers source de référence

| Fichier | Rôle |
|---------|------|
| `src/knowbase/ingestion/pipelines/pdf_pipeline.py` | Pipeline PDF principal |
| `src/knowbase/ingestion/pipelines/pptx_pipeline.py` | Pipeline PPTX principal |
| `src/knowbase/ingestion/parsers/megaparse_pdf.py` | Wrapper MegaParse pour PDF |
| `src/knowbase/ingestion/parsers/megaparse_safe.py` | Circuit breaker MegaParse (nouveau) |
| `src/knowbase/ingestion/components/extractors/binary_parser.py` | Extraction binaire PPTX |
| `src/knowbase/ingestion/components/transformers/vision_gating.py` | Gating Vision v3.4 |
| `src/knowbase/ingestion/extraction_cache.py` | Système de cache |

---

*Ce document sert de base pour la refonte de l'architecture d'extraction.*
