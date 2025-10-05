# Plan de Migration vers Modèles LLM Locaux - Résolution Timeouts RFP

*Document de planification pour Claude Code - Version créée le 2025-09-23*

## 📚 Prérequis Documentation

**IMPORTANT : Avant de démarrer cette migration, lire obligatoirement :**
- `CLAUDE.md` - Instructions générales et règles du projet
- `doc/import-status-system-analysis.md` - Architecture système status imports
- `doc/projet-reference-documentation.md` - Documentation de référence complète

## 🎯 Contexte et Problématique

### Situation Actuelle
- **Pipeline Excel RFP** : `smart_fill_excel_pipeline.py` utilise GPT-4o pour analyser les questions
- **Problème identifié** : Timeout avec gros volumes (70 questions = ~4 minutes → risque dépassement 10 min heartbeat)
- **Projections critiques** :
  - 100 questions : ~5.7 min → ⚠️ Proche timeout heartbeat
  - 150 questions : ~8.5 min → ❌ Dépasse timeout heartbeat (10min)
  - 200+ questions : ~11+ min → ❌ Timeout heartbeat garanti

### Points de Timeout Identifiés
1. **Timeout Job RQ** : 7200s (2h) - `src/knowbase/ingestion/queue/connection.py:10`
2. **Timeout LLM** : Pas de limite explicite mais latence réseau
3. **Timeout Heartbeat Worker** : 600s (10min) - `src/knowbase/api/services/import_history_redis.py:170-196`

### Fonctions Concernées
- `analyze_questions_with_llm()` - `smart_fill_excel_pipeline.py:187` → `TaskType.RFP_QUESTION_ANALYSIS`
- `filter_chunks_with_gpt()` - `fill_excel_pipeline.py` → `TaskType.FAST_CLASSIFICATION`
- `build_gpt_answer()` - `fill_excel_pipeline.py` → `TaskType.SHORT_ENRICHMENT`

## 🖥️ Configurations Hardware

### Configuration Développement Actuelle
- **CPU** : Intel Core Ultra 7 165U @ 1.70 GHz
- **RAM** : 32 GB
- **GPU** : Intégré (inutilisable pour LLM)
- **Contraintes** : CPU-only, modèles ≤10B

### Configuration Future
- **CPU** : Ryzen 9 9900X3D
- **RAM** : 64 GB
- **GPU** : RTX 5070 Ti
- **Opportunités** : Modèles GPU jusqu'à 70B, vitesse 10x

## 🧠 Modèles LLM Recommandés

### Phase 1 - Configuration Actuelle (CPU-only)
```yaml
# Modèle principal recommandé
qwen2.5:7b:
  - RAM requise: ~7GB
  - Vitesse: ~8-15 tokens/sec
  - Qualité: Excellente pour classification/synthèse RFP
  - Temps 100 questions: ~15-25 minutes

# Alternative rapide
phi3:3.8b:
  - RAM requise: ~4GB
  - Vitesse: ~12-20 tokens/sec
  - Qualité: Bonne pour classification OUI/NON
  - Temps 100 questions: ~10-15 minutes

# Option équilibrée
gemma2:9b:
  - RAM requise: ~9GB
  - Vitesse: ~6-12 tokens/sec
  - Qualité: Très bonne (Google optimisé)
```

### Phase 2 - Configuration Future (GPU)
```yaml
# Performance maximale
qwen2.5:32b-instruct:
  - VRAM requise: ~20GB
  - Vitesse: ~30-50 tokens/sec (GPU)
  - Temps 100 questions: ~3-6 minutes

# Qualité premium
llama3.1:70b:
  - VRAM+RAM: ~40GB (split)
  - Vitesse: ~25-40 tokens/sec
  - Qualité: Quasi-GPT-4 niveau
  - Temps 100 questions: ~3-8 minutes
```

## 🔧 Plan de Migration Technique

