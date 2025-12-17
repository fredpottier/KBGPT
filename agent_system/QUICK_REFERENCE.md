# 📋 Quick Reference - KnowWhere Agent System

*Aide-mémoire pour utilisation quotidienne*

---

## 🚀 Démarrage Rapide

### 1. Vérifier l'Installation

```bash
cd agent_system
python scripts/verify_installation.py
```

### 2. Configurer les Variables d'Environnement

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:LANGSMITH_API_KEY="lsv2_pt_..."

# Linux/Mac
export ANTHROPIC_API_KEY="sk-ant-..."
export LANGSMITH_API_KEY="lsv2_pt_..."
```

### 3. Exécuter une Tâche Simple

```bash
python scripts/run_orchestrator.py \
  --task "Implement a hello world function" \
  --priority low
```

---

## 📁 Structure du Projet

```
agent_system/
├── src/
│   ├── models/         # Data models Pydantic
│   ├── tools/          # 6 tools (filesystem, shell, git, testing, code_analysis, docker)
│   ├── agents/         # 3 agents (planning, dev, control)
│   ├── core/           # Orchestrateur LangGraph
│   └── monitoring/     # LangSmith integration
├── config/
│   ├── agents_settings.yaml
│   ├── tools_permissions.yaml
│   ├── langsmith.yaml
│   └── prompts/
│       ├── planning.yaml
│       ├── dev.yaml
│       └── control.yaml
├── scripts/
│   ├── run_orchestrator.py
│   └── verify_installation.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── data/               # Runtime data
    ├── plans/
    └── reports/
```

---

## 💻 Commandes Essentielles

### Exécution

```bash
# Tâche simple
python scripts/run_orchestrator.py --task "Votre tâche"

# Tâche avec requirements
python scripts/run_orchestrator.py \
  --task "Implement calculator" \
  --requirements "add,subtract,multiply,divide,tests" \
  --priority high

# Mode daemon (Docker)
python scripts/run_orchestrator.py \
  --task "Task" \
  --daemon
```

### Tests

```bash
# Tests unitaires
pytest tests/unit/ -v

# Tests d'intégration
pytest tests/integration/ -v

# Tests E2E (nécessite ANTHROPIC_API_KEY)
pytest tests/e2e/ -v

# Avec coverage
pytest --cov=src --cov-report=html

# Tests rapides uniquement (skip slow)
pytest -v -m "not slow"

# Tests spécifiques
pytest tests/unit/test_models.py::TestTaskModel::test_task_creation -v
```

### Docker

```bash
# Build
docker-compose -f docker-compose.agents.yml build

# Start
docker-compose -f docker-compose.agents.yml up -d

# Logs
docker-compose -f docker-compose.agents.yml logs -f agent-orchestrator

# Stop
docker-compose -f docker-compose.agents.yml down

# Exec into container
docker-compose -f docker-compose.agents.yml exec agent-orchestrator bash
```

---

## 🛠️ Configuration Rapide

### agents_settings.yaml

```yaml
llm:
  model: "claude-sonnet-4-5-20250929"
  temperature: 0.2
  max_tokens: 8192

orchestrator:
  max_iterations: 10
  human_in_loop: false
```

### tools_permissions.yaml

```yaml
shell:
  allowed_commands:
    - "^pytest\\s+.*"
    - "^git\\s+status$"
    - "^git\\s+diff\\s+.*"

filesystem:
  allowed_read_paths:
    - "agent_system/**"
    - "src/**"
  allowed_write_paths:
    - "agent_system/data/**"
```

### langsmith.yaml

```yaml
langsmith:
  api_key: "${LANGSMITH_API_KEY}"
  project: "knowwhere-agents"
  tracing_enabled: true
```

---

## 🔧 Utilisation Programmatique

### Exemple Basique

```python
from models import Task, TaskPriority
from core.orchestrator import AgentOrchestrator
from monitoring import configure_langsmith

# Configure monitoring
configure_langsmith()

# Créer la tâche
task = Task(
    task_id="task_001",
    title="Calculator Implementation",
    description="Implement add and subtract functions",
    requirements=[
        "Function add(a, b) returns a + b",
        "Function subtract(a, b) returns a - b",
        "Write unit tests",
    ],
    priority=TaskPriority.HIGH,
)

# Initialiser l'orchestrateur
orchestrator = AgentOrchestrator(config_path="agent_system/config/")

# Exécuter
result = orchestrator.run(task=task)

# Résultats
print(f"Status: {result['status']}")
print(f"Plan ID: {result['plan_id']}")
print(f"Dev Reports: {len(result['dev_reports'])}")
print(f"Validation: {result['validation_passed']}")
```

### Exemple Avancé avec Context

```python
task = Task(
    task_id="task_002",
    title="Refactor Module",
    description="Refactor user authentication module",
    requirements=[
        "Maintain backward compatibility",
        "Improve test coverage to 90%+",
        "Add type hints",
    ],
    priority=TaskPriority.MEDIUM,
    context={
        "project_type": "python",
        "module_path": "src/auth/",
        "existing_tests": "tests/auth/",
        "refactoring": True,
        "preserve_api": True,
    }
)

