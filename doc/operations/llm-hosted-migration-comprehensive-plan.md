# Plan de Migration Complète vers Modèles LLM Hostés - Analyse Exhaustive

*Document de planification pour Claude Code - Version créée le 2025-09-23*

## 📚 Prérequis Documentation

**IMPORTANT : Avant de démarrer cette migration, lire obligatoirement :**
- `CLAUDE.md` - Instructions générales et règles du projet
- `doc/import-status-system-analysis.md` - Architecture système status imports
- `doc/projet-reference-documentation.md` - Documentation de référence complète
- `doc/llm-local-migration-plan.md` - Plan migration LLM locaux (complémentaire)

## 🎯 Contexte et Objectifs

### Vision Stratégique
**Migration progressive de tous les appels LLM externes (OpenAI GPT-4o, Anthropic Claude) vers des modèles hébergés localement**, tout en conservant une architecture hybride pour les cas d'usage nécessitant la vision (temporairement).

### Motivations Principales
- **Réduction des coûts** : Élimination des coûts par token (actuellement significatifs)
- **Contrôle total** : Pas de dépendance aux APIs externes
- **Performance prédictible** : Pas de rate limiting ni timeouts réseau
- **Confidentialité** : Données traitées localement
- **Évolutivité** : Scaling horizontal possible

## 🔍 Analyse Exhaustive des Usages LLM Actuels

### Inventaire Complet par TaskType

#### 1. **VISION** 🖼️ (Multimodal - Critique)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py:723` - Analyse slides PowerPoint
- `src/knowbase/ingestion/pipelines/pdf_pipeline.py:157` - Analyse pages PDF

**Prompts utilisés :**
```python
# PPTX Pipeline - Analyse image + texte
{
  "type": "text",
  "text": "Global deck summary: {{ deck_summary }}\n\nSlide {{ slide_index }} extracted text: {{ text }}\n\nAnalyze slide {{ slide_index }} ('{{ source_name }}').\n\nYou are analyzing a single PowerPoint slide. Your goal is to extract its meaning and value for use in a knowledge base.\nDescribe the **visual content** in detail..."
}

# PDF Pipeline - OCR et analyse
{
  "type": "text",
  "text": "Tu es un expert en extraction de données. Extrais le contenu textuel de cette image de document PDF de manière structurée..."
}
```

**Configuration actuelle :** `gpt-4o`
**Complexité :** TRÈS ÉLEVÉE (vision + compréhension contextuelle)
**Migration :** ❌ **IMPOSSIBLE avec config actuelle** (pas de GPU vision)
**Plan futur :** Modèles vision locaux (LLaVA, Qwen2-VL) sur RTX 5070 Ti

#### 2. **METADATA_EXTRACTION** 📊 (JSON Structuré)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py:566` - Métadonnées deck
- `src/knowbase/ingestion/pipelines/pdf_pipeline.py:110` - Métadonnées PDF

**Prompts utilisés :**
```python
# Template depuis config/prompts.yaml
"""
Return a single JSON object with two fields:
- "summary": a concise thematic summary (3-5 sentences)
- "metadata": a JSON object with fields:
  - title, objective, main_solution, supporting_solutions, mentioned_solutions
  - document_type, audience, source_date, language

IMPORTANT:
- For 'main_solution', always use official SAP canonical solution name
- Return only the JSON object — no explanation
"""
```

**Configuration actuelle :** `gpt-4o`
**Complexité :** ÉLEVÉE (JSON structuré + connaissances SAP)
**Migration :** ✅ **POSSIBLE** - Modèles 7B+ excellent en JSON structuré

#### 3. **LONG_TEXT_SUMMARY** 📝 (Résumés Volumineux)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py:338,352` - Résumés partiels/finaux
- `src/knowbase/api/services/synthesis.py:122` - Synthèse réponses utilisateur

**Prompts utilisés :**
```python
# Résumé PPTX (partiel/final)
"You are a precise summarization assistant."
+ render_prompt(deck_template, summary_text=batch_text, source_name="partial")

# Synthèse réponses (synthesis.py)
"""
Tu es un assistant expert en SAP qui aide les utilisateurs à trouver des informations pertinentes.
Voici la question: {question}
Voici les informations trouvées: {chunks_content}

Instructions:
1. Synthétise une réponse cohérente
2. Utilise uniquement les informations fournies
3. Structure clairement avec références slides précises
4. Réponds en français
"""
```

**Configuration actuelle :** `gpt-4o-mini` / `claude-sonnet-4`
**Complexité :** MOYENNE-ÉLEVÉE (synthèse cohérente)
**Migration :** ✅ **EXCELLENTE** - Domaine de force des modèles 7B-14B

