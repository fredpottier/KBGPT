# Spécification : Consolidation Corpus-Level OSMOSE

**Version** : 1.0
**Date** : 2026-01-01
**Auteurs** : Claude Code + ChatGPT (spec), Fred (validation)
**Statut** : APPROUVÉ - Prêt pour implémentation

---

## 1. Contexte et Problématique

### 1.1 Diagnostic

Le Knowledge Graph OSMOSE actuel est **document-centric** alors que l'ambition produit est **corpus-centric**.

**Symptômes mesurés :**
- "cybersecurity certification schemes" existe **16 fois** (doublons inter-documents)
- **67.6%** des concepts sont isolés (sans relations)
- **0** relations cross-document
- **24 silos** documentaires non connectés

**Cause racine :**
L'Entity Resolution actuelle (`src/knowbase/entity_resolution/`) fonctionne uniquement **intra-document**. Il n'existe pas de mécanisme pour :
1. Fusionner les concepts identiques entre documents
2. Créer des liens faibles cross-document (cooccurrence)

### 1.2 Ce qui fonctionne (à préserver)

- ✅ Extraction segment-level avec evidence (`evidence_text` = 100%)
- ✅ Hard budgets ADR (8/segment, 150/doc)
- ✅ Fusion intra-document (26% de réduction Proto → Canonical)
- ✅ Module ER existant (CandidateFinder, PairScorer, DecisionRouter)

---

## 2. Architecture Cible

### 2.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                    CORPUS-LEVEL CONSOLIDATION                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PATCH-ER (BLOQUANT)          PATCH-LINK (BLOQUANT)             │
│  ┌─────────────────────┐      ┌─────────────────────┐           │
│  │ Entity Resolution   │      │ Corpus Linker       │           │
│  │ Inter-Document      │      │ (Liens faibles)     │           │
│  │                     │      │                     │           │
│  │ - Lexical (lex_key) │      │ - CO_OCCURS_IN_     │           │
│  │ - Semantic (embed)  │      │   CORPUS            │           │
│  │ - Compat (type)     │      │ - MENTIONED_IN_     │           │
│  │                     │      │   DOCUMENT          │           │
│  │ → MERGED_INTO edges │      │                     │           │
│  └─────────────────────┘      └─────────────────────┘           │
│                                                                  │
│  PATCH-BUDGET (STRUCTURANT)                                     │
│  ┌─────────────────────┐                                        │
│  │ Allocation Ranked   │                                        │
│  │ + Coverage Floor    │                                        │
│  │ (sans changer       │                                        │
│  │  les hard budgets)  │                                        │
│  └─────────────────────┘                                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Ordre d'exécution

1. **PATCH-ER** (bloquant) - Entity Resolution corpus-level
2. **PATCH-LINK** (bloquant) - Liens faibles déterministes
3. **PATCH-BUDGET** (structurant) - Allocation intelligente
4. **PATCH-CONFLICT** (qualité) - Verifier 2-pass pour conflicts_with

---

## 3. PATCH-ER : Entity Resolution Inter-Document

### 3.1 Objectif

Un `CanonicalConcept` représente un concept **unique dans le corpus**.
"GDPR" doit converger vers **un seul nœud**, sans whitelist métier.

### 3.2 Principe : Merge réversible

On ne supprime jamais de nœuds. On crée des relations `MERGED_INTO` réversibles.

### 3.3 Nouveaux champs sur :CanonicalConcept

```cypher
// Ajouts au schéma existant
corpus_concept_id: String    // ID stable corpus-level (= canonical_id du target après merge)
lex_key: String              // Clé lexicale normalisée pour matching
er_status: String            // STANDALONE | MERGED | PROPOSAL_PENDING
merged_into_id: String       // ID du concept cible si MERGED
merged_at: DateTime          // Timestamp du merge
```

### 3.4 Nouvelle relation : MERGED_INTO

```cypher
(:CanonicalConcept)-[:MERGED_INTO {
    merged_at: datetime,
    merge_score: float,
    merge_reason: string,      // "lex_exact" | "lex_high_sem_high" | "sem_only"
    lex_score: float,
    sem_score: float,
    compat_score: float,
    merged_by: string,         // "auto" | "manual"
    reversible: boolean        // always true
}]->(:CanonicalConcept)
```

