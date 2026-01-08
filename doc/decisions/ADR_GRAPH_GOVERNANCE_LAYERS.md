# ADR – Graph Governance Layers (Post-Consolidation)

## Metadata
- **Status**: Accepted
- **Date**: 2026-01-07
- **Revision**: v1.2 - Validation finale ChatGPT + renommage sémantique
- **Authors**: Claude + ChatGPT (validation croisée)
- **Related**: ADR Nomenclature Pass 2-4, ADR Assertion-Aware KG

---

## Context

OSMOSE adopte une architecture où :
- **Document-level** : La vérité extraite d'un document est sacrée et immutable
- **Corpus-level** : Les consolidations (Entity Resolution, CO_OCCURS_IN_CORPUS) enrichissent sans altérer
- **Principe fondamental** : *"OSMOSE ne réécrit jamais la vérité, il l'expose et la qualifie"*

Après les passes d'ingestion (Pass 1-4), le Knowledge Graph contient :
- Des relations **prouvées** avec `evidence_context_ids[]`
- Des relations **faibles** (CO_OCCURS_IN_CORPUS) pour les co-occurrences
- Des concepts **mergés** par Entity Resolution
- Des **assertions brutes** préservées pour traçabilité

---

## Problem Statement

### 1. Explosion du Graphe
Sans contrôle, le nombre de relations croît de manière combinatoire :
- N concepts × M documents → O(N²) relations potentielles
- Risque de bruit sémantique noyant les relations pertinentes

### 2. Qualité Hétérogène
Toutes les relations n'ont pas la même robustesse :
- Une relation prouvée par 5 documents ≠ une relation avec 1 mention faible
- Besoin de différencier sans supprimer

### 3. Contradictions Non Résolues
Deux documents peuvent affirmer des choses contradictoires :
- Doc A : "SAP S/4HANA remplace SAP ECC"
- Doc B : "SAP ECC reste en maintenance jusqu'en 2027"
- OSMOSE ne doit PAS trancher, mais EXPOSER la tension

---

## Decision

**Introduction de Graph Governance Layers**, distinctes des passes d'ingestion.

Ces couches s'appliquent **après** consolidation (Pass 4) et :
- ✅ **Ajoutent des métadonnées** de gouvernance
- ✅ **Marquent** les tensions et contradictions
- ✅ **Contrôlent** l'expansion à la requête
- ❌ **Ne créent PAS** de relations sémantiques
- ❌ **N'altèrent PAS** les preuves extraites

### Positionnement dans le Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INGESTION PIPELINE                                │
├─────────────┬─────────────┬─────────────┬─────────────┬─────────────────────┤
│   Pass 1    │   Pass 2    │   Pass 3    │   Pass 4a   │      Pass 4b        │
│  Document   │  Structure  │  Semantic   │   Entity    │   Corpus Links      │
│   Import    │  & Topics   │ Consolid.   │ Resolution  │ (CO_OCCURS_IN_CORPUS)│
│             │             │             │   (Merge)   │                     │
└─────────────┴─────────────┴─────────────┴─────────────┴─────────────────────┘
                                    │
                                    ▼
                    ════════════════════════════════════
                         GOVERNANCE LAYERS (ce ADR)
                    ════════════════════════════════════
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
             ┌──────────┐   ┌──────────┐   ┌──────────┐
             │ Quality  │   │  Budget  │   │ Conflict │
             │ Scoring  │   │ Control  │   │ Exposure │
             └──────────┘   └──────────┘   └──────────┘
                                    │
                                    ▼
                    ════════════════════════════════════
                              QUERY / USAGE
                    ════════════════════════════════════