#### 4. **SHORT_ENRICHMENT** ✨ (Enrichissement Court)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/excel_pipeline.py:121` - Enrichissement Q/A Excel
- `src/knowbase/ingestion/pipelines/fill_excel_pipeline.py:272` - Génération réponses RFP

**Prompts utilisés :**
```python
# Excel Q/A Enrichment
"""
You are an assistant specialized in SAP RFP document processing.
You receive a customer input (question/statement) and its answer.
Your task is to reformulate them into well-structured Q/A pairs.
Return a JSON array with objects containing:
- "question": reformulated question
- "answer": reformulated answer
- "category": topic category
"""

# RFP Answer Generation
"""
Question ({question_lang}): {question}
Source information: {context}

Requirements:
1. Answer ONLY in {question_lang}
2. Use only the provided information
3. We are SAP - use 'SAP' instead of 'vendor/provider/supplier'
4. Be direct and concise
5. If no answer possible, respond: 'NO_ANSWER_FOUND'
"""
```

**Configuration actuelle :** `claude-3-haiku` / défaut
**Complexité :** MOYENNE (génération guidée)
**Migration :** ✅ **PARFAITE** - Cas d'usage idéal pour modèles locaux

#### 5. **FAST_CLASSIFICATION** ⚡ (Classification Binaire)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/fill_excel_pipeline.py:390,487` - Pertinence chunks + Clarification questions

**Prompts utilisés :**
```python
# Filtrage chunks (FR)
"""
Question : {question}
Extrait de document : {chunk}

Instructions :
- L'extrait doit être DIRECTEMENT pertinent pour répondre à cette question spécifique
- L'extrait doit contenir des informations factuelles liées au sujet
- Rejette les extraits trop généraux ou qui parlent d'autre chose
- Réponds uniquement par : OUI ou NON
"""

# Clarification questions
"""
Voici une question métier posée dans un fichier Excel :
{question}

Reformule cette question de façon claire et directe, comme si elle était posée dans un appel d'offre SAP.
Tu dois reformuler dans la même langue que la question d'origine.
"""
```

**Configuration actuelle :** `gpt-4o-mini`
**Complexité :** FAIBLE (réponses binaires/courtes)
**Migration :** ✅ **TRIVIALE** - Cas d'usage parfait pour modèles légers

#### 6. **CANONICALIZATION** 🔄 (Normalisation)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/excel_pipeline.py:206` - Normalisation questions
- `src/knowbase/api/services/sap_solutions.py:89` - Canonicalisation solutions SAP

**Prompts utilisés :**
```python
# Excel canonicalization
"You are an assistant. Reformulate the following instruction or statement into a clear, standalone question in the same language. Only reply with the question, nothing else."

# SAP Solutions canonicalization
"""
Voici une liste de solutions SAP mentionnées dans un document : {solutions}
Voici le catalogue de référence : {catalog}

Retourne un JSON avec les solutions normalisées selon le catalogue officiel SAP.
Format: {"normalized_solutions": ["solution1", "solution2"]}
"""
```

**Configuration actuelle :** `gpt-4o-mini`
**Complexité :** FAIBLE-MOYENNE (reformulation simple)
**Migration :** ✅ **EXCELLENTE** - Modèles 3B-7B suffisants

#### 7. **RFP_QUESTION_ANALYSIS** 🔍 (Analyse RFP Intelligente)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/smart_fill_excel_pipeline.py:294` - Analyse batch questions RFP

**Prompts utilisés :**
```python
# Analyse complexe RFP (prompt très détaillé)
"""
You are analyzing questions from an RFP Excel file for SAP solutions.

TASK: Analyze each row and return a structured analysis with intelligent question dependency handling.

COMPANIES TO PRESERVE: {preserve_companies_str}
- NEVER replace these (they refer to us as solution provider)
- Replace OTHER company names with "customer", "client", "customer organization"

INSTRUCTIONS:
1. CLASSIFY each row as: "QUESTION", "HEADER", "UNCLEAR"
2. HANDLE QUESTION DEPENDENCIES:
   - Analyze each question in sequence
   - If references previous question ("If yes/no", "In case of"), mark DEPENDENT
   - DEPENDENT questions reformulated with context
   - INDEPENDENT questions processed standalone

3. REFORMULATE questions:
   - For INDEPENDENT: Optimize for semantic search, make standalone
   - For DEPENDENT: Include full context from referenced question
   - Keep same language, make comprehensive

OUTPUT FORMAT (valid JSON): ...
"""
```

