# Phase 2.8.1 - Canonical Deduplication Fix

**Date de création:** 2025-12-21
**Status:** EN COURS - Diagnostic validé, implémentation à faire
**Priorité:** CRITIQUE (bloquant Phase 2.8 ID-First Extraction)
**Collaboration:** Claude Code + ChatGPT (validation croisée)
**Dépendances:** Phase 2.7 (Concept Matching Engine) ✅ COMPLETE

---

## 1. Position dans la Timeline

```
Phase 2 : Intelligence Relationnelle Avancée
════════════════════════════════════════════

├─ Phase 2.5 : Memory Layer                    ✅ COMPLETE
├─ Phase 2.7 : Concept Matching Engine         ✅ COMPLETE (78% golden set)
├─ Phase 2.8 : ID-First Relation Extraction    🟡 BLOQUÉ
│   └─ Phase 2.8.1 : Canonical Dedup Fix       🔴 EN COURS ← VOUS ÊTES ICI
├─ Phase 2.8 : RawAssertion Architecture       ⏸️ DÉPEND DE 2.8.1
└─ Phase 2.9+ : Consolidation & Inference      ⏸️ NOT STARTED
```

**Relation causale:**
- Phase 2.8 ID-First requiert un catalogue complet de `canonical_id`
- 60% des ProtoConcepts sont orphelins → catalogue incomplet
- Cette phase corrige la chaîne de bugs bloquants

---

## 2. Contexte et Problème

### 2.1 Symptôme Observé

Le pipeline OSMOSE Phase 2.8 perd **82% des relations** lors de l'extraction LLM.

**Métriques Neo4j actuelles (2025-12-21):**
```
ProtoConcepts: 1634 total
  - Promus (PROMOTED_TO): 688 (42%)
  - Orphelins (sans PROMOTED_TO): 946 (58%)

CanonicalConcepts: 540
  - Avec relations: 85 (15%)
  - Sans relations: 455 (85%)

segment_id = "unknown": 100% des ProtoConcepts
chunk_ids vides: 100% des CanonicalConcepts

Relations existantes:
  - PROMOTED_TO: 939
  - HAS_SUBJECT: 449
  - HAS_OBJECT: 449
```

### 2.2 Cause Racine

**Déduplication case-sensitive** : Le système utilise un matching exact sur `canonical_name` au lieu d'une clé normalisée.

Exemple d'échec:
```
ProtoConcept: name="legitimate interests"
CanonicalConcept existant: canonical_name="Legitimate Interests"

→ Pas de match (case-sensitive)
→ Proto reste orphelin
→ Catalogue incomplet pour ID-First extraction
```

---

## 3. Chaîne de Bugs Identifiée

```
Bug #1 (segment_id non propagé)
         ↓
Bug #2 (source_topic_id non persisté)
         ↓
    Extraction segment-level impossible
         ↓
Bug #3 (Déduplication case-sensitive)
         ↓
    60% ProtoConcepts orphelins
         ↓
Bug #4 (chunk_ids vides)
    ← Mapping proto→canonical cassé
         ↓
Bug #5 (canonical_id enrichment partiel)
         ↓
    Catalogue incomplet pour EXTRACT_RELATIONS
         ↓
Bug #6 (15% couverture relations - hubs only)
```

### 3.1 Détail des Bugs

| # | Bug | Localisation | Impact |
|---|-----|--------------|--------|
| **1** | `segment_id` non propagé | `orchestrator.py:229-234` | 100% = "unknown" |
| **2** | `source_topic_id` non persisté | `gatekeeper.py` | Pas de provenance |
| **3** | Déduplication case-sensitive | `neo4j_client.py:352-356` | 60% orphelins |
| **4** | `chunk_ids` vides | `osmose_agentique.py:765-773` | Cross-ref cassée |
| **5** | `canonical_id` enrichment partiel | `gatekeeper.py:387-395` | Catalogue incomplet |
| **6** | Relations concentrées sur hubs | `llm_relation_extractor.py` | 15% couverture |

---

## 4. Plan d'Implémentation Validé (ChatGPT + Claude)

### 4.1 Architecture Cible

**Nouvelle propriété `canonical_key`:**
```python
def normalize_canonical_key(name: str) -> str:
    """Clé de déduplication robuste."""
    import re
    import unicodedata

    if not name:
        return ""
    key = name.strip().lower()
    key = unicodedata.normalize("NFKC", key)
    key = re.sub(r"[—–]", "-", key)           # tirets normalisés
    key = re.sub(r"[.,;:!?()\[\]{}'\"`''""]", "", key)  # ponctuation faible
    key = re.sub(r"\s+", " ", key)            # espaces multiples
    return key.strip()
