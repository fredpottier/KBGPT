# Analyse Cleanup Legacy V1

**Date**: 2025-01-05
**Objectif**: Identifier et supprimer le code legacy V1 suite au passage complet sur Extraction V2

---

## Synthese Executive

| Categorie | Fichiers | Lignes | Status |
|-----------|----------|--------|--------|
| Pipelines V1 (PDF, PPTX) | 5 | ~2,356 | A SUPPRIMER |
| Components V1 | 17 | ~3,708 | A SUPPRIMER |
| Jobs V1 (partiel) | 1 | ~300 | A REFACTORER |
| Modules orphelins | 4 | ~500 | A SUPPRIMER |
| Dossier duplique | 1 | ~3,000 | A SUPPRIMER |
| **TOTAL ESTIMÉ** | **~28** | **~9,864** | |

---

## 1. CODE A SUPPRIMER (SAFE)

### 1.1 Pipelines V1 Legacy

Ces pipelines sont remplacés par `ExtractionPipelineV2` + `jobs_v2.py`:

```
src/knowbase/ingestion/pipelines/
├── pdf_pipeline.py          # 1,198 lignes - SUPPRIMER
├── pptx_pipeline.py         # 1,158 lignes - SUPPRIMER
└── __init__.py              # A nettoyer les exports
```

**Raison**: ExtractionPipelineV2 gère maintenant PDF et PPTX avec Vision Gating V4.

**Impact**:
- `jobs.py` importe ces pipelines → devra être nettoyé
- `dispatcher.py` route vers V1 quand V2 disabled → simplifiera le code

### 1.2 Components V1 (TOUT le dossier)

Le dossier `components/` n'est utilisé QUE par `pptx_pipeline.py`:

```
src/knowbase/ingestion/components/
├── converters/
│   ├── pdf_to_images.py       # Remplacé par Docling + PyMuPDF dans V2
│   ├── pptx_to_pdf.py         # Non utilisé en V2
│   └── __init__.py
├── extractors/
│   ├── binary_parser.py       # Non utilisé
│   ├── checksum_calculator.py # Non utilisé
│   ├── metadata_extractor.py  # Non utilisé
│   ├── slide_cleaner.py       # Non utilisé en V2
│   └── __init__.py
├── transformers/
│   ├── chunker.py             # Remplacé par hybrid_anchor_chunker
│   ├── deck_summarizer.py     # Remplacé par OSMOSE
│   ├── llm_analyzer.py        # Remplacé par extraction_v2/vision/
│   ├── vision_analyzer.py     # CAUSE DU BUG! Remplacé par extraction_v2/vision/analyzer.py
│   ├── vision_gating.py       # V3.4 - Non utilisé! V2 a son propre gating/engine.py
│   └── __init__.py
├── sinks/
│   ├── neo4j_writer.py        # A verifier si utilisé ailleurs
│   ├── qdrant_writer.py       # A verifier si utilisé ailleurs
│   └── __init__.py
├── utils/
│   ├── image_utils.py
│   ├── subprocess_utils.py
│   ├── text_utils.py          # ATTENTION: Peut etre utilisé ailleurs
│   └── __init__.py
├── README.md
└── __init__.py
```

**TOTAL**: ~3,708 lignes

**Verification supplementaire requise**:
- `text_utils.py` - grep montre usage dans pptx_pipeline uniquement
- `qdrant_writer.py` / `neo4j_writer.py` - vérifier si API les utilise

### 1.3 Dossier Dupliqué

```
src/knowbase/extraction_v2/extraction_v2/    # DOUBLON COMPLET - SUPPRIMER
├── adapters/
├── cache/
├── extractors/
├── gating/
├── merge/
├── models/
├── vision/
├── pipeline.py
└── __init__.py
```

**Raison**: Structure dupliquée par erreur. Zero imports vers ce chemin.
**Taille estimee**: ~3,000 lignes

### 1.4 Parsers V1

```
src/knowbase/ingestion/parsers/
├── megaparse_pdf.py     # Non utilisé directement
├── megaparse_safe.py    # Utilisé UNIQUEMENT par pdf_pipeline.py
└── __init__.py
```

**Raison**: Docling remplace MegaParse dans V2.

### 1.5 Modules Orphelins (Zero Usage)

```
src/knowbase/ingestion/facts_extractor.py      # Zero imports - SUPPRIMER
src/knowbase/ingestion/notifications.py        # Zero imports - SUPPRIMER
src/knowbase/facts/                            # Module vide sauf __init__ - SUPPRIMER
src/knowbase/ui/streamlit_app.py               # Zero imports - VERIFIER si utilisé via Dockerfile
src/knowbase/rules/                            # Zero imports externes - SUPPRIMER
```

---

## 2. CODE A REFACTORER

### 2.1 Jobs V1 → Fusion avec Jobs V2

**Fichier**: `src/knowbase/ingestion/queue/jobs.py` (413 lignes)

**Probleme**: Contient du code mixte:
- `ingest_pdf_job`, `ingest_pptx_job` → V1, A SUPPRIMER
- `ingest_excel_job` → Toujours necessaire (Excel pas dans V2)
- `send_worker_heartbeat`, `update_job_progress` → DUPLIQUES dans jobs_v2.py

**Action**:
1. Migrer `ingest_excel_job` vers jobs_v2.py
2. Supprimer les fonctions V1 (pdf, pptx)
3. Unifier `send_worker_heartbeat`/`update_job_progress` dans un seul endroit
4. Supprimer jobs.py

### 2.2 Dispatcher Simplification

**Fichier**: `src/knowbase/ingestion/queue/dispatcher.py`