**Configuration actuelle :** `gpt-4o`
**Complexité :** TRÈS ÉLEVÉE (analyse séquentielle + logique dépendances)
**Migration :** ⚠️ **DIFFICILE** - Nécessite modèles 14B+ ou optimisation prompt

#### 8. **TRANSLATION** 🌐 (Traduction)
**Fichiers concernés :**
- `src/knowbase/ingestion/pipelines/fill_excel_pipeline.py:294` - Correction langue réponses

**Prompts utilisés :**
```python
# Translation simple
"""
Translate this text to {question_lang}, keeping the same meaning and technical accuracy:
{answer}
"""
```

**Configuration actuelle :** `gpt-4o-mini`
**Complexité :** FAIBLE (tâche simple)
**Migration :** ✅ **PARFAITE** - Modèles multilingues 3B+ excellents

## 📊 Matrice de Migration par Configuration

### Configuration Actuelle (Intel Core Ultra 7 + 32GB)

| TaskType | Complexité | Modèle Recommandé | Temps Estimé | Qualité Attendue |
|----------|------------|-------------------|--------------|-------------------|
| VISION | 🔴 IMPOSSIBLE | Garder `gpt-4o` | N/A | 100% (externe) |
| METADATA_EXTRACTION | 🟡 DIFFICILE | `qwen2.5:14b` | 10-15s | 85-90% |
| LONG_TEXT_SUMMARY | 🟢 EXCELLENT | `qwen2.5:7b` | 5-10s | 90-95% |
| SHORT_ENRICHMENT | 🟢 PARFAIT | `qwen2.5:7b` | 3-8s | 90-95% |
| FAST_CLASSIFICATION | 🟢 TRIVIAL | `phi3:3.8b` | 1-3s | 95%+ |
| CANONICALIZATION | 🟢 EXCELLENT | `phi3:3.8b` | 2-5s | 90%+ |
| RFP_QUESTION_ANALYSIS | 🟡 DIFFICILE | `qwen2.5:14b` | 15-25s | 80-85% |
| TRANSLATION | 🟢 PARFAIT | `gemma2:9b` | 2-5s | 95%+ |

### Configuration Future (Ryzen 9 9900X3D + RTX 5070 Ti + 64GB)

| TaskType | Complexité | Modèle Recommandé | Temps Estimé | Qualité Attendue |
|----------|------------|-------------------|--------------|-------------------|
| VISION | 🟢 EXCELLENT | `llava:34b` (GPU) | 3-8s | 85-90% |
| METADATA_EXTRACTION | 🟢 PARFAIT | `qwen2.5:32b` (GPU) | 2-5s | 95%+ |
| LONG_TEXT_SUMMARY | 🟢 PARFAIT | `llama3.1:70b` (GPU) | 3-8s | 95%+ |
| SHORT_ENRICHMENT | 🟢 PARFAIT | `qwen2.5:32b` (GPU) | 1-3s | 95%+ |
| FAST_CLASSIFICATION | 🟢 TRIVIAL | `phi3:3.8b` (CPU) | <1s | 95%+ |
| CANONICALIZATION | 🟢 PARFAIT | `qwen2.5:7b` (CPU) | 1-2s | 95%+ |
| RFP_QUESTION_ANALYSIS | 🟢 EXCELLENT | `llama3.1:70b` (GPU) | 5-12s | 90-95% |
| TRANSLATION | 🟢 PARFAIT | `qwen2.5:7b` (CPU) | 1-3s | 95%+ |

## 🔧 Plan Technique de Migration

### Phase 1 : Infrastructure Ollama (Semaine 1)

#### Installation et Configuration
```bash
# Installation Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Téléchargement modèles prioritaires
ollama pull qwen2.5:7b          # Modèle principal polyvalent
ollama pull phi3:3.8b           # Modèle rapide classification
ollama pull gemma2:9b           # Modèle équilibré

# Test fonctionnel
ollama run qwen2.5:7b "Résume en 2 phrases : SAP S/4HANA est une suite d'applications d'entreprise..."
```

#### Extension LLMRouter

**Fichier :** `src/knowbase/common/llm_router.py`

