# Adaptive Ontology - Status Implémentation

**Date** : 2025-10-17
**Commit** : `bdc2ccd`
**Statut** : Phases 1-2 COMPLÈTES ✅, Phase 3 EN COURS

---

## ✅ COMPLÉTÉ

### Phase 1: Setup Infrastructure AdaptiveOntology Neo4j

**Commit** : `bdc2ccd`

**Infrastructure Neo4j créée** :
```bash
# Vérifier status:
docker-compose exec app python -c "
from knowbase.common.clients.neo4j_client import get_neo4j_client
neo4j = get_neo4j_client(uri='bolt://neo4j:7687', user='neo4j', password='graphiti_neo4j_pass')
with neo4j.driver.session() as s:
    result = s.run('SHOW INDEXES')
    indexes = [r['name'] for r in result if 'adaptive_ontology' in r['name']]
    print(f'Indexes: {indexes}')
"
```

**Résultats attendus** :
```
Indexes: ['adaptive_ontology_domain', 'adaptive_ontology_tenant', 'adaptive_ontology_type', 'adaptive_ontology_unique_canonical']
```

**Fichiers créés** :
- ✅ `scripts/setup_adaptive_ontology.py` (150+ lignes)
- ✅ Schéma Neo4j (AdaptiveOntology node + indexes)

---

### Phase 2: LLMCanonicalizer + AdaptiveOntologyManager

**Commit** : `bdc2ccd`

**Fichiers créés** :
- ✅ `src/knowbase/ontology/llm_canonicalizer.py` (250 lignes)
  - Class `LLMCanonicalizer`
  - Class `CanonicalizationResult` (Pydantic)
  - Prompt système optimisé (100+ lignes)
  - Fallback gracieux si erreur LLM

- ✅ `src/knowbase/ontology/adaptive_ontology_manager.py` (200+ lignes)
  - Class `AdaptiveOntologyManager`
  - Methods: `lookup()`, `store()`, `add_alias()`, `increment_usage()`, `get_stats()`

**Test rapide** :
```bash
docker-compose exec app python -c "
from knowbase.ontology.llm_canonicalizer import LLMCanonicalizer
from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager
from knowbase.common.llm_router import get_llm_router
from knowbase.common.clients.neo4j_client import get_neo4j_client

# Init
llm_router = get_llm_router()
neo4j = get_neo4j_client(uri='bolt://neo4j:7687', user='neo4j', password='graphiti_neo4j_pass')
canonicalizer = LLMCanonicalizer(llm_router)
ontology = AdaptiveOntologyManager(neo4j)

# Test canonicalization
result = canonicalizer.canonicalize(
    raw_name=\"S/4HANA Cloud's\",
    context=\"Our public cloud ERP system\"
)
print(f'Canonical: {result.canonical_name}')
print(f'Confidence: {result.confidence}')

# Test store
ontology.store(
    tenant_id='default',
    canonical_name=result.canonical_name,
    raw_name=\"S/4HANA Cloud's\",
    canonicalization_result=result.model_dump()
)
print('✅ Stored in ontology')
"
```

---

## 🚧 EN COURS - Phase 3: Intégration Gatekeeper

**Status** : NON COMMENCÉ (code préparé mais non intégré)

**Objectif** : Modifier Gatekeeper pour utiliser LLM Canonicalizer au lieu de `.title()`

### Fichier à modifier

`src/knowbase/agents/gatekeeper/gatekeeper.py`

**Lignes critiques à remplacer** :
- Ligne 680 : `canonical_name = concept_name.strip().title()`
- Ligne 690 : `canonical_name = concept_name.strip().title()`
- Ligne 694 : `canonical_name = concept_name.strip().title()`

### Code d'intégration préparé