### 3.5 Nouveau label : MergeProposal (audit)

```cypher
(:MergeProposal {
    proposal_id: String,
    source_id: String,         // canonical_id source
    target_id: String,         // canonical_id target
    lex_score: Float,
    sem_score: Float,
    compat_score: Float,
    decision: String,          // AUTO_MERGE | PROPOSE_ONLY | REJECT
    decision_reason: String,
    created_at: DateTime,
    applied: Boolean,
    applied_at: DateTime,
    applied_by: String
})
```

### 3.6 Algorithme : 3 étages (agnostique, sans whitelist)

#### Étage 1 : Lexical Canonical Key (LCK)

```python
def compute_lex_key(canonical_name: str) -> str:
    """
    Normalisation forte, agnostique.
    """
    text = canonical_name.lower().strip()
    # Unicode normalization
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    # Remove punctuation
    text = re.sub(r'[^\w\s]', ' ', text)
    # Normalize whitespace
    text = ' '.join(text.split())
    # Singularisation légère (EN/FR)
    if text.endswith('s') and len(text) > 3:
        text = text[:-1]
    return text

def lex_score(key1: str, key2: str) -> float:
    """Jaro-Winkler ou rapidfuzz ratio."""
    return rapidfuzz.fuzz.ratio(key1, key2) / 100.0
```

#### Étage 2 : Similarité Sémantique (Embeddings)

```python
def sem_score(name1: str, name2: str, embedder) -> float:
    """
    Cosine similarity sur embeddings.
    Modèle : intfloat/multilingual-e5-large (déjà utilisé)
    """
    emb1 = embedder.embed(name1)
    emb2 = embedder.embed(name2)
    return cosine_similarity(emb1, emb2)
```

#### Étage 3 : Compatibilité (Type + Context)

```python
# Matrice de compatibilité type_fine (générique, pas métier)
TYPE_COMPAT_MATRIX = {
    ("entity_organization", "entity_organization"): 1.0,
    ("entity_product", "entity_product"): 1.0,
    ("entity_standard", "entity_standard"): 1.0,
    ("abstract_general", "abstract_general"): 1.0,
    ("abstract_capability", "abstract_capability"): 1.0,
    ("regulatory_requirement", "regulatory_requirement"): 1.0,
    # Cross-type (partiel)
    ("entity_standard", "regulatory_requirement"): 0.7,
    ("abstract_general", "abstract_capability"): 0.5,
    # Default
    ("*", "*"): 0.3
}

def compat_score(type1: str, type2: str) -> float:
    """Score de compatibilité basé sur types."""
    key = (type1, type2)
    if key in TYPE_COMPAT_MATRIX:
        return TYPE_COMPAT_MATRIX[key]
    key_rev = (type2, type1)
    if key_rev in TYPE_COMPAT_MATRIX:
        return TYPE_COMPAT_MATRIX[key_rev]
    return TYPE_COMPAT_MATRIX[("*", "*")]
```

### 3.7 Politique de décision

```python
def decide_merge(lex: float, sem: float, compat: float) -> DecisionType:
    """
    Décision de merge basée sur les 3 scores.
    """
    # AUTO_MERGE : haute confiance
    if lex >= 0.98:
        return DecisionType.AUTO_MERGE
    if lex >= 0.92 and sem >= 0.95 and compat >= 0.7:
        return DecisionType.AUTO_MERGE
    if sem >= 0.97 and compat >= 0.9:
        return DecisionType.AUTO_MERGE

    # PROPOSE_ONLY : zone grise
    if lex >= 0.85 or (sem >= 0.90 and compat >= 0.5):
        return DecisionType.PROPOSE_ONLY

    # REJECT : trop différent
    return DecisionType.REJECT
```

### 3.8 Application du merge (rewiring)

