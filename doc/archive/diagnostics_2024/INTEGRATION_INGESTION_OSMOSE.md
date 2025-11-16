# 🔗 Intégration Ingestion ↔ OSMOSE Pipeline

**Date:** 2025-10-14
**Status:** ⚠️ À INTÉGRER

---

## 🎯 Situation Actuelle

### ✅ Traitement Différencié DÉJÀ IMPLÉMENTÉ

**Pipelines d'ingestion existants:**

#### 1. PPTX Pipeline (`src/knowbase/ingestion/pipelines/pptx_pipeline.py`)

**Mode VISION (par défaut):**
```python
def process_pptx(pptx_path: Path, use_vision: bool = True):
    # Mode VISION: GPT-4 Vision avec images des slides
    # Analyse layout, organisation visuelle, graphiques
    # Utilise: gpt-4-vision-preview
```

**Features:**
- ✅ Conversion PDF → Images (DPI adaptatif)
- ✅ GPT-4 Vision sur chaque slide (avec image)
- ✅ Analyse layout et organisation visuelle
- ✅ Extraction contexte global deck
- ✅ Thumbnails générés automatiquement
- ✅ Mode text-only en fallback

**Prompt PPTX Vision:**
- Analyse organisation visuelle
- Hiérarchie informations (titres, bullets, graphiques)
- Relations entre éléments visuels
- Context deck global

#### 2. PDF Pipeline (`src/knowbase/ingestion/pipelines/pdf_pipeline.py`)

**Mode VISION (pour PDFs complexes):**
```python
def process_pdf(pdf_path: Path, use_vision: bool = True):
    # Mode VISION: GPT-4 Vision page par page
    # Pour PDFs avec graphiques, tableaux complexes, schémas
```

**Mode TEXT-ONLY (par défaut pour PDFs textuels):**
```python
def process_pdf(pdf_path: Path, use_vision: bool = False):
    # Mode TEXT-ONLY: MegaParse + LLM rapide
    # Découpage intelligent en blocs sémantiques
    # Utilise: gpt-4o-mini (plus rapide, moins cher)
```

**Features:**
- ✅ MegaParse pour découpage intelligent
- ✅ Blocs sémantiques (sections, paragraphs, tables, lists)
- ✅ GPT-4 Vision en option pour PDFs complexes
- ✅ pdftotext pour extraction texte pur

---

## 🔀 Architecture Actuelle

```
┌─────────────────────────────────────────────────────────────┐
│ INGESTION (Existant)                                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  PPTX Pipeline                    PDF Pipeline             │
│  (use_vision=True)                (use_vision=False)       │
│       ↓                                 ↓                   │
│  GPT-4 Vision                     MegaParse                │
│  + Images slides                  + pdftotext              │
│       ↓                                 ↓                   │
│  Chunks enrichis                  Blocs sémantiques        │
│       ↓                                 ↓                   │
│  ┌──────────────────────────────────────────┐              │
│  │  Qdrant "knowbase" collection            │              │
│  │  (chunks avec embeddings)                │              │
│  └──────────────────────────────────────────┘              │
│                                                             │
└─────────────────────────────────────────────────────────────┘

                          ❌ PAS CONNECTÉ ❌

┌─────────────────────────────────────────────────────────────┐
│ OSMOSE Phase 1 V2.1 (Nouveau)                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  SemanticPipelineV2                                         │
│  (process_document_semantic_v2)                             │
│       ↓                                                     │
│  TopicSegmenter → ConceptExtractor → SemanticIndexer       │
│  → ConceptLinker                                            │
│       ↓                                                     │
│  ┌──────────────────────────────────────────┐              │
│  │  Proto-KG (Neo4j + Qdrant concepts_proto) │              │
│  │  (concepts canoniques + relations)       │              │
│  └──────────────────────────────────────────┘              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚠️ Problème Actuel

### Pipelines Séparés

1. **Ingestion → Qdrant "knowbase"**
   - Chunks textuels enrichis
   - Embeddings
   - Pas de concepts canoniques
   - Pas de cross-lingual unification

2. **OSMOSE Phase 1 → Proto-KG**
   - Concepts canoniques multilingues
   - Relations cross-documents
   - Hiérarchies
   - **Mais prend du `text_content` brut en entrée**

### Gap à Combler

**Le pipeline OSMOSE ne reçoit pas encore le texte des pipelines d'ingestion !**

---

## ✅ Solution : Intégration

### Option 1: Appel Direct (Recommandé)

**Intégrer OSMOSE dans les pipelines d'ingestion existants:**

```python
# Dans pptx_pipeline.py et pdf_pipeline.py

