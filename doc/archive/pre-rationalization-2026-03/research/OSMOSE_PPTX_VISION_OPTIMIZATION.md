# OSMOSE - Optimisation Vision Analysis PPTX

**Date**: 2025-10-30
**Statut**: Stratégie d'optimisation validée - Implémentation à venir
**Contexte**: Réduction du temps de traitement PPTX avec vision analysis (GPT-4o)

---

## 📊 État Actuel - Baseline

### Performance Mesurée
- **Document de référence**: Slide deck de 230 slides
- **Temps total ingestion**: ~1h30
  - Convert to PDF: ~5-10 min
  - Image generation: ~10-15 min
  - **Vision analysis**: ~25-30 min ⚠️ (goulot principal)
  - OSMOSE processing: ~20-30 min
- **Coût par document**: 5-7€

### Configuration Actuelle
**Fichier**: `src/knowbase/ingestion/pipelines/pptx_pipeline.py:2108`
```python
MAX_WORKERS = 3  # Parallélisme limité
```

**Fonction Vision**: `ask_gpt_vision_summary()` (ligne 1494)
```python
raw_content = llm_router.complete(
    TaskType.VISION, msg,
    temperature=0.5,
    max_tokens=4000  # 1 slide = 1 appel = 4000 tokens max
)
```

**Modèle utilisé**: GPT-4o (config/llm_models.yaml:10)
- Input: $2.50 / 1M tokens
- Output: $10.00 / 1M tokens

### Consommation Tokens (230 slides)
- **Input tokens**: 920K-1.2M (images base64 + prompts)
- **Output tokens**: 138K-230K (2-4 paragraphes par slide)
- **Coût calculé**: ~6.61€ (cohérent avec observation 5-7€)

### Limites API GPT-4o
- **TPM** (Tokens Per Minute): 800,000
- **RPM** (Requests Per Minute): 5,000
- **TPD** (Tokens Per Day): 100,000,000

---

## 🎯 Stratégie d'Optimisation

### Option 1: Augmentation des Workers (Gain Rapide)

**Principe**: Exploiter pleinement le parallélisme autorisé par les limites API GPT-4o

#### Calculs de Dimensionnement

**Hypothèses**:
- Temps moyen par appel: 25s (range 20-30s observé)
- Tokens moyens par appel: 5,000 tokens (4000 input image + 1000 output texte)

**Calcul limite TPM**:
```
800,000 tokens/min ÷ 5,000 tokens/call = 160 calls/min
160 calls/min ÷ 60s = 2.67 calls/sec
Avec 25s par call: 2.67 × 25 = ~67 workers max théorique (TPM)
```

**Calcul limite RPM**:
```
5,000 requests/min ÷ 60s = 83.3 requests/sec
Avec 25s par call: 83.3 × 25 = ~208 workers max théorique (RPM)
```

**Limite contraignante**: TPM (67 workers max)

**Recommandation avec marge de sécurité (65%)**:
```
67 × 0.65 = ~44 workers recommandés
→ Arrondi conservateur: MAX_WORKERS = 30
```

#### Machine Cible - Capacité Validée

**Specs**: Ryzen 9 9950X3D
- 32 threads (16 cores)
- 64GB RAM
- SSD ultra rapide
- **Verdict**: Peut gérer 30-50 workers sans problème

#### Gains Attendus (Option 1)

**Vision analysis**:
- Actuel: 230 slides ÷ 3 workers = ~77 slides/worker × 25s = 32 min
- Optimisé: 230 slides ÷ 30 workers = ~8 slides/worker × 25s = **3.3 min**
- **Gain**: 25-30 min → 2.5-3.5 min ✅ (~10x plus rapide)

**Temps total ingestion**:
- Actuel: 1h30
- Optimisé: 50-55 min
- **Gain**: ~40 min économisés

**Coût**: Inchangé (5-7€) - même nombre d'appels API

---

### Option 2: Batching 3 Slides + 30 Workers (Optimisation Avancée)

**Principe**: Réduire le nombre d'appels API en groupant 3 slides par image composite

#### Architecture Batching

