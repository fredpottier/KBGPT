# Guide Benchmark Qwen2-VL-72B vs GPT-4o Vision

**Date** : 2025-01-20
**Objectif** : Tester Qwen2-VL-72B sur slides SAP réels pour évaluer gap qualité vs GPT-4o Vision
**Durée estimée** : 1 semaine
**Budget test** : $140 (7 jours × $20/jour GPU spot)

---

## 🎯 Objectifs du Benchmark

### Questions à Répondre

1. **Qualité OCR** : Qwen2-VL extrait-il le texte aussi bien que GPT-4o sur slides denses ?
2. **Compréhension diagrammes** : Identifie-t-il correctement les composants d'architecture SAP ?
3. **Extraction entités** : Trouve-t-il tous les concepts (produits, features, relations) ?
4. **Performance** : Quelle est la latence réelle par slide ?
5. **ROI** : À partir de quel volume mensuel le self-hosting devient rentable ?

### Critères de Succès

| Métrique | Minimum Acceptable | Objectif |
|----------|-------------------|----------|
| **Précision OCR** | > 85% | > 90% |
| **Entités extraites** | > 85% vs GPT-4o | > 90% |
| **Relations correctes** | > 80% | > 85% |
| **Latence par slide** | < 5s | < 3s |
| **Gap qualité global** | < 15% | < 10% |

**Décision GO** : Si gap < 10% ET volume > 400 docs/mois → Migration rentable

---

## 🛠️ Phase 1 : Setup Infrastructure GPU (1 jour)

### Option A : Vast.ai (Recommandé - Le Moins Cher)

**Avantages** :
- Prix spot : $0.60-1.20/h (vs $3.00/h fixed)
- Facturation à la seconde
- Large choix GPU

**Inscription** :
1. Aller sur https://vast.ai
2. Créer compte + ajouter $50 crédit
3. Rechercher GPU : **A100-80GB** avec filtre :
   - VRAM >= 80GB
   - Disk >= 200GB
   - Bandwidth >= 100 Mbps

**Commande recherche GPU** :
```bash
# Filtres Vast.ai
GPU: A100-80GB
RAM: >= 64GB
Disk: >= 200GB
Price: Spot < $1.50/h
Region: EU ou US (latence)
```

**Louer instance** :
- Template : PyTorch 2.1 + CUDA 12.1
- Ports : 8000, 22 (SSH)
- Durée : 7 jours (avec auto-renewal)

**Coût estimé** : $0.80/h × 24h × 7j = **$134/semaine**

---

### Option B : RunPod (Alternative)

**Avantages** :
- Interface plus simple
- Garantie uptime meilleure

**Prix** : $1.20-1.80/h (A100-80GB spot)

**Setup** :
1. https://runpod.io
2. Deploy → GPU Cloud
3. Template : RunPod PyTorch 2.1
4. GPU : A100-80GB (spot)

**Coût estimé** : $1.20/h × 168h = **$202/semaine**

---

## 📦 Phase 2 : Installation Qwen2-VL-72B (2-3 heures)

### SSH vers GPU

```bash
# Vast.ai te donne SSH command
ssh -p XXXXX root@ssh.vast.ai -L 8000:localhost:8000

# Vérifier GPU
nvidia-smi
```

**Output attendu** :
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.xx       Driver Version: 535.xx       CUDA Version: 12.1   |
|-------------------------------+----------------------+----------------------+
| GPU  Name                 TCC | Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
|===============================+======================+======================|
|   0  NVIDIA A100-SXM... On   | 00000000:00:04.0 Off |                    0 |
| N/A   32C    P0    52W / 400W |      0MiB / 81920MiB |      0%      Default |
+-------------------------------+----------------------+----------------------+
```

---

### Installation vLLM + Qwen2-VL

```bash
# Update system
apt update && apt install -y git wget htop

# Install Python deps
pip install --upgrade pip
pip install vllm==0.6.3
pip install qwen-vl-utils  # Utils pour Qwen2-VL
pip install pillow requests

# Télécharger modèle (prend 15-30 min, ~150GB)
huggingface-cli download Qwen/Qwen2-VL-72B-Instruct \
  --local-dir /workspace/qwen2-vl-72b \
  --local-dir-use-symlinks False