```

---

## Non-Goals / Anti-Patterns

> ⚠️ **GARDE-FOUS CRITIQUES** - À relire avant toute évolution de cet ADR

### Ce que les Governance Layers ne sont PAS

| Anti-Pattern | Pourquoi c'est interdit |
|--------------|------------------------|
| **Filtrage définitif** | Un score LOW ne justifie JAMAIS la suppression d'une relation |
| **Choix de vérité** | Les scores ne déterminent pas "quelle relation est vraie" |
| **Résolution automatique** | Aucune couche ne peut "choisir" entre deux assertions contradictoires |
| **Persistance budgétaire** | Les limites de budget ne modifient JAMAIS l'état persistant du graphe |
| **Cross-doc truth creation** | Ces couches ne créent pas de relations sémantiques cross-documents typées |

### Clarifications Sémantiques Essentielles

1. **Les scores sont des indicateurs de consommation, pas des décisions de vérité.**
   - `confidence_tier = LOW` signifie "moins de preuves", pas "probablement faux"
   - Une relation LOW peut être parfaitement vraie (document rare mais fiable)

2. **Le Budget Layer est strictement query-time.**
   - Les règles de budget ne modifient jamais l'état persistant du graphe
   - Aucune suppression, aucun masquage définitif
   - Le graphe complet reste toujours accessible si besoin

3. **Le LLM est advisory, jamais décisionnel.**
   - LLM = aide à la **détection** des tensions potentielles
   - LLM ≠ arbitre de la vérité
   - Toute "résolution" reste une décision humaine explicite

---

## Scope

| Aspect | In Scope | Out of Scope |
|--------|----------|--------------|
| Quand | Après Pass 4 (corpus consolidé) | Pendant l'ingestion |
| Action | Annotation, marquage, scoring | Création de relations |
| Données | Métadonnées de gouvernance | Contenu sémantique |
| Vérité | Exposition des tensions | Résolution des conflits |

---

## Governance Dimensions

### 1. Quality / Confidence Layer

**Objectif** : Qualifier la robustesse des relations sans les modifier.

#### Métriques de Qualité

| Métrique | Description | Calcul |
|----------|-------------|--------|
| `evidence_count` | Nombre de preuves distinctes | `size(evidence_context_ids)` |
| `doc_coverage` | Nombre de documents source | Comptage docs uniques |
| `extraction_confidence` | Confiance moyenne extraction | Moyenne des scores LLM |
| `temporal_spread` | Étalement temporel des preuves | Max - Min dates |

#### Propriétés Neo4j (sur les relations)

```cypher
// Ajout métadonnées qualité sur relations existantes
// Note: "evidence_strength" plutôt que "quality_score" pour éviter
// toute confusion avec une notion de "vérité" ou "qualité intrinsèque"
MATCH (c1:CanonicalConcept)-[r]->(c2:CanonicalConcept)
WHERE r.evidence_context_ids IS NOT NULL
SET r.evidence_strength = <calculated>,  // Indicateur de support, pas de vérité
    r.evidence_count = size(r.evidence_context_ids),
    r.confidence_tier = CASE
      WHEN size(r.evidence_context_ids) >= 5 THEN 'HIGH'
      WHEN size(r.evidence_context_ids) >= 2 THEN 'MEDIUM'
      ELSE 'LOW'
    END
```

#### Tiers de Confiance

| Tier | Critères | Usage Recommandé |
|------|----------|------------------|
| **HIGH** | ≥5 preuves, ≥2 documents | Affichage par défaut |
| **MEDIUM** | 2-4 preuves | Affichage sur demande |
| **LOW** | 1 preuve | Exploration avancée |
| **WEAK** | CO_OCCURS uniquement | Suggestions seulement |

---

### 2. Budget / Usage Control Layer

**Objectif** : Contrôler l'expansion du graphe à la requête pour éviter l'explosion.

#### Paramètres de Contrôle

| Paramètre | Description | Défaut |
|-----------|-------------|--------|
| `max_hops` | Profondeur maximale traversée | 2 |
| `max_relations_per_hop` | Relations par nœud par niveau | 10 |
| `min_confidence_tier` | Tier minimum pour traversée | MEDIUM |
| `include_weak_links` | Inclure CO_OCCURS_IN_CORPUS | false |
| `max_total_nodes` | Limite absolue de nœuds | 100 |

#### Query Budget Pattern

```typescript
interface QueryBudget {
  maxHops: number
  maxRelationsPerHop: number
  minConfidenceTier: 'HIGH' | 'MEDIUM' | 'LOW' | 'WEAK'
  includeWeakLinks: boolean
  maxTotalNodes: number
  timeout_ms: number
}

const DEFAULT_BUDGET: QueryBudget = {
  maxHops: 2,
  maxRelationsPerHop: 10,
  minConfidenceTier: 'MEDIUM',
  includeWeakLinks: false,
  maxTotalNodes: 100,
  timeout_ms: 5000
}
```

#### Cypher avec Budget

```cypher
// Traversée budgétée
MATCH path = (start:CanonicalConcept {canonical_id: $concept_id})
              -[r*1..2]->(related:CanonicalConcept)