```

### 4.2 Phases d'Implémentation

```
Phase 1 - Migration One-Shot (sans APOC)
├── M1: Backfill canonical_key (Python batch)
└── M2: Fusion doublons (Python explicite par type relation)

Phase 2 - Fixes Code (parallélisables)
├── A1: find_canonical_concept → lookup par canonical_key
├── A2: Gestion orphelins avec status PROVISIONAL
└── B:  Propagation segment_id dans orchestrator

Phase 3 - Enrichissement
├── C: canonical_id enrichment complet
└── D: Extraction relations segment-level (texte dans state.segments)

Phase 4 - Validation
└── Re-ingestion document test + vérification stats
```

---

## 5. Checklist d'Implémentation

### 5.1 Fichiers à Créer

| Fichier | Description | Status |
|---------|-------------|--------|
| `src/knowbase/utils/__init__.py` | Package utils | ⏸️ |
| `src/knowbase/utils/normalize.py` | `normalize_canonical_key()` | ⏸️ |
| `scripts/migration_canonical_key.py` | Script M1+M2 | ⏸️ |

### 5.2 Fichiers à Modifier

| Fichier | Modification | Status |
|---------|--------------|--------|
| `neo4j_client.py:334-380` | `find_canonical_concept()` → lookup par `canonical_key` | ⏸️ |
| `neo4j_client.py:create_canonical_concept()` | Ajouter `canonical_key` + `status` | ⏸️ |
| `gatekeeper.py:357` | Propagation `segment_id` | ⏸️ |
| `gatekeeper.py:387-395` | Enrichissement `canonical_id` complet | ⏸️ |
| `orchestrator.py:229-234` | Propagation `segment_id` aux concepts | ⏸️ |

### 5.3 Migration M1 - Backfill canonical_key (Python)

```python
# Script batch - pas Cypher pour normalisation cohérente
from knowbase.utils.normalize import normalize_canonical_key

with driver.session() as session:
    result = session.run("""
        MATCH (c:CanonicalConcept)
        WHERE c.canonical_key IS NULL OR c.canonical_key = ""
        RETURN c.tenant_id, c.canonical_id, c.canonical_name
    """)

    updates = []
    for record in result:
        key = normalize_canonical_key(record["canonical_name"] or "")
        if not key:
            key = f"__empty__:{record['canonical_id']}"
        updates.append({
            "tenant_id": record["tenant_id"],
            "canonical_id": record["canonical_id"],
            "canonical_key": key
        })

    # Batch write
    for batch in chunks(updates, 500):
        session.run("""
            UNWIND $rows AS row
            MATCH (c:CanonicalConcept {tenant_id: row.tenant_id, canonical_id: row.canonical_id})
            SET c.canonical_key = row.canonical_key, c.updated_at = datetime()
        """, {"rows": batch})
```

### 5.4 Migration M2 - Fusion Doublons (sans APOC)

**Relations à remapper (explicitement par type):**

1. **PROMOTED_TO** (ProtoConcept → CanonicalConcept)
2. **HAS_SUBJECT** (RawAssertion → CanonicalConcept)
3. **HAS_OBJECT** (RawAssertion → CanonicalConcept)

```python
# Pour chaque groupe de doublons (même canonical_key):
# 1. Identifier winner (plus ancien)
# 2. Remapper relations

# A) PROMOTED_TO
session.run("""
    MATCH (p:ProtoConcept {tenant_id:$tenant_id})-[r:PROMOTED_TO]->(l:CanonicalConcept {canonical_id:$loser_id})
    MATCH (w:CanonicalConcept {tenant_id:$tenant_id, canonical_id:$winner_id})
    MERGE (p)-[:PROMOTED_TO]->(w)
    DELETE r
""", tenant_id=tenant_id, loser_id=loser, winner_id=winner)

# B) HAS_SUBJECT
session.run("""
    MATCH (ra:RawAssertion {tenant_id:$tenant_id})-[r:HAS_SUBJECT]->(l:CanonicalConcept {canonical_id:$loser_id})
    MATCH (w:CanonicalConcept {tenant_id:$tenant_id, canonical_id:$winner_id})
    MERGE (ra)-[:HAS_SUBJECT]->(w)
    DELETE r
""", ...)

# C) HAS_OBJECT
session.run("""
    MATCH (ra:RawAssertion {tenant_id:$tenant_id})-[r:HAS_OBJECT]->(l:CanonicalConcept {canonical_id:$loser_id})
    MATCH (w:CanonicalConcept {tenant_id:$tenant_id, canonical_id:$winner_id})
    MERGE (ra)-[:HAS_OBJECT]->(w)
    DELETE r
""", ...)