```

**Vérification téléchargement** :
```bash
ls -lh /workspace/qwen2-vl-72b/
# Doit montrer ~145GB de fichiers .safetensors
```

---

### Lancer serveur vLLM

```bash
# Lancer vLLM avec quantization 4-bit (pour tenir en 80GB)
python -m vllm.entrypoints.openai.api_server \
  --model /workspace/qwen2-vl-72b \
  --dtype auto \
  --api-key sk-test-key-qwen2vl \
  --host 0.0.0.0 \
  --port 8000 \
  --quantization awq \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.95 \
  --enable-chunked-prefill

# En arrière-plan (recommandé)
nohup python -m vllm.entrypoints.openai.api_server \
  --model /workspace/qwen2-vl-72b \
  --dtype auto \
  --api-key sk-test-key-qwen2vl \
  --host 0.0.0.0 \
  --port 8000 \
  --quantization awq \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.95 \
  --enable-chunked-prefill \
  > vllm.log 2>&1 &

# Suivre logs
tail -f vllm.log
```

**Temps de chargement** : 3-5 minutes

**Vérifier serveur actif** :
```bash
curl http://localhost:8000/v1/models
```

**Output attendu** :
```json
{
  "object": "list",
  "data": [
    {
      "id": "Qwen/Qwen2-VL-72B-Instruct",
      "object": "model",
      "created": 1737000000,
      "owned_by": "vllm"
    }
  ]
}
```

---

## 🧪 Phase 3 : Script de Test Vision (2 heures)

### Script Python pour Benchmark

Créer `benchmark_vision.py` sur ton **laptop local** :

```python
"""
Benchmark Qwen2-VL-72B vs GPT-4o Vision sur slides SAP.

Usage:
    python benchmark_vision.py --slides-dir /path/to/slides
"""

import os
import base64
import time
import json
from pathlib import Path
from typing import List, Dict, Any
import requests
from openai import OpenAI
from dataclasses import dataclass, asdict

# ===================================
# Configuration
# ===================================

# GPT-4o Vision API (OpenAI)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Qwen2-VL-72B (vLLM sur Vast.ai)
# IMPORTANT: Remplacer par ton IP Vast.ai
QWEN_BASE_URL = "http://YOUR_VAST_IP:8000/v1"
QWEN_API_KEY = "sk-test-key-qwen2vl"

qwen_client = OpenAI(
    base_url=QWEN_BASE_URL,
    api_key=QWEN_API_KEY,
)

# ===================================
# Modèles de Données
# ===================================

@dataclass
class ExtractionResult:
    """Résultat extraction d'un slide."""
    slide_path: str
    model: str  # "gpt-4o" ou "qwen2-vl-72b"

    # Texte extrait
    ocr_text: str

    # Entités SAP
    entities: List[str]  # ["SAP S/4HANA Cloud", "SAP BTP", ...]

    # Relations
    relations: List[Dict[str, str]]  # [{"from": "A", "to": "B", "type": "USES"}, ...]

    # Métriques
    latency_seconds: float
    cost_usd: float  # 0 pour Qwen, calculé pour GPT-4o

    # Qualité (rempli après comparaison)
    ocr_accuracy: float = None  # vs ground truth si disponible
    entities_found: int = None
    relations_found: int = None


# ===================================
# Fonctions Vision
# ===================================

def encode_image_base64(image_path: str) -> str:
    """Encode image en base64."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_with_gpt4o(image_path: str) -> ExtractionResult:
    """Extrait entités/relations avec GPT-4o Vision."""

    print(f"  [GPT-4o] Extracting from {Path(image_path).name}...")

    start = time.time()

    # Encode image
    image_b64 = encode_image_base64(image_path)

    # Prompt extraction
    prompt = """Tu es un expert en analyse de documents SAP.

Analyse cette slide et extrait:

1. **Texte OCR complet** (verbatim, tout le texte visible)

2. **Entités SAP** (produits, services, technologies mentionnés)
   Format: Liste JSON ["SAP S/4HANA Cloud", "SAP BTP", ...]

3. **Relations** entre entités
   Format: Liste JSON [{"from": "SAP S/4HANA", "to": "SAP HANA", "type": "USES"}, ...]