**Probleme actuel**:
```python
if _is_extraction_v2_enabled() and _is_format_supported_v2("pdf"):
    return enqueue_document_v2(...)  # V2
else:
    return jobs.ingest_pdf_job(...)  # V1 fallback
```

**Action**: Supprimer le fallback V1, ne garder que V2

### 2.3 Queue __init__.py

**Fichier**: `src/knowbase/ingestion/queue/__init__.py`

**Probleme**: Exporte depuis `jobs.py`:
```python
from .jobs import (
    send_worker_heartbeat,
    update_job_progress,
)
```

**Action**: Changer pour importer depuis `jobs_v2.py`

---

## 3. CODE A CONSERVER

### 3.1 Pipelines Excel (A garder pour l'instant)

```
src/knowbase/ingestion/pipelines/excel_pipeline.py
src/knowbase/ingestion/pipelines/fill_excel_pipeline.py
src/knowbase/ingestion/pipelines/smart_fill_excel_pipeline.py
```

**Raison**: Excel n'est pas encore migré vers V2

### 3.2 Modules Actifs

```
src/knowbase/ingestion/osmose_agentique.py      # Coeur OSMOSE
src/knowbase/ingestion/osmose_integration.py    # Utilisé par osmose_agentique
src/knowbase/ingestion/folder_watcher.py        # Point d'entrée ingestion
src/knowbase/ingestion/extraction_cache.py      # Cache V1, mais referenced dans analytics
src/knowbase/ingestion/enrichment_tracker.py    # Utilisé par osmose_agentique
src/knowbase/ingestion/hybrid_anchor_chunker.py # Phase 2 Hybrid Anchor
src/knowbase/ingestion/text_chunker.py          # Utilisé par osmose_agentique (fallback)
src/knowbase/ingestion/pass2_orchestrator.py    # Phase 2 Pass 2
src/knowbase/ingestion/validate_osmose_deps.py  # CLI utilitaire
```

### 3.3 Burst Mode

```
src/knowbase/ingestion/burst/                   # Module complet - GARDER
```

### 3.4 CLI Utilitaires

```
src/knowbase/ingestion/cli/                     # Scripts utilitaires - GARDER
```

Note: Verifier si `update_main_solution.py` et `update_supporting_solutions.py` sont
encore pertinents post-pivot OSMOSE (references SAP Solutions?).

---

## 4. FICHIERS DE TEST A NETTOYER

```
tests/ingestion/test_facts_extraction.py  # Reference vision_analyzer V1
```

---

## 5. CONFIGURATION A NETTOYER

### 5.1 Feature Flags

Dans `config/feature_flags.yaml`, simplifier:
- Supprimer le toggle `extraction_v2.enabled` (toujours true maintenant)
- Supprimer les references aux phases anterieures si plus utilisées

### 5.2 Archives Config

```
config/archive/       # Verifier si nécessaire
config/agents/        # Verifier l'usage
```

---

## 6. PLAN D'EXECUTION RECOMMANDE

### Phase 1: Preparation (Risque: Faible)
1. [ ] Creer branche `cleanup/legacy-v1`
2. [ ] Backup de l'etat actuel (tag git)

### Phase 2: Suppression Safe (Risque: Faible)
1. [ ] Supprimer `extraction_v2/extraction_v2/` (dossier dupliqué)
2. [ ] Supprimer modules orphelins (facts_extractor, notifications, facts/, rules/)
3. [ ] Lancer tests pour verifier aucune regression

### Phase 3: Refactoring Jobs (Risque: Moyen)
1. [ ] Migrer `ingest_excel_job` de jobs.py vers jobs_v2.py
2. [ ] Unifier `send_worker_heartbeat` / `update_job_progress`
3. [ ] Mettre a jour `queue/__init__.py`
4. [ ] Supprimer jobs.py
5. [ ] Tests complets

### Phase 4: Suppression Pipelines V1 (Risque: Moyen)
1. [ ] Supprimer pdf_pipeline.py
2. [ ] Supprimer pptx_pipeline.py
3. [ ] Supprimer tout le dossier components/
4. [ ] Supprimer le dossier parsers/
5. [ ] Simplifier dispatcher.py (enlever fallback V1)
6. [ ] Tests complets + import burst test

### Phase 5: Cleanup Final (Risque: Faible)
1. [ ] Nettoyer feature_flags.yaml
2. [ ] Supprimer tests obsoletes
3. [ ] Mettre a jour documentation
4. [ ] Verifier CLI utilitaires

---

## 7. IMPACT ESTIMÉ

| Metrique | Avant | Apres | Delta |
|----------|-------|-------|-------|
| Lignes de code | ~150K | ~140K | -10K |
| Fichiers Python | ~200 | ~175 | -25 |
| Complexite dispatcher | 2 branches | 1 branche | -50% |
| Duplication | Elevee | Basse | -- |

---

## 8. RISQUES ET MITIGATIONS

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Regression Excel | Haut | Migrer excel vers jobs_v2 avant suppression |
| Imports caches | Moyen | Grep exhaustif avant suppression |
| Tests cassés | Bas | Lancer suite de tests apres chaque phase |
| Rollback nécessaire | Bas | Tag git avant chaque phase |

---

## 9. CONCLUSION

Le code V1 represente environ **10,000 lignes** de code mort ou dupliqué qui:
1. Genere de la confusion (2 systemes de Vision Gating)
2. Cause des bugs (le probleme des 3000 pages)
3. Augmente la surface de maintenance
4. Pollue les imports et la navigation

Le cleanup est SAFE si execute par phases avec tests entre chaque etape.

**Recommandation**: Executer ce cleanup AVANT tout nouveau developpement pour eviter
d'autres incidents comme celui du document de 3000 pages sans Vision Gating.
