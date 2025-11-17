# Architecture Modulaire des Composants d'Ingestion

**Extraction de `pptx_pipeline.py` (2871 lignes) en composants réutilisables**

## 📁 Structure

```
components/
├── __init__.py           # Point d'entrée, exports
├── README.md             # Cette documentation
│
├── extractors/           # Extraction données brutes
│   ├── checksum_calculator.py   # SHA256 pour détection duplicatas
│   ├── metadata_extractor.py    # Métadonnées PPTX (core.xml, app.xml)
│   ├── slide_cleaner.py         # Suppression slides cachés, GIF stripping
│   └── binary_parser.py         # MegaParse + python-pptx extraction
│
├── converters/           # Conversion formats
│   ├── pptx_to_pdf.py           # LibreOffice headless conversion
│   └── pdf_to_images.py         # PyMuPDF rendering
│
├── transformers/         # Enrichissement LLM
│   ├── chunker.py               # Token chunking
│   ├── deck_summarizer.py       # Résumé global deck
│   ├── llm_analyzer.py          # Analyse GPT text-only
│   └── vision_analyzer.py       # Analyse GPT-4V avec images
│
├── sinks/                # Écriture données enrichies
│   ├── qdrant_writer.py         # Ingestion chunks dans Qdrant
│   └── neo4j_writer.py          # Métadonnées et relations Neo4j
│
└── utils/                # Utilitaires réutilisables
    ├── subprocess_utils.py      # run_cmd()
    ├── image_utils.py           # encode_base64, normalize_url
    └── text_utils.py            # clean_gpt, language_detect, chunking
```

## 🔄 Pipelines Composables

### Pipeline PPTX (complet)

```python
from knowbase.ingestion.components.extractors import (
    remove_hidden_slides_inplace,
    extract_pptx_metadata,
    extract_notes_and_text,
)
from knowbase.ingestion.components.converters import (
    convert_pptx_to_pdf,
    convert_pdf_to_images_pymupdf,
)
from knowbase.ingestion.components.transformers import (
    analyze_deck_summary,
    ask_gpt_slide_analysis,
)
from knowbase.ingestion.components.sinks import ingest_chunks

# 1. Clean slides
remove_hidden_slides_inplace(pptx_path)

# 2. Extract metadata
metadata = extract_pptx_metadata(pptx_path)

# 3. Convert to PDF
pdf_path = convert_pptx_to_pdf(pptx_path, output_dir)

# 4. Generate images
images = convert_pdf_to_images_pymupdf(pdf_path)

# 5. Extract text
slides_data = extract_notes_and_text(pptx_path)

# 6. Analyze with LLM
deck_summary = analyze_deck_summary(slides_data)

# 7. Analyze slides with Vision
for slide, image in zip(slides_data, images):
    analysis = ask_gpt_slide_analysis(slide, image)

# 8. Write to Qdrant
ingest_chunks(chunks, metadata, file_uid, slide_index, deck_summary)
```

### Pipeline PDF (skip PPTX→PDF)

```python
from knowbase.ingestion.components.converters import convert_pdf_to_images_pymupdf
from knowbase.ingestion.components.transformers import analyze_deck_summary
from knowbase.ingestion.components.sinks import ingest_chunks

# 1. Generate images directement depuis PDF
images = convert_pdf_to_images_pymupdf(pdf_path)

# 2. Extract text (via OCR si nécessaire)
slides_data = extract_text_from_pdf(pdf_path)  # À implémenter

# 3. Continue pipeline normal
deck_summary = analyze_deck_summary(slides_data)
# etc.
```

### Pipeline DOCX (skip PPTX cleaning)

```python
from knowbase.ingestion.components.converters import convert_pptx_to_pdf  # Fonctionne aussi pour DOCX
from knowbase.ingestion.components.converters import convert_pdf_to_images_pymupdf

# 1. Convert DOCX→PDF (LibreOffice gère DOCX aussi)
pdf_path = convert_pptx_to_pdf(docx_path, output_dir)  # Même fonction!

# 2. Generate images
images = convert_pdf_to_images_pymupdf(pdf_path)

# 3. Continue pipeline normal
```

## 🎯 Avantages de l'Architecture

### 1. **Réutilisabilité**
- Chaque composant indépendant et testable
- Pas de duplication de code entre pipelines PPTX/PDF/DOCX

### 2. **Testabilité**
- Tests unitaires par composant (~200 lignes/fichier)
- Mock facile des dépendances

### 3. **Composition Flexible**
- Pipeline adaptable selon le type de fichier
- Étapes optionnelles (Vision, Neo4j, etc.)

### 4. **Maintenabilité**
- Structure claire vs 2871 lignes monolithiques
- Séparation responsabilités (extraction, conversion, transformation, écriture)

### 5. **Extensibilité**
- Facile d'ajouter nouveaux formats (EPUB, Markdown, etc.)
- Nouveaux transformers (OCR, Speech-to-Text, etc.)

## 📊 Métriques

| Métrique | Avant | Après | Amélioration |
|----------|-------|-------|--------------|
| **Taille fichier max** | 2871 lignes | ~300 lignes | 90% réduction |
| **Nombre de fichiers** | 1 monolithe | 16 modules | Structure claire |
| **Testabilité** | Difficile | Unitaire | ✅ Testable |
| **Réutilisabilité** | Code dupliqué | Composants partagés | ✅ DRY |

## 🔧 TODO - Extraction Complète

Certains composants sont actuellement des **wrappers** qui importent depuis `pptx_pipeline.py` :

- `transformers/llm_analyzer.py` : Extraire `analyze_deck_summary`, `ask_gpt_slide_analysis_text_only`
- `transformers/vision_analyzer.py` : Extraire `ask_gpt_slide_analysis`, `ask_gpt_vision_summary`
- `sinks/qdrant_writer.py` : Extraire `ingest_chunks`, `embed_texts`
- `sinks/neo4j_writer.py` : Implémenter `write_document_metadata`, `write_slide_relations`

**Raison** : Ces fonctions font 300-400 lignes chacune avec logique métier complexe (prompt management, retry logic, etc.). Extraction progressive recommandée.

## 🚀 Phase 1 OSMOSE - Intégration

Cette architecture modulaire facilite l'intégration des composants OSMOSE Phase 1 :

- **NarrativeThreadDetector** → `transformers/narrative_detector.py` (à créer)
- **ConceptExplainer** → `transformers/concept_explainer.py` (à créer)
- **Proto-KG Writer** → `sinks/proto_kg_writer.py` (à créer)

---

*Créé le 2025-11-17 dans le cadre du pivot OSMOSE Phase 1*
