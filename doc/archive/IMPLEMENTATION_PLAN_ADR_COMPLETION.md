# Plan d'Implémentation - Complétion des ADR OSMOSE

**Date**: 2026-01-15
**Statut**: En cours d'analyse
**Auteur**: Claude Code

---

## 1. Vue d'ensemble des ADR et leur état

| ADR | Statut Implémentation | Priorité |
|-----|----------------------|----------|
| ADR_STRUCTURAL_GRAPH_FROM_DOCLING | **Partiellement implémenté** | P0 |
| ADR_STRUCTURAL_CONTEXT_ALIGNMENT | **Partiellement implémenté** | P0 |
| ADR_DUAL_CHUNKING_ARCHITECTURE | **Implémenté** | - |
| ADR_UNIFIED_CORPUS_PROMOTION | **Partiellement implémenté** | P1 |
| ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION | **Partiellement implémenté** | P1 |

---

## 2. ADR_STRUCTURAL_GRAPH_FROM_DOCLING (Option C)

### 2.1 Ce qui EST implémenté

| Élément | Fichier | Statut |
|---------|---------|--------|
| `DocItem` nodes | `structural/models.py` | ✅ Créés (23,582 nodes) |
| `DocumentVersion` nodes | `structural/models.py` | ✅ Créés |
| `PageContext` nodes | Navigation layer | ✅ Créés (1,762 nodes) |
| `SectionContext` nodes | Navigation layer | ✅ Créés (4,854 nodes) |
| `TypeAwareChunk` nodes | Chunking | ✅ Créés (4,726 nodes) |
| DocItem de type HEADING | Extraction | ✅ Créés (4,852 nodes) |
| Relations CONTAINS, ON_PAGE | Neo4j | ✅ Créées |

### 2.2 Ce qui N'EST PAS implémenté

#### TÂCHE 2.2.1 - StructuralTopicExtractor doit utiliser Neo4j

**Problème actuel**: `StructuralTopicExtractor` parse le texte brut avec regex Markdown au lieu d'utiliser les DocItem HEADING de Neo4j.

**Fichier**: `src/knowbase/relations/structural_topic_extractor.py`

**Code actuel (lignes 165-195)**:
```python
def _extract_headers(self, text: str) -> List[Dict]:
    # H1 Markdown: # Title
    for match in self.H1_MARKDOWN_PATTERN.finditer(text):
        ...
```

**Code cible**:
```python
def _extract_headers_from_neo4j(self, document_id: str, neo4j_client) -> List[Dict]:
    """
    Récupère les HEADING depuis Neo4j (DocItem.item_type='HEADING').
    """
    query = """
    MATCH (d:DocItem {document_id: $document_id, item_type: 'HEADING'})
    RETURN d.item_id AS item_id,
           d.text AS title,
           d.heading_level AS level,
           d.reading_order_index AS order_idx,
           d.page_no AS page_no
    ORDER BY d.reading_order_index
    """
    result = neo4j_client.execute_query(query, document_id=document_id)
    return [
        {
            "title": r["title"],
            "level": r["level"] or 1,
            "item_id": r["item_id"],
            "order_idx": r["order_idx"],
            "page_no": r["page_no"]
        }
        for r in result
    ]
```

**Modifications requises**:
1. Ajouter paramètre `neo4j_client` à `extract()` et `_extract_headers()`
2. Remplacer parsing regex par requête Neo4j
3. Adapter `_build_topic_hierarchy()` pour utiliser les item_id
4. Modifier `process_document_topics()` pour passer le client Neo4j

**Fichiers à modifier**:
- `src/knowbase/relations/structural_topic_extractor.py`
- `src/knowbase/api/services/pass2_service.py` (appel)

---

#### TÂCHE 2.2.2 - Corriger heading_level dans DocItem

**Problème actuel**: Tous les 4,852 DocItem HEADING ont `heading_level = 1` (pas de hiérarchie H1/H2/H3).

**Diagnostic nécessaire**: Vérifier si Docling extrait les niveaux de heading.

**Fichier à vérifier**: `src/knowbase/structural/` (création DocItem)

