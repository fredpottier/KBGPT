# Analyse Gap: Canonicalisation P0/P1 - Système Agentique

**Date:** 2025-10-16
**Phase:** OSMOSE Phase 1.5 - Canonicalisation Robuste
**Statut:** ⚠️ GAP IDENTIFIÉ - Fonctionnalités implémentées mais non intégrées

---

## 📋 Résumé Exécutif

### Constat Principal

✅ **BONNE NOUVELLE**: Toutes les fonctionnalités P0 et P1 décrites dans `PLAN_IMPLEMENTATION_CANONICALISATION.md` **SONT IMPLÉMENTÉES** et **OPÉRATIONNELLES**.

❌ **PROBLÈME**: Ces fonctionnalités ne sont **PAS UTILISÉES** par le système agentique actuel (Gatekeeper).

🔧 **SOLUTION**: Intégrer les composants existants dans `GatekeeperDelegate._promote_concepts_tool()` (ligne 596).

---

## 🔍 Analyse Détaillée P0

### P0.1 - Sandbox Auto-Learning

#### ✅ Implémentation Existante

**Fichier:** `src/knowbase/ontology/entity_normalizer_neo4j.py` (lignes 81-100)

```python
# P0.1 Sandbox: Filtrer entités pending par défaut
if not include_pending:
    where_clauses.append("ont.status != 'auto_learned_pending'")
    logger.debug(
        f"[ONTOLOGY:Sandbox] Filtering pending entities for '{raw_name}' "
        f"(include_pending={include_pending})"
    )
```

**Statut Neo4j:**
- ✅ Enum `OntologyStatus.AUTO_LEARNED_PENDING` défini (`neo4j_schema.py` ligne 33)
- ✅ Index sur `status` créé pour filtrage efficace
- ✅ `OntologySaver` avec auto-validation (confidence ≥ 0.95) → `auto_learned_validated`

#### ❌ Gap Actuel

**Localisation:** `gatekeeper.py` ligne 596

```python
# ❌ CANONICALISATION NAÏVE ACTUELLE
canonical_name = concept_name.strip().title()
```

**Problème:** `EntityNormalizerNeo4j` est **importé** (ligne 27) mais **jamais appelé**.

**Impact:**
- Les entités pending ne sont pas filtrées
- Pas de lookup dans l'ontologie Neo4j
- Doublons créés pour entités SAP connues (ex: "Sap" au lieu de "SAP S/4HANA Cloud")

---

### P0.2 - Rollback Mechanism

#### ✅ Implémentation Existante

**Fichier:** `src/knowbase/api/routers/ontology_admin.py` (lignes 110-165)

```python
@router.post("/deprecate", response_model=DeprecateEntityResponse)
async def deprecate_entity(
    request: DeprecateEntityRequest,
    driver: GraphDatabase.driver = Depends(get_neo4j_driver)
):
    """
    Déprécier entité ontologie et migrer vers nouvelle (P0.2 Rollback).

    Algorithme:
    1. Marquer ancienne entité status='deprecated'
    2. Rediriger CanonicalConcept utilisant ancienne vers nouvelle
    3. Enregistrer metadata (raison, admin, timestamp)
    """
```

**Fichier:** `src/knowbase/ontology/neo4j_schema.py`

- ✅ Fonction `deprecate_ontology_entity()` (ligne 250+)
- ✅ Enum `DeprecationReason` (4 cas: DUPLICATE, INCORRECT_FUSION, BETTER_MATCH, ADMIN_DECISION)
- ✅ Metadata: `deprecated_at`, `deprecated_by`, `new_entity_id`, `deprecation_reason`

#### ✅ Gap: AUCUN

**Statut:** P0.2 est **100% fonctionnel** et **accessible via API admin**.

**Endpoints:**
- `POST /admin/ontology/deprecate` - Déprécier entité et migrer
- `GET /admin/ontology/deprecated` - Liste entités dépréciées
- `GET /admin/ontology/pending` - Liste entités en attente validation

**Note:** Ce composant est **indépendant** du Gatekeeper (workflow admin post-import). Pas d'intégration nécessaire.

---

### P0.3 - Decision Trace

#### ✅ Implémentation Existante

**Fichier:** `src/knowbase/ontology/decision_trace.py` (191 lignes)