**Création Image Composite**:
```
+-------------------+-------------------+-------------------+
|                   |                   |                   |
|    SLIDE 1        |    SLIDE 2        |    SLIDE 3        |
|   [Image 1]       |   [Image 2]       |   [Image 3]       |
|                   |                   |                   |
+-------------------+-------------------+-------------------+
```

**Prompt adapté**:
```
Analysez cette image composite contenant 3 slides d'une présentation.

Pour chaque slide (SLIDE 1, SLIDE 2, SLIDE 3), fournissez une description
narrative détaillée (2-4 paragraphes) expliquant :
- Le message principal véhiculé
- Les concepts clés et leur organisation visuelle
- Les relations entre les éléments présentés
- Le contexte métier ou technique

FORMAT DE RÉPONSE:
=== SLIDE 1 ===
[Votre analyse narrative...]

=== SLIDE 2 ===
[Votre analyse narrative...]

=== SLIDE 3 ===
[Votre analyse narrative...]
```

#### Calculs Batching

**Réduction appels API**:
- Actuel: 230 slides = 230 appels
- Batching: 230 slides ÷ 3 = **77 appels** (76 batches de 3 + 1 batch de 2)
- **Réduction**: 67% moins d'appels

**Tokens par appel batché**:
- Input: ~12,000 tokens (3 images composite + prompt)
- Output: ~3,000 tokens (3 descriptions de 2-4 paragraphes)
- **Total**: ~15,000 tokens/appel vs 5,000 actuellement

**Consommation totale (230 slides)**:
- Input: 77 × 12,000 = 924K tokens
- Output: 77 × 3,000 = 231K tokens
- **Coût**: (924K × $2.50 + 231K × $10) / 1M = **$4.62** ✅

#### Gains Attendus (Option 2)

**Vision analysis**:
- 77 appels ÷ 30 workers = ~3 appels/worker × 25s = **1.25 min**
- **Gain vs actuel**: 25-30 min → 1.25 min (~20x plus rapide)

**Temps total ingestion**:
- Actuel: 1h30
- Optimisé: **45-50 min**
- **Gain**: ~45 min économisés

**Coût**:
- Actuel: 5-7€
- Optimisé: **4-5.5€**
- **Gain**: ~1-2€ économisés par document

**Avantages supplémentaires**:
- Moins de pression réseau (77 uploads vs 230)
- Moins de stress sur les limites RPM
- Meilleure utilisation du contexte GPT-4o

---

## 🛠️ Plan d'Implémentation

### Phase 1: Optimisation Rapide (Option 1)
**Priorité**: Haute
**Effort**: Faible (5 min)
**Gain immédiat**: 10x speedup vision analysis

#### Modifications Code

**Fichier 1**: `src/knowbase/ingestion/pipelines/pptx_pipeline.py`

```python
# Ligne 2108 - AVANT
MAX_WORKERS = 3

# Ligne 2108 - APRÈS
MAX_WORKERS = 30  # Optimisé pour GPT-4o TPM limits (800K)
```

**Validation**:
```bash
# Test sur document de 230 slides
docker-compose exec app python -m knowbase.ingestion.pipelines.pptx_pipeline \
    --file data/docs_in/test_230_slides.pptx

# Vérifier logs - temps vision analysis devrait être ~3 min
docker-compose logs -f app | grep "Vision analysis completed"
```

---

### Phase 2: Batching Intelligent (Option 2)
**Priorité**: Moyenne
**Effort**: Moyen (2-4h développement + tests)
**Gain additionnel**: 2x speedup + économies coûts

#### Étape 2.1: POC Validation Qualité

**Objectif**: Vérifier que GPT-4o analyse correctement 3 slides simultanément

