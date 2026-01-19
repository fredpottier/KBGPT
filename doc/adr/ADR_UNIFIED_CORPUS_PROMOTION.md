# ADR: Unified Corpus Promotion (Pass 1 → Pass 2.0)

**Date**: 2026-01-09
**Statut**: Accepted
**Auteurs**: Claude + ChatGPT + Fred
**Contexte**: Amélioration du taux de promotion des concepts cross-document
**Dépendances**: ADR_DUAL_CHUNKING_ARCHITECTURE, ADR_HYBRID_ANCHOR_MODEL, ADR_MARKER_NORMALIZATION_LAYER, ADR_DOCUMENT_STRUCTURAL_AWARENESS
**Revue**: Évaluation ChatGPT 2026-01-09 - Approuvé avec amendements intégrés

---

## 1. Contexte et Problème

### 1.1 Symptôme observé

Après import de multiples documents :
- **46 concepts** apparaissent dans **≥2 documents distincts**
- **Aucun de ces 46 concepts n'est promu** en CanonicalConcept
- Ces concepts sont **exclus de tout enrichissement** (Pass 2, 3, 4)

### 1.2 Diagnostic

Le scoring de promotion actuel (`AnchorBasedScorer`) est **per-document** :

```python
# anchor_based_scorer.py, lignes 260-275
if proto_count >= self.min_proto_for_stable:      # ≥2 dans le MÊME document
    stability = ConceptStability.STABLE
    promote = True
elif section_count >= self.min_sections_for_stable:  # ≥2 sections MÊME document
    stability = ConceptStability.STABLE
    promote = True
elif proto_count == 1 and is_high_signal:         # singleton + signal fort
    stability = ConceptStability.SINGLETON
    promote = True
else:
    promote = False  # ← 46 concepts cross-doc tombent ici
```

### 1.3 Cause racine

**La promotion se fait document par document, sans vue corpus.**

| Concept | DocA | DocB | DocC | Promu ? |
|---------|------|------|------|---------|
| "Fiori Launchpad" | 1 occ | 1 occ | 0 | **Non** (1+1 ≠ 2 dans même doc) |
| "SAP S/4HANA" | 3 occ | 0 | 0 | **Oui** (≥2 même doc) |
| "Integration Suite" | 1 occ | 1 occ | 1 occ | **Non** (jamais ≥2 même doc) |

### 1.4 Conflit architectural identifié

**"Promotion" sert à deux choses conceptuellement différentes :**

| Niveau | Signal | Moment optimal |
|--------|--------|----------------|
| **Document** | Répétition intra-doc, sections multiples | Pass 1 (synchrone) |
| **Corpus** | Fréquence cross-doc, cohérence terminologique | Pass 2+ (batch) |

La Pass 1 actuelle tente de faire les deux mais ne voit qu'un document à la fois.

### 1.5 Conséquences

Les concepts non-promus :
1. **N'ont pas de CanonicalConcept** (restent ProtoConcepts orphelins)
2. **Sont exclus de Pass 2a** (STRUCTURAL_TOPICS ne voit que CanonicalConcepts)
3. **Sont exclus de Pass 2b** (CLASSIFY_FINE, ENRICH_RELATIONS)
4. **Sont exclus de Pass 3** (SEMANTIC_CONSOLIDATION)
5. **Sont exclus de Pass 4** (ENTITY_RESOLUTION, CORPUS_LINKS)

Résultat : **perte d'information systématique** pour les concepts dispersés.

---

## 2. Options Considérées

### Option A: Two-Stage Promotion (Pass 1 + Pass 2.0)

```
Pass 1: Promotion doc-level (≥2 même doc, ≥2 sections, singleton+signal)
Pass 2.0: Promotion corpus-level additionnelle (≥2 documents)
```

**Avantages :**
- Feedback immédiat (concepts visibles dès Pass 1)
- Pass 1 reste autonome

**Inconvénients :**
- Deux endroits avec logique de promotion
- Complexité de maintenance
- Certains concepts promus "tard" ratent potentiellement des enrichissements

### Option B: Single-Stage Promotion (tout en Pass 2.0)

```
Pass 1: Extraction ProtoConcepts uniquement (pas de promotion)
Pass 2.0: Toute la promotion (doc-level + corpus-level)
```

**Avantages :**
- Point unique de promotion
- Vision corpus-aware dès le départ
- Tous les concepts scorés ensemble avec mêmes règles
- Architecture plus simple

**Inconvénients :**
- Documents non "visibles" jusqu'à Pass 2
- Dépendance au batch pour voir les CanonicalConcepts

### Option C: Promotion asynchrone différée (Pass 4.5)