```python
# Dans GatekeeperAgent.__init__()
from knowbase.ontology.llm_canonicalizer import LLMCanonicalizer
from knowbase.ontology.adaptive_ontology_manager import AdaptiveOntologyManager
from knowbase.common.llm_router import get_llm_router

self.llm_router = get_llm_router()
self.llm_canonicalizer = LLMCanonicalizer(self.llm_router)
self.adaptive_ontology = AdaptiveOntologyManager(self.neo4j_client)

# Nouvelle méthode à ajouter
def _canonicalize_concept_name(
    self,
    raw_name: str,
    context: Optional[str] = None,
    tenant_id: str = "default"
) -> tuple[str, float]:
    """
    Canonicalise nom concept via Adaptive Ontology.

    Workflow:
    1. Lookup cache ontologie
    2. Si non trouvé → LLM canonicalization
    3. Store résultat dans ontologie

    Returns:
        (canonical_name, confidence)
    """

    # 1. Lookup cache ontologie
    cached = self.adaptive_ontology.lookup(raw_name, tenant_id)

    if cached:
        # Cache HIT
        logger.debug(
            f"[GATEKEEPER:Canonicalization] ✅ Cache HIT '{raw_name}' → '{cached['canonical_name']}' "
            f"(confidence={cached['confidence']:.2f}, source={cached['source']})"
        )

        # Incrémenter usage stats
        self.adaptive_ontology.increment_usage(cached["canonical_name"], tenant_id)

        return cached["canonical_name"], cached["confidence"]

    # 2. Cache MISS → LLM canonicalization
    logger.info(
        f"[GATEKEEPER:Canonicalization] 🔍 Cache MISS '{raw_name}', calling LLM canonicalizer..."
    )

    llm_result = self.llm_canonicalizer.canonicalize(
        raw_name=raw_name,
        context=context,
        domain_hint=None  # Auto-détection par LLM
    )

    logger.info(
        f"[GATEKEEPER:Canonicalization] ✅ LLM canonicalized '{raw_name}' → '{llm_result.canonical_name}' "
        f"(confidence={llm_result.confidence:.2f}, type={llm_result.concept_type})"
    )

    # 3. Store dans ontologie adaptive
    self.adaptive_ontology.store(
        tenant_id=tenant_id,
        canonical_name=llm_result.canonical_name,
        raw_name=raw_name,
        canonicalization_result=llm_result.model_dump(),
        context=context
    )

    return llm_result.canonical_name, llm_result.confidence


# Dans _promote_concepts_tool(), REMPLACER:
canonical_name = concept_name.strip().title()

# PAR:
canonical_name, confidence = self._canonicalize_concept_name(
    raw_name=concept_name,
    context=full_text,  # Passer contexte complet du document
    tenant_id=tenant_id
)
```

### Actions requises

1. **Ajouter imports** dans `gatekeeper.py`
2. **Modifier `__init__()`** pour initialiser canonicalizer + ontology
3. **Ajouter méthode `_canonicalize_concept_name()`**
4. **Remplacer 3 occurrences `.title()`** par appel à `_canonicalize_concept_name()`

---

## ⏳ À FAIRE - Phase 4: Tests Validation

**Objectif** : Valider bout-en-bout avec document réel

### Plan de test

1. **Rebuild worker** :
```bash
docker-compose build ingestion-worker
docker-compose restart ingestion-worker
```

2. **Purger données** :
```bash
# Purger Redis
docker-compose exec redis redis-cli FLUSHALL

# Purger Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass "
MATCH (n) WHERE n.tenant_id = 'default' DETACH DELETE n
"
```

3. **Import document test** :
- Via frontend : http://localhost:3000/documents/import
- Uploader PPTX SAP contenant variations : "S/4HANA Cloud's", "SAP ERP", etc.

4. **Vérifier logs** :
```bash
docker-compose logs ingestion-worker --tail=100 | grep "LLMCanonicalizer\|AdaptiveOntology"
```