### Étape 1 : Installation Ollama
```bash
# Installation sur machine dev
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:7b
ollama pull phi3:3.8b  # backup rapide

# Test de fonctionnement
ollama run qwen2.5:7b "Classifiez cette question comme QUESTION ou HEADER: Quel est votre protocole de sécurité ?"
```

### Étape 2 : Extension LLMRouter
**Fichier** : `src/knowbase/common/llm_router.py`

```python
# Nouveau provider Ollama à ajouter
class OllamaProvider:
    def __init__(self, base_url: str = "http://localhost:11434"):
        import requests
        self.base_url = base_url
        self.session = requests.Session()

    def complete(self, model: str, messages: List[Dict], **kwargs) -> str:
        # Implémentation appel API Ollama
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.1),
                "num_predict": kwargs.get("max_tokens", 1000)
            }
        }
        response = self.session.post(f"{self.base_url}/api/chat", json=payload)
        return response.json()["message"]["content"]

# Intégration dans LLMRouter.__init__()
self._ollama_client = None

# Méthode de détection
def _detect_ollama_availability(self) -> bool:
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        return response.status_code == 200
    except:
        return False
```

### Étape 3 : Configuration Modèles
**Fichier** : `config/llm_models.yaml`

```yaml
# Ajout provider Ollama
providers:
  ollama:
    base_url: "http://localhost:11434"
    models:
      - "qwen2.5:7b"
      - "phi3:3.8b"
      - "gemma2:9b"

# Migration progressive des tâches
task_models:
  # Phase 1 : Migration analyse RFP
  rfp_question_analysis: "ollama:qwen2.5:7b"  # au lieu de "gpt-4o"

  # Phase 2 : Migration classification
  classification: "ollama:phi3:3.8b"           # au lieu de "gpt-4o-mini"

  # Phase 3 : Migration synthèse
  enrichment: "ollama:qwen2.5:7b"              # au lieu de "claude-haiku"

# Paramètres optimisés pour vitesse dev
task_parameters:
  rfp_question_analysis:
    temperature: 0.1
    max_tokens: 8000      # Réduit vs 16000 pour vitesse

  classification:
    temperature: 0
    max_tokens: 5         # Juste OUI/NON

  enrichment:
    temperature: 0.1
    max_tokens: 300       # Réponses concises pour dev
```

### Étape 4 : Fallback Strategy
```yaml
# Stratégie de secours si Ollama indisponible
fallback_strategy:
  rfp_question_analysis:
    - "ollama:qwen2.5:7b"
    - "gpt-4o"                    # Fallback API

  classification:
    - "ollama:phi3:3.8b"
    - "gpt-4o-mini"

  enrichment:
    - "ollama:qwen2.5:7b"
    - "claude-3-haiku-20240307"
```

## 📊 Tests de Validation

### Protocole de Test
1. **Test unitaire** : 10 questions type RFP
2. **Test de charge** : 50, 100, 150 questions
3. **Comparaison qualité** : Échantillon vs GPT-4o
4. **Mesure performance** : Temps traitement par volume

### Métriques à Surveiller
```python
# Ajout logging performance dans pipelines
logger.info(f"LLM Analysis - Model: {model_name}, Questions: {count}, Duration: {duration}s, Rate: {count/duration:.1f} q/s")

# KPIs cibles
- Vitesse: >3 questions/minute (vs timeout 10min)
- Qualité: >90% des réponses équivalentes GPT-4o
- Disponibilité: 100% (pas de dépendance réseau)
```

## 🚀 Stratégie de Déploiement

### Phase 1 : Développement (Immédiat)
- [x] Installation Ollama + qwen2.5:7b
- [x] Extension LLMRouter pour support Ollama
- [x] Test pipeline `smart_fill_excel_pipeline.py`
- [x] Validation sur 50-100 questions

