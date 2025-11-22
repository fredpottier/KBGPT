# 🌊 OSMOSE - Fix Critique : ConceptType Domain-Agnostic

**Date** : 2025-11-21
**Phase** : 1.8.1d
**Priorité** : 🚨 **CRITIQUE**

---

## 🔍 Problème Identifié

### Symptôme Initial
Lors de l'analyse des logs après import, **SmartConceptMerger CRASH COMPLET** :

```
ERROR: [OSMOSE:Fusion] Error applying rule main_entities_merge: 'product' is not a valid ConceptType
ERROR: [OSMOSE:Fusion] Error applying rule slide_specific_preserve: 5 validation errors for CanonicalConcept
INFO: [OSMOSE:Fusion] Fallback: 1418 concepts not processed by rules
```

**Impact** :
- ❌ **AUCUNE FUSION** effectuée (tous concepts fell back to preserve-all)
- ❌ Pas de metrics `fusion_rate` générées
- ❌ Pas de metrics `concepts by type` générées
- ❌ Perte complète des bénéfices de la fusion intelligente

### Cause Racine

**Enum ConceptType trop restrictive** dans `src/knowbase/semantic/models.py` :

```python
class ConceptType(str, Enum):
    """Types de concepts sémantiques"""
    ENTITY = "entity"          # SAP S/4HANA, ISO 27001, MFA
    PRACTICE = "practice"      # threat modeling, code review
    STANDARD = "standard"      # ISO 27001, GDPR, SOC2
    TOOL = "tool"             # SAST, DAST, SIEM
    ROLE = "role"             # BISO, CSO, Security Champion
```

**Problèmes** :
1. ❌ **Domaine-spécifique** : Conçue pour cybersécurité uniquement
2. ❌ **Non extensible** : Pas de support pour PRODUCT, TECHNOLOGY, MOLECULE, CAMPAIGN, etc.
3. ❌ **Bloque fusion** : Config fusion_rules.yaml utilisait `PRODUCT` et `TECHNOLOGY` → validation Pydantic échoue
4. ❌ **Limite KnowWhere** : Inutilisable pour retail, life science, finance, etc.

---

## ✅ Solution Implémentée

### Principe : **Type Libre, Découvert Dynamiquement par LLM**

Le type de concept est maintenant un **simple `str`** sans contrainte d'enum.
Le LLM décide du type selon le contexte métier (domain-agnostic).

### Changements Appliqués

#### 1. Suppression de l'enum ConceptType

**Fichier** : `src/knowbase/semantic/models.py`

**Avant** :
```python
class ConceptType(str, Enum):
    ENTITY = "entity"
    PRACTICE = "practice"
    STANDARD = "standard"
    TOOL = "tool"
    ROLE = "role"
```

**Après** :
```python
# Note: Concept types are intentionally NOT an enum to remain domain-agnostic.
# Types are discovered dynamically by LLM based on document content.
# Examples: "product", "technology", "molecule", "campaign", "regulation", etc.
```

#### 2. Modification des modèles Pydantic

**Concept** :
```python
class Concept(BaseModel):
    name: str
    type: str  # Au lieu de ConceptType
    definition: str = ""
    context: str
    # ...
```

**CanonicalConcept** :
```python
class CanonicalConcept(BaseModel):
    canonical_name: str
    type: str  # Au lieu de ConceptType
    # ...
```

**CandidateEntity** (Proto-KG) :
```python
class CandidateEntity(BaseModel):
    canonical_name: str
    concept_type: str  # Au lieu de ConceptType
    # ...
```

#### 3. Correction des règles de fusion

**Fichier** : `src/knowbase/semantic/fusion/rules/main_entities.py`

**Avant** :
```python
eligible_types_str = self.config.get("eligible_types", ["ENTITY", "PRODUCT", "TECHNOLOGY"])
eligible_types = [ConceptType(t.lower()) for t in eligible_types_str]  # ❌ Crash si type invalide
if concept.type in eligible_types:
    eligible_concepts.append(concept)
```