```python
class OllamaProvider:
    """Provider pour modèles Ollama locaux."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.available_models = self._get_available_models()

    def _get_available_models(self) -> List[str]:
        """Récupère la liste des modèles disponibles."""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Impossible de récupérer les modèles Ollama: {e}")
        return []

    def complete(self, model: str, messages: List[Dict], **kwargs) -> str:
        """Appel API Ollama pour complétion."""
        # Conversion du format OpenAI vers Ollama
        ollama_messages = []
        for msg in messages:
            # Gestion des messages multimodaux (vision)
            if isinstance(msg.get("content"), list):
                # Vision non supportée actuellement sur config actuelle
                raise NotImplementedError("Vision non supportée avec Ollama sur cette configuration")
            else:
                ollama_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        payload = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.1),
                "num_predict": kwargs.get("max_tokens", 1000),
                "top_k": kwargs.get("top_k", 40),
                "top_p": kwargs.get("top_p", 0.9),
            }
        }

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=300  # 5 minutes timeout
        )
        response.raise_for_status()

        return response.json()["message"]["content"]

# Intégration dans LLMRouter
class LLMRouter:
    def __init__(self, config_path: Optional[Path] = None):
        # ... existing code ...
        self._ollama_client = None
        self._ollama_available = self._detect_ollama_availability()

    def _detect_ollama_availability(self) -> bool:
        """Détecte si Ollama est disponible."""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False

    @property
    def ollama_client(self) -> OllamaProvider:
        """Client Ollama paresseux."""
        if self._ollama_client is None:
            self._ollama_client = OllamaProvider()
        return self._ollama_client

    def _route_model_call(self, model_name: str, messages: List[Dict], **kwargs) -> str:
        """Routage vers le bon provider selon le modèle."""
        if model_name.startswith("ollama:"):
            if not self._ollama_available:
                raise RuntimeError("Ollama non disponible")
            actual_model = model_name.replace("ollama:", "")
            return self.ollama_client.complete(actual_model, messages, **kwargs)
        elif model_name.startswith("gpt-"):
            return self._call_openai(model_name, messages, **kwargs)
        elif model_name.startswith("claude-"):
            return self._call_anthropic(model_name, messages, **kwargs)
        else:
            raise ValueError(f"Provider inconnu pour modèle: {model_name}")
```

### Phase 2 : Migration par Priorité (Semaines 2-4)

#### Priorité 1 : Tâches Simples (Semaine 2)
```yaml
# config/llm_models.yaml - Migration progressive
task_models:
  # Migration immédiate (gain maximal, risque minimal)
  classification: "ollama:phi3:3.8b"           # au lieu de "gpt-4o-mini"
  translation: "ollama:gemma2:9b"              # au lieu de "gpt-4o-mini"
  canonicalization: "ollama:phi3:3.8b"        # au lieu de "gpt-4o-mini"

  # Garder externe pour l'instant
  vision: "gpt-4o"                             # OBLIGATOIRE (pas de GPU vision)
  metadata: "gpt-4o"                           # Migration Semaine 3
  long_summary: "gpt-4o-mini"                  # Migration Semaine 3
  enrichment: "claude-3-haiku-20240307"       # Migration Semaine 4
  rfp_question_analysis: "gpt-4o"             # Migration Semaine 4

# Fallbacks hybrides
fallback_strategy:
  classification:
    - "ollama:phi3:3.8b"
    - "gpt-4o-mini"                            # Fallback API si Ollama down

  translation:
    - "ollama:gemma2:9b"
    - "gpt-4o-mini"
```

#### Priorité 2 : Tâches Moyennes (Semaine 3)
```yaml
task_models:
  # Migration modèles 7B-14B
  long_summary: "ollama:qwen2.5:7b"           # au lieu de "gpt-4o-mini"
  metadata: "ollama:qwen2.5:14b"              # au lieu de "gpt-4o" (si RAM suffisante)

  # Paramètres optimisés
task_parameters:
  long_summary:
    temperature: 0.1
    max_tokens: 1500

  metadata:
    temperature: 0.05      # Plus déterministe pour JSON
    max_tokens: 2000
```

#### Priorité 3 : Tâches Complexes (Semaine 4)
```yaml
task_models:
  # Migration dernières tâches text-only
  enrichment: "ollama:qwen2.5:7b"             # au lieu de "claude-haiku"
  rfp_question_analysis: "ollama:qwen2.5:14b" # au lieu de "gpt-4o" (avec optimisation prompt)

  # Vision reste externe (temporaire)
  vision: "gpt-4o"                             # Migration Phase 3 (machine future)
```

### Phase 3 : Optimisation et Vision (Machine Future)

#### Migration Vision Complète
```yaml
# config/llm_models.yaml - Configuration finale
providers:
  ollama:
    base_url: "http://localhost:11434"
    models:
      # Vision multimodale
      - "llava:34b"                            # Vision + texte
      - "qwen2-vl:7b"                          # Vision spécialisée

      # Modèles texte premium
      - "llama3.1:70b"                         # Qualité maximale
      - "qwen2.5:32b"                          # Équilibre performance/qualité
      - "qwen2.5:14b"                          # Modèle moyen
      - "qwen2.5:7b"                           # Modèle léger

task_models:
  # Configuration finale 100% locale
  vision: "ollama:llava:34b"                   # 🎯 MIGRATION COMPLÈTE
  metadata: "ollama:qwen2.5:32b"
  long_summary: "ollama:llama3.1:70b"
  enrichment: "ollama:qwen2.5:32b"
  classification: "ollama:phi3:3.8b"
  canonicalization: "ollama:qwen2.5:7b"
  rfp_question_analysis: "ollama:llama3.1:70b"
  translation: "ollama:qwen2.5:7b"
```