**Script POC**: `scripts/poc_batch_vision.py`
```python
"""
POC: Valider la qualité d'analyse batched (3 slides/image)
"""
from PIL import Image
import numpy as np
from knowbase.common.llm_router import llm_router, TaskType

def create_composite_image(slide_images, labels=None):
    """
    Crée une image composite horizontale avec 3 slides

    Args:
        slide_images: List[PIL.Image] (1 à 3 images)
        labels: List[str] optionnel (["SLIDE 1", "SLIDE 2", "SLIDE 3"])

    Returns:
        PIL.Image composite
    """
    width = sum(img.width for img in slide_images)
    height = max(img.height for img in slide_images)

    composite = Image.new('RGB', (width, height), 'white')
    x_offset = 0

    for i, img in enumerate(slide_images):
        composite.paste(img, (x_offset, 0))

        # Ajouter label si fourni
        if labels and i < len(labels):
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(composite)
            font = ImageFont.truetype("arial.ttf", 60)
            draw.text((x_offset + 20, 20), labels[i],
                     fill='red', font=font)

        x_offset += img.width

    return composite

def analyze_batch(composite_image_path, slide_count):
    """
    Analyse un batch de slides via GPT-4o vision
    """
    prompt = f"""Analysez cette image composite contenant {slide_count} slides d'une présentation.

Pour chaque slide (SLIDE 1, SLIDE 2, SLIDE 3), fournissez une description narrative détaillée (2-4 paragraphes) expliquant :
- Le message principal véhiculé
- Les concepts clés et leur organisation visuelle
- Les relations entre les éléments présentés
- Le contexte métier ou technique

FORMAT DE RÉPONSE:
=== SLIDE 1 ===
[Votre analyse narrative...]

=== SLIDE 2 ===
[Votre analyse narrative...]

=== SLIDE 3 ===
[Votre analyse narrative...]"""

    response = llm_router.complete(
        TaskType.VISION,
        prompt,
        image_path=composite_image_path,
        temperature=0.5,
        max_tokens=12000  # 3x le max actuel
    )

    return response

def parse_batch_response(response_text):
    """
    Parse la réponse GPT-4o pour extraire les 3 analyses

    Returns:
        Dict[int, str] - {1: "analyse slide 1", 2: "...", 3: "..."}
    """
    import re

    analyses = {}
    pattern = r"===\s*SLIDE\s+(\d+)\s*===\s*(.*?)(?====\s*SLIDE\s+\d+\s*===|$)"
    matches = re.findall(pattern, response_text, re.DOTALL | re.IGNORECASE)

    for slide_num, content in matches:
        analyses[int(slide_num)] = content.strip()

    return analyses

# Test POC
if __name__ == "__main__":
    # Charger 3 slides de test
    slide1 = Image.open("data/public/slides/test_001.png")
    slide2 = Image.open("data/public/slides/test_002.png")
    slide3 = Image.open("data/public/slides/test_003.png")

    # Créer composite
    composite = create_composite_image(
        [slide1, slide2, slide3],
        labels=["SLIDE 1", "SLIDE 2", "SLIDE 3"]
    )
    composite.save("/tmp/batch_test.png")

    # Analyser
    response = analyze_batch("/tmp/batch_test.png", 3)
    print("=== RÉPONSE BRUTE GPT-4o ===")
    print(response)

    # Parser
    analyses = parse_batch_response(response)
    print("\n=== ANALYSES PARSÉES ===")
    for slide_num, content in analyses.items():
        print(f"\nSlide {slide_num}:")
        print(content[:200] + "...")

    # Validation qualité manuelle requise
    print("\n⚠️ VALIDATION MANUELLE:")
    print("1. Vérifier que les 3 slides sont correctement identifiées")
    print("2. Comparer qualité vs analyse slide par slide actuelle")
    print("3. Valider que les concepts/relations ne sont pas mélangés")
```

**Critères de validation**:
- ✅ GPT-4o identifie correctement les 3 slides distinctes
- ✅ Qualité narrative équivalente à l'analyse slide-par-slide
- ✅ Pas de confusion entre les concepts des différents slides
- ✅ Parsing fiable des 3 sections de réponse

#### Étape 2.2: Modifications Configuration

**Fichier**: `config/llm_models.yaml`

```yaml
# Ligne 39-41 - AVANT
vision:
  temperature: 0.2
  max_tokens: 4000

# Ligne 39-41 - APRÈS
vision:
  temperature: 0.2
  max_tokens: 12000  # Support batching 3 slides (3 × 4000)
```

#### Étape 2.3: Refactoring Pipeline

**Fichier**: `src/knowbase/ingestion/pipelines/pptx_pipeline.py`

**Nouvelle fonction** (insérer après `ask_gpt_vision_summary`, ligne ~1650):