```
Pass 1-4: Inchangées
Pass 4.5 (NOUVEAU): "Late Promotion" pour concepts cross-doc
```

**Avantages :**
- Pas de modification des passes existantes

**Inconvénients :**
- Les concepts promus tardivement **ratent Pass 2 et 3**
- Enrichissement incomplet pour ces concepts
- **Rejeté** - ne résout pas le problème fondamental

---

## 3. Décision

**Adopter l'Option B : Single-Stage Promotion en Pass 2.0**

### 3.1 Justification

Le contexte d'usage réel invalide l'argument UX de l'Option A :

| Facteur | Réalité |
|---------|---------|
| Mode d'import | Agents automatiques (Sharepoint, Google Drive) |
| Conscience utilisateur | Ne sait pas quand un doc est "en traitement" |
| Attente | Acceptable - doc visible quand complètement traité |
| Batch nocturne | Usage normal en production |

**Citation décisive (utilisateur)** :
> "Que le document ne soit pas visible et exploitable juste après Pass 1 et qu'il faille attendre le passage de Pass 2, 3, etc... via un batch nocturne ou tous les X documents ne me semble pas un problème en soi."

### 3.2 Architecture cible

```
Pass 1 (Document Import - Synchrone):
├── Segmentation
├── Extraction → ProtoConcepts
├── Classification heuristique (conservée)
├── Dual Chunking (Coverage + Retrieval)
├── Persistance Neo4j (ProtoConcepts + Chunks)
├── Persistance Qdrant (RetrievalChunks)
└── ❌ PAS de promotion, PAS de CanonicalConcepts

Pass 2.0 "Corpus Promotion" (NOUVEAU):
├── Charger TOUS les ProtoConcepts (document courant + corpus existant)
├── Grouper par label canonique (via NormalizationEngine)
├── Scorer avec règles UNIFIÉES :
│   ├── ≥2 occurrences même document → STABLE
│   ├── ≥2 sections différentes → STABLE
│   ├── ≥2 documents + signal minimal → STABLE (NOUVEAU)
│   └── singleton + high-signal → SINGLETON
└── Créer CanonicalConcepts + relations INSTANCE_OF

Pass 2a (STRUCTURAL_TOPICS): inchangée
Pass 2b (CLASSIFY_FINE + ENRICH_RELATIONS): inchangée
Pass 3 (SEMANTIC_CONSOLIDATION): inchangée
Pass 4 (ENTITY_RESOLUTION + CORPUS_LINKS): inchangée
```

---

## 4. Schéma de Promotion Unifié

### 4.1 Normalisation Canonique des Labels

**IMPORTANT** : La promotion corpus-level s'appuie sur le `NormalizationEngine` existant (ADR_MARKER_NORMALIZATION_LAYER), et **non sur un simple `lower/strip`**.

Cela garantit que les variantes d'un même concept sont correctement groupées :
- "Fiori Launchpad" / "SAP Fiori Launchpad" / "Fiori launch pad" → même canonical
- Évite la duplication de CanonicalConcepts pour variantes mineures

```python
from knowbase.consolidation.normalization import NormalizationEngine

def group_by_canonical_label(
    protos: List[ProtoConcept],
    tenant_id: str
) -> Dict[str, List[ProtoConcept]]:
    """
    Groupe les ProtoConcepts par label canonique.

    Utilise NormalizationEngine (pas simple lower/strip).
    """
    engine = NormalizationEngine(tenant_id=tenant_id)
    groups = defaultdict(list)

    for proto in protos:
        # Obtenir la forme canonique via le moteur
        result = engine.normalize(proto.label)
        canonical_form = result.canonical_form or proto.label.lower().strip()
        groups[canonical_form].append(proto)

    return groups
```

### 4.2 Condition Signal Minimal pour Cross-Doc

**AMENDEMENT ChatGPT** : La règle "≥2 documents → STABLE" est conditionnée à un **signal minimal** pour éviter de promouvoir des concepts "plats" sans valeur informationnelle.

| Signal Minimal | Description |
|----------------|-------------|
| `anchor_status = SPAN` | Au moins un proto a une quote localisée |
| `role ∈ {definition, constraint}` | Rôle structurant (pas juste context) |
| `confidence >= 0.7` | Score d'extraction suffisant |

Un concept cross-doc est promu STABLE **si et seulement si** :
- Il apparaît dans ≥2 documents distincts
- **ET** au moins un ProtoConcept satisfait le signal minimal

### 4.3 Algorithme Pass 2.0