**Après** :
```python
eligible_types_str = self.config.get("eligible_types", ["entity", "product", "technology"])
eligible_types = [t.lower() for t in eligible_types_str]  # ✅ Simple str normalization
if concept.type.lower() in eligible_types:
    eligible_concepts.append(concept)
```

**Fichier** : `src/knowbase/semantic/fusion/rules/slide_specific.py`

**Avant** :
```python
preserve_types_str = self.config.get("preserve_types", ["METRIC", "DETAIL", "TECHNICAL", "VALUE"])
preserve_types = []
for t in preserve_types_str:
    try:
        preserve_types.append(ConceptType(t.lower()))  # ❌ Crash si type invalide
    except ValueError:
        self.logger.warning(f"Unknown concept type: {t}")

if preserve_types and concept.type not in preserve_types:
    continue
```

**Après** :
```python
preserve_types_str = self.config.get("preserve_types", ["metric", "detail", "technical", "value"])
preserve_types = [t.lower() for t in preserve_types_str]  # ✅ Simple str normalization

if preserve_types and concept.type.lower() not in preserve_types:
    continue
```

#### 4. Mise à jour configuration YAML

**Fichier** : `config/fusion_rules.yaml`

**Avant** :
```yaml
eligible_types:
  - ENTITY
  - PRODUCT     # ❌ Type invalide selon enum
  - TECHNOLOGY  # ❌ Type invalide selon enum
```

**Après** :
```yaml
# Types domain-agnostic (lowercase)
# Les types sont découverts dynamiquement par le LLM selon le contexte métier
eligible_types:
  - entity       # Entités générales (produits, plateformes, systèmes)
  - product      # Produits spécifiques (si LLM le détecte)
  - technology   # Technologies (si LLM le détecte)
```

**Preserve types** :
```yaml
preserve_types:
  - metric       # Métriques
  - detail       # Détails spécifiques
  - technical    # Informations techniques
  - value        # Valeurs numériques
```

#### 5. Correction des defaults hardcodés

**Fichier** : `src/knowbase/semantic/fusion/fusion_integration.py`

```python
rules.append(MainEntitiesMergeRule(config={
    "eligible_types": ["entity", "product", "technology"]  # lowercase
}))

rules.append(SlideSpecificPreserveRule(config={
    "preserve_types": ["metric", "detail", "technical", "value"]  # lowercase
}))
```

#### 6. Correction des tests

**Fichier** : `tests/semantic/indexing/test_llm_judge_validation.py`

**Avant** :
```python
Concept(name="authentication", type=ConceptType.PRACTICE, ...)
```

**Après** :
```python
Concept(name="authentication", type="practice", ...)
```

#### 7. Correction SemanticIndexer

**Fichier** : `src/knowbase/semantic/indexing/semantic_indexer.py`

```python
def _select_concept_type(self, concepts: List[Concept]) -> str:
    """Sélectionne le type de concept majoritaire (normalized lowercase)."""
    type_counts = Counter(c.type.lower() for c in concepts)
    most_common_type = type_counts.most_common(1)[0][0]
    return most_common_type
```

---

## 🎯 Bénéfices de la Solution

### 1. **Domain-Agnostic True**

KnowWhere peut maintenant gérer **n'importe quel domaine métier** :

| Domaine | Types Découverts par LLM |
|---------|--------------------------|
| **SAP/ERP** | product, module, solution, technology, integration |
| **Life Science** | molecule, pathway, study, protocol, assay, compound |
| **Retail** | campaign, segment, channel, promotion, category |
| **Finance** | instrument, regulation, transaction, portfolio, risk |
| **Manufacturing** | process, equipment, material, specification, standard |

### 2. **Flexibilité Totale**

- ✅ LLM décide du type selon le contexte
- ✅ Pas de liste prédéfinie à maintenir
- ✅ Adaptatif automatiquement

### 3. **Robustesse**