```python
def ask_gpt_vision_batch_summary(
    image_paths: List[str],
    slide_indices: List[int],
    source_name: str,
    texts: List[str] = None,
    notes: List[str] = None,
    retries: int = 2
) -> Dict[int, str]:
    """
    Analyse un batch de 2-3 slides via GPT-4o vision (mode optimisé).

    Args:
        image_paths: Chemins vers les images de slides (2-3 max)
        slide_indices: Indices des slides dans le document
        source_name: Nom du document source
        texts: Textes extraits des slides (optionnel)
        notes: Notes speaker des slides (optionnel)
        retries: Nombre de tentatives en cas d'erreur

    Returns:
        Dict[int, str]: Mapping slide_index → analyse narrative
    """
    from PIL import Image
    import tempfile

    batch_size = len(image_paths)
    if batch_size < 2 or batch_size > 3:
        raise ValueError(f"Batch size must be 2-3, got {batch_size}")

    # Créer image composite
    slide_images = [Image.open(path) for path in image_paths]
    labels = [f"SLIDE {idx+1}" for idx in slide_indices]

    composite = create_composite_image(slide_images, labels)

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        composite.save(tmp.name)
        composite_path = tmp.name

    # Construire prompt avec contexte textuel optionnel
    context_parts = []
    for i, idx in enumerate(slide_indices):
        parts = [f"**SLIDE {idx+1}**"]
        if texts and i < len(texts) and texts[i]:
            parts.append(f"Texte: {texts[i][:500]}")
        if notes and i < len(notes) and notes[i]:
            parts.append(f"Notes: {notes[i][:300]}")
        context_parts.append("\n".join(parts))

    context = "\n\n".join(context_parts) if context_parts else ""

    prompt = f"""Analysez cette image composite contenant {batch_size} slides de la présentation "{source_name}".

{context}

Pour chaque slide visible (SLIDE {slide_indices[0]+1}{"".join(f", SLIDE {idx+1}" for idx in slide_indices[1:])}), fournissez une description narrative DÉTAILLÉE (2-4 paragraphes) qui explique :

1. **Message principal** : Quelle est l'idée centrale véhiculée par ce slide ?
2. **Concepts clés** : Quels sont les concepts, termes techniques ou entités importantes présentés ?
3. **Organisation visuelle** : Comment l'information est-elle structurée visuellement (diagrammes, schémas, tableaux, flux) ?
4. **Relations et dynamiques** : Quelles sont les relations, dépendances ou processus illustrés ?
5. **Contexte métier/technique** : Quel est le domaine d'application et les implications pratiques ?

⚠️ IMPORTANT:
- Analysez chaque slide SÉPARÉMENT et DISTINCTEMENT
- Ne confondez pas les concepts de différents slides
- Fournissez une analyse RICHE et NARRATIVE (pas une simple liste)

FORMAT DE RÉPONSE OBLIGATOIRE:
=== SLIDE {slide_indices[0]+1} ===
[Votre analyse narrative détaillée...]

=== SLIDE {slide_indices[1]+1} ===
[Votre analyse narrative détaillée...]
""" + (f"""
=== SLIDE {slide_indices[2]+1} ===
[Votre analyse narrative détaillée...]""" if batch_size == 3 else "")

    # Appel GPT-4o avec retry
    for attempt in range(retries + 1):
        try:
            response = llm_router.complete(
                TaskType.VISION,
                prompt,
                image_path=composite_path,
                temperature=0.5,
                max_tokens=12000
            )

            # Parser la réponse
            analyses = parse_batch_response(response)

            # Valider qu'on a bien toutes les analyses
            expected_slides = set(idx + 1 for idx in slide_indices)
            received_slides = set(analyses.keys())

            if expected_slides != received_slides:
                missing = expected_slides - received_slides
                logger.warning(
                    f"[OSMOSE] Batch analysis incomplete - "
                    f"missing slides: {missing}. Retry {attempt+1}/{retries}"
                )
                if attempt < retries:
                    continue
                else:
                    # Fallback: retourner ce qu'on a
                    pass

            # Convertir les clés pour matcher les indices originaux
            result = {}
            for slide_num, content in analyses.items():
                # slide_num est 1-based dans la réponse
                # On cherche l'index correspondant
                for i, idx in enumerate(slide_indices):
                    if slide_num == idx + 1:  # idx est 0-based
                        result[idx] = content
                        break

            logger.info(
                f"[OSMOSE] Batch vision analysis completed - "
                f"{len(result)}/{batch_size} slides"
            )

            return result

        except Exception as e:
            logger.error(
                f"[OSMOSE] Batch vision analysis error (attempt {attempt+1}): {e}"
            )
            if attempt == retries:
                raise

    # Cleanup
    try:
        os.unlink(composite_path)
    except:
        pass


def create_composite_image(
    slide_images: List[Image.Image],
    labels: List[str] = None
) -> Image.Image:
    """
    Crée une image composite horizontale avec 2-3 slides + labels.

    Args:
        slide_images: Liste de 2-3 images PIL
        labels: Labels optionnels ["SLIDE 1", "SLIDE 2", "SLIDE 3"]

    Returns:
        Image composite PIL
    """
    from PIL import ImageDraw, ImageFont

    # Calculer dimensions
    total_width = sum(img.width for img in slide_images)
    max_height = max(img.height for img in slide_images)

    # Créer canvas blanc
    composite = Image.new('RGB', (total_width, max_height), 'white')

    # Coller les slides horizontalement
    x_offset = 0
    for i, img in enumerate(slide_images):
        composite.paste(img, (x_offset, 0))

        # Ajouter label rouge en haut à gauche de chaque slide
        if labels and i < len(labels):
            draw = ImageDraw.Draw(composite)
            try:
                font = ImageFont.truetype("arial.ttf", 60)
            except:
                font = ImageFont.load_default()

            # Fond semi-transparent pour lisibilité
            label_bbox = draw.textbbox((0, 0), labels[i], font=font)
            label_width = label_bbox[2] - label_bbox[0]
            label_height = label_bbox[3] - label_bbox[1]

            draw.rectangle(
                [x_offset + 10, 10, x_offset + label_width + 30, label_height + 30],
                fill=(255, 0, 0, 180)
            )
            draw.text(
                (x_offset + 20, 20),
                labels[i],
                fill='white',
                font=font
            )

        x_offset += img.width

    return composite


def parse_batch_response(response_text: str) -> Dict[int, str]:
    """
    Parse la réponse GPT-4o pour extraire les analyses individuelles.

    Format attendu:
    === SLIDE 1 ===
    Contenu...
    === SLIDE 2 ===
    Contenu...

    Returns:
        Dict[int, str]: {1: "analyse slide 1", 2: "analyse slide 2", ...}
    """
    import re

    analyses = {}

    # Pattern flexible pour capturer les sections
    pattern = r"===\s*SLIDE\s+(\d+)\s*===\s*(.*?)(?====\s*SLIDE\s+\d+\s*===|$)"
    matches = re.findall(pattern, response_text, re.DOTALL | re.IGNORECASE)

    for slide_num_str, content in matches:
        slide_num = int(slide_num_str)
        analyses[slide_num] = content.strip()

    return analyses
```

