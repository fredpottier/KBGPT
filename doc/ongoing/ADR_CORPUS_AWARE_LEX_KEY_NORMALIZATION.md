# ADR: Corpus-Aware Lex-Key Normalization for Pass 2.0

**Status:** Accepted
**Date:** 2026-01-11
**Authors:** Claude Code + ChatGPT (validation)
**Supersedes:** N/A
**Related:** ADR_UNIFIED_CORPUS_PROMOTION.md

---

## Context

### Problème observé

Pass 4b (Corpus Links) retourne **0 CO_OCCURS_IN_CORPUS relations** malgré un corpus de 23 documents SAP.

### Diagnostic

1. **Pass 4b requiert** que des paires de concepts apparaissent dans **≥2 documents** ensemble
2. **Après analyse**, seulement **2 concepts** apparaissent dans plusieurs documents
3. **Cause racine:** La normalisation dans `corpus_promotion.py` est trop faible

### Normalisation actuelle (problématique)

```python
# corpus_promotion.py ligne 395-426
def _normalize_label(self, label: str) -> str:
    normalized = label.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = normalized.replace('s/4 hana', 's/4hana')  # Hardcodé!
    return normalized
```

**Limitations:**
- Ne gère pas les accents ("Données" vs "Donnees")
- Ne gère pas la ponctuation ("SAP S/4HANA" vs "SAP S 4HANA")
- Ne gère pas les pluriels ("Documents" vs "Document")
- Patch hardcodé non maintenable

### Conséquence

"SAP S/4HANA" dans Document A et "SAP S/4HANA" dans Document B créent **2 CanonicalConcepts distincts** au lieu d'un seul, car le matching cross-doc échoue.

---

## Decision

### Utiliser `compute_lex_key()` comme fonction de normalisation canonique

**Fonction existante** dans `lex_utils.py`:

```python
def compute_lex_key(canonical_name: str) -> str:
    """
    Normalisation forte, agnostique:
    1. Lowercase
    2. Unicode normalization (NFKD) → supprime accents
    3. Remove punctuation
    4. Normalize whitespace
    5. Light singularization (EN/FR)

    Exemple: "SAP S/4HANA" → "sap s 4hana"
    """
```

### Stocker `lex_key` sur ProtoConcept (Option B)

Au lieu de calculer à la volée, **persister** le `lex_key` sur chaque ProtoConcept pour:
- Matching performant côté Neo4j (indexable)
- Cohérence garantie (même algorithme partout)
- Éviter les calculs répétés

### Séparation des rôles (recommandation ChatGPT)

| Propriété | Rôle | Exemple |
|-----------|------|---------|
| `CanonicalConcept.label` | **Forme lisible** (display) | "SAP S/4HANA" |
| `CanonicalConcept.lex_key` | **Clé technique** (matching) | "sap s 4hana" |
| `ProtoConcept.concept_name` | Forme brute extraite | "SAP S/4HANA" |
| `ProtoConcept.lex_key` | **Clé technique** (à ajouter) | "sap s 4hana" |

### Ajouter un Type Guard Soft

Pour éviter les faux positifs (homonymes), appliquer une règle de **dominance 70%**:
- Si un type domine à ≥70% dans un bucket `lex_key` → garder ensemble
- Si divergence forte → split par type
- Labels courts/acronymes (< 6 chars) → split plus agressif
- **Sinon:** garder ensemble + flag `type_conflict=true` sur CanonicalConcept

---

## Neo4j Schema (propriétés vérifiées)

### ProtoConcept (existant)

```
(:ProtoConcept {
    concept_id: str,           # ID unique
    concept_name: str,         # Label brut extrait
    tenant_id: str,
    document_id: str,          # ⚠️ Attention: SectionContext utilise doc_id
    anchor_status: str,        # SPAN, FUZZ, NONE
    extract_confidence: float, # ⚠️ Pas "confidence"
    section_id: str,
    definition: str,
    type_heuristic: str,       # ⚠️ Pas type_fine (qui est sur CC)
    extraction_method: str,
    created_at: datetime
})
```

**À AJOUTER:**
```
    lex_key: str               # compute_lex_key(concept_name)
```

