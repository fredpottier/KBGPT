# Plan d'Évaluation DeepSeek-OCR pour OSMOSE
*Date: 2025-11-07*
*Status: PHASE ÉVALUATION - Pas d'implémentation immédiate*

## 🎯 Objectif

Évaluer si DeepSeek-OCR peut résoudre le **problème bloquant de performance** (1h30 pour 230 slides PPTX) tout en préservant l'**USP critique** d'OSMOSE (cross-lingual concept canonicalization).

## ✅ Validation Hardware

### Specs RTX 5070 TI
- **VRAM**: 16GB GDDR7
- **CUDA Cores**: 8,960
- **Bandwidth**: 896 GB/s
- **TDP**: 300W

### Exigences DeepSeek-OCR
- **Modèle**: ~6.7GB BF16 (~3B params)
- **VRAM Min**: 16GB (24GB optimal)
- **VRAM Optimisé**: 4-bit quantization possible
- **Testé sur**: A100-40G (2500 tokens/s)

**VERDICT**: ✅ **COMPATIBLE** - RTX 5070 TI répond aux exigences minimales

### Optimisations Possibles si Nécessaire
```python
# Option 1: Quantization 4-bit (réduit VRAM usage)
model = AutoModel.from_pretrained(
    "deepseek-ai/DeepSeek-OCR",
    load_in_4bit=True,
    device_map="auto"
)

# Option 2: Résolution adaptative
# Tiny: 64 tokens (512x512) - minimal VRAM
# Small: 100 tokens (640x640) - léger
# Base: 256 tokens (1024x1024) - standard ✅ RECOMMANDÉ
# Large: 400 tokens (1280x1280) - haute qualité
```

## 📊 Plan d'Évaluation en 3 Phases

### Phase 1: Faisabilité Technique (Jour 1-2)
**Objectif**: Valider que DeepSeek-OCR tourne sur RTX 5070 TI

#### Test 1.1: Installation & Setup
```bash
# Setup environnement
conda create -n deepseek-ocr python=3.10
conda activate deepseek-ocr
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu118
pip install flash-attn==2.7.3
pip install transformers>=4.51.1
pip install vllm==0.8.5

# Clone repo
git clone https://github.com/deepseek-ai/DeepSeek-OCR.git
cd DeepSeek-OCR
```

#### Test 1.2: Hello World PPTX
```python
# Script: tests/eval_deepseek/test_01_hello_world.py
from transformers import AutoModel, AutoProcessor
import torch

# Load model
processor = AutoProcessor.from_pretrained("deepseek-ai/DeepSeek-OCR")
model = AutoModel.from_pretrained(
    "deepseek-ai/DeepSeek-OCR",
    torch_dtype=torch.bfloat16,
    device_map="auto"
)

# Test simple PPTX (5-10 slides)
# Mesurer: VRAM usage, temps inference, qualité OCR
```

**Métriques Clés Phase 1**:
- ✅ VRAM peak usage < 14GB (buffer 2GB)
- ✅ Inference < 30s pour 10 slides
- ✅ OCR accuracy > 90% (validation manuelle)

**DECISION GATE 1**: Si FAIL → Passer en mode quantization 4-bit et retester

---

### Phase 2: Performance Benchmark (Jour 3-4)
**Objectif**: Mesurer gain performance réel vs pipeline actuel

#### Test 2.1: Benchmark 230 Slides (Cas Réel)
```python
# Script: tests/eval_deepseek/test_02_benchmark_230_slides.py

import time
from pathlib import Path

# Pipeline ACTUEL (baseline)
# Vision GPT-4V: ~5-10 min
# → DeepSeek-OCR: TARGET < 5 min

def benchmark_deepseek_ocr(pptx_path: Path):
    """
    Benchmark DeepSeek-OCR sur 230 slides réelles
    """
    start = time.time()

    # Mode Base (1024x1024 → ~256 tokens/slide)
    # 230 slides × 256 tokens = ~59k tokens total
    # Expected: 2500 tokens/s (A100) → 23s
    # RTX 5070 TI (estimé 60% perf A100) → ~40s

    # Extraction
    vision_tokens = extract_vision_tokens(pptx_path, mode="Base")

    elapsed = time.time() - start

    return {
        "slides": 230,
        "tokens": len(vision_tokens),
        "time_seconds": elapsed,
        "tokens_per_second": len(vision_tokens) / elapsed,
        "vram_peak_gb": torch.cuda.max_memory_allocated() / 1e9
    }
```