**Modification logique principale** (ligne ~2100-2200):

```python
# AVANT (traitement séquentiel slide par slide)
with ThreadPoolExecutor(max_workers=actual_workers) as executor:
    futures = {}
    for idx, img_path in enumerate(slide_image_paths):
        future = executor.submit(
            ask_gpt_vision_summary,
            img_path, idx, source_name,
            texts[idx] if idx < len(texts) else "",
            notes[idx] if idx < len(notes) else "",
            megaparse_content,
            retries=2
        )
        futures[future] = idx

# APRÈS (batching 3 slides)
BATCH_SIZE = 3  # Nombre de slides par batch
batches = []

# Créer les batches de slides
for i in range(0, len(slide_image_paths), BATCH_SIZE):
    batch_end = min(i + BATCH_SIZE, len(slide_image_paths))
    batch = {
        'image_paths': slide_image_paths[i:batch_end],
        'slide_indices': list(range(i, batch_end)),
        'texts': texts[i:batch_end] if texts else None,
        'notes': notes[i:batch_end] if notes else None,
    }
    batches.append(batch)

logger.info(
    f"[OSMOSE] Processing {len(slide_image_paths)} slides in "
    f"{len(batches)} batches (batch_size={BATCH_SIZE})"
)

# Traiter les batches en parallèle
vision_summaries = [""] * len(slide_image_paths)  # Pré-allouer

with ThreadPoolExecutor(max_workers=actual_workers) as executor:
    futures = {}
    for batch_idx, batch in enumerate(batches):
        future = executor.submit(
            ask_gpt_vision_batch_summary,
            batch['image_paths'],
            batch['slide_indices'],
            source_name,
            batch['texts'],
            batch['notes'],
            retries=2
        )
        futures[future] = batch_idx

    # Collecter les résultats
    for future in as_completed(futures):
        batch_idx = futures[future]
        try:
            batch_results = future.result()  # Dict[int, str]

            # Insérer les résultats aux bons indices
            for slide_idx, summary in batch_results.items():
                vision_summaries[slide_idx] = summary

            logger.info(
                f"[OSMOSE] Batch {batch_idx+1}/{len(batches)} completed - "
                f"{len(batch_results)} slides analyzed"
            )
        except Exception as e:
            logger.error(f"[OSMOSE] Batch {batch_idx} failed: {e}")
            # On continue avec les autres batches

# Vérifier qu'on a toutes les analyses
missing_indices = [i for i, s in enumerate(vision_summaries) if not s]
if missing_indices:
    logger.warning(
        f"[OSMOSE] Missing vision analyses for slides: {missing_indices}"
    )
```