### CanonicalConcept (existant)

```
(:CanonicalConcept {
    canonical_id: str,
    label: str,                # Forme lisible (display)
    lex_key: str,              # ✅ Existe déjà! Clé technique
    tenant_id: str,
    type_fine: str,            # Type LLM (enrichi en Pass 2)
    type_coarse: str,          # Type heuristique
    stability: str,            # STABLE | SINGLETON
    unified_definition: str,
    promotion_reason: str,
    proto_count: int,
    document_count: int,
    created_at: datetime
})
```

**À AJOUTER (pour type guard):**
```
    type_bucket: str,          # Type dominant ou "__NONE__"
    type_conflict: bool        # true si divergence type dans bucket
```

### SectionContext (existant)

```
(:SectionContext {
    context_id: str,
    doc_id: str,               # ⚠️ Pas document_id!
    section_id: str,
    tenant_id: str,
    title: str,
    section_path: str
})
```

### Contrainte d'unicité CanonicalConcept (recommandation ChatGPT)

```cypher
CREATE CONSTRAINT canonical_unique IF NOT EXISTS
FOR (c:CanonicalConcept)
REQUIRE (c.tenant_id, c.lex_key, c.type_bucket) IS UNIQUE;
```

---

## Implementation Plan

### Phase 1: Migration des données existantes

**Script:** `scripts/migrate_lex_key.py`

```python
from knowbase.consolidation.lex_utils import compute_lex_key

# Pour tous les ProtoConcepts sans lex_key
query_read = """
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WHERE p.lex_key IS NULL
RETURN p.concept_id AS id, p.concept_name AS name
"""

query_update = """
MATCH (p:ProtoConcept {concept_id: $id, tenant_id: $tenant_id})
SET p.lex_key = $lex_key
"""

for proto in fetch_all(query_read):
    lex_key = compute_lex_key(proto["name"])
    execute(query_update, id=proto["id"], lex_key=lex_key)
```

**Index Neo4j:**
```cypher
CREATE INDEX proto_lex_key IF NOT EXISTS
FOR (p:ProtoConcept) ON (p.tenant_id, p.lex_key);
```

### Phase 2: Pass 1 - Enrichir à la création

**Fichier:** `src/knowbase/ingestion/` (création ProtoConcept)

À chaque création de ProtoConcept:
```python
from knowbase.consolidation.lex_utils import compute_lex_key

# Lors de la création du noeud
p.lex_key = compute_lex_key(p.concept_name)
```

### Phase 3: Pass 2.0 - Modifier corpus_promotion.py

#### 3.1 Supprimer `_normalize_label()`

Remplacer par import de `compute_lex_key`.

#### 3.2 Modifier `group_by_canonical_label()` → `group_by_lex_key()`

```python
from knowbase.consolidation.lex_utils import compute_lex_key

def group_by_lex_key(self, protos: List[Dict]) -> Dict[str, List[Dict]]:
    groups = defaultdict(list)
    for proto in protos:
        # Fallback transitoire (à retirer après migration)
        lex_key = proto.get("lex_key") or compute_lex_key(proto.get("concept_name", ""))
        groups[lex_key].append(proto)
    return groups
```

#### 3.3 Modifier `count_corpus_occurrences()`

```cypher
-- Avant
WHERE toLower(trim(p.concept_name)) = $canonical_label

-- Après
WHERE p.lex_key = $lex_key
  AND p.tenant_id = $tenant_id
```

#### 3.4 Modifier `link_corpus_protos_to_canonical()`

```cypher
-- Avant
WHERE toLower(trim(p.concept_name)) = $canonical_label

-- Après
WHERE p.lex_key = $lex_key
  AND p.tenant_id = $tenant_id
```

#### 3.5 Ajouter Type Guard Soft avec comportement explicite

