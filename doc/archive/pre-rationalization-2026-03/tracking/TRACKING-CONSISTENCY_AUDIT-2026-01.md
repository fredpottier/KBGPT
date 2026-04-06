# Audit de Consistance OSMOSE - Janvier 2026

**Date:** 2026-01-01
**Contexte:** Après plusieurs semaines de développement intense (Burst Mode, Pass 2, Frontend, KG improvements), audit de consistance du projet.

---

## Résumé Exécutif

L'audit a identifié plusieurs incohérences architecturales, dont la principale était l'existence de **deux chemins parallèles** pour l'extraction de relations. Une décision a été prise pour unifier sur le chemin ADR-compliant.

---

## 1. Points d'Entrée d'Ingestion

### Analyse

| Méthode | Vision | LLM Provider | Pass 1 | Pass 2 |
|---------|--------|--------------|--------|--------|
| Frontend Upload | Auto par page | OpenAI | OSMOSE | Manuelle |
| Folder Watcher | Auto par page | OpenAI | OSMOSE | Manuelle |
| Burst Mode | Désactivée | vLLM | OSMOSE | Manuelle |

### Décisions

- **Vision Gating option frontend** : Obsolète. La décision vision/texte est maintenant automatique par page.
- **Pass 2** : Reste en mode manuel via frontend. Objectif futur : batch nocturne.
- **Convergence** : Les 3 méthodes convergent vers le même pipeline OSMOSE et les mêmes sinks Neo4j/Qdrant.

---

## 2. Extraction de Relations - DÉCISION MAJEURE

### Problème Identifié

Deux chemins parallèles existaient :

```
CHEMIN 1 (Legacy Phase 1.8) - DÉSACTIVÉ
  osmose_integration.py → RelationExtractionEngine → Neo4jRelationshipWriter
  → Edges directs entre CanonicalConcepts
  → Pas de RawAssertions, traçabilité limitée

CHEMIN 2 (Phase 2.8 ADR-Compliant) - CONSERVÉ
  Pass 2 ENRICH_RELATIONS → SegmentWindowRelationExtractor → RawAssertionWriter
  → RawAssertions avec fingerprint, evidence obligatoire
  → Consolidation → CanonicalRelations
```

### Décision

**Désactiver le Chemin 1 (legacy)** et conserver uniquement le Chemin 2.

**Modifications appliquées :**
- `config/feature_flags.yaml` : `enable_llm_relation_enrichment: false`
- `src/knowbase/ingestion/osmose_integration.py` : `enable_phase2_relations: false`

**Justification :**
- Chemin 2 conforme à l'ADR Hybrid Anchor Model
- Traçabilité complète (evidence, fingerprint, consolidation)
- Évite les doublons et incohérences
- `Neo4jRelationshipWriter` devient legacy (non utilisé)

---

## 3. Writers Neo4j

### Analyse

| Writer | Statut | Consistance |
|--------|--------|-------------|
| RawAssertionWriter | Actif (Pass 2) | 95% - Excellent |
| RawClaimWriter | Actif (Pass 2) | 95% - Excellent |
| CanonicalRelationWriter | Actif (Pass 2) | 92% - Bon |
| CanonicalClaimWriter | Actif (Pass 2) | 94% - Bon |
| Neo4jRelationshipWriter | **LEGACY** | Désactivé |
| MergeStore | Actif (ER) | 80% - Bon |

### Points d'Attention

- **Tenant isolation** : Strictement respectée (100%)
- **Timestamps** : Cohérents (append-only vs upsert bien séparés)
- **Fingerprint dedup** : Actif sur raw layer
- **Delete operations** : Suppression physique (soft-delete = amélioration future)

---

## 4. Feature Flags

### Corrections Appliquées

| Flag | Avant | Après | Raison |
|------|-------|-------|--------|
| `enable_llm_relation_enrichment` | `true` | `false` | Unifie sur Pass 2 |
| `enable_phase2_relations` | `true` | `false` | Unifie sur Pass 2 |

### Points Non Modifiés

| Sujet | Statut | Raison |
|-------|--------|--------|
| Excel pipeline hardcode | Ignoré | Pivot OSMOSE, fonctionnalité déprioritisée |
| Timeouts Pass 2 | À surveiller | Non critique, documenter |
| Context vLLM hardcodé | À documenter | Limite connue (6500 tokens) |

---

## 5. Architecture Cible Post-Audit

```
PASS 1 (Ingestion)
├── Extraction concepts (OSMOSE Agentique)
├── Création CanonicalConcepts
├── Création HybridAnchors
├── Création DocumentChunks
└── ❌ PAS de relations (désactivé)

PASS 2 (Enrichissement - Manuel via Frontend)
├── CLASSIFY_FINE : Types fine-grained
├── ENRICH_RELATIONS : RawAssertions (ADR-compliant)
├── CONSOLIDATE_CLAIMS : CanonicalClaims
├── CONSOLIDATE_RELATIONS : CanonicalRelations
└── CORPUS_ER : Entity Resolution

NAVIGATION LAYER (À implémenter - ADR_NAVIGATION_LAYER.md)
├── DocumentContext
├── SectionContext
└── WindowContext (optionnel)
```