## 🧪 Protocole de Tests et Validation

### Tests Unitaires par TaskType

#### 1. Classification (FAST_CLASSIFICATION)
```python
# tests/integration/test_ollama_classification.py
def test_classification_quality():
    test_cases = [
        {
            "question": "Quelle est la politique de sécurité SAP ?",
            "chunk": "SAP S/4HANA inclut des fonctionnalités de sécurité avancées...",
            "expected": "OUI"
        },
        {
            "question": "Comment configurer la paie ?",
            "chunk": "Les modules logistiques permettent la gestion des stocks...",
            "expected": "NON"
        }
    ]

    ollama_results = []
    gpt_results = []

    for case in test_cases:
        # Test Ollama
        ollama_response = llm_router.complete(
            TaskType.FAST_CLASSIFICATION,
            build_classification_prompt(case["question"], case["chunk"])
        )
        ollama_results.append(ollama_response.strip().upper())

        # Test GPT baseline
        # ... comparison logic

    accuracy = calculate_accuracy(ollama_results, [case["expected"] for case in test_cases])
    assert accuracy >= 0.90, f"Accuracy trop faible: {accuracy}"
```

#### 2. Enrichissement (SHORT_ENRICHMENT)
```python
def test_enrichment_quality():
    sample_qa = {
        "question": "Prérequis techniques",
        "answer": "Windows Server 2019+, 32GB RAM"
    }

    ollama_result = llm_router.complete(
        TaskType.SHORT_ENRICHMENT,
        build_enrichment_prompt(sample_qa)
    )

    # Validation structure JSON
    parsed = json.loads(ollama_result)
    assert "question" in parsed[0]
    assert "answer" in parsed[0]
    assert len(parsed[0]["question"]) > len(sample_qa["question"])  # Enrichissement
```

#### 3. Métadonnées (METADATA_EXTRACTION)
```python
def test_metadata_extraction():
    sample_summary = """
    Cette présentation introduit SAP SuccessFactors pour la gestion RH.
    Elle s'adresse aux responsables RH et IT.
    Couvre le recrutement, l'évaluation des performances et la formation.
    Document créé en janvier 2024.
    """

    ollama_result = llm_router.complete(
        TaskType.METADATA_EXTRACTION,
        build_metadata_prompt(sample_summary)
    )

    parsed = json.loads(ollama_result)
    assert "metadata" in parsed
    assert parsed["metadata"]["main_solution"] == "SAP SuccessFactors"
    assert parsed["metadata"]["audience"] is not None
```

### Tests de Performance

#### Benchmark Temps de Réponse
```python
def benchmark_response_times():
    """Compare les temps de réponse Ollama vs APIs externes."""
    test_prompts = {
        TaskType.FAST_CLASSIFICATION: classification_samples,
        TaskType.SHORT_ENRICHMENT: enrichment_samples,
        TaskType.CANONICALIZATION: canonicalization_samples,
    }

    results = {}

    for task_type, samples in test_prompts.items():
        ollama_times = []
        api_times = []

        for sample in samples:
            # Test Ollama
            start = time.time()
            ollama_response = llm_router.complete(task_type, sample)
            ollama_times.append(time.time() - start)

            # Test API externe (baseline)
            # ... similar timing

        results[task_type] = {
            "ollama_avg": np.mean(ollama_times),
            "api_avg": np.mean(api_times),
            "improvement": (np.mean(api_times) - np.mean(ollama_times)) / np.mean(api_times)
        }

    return results
```

### Tests de Charge (Volume)

#### Test RFP Excel Complet
```python
def test_rfp_processing_volume():
    """Test traitement RFP avec 100+ questions."""

    # Génère 100 questions de test
    test_questions = generate_rfp_questions(count=100)

    start_time = time.time()

    # Test pipeline complet avec Ollama
    processed = analyze_questions_with_llm(test_questions)

    duration = time.time() - start_time

    # Validations
    assert len(processed) > 0, "Aucune question traitée"
    assert duration < 1800, f"Trop lent: {duration}s (max 30min)"  # 30min max acceptable

    success_rate = len([q for q in processed if q.category == "QUESTION"]) / len(test_questions)
    assert success_rate > 0.7, f"Taux de succès trop faible: {success_rate}"

    logger.info(f"✅ Test volume: {len(test_questions)} questions en {duration:.1f}s")
    logger.info(f"✅ Vitesse: {len(test_questions)/duration:.1f} questions/sec")
```