```cypher
// 1. Créer l'edge MERGED_INTO
MATCH (source:CanonicalConcept {canonical_id: $source_id})
MATCH (target:CanonicalConcept {canonical_id: $target_id})
CREATE (source)-[:MERGED_INTO {
    merged_at: datetime(),
    merge_score: $merge_score,
    merge_reason: $reason,
    lex_score: $lex,
    sem_score: $sem,
    compat_score: $compat,
    merged_by: "auto",
    reversible: true
}]->(target)

// 2. Marquer source comme MERGED
SET source.er_status = "MERGED"
SET source.merged_into_id = $target_id
SET source.merged_at = datetime()

// 3. Mettre à jour target
SET target.merged_from = coalesce(target.merged_from, []) + $source_id

// 4. Rewire les edges typés SORTANTS de source
MATCH (source)-[r]->(other:CanonicalConcept)
WHERE type(r) IN ["REQUIRES", "ENABLES", "APPLIES_TO", "PART_OF", "CAUSES", "PREVENTS", "CONFLICTS_WITH", "GOVERNED_BY", "DEFINES", "MITIGATES"]
AND other.canonical_id <> $target_id
MERGE (target)-[new_r:$(type(r))]->(other)
SET new_r = properties(r)
SET new_r.rewired_from = $source_id
DELETE r

// 5. Rewire les edges typés ENTRANTS vers source
MATCH (other:CanonicalConcept)-[r]->(source)
WHERE type(r) IN ["REQUIRES", "ENABLES", "APPLIES_TO", "PART_OF", "CAUSES", "PREVENTS", "CONFLICTS_WITH", "GOVERNED_BY", "DEFINES", "MITIGATES"]
AND other.canonical_id <> $target_id
MERGE (other)-[new_r:$(type(r))]->(target)
SET new_r = properties(r)
SET new_r.rewired_from = $source_id
DELETE r

// 6. Rewire les INSTANCE_OF (Proto -> Canonical)
MATCH (proto:ProtoConcept)-[r:INSTANCE_OF]->(source)
MERGE (proto)-[:INSTANCE_OF]->(target)
DELETE r
```

### 3.9 Rollback (réversibilité)

```cypher
// Annuler un merge
MATCH (source:CanonicalConcept {canonical_id: $source_id})-[m:MERGED_INTO]->(target:CanonicalConcept)

// 1. Restaurer les edges rewirés
MATCH (target)-[r]->(other:CanonicalConcept)
WHERE r.rewired_from = $source_id
MERGE (source)-[new_r:$(type(r))]->(other)
SET new_r = properties(r)
REMOVE new_r.rewired_from
DELETE r

MATCH (other:CanonicalConcept)-[r]->(target)
WHERE r.rewired_from = $source_id
MERGE (other)-[new_r:$(type(r))]->(source)
SET new_r = properties(r)
REMOVE new_r.rewired_from
DELETE r

// 2. Restaurer INSTANCE_OF
MATCH (proto:ProtoConcept)-[:INSTANCE_OF]->(target)
WHERE proto.document_id IN $source_doc_ids  // docs d'origine du source
MERGE (proto)-[:INSTANCE_OF]->(source)

// 3. Nettoyer source
SET source.er_status = "STANDALONE"
REMOVE source.merged_into_id
REMOVE source.merged_at

// 4. Supprimer MERGED_INTO
DELETE m
```

### 3.10 Critères d'acceptation PATCH-ER

- [ ] "GDPR" (ou tout label identique) n'existe plus en N exemplaires actifs
- [ ] Un seul concept cible + N sources avec `er_status=MERGED`
- [ ] Pas de perte de relations (uniquement rewiring)
- [ ] Rollback testé et fonctionnel
- [ ] Module existant `entity_resolution/` étendu (pas nouveau module)

---

## 4. PATCH-LINK : Liens Faibles Cross-Document

### 4.1 Objectif

Connecter le graphe corpus **sans halluciner de causalité**.
Ces liens sont **déterministes** (zéro LLM).

### 4.2 Nouveaux types de relations

#### MENTIONED_IN_DOCUMENT

```cypher
(:CanonicalConcept)-[:MENTIONED_IN_DOCUMENT {
    mention_count: Integer,     // Nombre de ProtoConcepts liés dans ce doc
    first_seen: DateTime,
    sections: [String]          // Liste des sections où mentionné
}]->(:Document)
```

#### CO_OCCURS_IN_CORPUS

```cypher
(:CanonicalConcept)-[:CO_OCCURS_IN_CORPUS {
    weight: Float,              // PMI ou Jaccard normalisé
    doc_count: Integer,         // Nombre de docs où ils co-apparaissent
    is_weak_link: true,         // Flag explicite
    computed_at: DateTime
}]->(:CanonicalConcept)
```

### 4.3 Algorithme de calcul