---

## 📈 Comparaison Options

| Métrique | Actuel | Option 1 (30 workers) | Option 2 (Batch + 30w) |
|----------|--------|-----------------------|------------------------|
| **Vision analysis** | 25-30 min | 2.5-3.5 min | 1-1.5 min |
| **Temps total** | 1h30 | 50-55 min | 45-50 min |
| **Appels API** | 230 | 230 | 77 |
| **Coût** | 5-7€ | 5-7€ | 4-5.5€ |
| **Speedup** | 1x | ~10x | ~20x |
| **Effort implémentation** | - | 5 min | 2-4h |
| **Risque qualité** | Aucun | Aucun | Faible (POC requis) |

---

## ⚠️ Risques et Mitigations

### Option 1: Augmentation Workers

**Risques**:
1. **Dépassement limites API en production multi-utilisateurs**
   - *Mitigation*: Monitoring TPM/RPM, file d'attente si limite approchée

2. **Consommation réseau importante (30 uploads simultanés)**
   - *Mitigation*: Connexion fibre requise, sinon réduire à 15-20 workers

3. **Charge CPU/RAM sur la machine**
   - *Mitigation*: Ryzen 9 9950X3D largement dimensionné, monitoring CPU/RAM

### Option 2: Batching

**Risques**:
1. **Qualité d'analyse dégradée (confusion entre slides)**
   - *Mitigation*: POC validation obligatoire avant déploiement
   - *Fallback*: Revenir à Option 1 si qualité insuffisante

2. **Parsing fragile des réponses GPT-4o**
   - *Mitigation*: Regex robuste + retry si parsing échoue
   - *Alternative*: Demander JSON structuré au lieu de texte

3. **Labels "SLIDE X" non visible si images trop petites**
   - *Mitigation*: Font size adaptatif selon résolution, contraste élevé

4. **Timeout sur gros batches (max_tokens=12000)**
   - *Mitigation*: Timeout API augmenté, retry automatique

---

## 🧪 Protocole de Test

### Tests Option 1 (Workers)

**Test 1: Performance baseline**
```bash
# Document 230 slides
time docker-compose exec app python -m knowbase.ingestion.pipelines.pptx_pipeline \
    --file data/docs_in/test_230_slides.pptx

# Vérifier logs
# - Temps vision analysis doit être ~3 min
# - Pas d'erreurs rate limit
```

**Test 2: Stress test multi-docs**
```bash
# Lancer 3 ingestions simultanées
for i in {1..3}; do
    docker-compose exec app python -m knowbase.ingestion.pipelines.pptx_pipeline \
        --file data/docs_in/test_doc_$i.pptx &
done

# Monitorer logs pour rate limit errors
docker-compose logs -f app | grep -i "rate limit"
```