**Actions**:
1. Vérifier le mapping `DocItemLabel` → `heading_level` dans le code
2. Si Docling fournit le niveau, corriger le mapping
3. Si Docling ne fournit pas le niveau, implémenter une heuristique basée sur:
   - Position dans la hiérarchie Docling (`parent_item_id`)
   - Taille de police (si disponible dans les metadata)
   - Pattern titre numéroté (1., 1.1, 1.1.1)

**Requête de diagnostic**:
```cypher
MATCH (d:DocItem {item_type: 'HEADING'})
RETURN d.heading_level as level, count(d) as count
ORDER BY level
```

---

#### TÂCHE 2.2.3 - Relation NEXT_IN_READING_ORDER

**Prescrit par ADR (D2)**: Créer des relations `NEXT_IN_READING_ORDER` entre DocItems consécutifs.

**Statut**: Non implémenté

**Requête de création**:
```cypher
MATCH (d1:DocItem {document_id: $doc_id})
MATCH (d2:DocItem {document_id: $doc_id})
WHERE d2.reading_order_index = d1.reading_order_index + 1
MERGE (d1)-[:NEXT_IN_READING_ORDER]->(d2)
```

**Impact**: Facilite la navigation séquentielle dans le document.

---

#### TÂCHE 2.2.4 - Indexes Neo4j manquants (D9)

**Indexes prescrits par ADR**:
```cypher
-- Contraintes uniques (vérifier si existantes)
CREATE CONSTRAINT doc_context_unique IF NOT EXISTS
FOR (d:DocumentContext) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE;

CREATE CONSTRAINT doc_version_unique IF NOT EXISTS
FOR (v:DocumentVersion) REQUIRE (v.tenant_id, v.doc_id, v.doc_version_id) IS UNIQUE;

CREATE CONSTRAINT docitem_unique IF NOT EXISTS
FOR (i:DocItem) REQUIRE (i.tenant_id, i.doc_id, i.doc_version_id, i.item_id) IS UNIQUE;

-- Indexes de performance
CREATE INDEX docitem_order IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.doc_version_id, i.reading_order_index);

CREATE INDEX docitem_type IF NOT EXISTS
FOR (i:DocItem) ON (i.tenant_id, i.item_type);
```

---

## 3. ADR_STRUCTURAL_CONTEXT_ALIGNMENT

### 3.1 Ce qui EST implémenté

| Élément | Statut |
|---------|--------|
| `ProtoConcept.context_id` propriété | ✅ Défini dans le code |
| Modification `corpus_promotion.py` | ✅ Utilise context_id |
| Modification `semantic_consolidation_pass3.py` | ✅ Utilise context_id |

### 3.2 Ce qui N'EST PAS implémenté / À vérifier

#### TÂCHE 3.2.1 - Vérifier que context_id est bien peuplé

**Requête de vérification**:
```cypher
MATCH (p:ProtoConcept {tenant_id: 'default'})
WHERE p.context_id IS NULL
RETURN count(p) as protos_without_context_id
```

**Si > 0**: Exécuter le script de migration `scripts/migrate_context_id.py`

---

#### TÂCHE 3.2.2 - Vérifier MENTIONED_IN sparse

**Problème décrit dans ADR**: Explosion de 2M de relations MENTIONED_IN.

**Requête de vérification**:
```cypher
MATCH ()-[r:MENTIONED_IN]->()
RETURN count(r) as mentioned_in_count
```

**Cible**: < 5,000 relations (vs 2,048,725 avant fix)

---

## 4. ADR_UNIFIED_CORPUS_PROMOTION

### 4.1 Ce qui EST implémenté

| Élément | Fichier | Statut |
|---------|---------|--------|
| `CorpusPromotionEngine` | `corpus_promotion.py` | ✅ Existe |
| Règles de promotion unifiées | `corpus_promotion.py` | ✅ Implémentées |
| Promotion cross-doc avec signal minimal | `corpus_promotion.py` | ✅ Implémentée |

### 4.2 Ce qui N'EST PAS implémenté / À vérifier

#### TÂCHE 4.2.1 - Vérifier la suppression de promotion en Pass 1

**Prescrit par ADR**: Pass 1 ne doit JAMAIS créer de CanonicalConcept.

**Vérification**: Rechercher création de CanonicalConcept dans les fichiers Pass 1:
- `src/knowbase/ingestion/pipelines/`
- `src/knowbase/semantic/`

---

#### TÂCHE 4.2.2 - Invariant 5: Semantic Non-Regression