**Métriques Cibles Phase 2**:
- ✅ Vision extraction < 5 min (vs 10 min actuel)
- ✅ Total pipeline < 30 min (vs 1h30 actuel) - gain 3x minimum
- ✅ VRAM stable < 14GB

#### Test 2.2: Profiling Détaillé
```python
# Mesurer chaque composant:
# 1. PPTX → Images conversion: ?
# 2. DeepSeek-OCR inference: ?
# 3. Text extraction: ?
# 4. Total: ?

# Comparer avec pipeline actuel:
# - GPT-4V vision: 5-10 min
# - NER spaCy: 15-20 min
# - Embeddings e5: 10-15 min
# - HDBSCAN: 5-10 min
# - LLM extraction: 20-30 min
# TOTAL: ~1h30
```

**DECISION GATE 2**: Si gain < 2x → Évaluer si worth it. Si gain ≥ 3x → GO Phase 3

---

### Phase 3: Validation USP (Jour 5-6)
**Objectif**: CRITIQUE - Valider que cross-lingual canonicalization fonctionne

#### Test 3.1: Cross-Lingual Preservation
```python
# Script: tests/eval_deepseek/test_03_cross_lingual.py

# Corpus test:
# 1. "Customer Retention Rate" (EN) - slide PPTX
# 2. "Taux de Rétention Client" (FR) - slide PPTX
# 3. "Kundenbindungsrate" (DE) - slide PPTX

# Test:
# 1. DeepSeek-OCR → Extract text de chaque slide
# 2. NER spaCy multilingue → Extract concepts
# 3. Embeddings multilingual-e5-large → Vectors
# 4. Similarity cosine → DOIT être > 0.85 (threshold OSMOSE)

def test_cross_lingual_similarity():
    """
    CRITICAL: Valider que texte extrait par DeepSeek
    préserve similarité cross-linguale
    """
    # Extract text via DeepSeek-OCR
    text_en = deepseek_extract("slide_crr_en.pptx")
    text_fr = deepseek_extract("slide_crr_fr.pptx")
    text_de = deepseek_extract("slide_crr_de.pptx")

    # NER + Embeddings (pipeline OSMOSE existant)
    concepts_en = extract_concepts(text_en)  # spaCy en_core_web_lg
    concepts_fr = extract_concepts(text_fr)  # spaCy fr_core_news_lg
    concepts_de = extract_concepts(text_de)  # spaCy de_core_news_lg

    # Embeddings
    emb_en = embed_multilingual_e5(concepts_en)
    emb_fr = embed_multilingual_e5(concepts_fr)
    emb_de = embed_multilingual_e5(concepts_de)

    # Similarity
    sim_en_fr = cosine_similarity(emb_en, emb_fr)
    sim_en_de = cosine_similarity(emb_en, emb_de)
    sim_fr_de = cosine_similarity(emb_fr, emb_de)

    # CRITÈRE SUCCÈS
    assert sim_en_fr > 0.85, f"EN-FR similarity {sim_en_fr} < 0.85 FAIL"
    assert sim_en_de > 0.85, f"EN-DE similarity {sim_en_de} < 0.85 FAIL"
    assert sim_fr_de > 0.85, f"FR-DE similarity {sim_fr_de} < 0.85 FAIL"

    return "PASS" if all([sim_en_fr, sim_en_de, sim_fr_de]) > 0.85 else "FAIL"
```

**Métriques Critiques Phase 3**:
- ✅ Cross-lingual similarity > 0.85 (non-négociable)
- ✅ Concept extraction quality = baseline NER (validation manuelle)
- ✅ Relations extraction preserved

#### Test 3.2: Concept Extraction Complexe
```python
# Test cas difficile: Diagrams avec annotations multilingues
# Ex: Architecture diagram EN avec labels FR/DE

# Valider:
# - DeepSeek extrait TOUTES les annotations (pas juste texte principal)
# - Préserve positionnement sémantique (titre vs labels vs légendes)
# - OCR accuracy sur texte small/rotated/embedded
```

**DECISION GATE 3**:
- ✅ PASS Phase 3 → **Recommander intégration Scénario A**
- ❌ FAIL Phase 3 → **Abandonner DeepSeek-OCR** (USP non préservé)

---

## 📁 Structure Tests