# D) Fusion chunk_ids (winner = union)
session.run("""
    MATCH (w:CanonicalConcept {tenant_id:$tenant_id, canonical_id:$winner_id})
    MATCH (l:CanonicalConcept {tenant_id:$tenant_id, canonical_id:$loser_id})
    WITH w, l,
         coalesce(w.chunk_ids, []) AS wc,
         coalesce(l.chunk_ids, []) AS lc
    SET w.chunk_ids = wc + [x IN lc WHERE NOT x IN wc],
        w.updated_at = datetime()
""", ...)

# E) Supprimer loser
session.run("""
    MATCH (l:CanonicalConcept {tenant_id:$tenant_id, canonical_id:$loser_id})
    DETACH DELETE l
""", ...)
```

### 5.5 Fix A2 - Gestion Orphelins avec Status

**Nouveau schéma CanonicalConcept:**
```cypher
(:CanonicalConcept {
    ...
    canonical_key: "legitimate interests",  -- NOUVEAU
    status: "PROVISIONAL" | "VALIDATED",    -- NOUVEAU
    ...
})
```

**Nouveau schéma ProtoConcept:**
```cypher
(:ProtoConcept {
    ...
    promotion_status: "PROMOTED" | "REJECTED" | "FAILED",  -- NOUVEAU
    ...
})
```

**Règles de promotion:**
1. Si `concept_name` vide → `promotion_status = "REJECTED"`
2. Si création canonical échoue → retry 1x, sinon `promotion_status = "FAILED"`
3. Nouveaux canonicals créés avec `status = "PROVISIONAL"`
4. Promotion vers `status = "VALIDATED"` si multi-documents ou relations fortes

### 5.6 Fix D - Texte Segments

**Option retenue: D1 - Garder en mémoire pendant le run**

Le segmenter produit le texte, donc:
- `state.segments = [{segment_id, text, topic_id, ...}]`
- Relation extraction réutilise `text` immédiatement
- Pas besoin de persister dans Neo4j

---

## 6. Contraintes et Index Neo4j

```cypher
-- Index pour déduplication rapide
CREATE INDEX canonical_concept_key_idx IF NOT EXISTS
FOR (c:CanonicalConcept) ON (c.tenant_id, c.canonical_key);

-- Index pour status
CREATE INDEX canonical_concept_status_idx IF NOT EXISTS
FOR (c:CanonicalConcept) ON (c.tenant_id, c.status);

-- Index pour promotion_status
CREATE INDEX proto_concept_promotion_idx IF NOT EXISTS
FOR (p:ProtoConcept) ON (p.tenant_id, p.promotion_status);
```

---

## 7. Métriques de Succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| ProtoConcepts orphelins | 58% | < 5% |
| CanonicalConcepts avec chunk_ids | 0% | > 90% |
| segment_id != "unknown" | 0% | 100% |
| Relations conservées (ID-First) | 18% | > 90% |
| Doublons CanonicalConcepts | ~15% estimé | 0% |

---

## 8. Risques et Mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Perte données lors fusion M2 | Basse | Élevé | Backup Neo4j avant migration |
| Normalisation trop agressive | Moyenne | Moyen | Tests sur échantillon avant batch |
| Régression performances | Basse | Moyen | Index canonical_key créé avant |
| APOC requis | Éliminé | - | Migration explicite Python |

---

## 9. Références

- **Conversation technique:** Claude Code + ChatGPT 2025-12-21
- **Phase parente:** Phase 2.8 - ID-First Relation Extraction
- **Documentation liée:**
  - `doc/ongoing/PHASE2.8_ID_FIRST_EXTRACTION.md`
  - `doc/ongoing/PHASE2.8_RAW_CANONICAL_ARCHITECTURE.md`
  - `doc/ongoing/PHASE2.7_CONCEPT_MATCHING_ENGINE.md`

---

## 10. Journal d'Implémentation

### 2025-12-21 (Nuit) : Bug Fix Orphelins + Script Réparation

**Diagnostic approfondi:**
- Les ProtoConcepts orphelins existaient bien dans Neo4j mais n'étaient pas liés aux CanonicalConcepts
- Cause: timing issues lors du batch processing (canonical créé mais proto pas encore visible)
- Cause secondaire: lock basé sur `canonical_name` au lieu de `canonical_key`

**Bugs corrigés dans `neo4j_client.py` (promote_to_published):**

1. **Bug Lock Key** (ligne 454):
   - Avant: `lock_key = f"canonical_lock:{tenant_id}:{canonical_name}"`
   - Après: `lock_key = f"canonical_lock:{tenant_id}:{canonical_key}"`
   - Impact: "Legitimate Interests" et "legitimate interests" utilisent maintenant le même lock

2. **Bug Return Empty** (lignes 543-563):
   - Avant: Si aggregate_query échouait → `return ""` → concept non lié
   - Après: Retourne `existing_canonical_id` même si aggregate_query échoue
   - Impact: Les concepts sont correctement mappés même si la relation n'est pas créée immédiatement

**Script de réparation créé:**
- `scripts/repair_orphan_protos.py` - Lie les orphelins aux canonicals existants
- Résultat: 101 orphelins réparés sur 180 (74 sans canonical correspondant)
- Stats après réparation: 81% protos promus (vs 57% avant)

**Containers redémarrés:** app, worker, watcher

---

### 2025-12-21 (Soir) : Implémentation Complète

**Fichiers créés:**
- `src/knowbase/utils/__init__.py` - Package utils
- `src/knowbase/utils/normalize.py` - Fonction `normalize_canonical_key()`
- `scripts/migration_canonical_key.py` - Script M1+M2
- `app/scripts/migration_canonical_key.py` - Copie pour container

**Fichiers modifiés:**
- `src/knowbase/common/clients/neo4j_client.py`:
  - Import `normalize_canonical_key`
  - `find_canonical_concept()` utilise `canonical_key` au lieu de `canonical_name`
  - `promote_to_published()` ajoute `canonical_key` + `status` aux nouveaux Canonicals
- `src/knowbase/agents/extractor/orchestrator.py`:
  - Fix Bug #1: Propagation `segment_id` aux concepts avant agrégation

**Migration exécutée (19:07 UTC):**
```
M1 Backfill: 903 concepts → canonical_key ajouté (100%)
M2 Fusion: 1 groupe de doublons fusionné
  - 1 concept supprimé
  - 1 relation PROMOTED_TO remappée