**Prescrit par ADR**: Tout CanonicalConcept doit avoir ≥1 ProtoConcept avec anchor_status=SPAN.

**Requête de vérification**:
```cypher
MATCH (cc:CanonicalConcept {tenant_id: 'default'})
WHERE NOT EXISTS {
    MATCH (cc)<-[:INSTANCE_OF]-(p:ProtoConcept {anchor_status: 'SPAN'})
}
RETURN cc.label, cc.canonical_id
```

**Cible**: 0 résultats

---

## 5. ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION

### 5.1 Ce qui EST implémenté

| Élément | Statut |
|---------|--------|
| `compute_lex_key()` fonction | ✅ Existe dans `lex_utils.py` |
| `CanonicalConcept.lex_key` propriété | ✅ Existe |

### 5.2 Ce qui N'EST PAS implémenté

#### TÂCHE 5.2.1 - Ajouter lex_key sur ProtoConcept

**Prescrit par ADR**: Stocker `lex_key` sur chaque ProtoConcept pour matching performant.

**Vérification**:
```cypher
MATCH (p:ProtoConcept {tenant_id: 'default'})
WHERE p.lex_key IS NULL
RETURN count(p) as protos_without_lex_key
```

**Si > 0**: Exécuter `scripts/migrate_lex_key.py`

---

#### TÂCHE 5.2.2 - Index Neo4j sur lex_key

**Prescrit par ADR**:
```cypher
CREATE INDEX proto_lex_key IF NOT EXISTS
FOR (p:ProtoConcept) ON (p.tenant_id, p.lex_key);
```

---

#### TÂCHE 5.2.3 - Type Guard Soft

**Prescrit par ADR**: Split buckets par type si divergence > 30%.

**À vérifier dans**: `corpus_promotion.py` - fonction `split_by_type_if_divergent()`

---

#### TÂCHE 5.2.4 - Contrainte unique CanonicalConcept

**Prescrit par ADR**:
```cypher
CREATE CONSTRAINT canonical_unique IF NOT EXISTS
FOR (c:CanonicalConcept)
REQUIRE (c.tenant_id, c.lex_key, c.type_bucket) IS UNIQUE;
```

---

## 6. Récapitulatif des tâches par priorité

### Priorité P0 (Critique - Impacte Pass 2 actuelle)

| # | Tâche | ADR | Effort |
|---|-------|-----|--------|
| 1 | StructuralTopicExtractor → utiliser Neo4j HEADING | STRUCTURAL_GRAPH | Moyen |
| 2 | Corriger heading_level dans DocItem | STRUCTURAL_GRAPH | Moyen |
| 3 | Vérifier context_id peuplé sur ProtoConcept | CONTEXT_ALIGNMENT | Faible |
| 4 | Vérifier MENTIONED_IN sparse | CONTEXT_ALIGNMENT | Faible |

### Priorité P1 (Important - Améliore qualité corpus)

| # | Tâche | ADR | Effort |
|---|-------|-----|--------|
| 5 | Ajouter lex_key sur ProtoConcept | LEX_KEY | Faible |
| 6 | Index Neo4j sur lex_key | LEX_KEY | Faible |
| 7 | Contrainte unique CanonicalConcept | LEX_KEY | Faible |
| 8 | Type Guard Soft | LEX_KEY | Moyen |

### Priorité P2 (Nice-to-have - Améliore navigation)

| # | Tâche | ADR | Effort |
|---|-------|-----|--------|
| 9 | Relation NEXT_IN_READING_ORDER | STRUCTURAL_GRAPH | Faible |
| 10 | Indexes Neo4j manquants (D9) | STRUCTURAL_GRAPH | Faible |

---

## 7. Dépendances entre tâches

```
[1] StructuralTopicExtractor → Neo4j
    └── dépend de [2] heading_level correct

[5] lex_key sur ProtoConcept
    └── prerequis pour [6] Index
    └── prerequis pour [7] Contrainte unique
    └── prerequis pour [8] Type Guard
```

---

## 8. Scripts de vérification à exécuter

### 8.1 Vérification état actuel

```bash
# Vérifier context_id
docker-compose exec app python scripts/migrate_context_id.py --verify

# Vérifier lex_key
docker-compose exec app python scripts/migrate_lex_key.py --verify
```