result = orchestrator.run(task=task, context={"branch": "refactor-auth"})
```

---

## 📊 Interprétation des Résultats

### Structure du Résultat

```python
{
    "status": "success" | "failed",
    "task_id": "task_001",
    "plan_id": "plan_20251202_143025",
    "dev_reports": [
        {
            "report_id": "dev_report_20251202_143030",
            "subtask_id": "subtask_001",
            "files_modified": ["calculator.py"],
            "lines_added": 45,
            "lines_deleted": 0,
            "tests_executed": {
                "total_tests": 10,
                "passed": 10,
                "failed": 0,
            },
            "test_coverage": {
                "total_coverage": 0.95,
                "line_coverage": 0.95,
                "branch_coverage": 0.90,
            },
            "status": "SUCCESS",
        }
    ],
    "control_reports": [
        {
            "report_id": "control_report_20251202_143035",
            "conformity_score": 0.90,
            "quality_score": 0.85,
            "test_score": 0.95,
            "security_score": 1.0,
            "performance_score": 0.90,
            "overall_score": 0.91,
            "decision": "APPROVED",
        }
    ],
    "validation_passed": True,
    "iterations": 1,
}
```

### Scores de Validation

| Score | Signification |
|-------|---------------|
| **Conformity** | Conformité aux spécifications |
| **Quality** | Qualité du code (linting, complexité) |
| **Test** | Coverage et succès des tests |
| **Security** | Absence de vulnérabilités |
| **Performance** | Performance estimée |
| **Overall** | Score global pondéré |

### Décisions Control Agent

- **APPROVED** (score ≥ 0.85): Validation OK, tâche terminée
- **APPROVED_WITH_COMMENTS** (0.70 ≤ score < 0.85): Validation OK avec réserves
- **REJECTED** (score < 0.70 ou issues critiques): Rejet, replanification

---

## 🔍 Monitoring LangSmith

### Accès Dashboard

```
https://smith.langchain.com/
Project: knowwhere-agents
```

### Traces Importantes

- **Planning traces**: Décomposition de tâches
- **Dev traces**: Génération de code
- **Control traces**: Validation et scoring

### Evaluators Configurés

1. **conformity_score**: Score de conformité aux specs
2. **test_coverage**: Taux de couverture des tests
3. **hallucination_detection**: Détection d'hallucinations

---

## 🐛 Troubleshooting Rapide

### Erreur: "ANTHROPIC_API_KEY not found"

```bash
# Vérifier
echo $ANTHROPIC_API_KEY  # Linux/Mac
$env:ANTHROPIC_API_KEY   # Windows

# Définir
export ANTHROPIC_API_KEY="sk-ant-..."  # Linux/Mac
$env:ANTHROPIC_API_KEY="sk-ant-..."   # Windows
```

### Erreur: "Module not found"

```bash
# Réinstaller dépendances
cd agent_system
pip install -r requirements.txt
```

### Erreur: "Config file not found"

```bash
# Vérifier présence
ls -la agent_system/config/

# Vérifier path dans commande
python scripts/run_orchestrator.py --config agent_system/config/
```

### Tests échouent

```bash
# Vérifier installation
python scripts/verify_installation.py

# Tests unitaires uniquement (plus rapides)
pytest tests/unit/ -v

# Skip tests lents
pytest -v -m "not slow"
```

### LangSmith ne trace pas

```bash
# Vérifier variable
echo $LANGSMITH_TRACING

# Activer
export LANGSMITH_TRACING="true"

# Vérifier config
cat agent_system/config/langsmith.yaml
```

---

## 📚 Documentation Complète

- **README**: `agent_system/README.md` - Documentation complète
- **Implementation Guide**: `agent_system/IMPLEMENTATION_GUIDE.md` - Guide développeur
- **Finalization Report**: `agent_system/FINALIZATION_REPORT.md` - Rapport complet
- **Quick Start**: `agent_system/QUICKSTART.md` - Démarrage 5 minutes

---

## 🔗 Liens Utiles

- **LangGraph Docs**: https://python.langchain.com/docs/langgraph
- **LangSmith Dashboard**: https://smith.langchain.com/
- **Claude API Docs**: https://docs.anthropic.com/
- **Pydantic Docs**: https://docs.pydantic.dev/

---

## 💡 Tips & Best Practices

### Écriture de Tâches

✅ **Bon**:
```
"Implement a calculator with add, subtract, multiply, divide operations.
Handle edge cases like division by zero. Write comprehensive unit tests."
```

❌ **Mauvais**:
```
"Make a calculator"
```

### Requirements Clairs

✅ **Bon**:
```python
requirements=[
    "Function add(a, b) returns sum of a and b",
    "Function divide(a, b) raises ValueError on zero division",
    "Unit tests with 90%+ coverage",
    "Pass ruff linting",
]
```

❌ **Mauvais**:
```python
requirements=["Make it work", "Add tests"]
```

### Context Utile

```python
context={
    "project_type": "python",
    "test_framework": "pytest",
    "existing_code": "src/utils/math.py",
    "coding_style": "PEP 8",
    "target_python": "3.11+",
}
```

---

## 🎯 Cas d'Usage Courants

### 1. Nouvelle Feature

```bash
python scripts/run_orchestrator.py \
  --task "Add user authentication with JWT tokens" \
  --requirements "Secure password hashing,Token expiration,Refresh tokens,Unit tests" \
  --priority high
```

### 2. Bug Fix

```bash
python scripts/run_orchestrator.py \
  --task "Fix memory leak in cache manager" \
  --requirements "Identify leak source,Implement proper cleanup,Add regression test" \
  --priority critical
```

### 3. Refactoring

```bash
python scripts/run_orchestrator.py \
  --task "Refactor legacy payment module" \
  --requirements "Extract constants,Add type hints,Split large functions,Maintain API" \
  --priority medium
```

### 4. Code Review

```bash
python scripts/run_orchestrator.py \
  --task "Review and improve error handling in API endpoints" \
  --requirements "Add try-except blocks,Log errors properly,Return proper status codes" \
  --priority low
```

---

*Dernière mise à jour: 2025-12-02*
*KnowWhere Agent System v1.0*