```python
def compute_cooccurrence_weight(
    concept_a_docs: Set[str],
    concept_b_docs: Set[str],
    total_docs: int
) -> float:
    """
    Calcul PMI (Pointwise Mutual Information) normalisé.
    """
    intersection = concept_a_docs & concept_b_docs
    if not intersection:
        return 0.0

    # P(A), P(B), P(A,B)
    p_a = len(concept_a_docs) / total_docs
    p_b = len(concept_b_docs) / total_docs
    p_ab = len(intersection) / total_docs

    # PMI = log(P(A,B) / (P(A) * P(B)))
    pmi = math.log(p_ab / (p_a * p_b))

    # Normalisation [-1, 1] -> [0, 1]
    npmi = pmi / (-math.log(p_ab))
    return max(0, npmi)
```

### 4.4 Filtrage (éviter graphe complet)

```python
# Ne garder que les top-K cooccurrences par concept
TOP_K_COOCCURRENCES = 20

# Seuil minimum de poids
MIN_COOCCURRENCE_WEIGHT = 0.1

# Minimum de docs communs
MIN_COMMON_DOCS = 2
```

### 4.5 Requête de génération

```cypher
// Générer MENTIONED_IN_DOCUMENT
MATCH (cc:CanonicalConcept {tenant_id: $tenant_id, er_status: "STANDALONE"})
MATCH (pc:ProtoConcept)-[:INSTANCE_OF]->(cc)
WITH cc, pc.document_id AS doc_id, collect(pc.section_id) AS sections
MATCH (d:Document {document_id: doc_id, tenant_id: $tenant_id})
MERGE (cc)-[m:MENTIONED_IN_DOCUMENT]->(d)
SET m.mention_count = size(sections),
    m.sections = sections,
    m.first_seen = datetime()

// Générer CO_OCCURS_IN_CORPUS (top-K par concept)
MATCH (cc1:CanonicalConcept {tenant_id: $tenant_id, er_status: "STANDALONE"})-[:MENTIONED_IN_DOCUMENT]->(d:Document)<-[:MENTIONED_IN_DOCUMENT]-(cc2:CanonicalConcept {tenant_id: $tenant_id, er_status: "STANDALONE"})
WHERE cc1.canonical_id < cc2.canonical_id  // Éviter doublons
WITH cc1, cc2, count(DISTINCT d) AS doc_count
WHERE doc_count >= 2
WITH cc1, cc2, doc_count,
     // Calcul simplifié du poids (Jaccard)
     doc_count * 1.0 / (
         size((cc1)-[:MENTIONED_IN_DOCUMENT]->()) +
         size((cc2)-[:MENTIONED_IN_DOCUMENT]->()) - doc_count
     ) AS weight
ORDER BY cc1.canonical_id, weight DESC
WITH cc1, collect({cc2: cc2, weight: weight, doc_count: doc_count})[0..20] AS top_coocs
UNWIND top_coocs AS cooc
MERGE (cc1)-[c:CO_OCCURS_IN_CORPUS]->(cooc.cc2)
SET c.weight = cooc.weight,
    c.doc_count = cooc.doc_count,
    c.is_weak_link = true,
    c.computed_at = datetime()
```

### 4.6 Critères d'acceptation PATCH-LINK

- [ ] Chaque CanonicalConcept actif a au moins un MENTIONED_IN_DOCUMENT
- [ ] Les 24 silos sont connectés via CO_OCCURS_IN_CORPUS
- [ ] Aucun appel LLM
- [ ] Les liens faibles sont clairement distingués des relations typées (is_weak_link=true)
- [ ] Densité du graphe augmente significativement (objectif : <30% isolés)

---

## 5. PATCH-BUDGET : Allocation Intelligente

### 5.1 Objectif

Mieux utiliser les budgets existants **sans les augmenter**.

### 5.2 Budgets ADR (invariants)

```python
# Ces valeurs sont FIXES et ne doivent PAS changer
MAX_RELATIONS_PER_SEGMENT = 8
MAX_RELATIONS_PER_DOCUMENT = 150
MAX_QUOTE_WORDS = 30
VALID_PREDICATES = 12
```

### 5.3 Allocation Ranked