### 8.2 Requêtes Neo4j de diagnostic

```cypher
-- État des DocItem HEADING
MATCH (d:DocItem {item_type: 'HEADING'})
RETURN d.heading_level as level, count(d) as count
ORDER BY level;

-- ProtoConcept sans context_id
MATCH (p:ProtoConcept {tenant_id: 'default'})
WHERE p.context_id IS NULL
RETURN count(p);

-- ProtoConcept sans lex_key
MATCH (p:ProtoConcept {tenant_id: 'default'})
WHERE p.lex_key IS NULL
RETURN count(p);

-- Compte MENTIONED_IN
MATCH ()-[r:MENTIONED_IN]->()
RETURN count(r);

-- CanonicalConcept sans SPAN
MATCH (cc:CanonicalConcept {tenant_id: 'default'})
WHERE NOT EXISTS {
    MATCH (cc)<-[:INSTANCE_OF]-(p:ProtoConcept {anchor_status: 'SPAN'})
}
RETURN count(cc);
```

---

## 9. Estimation effort total

| Priorité | Tâches | Effort estimé |
|----------|--------|---------------|
| P0 | 4 tâches | ~2-3 jours |
| P1 | 4 tâches | ~1-2 jours |
| P2 | 2 tâches | ~0.5 jour |
| **Total** | **10 tâches** | **~4-6 jours** |

---

## 10. ADR_LINGUISTIC_COREFERENCE_LAYER (Nouvelle Capacité)

> **Note**: Cette section est le fruit d'une collaboration Claude Code + ChatGPT.
> L'approche initiale (pré-traitement pipeline) a été remplacée par une architecture
> plus robuste (couche ontologique) suite à la critique constructive de ChatGPT.

### 10.1 Décision

Créer une **couche linguistique dédiée** à la coréférence (Pass 0.5) qui :

- **Ne modifie JAMAIS le texte source**
- **Persiste uniquement des liens entre spans textuels** (mentions ↔ antécédents / chaînes)
- Est **consommée** par les passes sémantiques et d'extraction (Pass 1 / Pass 2+)
- Applique une politique **conservative + abstention** (aucun "best guess")

Cette couche devient une **structure documentaire** au même titre que la Structural Layer
(DocItem, ordre de lecture), et non un pré-traitement orienté extraction.

### 10.2 Motivation

**Problème identifié**: Lors de l'extraction de relations, les pronoms ne sont pas résolus :

```
Texte: "La norme TLS permet de sécuriser les échanges. Elle peut être utilisée avec AES256."

Extraction actuelle:  (???) --[UTILISÉE_AVEC]--> (AES256)
Extraction attendue:  (TLS) --[UTILISÉE_AVEC]--> (AES256)
```

**Pourquoi une couche et pas un pré-traitement ?**

| Approche | Problème |
|----------|----------|
| Pré-traitement (texte modifié) | Couplé à l'extraction, non réutilisable, audit limité |
| **Couche ontologique** | Inspectable, comparable, réutilisable, gouvernable |

> *"Osmosis n'est pas un extracteur de relations. C'est un système de connaissance
> fondé sur la structure documentaire."* — La coréférence est un fait linguistique
> du document, donc elle mérite un modèle, une couche, une gouvernance.

### 10.3 Invariants Spécifiques (Layer-level)

En plus des invariants OSMOSE globaux, cette couche impose :

| Invariant | Description |
|-----------|-------------|
| **L1 — Evidence-preserving** | Chaque mention stockée pointe vers un span exact (offsets) dans un texte original |
| **L2 — No generated evidence** | Aucun "resolved text" n'est persisté comme evidence. Substitutions = runtime only |
| **L3 — Closed-world disambiguation** | LLM ne peut choisir que parmi candidats locaux, sinon ABSTAIN |
| **L4 — Abstention-first** | Ambiguïté, longue portée, bridging → ABSTAIN |
| **L5 — Linguistic-only** | Les liens COREFERS_TO n'impliquent aucune relation conceptuelle (is-a, uses, etc.) |

### 10.4 Modèle de Données Neo4j

#### 10.4.1 Nodes

##### (A) `MentionSpan`

Représente une mention textuelle (pronom, GN défini, nom propre).

