# Évaluation DeepSeek-OCR pour OSMOSE

**Objectif**: Évaluer si DeepSeek-OCR peut résoudre le problème de performance (1h30 pour 230 slides) tout en préservant l'USP cross-lingual d'OSMOSE.

**Documentation complète**: `doc/ongoing/OSMOSE_DEEPSEEK_OCR_EVALUATION_PLAN.md`

---

## 🎯 Vue d'Ensemble

### Problème à Résoudre
- **Performance bloquante**: 1h30 pour traiter 230 slides PPTX
- **Goulot principal**: Vision extraction GPT-4V (5-10 min sur 90 min total)

### Solution Potentielle
- **DeepSeek-OCR**: 10x compression via vision tokens
- **Gain attendu**: 1h30 → 20-30 min (3-5x improvement)
- **Risque**: Préserver cross-lingual canonicalization (USP critique)

### Validation en 3 Phases
1. **Phase 1**: Faisabilité hardware (RTX 5070 TI compatible?)
2. **Phase 2**: Benchmark performance (gain réel?)
3. **Phase 3**: USP validation (cross-lingual préservé?) ← **CRITIQUE**

---

## 📁 Structure

```
tests/eval_deepseek/
├── README.md                        # Ce fichier
├── test_01_hello_world.py           # Phase 1: Faisabilité
├── test_02_benchmark_230_slides.py  # Phase 2: Performance
├── test_03_cross_lingual.py         # Phase 3: USP Validation
│
├── fixtures/                        # Test data
│   ├── cross_lingual/               # Slides EN/FR/DE
│   │   ├── crr_definition_en.png
│   │   ├── crr_definition_fr.png
│   │   └── crr_definition_de.png
│   └── real_230_slides.pptx         # Document test réel
│
└── results/                         # Résultats JSON
    ├── phase1_feasibility.json
    ├── phase2_performance.json
    └── phase3_cross_lingual.json
```

---

## 🚀 Quick Start

### Prérequis

#### Hardware
- ✅ RTX 5070 TI (16GB VRAM) ou équivalent
- ✅ CUDA 11.8+ drivers installés
- ✅ 32GB RAM système recommandé

#### Software - Installation

```bash
# 1. Environnement Python
conda create -n deepseek-ocr python=3.10
conda activate deepseek-ocr

# 2. PyTorch + CUDA
pip install torch==2.6.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 3. DeepSeek-OCR dependencies
pip install transformers>=4.51.1
pip install flash-attn==2.7.3
pip install vllm==0.8.5

# 4. OSMOSE pipeline dependencies (pour Phase 3)
pip install sentence-transformers
pip install spacy
python -m spacy download en_core_web_lg
python -m spacy download fr_core_news_lg
python -m spacy download de_core_news_lg

# 5. Autres
pip install scikit-learn pillow python-pptx
```

#### Clone DeepSeek-OCR Repo

```bash
git clone https://github.com/deepseek-ai/DeepSeek-OCR.git
cd DeepSeek-OCR
pip install -e .
```

---

## 📊 Exécution des Tests

### Phase 1: Faisabilité Hardware (5-10 min)

**Objectif**: Valider que RTX 5070 TI peut charger et exécuter DeepSeek-OCR

```bash
cd tests/eval_deepseek
python test_01_hello_world.py
```

**Métriques de succès**:
- ✅ VRAM peak < 14GB
- ✅ Modèle charge sans erreur
- ✅ Inference basique fonctionne

**Si FAIL** (VRAM insuffisante):
```python
# Le script retentera automatiquement en mode 4-bit quantization
# Ou forcer manuellement:
from test_01_hello_world import Phase1FeasibilityTest
tester = Phase1FeasibilityTest()
results = tester.run_phase1(use_4bit=True)
```

**Decision Gate**: Si FAIL même en 4-bit → STOP (hardware insuffisant)

---

### Phase 2: Benchmark Performance (30-60 min)

**Objectif**: Mesurer gain performance réel sur 230 slides

```bash
python test_02_benchmark_230_slides.py
```

