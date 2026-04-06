# Analyse des Problèmes Qwen2.5-14B-AWQ (vLLM Burst Mode)

**Date:** 2026-01-27
**Contexte:** Pipeline OSMOSE Pass 1/2/3 - Extraction de connaissances
**Modèle:** `Qwen/Qwen2.5-14B-Instruct-AWQ` (quantized, 8192 context)
**Infrastructure:** EC2 Spot g5.xlarge (1x A10G 24GB) via vLLM

---

## 1. Configuration Actuelle

### 1.1 Tâches utilisant Qwen (via vLLM Burst)

| Tâche | Fichier | Token Limit | Usage |
|-------|---------|-------------|-------|
| `knowledge_extraction` | Pass 1.1/1.2/1.3 | 4000 | Extraction assertions, concepts, liens |
| `coref_llm_arbiter` | `linguistic/coref_llm_arbiter.py` | 1000 | Résolution de coréférences |
| `llm_merge_gate` | `entity_resolution/llm_merge_gate.py` | 500 | Validation fusions entités |
| `corpus_er_pipeline` | `consolidation/corpus_er_pipeline.py` | 1000 | Entity Resolution corpus |

### 1.2 Configuration `llm_models.yaml`

```yaml
knowledge_extraction:
  temperature: 0.2
  max_tokens: 4000  # Réduit pour compatibilité Qwen2.5-14B (8192 context)
```