```python
from collections import Counter, defaultdict
from typing import List, Dict, Tuple

def split_by_type_if_divergent(
    self,
    lex_key: str,
    protos: List[Dict]
) -> List[Tuple[str, List[Dict], bool]]:
    """
    Split un bucket par type si divergence forte.

    Returns:
        Liste de (type_bucket, protos, type_conflict)
    """
    # Utiliser type_heuristic (pas type_fine qui n'est pas sur Proto)
    types = [p.get("type_heuristic") for p in protos if p.get("type_heuristic")]

    if not types:
        return [("__NONE__", protos, False)]

    counter = Counter(types)
    total = sum(counter.values())
    top_type, top_count = counter.most_common(1)[0]
    dominance = top_count / total

    # Dominance >= 70% → pas de split
    if dominance >= 0.70:
        return [(top_type, protos, False)]

    # Divergence forte
    label_sample = protos[0].get("concept_name", "")
    is_short_or_acronym = len(label_sample) < 6 or label_sample.isupper()

    if is_short_or_acronym:
        # Split agressif par type
        grouped = defaultdict(list)
        for p in protos:
            t = p.get("type_heuristic") or "__NONE__"
            grouped[t].append(p)
        return [(t, ps, False) for t, ps in grouped.items()]

    # Label normal avec divergence → garder ensemble + flag conflict
    return [(top_type, protos, True)]  # type_conflict=True
```

#### 3.6 Création CanonicalConcept avec type_bucket

```python
def create_canonical_concept(self, decision, protos, type_bucket, type_conflict):
    # ...
    create_query = """
    MERGE (cc:CanonicalConcept {
        tenant_id: $tenant_id,
        lex_key: $lex_key,
        type_bucket: $type_bucket
    })
    ON CREATE SET
        cc.canonical_id = $canonical_id,
        cc.label = $label,
        cc.unified_definition = $unified_definition,
        cc.type_coarse = $type_coarse,
        cc.stability = $stability,
        cc.created_at = datetime(),
        cc.promotion_reason = $reason,
        cc.proto_count = $proto_count,
        cc.document_count = $document_count,
        cc.type_conflict = $type_conflict
    ON MATCH SET
        cc.updated_at = datetime(),
        cc.proto_count = cc.proto_count + $proto_count
    RETURN cc.canonical_id AS id
    """
```

### Phase 4: Requête de chargement modifiée

```cypher
MATCH (p:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
WHERE NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
OPTIONAL MATCH (p)-[a:ANCHORED_IN]->(dc:DocumentChunk)
WITH p, collect(DISTINCT dc.section_path) AS sections,
     collect(DISTINCT a.role) AS anchor_roles
RETURN p.concept_id AS proto_id,
       p.concept_name AS label,
       p.lex_key AS lex_key,
       p.type_heuristic AS type_heuristic,
       p.anchor_status AS anchor_status,
       p.extract_confidence AS confidence,
       p.definition AS quote,
       p.section_id AS section_path,
       p.template_likelihood AS template_likelihood,
       p.positional_stability AS positional_stability,
       p.dominant_zone AS dominant_zone,
       sections,
       anchor_roles,
       p.document_id AS document_id
```

---

## Fallback Transitoire (recommandation ChatGPT)

Pendant la période de migration (2-3 jours):

```python
def get_lex_key(proto: Dict) -> str:
    """Fallback si lex_key pas encore migré."""
    if proto.get("lex_key"):
        return proto["lex_key"]

    # Fallback + log pour monitoring
    logger.warning(f"[OSMOSE:CorpusPromotion] Proto {proto.get('proto_id')} missing lex_key")
    return compute_lex_key(proto.get("concept_name", ""))
```

**À retirer** une fois la migration complète.

---

## Tests Unitaires (recommandation ChatGPT)

**Fichier:** `tests/consolidation/test_lex_key_normalization.py`

```python
import pytest
from knowbase.consolidation.lex_utils import compute_lex_key

class TestLexKeyNormalization:
    """Tests de non-régression pour compute_lex_key."""

    def test_ponctuation(self):
        assert compute_lex_key("SAP S/4HANA") == compute_lex_key("SAP S 4HANA")

    def test_accents(self):
        assert compute_lex_key("Données") == compute_lex_key("Donnees")

    def test_espaces(self):
        assert compute_lex_key("  SAP   S/4HANA ") == compute_lex_key("SAP S/4HANA")

    def test_casse(self):
        assert compute_lex_key("SAP S/4HANA") == compute_lex_key("sap s/4hana")

    def test_pluriels(self):
        # Si singularisation activée
        assert compute_lex_key("documents") == compute_lex_key("document")

    def test_acronymes_preserves(self):
        # Les acronymes courts ne doivent pas être cassés
        key = compute_lex_key("SUM")
        assert key == "sum"
        assert len(key) == 3  # Pas de singularisation abusive
```