Retourne UNIQUEMENT un JSON valide:
{
  "ocr_text": "...",
  "entities": [...],
  "relations": [...]
}
"""

    # Call API
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        max_tokens=2000,
        temperature=0.0,
    )

    latency = time.time() - start

    # Parse response
    content = response.choices[0].message.content

    # Extraire JSON (parfois LLM ajoute markdown)
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()

    data = json.loads(content)

    # Calculer coût approximatif
    # GPT-4o: $5/1M input tokens, $15/1M output tokens
    # Image high detail ~= 765 tokens, prompt ~= 200 tokens
    input_tokens = 765 + 200
    output_tokens = len(content.split()) * 1.3  # Approximation
    cost = (input_tokens * 5.0 + output_tokens * 15.0) / 1_000_000

    return ExtractionResult(
        slide_path=image_path,
        model="gpt-4o",
        ocr_text=data.get("ocr_text", ""),
        entities=data.get("entities", []),
        relations=data.get("relations", []),
        latency_seconds=latency,
        cost_usd=cost,
    )


def extract_with_qwen2vl(image_path: str) -> ExtractionResult:
    """Extrait entités/relations avec Qwen2-VL-72B."""

    print(f"  [Qwen2-VL] Extracting from {Path(image_path).name}...")

    start = time.time()

    # Encode image
    image_b64 = encode_image_base64(image_path)

    # Même prompt que GPT-4o
    prompt = """Tu es un expert en analyse de documents SAP.

Analyse cette slide et extrait:

1. **Texte OCR complet** (verbatim, tout le texte visible)

2. **Entités SAP** (produits, services, technologies mentionnés)
   Format: Liste JSON ["SAP S/4HANA Cloud", "SAP BTP", ...]

3. **Relations** entre entités
   Format: Liste JSON [{"from": "SAP S/4HANA", "to": "SAP HANA", "type": "USES"}, ...]