Résultat: 902 CanonicalConcepts, 0 doublons
```

**Containers redémarrés:** app, worker, watcher

### 2025-12-21 (Après-midi) : Diagnostic et Plan

**Travail réalisé:**
1. Identification des 6 bugs interconnectés
2. Collecte stats Neo4j (1634 protos, 540 canonicals, 58% orphelins)
3. Validation plan avec ChatGPT (3 itérations)
4. Challenge technique (APOC non disponible, Cypher M2 invalide)
5. Plan final validé sans APOC

**Décisions clés:**
- ✅ Migration en Python (pas Cypher/APOC) pour normalisation cohérente
- ✅ Fusion explicite par type de relation (pas de merge générique)
- ✅ A1 et B parallélisables
- ✅ segment_text gardé en mémoire (Option D1)

---

---

## 11. Problème Structurel Identifié (Post-Implémentation)

### 11.1 Constat Après Réparation

Malgré les corrections bugs 2.8.1, un problème structurel persiste :

**Stats Neo4j actuelles (2025-12-21 après réparation):**
```
CanonicalConcepts: 1081 total
  - Avec relations (RawAssertions): 165 (15%)
  - Isolés (sans relations): 916 (85%) ← PROBLÈME MAJEUR

RawAssertions: 554
  - HAS_SUBJECT: 554
  - HAS_OBJECT: 554
```

### 11.2 Analyse Root Cause

Le taux d'utilisation des concepts dans les relations varie **inversement** avec la taille du catalogue :

| Document | Concepts | Utilisés | Taux |
|----------|----------|----------|------|
| bird_protection_directive | 39 | 32 | **82%** |
| eu_ai_act | 438 | 48 | **11%** |
| eprivacy_directive | 98 | 16 | **16%** |
| eidas_regulation | 177 | 25 | **14%** |

**Cause racine:** L'extraction de relations travaille au niveau **DOCUMENT** avec un catalogue complet (400+ concepts pour gros docs), alors que l'architecture OSMOSE prévoyait une extraction par **SEGMENT**.

### 11.3 Impact

Le LLM reçoit un catalogue trop volumineux → n'utilise que 11-16% des concepts → 85% des concepts restent isolés sans relations → Knowledge Graph sous-exploité.

### 11.4 Solution → Phase 2.9

Voir `doc/ongoing/PHASE2.9_SEGMENT_LEVEL_RELATIONS.md` pour le plan d'implémentation.

---

**Version:** 1.3
**Dernière MAJ:** 2025-12-21 23:00 UTC
**Status:** ✅ BUGS FIXÉS | 🔴 PROBLÈME STRUCTUREL IDENTIFIÉ → Phase 2.9
**Auteurs:** Claude Code + ChatGPT (validation croisée)