**Pré-requis**:
- Fournir PPTX de test (230 slides) dans:
  - `data/docs_in/test_230_slides.pptx` OU
  - `tests/eval_deepseek/fixtures/real_230_slides.pptx`
- Si absent: script génère estimations basées specs

**Métriques de succès**:
- ✅ Vision extraction < 5 min (vs 10 min baseline GPT-4V)
- ✅ Pipeline total estimé < 30 min (vs 1h30 baseline)
- ✅ Gain total ≥ 3x

**Decision Gate**:
- Gain ≥ 3x → **PASS** - GO Phase 3
- Gain 2-3x → **PARTIAL** - Envisager hybrid approach
- Gain < 2x → **FAIL** - Pas worth it (mais continuer Phase 3 pour learning)

---

### Phase 3: Validation USP Cross-Lingual (1-2h) ⚠️ CRITIQUE

**Objectif**: Valider que cross-lingual canonicalization fonctionne toujours

```bash
python test_03_cross_lingual.py
```

**Pré-requis**: Créer fixtures cross-lingual (voir section suivante)

**Métriques de succès**:
- ✅ Similarity EN-FR ≥ 0.85
- ✅ Similarity EN-DE ≥ 0.85
- ✅ Similarity FR-DE ≥ 0.85

**Decision Gate**:
- **PASS** → ✅ USP préservé - **RECOMMANDER Scénario A**
- **FAIL** → ❌ USP compromis - **ABANDONNER DeepSeek-OCR**

**Note**: Ce test est **NON-NÉGOCIABLE** - USP cross-lingual est différenciation critique OSMOSE

---

## 🎨 Créer Fixtures Cross-Lingual

Les fixtures sont nécessaires pour Phase 3. Créer slides PPTX simples avec même concept en 3 langues.

### Option 1: Automatique (Python Script)

```python
# Script: create_cross_lingual_fixtures.py
from pptx import Presentation
from pptx.util import Inches, Pt

def create_crr_slide(lang: str, text: str, output_path: str):
    """Créer slide simple avec définition CRR"""
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    # Blank slide
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # Title
    title_box = slide.shapes.add_textbox(
        Inches(0.5), Inches(0.5),
        Inches(9), Inches(1)
    )
    title_frame = title_box.text_frame
    title_frame.text = {
        "en": "Customer Retention Rate (CRR)",
        "fr": "Taux de Rétention Client (CRR)",
        "de": "Kundenbindungsrate (CRR)"
    }[lang]
    title_frame.paragraphs[0].font.size = Pt(32)
    title_frame.paragraphs[0].font.bold = True

    # Definition
    text_box = slide.shapes.add_textbox(
        Inches(0.5), Inches(2),
        Inches(9), Inches(4)
    )
    text_frame = text_box.text_frame
    text_frame.text = text
    text_frame.paragraphs[0].font.size = Pt(18)

    prs.save(output_path)

# Créer 3 slides
create_crr_slide(
    "en",
    "The Customer Retention Rate (CRR) measures the percentage of customers "
    "retained over a specific period. Formula: CRR = ((E-N)/S) × 100",
    "fixtures/cross_lingual/crr_definition_en.pptx"
)

create_crr_slide(
    "fr",
    "Le Taux de Rétention Client (CRR) mesure le pourcentage de clients "
    "conservés sur une période donnée. Formule: CRR = ((E-N)/S) × 100",
    "fixtures/cross_lingual/crr_definition_fr.pptx"
)

create_crr_slide(
    "de",
    "Die Kundenbindungsrate (CRR) misst den Prozentsatz der Kunden, "
    "die über einen bestimmten Zeitraum gehalten werden. Formel: CRR = ((E-N)/S) × 100",
    "fixtures/cross_lingual/crr_definition_de.pptx"
)
```

Puis convertir PPTX → PNG:
```bash
# Utiliser LibreOffice headless ou pdf2image
libreoffice --headless --convert-to png crr_definition_en.pptx
```

### Option 2: Manuel (PowerPoint)