WHERE ALL(rel IN relationships(path) WHERE
  rel.confidence_tier IN ['HIGH', 'MEDIUM']
  AND type(rel) <> 'CO_OCCURS_IN_CORPUS'
)
WITH related, relationships(path) AS rels
ORDER BY reduce(s = 0, rel IN rels | s + rel.evidence_count) DESC
LIMIT 100
RETURN related
```

---

### 3. Conflict / Contradiction Exposure Layer

**Objectif** : Identifier et marquer les tensions sans les résoudre.

#### Principe Fondamental

> **OSMOSE ne tranche jamais les contradictions.**
> Il les expose à l'utilisateur avec contexte pour décision humaine.

#### Types de Tensions

| Type | Description | Exemple |
|------|-------------|---------|
| **TEMPORAL** | Informations de dates différentes | "Version 2023 vs Version 2025" |
| **SEMANTIC** | Assertions contradictoires | "Remplace" vs "Complète" |
| **SCOPE** | Contextes d'application différents | "Cloud only" vs "On-premise" |
| **SOURCE** | Sources de fiabilité différente | "Official doc" vs "Blog post" |

#### Modèle de Données Tension

```cypher
// Nœud Tension (ne modifie pas les relations existantes)
CREATE (t:Tension {
  tension_id: randomUUID(),
  tenant_id: $tenant_id,
  tension_type: 'SEMANTIC',  // TEMPORAL, SEMANTIC, SCOPE, SOURCE

  // Concepts concernés
  concept_ids: [$concept1_id, $concept2_id],

  // Assertions en tension
  assertion_ids: [$assertion1_id, $assertion2_id],

  // Contexte pour l'utilisateur
  description: "Contradiction détectée sur la relation entre X et Y",
  evidence_summary: [
    {doc_id: "doc1", assertion: "X remplace Y", date: "2024-01"},
    {doc_id: "doc2", assertion: "X complète Y", date: "2025-06"}
  ],

  // Métadonnées
  detected_at: datetime(),
  status: 'UNRESOLVED',  // UNRESOLVED, ACKNOWLEDGED, EXPLAINED
  resolution_note: null  // Rempli par l'utilisateur si EXPLAINED
  // IMPORTANT: EXPLAINED n'implique pas que la tension est "résolue" globalement.
  // Cela signifie qu'un humain a fourni une explication contextuelle,
  // mais les deux assertions sources restent intactes dans le graphe.
})

// Liens vers les éléments concernés
MATCH (c:CanonicalConcept {canonical_id: $concept1_id})
MATCH (t:Tension {tension_id: $tension_id})
CREATE (t)-[:CONCERNS]->(c)
```

#### Détection des Contradictions

```cypher
// Détection automatique : même paire de concepts, prédicats contradictoires
MATCH (c1:CanonicalConcept)-[r1]->(c2:CanonicalConcept)
MATCH (c1)-[r2]->(c2)
WHERE type(r1) <> type(r2)
  AND r1.evidence_context_ids IS NOT NULL
  AND r2.evidence_context_ids IS NOT NULL
  // Prédicats potentiellement contradictoires
  AND (
    (type(r1) = 'REPLACES' AND type(r2) = 'COMPLEMENTS')
    OR (type(r1) = 'ENABLES' AND type(r2) = 'BLOCKS')
    OR (type(r1) = 'DEPENDS_ON' AND type(r2) = 'INDEPENDENT_OF')
  )
RETURN c1, c2, type(r1), type(r2), r1.evidence_context_ids, r2.evidence_context_ids
```

#### UI Exposition des Tensions

```typescript
interface TensionDisplay {
  tensionId: string
  type: 'TEMPORAL' | 'SEMANTIC' | 'SCOPE' | 'SOURCE'
  concepts: ConceptSummary[]
  evidenceSummary: {
    docId: string
    docTitle: string
    assertion: string
    date?: string
  }[]
  status: 'UNRESOLVED' | 'ACKNOWLEDGED' | 'EXPLAINED'
  resolutionNote?: string
}