## 📈 Métriques et KPIs

### Indicateurs de Performance

#### KPIs Techniques
```python
class MigrationMetrics:
    """Collecte des métriques de migration."""

    def __init__(self):
        self.response_times = defaultdict(list)
        self.error_rates = defaultdict(float)
        self.cost_savings = 0.0
        self.quality_scores = defaultdict(list)

    def log_task_completion(self, task_type: TaskType, duration: float,
                           provider: str, success: bool, quality_score: float = None):
        """Log d'une completion de tâche."""
        self.response_times[f"{task_type.value}_{provider}"].append(duration)

        if not success:
            self.error_rates[f"{task_type.value}_{provider}"] += 1

        if quality_score:
            self.quality_scores[f"{task_type.value}_{provider}"].append(quality_score)

    def calculate_cost_savings(self) -> Dict[str, float]:
        """Calcule les économies réalisées."""
        # Coûts estimés par task type (basé sur usage actuel)
        api_costs_per_1000_calls = {
            TaskType.VISION: 15.0,               # GPT-4o vision cher
            TaskType.METADATA_EXTRACTION: 8.0,   # GPT-4o
            TaskType.LONG_TEXT_SUMMARY: 3.0,     # GPT-4o-mini/Claude
            TaskType.SHORT_ENRICHMENT: 2.0,      # Claude Haiku
            TaskType.FAST_CLASSIFICATION: 0.8,   # GPT-4o-mini
            TaskType.CANONICALIZATION: 0.5,      # GPT-4o-mini
            TaskType.RFP_QUESTION_ANALYSIS: 12.0, # GPT-4o (gros prompts)
            TaskType.TRANSLATION: 0.3,           # GPT-4o-mini
        }

        # Usage mensuel estimé
        monthly_usage = {
            TaskType.VISION: 500,                # Slides analysées
            TaskType.METADATA_EXTRACTION: 200,   # Documents
            TaskType.LONG_TEXT_SUMMARY: 800,     # Synthèses
            TaskType.SHORT_ENRICHMENT: 2000,     # Q/A + RFP
            TaskType.FAST_CLASSIFICATION: 5000,  # Filtrage chunks
            TaskType.CANONICALIZATION: 1000,     # Reformulations
            TaskType.RFP_QUESTION_ANALYSIS: 50,  # RFP complets
            TaskType.TRANSLATION: 200,           # Corrections langue
        }

        total_monthly_cost_before = sum(
            api_costs_per_1000_calls[task] * monthly_usage[task] / 1000
            for task in api_costs_per_1000_calls
        )

        # Coût après migration (seulement Vision externe)
        total_monthly_cost_after = (
            api_costs_per_1000_calls[TaskType.VISION] *
            monthly_usage[TaskType.VISION] / 1000
        )

        return {
            "monthly_savings": total_monthly_cost_before - total_monthly_cost_after,
            "yearly_savings": (total_monthly_cost_before - total_monthly_cost_after) * 12,
            "reduction_percentage": (1 - total_monthly_cost_after / total_monthly_cost_before) * 100
        }

    def generate_report(self) -> str:
        """Génère un rapport de migration."""
        cost_data = self.calculate_cost_savings()

        report = f"""
# 📊 Rapport de Migration LLM Hostés

## 💰 Économies Réalisées
- **Économie mensuelle** : {cost_data['monthly_savings']:.2f}€
- **Économie annuelle** : {cost_data['yearly_savings']:.2f}€
- **Réduction des coûts** : {cost_data['reduction_percentage']:.1f}%

## ⚡ Performance par TaskType
"""

        for task_type in TaskType:
            ollama_times = self.response_times.get(f"{task_type.value}_ollama", [])
            api_times = self.response_times.get(f"{task_type.value}_api", [])

            if ollama_times and api_times:
                ollama_avg = np.mean(ollama_times)
                api_avg = np.mean(api_times)
                improvement = ((api_avg - ollama_avg) / api_avg) * 100

                report += f"""
### {task_type.value.upper()}
- **Ollama** : {ollama_avg:.2f}s moyenne
- **API** : {api_avg:.2f}s moyenne
- **Amélioration** : {improvement:+.1f}%
"""

        return report
```