1. Ouvrir PowerPoint
2. Créer 3 fichiers PPTX identiques sauf texte:
   - `crr_definition_en.pptx`
   - `crr_definition_fr.pptx`
   - `crr_definition_de.pptx`
3. Exporter chaque slide en PNG
4. Placer dans `fixtures/cross_lingual/`

**Contenu suggéré**:

**EN**:
```
Title: Customer Retention Rate (CRR)

Definition: The Customer Retention Rate (CRR) measures the percentage
of customers retained over a specific period.

Formula: CRR = ((E-N)/S) × 100
Where:
- E = customers at end of period
- N = new customers during period
- S = customers at start of period
```

**FR**:
```
Titre: Taux de Rétention Client (CRR)

Définition: Le Taux de Rétention Client (CRR) mesure le pourcentage
de clients conservés sur une période donnée.

Formule: CRR = ((E-N)/S) × 100
Où:
- E = clients en fin de période
- N = nouveaux clients pendant la période
- S = clients au début de période
```

**DE**:
```
Titel: Kundenbindungsrate (CRR)

Definition: Die Kundenbindungsrate (CRR) misst den Prozentsatz der Kunden,
die über einen bestimmten Zeitraum gehalten werden.

Formel: CRR = ((E-N)/S) × 100
Wobei:
- E = Kunden am Ende des Zeitraums
- N = neue Kunden während des Zeitraums
- S = Kunden zu Beginn des Zeitraums
```

---

## 📈 Interprétation des Résultats

### Scénario A: PASS toutes phases ✅

**Conditions**:
- Phase 1: ✅ Hardware compatible
- Phase 2: ✅ Gain ≥ 3x (pipeline < 30 min)
- Phase 3: ✅ Cross-lingual similarity > 0.85

**Decision**: **RECOMMANDER Scénario A - DeepSeek comme optimisation vision**

**Action**:
1. Intégrer DeepSeek-OCR dans `src/knowbase/ingestion/pipelines/pptx_vision_pipeline.py`
2. Remplacer GPT-4V par DeepSeek-OCR pour extraction vision
3. Garder pipeline OSMOSE downstream (NER, embeddings, canonicalization)
4. Mesurer performance end-to-end

**Gains attendus**:
- Performance: 1h30 → 20-30 min (3-5x)
- Coûts: Réduction appels GPT-4V vision
- USP: Préservé (cross-lingual canonicalization intact)

---

### Scénario B: PARTIAL Phase 2, PASS Phase 3 ⚠️

**Conditions**:
- Phase 1: ✅
- Phase 2: ⚠️ Gain 2-3x seulement
- Phase 3: ✅

**Decision**: **HYBRID APPROACH**

**Action**:
- DeepSeek-OCR pour slides simples (texte majoritaire)
- GPT-4V pour slides complexes (diagrams, charts)
- Classifier slide complexity en preprocessing

---

### Scénario C: FAIL Phase 3 ❌

**Conditions**:
- Phase 3: ❌ Cross-lingual similarity < 0.85

**Decision**: **ABANDONNER DeepSeek-OCR**

**Raison**: USP cross-lingual compromise = perte différenciation vs ChatGPT/Copilot

**Alternatives**:
1. Optimiser pipeline actuel (profiling, batch processing)
2. Paralléliser vision extraction (multi-GPU)
3. Chercher autres vision models (Claude 3.5 Sonnet vision?)

---

### Scénario D: FAIL Phase 1 ❌

**Conditions**:
- Phase 1: ❌ Hardware insuffisant (même en 4-bit)

**Decision**: **STOP évaluation**

**Action**:
- Upgrade hardware (ex: cloud GPU A100)
- Ou abandonner DeepSeek-OCR

---

## 🔧 Troubleshooting

### Erreur: CUDA Out of Memory

```python
# Solution 1: Mode 4-bit quantization
results = tester.run_phase1(use_4bit=True)

# Solution 2: Batch size plus petit
# (à implémenter dans test_02_benchmark)

# Solution 3: Clear cache entre runs
import torch
torch.cuda.empty_cache()
```