**Composants:**
- ✅ Classe `DecisionTrace` (Pydantic model complet)
- ✅ Classe `StrategyResult` (résultat par stratégie)
- ✅ Enum `NormalizationStrategy` (5 stratégies)
- ✅ Factory `create_decision_trace()`
- ✅ Serialization JSON pour Neo4j (`to_json_string()`)

**Fichier:** `neo4j_client.py`

```python
def promote_to_published(
    self,
    tenant_id: str,
    proto_concept_id: str,
    canonical_name: str,
    unified_definition: str,
    quality_score: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
    decision_trace_json: Optional[str] = None,  # ✅ P0.3
    surface_form: Optional[str] = None,
    deduplicate: bool = True
) -> str:
```

#### ⚠️ Gap Partiel

**Gatekeeper actuel (lignes 636-673):**

```python
# ✅ DecisionTrace CRÉÉ
decision_trace = create_decision_trace(
    raw_name=concept_name,
    entity_type_hint=concept_type,
    tenant_id=tenant_id,
    document_id=concept.get("document_id"),
    segment_id=concept.get("segment_id")
)

# ⚠️ MAIS: Seulement stratégie HEURISTIC_RULES enregistrée
decision_trace.add_strategy_result(StrategyResult(
    strategy=NormalizationStrategy.HEURISTIC_RULES,  # ← Unique stratégie
    attempted=True,
    success=True,
    canonical_name=canonical_name,  # ← Nom naïf .strip().title()
    confidence=confidence,
    execution_time_ms=0.0,
    metadata={...}
))

# ✅ Trace stockée dans Neo4j
decision_trace_json = decision_trace.to_json_string()
# ...
canonical_id = self.neo4j_client.promote_to_published(
    # ...
    decision_trace_json=decision_trace_json,  # ✅ Persisted
)
```

**Problème:**
- ✅ Infrastructure P0.3 opérationnelle
- ❌ **Mais**: Pas de trace des stratégies réelles (ontology lookup, fuzzy, LLM)
- ❌ DecisionTrace ne reflète pas le workflow cascade décrit dans `STRATEGIE_CANONICALISATION_AUTO_APPRENTISSAGE.md`

**Impact:**
- Audit partiel (trace existe mais incomplète)
- Impossible de débugger pourquoi "sap s/4hana" → "Sap S/4Hana" au lieu de "SAP S/4HANA Cloud"

---

## 🔍 Analyse Détaillée P1

### P1.1 - Adaptive Thresholds

#### ✅ Implémentation Existante

**Fichier:** `src/knowbase/ontology/adaptive_thresholds.py` (364 lignes)

**Composants:**
- ✅ Classe `AdaptiveThresholdSelector` (sélection intelligente de profil)
- ✅ 6 profils prédéfinis:
  - `SAP_OFFICIAL_DOCS` (fuzzy=0.90, auto_validation=0.95)
  - `SAP_PRODUCTS_CATALOG` (fuzzy=0.92, auto_validation=0.98)
  - `INTERNAL_DOCS` (fuzzy=0.85, auto_validation=0.95)
  - `COMMUNITY_CONTENT` (fuzzy=0.80, auto_validation=0.97)
  - `MULTILINGUAL_TECHNICAL` (fuzzy=0.82, auto_validation=0.95)
  - `DEFAULT` (fuzzy=0.85, auto_validation=0.95)
- ✅ Enums contextuels: `DomainContext`, `LanguageContext`, `SourceContext`, `EntityTypeContext`
- ✅ Méthode `select_profile()` avec algorithme de sélection par priorité

**Algorithme de sélection (lignes 210-282):**
```python
# Priorité 1: Produits SAP catalogués (très strict)
if domain == DomainContext.SAP_ECOSYSTEM and entity_type == EntityTypeContext.PRODUCT:
    return self.profiles["SAP_PRODUCTS_CATALOG"]

# Priorité 2: Documentation officielle SAP (haute confiance)
if domain == DomainContext.SAP_ECOSYSTEM and source == SourceContext.OFFICIAL_DOCUMENTATION:
    return self.profiles["SAP_OFFICIAL_DOCS"]

# ... etc
```

#### ❌ Gap Actuel

**Localisation:** `gatekeeper.py` - **AUCUNE UTILISATION**

**Recherche dans le code:**
```bash
grep -r "adaptive_thresholds" src/knowbase/agents/gatekeeper/
# Résultat: Aucun match
```