#### Dashboarding Temps Réel
```python
# src/knowbase/api/routers/migration_metrics.py
@router.get("/migration/metrics")
async def get_migration_metrics():
    """Endpoint pour monitoring migration."""
    metrics = MigrationMetrics()

    return {
        "cost_savings": metrics.calculate_cost_savings(),
        "performance_summary": {
            task_type.value: {
                "avg_response_time": np.mean(metrics.response_times.get(f"{task_type.value}_ollama", [0])),
                "error_rate": metrics.error_rates.get(f"{task_type.value}_ollama", 0),
                "quality_score": np.mean(metrics.quality_scores.get(f"{task_type.value}_ollama", [0]))
            }
            for task_type in TaskType
        },
        "ollama_status": check_ollama_health()
    }

def check_ollama_health() -> Dict[str, Any]:
    """Vérifie la santé du service Ollama."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = response.json().get("models", [])

        return {
            "status": "healthy",
            "models_count": len(models),
            "available_models": [m["name"] for m in models]
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
```

## 🚨 Gestion des Risques et Fallbacks

### Architecture Hybride Robuste

#### Fallback Automatique
```python
class HybridLLMRouter(LLMRouter):
    """Router avec fallback automatique API/Local."""

    def complete(self, task_type: TaskType, messages: List[Dict], **kwargs) -> str:
        """Completion avec fallback automatique."""

        # 1. Tentative modèle local d'abord
        local_model = self._get_local_model(task_type)
        if local_model and self._ollama_available:
            try:
                result = self._route_model_call(local_model, messages, **kwargs)
                self._log_success(task_type, "ollama", result)
                return result

            except Exception as e:
                logger.warning(f"Ollama failed for {task_type}: {e}")
                self._log_failure(task_type, "ollama", str(e))

        # 2. Fallback vers API externe
        api_model = self._get_api_fallback(task_type)
        if api_model:
            try:
                result = self._route_model_call(api_model, messages, **kwargs)
                self._log_success(task_type, "api", result)
                return result

            except Exception as e:
                logger.error(f"API fallback failed for {task_type}: {e}")
                self._log_failure(task_type, "api", str(e))
                raise

        raise RuntimeError(f"Aucun provider disponible pour {task_type}")

    def _get_local_model(self, task_type: TaskType) -> Optional[str]:
        """Récupère le modèle local pour une tâche."""
        model_mapping = self._config.get("task_models", {})
        model = model_mapping.get(task_type.value)

        if model and model.startswith("ollama:"):
            return model
        return None

    def _get_api_fallback(self, task_type: TaskType) -> Optional[str]:
        """Récupère le fallback API pour une tâche."""
        fallbacks = self._config.get("fallback_strategy", {})
        task_fallbacks = fallbacks.get(task_type.value, [])

        for fallback in task_fallbacks:
            if not fallback.startswith("ollama:"):
                return fallback

        return None
```

#### Monitoring et Alertes
```python
# src/knowbase/api/services/health_monitor.py
class HealthMonitor:
    """Monitoring de santé des services LLM."""

    def __init__(self):
        self.failure_counts = defaultdict(int)
        self.last_success = defaultdict(float)

    def check_ollama_degradation(self) -> bool:
        """Détecte une dégradation d'Ollama."""
        failure_rate = self.failure_counts["ollama"] / max(1, self.failure_counts["total"])
        last_success_age = time.time() - self.last_success.get("ollama", 0)

        # Seuils d'alerte
        if failure_rate > 0.3:  # 30% échecs
            logger.warning(f"⚠️ Ollama failure rate élevé: {failure_rate:.2%}")
            return True

        if last_success_age > 300:  # 5min sans succès
            logger.warning(f"⚠️ Ollama inactif depuis {last_success_age:.0f}s")
            return True

        return False

    def auto_recovery_actions(self):
        """Actions de récupération automatique."""
        if self.check_ollama_degradation():
            # 1. Tentative restart Ollama
            try:
                subprocess.run(["ollama", "serve"], check=False, timeout=10)
                logger.info("🔄 Tentative restart Ollama")
            except:
                pass

            # 2. Bascule temporaire vers APIs
            logger.warning("🚨 Basculement forcé vers APIs externes")
            # Modifier config temporairement
```

## 🎯 Roadmap de Déploiement

### Timeline Détaillée

#### Semaine 1 : Infrastructure
- ✅ **Jour 1-2** : Installation Ollama + modèles de base
- ✅ **Jour 3-4** : Extension LLMRouter + tests unitaires
- ✅ **Jour 5** : Tests intégration + fallbacks

#### Semaine 2 : Migration Tâches Simples
- ✅ **Jour 1** : Migration FAST_CLASSIFICATION (phi3:3.8b)
- ✅ **Jour 2** : Migration TRANSLATION (gemma2:9b)
- ✅ **Jour 3** : Migration CANONICALIZATION (phi3:3.8b)
- ✅ **Jour 4-5** : Tests qualité + ajustements