### Erreur: spaCy models manquants

```bash
python -m spacy download en_core_web_lg
python -m spacy download fr_core_news_lg
python -m spacy download de_core_news_lg
```

### Erreur: Flash Attention compilation

```bash
# Si installation flash-attn échoue:
# Option 1: Pre-built wheels
pip install flash-attn==2.7.3 --no-build-isolation

# Option 2: Skip flash attention (perf impact)
# Modifier load_kwargs dans scripts:
# Remove: _attn_implementation='flash_attention_2'
```

### Performance plus lente que attendu

**Causes possibles**:
1. RTX 5070 TI perf < A100 (normal)
2. CPU bottleneck (conversion PPTX → images)
3. Batch size non optimal

**Debug**:
```python
# Profiler chaque étape
import time

start = time.time()
# ... operation ...
print(f"Elapsed: {time.time() - start:.2f}s")
```

---

## 📊 Résultats Attendus

### Estimations Basées Specs

**Hardware**: RTX 5070 TI (16GB VRAM)

| Métrique | A100-40G (paper) | RTX 5070 TI (estimé) |
|----------|------------------|----------------------|
| Tokens/s | 2,500 | 1,500 (60% A100) |
| VRAM usage | ~12GB | ~12GB |
| 230 slides (Base mode) | ~24s | ~40s |

**Pipeline Total**:

| Étape | Actuel | Avec DeepSeek | Gain |
|-------|--------|---------------|------|
| Vision extraction | 5-10 min | <1 min | 5-10x |
| NER spaCy | 15-20 min | 15-20 min | 1x |
| Embeddings e5 | 10-15 min | 10-15 min | 1x |
| HDBSCAN | 5-10 min | 5-10 min | 1x |
| LLM extraction | 20-30 min | 20-30 min | 1x |
| **TOTAL** | **~90 min** | **~50 min** | **~2x** |

**Note**: Gain total < gain vision seul car autres étapes non optimisées

---

## 📝 Prochaines Étapes

Après évaluation complète:

### Si PASS → Implémentation

1. **Integration Planning**:
   - Lire `doc/phases/PHASE1_SEMANTIC_CORE.md`
   - Identifier points d'intégration dans pipeline
   - Créer branch `feat/deepseek-ocr-integration`

2. **Refactoring**:
   - Extraire vision extraction en module séparé
   - Créer interface abstraction (GPT-4V vs DeepSeek)
   - Permettre switch A/B testing

3. **Testing**:
   - Tests end-to-end sur corpus complet
   - Validation qualité extraction vs baseline
   - Performance profiling production

4. **Documentation**:
   - Mettre à jour architecture docs
   - Ajouter guide configuration DeepSeek
   - Performance benchmarks

### Si FAIL → Alternatives

1. **Profiling Pipeline Actuel**:
   - Identifier goulots exacts
   - Optimiser sans changer architecture

2. **Autres Optimisations**:
   - Batch processing
   - Parallel workers
   - Caching stratégique

3. **Autres Vision Models**:
   - Claude 3.5 Sonnet vision
   - Gemini Pro Vision
   - LLaVA (open-source)

---

## 🔗 Références

- **Plan Complet**: `doc/ongoing/OSMOSE_DEEPSEEK_OCR_EVALUATION_PLAN.md`
- **DeepSeek-OCR Paper**: `C:\Users\I502446\Downloads\DeepSeek_OCR_paper.pdf`
- **DeepSeek-OCR GitHub**: https://github.com/deepseek-ai/DeepSeek-OCR
- **DeepSeek-OCR Blog**: https://deepseek.ai/blog/deepseek-ocr-context-compression
- **OSMOSE Phase 1 Spec**: `doc/phases/PHASE1_SEMANTIC_CORE.md`
- **OSMOSE Pivot Analysis**: `doc/ongoing/OSMOSE_PIVOT_LEARNING_KG.md`

---

**Status**: 📋 Scripts prêts - En attente exécution
**Contact HELIOS**: Mode analytique activé pour suivi évaluation