async def process_document_with_osmose(
    file_path: Path,
    document_id: str,
    text_content: str,
    use_vision: bool
):
    """
    Pipeline complet: Ingestion + OSMOSE
    """

    # 1. Ingestion existante (PPTX ou PDF)
    if file_path.suffix == ".pptx":
        chunks = process_pptx(file_path, use_vision=True)
    else:
        chunks = process_pdf(file_path, use_vision=False)

    # Stocker chunks dans Qdrant "knowbase" (existant)
    store_chunks_in_qdrant(chunks)

    # 2. Pipeline OSMOSE V2.1 (nouveau)
    from knowbase.semantic.semantic_pipeline_v2 import process_document_semantic_v2
    from knowbase.common.llm_router import get_llm_router

    llm_router = get_llm_router()

    result = await process_document_semantic_v2(
        document_id=document_id,
        document_title=file_path.stem,
        document_path=str(file_path),
        text_content=text_content,  # ✅ Texte déjà extrait
        llm_router=llm_router
    )

    # 3. Stocker dans Proto-KG
    store_in_proto_kg(result)

    return {
        "chunks": chunks,
        "osmose": result
    }
```

**Avantages:**
- ✅ Intégration simple
- ✅ Réutilise code existant
- ✅ Double storage: knowbase + Proto-KG
- ✅ Pas de duplication de traitement

### Option 2: Event-Driven (Future)

**Utiliser événements pour découplage:**

```python
# Ingestion émet événement
emit_event("document.ingested", {
    "document_id": doc_id,
    "text_content": text,
    "file_path": path
})

# OSMOSE écoute événement
@on_event("document.ingested")
async def process_with_osmose(event):
    await process_document_semantic_v2(...)
```

---

## 🎯 Recommandation: Phase 1.5 - Intégration

### Durée: 1 semaine

**Objectif:**
Connecter pipelines d'ingestion existants avec OSMOSE Phase 1 V2.1

**Tasks:**

1. **Créer wrapper d'intégration** (2 jours)
   - `src/knowbase/ingestion/osmose_integration.py`
   - Fonction `process_document_with_osmose()`
   - Gestion des 2 pipelines (ingestion + OSMOSE)

2. **Modifier pipelines existants** (1 jour)
   - Appeler OSMOSE après ingestion
   - Passer `text_content` extrait
   - Stocker dans Proto-KG

3. **Configuration** (1 jour)
   - Feature flag `ENABLE_OSMOSE_PIPELINE=true`
   - Possibilité de désactiver OSMOSE (legacy)
   - Configuration par type de document

4. **Tests** (2 jours)
   - Test PPTX → OSMOSE
   - Test PDF → OSMOSE
   - Validation double storage (knowbase + Proto-KG)

5. **Documentation** (1 jour)
   - Guide intégration
   - Migration progressive

---

## 📊 Flux Complet Intégré

```
Document (PPTX/PDF)
      ↓