Retourne UNIQUEMENT un JSON valide:
{
  "ocr_text": "...",
  "entities": [...],
  "relations": [...]
}
"""

    # Call vLLM API (compatible OpenAI)
    try:
        response = qwen_client.chat.completions.create(
            model="Qwen/Qwen2-VL-72B-Instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,
            temperature=0.0,
        )

        latency = time.time() - start

        # Parse response
        content = response.choices[0].message.content

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()

        data = json.loads(content)

        return ExtractionResult(
            slide_path=image_path,
            model="qwen2-vl-72b",
            ocr_text=data.get("ocr_text", ""),
            entities=data.get("entities", []),
            relations=data.get("relations", []),
            latency_seconds=latency,
            cost_usd=0.0,  # Self-hosted, coût inclus dans infra
        )

    except Exception as e:
        print(f"    ❌ Error with Qwen2-VL: {e}")
        return ExtractionResult(
            slide_path=image_path,
            model="qwen2-vl-72b",
            ocr_text="ERROR",
            entities=[],
            relations=[],
            latency_seconds=time.time() - start,
            cost_usd=0.0,
        )


# ===================================
# Comparaison Résultats
# ===================================

def compare_results(gpt_result: ExtractionResult, qwen_result: ExtractionResult) -> Dict[str, Any]:
    """Compare résultats GPT-4o vs Qwen2-VL."""

    # Entités trouvées
    gpt_entities_set = set(e.lower() for e in gpt_result.entities)
    qwen_entities_set = set(e.lower() for e in qwen_result.entities)

    common_entities = gpt_entities_set & qwen_entities_set
    only_gpt = gpt_entities_set - qwen_entities_set
    only_qwen = qwen_entities_set - gpt_entities_set

    entities_recall = len(common_entities) / len(gpt_entities_set) if gpt_entities_set else 0

    # Relations trouvées
    gpt_relations = len(gpt_result.relations)
    qwen_relations = len(qwen_result.relations)

    # OCR similarity (simple Jaccard sur mots)
    gpt_words = set(gpt_result.ocr_text.lower().split())
    qwen_words = set(qwen_result.ocr_text.lower().split())

    ocr_similarity = len(gpt_words & qwen_words) / len(gpt_words | qwen_words) if (gpt_words | qwen_words) else 0

    return {
        "entities_recall": entities_recall,  # % entités GPT-4o retrouvées par Qwen
        "entities_gpt": len(gpt_entities_set),
        "entities_qwen": len(qwen_entities_set),
        "entities_common": len(common_entities),
        "entities_only_gpt": list(only_gpt),
        "entities_only_qwen": list(only_qwen),

        "relations_gpt": gpt_relations,
        "relations_qwen": qwen_relations,
        "relations_recall": qwen_relations / gpt_relations if gpt_relations > 0 else 0,

        "ocr_similarity": ocr_similarity,

        "latency_gpt": gpt_result.latency_seconds,
        "latency_qwen": qwen_result.latency_seconds,
        "latency_ratio": qwen_result.latency_seconds / gpt_result.latency_seconds if gpt_result.latency_seconds > 0 else 0,

        "cost_gpt": gpt_result.cost_usd,
        "cost_qwen": qwen_result.cost_usd,
    }


# ===================================
# Benchmark Principal
# ===================================

def run_benchmark(slides_dir: str, output_file: str = "benchmark_results.json"):
    """Run full benchmark sur tous les slides."""

    slides_path = Path(slides_dir)

    # Trouver tous les PNG/JPG
    image_files = list(slides_path.glob("*.png")) + list(slides_path.glob("*.jpg"))

    if not image_files:
        print(f"❌ No images found in {slides_dir}")
        return

    print(f"\n🔬 Starting benchmark on {len(image_files)} slides...")
    print(f"   GPT-4o Vision vs Qwen2-VL-72B\n")

    results = []

    for i, image_path in enumerate(image_files[:20], 1):  # Limiter à 20 pour test
        print(f"\n📊 Slide {i}/{min(20, len(image_files))}: {image_path.name}")

        # Extract with both models
        gpt_result = extract_with_gpt4o(str(image_path))
        qwen_result = extract_with_qwen2vl(str(image_path))

        # Compare
        comparison = compare_results(gpt_result, qwen_result)

        # Store
        results.append({
            "slide": image_path.name,
            "gpt4o": asdict(gpt_result),
            "qwen2vl": asdict(qwen_result),
            "comparison": comparison,
        })

        # Print summary
        print(f"  ✅ Entities recall: {comparison['entities_recall']:.1%} ({comparison['entities_qwen']}/{comparison['entities_gpt']})")
        print(f"  ✅ OCR similarity: {comparison['ocr_similarity']:.1%}")
        print(f"  ⏱️  Latency: GPT={gpt_result.latency_seconds:.1f}s, Qwen={qwen_result.latency_seconds:.1f}s")
        print(f"  💰 Cost: GPT=${gpt_result.cost_usd:.4f}, Qwen=$0")

    # Save results
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Benchmark complete! Results saved to {output_file}")

    # Aggregate stats
    print_aggregate_stats(results)


def print_aggregate_stats(results: List[Dict]):
    """Print aggregate statistics."""

    if not results:
        return

    # Moyennes
    avg_entities_recall = sum(r["comparison"]["entities_recall"] for r in results) / len(results)
    avg_ocr_similarity = sum(r["comparison"]["ocr_similarity"] for r in results) / len(results)
    avg_latency_gpt = sum(r["comparison"]["latency_gpt"] for r in results) / len(results)
    avg_latency_qwen = sum(r["comparison"]["latency_qwen"] for r in results) / len(results)
    total_cost_gpt = sum(r["comparison"]["cost_gpt"] for r in results)

    print("\n" + "="*60)
    print("📊 AGGREGATE STATISTICS")
    print("="*60)
    print(f"\n🎯 Quality Metrics:")
    print(f"   - Entities Recall (Qwen vs GPT):  {avg_entities_recall:.1%}")
    print(f"   - OCR Similarity:                 {avg_ocr_similarity:.1%}")
    print(f"   - Quality Gap:                    {(1 - avg_entities_recall):.1%}")

    print(f"\n⏱️  Performance:")
    print(f"   - Avg Latency GPT-4o:             {avg_latency_gpt:.2f}s")
    print(f"   - Avg Latency Qwen2-VL:           {avg_latency_qwen:.2f}s")
    print(f"   - Speedup/Slowdown:               {avg_latency_qwen/avg_latency_gpt:.2f}x")

    print(f"\n💰 Cost (for {len(results)} slides):")
    print(f"   - Total GPT-4o:                   ${total_cost_gpt:.2f}")
    print(f"   - Total Qwen2-VL:                 $0.00 (infra cost separate)")
    print(f"   - Savings per slide:              ${total_cost_gpt/len(results):.4f}")

    print(f"\n🎯 Decision Guidance:")

    if avg_entities_recall >= 0.90:
        print("   ✅ Quality EXCELLENT (>90%) - Safe for production")
    elif avg_entities_recall >= 0.85:
        print("   ⚠️  Quality GOOD (85-90%) - Acceptable for production")
    elif avg_entities_recall >= 0.75:
        print("   ⚠️  Quality MODERATE (75-85%) - Use with caution")
    else:
        print("   ❌ Quality POOR (<75%) - Not recommended for production")

    print("\n" + "="*60 + "\n")


# ===================================
# Main
# ===================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Benchmark Qwen2-VL-72B vs GPT-4o Vision")
    parser.add_argument("--slides-dir", required=True, help="Directory containing slide images (PNG/JPG)")
    parser.add_argument("--output", default="benchmark_results.json", help="Output JSON file")

    args = parser.parse_args()

    # Vérifier config
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY not set!")
        exit(1)

    if "YOUR_VAST_IP" in QWEN_BASE_URL:
        print("❌ Please update QWEN_BASE_URL with your Vast.ai IP!")
        exit(1)

    # Run benchmark
    run_benchmark(args.slides_dir, args.output)
```

---

## 🧪 Phase 4 : Exécution du Benchmark (1 journée)

### Préparer Slides de Test

```bash
# Sur ton laptop
mkdir -p ~/sap_slides_benchmark

# Copier 20 slides variés:
# - 5 simples (texte seulement)
# - 10 moyennes (diagrammes)
# - 5 complexes (architecture dense)

# Convertir PPTX en images si besoin
python -c "
from pptx import Presentation
from PIL import Image
import io

prs = Presentation('ton_document.pptx')
for i, slide in enumerate(prs.slides[:20]):
    # Export slide as image (nécessite libreoffice)
    # Ou utilise ton pipeline existant PPTX → images
    pass
"
```

---

### Lancer Benchmark

```bash
# Mettre à jour QWEN_BASE_URL dans benchmark_vision.py
# Remplacer YOUR_VAST_IP par l'IP publique de ton instance Vast.ai

# Export API key
export OPENAI_API_KEY="sk-..."

# Run benchmark
python benchmark_vision.py --slides-dir ~/sap_slides_benchmark

# Output en temps réel:
# 📊 Slide 1/20: slide_01.png
#   [GPT-4o] Extracting...
#   [Qwen2-VL] Extracting...
#   ✅ Entities recall: 92.3% (12/13)
#   ✅ OCR similarity: 88.5%
#   ⏱️  Latency: GPT=1.2s, Qwen=3.1s
#   💰 Cost: GPT=$0.0089, Qwen=$0
# ...
```

---

## 📊 Phase 5 : Analyse Résultats (1 jour)

### Ouvrir Résultats JSON

```bash
# Résultats sauvegardés dans benchmark_results.json
cat benchmark_results.json | python -m json.tool | less
```

**Exemple output** :
```json
{
  "slide": "slide_architecture_s4hana.png",
  "gpt4o": {
    "entities": [
      "SAP S/4HANA Cloud",
      "SAP HANA Database",
      "SAP Fiori",
      "SAP Business Technology Platform",
      ...
    ],
    "relations": [
      {"from": "SAP S/4HANA Cloud", "to": "SAP HANA", "type": "USES"},
      ...
    ],
    "latency_seconds": 1.23,
    "cost_usd": 0.0087
  },
  "qwen2vl": {
    "entities": [
      "SAP S/4HANA Cloud",
      "SAP HANA",
      "Fiori",
      ...
    ],
    "relations": [...],
    "latency_seconds": 2.95,
    "cost_usd": 0.0
  },
  "comparison": {
    "entities_recall": 0.923,  # 92.3% des entités GPT retrouvées
    "ocr_similarity": 0.885,
    "entities_only_gpt": ["SAP Business Technology Platform"],
    "entities_only_qwen": [],
    ...
  }
}
```

---

### Créer Rapport d'Analyse

```bash
# Script analyse automatique
python analyze_benchmark.py benchmark_results.json
```

Créer `analyze_benchmark.py` :

```python
"""Analyse résultats benchmark et génère rapport."""

import json
import sys
from pathlib import Path

def analyze_benchmark(results_file: str):
    with open(results_file) as f:
        results = json.load(f)

    # Calculs
    total_slides = len(results)

    recalls = [r["comparison"]["entities_recall"] for r in results]
    ocr_sims = [r["comparison"]["ocr_similarity"] for r in results]

    avg_recall = sum(recalls) / len(recalls)
    min_recall = min(recalls)
    max_recall = max(recalls)

    avg_ocr = sum(ocr_sims) / len(ocr_sims)

    # Slides problématiques
    poor_slides = [r for r in results if r["comparison"]["entities_recall"] < 0.80]

    # Génération rapport
    report = f"""