```python
def allocate_budget_ranked(segments: List[Segment], doc_budget: int = 150) -> List[Segment]:
    """
    Alloue le budget en priorisant les meilleurs segments.
    """
    # Trier par score décroissant
    ranked = sorted(segments, key=lambda s: s.score, reverse=True)

    remaining_budget = doc_budget
    selected = []

    for segment in ranked:
        if remaining_budget <= 0:
            break
        # Allouer au maximum 8 relations par segment
        segment_allocation = min(8, remaining_budget)
        segment.allocated_budget = segment_allocation
        selected.append(segment)
        remaining_budget -= segment_allocation

    return selected
```

### 5.4 Coverage Floor Proportionnel

```python
def compute_coverage_floor(total_segments: int) -> int:
    """
    Garantit un minimum de segments traités.
    """
    # 15% des segments, borné entre 10 et 25
    floor = math.ceil(0.15 * total_segments)
    return max(10, min(floor, 25))

def ensure_coverage(segments: List[Segment], min_segments: int) -> List[Segment]:
    """
    Si pas assez de segments éligibles (score >= 35),
    compléter avec les meilleurs parmi score >= 25.
    """
    eligible_high = [s for s in segments if s.score >= 35]

    if len(eligible_high) >= min_segments:
        return eligible_high[:min_segments]

    # Compléter avec score >= 25
    eligible_medium = [s for s in segments if 25 <= s.score < 35]
    eligible_medium = sorted(eligible_medium, key=lambda s: s.score, reverse=True)

    needed = min_segments - len(eligible_high)
    return eligible_high + eligible_medium[:needed]
```

### 5.5 Stop Condition Anti-Bruit

```python
def should_stop_extraction(recent_results: List[SegmentResult], window: int = 5) -> bool:
    """
    Arrête l'extraction si trop de rejets evidence.
    """
    if len(recent_results) < window:
        return False

    last_n = recent_results[-window:]
    total_proposed = sum(r.relations_proposed for r in last_n)
    total_rejected = sum(r.relations_rejected for r in last_n)

    if total_proposed == 0:
        return True

    rejection_rate = total_rejected / total_proposed
    return rejection_rate > 0.60  # >60% rejet = stop
```

### 5.6 Critères d'acceptation PATCH-BUDGET

- [ ] Hard budgets inchangés (8/seg, 150/doc)
- [ ] Segments traités par ordre de score
- [ ] Coverage floor respecté (min 10 segments ou 15%)
- [ ] Stop condition implémentée
- [ ] Taux de concepts connectés augmente

---

## 6. PATCH-CONFLICT : Verifier 2-Pass

### 6.1 Problème

Le self-audit pour `conflicts_with` est auto-justificatif.
Le LLM tend à confirmer sa propre extraction.

### 6.2 Solution : 2-Pass Verifier

```python
async def verify_conflicts_with(
    relation: ExtractedRelation,
    segment_text: str,
    llm_router
) -> VerificationResult:
    """
    Vérification dédiée pour conflicts_with.
    Appel LLM séparé avec prompt spécialisé.
    """
    if relation.predicate != "CONFLICTS_WITH":
        return VerificationResult(valid=True)

    prompt = f"""Analyze this potential conflict relation:

Subject: {relation.subject_label}
Object: {relation.object_label}
Evidence: "{relation.quote}"

Question: Does this evidence EXPLICITLY show a conflict, contradiction, or incompatibility?

Rules:
- A conflict means they CANNOT coexist or one prevents/negates the other
- "Different" is NOT a conflict
- "Alternative" is NOT a conflict
- "Complementary" is NOT a conflict

Answer ONLY:
- YES: if genuine conflict with reason
- NO: if not a conflict, suggest better predicate from: REQUIRES, ENABLES, APPLIES_TO, PART_OF, ASSOCIATED_WITH
- REJECT: if no valid relation exists

Format: DECISION|REASON|ALTERNATIVE_PREDICATE (if NO)
"""

    response = await llm_router.acomplete(
        task_type=TaskType.KNOWLEDGE_EXTRACTION,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0
    )

    return parse_verification_response(response)
```

### 6.3 Critères d'acceptation PATCH-CONFLICT

- [ ] Toute relation `conflicts_with` passe par le verifier
- [ ] Taux de conflicts_with < 3% du total (actuellement 1.2%, à surveiller)
- [ ] Rejets/remplacements loggués pour audit

---

## 7. Fichiers à créer/modifier

### 7.1 Nouveaux fichiers