┌─────────────────────────────────────────┐
│ Ingestion Pipeline                      │
├─────────────────────────────────────────┤
│ PPTX: GPT-4 Vision + Images            │
│ PDF:  MegaParse + pdftotext             │
│                                         │
│ → Chunks enrichis                       │
│ → text_content extrait                  │
└─────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────┐
│ Storage: Qdrant "knowbase"              │
│ (chunks + embeddings)                   │
└─────────────────────────────────────────┘
      ↓
      ↓ text_content
      ↓
┌─────────────────────────────────────────┐
│ OSMOSE Pipeline V2.1                    │
├─────────────────────────────────────────┤
│ TopicSegmenter                          │
│     ↓                                   │
│ ConceptExtractor (NER+Clustering+LLM)   │
│     ↓                                   │
│ SemanticIndexer (cross-lingual)         │
│     ↓                                   │
│ ConceptLinker (DocumentRole)            │
│                                         │
│ → Concepts canoniques                   │
│ → Relations cross-documents             │
└─────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────┐
│ Storage: Proto-KG                       │
│ (Neo4j + Qdrant concepts_proto)         │
└─────────────────────────────────────────┘
```

---

## 🔧 Configuration Proposée

### Feature Flags

```python
# .env ou config
ENABLE_OSMOSE_PIPELINE=true           # Activer OSMOSE
OSMOSE_FOR_PPTX=true                  # OSMOSE sur PPTX
OSMOSE_FOR_PDF=true                   # OSMOSE sur PDF
OSMOSE_MIN_TEXT_LENGTH=500            # Skip si < 500 chars
```

### Configuration par Type

```yaml
# config/ingestion.yaml
document_types:
  presentation:
    use_vision: true
    enable_osmose: true

  technical_document:
    use_vision: false
    enable_osmose: true

  audit_report:
    use_vision: false
    enable_osmose: true
```

---

## 🚀 Migration Progressive

### Phase 1.5.1: Proof of Concept (3 jours)
- Intégrer OSMOSE sur 1 type de document (PPTX)
- Validation avec 10 documents test
- Métriques performance

### Phase 1.5.2: Déploiement Partiel (2 jours)
- Activer OSMOSE sur PPTX + PDF
- Feature flag pour rollback facile
- Monitoring ajouté

### Phase 1.5.3: Production (2 jours)
- Activation sur tous documents
- Documentation utilisateur
- Guide troubleshooting

---

## 📈 Avantages Intégration

### Fonctionnel
- ✅ Double bénéfice: chunks + concepts canoniques
- ✅ Cross-lingual unification automatique
- ✅ Relations cross-documents
- ✅ DocumentRole classification

### Technique
- ✅ Réutilise pipelines existants (pas de duplication)
- ✅ Feature flag pour rollback
- ✅ Performance optimisée (1 seul passage)

### Business
- ✅ USP KnowWhere vs Copilot/Gemini démontré
- ✅ Language-agnostic knowledge graph
- ✅ Meilleure recherche sémantique

---

## 🎯 Timeline Proposée

| Semaine | Phase | Livrable |
|---------|-------|----------|
| **Semaine 11** | Phase 1.5 - Intégration | Wrapper intégration + Tests |
| **Semaine 12** | Validation | 100 docs test + Métriques |
| **Semaine 13** | Production | Déploiement + Documentation |

---

## 📝 Résumé Exécutif

### Situation
- ✅ Traitement différencié PPTX (vision) vs PDF (texte) **existe déjà**
- ✅ OSMOSE Phase 1 V2.1 **complete**
- ❌ **Pas encore connectés ensemble**

### Solution
- Créer **Phase 1.5 - Intégration** (1 semaine)
- Wrapper pour appeler OSMOSE après ingestion
- Feature flags pour contrôle progressif

### Bénéfices
- Double storage: chunks (recherche) + concepts canoniques (intelligence)
- Cross-lingual unification automatique
- Relations cross-documents
- USP KnowWhere établi

---

**Version:** 1.0
**Date:** 2025-10-14
**Status:** Recommandation pour Phase 1.5