```cypher
(:MentionSpan {
    tenant_id: String,
    doc_id: String,
    doc_version_id: String,
    docitem_id: String,           -- Ancrage principal (vérité structurelle)
    chunk_id: String,             -- Lien secondaire (consommation)
    span_start: Integer,          -- Offset char début
    span_end: Integer,            -- Offset char fin
    surface: String,              -- Texte exact ("elle", "TLS", etc.)
    mention_type: String,         -- PRONOUN | NP | PROPER | OTHER
    lang: String,                 -- fr | en | de | it
    sentence_index: Integer,
    created_at: DateTime
})
```

**Contrainte d'unicité**:
```cypher
CREATE CONSTRAINT mentionspan_unique IF NOT EXISTS
FOR (m:MentionSpan) REQUIRE (m.tenant_id, m.doc_version_id, m.docitem_id, m.span_start, m.span_end) IS UNIQUE;
```

##### (B) `CoreferenceChain`

Un cluster (chaîne) de mentions dans un document.

```cypher
(:CoreferenceChain {
    tenant_id: String,
    doc_id: String,
    doc_version_id: String,
    chain_id: String,             -- UUID
    method: String,               -- spacy_coref | coreferee | rule_based | llm_arbiter
    confidence: Float,            -- 0.0-1.0 (agrégé)
    created_at: DateTime
})
```

##### (C) `CorefDecision`

Objet d'audit pour chaque décision de résolution (standard, pas optionnel).

```cypher
(:CorefDecision {
    tenant_id: String,
    doc_version_id: String,
    decision_id: String,          -- UUID
    mention_span_key: String,     -- Référence vers MentionSpan
    candidate_count: Integer,
    chosen_candidate_key: String, -- Nullable si ABSTAIN
    decision_type: String,        -- RESOLVED | ABSTAIN | NON_REFERENTIAL
    confidence: Float,
    method: String,
    reason_code: String,          -- UNAMBIGUOUS | AMBIGUOUS | NO_CANDIDATE | IMPERSONAL | ...
    created_at: DateTime
})
```

#### 10.4.2 Relations

```cypher
-- Appartenance à une chaîne
(:CoreferenceChain)-[:HAS_MENTION {role: "REPRESENTATIVE"|"MEMBER"}]->(:MentionSpan)

-- Lien direct pronom → antécédent
(:MentionSpan)-[:COREFERS_TO {
    method: String,
    confidence: Float,
    scope: String,                -- same_sentence | prev_sentence | prev_chunk
    window_chars: Integer,
    created_at: DateTime
}]->(:MentionSpan)

-- Ancrage vers structure existante
(:MentionSpan)-[:MENTION_IN_DOCITEM]->(:DocItem)
(:MentionSpan)-[:MENTION_IN_CHUNK]->(:TypeAwareChunk)

-- Lien vers ProtoConcept (conditionnel mais systématique quand applicable)
(:MentionSpan)-[:MATCHES_PROTOCONCEPT {
    confidence: Float,
    method: String
}]->(:ProtoConcept)
```

> **⚠️ NOTE DE GOUVERNANCE - MATCHES_PROTOCONCEPT**
>
> Ce lien exprime un **alignement lexical/ancré**, PAS une identité ontologique.
> - ✅ "Cette mention textuelle correspond au même span qu'un ProtoConcept"
> - ❌ "Cette mention EST ce concept" (interprétation interdite)
>
> Les passes aval (Pass 2+) ne doivent JAMAIS interpréter `MATCHES_PROTOCONCEPT`
> comme une promotion sémantique. C'est un raccourci de navigation, pas une assertion.

#### 10.4.3 Indexes de Performance

```cypher
CREATE INDEX mentionspan_doc IF NOT EXISTS
FOR (m:MentionSpan) ON (m.tenant_id, m.doc_version_id);

CREATE INDEX mentionspan_type IF NOT EXISTS
FOR (m:MentionSpan) ON (m.tenant_id, m.mention_type);

CREATE INDEX corefchain_doc IF NOT EXISTS
FOR (c:CoreferenceChain) ON (c.tenant_id, c.doc_version_id);
```

### 10.5 Stratégie Multilingue

#### 10.5.1 Principe : Engine-per-Language

Aucun modèle multilingue n'est à la fois précis, maintenu et robuste sur FR/DE/IT.
OSMOSE adopte une stratégie **engine par langue** avec abstraction obligatoire.