```
src/knowbase/consolidation/
├── __init__.py
├── corpus_er_pipeline.py      # PATCH-ER : orchestration ER corpus
├── corpus_linker.py           # PATCH-LINK : liens faibles
├── merge_store.py             # Stockage/audit des merges
└── types.py                   # Types partagés

src/knowbase/api/routers/
└── corpus_consolidation.py    # API endpoints
```

### 7.2 Fichiers à modifier

```
src/knowbase/entity_resolution/
├── candidate_finder.py        # Étendre pour cross-doc
├── pipeline.py                # Mode corpus vs document
└── config.py                  # Seuils ER

src/knowbase/relations/
└── segment_window_relation_extractor.py  # PATCH-BUDGET

src/knowbase/api/services/
└── pass2_service.py           # Intégrer consolidation corpus
```

---

## 8. Plan d'exécution

### Phase 1 : PATCH-ER (Semaine 1-2)

1. Ajouter champs Neo4j (lex_key, er_status, etc.)
2. Implémenter compute_lex_key + lex_score
3. Étendre CandidateFinder pour mode corpus
4. Implémenter decide_merge
5. Implémenter rewiring + rollback
6. Tests unitaires + intégration
7. Exécuter ER sur corpus existant

### Phase 2 : PATCH-LINK (Semaine 2-3)

1. Implémenter génération MENTIONED_IN_DOCUMENT
2. Implémenter calcul CO_OCCURS_IN_CORPUS
3. API pour visualiser liens faibles
4. Tests + validation densité graphe

### Phase 3 : PATCH-BUDGET (Semaine 3)

1. Implémenter ranked allocation
2. Implémenter coverage floor
3. Implémenter stop condition
4. Re-run Pass 2 sur documents avec faible couverture

### Phase 4 : Validation (Semaine 4)

1. Métriques qualité KG
2. Tests navigation corpus
3. Documentation utilisateur

---

## 9. Métriques de succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| Doublons inter-doc | 16x "GDPR" | 1x |
| Concepts isolés | 67.6% | <30% |
| Relations cross-doc | 0 | >500 (via cooccurrence) |
| Densité graphe | 0.009% | >0.05% |
| Hubs corpus identifiables | 0 | >20 |

---

## 10. Annexe : Schéma Neo4j cible

```cypher
// CanonicalConcept (après PATCH-ER)
(:CanonicalConcept {
    canonical_id: String,        // ID unique
    canonical_name: String,      // Nom affiché
    canonical_key: String,       // Clé de dédup (existant)
    lex_key: String,             // NOUVEAU: clé lexicale normalisée
    type_fine: String,           // Type fin
    er_status: String,           // NOUVEAU: STANDALONE | MERGED | PROPOSAL_PENDING
    merged_into_id: String,      // NOUVEAU: ID cible si MERGED
    merged_from: [String],       // NOUVEAU: Liste des IDs fusionnés
    merged_at: DateTime,         // NOUVEAU: Timestamp merge
    tenant_id: String,
    created_at: DateTime
})

// Nouvelle relation MERGED_INTO
(:CanonicalConcept)-[:MERGED_INTO {
    merged_at: DateTime,
    merge_score: Float,
    merge_reason: String,
    lex_score: Float,
    sem_score: Float,
    compat_score: Float,
    merged_by: String,
    reversible: Boolean
}]->(:CanonicalConcept)

// Nouvelle relation MENTIONED_IN_DOCUMENT
(:CanonicalConcept)-[:MENTIONED_IN_DOCUMENT {
    mention_count: Integer,
    first_seen: DateTime,
    sections: [String]
}]->(:Document)

// Nouvelle relation CO_OCCURS_IN_CORPUS
(:CanonicalConcept)-[:CO_OCCURS_IN_CORPUS {
    weight: Float,
    doc_count: Integer,
    is_weak_link: Boolean,
    computed_at: DateTime
}]->(:CanonicalConcept)

// Nouveau label MergeProposal
(:MergeProposal {
    proposal_id: String,
    source_id: String,
    target_id: String,
    lex_score: Float,
    sem_score: Float,
    compat_score: Float,
    decision: String,
    decision_reason: String,
    created_at: DateTime,
    applied: Boolean,
    applied_at: DateTime,
    applied_by: String
})
```

---

**Fin de spécification**