**Contexte effectif Qwen2.5-14B-AWQ:** 8192 tokens total (input + output)
**Limite output configurée:** 4000 tokens (pour laisser ~4000 à l'input)

---

## 2. Problèmes Identifiés

### 🔴 Problème 1: Troncature JSON (CRITIQUE)

**Symptôme observé (2026-01-26 23:24):**
```
ERROR: [OSMOSE:Pass1:1.2] TRONCATURE DÉTECTÉE - JSON incomplet
Fin: ...{"term": "SAP Cloud ERP Private", "reason": "Générique"}, {"term
ERROR: LLM Contract Violation: JSON tronqué détecté. Le modèle a probablement atteint sa limite de tokens.
```

**Cause:**
- Le prompt Phase 1.2 (concept_identification) demande une liste de concepts + termes refusés
- Qwen génère des output verbeux et atteint la limite de 4000 tokens
- Le JSON est tronqué en plein milieu d'un objet

**Impact:**
- Pipeline crash complet
- Aucune phase ultérieure exécutée (ancrage, enrichissement, etc.)
- 0% anchor rate final

**Données:**
- Input: 1529 tokens
- Output demandé: 4000 tokens (limite atteinte)
- Total: 5529 tokens (dépasse le budget de 4000 output)

### 🔴 Problème 2: Reformulation malgré instruction "verbatim"

**Prompt (pass1_prompts.yaml ligne 155):**
```yaml
"text": "Le texte EXACT de l'assertion (copié du texte)"
```

**Comportement observé:**
Qwen reformule le texte au lieu de le copier verbatim, ce qui:
1. Modifie le sens original (perte de nuance)
2. Empêche l'ancrage (le texte reformulé ne matche plus le DocItem)
3. Crée des doublons sémantiques (même assertion reformulée différemment)

**Exemple typique:**
- **Source:** "Customer manages configuration, implementation, integration, monitoring, application support etc"
- **Qwen output:** "The customer is responsible for managing configuration, implementation, integration, monitoring, and application support"

**Cause probable:**
- Qwen est entraîné pour être "helpful" et reformule naturellement
- L'instruction "texte EXACT" n'est pas assez forte
- Pas de contrainte structurelle (JSON schema avec regex)

### 🟠 Problème 3: Verbosité excessive

**Observation:**
- Qwen génère ~2x plus d'assertions que GPT-4o-mini pour le même document
- Beaucoup sont des assertions de faible qualité (fragments, répétitions)

**Données test (même document):**
| Modèle | Assertions | PROMOTED | Rate |
|--------|-----------|----------|------|
| GPT-4o-mini | ~600 | ~100 | ~16% |
| Qwen-14B | ~1126 | ~135 | ~12% |

**Impact:**
- Plus de tokens consommés pour un résultat équivalent ou pire
- Plus de bruit à filtrer en aval
- Risque accru de troncature JSON

### 🟠 Problème 4: Mauvais suivie des formats JSON

**Observations:**
- Tendance à ajouter du texte explicatif avant/après le JSON
- Parfois utilise `'''json` au lieu de ` ```json `
- Inclut parfois des commentaires dans le JSON (invalide)

**Exemple:**
```
Voici les concepts extraits du document:
```json
{
  "concepts": [...]
}
```
```

**Impact:**
- Parser JSON échoue
- Nécessite un post-processing regex pour extraire le JSON

### 🟡 Problème 5: Coût/Bénéfice EC2 Spot

**Coût actuel:**
- g5.xlarge: ~$0.60/heure (Spot)
- Ingestion 1 document: ~30 min → ~$0.30

**Comparaison GPT-4o-mini:**
- ~$0.15 / 1M input tokens, ~$0.60 / 1M output tokens
- Ingestion 1 document: ~$0.02-0.05

**Conclusion:** vLLM/Qwen n'est rentable que pour des batches massifs (>100 documents).

---

## 3. Tâches où Qwen fonctionne bien

| Tâche | Performance | Commentaire |
|-------|-------------|-------------|
| `coref_llm_arbiter` | ✅ Bon | Réponses courtes (oui/non), pas de JSON complexe |
| `llm_merge_gate` | ✅ Acceptable | Validation binaire, output limité |
| Classification simple | ✅ Bon | Température 0, réponses courtes |

---

## 4. Alternatives à Explorer

### Option A: Augmenter les limites Qwen

- Passer à Qwen2.5-32B (meilleur suivi instructions)
- Nécessite GPU plus gros (g5.2xlarge ou A100)
- Coût x2

### Option B: Prompts plus stricts

- Ajouter des contraintes JSON Schema
- Réduire verbosité des prompts
- Forcer format compact sans définitions

### Option C: Modèle hybride

- Qwen pour tâches simples (coref, merge_gate)
- GPT-4o-mini pour extraction JSON complexe (Pass 1.2)

### Option D: Autres modèles vLLM

| Modèle | Context | Qualité JSON | Verbosité |
|--------|---------|--------------|-----------|
| Mistral-7B-Instruct | 32K | Moyenne | Faible |
| Llama-3.1-8B-Instruct | 128K | Bonne | Moyenne |
| DeepSeek-Coder-7B | 16K | Excellente | Très faible |
| Phi-3-medium-128k | 128K | Bonne | Faible |

---

## 5. Recommandations Immédiates

1. **Limite output réduite à 2000 tokens** pour Pass 1.2 (concepts) - forcer frugalité
2. **Prompt renforcé** avec "INTERDIT de reformuler" + "COPIE VERBATIM OBLIGATOIRE"
3. **Fallback OpenAI** si JSON tronqué détecté (retry avec GPT-4o-mini)
4. **Validation JSON** avant parsing avec regex extraction

---

## 6. Métriques de Comparaison à Collecter

Pour évaluer correctement Qwen vs GPT-4o-mini:

| Métrique | Description |
|----------|-------------|
| Anchor Rate | % assertions ancrées sur DocItem |
| JSON Truncation Rate | % appels avec JSON tronqué |
| Verbatim Accuracy | % assertions copiées exactement vs reformulées |
| Tokens/Assertion | Efficacité output |
| Latency p50/p95 | Temps de réponse |
| Cost/Document | Coût total par document |

---

## 7. Historique des Tests

| Date | Cache | Modèle | Assertions | PROMOTED | Anchor Rate | Notes |
|------|-------|--------|------------|----------|-------------|-------|
| 2026-01-26 | Vision | Qwen-14B | 621 | 94 | 15.1% | Test avec Vision cache |
| 2026-01-26 | TEXT-ONLY | Qwen-14B | 1126 | 135 | 0% | Pipeline crash (troncature) |

---

*Document généré pour analyse comparative avec ChatGPT*
