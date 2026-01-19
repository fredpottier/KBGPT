# Issue: MENTIONED_IN et COVERS à 0

**Date**: 2026-01-09
**Statut**: En investigation

## Problème

Les KPIs suivants dans la page Enrichment affichent 0 :
- **Mentions (MENTIONED_IN)** : 0
- **Couvertures (COVERS)** : 0

## Analyse

### MENTIONED_IN

Les relations `MENTIONED_IN` (CanonicalConcept → SectionContext) sont créées par `NavigationLayerBuilder.build_for_document()` dans `src/knowbase/navigation/navigation_layer_builder.py`.

**Problème** : Cette méthode n'est jamais appelée dans le pipeline actuel.
- L'import existe dans `osmose_agentique.py:75` mais reste inutilisé
- Le builder a été créé dans le commit `8a74194` mais jamais intégré au flux principal

### COVERS

Les relations `COVERS` (Topic → Concept) sont créées par `CoversBuilder` dans Pass 2a (`src/knowbase/relations/structural_topic_extractor.py:602`).

**Problème** : CoversBuilder dépend de MENTIONED_IN existants :
```cypher
MATCH (c:CanonicalConcept)-[m:MENTIONED_IN]->(ctx:SectionContext)
WHERE ctx.doc_id = $document_id
```

Sans MENTIONED_IN, cette requête ne retourne rien → aucun COVERS créé.

## Dépendance

```
Pass 1 (Extraction)
    → devrait créer MENTIONED_IN (non implémenté)
        → Pass 2a utilise MENTIONED_IN pour créer COVERS
```

## Solutions Possibles

1. **Option A** - Intégrer NavigationLayerBuilder dans Pass 1
2. **Option B** - Créer MENTIONED_IN dans Pass 2.0 (Promotion)
3. **Option C** - Modifier CoversBuilder pour utiliser ANCHORED_IN (existe déjà)

## Décision

À définir après stabilisation du pipeline Pass 2.
