# ADR: Coverage is a Property, Not a Node Type

**Date**: 2026-01-16
**Status**: ACCEPTED
**Supersedes**: CoverageChunk node type / DocumentChunk as proof surface

---

## Context

### Origine du "coverage"

Le concept de coverage est né d'un problème concret : des concepts étaient extraits avec des anchors localisés (`anchor_status=SPAN`), mais ne pouvaient pas être reliés à un chunk car le chunker "retrieval" créait des trous (gaps).

Pour résoudre ce problème, un système de **dual chunking** a été implémenté :
- **CoverageChunks** : couverture 100% du texte, preuve de position
- **RetrievalChunks** : optimisés pour la recherche vectorielle

### Problème actuel

Avec l'introduction de **Option C** (DocItem → SectionContext → TypeAwareChunk), deux systèmes coexistent :

| Système | Nœuds | Usage |
|---------|-------|-------|
| Legacy | CoverageChunk → DocumentChunk | ANCHORED_IN (preuve position) |
| Option C | DocItem → SectionContext → TypeAwareChunk | Structure document |

Cette dualité cause :
1. **Mismatch section_id** : ProtoConcept utilise un format texte, SectionContext utilise UUID
2. **MENTIONED_IN = 0** : Pas de lien vers SectionContext
3. **COVERS = 0** : Chaîne cassée en aval
4. **Complexité** : Deux pipelines de chunking à maintenir

---

## Decision

### Principe fondamental

> **Coverage est un invariant produit, pas un type de nœud.**

L'invariant à garantir est :

> *Tout anchor SPAN doit pouvoir pointer vers une unité persistée qui couvre sa position (preuve localisable).*

### Actions

| Action | Cible |
|--------|-------|
| **SUPPRIMER** | CoverageChunk, DocumentChunk (node types) |
| **CONSERVER** | Invariant coverage (preuve localisable) |
| **IMPLÉMENTER** | Via DocItem (granularité plus fine, charspan natif) |

### Nouvelle architecture

```
AVANT (Dual Chunking)
─────────────────────
ProtoConcept ──ANCHORED_IN──> DocumentChunk (coverage)
                              └── char_start, char_end
                              └── context_id (souvent NULL)

APRÈS (Option C)
────────────────
ProtoConcept ──ANCHORED_IN──> DocItem
                              └── charspan_start, charspan_end
                              └── section_id (UUID, lié à SectionContext)
                              └── item_type, reading_order_index
```

### Rôles distincts (Proof vs Retrieval)

> **Règle contractuelle : ANCHORED_IN pointe uniquement vers DocItem, jamais vers des chunks retrieval.**

| Unité | Rôle | Usage |
|-------|------|-------|
| **DocItem** | **Proof surface** | Preuve localisable, cible de ANCHORED_IN |
| **TypeAwareChunk** | **Retrieval projection** | Recherche vectorielle, UI, RAG |

Cette séparation préserve le besoin dual (proof/retrieval) tout en supprimant la redondance de nœuds.

### Avantages DocItem vs DocumentChunk

| Critère | DocumentChunk | DocItem |
|---------|---------------|---------|
| Granularité | ~800 tokens | Paragraphe/élément |
| Position | char_start/end | charspan_start/end |
| Lien structure | context_id (NULL) | section_id (UUID) |
| Traçabilité | Isolé | → SectionContext → TypeAwareChunk |

---

## KPIs de remplacement

L'ancienne métrique "coverage %" (% texte couvert par chunks) est remplacée par des métriques directement liées aux invariants :

### 1. Anchor Bind Rate (ABR)
```
ABR = ProtoConcepts(SPAN) avec ANCHORED_IN valide / Total ProtoConcepts(SPAN)
```
- **Cible** : 100%
- **Alerte** : < 95%

### 2. Orphan Ratio (OR)
```
OR = ProtoConcepts sans ANCHORED_IN / Total ProtoConcepts
```
- **Cible** : 0%
- **Alerte** : > 5%

### 3. Section Alignment Rate (SAR)
```
SAR = ProtoConcepts dont section_id matche SectionContext / Total ProtoConcepts
```
- **Cible** : 100%
- **Alerte** : < 95%