#### 10.5.2 Table des Engines par Langue

| Langue | Engine Principal | Fallback | Statut |
|--------|------------------|----------|--------|
| **EN** | spaCy CoreferenceResolver / F-Coref | Rule-based | ✅ Priorité 1 |
| **FR** | Coreferee (expérimental) | Rule-based + abstention | ⚠️ Priorité 2 |
| **DE** | CoreNLP / Coreferee | Rule-based + abstention | 📋 Priorité 3 |
| **IT** | Rule-based only | Abstention | 📋 Priorité 4 |

> **⚠️ COREFEREE - Contrainte de Swappabilité**
>
> Coreferee (dernier release 2022) est classé **expérimental** et doit rester
> **swappable sans douleur**. Concrètement :
> - Aucune dépendance fonctionnelle critique sur Coreferee
> - Le fallback rule-based doit toujours être opérationnel
> - Si Coreferee devient non-maintenu, le swap vers rules-only est immédiat
>
> L'interface `ICorefEngine` garantit cette swappabilité.

#### 10.5.3 Interface d'Abstraction

```python
class ICorefEngine(Protocol):
    """Interface commune pour tous les engines de coréférence."""

    def resolve(
        self,
        document_text: str,
        chunks: List[Dict],
        lang: str
    ) -> List[CoreferenceCluster]:
        """
        Résout les coréférences dans un document.

        Returns:
            Liste de clusters (chaînes de mentions).
        """
        ...

# Implémentations
class SpacyCorefEngine(ICorefEngine): ...      # EN (maintenu, recommandé)
class FCorefEngine(ICorefEngine): ...          # EN (performance)
class CorefereeEngine(ICorefEngine): ...       # FR/EN/DE (maintenance ⚠️)
class RuleBasedEngine(ICorefEngine): ...       # Fallback universel
```

#### 10.5.4 Fallback et Abstention

**Règle** : Absence d'engine ≠ échec. Cela signifie CorefGraph pauvre mais épistémiquement propre.

```python
def get_engine_for_language(lang: str) -> ICorefEngine:
    """Retourne l'engine approprié pour la langue."""
    engines = {
        "en": SpacyCorefEngine(),
        "fr": CorefereeEngine() if COREFEREE_AVAILABLE else RuleBasedEngine(),
        "de": CorefereeEngine() if COREFEREE_AVAILABLE else RuleBasedEngine(),
        "it": RuleBasedEngine(),
    }
    return engines.get(lang, RuleBasedEngine())
```

#### 10.5.5 Détection de Langue

- **Par défaut** : `doc_language` au niveau `DocumentVersion`
- **Exception** : `chunk_language` si document mixte détecté (score < seuil ou hétérogène)

### 10.6 Intégration Pipeline OSMOSE

```
┌─────────────────────────────────────────────────────────────┐
│  Pass 0 - Structural Layer (existant)                       │
│  Docling → DocItem, PageContext, SectionContext             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 0.5 - Linguistic Coreference Layer (NOUVEAU)          │
│                                                             │
│  Entrées:                                                   │
│  - Texte chunké (TypeAwareChunk)                           │
│  - Contexte local (prev chunk / fenêtre)                   │
│  - Langue (doc_language ou chunk_language)                 │
│  - DocItem reading order                                    │
│                                                             │
│  Traitement:                                                │
│  1. Détection mentions candidates                           │
│  2. Coref engine (spaCy/Coreferee/rules selon langue)      │
│  3. Gating policy (conservative + abstention)              │
│  4. Persistance: MentionSpan / Chain / CorefDecision       │
│                                                             │
│  Sorties:                                                   │
│  - CorefGraph en Neo4j                                      │
│  - Métriques (taux abstention, chaînes/doc)                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 1 - Semantic Layer (consommation)                     │
│  - Consulte CorefGraph pour alignement ProtoConcept        │
│  - Crée MATCHES_PROTOCONCEPT si antécédent = concept ancré │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Pass 2+ - Relation Extraction (consommation runtime)       │
│  - Consulte CorefGraph                                      │
│  - Construit "vue résolue" temporaire (annotations)        │
│  - NE PERSISTE JAMAIS le texte modifié                     │
└─────────────────────────────────────────────────────────────┘
```

### 10.7 Gating Policy (Critères d'Admissibilité)