// Affichage dans l'UI
// ⚠️ Tension détectée
// Document A (2024-01): "SAP S/4HANA remplace SAP ECC"
// Document B (2025-06): "SAP ECC reste en maintenance"
// [Marquer comme vu] [Ajouter explication]
```

---

## Implementation Phases

### Phase A : Quality Layer (Priorité Haute)

1. **Script de scoring** : Calcul `confidence_tier` sur relations existantes
2. **Migration** : Ajout propriétés sur relations Neo4j
3. **API** : Paramètre `min_confidence` sur endpoints search
4. **UI** : Badge de confiance sur les relations affichées

### Phase B : Budget Layer (Priorité Moyenne)

1. **Query Builder** : Génération Cypher avec limites
2. **API** : Paramètres budget sur graph traversal
3. **Config** : Budgets par défaut configurables
4. **UI** : Contrôles "Explorer plus" avec warning

### Phase C : Conflict Layer (Priorité Basse)

1. **Détection batch** : Script identification tensions
2. **Modèle Tension** : Nœuds et relations Neo4j
3. **API** : Endpoints CRUD tensions
4. **UI** : Panel "Tensions détectées" avec résolution

---

## Metrics & Monitoring

### KPIs Qualité

| Métrique | Description | Alerte si |
|----------|-------------|-----------|
| `high_confidence_ratio` | % relations HIGH | < 20% |
| `orphan_relations` | Relations sans preuve | > 0 |
| `avg_evidence_count` | Moyenne preuves/relation | < 1.5 |

### KPIs Budget

| Métrique | Description | Alerte si |
|----------|-------------|-----------|
| `query_timeout_rate` | % requêtes timeout | > 5% |
| `avg_nodes_returned` | Moyenne nœuds/requête | > 80 |
| `budget_exceeded_rate` | % requêtes limitées | > 30% |

### KPIs Conflits

| Métrique | Description | Alerte si |
|----------|-------------|-----------|
| `unresolved_tensions` | Tensions non traitées | > 50 |
| `tension_rate` | Tensions / 100 relations | > 10% |

---

## Consequences

### Positives

- ✅ **Transparence** : L'utilisateur voit la qualité des informations
- ✅ **Performance** : Requêtes contrôlées, pas d'explosion
- ✅ **Intégrité** : Vérité préservée, contradictions exposées
- ✅ **Confiance** : Système honnête sur ses limites

### Négatives

- ⚠️ **Complexité** : Couche supplémentaire à maintenir
- ⚠️ **UX** : Risque de surcharger l'utilisateur d'informations
- ⚠️ **Batch** : Calculs qualité à re-exécuter après chaque import

### Risques

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Scoring trop strict | Moyenne | Relations utiles cachées | Tiers configurables |
| Détection faux positifs | Haute | Bruit tensions | LLM advisory (pré-filtre, pas décision) |
| Performance batch | Basse | Lenteur post-import | Calcul incrémental |
| Dérive vers filtrage définitif | Moyenne | Perte de vérité | Relecture section Non-Goals |

---

## References

- ADR Nomenclature Document/Corpus Phases (2026-01-07)
- ADR Assertion-Aware KG
- Principe OSMOSE : "Ne jamais réécrire la vérité"
- ChatGPT Analysis Session (2026-01-07)

---

## Open Questions

1. **Seuils confidence_tier** : Les valeurs 1/2/5 sont-elles optimales ?
2. **LLM detection scope** : Jusqu'où le LLM peut-il aller en mode advisory ? Pré-filtre des candidats tensions uniquement, ou aussi suggestion de type de tension ?
3. **Résolution utilisateur** : Comment tracker qui a "résolu" une tension ? Audit trail avec user_id ?
4. **Historique** : Garder l'historique des scores qualité dans le temps ? (pour détecter dégradation corpus)
5. **Cross-doc relations futures** : Si un jour OSMOSE crée des relations cross-doc typées, où cela s'insère-t-il ? (probablement nouveau Pass 5, hors scope Governance)

---

## Appendix: Predicate Contradiction Matrix

| Predicate A | Predicate B | Contradiction? |
|-------------|-------------|----------------|
| REPLACES | COMPLEMENTS | ✅ Probable |
| ENABLES | BLOCKS | ✅ Certaine |
| DEPENDS_ON | INDEPENDENT_OF | ✅ Certaine |
| PART_OF | CONTAINS | ❌ Non (inverse) |
| RELATED_TO | * | ❌ Trop vague |
| IMPLEMENTS | USES | ❌ Compatible |
| PRECEDES | FOLLOWS | ❌ Non (inverse) |