#### Semaine 3 : Migration Tâches Moyennes
- ✅ **Jour 1** : Migration LONG_TEXT_SUMMARY (qwen2.5:7b)
- ✅ **Jour 2-3** : Migration METADATA_EXTRACTION (qwen2.5:14b si RAM OK)
- ✅ **Jour 4-5** : Tests performance + optimisations

#### Semaine 4 : Migration Tâches Complexes
- ✅ **Jour 1-2** : Migration SHORT_ENRICHMENT (qwen2.5:7b)
- ✅ **Jour 3-4** : Migration RFP_QUESTION_ANALYSIS (qwen2.5:14b + optimisation prompt)
- ✅ **Jour 5** : Tests charge RFP 100+ questions

#### Phase Future : Vision Locale (Post RTX 5070 Ti)
- ✅ **Semaine 1** : Installation modèles vision (llava:34b, qwen2-vl:7b)
- ✅ **Semaine 2** : Adaptation pipelines PPTX/PDF
- ✅ **Semaine 3** : Migration complète VISION
- ✅ **Semaine 4** : Optimisation et monitoring final

### Critères de Succès

#### Phase 1 (Tâches Simples)
- ✅ **Performance** : Temps réponse ≤ 5s moyenne
- ✅ **Qualité** : Accuracy ≥ 90% vs baseline API
- ✅ **Fiabilité** : Uptime ≥ 99% (fallback inclus)
- ✅ **Économies** : -60% coûts LLM

#### Phase 2 (Tâches Moyennes)
- ✅ **Performance** : Temps réponse ≤ 10s moyenne
- ✅ **Qualité** : Accuracy ≥ 85% vs baseline API
- ✅ **Throughput** : Capacité traitement 100+ questions RFP
- ✅ **Économies** : -80% coûts LLM

#### Phase 3 (Migration Complète)
- ✅ **Performance** : Temps réponse ≤ 8s moyenne (vision incluse)
- ✅ **Qualité** : Accuracy ≥ 90% toutes tâches
- ✅ **Autonomie** : 100% indépendance APIs externes
- ✅ **Économies** : -95% coûts LLM (sauf infrastructure)

## 📋 Checklist de Démarrage Session

Quand vous reprenez ce projet pour la migration :

### Prérequis
1. [x] Lire `CLAUDE.md` (règles projet)
2. [x] Lire `doc/import-status-system-analysis.md` (architecture)
3. [x] Lire `doc/projet-reference-documentation.md` (référence complète)
4. [x] Lire `doc/llm-local-migration-plan.md` (plan local complémentaire)
5. [x] Comprendre l'analyse complète des TaskTypes (ce document)

### Démarrage Migration
6. [x] Vérifier configuration hardware disponible
7. [x] Installer Ollama si pas déjà fait : `curl -fsSL https://ollama.ai/install.sh | sh`
8. [x] Télécharger modèles prioritaires selon phase
9. [x] Commencer par Phase 1 - Tâches Simples
10. [x] Exécuter tests qualité avant migration suivante

### Outils de Debug
```bash
# Vérifier Ollama
curl http://localhost:11434/api/tags

# Test modèle
ollama run qwen2.5:7b "Test simple: résume SAP en une phrase"

# Monitoring performance
docker-compose logs -f app | grep "LLM"

# Métriques migration
curl http://localhost:8000/api/migration/metrics
```

## 🏆 Impact Attendu

### Bénéfices Quantifiés

#### Économiques
- **Coût mensuel actuel** : ~120-180€ (estimation basée usage)
- **Coût après migration** : ~15-25€ (seulement Vision)
- **Économie annuelle** : ~1200-1800€
- **ROI infrastructure** : 6-12 mois

#### Performance
- **Latence** : -50 à -80% (pas de réseau)
- **Débit** : +200 à +500% (pas de rate limiting)
- **Disponibilité** : 99.9% (contrôle local)
- **Prévisibilité** : 100% (pas de variations API)

#### Qualité
- **Cohérence** : +30% (même modèle partout)
- **Personnalisation** : Prompts optimisés pour modèles spécifiques
- **Contrôle** : Fine-tuning possible sur cas d'usage SAP
- **Évolution** : Indépendance des roadmaps externes

---

**💡 Conclusion** : Cette migration représente un changement fondamental vers l'autonomie LLM tout en préservant la qualité de service. La stratégie hybride avec fallbacks garantit une transition sûre et progressive.

*Dernière mise à jour : 2025-09-23*