**Logs attendus** :
```
[LLMCanonicalizer] Canonicalizing 'S/4HANA Cloud's'
[LLMCanonicalizer] ✅ 'S/4HANA Cloud's' → 'SAP S/4HANA Cloud, Public Edition'
[AdaptiveOntology:Store] Created ontology entry 'SAP S/4HANA Cloud, Public Edition'
```

5. **Vérifier Neo4j** :
```cypher
// Canonical concepts unifiés
MATCH (c:CanonicalConcept {tenant_id: 'default'})
WHERE c.canonical_name CONTAINS 'S/4'
RETURN c.canonical_name, c.surface_form

// Expected: UN SEUL concept canonical_name, multiples surface_forms

// Ontologie adaptive
MATCH (o:AdaptiveOntology {tenant_id: 'default'})
RETURN o.canonical_name, o.aliases, o.usage_count
ORDER BY o.usage_count DESC
```

6. **Tester 2ème document** (cache hit) :
- Importer AUTRE document avec mêmes concepts
- Logs attendus : `[AdaptiveOntology:Lookup] ✅ Cache HIT`
- Coût LLM : $0 (pas d'appel, cache utilisé)

---

## 📊 Métriques Attendues

### Premier Document (Cache vide)
- **Concepts extraits** : ~15-30
- **Appels LLM** : 15-30 (tous nouveaux)
- **Coût** : ~$0.002-$0.003
- **Cache hit rate** : 0%
- **AdaptiveOntology entries** : 15-30

### Deuxième Document (Cache warm)
- **Concepts extraits** : ~20
- **Appels LLM** : ~3-8 (seulement nouveaux termes)
- **Coût** : ~$0.0003-$0.0008
- **Cache hit rate** : ~60-75%
- **AdaptiveOntology entries** : 18-35 (enrichissement)

### Dixième Document (Cache mature)
- **Concepts extraits** : ~20
- **Appels LLM** : ~0-2
- **Coût** : ~$0.00-$0.0002
- **Cache hit rate** : ~90-95%
- **AdaptiveOntology entries** : 30-50

---

## 🐛 Problèmes Connus

### Issue 1: Gatekeeper non modifié

**Status** : Lignes 680/690/694 utilisent encore `.title()`

**Impact** : Canonicalization LLM pas utilisée dans production

**Fix** : Appliquer intégration Phase 3 (voir code ci-dessus)

---

## 📝 Notes Importantes

### Documentation complète

`doc/ongoing/ADAPTIVE_ONTOLOGY_CANONICALIZATION.md` (1,110 lignes)
- Architecture détaillée
- Schéma Neo4j complet
- Code d'intégration Gatekeeper
- Cas d'usage réels
- Métriques et KPIs

### Commits

- `7a365a3` : docs: Architecture LLM Canonicalizer + Adaptive Ontology
- `bfbf0db` : fix(neo4j): Corriger bug UNWIND liste vide dans promote_to_published
- `bdc2ccd` : feat(ontology): Implémenter LLM Canonicalizer + Adaptive Ontology (Phases 1-2)

---

## 🎯 Prochaine Session - Quick Start

```bash
# 1. Vérifier infrastructure Neo4j
docker-compose exec app python -c "
from knowbase.common.clients.neo4j_client import get_neo4j_client
neo4j = get_neo4j_client(uri='bolt://neo4j:7687', user='neo4j', password='graphiti_neo4j_pass')
with neo4j.driver.session() as s:
    result = s.run('SHOW INDEXES')
    indexes = [r['name'] for r in result if 'adaptive_ontology' in r['name']]
    print('✅ Indexes:', indexes)
"

# 2. Intégrer Gatekeeper (Phase 3)
# → Voir code ci-dessus dans section "Code d'intégration préparé"

# 3. Rebuild + test
docker-compose build ingestion-worker
docker-compose restart ingestion-worker

# 4. Import document test
# → http://localhost:3000/documents/import
```

**Dernière mise à jour** : 2025-10-17 12:00 UTC