```python
def corpus_promotion(
    document_id: str,
    tenant_id: str,
    neo4j_client: Neo4jClient
) -> List[CanonicalConcept]:
    """
    Phase 2.0: Promotion unifiée avec vue corpus.

    Exécutée au DÉBUT de Pass 2, AVANT toute autre phase.
    """

    # 1. Charger les ProtoConcepts non-promus du document courant
    current_protos = load_unlinked_proto_concepts(
        document_id=document_id,
        tenant_id=tenant_id
    )

    # 2. Pour chaque label CANONIQUE, vérifier la fréquence corpus
    promoted = []

    for canonical_label, protos in group_by_canonical_label(current_protos, tenant_id):
        # Compter dans le document courant
        doc_count = len(protos)
        section_count = count_distinct_sections(protos)
        is_high_signal = any(has_high_signal(p) for p in protos)

        # Signal minimal pour cross-doc (amendement ChatGPT)
        has_minimal_signal = any(
            p.anchor_status == "SPAN" or
            p.role in ("definition", "constraint") or
            (p.confidence and p.confidence >= 0.7)
            for p in protos
        )

        # Compter dans le corpus (autres documents)
        corpus_count = count_corpus_occurrences(
            canonical_label=canonical_label,
            tenant_id=tenant_id,
            exclude_document_id=document_id
        )

        # Règles de promotion unifiées
        promote = False
        stability = None
        reason = ""

        if doc_count >= 2:
            promote, stability = True, "STABLE"
            reason = f"≥2 occurrences même document ({doc_count})"

        elif section_count >= 2:
            promote, stability = True, "STABLE"
            reason = f"≥2 sections différentes ({section_count})"

        # AMENDEMENT: cross-doc nécessite signal minimal
        elif corpus_count >= 1 and has_minimal_signal:
            promote, stability = True, "STABLE"
            reason = f"≥2 documents + signal minimal (1 + {corpus_count} corpus)"

        elif doc_count == 1 and is_high_signal:
            promote, stability = True, "SINGLETON"
            reason = "singleton high-signal"

        if promote:
            canonical = create_canonical_from_protos(
                protos=protos,
                stability=stability
            )
            promoted.append(canonical)

            # Vérifier si des ProtoConcepts corpus doivent être liés
            if corpus_count > 0:
                link_corpus_protos_to_canonical(
                    canonical_label=canonical_label,
                    canonical_id=canonical.id,
                    tenant_id=tenant_id
                )

    return promoted
```

### 4.2 Requêtes Neo4j

```cypher
// Charger ProtoConcepts non-promus d'un document
MATCH (p:ProtoConcept {tenant_id: $tenant_id, document_id: $document_id})
WHERE NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
RETURN p

// Compter occurrences corpus pour un label
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WHERE toLower(trim(p.label)) = $normalized_label
  AND p.document_id <> $exclude_document_id
  AND NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
RETURN count(DISTINCT p.document_id) AS corpus_doc_count

// Lier ProtoConcepts corpus à un CanonicalConcept existant
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WHERE toLower(trim(p.label)) = $normalized_label
  AND NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
MATCH (cc:CanonicalConcept {concept_id: $canonical_id})
CREATE (p)-[:INSTANCE_OF {created_at: datetime()}]->(cc)
```

---

## 5. Impact sur le Code Existant

### 5.1 Fichiers à modifier

| Fichier | Modification |
|---------|--------------|
| `osmose_agentique.py` | Retirer bloc promotion (lignes 1061-1107) |
| `anchor_based_scorer.py` | Déplacer logique vers nouveau module |
| `pass2_orchestrator.py` | Ajouter `CorpusPhase.PROMOTION` comme Phase 0 |
| `osmose_persistence.py` | Ne plus créer CanonicalConcepts en Pass 1 |

### 5.2 Nouveau fichier à créer

```
src/knowbase/consolidation/corpus_promotion.py
```

Contient :
- `CorpusPromotionEngine` - Orchestration Phase 2.0
- `load_unlinked_proto_concepts()` - Chargement Neo4j
- `count_corpus_occurrences()` - Comptage cross-doc
- `link_corpus_protos_to_canonical()` - Liaison différée

### 5.3 Modification `pass2_orchestrator.py`

```python
class CorpusPhase(str, Enum):
    """Phases Corpus-Level (Pass 4 + nouveau)."""

    # Pass 2.0: Promotion (NOUVEAU - exécuté EN PREMIER)
    CORPUS_PROMOTION = "corpus_promotion"

    # Pass 4a: Entity Resolution
    ENTITY_RESOLUTION = "entity_resolution"

    # Pass 4b: Corpus Links
    CORPUS_LINKS = "corpus_links"
```