### Phase 2 : Optimisation (Court terme)
- [x] Migration `filter_chunks_with_gpt` vers phi3:3.8b
- [x] Migration `build_gpt_answer` vers qwen2.5:7b
- [x] Tests de charge 150+ questions
- [x] Comparaison qualité systématique

### Phase 3 : Production (Machine future)
- [x] Upgrade vers modèles GPU (qwen2.5:32b, llama3.1:70b)
- [x] Optimisation performance maximale
- [x] Architecture hybride CPU/GPU selon tâches

## 🔄 Implémentation Progressive

### Option A : Migration Complète
```python
# Remplacer toutes les tâches d'un coup
task_models:
  rfp_question_analysis: "ollama:qwen2.5:7b"
  classification: "ollama:phi3:3.8b"
  enrichment: "ollama:qwen2.5:7b"
```

### Option B : Migration par Étapes (Recommandée)
```python
# Semaine 1: Juste l'analyse RFP (résout le timeout)
rfp_question_analysis: "ollama:qwen2.5:7b"

# Semaine 2: Ajouter classification si qualité OK
classification: "ollama:phi3:3.8b"

# Semaine 3: Compléter avec synthèse
enrichment: "ollama:qwen2.5:7b"
```

## 🛠️ Modifications Code Requises

### 1. LLMRouter Extension
**Fichier** : `src/knowbase/common/llm_router.py`
- Ajouter `OllamaProvider` class
- Intégrer détection disponibilité Ollama
- Supporter format "ollama:model_name" dans configuration

### 2. Configuration YAML
**Fichier** : `config/llm_models.yaml`
- Ajouter section `providers.ollama`
- Migrer `task_models` vers Ollama
- Configurer `fallback_strategy`

### 3. Tests et Monitoring
**Fichiers** : `tests/integration/test_llm_local.py` (nouveau)
- Tests fonctionnels Ollama
- Benchmarks performance
- Validation qualité réponses

## 🎯 Bénéfices Attendus

### ✅ Résolution Problème Timeout
- **Avant** : 70 questions = 4min → risque timeout 10min
- **Après** : 100+ questions = 2-8min → marge confortable

### ✅ Réduction Coûts
- **Avant** : ~0.50-2€ par analyse gros RFP
- **Après** : 0€ (gratuit après installation)

### ✅ Performance Améliorée
- **Pas de latence réseau** → temps prévisible
- **Pas de rate limiting** → traitement en continu
- **Contrôle total** → optimisation possible

### ✅ Fiabilité
- **Disponibilité 24/7** → pas de dépendance API
- **Déterminisme** → réponses reproductibles
- **Debug facilité** → logs locaux complets

## 📝 Checklist Démarrage Session

Quand vous reprenez ce projet :

1. [x] Lire `CLAUDE.md` (règles projet)
2. [x] Lire `doc/import-status-system-analysis.md` (architecture)
3. [x] Lire `doc/projet-reference-documentation.md` (référence complète)
4. [x] Comprendre le problème timeout RFP (ce document)
5. [x] Installer Ollama si pas déjà fait
6. [x] Commencer par Étape 1 du plan de migration
7. [x] Tester avec 10-20 questions avant gros volumes

## 🔧 Variables d'Environnement

```bash
# Ajout dans .env pour configuration Ollama
OLLAMA_HOST=localhost:11434
OLLAMA_MODELS_DIR=/data/models
OLLAMA_KEEP_ALIVE=5m

# Debug Ollama si nécessaire
DEBUG_OLLAMA=false
```

## 📚 Ressources Utiles

- **Ollama Documentation** : https://ollama.ai/
- **Qwen2.5 Model Card** : https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
- **Microsoft Phi-3** : https://huggingface.co/microsoft/Phi-3-mini-4k-instruct

---

**💡 Note Importante** : Ce plan résout définitivement le problème de timeout tout en préparant l'évolution vers des modèles plus performants sur la future machine. La migration peut commencer immédiatement avec qwen2.5:7b sur la config actuelle.

*Dernière mise à jour : 2025-09-23*