- ✅ Plus de crash sur type invalide
- ✅ Normalisation lowercase pour comparaison
- ✅ Validation Pydantic simple (str au lieu d'enum)

### 4. **Cohérence Architecture**

Aligné avec l'objectif OSMOSE : **Organic Semantic Memory Organization**
→ Le système découvre organiquement les types sans contrainte artificielle

---

## 📊 Validation Post-Fix

### Tests à Effectuer

1. **Import nouveau document**
   ```bash
   # Via interface ou API
   POST /documents/import
   ```

2. **Vérifier fusion fonctionne**
   ```bash
   docker-compose logs worker | grep "\[OSMOSE:Fusion\]"
   ```

   **Attendu** :
   ```
   [OSMOSE:Fusion:MainEntities] Applying to 1418 concepts
   [OSMOSE:Fusion] ✅ Merge complete: 1418 concepts → 317 canonical
   [OSMOSE:Fusion] fusion_rate=23.4%
   ```

3. **Vérifier types découverts**
   ```bash
   docker-compose logs worker | grep "\[OSMOSE:Concept\] type="
   ```

   **Attendu** :
   ```
   [OSMOSE:Concept] type=entity
   [OSMOSE:Concept] type=product
   [OSMOSE:Concept] type=technology
   [OSMOSE:Concept] type=module
   [OSMOSE:Concept] type=feature
   ```

4. **Vérifier metrics Grafana**
   - Dashboard : http://localhost:3001/d/osmose-phase18
   - Panel "Fusion Rate" doit afficher une valeur
   - Panel "Concepts by Type" doit afficher distribution

---

## 🔧 Migration Guide (si besoin)

### Si DomainContext utilisait ConceptType

**Vérifier** : `src/knowbase/ontology/domain_context.py`

**Si enum utilisée** :
```python
# Avant
if concept_type == ConceptType.ENTITY:
    ...

# Après
if concept_type.lower() == "entity":
    ...
```

### Si Neo4j contraintes sur type

**Vérifier constraints Neo4j** :
```cypher
SHOW CONSTRAINTS
```

**Si constraint enum existante** :
```cypher
// Supprimer constraint enum si existe
DROP CONSTRAINT concept_type_enum IF EXISTS;
```

---

## 📝 Fichiers Modifiés

| Fichier | Changement | Impact |
|---------|------------|--------|
| `src/knowbase/semantic/models.py` | Suppression enum ConceptType | ⚠️ **BREAKING CHANGE** |
| `src/knowbase/semantic/fusion/rules/main_entities.py` | Type str normalization | ✅ Fix fusion |
| `src/knowbase/semantic/fusion/rules/slide_specific.py` | Type str normalization | ✅ Fix fusion |
| `src/knowbase/semantic/fusion/fusion_integration.py` | Defaults lowercase | ✅ Cohérence |
| `src/knowbase/semantic/indexing/semantic_indexer.py` | Return type str | ✅ Cohérence |
| `config/fusion_rules.yaml` | Types lowercase | ✅ Config valide |
| `tests/semantic/indexing/test_llm_judge_validation.py` | Type str au lieu enum | ✅ Tests passent |

---

## 🚀 Prochaines Étapes

1. ✅ **Redémarrage conteneurs** (fait)
2. 🔄 **Test import nouveau document**
3. 🔍 **Vérifier logs fusion OK**
4. 📊 **Vérifier dashboard metrics**
5. 📖 **Mettre à jour documentation architecture**

---

## 📚 Références

- **Ticket** : Phase 1.8.1d Fusion Crash Analysis
- **Logs** : docker-compose logs worker (timestamp 2025-11-21 18:xx)
- **Documentation** : `doc/OSMOSE_ARCHITECTURE_TECHNIQUE.md` (à mettre à jour)
- **Config** : `config/fusion_rules.yaml`

---

**Auteur** : Claude Code
**Session** : 2025-11-21
**Status** : ✅ **FIX APPLIQUÉ - EN ATTENTE VALIDATION**