# Rapport Benchmark Qwen2-VL-72B vs GPT-4o Vision

**Date** : {Path(results_file).stat().st_mtime}
**Slides testés** : {total_slides}

## 📊 Métriques Globales

| Métrique | Valeur |
|----------|--------|
| **Recall Entités (moyenne)** | {avg_recall:.1%} |
| **Recall Entités (min)** | {min_recall:.1%} |
| **Recall Entités (max)** | {max_recall:.1%} |
| **Similarité OCR (moyenne)** | {avg_ocr:.1%} |
| **Gap Qualité** | {(1-avg_recall):.1%} |

## ⚠️ Slides Problématiques (recall < 80%)

{len(poor_slides)} slides avec qualité insuffisante:

"""

    for slide in poor_slides:
        report += f"\n- **{slide['slide']}** : Recall {slide['comparison']['entities_recall']:.1%}\n"
        report += f"  - Entités manquées : {slide['comparison']['entities_only_gpt']}\n"

    report += f"""

## 🎯 Recommandation

"""

    if avg_recall >= 0.90:
        report += "✅ **GO PRODUCTION** : Qualité excellente (>90%)\n"
        report += f"- Économie estimée: ${sum(r['comparison']['cost_gpt'] for r in results) * 50:.2f}/mois (si 1000 slides/mois)\n"
    elif avg_recall >= 0.85:
        report += "⚠️ **GO avec CAUTION** : Qualité acceptable (85-90%)\n"
        report += "- Surveiller slides complexes\n"
    else:
        report += "❌ **NO-GO** : Qualité insuffisante (<85%)\n"
        report += "- Rester sur GPT-4o Vision API\n"

    # Sauvegarder
    report_file = results_file.replace(".json", "_report.md")
    with open(report_file, "w") as f:
        f.write(report)

    print(report)
    print(f"\n✅ Rapport sauvegardé: {report_file}")

if __name__ == "__main__":
    analyze_benchmark(sys.argv[1])
```

---

## 🎯 Phase 6 : Décision GO/NO-GO

### Critères de Décision

**GO vers Self-Hosted Qwen2-VL** SI :
- ✅ Recall entities >= 85%
- ✅ Volume >= 400 docs/mois
- ✅ Budget infra $1,080/mois OK
- ✅ Équipe peut gérer infra GPU

**NO-GO (rester API)** SI :
- ❌ Recall < 85%
- ❌ Volume < 400 docs/mois
- ❌ Slides très complexes critiques
- ❌ Pas de ressources DevOps GPU

---

## 💰 Calcul ROI Précis

```python
# Basé sur résultats benchmark

avg_cost_per_slide_gpt4o = 0.01  # $0.01 mesuré
slides_per_doc = 250
cost_per_doc_gpt4o = avg_cost_per_slide_gpt4o * slides_per_doc  # $2.50

# Coût mensuel API selon volume
volume_monthly = 500  # Ajuster selon ton usage réel
cost_monthly_api = volume_monthly * cost_per_doc_gpt4o

# Coût mensuel self-hosted
cost_monthly_gpu = 1080  # A100-80GB
cost_monthly_storage = 50
cost_monthly_bandwidth = 20
cost_monthly_self = cost_monthly_gpu + cost_monthly_storage + cost_monthly_bandwidth

# Breakeven
breakeven_volume = cost_monthly_self / cost_per_doc_gpt4o

print(f"Coût API ({volume_monthly} docs): ${cost_monthly_api:.2f}/mois")
print(f"Coût Self-Hosted: ${cost_monthly_self:.2f}/mois")
print(f"Économie: ${cost_monthly_api - cost_monthly_self:.2f}/mois")
print(f"Breakeven volume: {breakeven_volume:.0f} docs/mois")
```

---

## 📋 Checklist Finale

### Avant de Décider

- [ ] Benchmark exécuté sur 20+ slides variés
- [ ] Recall entities mesuré précisément
- [ ] Slides problématiques identifiés
- [ ] Volume mensuel réel estimé
- [ ] ROI calculé avec vrais chiffres
- [ ] Équipe DevOps prête pour GPU (si GO)

### Si GO Production

- [ ] Louer A100-80GB long-term (RunPod committed)
- [ ] Setup monitoring (Prometheus + Grafana)
- [ ] Backup model weights
- [ ] Load balancing si besoin
- [ ] Migration progressive (10% trafic → 100%)

---

## 🚀 Prochaines Étapes

1. **Semaine 1** : Setup GPU + Benchmark (ce guide)
2. **Semaine 2** : Analyse résultats + Décision
3. **Si GO** :
   - Semaine 3 : Setup prod infra
   - Semaine 4 : Migration 10% trafic
   - Semaine 5 : Scaling 100%

---

**Bon benchmark ! N'hésite pas si tu as des questions pendant le setup.** 🎯
