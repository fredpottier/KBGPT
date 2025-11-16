# Chemin Critique vers Validation Concept - OSMOSE Phase 1.5

**Date**: 2025-10-15
**Objectif**: Valider que l'approche Graph + Embeddings résout le problème d'extraction peu intelligente SANS LLM excessif

---

## 🎯 Question Centrale à Valider

**"Est-ce que notre approche (Graph Centrality + Embeddings Contextual) permet d'extraire intelligemment les entités pertinentes et de distinguer les produits principaux des concurrents, SANS recours excessif aux LLM?"**

**Success criteria**:
1. ✅ Document RFP typique (SAP S/4HANA + Oracle + Workday) ingesté
2. ✅ SAP S/4HANA classifié PRIMARY → promu dans Neo4j
3. ✅ Oracle/Workday classifiés COMPETITOR → rejetés
4. ✅ Latence acceptable (<500ms pour filtrage contextuel)
5. ✅ $0 coût supplémentaire (pas d'appels LLM externes)

---

## ✅ CE QUI EST DÉJÀ IMPLÉMENTÉ (Ready to Test)

### Composants Principaux (Jours 7-9) ✅ COMPLET

| Composant | Status | Impact | Fichier |
|-----------|--------|--------|---------|
| **GraphCentralityScorer** | ✅ IMPLÉMENTÉ | Structure du document (TF-IDF, Centrality, Salience) | `graph_centrality_scorer.py` (350 lignes) |
| **EmbeddingsContextualScorer** | ✅ IMPLÉMENTÉ | Sémantique contextuelle (60 paraphrases multilingues) | `embeddings_contextual_scorer.py` (420 lignes) |
| **Cascade Hybride** | ✅ IMPLÉMENTÉ | Graph → Embeddings → Ajustement confidence | `gatekeeper.py` (160 lignes modifiées) |

**Impact attendu**: +30% précision, $0 coût, <300ms latence

---

## 🔴 CE QUI MANQUE POUR VALIDER LE CONCEPT

### Phase Critique 1: Transmission `full_text` (BLOQUEUR)

**Durée**: ⏱️ **2-3 heures**

**Pourquoi c'est bloqueur**: Sans le texte complet, les scorers Graph et Embeddings **ne peuvent pas analyser le contexte** → cascade inactive → extraction reste "peu intelligente"

**Ce qu'il faut faire** (3 modifications simples):

#### 1.1. Modifier `AgentState` (1 ligne)

```python
# Fichier: src/knowbase/agents/base.py

class AgentState(BaseModel):
    """État partagé entre agents (passé via FSM)."""
    document_id: str
    tenant_id: str = "default"
    full_text: Optional[str] = None  # ← AJOUTER CETTE LIGNE

    # Budget tracking
    budget_remaining: Dict[str, int] = Field(default_factory=lambda: {
        "SMALL": 120,
        "BIG": 8,
        "VISION": 2
    })
    # ... reste inchangé
```

#### 1.2. Stocker `full_text` dans `osmose_agentique.py` (1 ligne)

```python
# Fichier: src/knowbase/ingestion/osmose_agentique.py
# Ligne ~189

initial_state = AgentState(
    document_id=document_id,
    tenant_id=tenant,
    full_text=text_content  # ← AJOUTER CETTE LIGNE
)
```

#### 1.3. Transmettre `full_text` dans `gatekeeper.py` (1 ligne)

```python
# Fichier: src/knowbase/agents/gatekeeper/gatekeeper.py
# Dans execute(), ligne ~195

gate_input = GateCheckInput(
    candidates=state.candidates,
    profile_name=profile_name,
    full_text=state.full_text  # ← AJOUTER CETTE LIGNE
)
```

**Validation**:
- Tests unitaires passent
- Log confirme: `[GATEKEEPER:GateCheck] Applying contextual filtering (graph=ON, embeddings=ON)`

---

### Phase Critique 2: Environnement + Worker (NÉCESSAIRE)

**Durée**: ⏱️ **1-2 heures**

**Pourquoi c'est nécessaire**: Le worker Docker n'a pas les dépendances et le nouveau code n'est pas chargé

**Ce qu'il faut faire**:

#### 2.1. Installer dépendances manquantes

```bash
# Option A: Via docker-compose exec
docker-compose exec ingestion-worker pip install sentence-transformers networkx

# Option B: Modifier requirements.txt et rebuild
echo "sentence-transformers==2.2.2" >> requirements.txt
echo "networkx==3.1" >> requirements.txt
docker-compose build ingestion-worker
```

#### 2.2. Redémarrer worker

```bash
docker-compose restart ingestion-worker
```

#### 2.3. Vérifier logs de démarrage

```bash
docker-compose logs -f ingestion-worker | grep "GATEKEEPER\|GraphCentrality\|Embeddings"
```

**Logs attendus**:
```
[GATEKEEPER] GraphCentralityScorer initialisé
[GATEKEEPER] EmbeddingsContextualScorer initialisé
[GATEKEEPER] Initialized with default profile 'BALANCED' (contextual_filtering=ON)
```

**Validation**:
- Scorers initialisés sans erreur
- Logs confirment `contextual_filtering=ON`

---

### Phase Critique 3: Test de Validation du Concept

**Durée**: ⏱️ **1-2 heures**

**Pourquoi c'est critique**: C'est le test qui valide (ou invalide) tout le concept

**Ce qu'il faut faire**:

#### 3.1. Préparer document de test

**Créer**: `data/docs_in/test_validation_concept.txt`

```text
Request for Proposal: Enterprise ERP System

Our organization seeks a modern ERP solution to replace our legacy systems.
We are evaluating SAP S/4HANA Cloud as our primary candidate.

SAP S/4HANA Cloud is a comprehensive enterprise resource planning system that offers:
- Real-time analytics and reporting
- Cloud-native architecture for scalability
- Seamless integration with existing SAP systems

We have also considered alternatives such as Oracle ERP Cloud and Workday.
While both Oracle ERP Cloud and Workday provide competitive offerings,
SAP S/4HANA Cloud aligns better with our existing infrastructure.

Key differentiators of SAP S/4HANA Cloud:
1. Advanced ERP capabilities tailored to our industry
2. Proven track record in similar enterprises
3. Superior technical support and training programs

Based on our comprehensive evaluation, SAP S/4HANA Cloud is our recommended solution.
Oracle ERP Cloud and Workday were mentioned for comparison purposes only.
```

#### 3.2. Ingérer document via worker

```bash
# Copier document dans docs_in
cp test_validation_concept.txt data/docs_in/

# Le worker devrait détecter automatiquement et traiter
# Sinon, déclencher manuellement via API ou interface
```

#### 3.3. Surveiller logs en temps réel

```bash
# Terminal 1: Logs worker
docker-compose logs -f ingestion-worker | grep "OSMOSE\|GATEKEEPER"

# Terminal 2: Logs Neo4j (si disponible)
docker-compose logs -f knowbase-neo4j
```

**Logs attendus (SUCCESS)**:
```
[OSMOSE AGENTIQUE] Processing document test_validation_concept (1234 chars) with SupervisorAgent FSM
[GATEKEEPER:GateCheck] Applying contextual filtering (graph=ON, embeddings=ON)
[GATEKEEPER:GateCheck] GraphCentralityScorer applied (3 candidates)
[GATEKEEPER:GateCheck] EmbeddingsContextualScorer applied (3 candidates)
[GATEKEEPER:GateCheck] PRIMARY boost: SAP S/4HANA Cloud 0.95 → 1.0
[GATEKEEPER:GateCheck] COMPETITOR penalty: Oracle ERP Cloud 0.90 → 0.75
[GATEKEEPER:GateCheck] COMPETITOR penalty: Workday 0.88 → 0.73
[GATEKEEPER:GateCheck] 1 promoted, 2 rejected, promotion_rate=33%
[GATEKEEPER:PromoteConcepts] Promoted 'SAP S/4HANA Cloud' (tenant=default, quality=1.00)
```

#### 3.4. Vérifier Neo4j Published-KG

**Option A: Via Cypher-shell**
```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
  AND c.created_at > datetime() - duration('PT1H')
RETURN c.canonical_name, c.concept_type, c.quality_score
ORDER BY c.created_at DESC
LIMIT 10
"
```

**Résultat attendu (SUCCESS)**:
```
canonical_name         concept_type  quality_score
SAP S/4HANA Cloud     Product       1.00
```

**Résultat NON attendu (FAILURE - concept pas validé)**:
```
SAP S/4HANA Cloud     Product       1.00
Oracle ERP Cloud      Product       0.75
Workday               Product       0.73
```

**Option B: Via Neo4j Browser**
- URL: http://localhost:7474
- Query: `MATCH (c:CanonicalConcept {tenant_id: 'default'}) RETURN c ORDER BY c.created_at DESC LIMIT 10`

---

## 📊 Checklist de Validation du Concept

### ✅ Validation RÉUSSIE si:

- [ ] **1. Ingestion complète** (pas d'erreur logs)
- [ ] **2. Cascade hybride active** (logs montrent Graph + Embeddings)
- [ ] **3. SAP S/4HANA classifié PRIMARY** (boost +0.12 dans logs)
- [ ] **4. Oracle/Workday classifiés COMPETITOR** (penalty -0.15 dans logs)
- [ ] **5. SAP S/4HANA promu dans Neo4j** (seul concept dans Published-KG)
- [ ] **6. Oracle/Workday rejetés** (absents de Published-KG)
- [ ] **7. Latence acceptable** (<500ms pour filtrage contextuel selon logs)
- [ ] **8. Coût nul** (aucun appel API externe dans logs)

**Si ces 8 critères sont OK** → ✅ **CONCEPT VALIDÉ**

### ❌ Validation ÉCHOUÉE si:

- [ ] Oracle/Workday également promus dans Neo4j (problème pas résolu)
- [ ] Cascade hybride inactive (pas de logs Graph/Embeddings)
- [ ] Erreurs lors de l'ingestion
- [ ] Latence excessive (>1s pour filtrage)

**Si échec** → Analyser logs, identifier cause, ajuster, re-tester

---

## ⏱️ Timeline Complète vers Validation

| Phase | Durée | Bloqueur? | Description |
|-------|-------|-----------|-------------|
| **Phase 1: Transmission `full_text`** | 2-3h | ✅ **OUI** | 3 modifications simples |
| **Phase 2: Environnement + Worker** | 1-2h | ✅ **OUI** | Install deps + restart |
| **Phase 3: Test Validation** | 1-2h | ❌ Non | Préparer doc + ingérer + vérifier |
| **TOTAL** | **4-7h** | - | **Demi-journée à 1 journée** |

---

## 🎯 Plan d'Action Minimal pour Validation

### Aujourd'hui (Priorité Absolue)

**Matin (3-4h)**:
1. ✅ Phase 1: Transmission `full_text` (2-3h)
   - Modifier AgentState
   - Modifier osmose_agentique.py
   - Modifier gatekeeper.py
   - Commit + tests

2. ✅ Phase 2: Environnement (1-2h)
   - Install sentence-transformers + networkx
   - Restart worker
   - Vérifier logs init

**Après-midi (1-2h)**:
3. ✅ Phase 3: Test validation (1-2h)
   - Préparer document test
   - Ingérer
   - Vérifier logs + Neo4j
   - **Verdict: CONCEPT VALIDÉ ou pas**

---

## 🚀 Alternative: Test Local (si Docker instable)

Si tu veux **valider le concept IMMÉDIATEMENT** sans attendre Docker:

```python
# Script: scripts/test_concept_validation_local.py

from knowbase.agents.gatekeeper.gatekeeper import GatekeeperDelegate, GateCheckInput

# Document test
document = """
Notre solution SAP S/4HANA Cloud répond à vos besoins ERP.
SAP S/4HANA Cloud offre des capacités avancées.

Les concurrents Oracle ERP Cloud et Workday proposent des alternatives.
Bien qu'Oracle et Workday soient mentionnés, SAP S/4HANA Cloud est recommandé.
"""

# Candidats (simulant extraction NER)
candidates = [
    {
        "name": "SAP S/4HANA Cloud",
        "type": "Product",
        "definition": "Enterprise ERP solution",
        "confidence": 0.92,
        "text": "SAP S/4HANA Cloud"
    },
    {
        "name": "Oracle ERP Cloud",
        "type": "Product",
        "definition": "Alternative ERP",
        "confidence": 0.88,
        "text": "Oracle ERP Cloud"
    },
    {
        "name": "Workday",
        "type": "Product",
        "definition": "Competing ERP",
        "confidence": 0.86,
        "text": "Workday"
    }
]

# AVANT: Sans cascade (baseline)
print("\n=== BASELINE (sans cascade) ===")
gatekeeper_baseline = GatekeeperDelegate(config={"enable_contextual_filtering": False})
baseline_input = GateCheckInput(candidates=candidates.copy(), profile_name="BALANCED")
baseline_result = gatekeeper_baseline._gate_check_tool(baseline_input)
print(f"Promoted: {[c['name'] for c in baseline_result.data['promoted']]}")
print(f"Rejected: {[c['name'] for c in baseline_result.data['rejected']]}")

# APRÈS: Avec cascade (notre concept)
print("\n=== AVEC CASCADE HYBRIDE (notre concept) ===")
gatekeeper_cascade = GatekeeperDelegate(config={"enable_contextual_filtering": True})
cascade_input = GateCheckInput(candidates=candidates.copy(), profile_name="BALANCED", full_text=document)
cascade_result = gatekeeper_cascade._gate_check_tool(cascade_input)
print(f"Promoted: {[c['name'] for c in cascade_result.data['promoted']]}")
print(f"Rejected: {[c['name'] for c in cascade_result.data['rejected']]}")

# VERDICT
promoted_names = [c['name'] for c in cascade_result.data['promoted']]
if "SAP S/4HANA Cloud" in promoted_names and "Oracle ERP Cloud" not in promoted_names:
    print("\n✅ CONCEPT VALIDÉ: SAP promu, Oracle rejeté")
else:
    print("\n❌ CONCEPT NON VALIDÉ: Besoin d'ajustements")
```

**Exécution**:
```bash
python scripts/test_concept_validation_local.py
```

**Résultat attendu**:
```
=== BASELINE (sans cascade) ===
Promoted: ['SAP S/4HANA Cloud', 'Oracle ERP Cloud', 'Workday']
Rejected: []

=== AVEC CASCADE HYBRIDE (notre concept) ===
[GATEKEEPER:GateCheck] Applying contextual filtering (graph=ON, embeddings=ON)
[GATEKEEPER:GateCheck] PRIMARY boost: SAP S/4HANA Cloud 0.92 → 1.0
[GATEKEEPER:GateCheck] COMPETITOR penalty: Oracle ERP Cloud 0.88 → 0.73
[GATEKEEPER:GateCheck] COMPETITOR penalty: Workday 0.86 → 0.71
Promoted: ['SAP S/4HANA Cloud']
Rejected: ['Oracle ERP Cloud', 'Workday']

✅ CONCEPT VALIDÉ: SAP promu, Oracle rejeté
```

---

## 📝 Résumé Ultra-Compact

### Qu'est-ce qui manque EXACTEMENT pour valider le concept?

**3 choses simples (4-7h total)**:

1. 🔴 **Ajouter `full_text` à AgentState et le transmettre** (2-3h)
   - 3 lignes de code à ajouter

2. 🟡 **Installer dépendances + redémarrer worker** (1-2h)
   - `pip install sentence-transformers networkx`
   - `docker-compose restart ingestion-worker`

3. 🟢 **Tester avec document RFP réel** (1-2h)
   - Ingérer document test
   - Vérifier logs + Neo4j
   - **Verdict: Validé ou pas**

### Tout le reste (Phase 4 bis) est OPTIONNEL

Les améliorations documentées (calibration, fuzzy linking, etc.) sont des **optimisations** pour passer de 85% à 95%, mais **PAS nécessaires** pour valider que le concept fonctionne.

---

*Dernière mise à jour: 2025-10-15*
*Objectif: Validation Concept - Chemin Critique Identifié*