Ordre d'exécution Pass 2 :
```
1. CorpusPhase.CORPUS_PROMOTION  ← NOUVEAU
2. DocumentPhase.STRUCTURAL_TOPICS
3. DocumentPhase.CLASSIFY_FINE
4. DocumentPhase.ENRICH_RELATIONS
```

---

## 6. Statut Document et Visibilité

### 6.1 Cycle de vie document

```
UPLOADED → PASS1_DONE → PASS2_DONE → PASS3_DONE → PASS4_DONE → VISIBLE
              │
              └── ProtoConcepts créés, PAS de CanonicalConcepts
                  Document NON visible dans l'interface
```

### 6.2 Invariant de visibilité

```
Document.status == "VISIBLE"
    ⟺ Pass 4 terminée
    ⟺ CanonicalConcepts créés et enrichis
```

Un document n'apparaît dans les recherches et l'interface que lorsqu'il est complètement traité.

---

## 7. Métriques de Validation

### 7.1 Avant/Après

| Métrique | Avant | Cible |
|----------|-------|-------|
| Concepts cross-doc promus | 0/46 (0%) | **46/46 (100%)** |
| Concepts total promus | ~60% | **>85%** |
| Concepts exclus de Pass 2+ | ~40% | **<15%** |

### 7.2 Invariants à vérifier

| Invariant | Vérification |
|-----------|--------------|
| Pas de CanonicalConcept en Pass 1 | `COUNT(cc) = 0` après Pass 1 |
| Tous les CC créés en Pass 2.0 | `COUNT(cc) > 0` après Pass 2.0 |
| Liaison INSTANCE_OF complète | `COUNT(p) sans INSTANCE_OF = singletons non high-signal` |

### 7.3 Requête de validation

```cypher
// Vérifier qu'aucun concept cross-doc n'est orphelin
MATCH (p:ProtoConcept {tenant_id: $tenant_id})
WHERE NOT (p)-[:INSTANCE_OF]->(:CanonicalConcept)
WITH toLower(trim(p.label)) AS label, collect(DISTINCT p.document_id) AS docs
WHERE size(docs) >= 2
RETURN label, docs, size(docs) AS doc_count
// Résultat attendu: 0 lignes
```

---

## 8. Migration et Rétrocompatibilité

### 8.1 Documents existants

Les documents déjà importés avec l'ancienne architecture :
- Conservent leurs CanonicalConcepts existants
- Peuvent être "re-enrichis" via un script de migration optionnel

### 8.2 Script de migration (optionnel)

```python
def migrate_existing_documents(tenant_id: str):
    """
    Réexécute Pass 2.0 sur les ProtoConcepts orphelins existants.
    """
    # Charger tous les ProtoConcepts sans INSTANCE_OF
    orphans = load_all_unlinked_protos(tenant_id)

    # Grouper par label et appliquer nouvelles règles
    for label, protos in group_by_label(orphans):
        corpus_count = count_distinct_documents(protos)
        if corpus_count >= 2:
            # Créer CanonicalConcept et lier
            ...
```

---

## 9. Invariants NON NÉGOCIABLES

### Invariant 1 – Single Promotion Point
```
CanonicalConcepts créés UNIQUEMENT en Pass 2.0
Pass 1 ne crée JAMAIS de CanonicalConcept
```

### Invariant 2 – Corpus Awareness (avec signal minimal)
```
Tout concept apparaissant dans ≥2 documents + signal minimal DOIT être promu
Signal minimal = anchor_status=SPAN OU role∈{definition,constraint} OU confidence≥0.7
```

### Invariant 3 – Enrichment Completeness
```
Tout CanonicalConcept passe par Pass 2a/2b/3/4
Pas de concept "partiellement enrichi"
```

### Invariant 4 – Domain Agnosticism
```
Aucune règle spécifique à un domaine (SAP, etc.)
Scoring basé uniquement sur fréquence et signaux structurels
```

### Invariant 5 – Semantic Non-Regression (AMENDEMENT ChatGPT)
```
Tout CanonicalConcept promu DOIT avoir ≥1 ProtoConcept avec anchor_status=SPAN
Évite les CC purement "statistiques" sans preuve textuelle forte
```

Requête de vérification :
```cypher
// Vérifier qu'aucun CC n'est "sans preuve"
MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
WHERE NOT EXISTS {
    MATCH (cc)<-[:INSTANCE_OF]-(p:ProtoConcept {anchor_status: 'SPAN'})
}
RETURN cc.label, cc.concept_id
// Résultat attendu: 0 lignes
```

---

## 10. Risques Résiduels