### Requêtes Cypher pour monitoring

```cypher
-- Anchor Bind Rate (ABR)
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WHERE p.anchor_status = 'SPAN'
WITH collect(DISTINCT p) as all_protos
UNWIND all_protos as p
OPTIONAL MATCH (p)-[:ANCHORED_IN]->(target:DocItem)
WITH count(DISTINCT p) as total,
     count(DISTINCT CASE WHEN target IS NOT NULL THEN p END) as bound
RETURN total, bound,
       CASE WHEN total > 0 THEN toFloat(bound) / total * 100 ELSE 0 END as anchor_bind_rate

-- Orphan Ratio (OR)
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WITH count(p) as total
MATCH (orphan:ProtoConcept {tenant_id: $tenant_id})
WHERE NOT (orphan)-[:ANCHORED_IN]->()
WITH total, count(orphan) as orphans
RETURN total, orphans,
       CASE WHEN total > 0 THEN toFloat(orphans) / total * 100 ELSE 0 END as orphan_ratio

-- Section Alignment Rate (SAR)
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WHERE p.section_id IS NOT NULL
WITH count(DISTINCT p) as total
MATCH (p2:ProtoConcept {tenant_id: $tenant_id})
WHERE p2.section_id IS NOT NULL
MATCH (s:SectionContext {section_id: p2.section_id, tenant_id: $tenant_id})
WITH total, count(DISTINCT p2) as aligned
RETURN total, aligned,
       CASE WHEN total > 0 THEN toFloat(aligned) / total * 100 ELSE 0 END as section_alignment_rate
```

---

## Migration

Voir `doc/ongoing/PLAN_MIGRATION_COVERAGE_TO_OPTION_C.md` pour le plan détaillé.

### Résumé des phases

1. **Phase 1** : Aligner section_id (ProtoConcept utilise UUID de SectionContext)
2. **Phase 2** : Migrer ANCHORED_IN → DocItem
3. **Phase 3** : Supprimer CoverageChunks/DocumentChunk
4. **Phase 4** : Migrer MENTIONED_IN (utiliser section_id)
5. **Phase 5** : Validation COVERS

---

## Failure Modes & Guards

### Risque principal

Si la génération de DocItem échoue ou est partielle (OCR dégradé, PDF mal segmenté, tables complexes), le système peut revenir silencieusement à un coverage partiel sans alerte.

### Garde-fous obligatoires

1. **ABR monitoring** : Si ABR < 95%, alerte immédiate (invariant violé)
2. **Fallback explicite** : Si DocItem generation fails, le système doit :
   - Logger `[OSMOSE:COVERAGE] DocItem generation partial for doc_id={id}`
   - Créer un DocItem "fallback" couvrant la zone non structurée (type=`UNSTRUCTURED_ZONE`)
   - **Ne jamais** utiliser TypeAwareChunk comme fallback pour ANCHORED_IN
3. **Validation pipeline** : Avant de persister ProtoConcepts, vérifier que les DocItems cibles existent

### Non-goals explicites

- Ce ADR **ne supprime pas** la séparation proof/retrieval (deux besoins distincts)
- Ce ADR **ne garantit pas** que TypeAwareChunk couvre 100% du texte (ce n'est pas son rôle)

---

## Conséquences

### Positives
- Architecture simplifiée (1 seul système de chunking)
- Traçabilité complète : ProtoConcept → DocItem → SectionContext → TypeAwareChunk
- Métriques alignées sur les invariants réels
- Moins de code à maintenir

### Négatives
- Migration nécessaire pour données existantes
- Réimport potentiel de documents sans DocItem

### Neutres
- Le terme "coverage" reste utilisable pour décrire l'invariant
- Les métriques changent mais mesurent mieux la santé du système

---

## Références

- Option C ADR : `doc/ongoing/ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md`
- Plan migration : `doc/ongoing/PLAN_MIGRATION_COVERAGE_TO_OPTION_C.md`
- Modèles structural : `src/knowbase/structural/models.py`