**Problème:**
- Module `adaptive_thresholds.py` **jamais importé** dans Gatekeeper
- Seuils hardcodés: `confidence >= 0.70` (ligne 567)
- Pas d'adaptation selon contexte document (SAP officiel vs forum)

**Impact:**
- Même seuil pour documentation SAP officielle (haute qualité) et forums (qualité variable)
- Faux positifs/négatifs selon source
- Pas d'ajustement auto selon domaine/langue

---

### P1.2 - Structural Similarity

#### ✅ Implémentation Existante

**Fichier:** `src/knowbase/ontology/structural_similarity.py` (442 lignes)

**Composants:**
- ✅ Fonction `enhanced_fuzzy_match()` (ligne 360-428) - Matching hybride textuel + structurel
- ✅ Fonction `compute_structural_similarity()` (ligne 254-323) - Score agrégé 4 dimensions
- ✅ Extraction acronymes: `extract_acronyms()` (ligne 60-98)
- ✅ Extraction composants: `extract_components()` (ligne 101-127)
- ✅ Normalisation typo: `normalize_typography()` (ligne 130-152)
- ✅ Strip affixes: `strip_optional_affixes()` (ligne 155-183)
- ✅ Patterns SAP: `StructuralPattern.SAP_ACRONYMS` (S/4HANA, SuccessFactors, etc.)

**Exemple de matching structurel:**
```python
# "SAP S/4HANA Cloud" vs "S4H Cloud"
is_match, score, method = enhanced_fuzzy_match(
    "SAP S/4HANA Cloud",
    "S4H Cloud",
    textual_threshold=0.85,
    structural_threshold=0.75
)
# Résultat: (True, 0.80, "structural")
# - Textual: 0.60 (trop faible)
# - Structural: 0.80 (acronyme S4H match, composant "Cloud" match)
```

#### ✅ Utilisé par `EntityNormalizerNeo4j`

**Fichier:** `entity_normalizer_neo4j.py` (ligne 18)

```python
from knowbase.ontology.structural_similarity import enhanced_fuzzy_match
```

**Utilisation (ligne 290-309):**
```python
# P1.2: Fallback matching structurel
for candidate in candidates:
    canonical_name = candidate["canonical_name"]

    is_match, score, method = enhanced_fuzzy_match(
        raw_name,
        canonical_name,
        textual_threshold=0.85,
        structural_threshold=0.75
    )

    if is_match and score > best_score:
        best_score = score
        best_match = (candidate["entity_id"], canonical_name, candidate["entity_type"], score)
```

#### ❌ Gap Actuel

**Problème:** `EntityNormalizerNeo4j` **utilise** `enhanced_fuzzy_match()`, **MAIS** Gatekeeper **n'appelle jamais** `EntityNormalizerNeo4j`.

**Workflow actuel:**
```
Gatekeeper → canonical_name = concept_name.strip().title()  ❌ NAÏF
```

**Workflow attendu:**
```
Gatekeeper → EntityNormalizerNeo4j.normalize_entity_name()
          → enhanced_fuzzy_match() (si exact match échoue)
          → Structural similarity matching  ✅
```