| Risque | Probabilité | Mitigation |
|--------|-------------|------------|
| Délai visibilité (batch nocturne) | Faible | Mode INLINE disponible pour tests |
| Explosion promotions cross-doc | Faible | **Signal minimal requis** (amendement ChatGPT) |
| Performance corpus query | Moyenne | Index Neo4j sur `(canonical_label, tenant_id)` |
| Régression tests existants | Moyenne | Tests d'intégration à adapter |
| CC sans preuve textuelle | Faible | **Invariant 5** garantit ≥1 SPAN par CC |

---

## 11. Références

- ADR_DUAL_CHUNKING_ARCHITECTURE.md (prérequis pour ANCHORED_IN)
- ADR_HYBRID_ANCHOR_MODEL.md (architecture anchor)
- Discussion ChatGPT 2026-01-09 (recommandation Pass 2.0 vs Pass 4.5)
- Analyse Claude 2026-01-09 (comptage 46 concepts cross-doc)

---

## Annexe A: Règles de Promotion Unifiées

| Règle | Condition | Stabilité | Priorité |
|-------|-----------|-----------|----------|
| Multi-occurrence doc | `doc_count >= 2` | STABLE | 1 |
| Multi-section | `section_count >= 2` | STABLE | 2 |
| Multi-document | `corpus_count >= 1 AND has_minimal_signal` | STABLE | 3 |
| Singleton high-signal | `doc_count == 1 AND is_high_signal` | SINGLETON | 4 |

### Signal minimal (pour cross-doc)

La règle Multi-document nécessite au moins un des signaux suivants :
- `anchor_status = SPAN` (preuve textuelle localisée)
- `role ∈ {definition, constraint}` (rôle structurant)
- `confidence >= 0.7` (score d'extraction suffisant)

### High-signal criteria V2 (AMENDEMENT - signaux structurels)

**Problème résolu** : L'ancienne définition (modaux seuls) promouvait des faux positifs comme "Subject to change" (disclaimers légaux contenant "must/shall").

**Nouvelle définition** : `High-Signal = Normatif + Non-Template + Signal-Contenu`

```
1. NORMATIF (au moins un) :
   ├── anchor_role ∈ {definition, constraint, requirement, prohibition}
   └── OU pattern normatif dans quote (shall/must/required/shall not)

2. ET NON-TEMPLATE (tous) :
   ├── template_likelihood < 0.5
   ├── positional_stability < 0.8
   └── NOT (dominant_zone = BOTTOM_ZONE AND répété inter-pages)

3. ET SIGNAL-CONTENU (au moins un) :
   ├── dominant_zone = MAIN_ZONE
   ├── OU section_path non vide (SectionContext)
   └── ET len(label) < 120 chars (pas phrase monstrueuse)
```

**Référence** : ADR_DOCUMENT_STRUCTURAL_AWARENESS (composants ZoneSegmenter, TemplateDetector, LinguisticCueDetector)

**Exemples** :

| Concept | Normatif | Non-Template | Contenu | Résultat |
|---------|----------|--------------|---------|----------|
| "System shall validate" | shall ✓ | MAIN, low template ✓ | <120 chars ✓ | **HIGH-SIGNAL** |
| "Subject to change" | shall ✓ | BOTTOM, high template ✗ | - | **REJETÉ** |
| "© 2024 All rights reserved" | - | BOTTOM, legal_lang ✗ | - | **REJETÉ** |

---

## Annexe B: Comparaison Architectures

```
AVANT (Two-Stage implicite, incomplète):
┌─────────────────────────────────────────────────────────────┐
│ Pass 1: Extract + Promote (doc-level only)                  │
│         → CanonicalConcepts pour concepts "évidents"        │
│         → ProtoConcepts orphelins pour les autres           │
├─────────────────────────────────────────────────────────────┤
│ Pass 2-4: Travaille sur CanonicalConcepts UNIQUEMENT        │
│           → ProtoConcepts orphelins IGNORÉS                 │
└─────────────────────────────────────────────────────────────┘

APRÈS (Single-Stage, complète):
┌─────────────────────────────────────────────────────────────┐
│ Pass 1: Extract ONLY                                        │
│         → ProtoConcepts pour TOUS les concepts              │
│         → Pas de promotion                                  │
├─────────────────────────────────────────────────────────────┤
│ Pass 2.0: Corpus Promotion (NOUVEAU)                        │
│           → Vue corpus complète                             │
│           → CanonicalConcepts pour concepts qualifiés       │
├─────────────────────────────────────────────────────────────┤
│ Pass 2a-4: Travaille sur TOUS les CanonicalConcepts         │
│            → Enrichissement complet                         │
└─────────────────────────────────────────────────────────────┘
```