---

## 6. Actions Réalisées

- [x] Désactiver `enable_llm_relation_enrichment` dans feature_flags.yaml
- [x] Désactiver `enable_phase2_relations` dans osmose_integration.py
- [x] Documenter la décision dans ce fichier

## 7. Actions Futures

- [x] Implémenter Navigation Layer (ADR_NAVIGATION_LAYER.md) - FAIT 2026-01-01
- [ ] Supprimer option Vision Gating du frontend (obsolète)
- [ ] Préparer batch nocturne pour Pass 2
- [ ] Considérer soft-delete pour audit trail (non prioritaire)

---

## 8. Navigation Layer - Implémentation (2026-01-01)

### Fichiers Créés

| Fichier | Description |
|---------|-------------|
| `src/knowbase/navigation/__init__.py` | Module principal |
| `src/knowbase/navigation/types.py` | Modèles ContextNode, MentionedIn, Config |
| `src/knowbase/navigation/navigation_layer_builder.py` | Writer pour créer ContextNodes |
| `src/knowbase/navigation/graph_lint.py` | Validation anti-mélange |

### Configuration Ajoutée

`config/feature_flags.yaml` - Section `navigation_layer`:
- `enable_document_context: true`
- `enable_section_context: true`
- `enable_window_context: false` (ADR)
- Budgets et seuils

### RAG Whitelist

Modifié `graph_guided_search.py:745` pour filtrer les relations par type sémantique.

### Fichiers à Vérifier (whitelist non encore appliquée)

Ces fichiers traversent des relations sans filtrer par type.
À modifier si nécessaire :

| Fichier | Ligne | Risque |
|---------|-------|--------|
| `coverage_map_service.py` | 508 | Moyen |
| `knowledge_proof_service.py` | 230 | Moyen |
| `research_axes_engine.py` | 470, 487 | Moyen |
| `entity_merge_service.py` | 138, 160 | Faible (merge) |
| `knowledge_graph_service.py` | 974, 995, 1017 | Faible (legacy) |

---

## 9. Navigation Layer - Compléments (2026-01-01)

### Intégration Pipeline OSMOSE

Fichier modifié: `src/knowbase/ingestion/osmose_agentique.py`

L'intégration est faite à l'étape 8b du pipeline Hybrid Anchor, après la persistance
Neo4j et avant Pass 2. Les ContextNodes sont créés automatiquement pour chaque document.

### Budget Top-N

Le budget `max_mentions_per_concept` (config: 100) est appliqué via
`_enforce_mention_budget()` dans le builder. Les mentions excédentaires sont
supprimées par ordre de poids croissant.

### Endpoints API

| Endpoint | Description |
|----------|-------------|
| `GET /api/navigation/stats` | Statistiques Navigation Layer |
| `GET /api/navigation/validate` | Validation graphe (lint) |
| `GET /api/navigation/document/{id}` | Concepts d'un document |
| `GET /api/navigation/concept/{id}/mentions` | Mentions d'un concept |

### Commande CLI

```bash
python scripts/validate_graph.py [--tenant X] [--verbose] [--stats] [--json]
```

### Tests

- `tests/navigation/test_types.py` - Tests des types
- `tests/navigation/test_graph_lint.py` - Tests du linter

### UI Graph

Modifié `frontend/src/types/graph.ts`:
- Ajout type `GraphLayer` (semantic | navigation)
- Ajout champ `layer` dans `GraphEdge`
- Style navigation: pointillés fins (#9F7AEA violet)
- Style sémantique: lignes pleines

---

---

## 10. Migration Navigation Layer (2026-01-01)

### Contexte

La Navigation Layer a été intégrée dans Pass 1 (Étape 8b). Les documents
ingérés AVANT cette modification n'ont pas de ContextNodes ni de relations
MENTIONED_IN.

### Script de Migration

`scripts/migrate_navigation_layer.py` - Construit la Navigation Layer pour
les documents existants.

**Usage:**

```bash
# Dry run - voir ce qui serait migré
docker-compose exec app python scripts/migrate_navigation_layer.py --dry-run

# Migration complète
docker-compose exec app python scripts/migrate_navigation_layer.py --verbose

# Migrer un seul document
docker-compose exec app python scripts/migrate_navigation_layer.py --doc-id abc123
```

**Options:**
- `--tenant TENANT_ID` : Tenant à migrer (défaut: default)
- `--doc-id DOC_ID` : Migrer un seul document
- `--dry-run` : Afficher sans exécuter
- `--verbose` : Logs détaillés
- `--batch-size N` : Documents par batch (défaut: 50)

### Comportement

Le script:
1. Parcourt tous les documents dans Neo4j
2. Vérifie si le DocumentContext existe déjà (skip si oui)
3. Récupère les CanonicalConcepts via HybridAnchors
4. Appelle `NavigationLayerBuilder.build_for_document()`
5. Calcule les poids et applique le budget

---

*Audit réalisé par Claude Code*
*Date: 2026-01-01*
*Dernière mise à jour: 2026-01-01 (Navigation Layer + Migration)*