#### Résolution Admissible

Autoriser `COREFERS_TO` si :
- Candidat dans fenêtre courte (same/prev sentence, ou prev chunk immédiat)
- Compatibilité morpho-syntaxique (FR : genre/nombre quand possible)
- Score engine ≥ 0.85
- Pas de signal "non référentiel" (il pleut, it rains, c'est X)

#### Abstention Obligatoire

- Plusieurs candidats valides (ambiguïté)
- Distance trop grande sans support structurel
- "Bridging" (the device → the server) non explicitement coréférentiel
- Candidats hors liste (si LLM arbiter)

### 10.8 Consommation par l'Extracteur de Relations

**Point d'insertion** : `extract_relations_chunk_aware_async()`

**Fichier** : `src/knowbase/relations/llm_relation_extractor.py`

```python
async def extract_relations_chunk_aware_async(
    self,
    document_chunks: List[Dict[str, Any]],
    all_concepts: List[Dict[str, Any]],
    ...
) -> TypeFirstExtractionResult:

    # NOUVEAU: Consulter la CorefGraph (ne modifie pas les chunks)
    if self.use_coref_layer:
        coref_graph = self._load_coref_graph(doc_version_id)

        # Construire une vue annotée TEMPORAIRE pour le LLM
        # Format: "Elle [→TLS] peut être utilisée..."
        annotated_chunks = self._annotate_with_coref(
            document_chunks,
            coref_graph
        )
        # Cette vue n'est JAMAIS persistée
    else:
        annotated_chunks = document_chunks

    # ... suite du code existant (extraction sur annotated_chunks)
```

### 10.9 Fichiers à Créer/Modifier

| Fichier | Action | Description |
|---------|--------|-------------|
| `src/knowbase/linguistic/coref_models.py` | **Créer** | Modèles de données (MentionSpan, CoreferenceChain, CorefDecision) |
| `src/knowbase/linguistic/coref_engine.py` | **Créer** | Interface ICorefEngine + implémentations |
| `src/knowbase/linguistic/coref_persist.py` | **Créer** | Persistance Neo4j de la CorefGraph |
| `src/knowbase/linguistic/coref_gating.py` | **Créer** | Politique de gating (conservative + abstention) |
| `src/knowbase/ingestion/pipelines/pass05_coref.py` | **Créer** | Pipeline Pass 0.5 |
| `src/knowbase/relations/llm_relation_extractor.py` | **Modifier** | Consommation CorefGraph |
| `tests/linguistic/test_coref_layer.py` | **Créer** | Tests unitaires |

### 10.10 Tests de Validation

```python
# tests/linguistic/test_coref_layer.py

def test_coref_creates_mentionspan_not_modified_text():
    """La coréférence crée des MentionSpan, pas de texte modifié."""
    engine = SpacyCorefEngine()
    result = engine.resolve("TLS secures data. It uses encryption.", ...)

    # Vérifier que des MentionSpan sont créés
    assert len(result.mention_spans) >= 2
    # Vérifier qu'aucun texte modifié n'est retourné
    assert result.modified_text is None

def test_coref_links_to_docitem():
    """Les MentionSpan sont ancrés sur DocItem (vérité structurelle)."""
    # ... test ancrage DocItem

def test_abstention_on_ambiguity():
    """Abstention quand plusieurs antécédents possibles."""
    text = "TLS and AES256 are standards. It is recommended."
    result = resolve_coref(text, lang="en")

    decision = result.decisions[0]
    assert decision.decision_type == "ABSTAIN"
    assert decision.reason_code == "AMBIGUOUS"

def test_matches_protoconcept_created():
    """MATCHES_PROTOCONCEPT créé quand antécédent = ProtoConcept ancré."""
    # ... test lien vers ProtoConcept

def test_engine_fallback_for_unsupported_language():
    """Fallback rule-based pour langue non supportée."""
    engine = get_engine_for_language("it")
    assert isinstance(engine, RuleBasedEngine)
```

### 10.11 Métriques de Succès

> **Note** : Ces métriques sont **observationnelles**, pas contractuelles.
> Elles servent à calibrer le système, pas à créer une pression vers le "forçage" de résolutions.

| Métrique | Cible | Type |
|----------|-------|------|
| Taux d'abstention | 10-30% | Observationnel |
| Chaînes par document | 5-20 (selon taille doc) | Observationnel |
| MATCHES_PROTOCONCEPT créés | ~80% des antécédents résolus (EN), ~60% (FR/DE) | Observationnel, différencié par langue |
| Temps Pass 0.5 | < 5s par document | Technique |

**Important** : Si le taux de MATCHES_PROTOCONCEPT est bas, cela indique un désalignement
chunking/ancrage, PAS un échec de la coréférence. Ne jamais "forcer" des matchs pour
atteindre un KPI.

### 10.12 Priorité et Effort

| Aspect | Évaluation |
|--------|------------|
| **Priorité** | P1 (Améliore qualité relations + architecture propre) |
| **Effort** | Élevé (5-7 jours avec tests et intégration) |
| **Dépendances** | Pass 0 (Structural Layer) doit être stable |
| **Risque** | Moyen (dépendance engines OSS, mais fallback prévu) |

---

## 11. Récapitulatif Mis à Jour

### Toutes les Tâches par Priorité

| # | Tâche | ADR/Capacité | Priorité | Effort |
|---|-------|--------------|----------|--------|
| 1 | StructuralTopicExtractor → Neo4j HEADING | STRUCTURAL_GRAPH | P0 | Moyen |
| 2 | Corriger heading_level dans DocItem | STRUCTURAL_GRAPH | P0 | Moyen |
| 3 | Vérifier context_id sur ProtoConcept | CONTEXT_ALIGNMENT | P0 | Faible |
| 4 | Vérifier MENTIONED_IN sparse | CONTEXT_ALIGNMENT | P0 | Faible |
| 5 | Ajouter lex_key sur ProtoConcept | LEX_KEY | P1 | Faible |
| 6 | Index Neo4j sur lex_key | LEX_KEY | P1 | Faible |
| 7 | Contrainte unique CanonicalConcept | LEX_KEY | P1 | Faible |
| 8 | Type Guard Soft | LEX_KEY | P1 | Moyen |
| 9 | **Linguistic Coreference Layer (Pass 0.5)** | **NOUVELLE** | **P1** | **Élevé** |
| 10 | Relation NEXT_IN_READING_ORDER | STRUCTURAL_GRAPH | P2 | Faible |
| 11 | Indexes Neo4j manquants (D9) | STRUCTURAL_GRAPH | P2 | Faible |

### Effort Total Révisé

| Priorité | Tâches | Effort estimé |
|----------|--------|---------------|
| P0 | 4 tâches | ~2-3 jours |
| P1 | **5 tâches** | ~5-7 jours (dont 5-7j pour Coref Layer) |
| P2 | 2 tâches | ~0.5 jour |
| **Total** | **11 tâches** | **~8-11 jours** |

### Note sur la Linguistic Coreference Layer

Cette capacité est le fruit d'une **collaboration Claude Code + ChatGPT** :
- **Proposition initiale** (Claude) : Pré-traitement pipeline avec texte modifié
- **Critique constructive** (ChatGPT) : Devrait être une couche ontologique
- **Décision finale** : Couche structurelle (Pass 0.5) avec MentionSpan/CorefLink/CorefDecision

**Points clés retenus** :
- Ne modifie JAMAIS le texte source (invariant L2)
- Engine-per-language avec fallback rule-based
- Abstention-first (pas de "best guess")
- Consommation runtime par les passes suivantes

---

## Changelog

| Date | Auteur | Modification |
|------|--------|--------------|
| 2026-01-15 | Claude Code | Création initiale du document |
| 2026-01-15 | Claude Code | Ajout Section 10 - Résolution Linguistique d'Anaphores (approche initiale) |
| 2026-01-15 | Claude Code + ChatGPT | Refonte Section 10 - ADR_LINGUISTIC_COREFERENCE_LAYER (couche ontologique) |
| 2026-01-15 | Claude Code + ChatGPT | Ajout stratégie multilingue (engine-per-language, fallback, abstention) |
| 2026-01-15 | Claude Code | Intégration review ChatGPT : note gouvernance MATCHES_PROTOCONCEPT |
| 2026-01-15 | Claude Code | Intégration review ChatGPT : métriques observationnelles (pas KPI durs) |
| 2026-01-15 | Claude Code | Intégration review ChatGPT : contrainte swappabilité Coreferee |