### Tests Option 2 (Batching)

**Test 1: POC qualité (3 slides)**
```bash
# Exécuter script POC
docker-compose exec app python scripts/poc_batch_vision.py

# Validation manuelle:
# 1. Comparer analyse batch vs slide-by-slide (ground truth)
# 2. Vérifier parsing correct des 3 sections
# 3. Tester avec slides variés (texte, diagramme, tableau)
```

**Test 2: Regression complète**
```bash
# Traiter document complet avec batching
docker-compose exec app python -m knowbase.ingestion.pipelines.pptx_pipeline \
    --file data/docs_in/test_230_slides.pptx \
    --batch-mode

# Comparer résultats vs baseline:
# - Nombre de concepts extraits (~même)
# - Nombre de relations détectées (~même)
# - Qualité narrative (validation manuelle échantillon)
```

**Test 3: Edge cases**
```bash
# Test avec nombre de slides non multiple de 3
# → Dernier batch avec 1 ou 2 slides seulement
python scripts/poc_batch_vision.py --slides 228  # 76 batches de 3
python scripts/poc_batch_vision.py --slides 229  # 76 de 3 + 1 de 1
python scripts/poc_batch_vision.py --slides 230  # 76 de 3 + 1 de 2
```

---

## 📋 Checklist Déploiement

### Option 1 - Ready to Deploy ✅

- [ ] Modifier `MAX_WORKERS = 30` dans pptx_pipeline.py:2108
- [ ] Tester sur doc 230 slides (temps ~3 min vision)
- [ ] Vérifier logs - pas de rate limit errors
- [ ] Valider coût inchangé (5-7€)
- [ ] Commit + déploiement

### Option 2 - Requires POC First ⚠️

- [ ] Développer `scripts/poc_batch_vision.py`
- [ ] Implémenter fonctions helpers (create_composite_image, parse_batch_response)
- [ ] Exécuter POC sur 10 exemples variés
- [ ] **VALIDATION MANUELLE**: Qualité équivalente slide-by-slide ? ✅/❌
- [ ] Si ✅: Modifier llm_models.yaml (max_tokens: 12000)
- [ ] Si ✅: Refactorer pptx_pipeline.py (batching logic)
- [ ] Tests regression complets
- [ ] Si ❌: Rester sur Option 1

---

## 🎯 Recommandation Finale

### Court Terme (Semaine en cours)
**Déployer Option 1 (30 workers)** - Quick win garanti
- Gain 10x immédiat sur vision analysis
- Risque minimal (juste paramètre)
- Validé par calculs API limits

### Moyen Terme (2-3 semaines)
**Évaluer Option 2 (Batching)** - Si bandwidth disponible
- POC qualité d'abord (1 jour)
- Si concluant: implémentation (1-2 jours)
- Gain additionnel 2x + économies

### Alternative: Optimisation Hybride
Si Option 2 échoue le POC qualité, explorer:
- **Batching sélectif**: Grouper seulement slides similaires (texte dense) mais pas les diagrammes complexes
- **Batching 2 slides**: Moins risqué que 3, toujours 50% réduction appels
- **Batching adaptatif**: Décider par slide (analyse complexité visuelle d'abord)

---

## 📚 Références

**Code Source**:
- Pipeline PPTX: `src/knowbase/ingestion/pipelines/pptx_pipeline.py`
- LLM Router: `src/knowbase/common/llm_router.py`
- Config modèles: `config/llm_models.yaml`

**Documentation**:
- Limites API GPT-4o: https://platform.openai.com/docs/guides/rate-limits
- Vision API: https://platform.openai.com/docs/guides/vision
- ThreadPoolExecutor: https://docs.python.org/3/library/concurrent.futures.html

**Commits Historiques**:
- `69048d2`: Evolution max_tokens 2500→4000 (meilleure qualité narrative)
- `fa57394`: Implémentation AsyncOpenAI (parallélisation LLM calls)

---

**Auteur**: Claude Code
**Validation**: À valider avec POC avant déploiement Option 2
**Prochaine étape**: Déploiement Option 1 (MAX_WORKERS=30)