```
tests/eval_deepseek/
├── test_01_hello_world.py          # Faisabilité technique
├── test_02_benchmark_230_slides.py # Performance réelle
├── test_03_cross_lingual.py        # USP validation
├── fixtures/
│   ├── sample_10_slides.pptx       # Test Phase 1
│   ├── real_230_slides.pptx        # Test Phase 2
│   └── cross_lingual/              # Test Phase 3
│       ├── crr_definition_en.pptx
│       ├── crr_definition_fr.pptx
│       └── crr_definition_de.pptx
└── results/
    ├── phase1_feasibility.json
    ├── phase2_performance.json
    └── phase3_cross_lingual.json
```

---

## 🎯 Métriques de Décision Finales

### Scénario A: Integration Recommandée
**Conditions**:
1. ✅ Phase 1 PASS (faisabilité RTX 5070 TI)
2. ✅ Phase 2 PASS (gain perf ≥ 3x → pipeline < 30 min)
3. ✅ Phase 3 PASS (cross-lingual similarity > 0.85)

**Action**: Implémenter Scénario A - DeepSeek comme optimisation vision

### Scénario B: Optimisation Partielle
**Conditions**:
1. ✅ Phase 1 PASS
2. ⚠️ Phase 2 PARTIAL (gain 2-3x seulement)
3. ✅ Phase 3 PASS

**Action**: Envisager mode hybrid (DeepSeek pour slides simples, GPT-4V pour complexes)

### Scénario C: Abandon
**Conditions**:
1. ❌ Phase 1 FAIL (hardware insuffisant)
   OU
2. ❌ Phase 3 FAIL (USP compromise)

**Action**: Rester sur pipeline actuel, chercher autres optimisations

---

## 🚀 Timeline Évaluation

| Phase | Durée | Effort | Bloquant |
|-------|-------|--------|----------|
| Phase 1: Faisabilité | 1-2 jours | 4-6h | Oui - STOP si FAIL |
| Phase 2: Performance | 1-2 jours | 6-8h | Non - données utiles même si FAIL |
| Phase 3: USP Validation | 1-2 jours | 8-10h | Oui - STOP si FAIL |
| **TOTAL** | **3-6 jours** | **18-24h** | - |

---

## 🔧 Prérequis Setup

### Hardware
- ✅ RTX 5070 TI (16GB VRAM)
- ✅ CUDA 11.8+ drivers
- ✅ 32GB RAM système recommandé

### Software
```bash
# Python 3.10
# PyTorch 2.6.0 + CUDA 11.8
# Flash Attention 2.7.3
# Transformers ≥ 4.51.1
# vLLM 0.8.5
```

### Data
- ✅ Sample 10 slides PPTX (Phase 1)
- ✅ Real 230 slides PPTX (Phase 2) - **EXISTE déjà dans vos tests**
- ⚠️ Cross-lingual fixtures (Phase 3) - **À CRÉER** (3 slides EN/FR/DE)

---

## 📝 Prochaines Actions Immédiates

### Option 1: Démarrer Phase 1 (Faisabilité)
```bash
# Setup environnement
conda create -n deepseek-ocr python=3.10
git clone https://github.com/deepseek-ai/DeepSeek-OCR.git
# Installer dépendances
# Tester hello_world.py
```

### Option 2: Créer Fixtures Cross-Lingual (Phase 3)
- Créer 3 slides PPTX: CRR definition EN/FR/DE
- Préparer corpus test complet
- Permet de valider USP même sans Phase 1/2

### Option 3: Profiler Pipeline Actuel d'Abord
- Identifier goulots exacts dans 1h30 actuel
- Déterminer si DeepSeek-OCR cible bon bottleneck
- Baseline précise pour comparaison Phase 2

---

## 🧠 Notes Stratégiques

### Pourquoi Évaluation ≠ Implémentation
- **Évaluation** (cette phase): Tests isolés, POC, benchmarks, validation
- **Implémentation** (si GO): Intégration dans pipeline OSMOSE, refactoring, tests end-to-end

### Risques Identifiés
1. **RTX 5070 TI perf < A100**: Possible temps > 5 min (mais toujours < 10 min baseline)
2. **Visual tokens ≠ Text embeddings**: Cross-lingual similarity peut chuter
3. **OCR errors**: Texte extrait bruité → impact NER downstream

### Mitigation
- Quantization 4-bit si VRAM tight
- Fallback GPT-4V si OCR quality insufficient
- Post-processing OCR (correction orthographe) si nécessaire

---

**Statut**: 📋 PLAN PRÊT - En attente choix action utilisateur
**Prochaine étape recommandée**: **Option 2** (Créer fixtures cross-lingual) - validation USP critique sans setup complet