**Impact:**
- "SAP S/4HANA" ≠ "S4H" (alors qu'ils devraient matcher)
- "SuccessFactors" ≠ "SF" (acronyme SAP connu non reconnu)
- Doublons créés pour variantes structurelles

---

### P1.3 - Surface/Canonical Separation

#### ✅ Implémentation Existante

**Fichier:** `neo4j_client.py` (ligne 320)

```python
def promote_to_published(
    self,
    tenant_id: str,
    proto_concept_id: str,
    canonical_name: str,
    unified_definition: str,
    quality_score: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
    decision_trace_json: Optional[str] = None,
    surface_form: Optional[str] = None,  # ✅ P1.3
    deduplicate: bool = True
) -> str:
```

**Cypher Query (ligne 433):**
```cypher
CREATE (canonical:CanonicalConcept {
    canonical_id: $canonical_id,
    canonical_name: $canonical_name,  # Nom normalisé
    surface_form: $surface_form,      # Nom brut extrait (P1.3)
    # ...
})
```

#### ✅ Utilisé par Gatekeeper

**Fichier:** `gatekeeper.py` (ligne 688)

```python
canonical_id = self.neo4j_client.promote_to_published(
    tenant_id=tenant_id,
    proto_concept_id=proto_concept_id,
    canonical_name=canonical_name,  # ← Naïf .strip().title()
    unified_definition=unified_definition,
    quality_score=quality_score,
    metadata={...},
    decision_trace_json=decision_trace_json,
    surface_form=concept_name  # ✅ P1.3: Préservé
)
```

#### ⚠️ Gap Partiel

**Problème:**
- ✅ `surface_form` **stocké** correctement dans Neo4j
- ❌ **Mais**: `canonical_name` est naïf (`.strip().title()`)
- ❌ Devrait être: `canonical_name` = résultat d'`EntityNormalizerNeo4j`

**Exemple actuel:**
```python
concept_name = "sap s/4hana cloud"
canonical_name = "Sap S/4Hana Cloud"  # ❌ Naïf
surface_form = "sap s/4hana cloud"    # ✅ Préservé
```

**Exemple attendu:**
```python
concept_name = "sap s/4hana cloud"
canonical_name = "SAP S/4HANA Cloud"  # ✅ Normalisé via ontologie
surface_form = "sap s/4hana cloud"    # ✅ Préservé
```

---

## 📊 Tableau Récapitulatif

| Composant | Implémenté | Testé | Utilisé par Gatekeeper | Gap |
|-----------|-----------|-------|------------------------|-----|
| **P0.1 - Sandbox Auto-Learning** | ✅ | ✅ | ❌ | `EntityNormalizerNeo4j` pas appelé |
| **P0.2 - Rollback Mechanism** | ✅ | ✅ | N/A | ✅ API admin fonctionnelle |
| **P0.3 - Decision Trace** | ✅ | ✅ | ⚠️ | Infrastructure OK, mais traces incomplètes |
| **P1.1 - Adaptive Thresholds** | ✅ | ✅ | ❌ | Module jamais importé |
| **P1.2 - Structural Similarity** | ✅ | ✅ | ❌ | `enhanced_fuzzy_match()` pas utilisé |
| **P1.3 - Surface/Canonical** | ✅ | ✅ | ⚠️ | `surface_form` OK, mais `canonical_name` naïf |

---

## 🔧 Localisation du Code à Modifier

### Fichier Unique: `gatekeeper.py`

**Ligne critique: 596**

```python
# ❌ ACTUEL - Canonicalisation naïve
canonical_name = concept_name.strip().title()
```

**✅ À REMPLACER PAR:**

```python
# ✅ P0.1 + P1.1 + P1.2: Canonicalisation cascade intelligente
entity_id, canonical_name, entity_type, is_cataloged = self.entity_normalizer.normalize_entity_name(
    raw_name=concept_name,
    entity_type_hint=concept_type,
    tenant_id=tenant_id,
    include_pending=False  # P0.1 Sandbox
)

# Si non trouvé dans ontologie, fallback heuristique
if not is_cataloged:
    canonical_name = concept_name.strip().title()
```

---

## 🛠️ Modifications Nécessaires

### 1. Initialiser `EntityNormalizerNeo4j` dans Gatekeeper

**Fichier:** `gatekeeper.py`

**Ligne 27:** ✅ Import déjà présent
```python
from knowbase.ontology.entity_normalizer_neo4j import EntityNormalizerNeo4j
```

**Ajouter dans `__init__()` (après ligne 95):**

```python
def __init__(self, config: Optional[Dict[str, Any]] = None):
    super().__init__(AgentRole.GATEKEEPER, config)

    # ... code existant ...

    # P0.1 + P1.2: Initialiser EntityNormalizerNeo4j
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    neo4j_client = get_neo4j_client()
    self.entity_normalizer = EntityNormalizerNeo4j(neo4j_client.driver)

    logger.info(
        f"[GATEKEEPER] Initialized with EntityNormalizerNeo4j "
        f"(P0.1 Sandbox + P1.2 Structural Similarity enabled)"
    )
```

---

### 2. Remplacer Canonicalisation Naïve (ligne 596)

**Avant:**
```python
# Générer canonical_name (normalisé)
canonical_name = concept_name.strip().title()
```

**Après:**
```python
# P0.1 + P1.2: Normalisation via EntityNormalizerNeo4j (ontologie + fuzzy structurel)
entity_id, canonical_name, normalized_type, is_cataloged = self.entity_normalizer.normalize_entity_name(
    raw_name=concept_name,
    entity_type_hint=concept_type,
    tenant_id=tenant_id,
    include_pending=False  # P0.1 Sandbox: Exclure entités pending
)

# Fallback heuristique si non trouvé
if not is_cataloged:
    canonical_name = concept_name.strip().title()
    logger.debug(
        f"[GATEKEEPER:Canonicalization] Fallback heuristic for '{concept_name}' → '{canonical_name}' "
        f"(not found in ontology)"
    )
else:
    logger.info(
        f"[GATEKEEPER:Canonicalization] ✅ Normalized via ontology: '{concept_name}' → '{canonical_name}' "
        f"(entity_id={entity_id}, type={normalized_type})"
    )
```

---

### 3. Enrichir DecisionTrace avec Stratégies Réelles (ligne 636-673)

**Avant (P0.3 partiel):**
```python
# Ajouter stratégie HEURISTIC_RULES (gate check)
decision_trace.add_strategy_result(StrategyResult(
    strategy=NormalizationStrategy.HEURISTIC_RULES,  # ← Unique
    attempted=True,
    success=True,
    canonical_name=canonical_name,
    confidence=confidence,
    execution_time_ms=0.0,
    metadata={...}
))
```

**Après (P0.3 complet):**
```python
# P0.3: Enregistrer stratégie réellement utilisée
if is_cataloged:
    # Stratégie ONTOLOGY_LOOKUP réussie
    decision_trace.add_strategy_result(StrategyResult(
        strategy=NormalizationStrategy.ONTOLOGY_LOOKUP,
        attempted=True,
        success=True,
        canonical_name=canonical_name,
        confidence=1.0,  # Exact match ontologie
        execution_time_ms=0.0,
        metadata={
            "entity_id": entity_id,
            "normalized_type": normalized_type,
            "match_method": "ontology_exact_or_structural"
        }
    ))
else:
    # Fallback HEURISTIC_RULES
    decision_trace.add_strategy_result(StrategyResult(
        strategy=NormalizationStrategy.HEURISTIC_RULES,
        attempted=True,
        success=True,
        canonical_name=canonical_name,
        confidence=confidence,
        execution_time_ms=0.0,
        metadata={
            "fallback_reason": "not_in_ontology",
            "heuristic": "strip_title"
        }
    ))
```

---

### 4. (Optionnel) Intégrer P1.1 Adaptive Thresholds

**Ajouter import:**
```python
from knowbase.ontology.adaptive_thresholds import (
    AdaptiveThresholdSelector,
    DomainContext,
    SourceContext
)
```

**Utiliser dans gate check (ligne 567):**
```python
# Avant:
if concept.get("confidence", 0.0) < 0.70:  # ❌ Hardcodé
    continue

# Après:
# P1.1: Sélectionner seuil adaptatif selon contexte
threshold_selector = AdaptiveThresholdSelector()
promotion_threshold = threshold_selector.get_threshold(
    threshold_type="promotion",
    domain=DomainContext.SAP_ECOSYSTEM,  # À détecter dynamiquement
    source=SourceContext.INTERNAL_DOCUMENTATION,  # À détecter dynamiquement
    entity_type=EntityTypeContext.PRODUCT if concept_type == "PRODUCT" else None
)

if concept.get("confidence", 0.0) < promotion_threshold:
    logger.debug(
        f"[GATEKEEPER:GateCheck] Concept '{concept_name}' rejected: "
        f"confidence={confidence:.2f} < threshold={promotion_threshold:.2f} "
        f"(adaptive threshold for context)"
    )
    continue
```

---

## 🎯 Workflow Attendu (Après Intégration)

### Scénario 1: Produit SAP Connu

**Input:** `concept_name = "sap s/4hana cloud"`

**Workflow:**
1. **Gatekeeper** appelle `entity_normalizer.normalize_entity_name()`
2. **EntityNormalizerNeo4j** recherche dans ontologie:
   - Alias normalisé: `"sap s/4hana cloud"` → Match exact avec `OntologyAlias`
   - Trouvé: `entity_id = "S4HANA_CLOUD"`, `canonical_name = "SAP S/4HANA Cloud"`
3. **DecisionTrace** enregistre stratégie `ONTOLOGY_LOOKUP` (success=True, confidence=1.0)
4. **Gatekeeper** promeut avec:
   - `canonical_name = "SAP S/4HANA Cloud"` ✅
   - `surface_form = "sap s/4hana cloud"` ✅
   - `decision_trace_json` complet ✅

**Résultat Neo4j:**
```cypher
MATCH (c:CanonicalConcept {canonical_name: "SAP S/4HANA Cloud"})
RETURN c.canonical_name, c.surface_form, c.decision_trace_json
```

---

### Scénario 2: Variante Structurelle (Acronyme)

**Input:** `concept_name = "S4H Cloud"`

**Workflow:**
1. **Gatekeeper** appelle `entity_normalizer.normalize_entity_name()`
2. **EntityNormalizerNeo4j** recherche:
   - Exact match échoue
   - Fallback: `_try_structural_match()` (P1.2)
     - Acronyme détecté: `"S4H"` ∈ `["S4HANA", "S/4HANA", "S4H", "S/4"]`
     - Match structurel: `"S4H Cloud"` vs `"SAP S/4HANA Cloud"` → score=0.80
   - Trouvé: `canonical_name = "SAP S/4HANA Cloud"`
3. **DecisionTrace** enregistre:
   - Stratégie `ONTOLOGY_LOOKUP` (attempted=True, success=False)
   - Stratégie `FUZZY_MATCHING` (attempted=True, success=True, confidence=0.80, method="structural")
4. **Gatekeeper** promeut avec canonical correct ✅

---

### Scénario 3: Entité Non Cataloguée

**Input:** `concept_name = "Azure VNET"`

**Workflow:**
1. **Gatekeeper** appelle `entity_normalizer.normalize_entity_name()`
2. **EntityNormalizerNeo4j**:
   - Exact match échoue
   - Structural match échoue (aucun candidat Azure dans ontologie SAP)
   - Retour: `is_cataloged = False`, `canonical_name = "Azure VNET"` (raw)
3. **Gatekeeper** fallback heuristique: `canonical_name = "Azure Vnet"` (title)
4. **DecisionTrace** enregistre stratégie `HEURISTIC_RULES` (fallback)
5. **OntologySaver** (si activé) crée entité `status="auto_learned_pending"` pour review admin (P0.1)

---

## 📈 Impact Attendu

### Avant Intégration (Actuel)

```cypher
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
RETURN c.canonical_name AS name, count(*) AS count
ORDER BY count DESC

// Résultats:
| name                | count |
|---------------------|-------|
| Sap                 | 5     | ← DOUBLONS (5× le même concept)
| Sap S/4Hana         | 3     | ← Casse incorrecte
| S4Hana Cloud        | 2     | ← Préfixe SAP manquant
| Successfactors      | 4     | ← Casse incorrecte
```

### Après Intégration (Attendu)

```cypher
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
RETURN c.canonical_name AS name, count(*) AS count
ORDER BY count DESC

// Résultats:
| name                    | count |
|-------------------------|-------|
| SAP S/4HANA Cloud       | 1     | ← DÉDUPLIQUÉ + Nom canonique correct
| SAP SuccessFactors      | 1     | ← Nom canonique officiel
| SAP Ariba               | 1     | ← Préfixe SAP ajouté automatiquement
```

---

## ✅ Prochaines Étapes

1. ✅ **Analyser implémentation P0/P1** (fait)
2. ✅ **Documenter gap** (ce document)
3. ⏳ **Implémenter intégration dans Gatekeeper** (3 modifications simples)
4. ⏳ **Tester E2E** (import document → vérifier canonical names corrects)
5. ⏳ **Valider métriques Neo4j** (0 doublons, noms canoniques officiels)

---

## 📝 Conclusion

### Bilan

✅ **Tout le code P0 et P1 est déjà là** - Travail original bien fait!
❌ **Mais**: Code existant non connecté au système agentique actuel
🔧 **Solution**: 3 modifications simples dans `gatekeeper.py` (lignes 95, 596, 636-673)

### Temps Estimé

- ⏱️ **Modifications code**: 30 minutes
- ⏱️ **Tests unitaires**: 1 heure
- ⏱️ **Tests E2E**: 1 heure
- 🎯 **Total**: ~2.5 heures pour intégration complète

---

**Auteur:** Claude Code
**Date:** 2025-10-16
**Version:** 1.0
**Statut:** ⚠️ Gap Analysis Complete - Ready for Implementation