---

## Métriques d'Observabilité (recommandation ChatGPT)

À la fin de Pass 2.0, logger:

```python
logger.info(
    f"[OSMOSE:CorpusPromotion] Metrics: "
    f"protos_without_lex_key={count_missing_lex_key}, "
    f"canonical_created={created}, "
    f"canonical_reused={reused}, "
    f"instance_of_created={linked}, "
    f"buckets_split_by_type={splits}, "
    f"buckets_type_conflict={conflicts}"
)

# Top 10 lex_key by doc_count (pour vérifier consolidation cross-doc)
for lex_key, doc_count in top_lex_keys[:10]:
    logger.info(f"[OSMOSE:CorpusPromotion] Top lex_key: '{lex_key}' in {doc_count} docs")
```

---

## Consequences

### Positives

1. **Concepts unifiés cross-doc:** "SAP S/4HANA" dans N documents → 1 seul CanonicalConcept
2. **Pass 4b débloquée:** Plus de concepts multi-doc → plus de paires éligibles
3. **Matching robuste:** Accents, ponctuation, pluriels gérés automatiquement
4. **Performance:** Index Neo4j sur lex_key → requêtes O(1)
5. **Maintenabilité:** Suppression des hacks hardcodés
6. **Idempotence:** MERGE avec contrainte unique → pas de doublons

### Négatives

1. **Migration requise:** Script one-shot pour les ProtoConcepts existants
2. **Stockage additionnel:** ~20-50 bytes par ProtoConcept (négligeable)
3. **Risque faux positifs:** Atténué par type guard soft

### Neutres

1. **Règles de promotion inchangées:** High-Signal V2, minimal signal, seuils ADR
2. **Architecture batch préservée:** Pas de changement de paradigme
3. **Pass 4b inchangée:** Seule la "matière première" (concepts multi-doc) augmente

---

## Validation

### Consensus

- **Claude Code:** Diagnostic et proposition Option B
- **ChatGPT:** Validation + recommandations (type_bucket, fallback, tests, métriques)
- **Utilisateur:** Approbation du plan

### Critères de succès

Après implémentation:
1. `compute_lex_key("SAP S/4HANA") == compute_lex_key("sap s 4hana")` ✓
2. Concepts multi-doc > 10 (vs 2 actuellement)
3. CO_OCCURS_IN_CORPUS relations > 0
4. `protos_without_lex_key = 0` après migration

### Rollback

Si problème:
1. Retirer la contrainte unique CanonicalConcept
2. Revenir à `_normalize_label()` (backup dans git)
3. Les lex_key stockés restent mais sont ignorés

---

## Files to Modify

| File | Change |
|------|--------|
| `scripts/migrate_lex_key.py` | **CREATE** - Migration script |
| `src/knowbase/consolidation/corpus_promotion.py` | Remplacer normalisation, ajouter type guard |
| `src/knowbase/ingestion/pipelines/*.py` | Ajouter lex_key à création ProtoConcept |
| `tests/consolidation/test_lex_key_normalization.py` | **CREATE** - Tests unitaires |
| Neo4j | Index + contrainte unique |

---

## References

- `src/knowbase/consolidation/lex_utils.py` - Fonction `compute_lex_key()`
- `src/knowbase/consolidation/corpus_promotion.py` - Pass 2.0 actuelle
- `doc/ongoing/ADR_UNIFIED_CORPUS_PROMOTION.md` - Règles de promotion
- Conversation Claude + ChatGPT 2026-01-11

---

## Changelog

| Date | Author | Change |
|------|--------|--------|
| 2026-01-11 | Claude Code | Initial ADR creation |
| 2026-01-11 | Claude Code | V2: Corrections nommage Neo4j + recommandations ChatGPT |
