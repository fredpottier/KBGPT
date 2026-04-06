# Phase 2.8 - ID-First Relation Extraction (Version Définitive)

**Date**: 2025-12-21
**Statut**: Implémentation en cours
**Auteurs**: Claude Code + ChatGPT (collaboration)

---

## 1. Contexte et Problème

### Situation actuelle

Le pipeline OSMOSE Phase 2.8 extrait des relations sémantiques entre concepts et les stocke comme `RawAssertion` nodes dans Neo4j.

**Flux actuel (problématique)** :

1. Le `LLMRelationExtractor` envoie au LLM la liste des concepts + le texte
2. Le LLM retourne des relations avec des **noms** de concepts :
   ```json
   {
     "subject_concept": "EDPB",
     "object_concept": "GDPR",
     "predicate_raw": "enforces"
   }
   ```
3. Le supervisor tente un **matching exact** (case-insensitive) pour résoudre les noms → IDs
4. Si "EDPB" ≠ "European Data Protection Board" → **relation jetée**

### Impact mesuré

- 45 CanonicalConcepts créés
- Seulement **8 RawAssertions** créées
- **~82% des relations perdues** à cause du matching strict

### Cause racine

Le LLM "parle en noms/mentions" tandis que Neo4j "pense en IDs".
Le matching textuel est intrinsèquement fragile (acronymes, variantes linguistiques, typos).

---

## 2. Solution Définitive : Index-Based ID-First Extraction

### Principe Core

1. **Catalogue fermé avec index numériques** : Le LLM reçoit un catalogue compact `c1, c2, c3...`
2. **Le LLM retourne des index**, pas des noms ni des UUIDs
3. **Validation closed-world stricte** : index ∉ catalogue → relation rejetée
4. **UnresolvedMention nodes** : Stockage Neo4j (pas juste log) pour enrichissement futur

### Pourquoi Index (c1, c2...) plutôt que UUIDs ?

| Aspect | UUIDs (cc_01J...) | Index (c1, c2...) |
|--------|-------------------|-------------------|
| Tokens consommés | ~20 tokens/ID | 2-3 tokens/ID |
| Robustesse LLM | Risque troncation/erreur | Très fiable |
| Mapping | Direct | Nécessite index→ID map |
| Lisibilité prompt | Complexe | Simple |

**Choix définitif** : Index numériques pour économie de tokens et robustesse.

### Architecture Finale

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Pipeline Relation                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  state.promoted (concepts)                                          │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────────┐                                               │
│  │ Build Catalogue  │  → Catalogue JSON avec index c1, c2, c3...   │
│  │ + Index Map      │  → index_to_concept_id: {c1: cc_123, ...}    │
│  └────────┬─────────┘                                               │
│           │                                                         │
│           ▼                                                         │
│  ┌──────────────────┐                                               │
│  │   LLM Prompt V3  │  → Texte + Catalogue fermé                   │
│  │   (ID-First)     │  → "Tu dois utiliser UNIQUEMENT ces index"   │
│  └────────┬─────────┘                                               │
│           │                                                         │
│           ▼                                                         │
│  ┌──────────────────┐     relations: [{subject_id: "c1", ...}]     │
│  │   LLM Response   │ ──►                                           │
│  │                  │     unresolved_mentions: [{mention: "EDPB"}] │
│  └────────┬─────────┘                                               │
│           │                                                         │
│           ▼                                                         │
│  ┌──────────────────┐                                               │
│  │ Validation       │  → subject_id ∈ catalogue ? object_id ∈ ?    │
│  │ Closed-World     │  → Si NON → log warning + skip               │
│  └────────┬─────────┘                                               │
│           │                                                         │
│           ▼                                                         │
│  ┌──────────────────┐                                               │
│  │ Index → UUID     │  → c1 → cc_01JGABC..., c2 → cc_01JDEF...     │
│  │ Resolution       │  → Utilise index_to_concept_id map           │
│  └────────┬─────────┘                                               │
│           │                                                         │
│           ├──────────────────────────────────┐                      │
│           ▼                                  ▼                      │
│  ┌──────────────────┐               ┌──────────────────┐            │
│  │ RawAssertion     │               │ UnresolvedMention│            │
│  │ Writer (Neo4j)   │               │ Writer (Neo4j)   │            │
│  └──────────────────┘               └──────────────────┘            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Architecture Technique Définitive

### 3.1 Catalogue avec Index (Format Envoyé au LLM)

```json
[
  {"idx": "c1", "name": "European Data Protection Board", "aliases": ["EDPB"], "type": "organization"},
  {"idx": "c2", "name": "General Data Protection Regulation", "aliases": ["GDPR", "RGPD"], "type": "regulation"},
  {"idx": "c3", "name": "Data Protection Impact Assessment", "aliases": ["DPIA"], "type": "process"}
]
```

**Mapping côté serveur** (non envoyé au LLM) :
```python
index_to_concept_id = {
    "c1": "cc_01JGABC123DEF456",  # EDPB
    "c2": "cc_01JGDEF789ABC012",  # GDPR
    "c3": "cc_01JGHIJ345KLM678",  # DPIA
}
```

### 3.2 Prompt V3 Définitif (Index-Based ID-First)

```text
Tu es un expert en extraction de relations sémantiques entre concepts.

CONTEXTE DU DOCUMENT (extrait) :
{full_text_excerpt}

CATALOGUE DE CONCEPTS AUTORISÉS (ensemble fermé) :
{concept_catalog_json}

RÈGLES STRICTES - À RESPECTER IMPÉRATIVEMENT :

1) subject_id et object_id = UNIQUEMENT des index du catalogue (c1, c2, c3, etc.)
2) Si une entité mentionnée dans le texte N'EST PAS dans le catalogue :
   → NE CRÉE PAS de relation avec elle
   → AJOUTE-LA dans "unresolved_mentions"
3) predicate_raw = verbe/prédicat EXACT tel qu'il apparaît dans le texte
4) evidence = citation EXACTE du texte (copier-coller, pas de paraphrase)
5) Retourne UNIQUEMENT un JSON valide. Pas de texte avant ou après.

DÉTECTION DES FLAGS :
- is_negated: true si relation niée ("ne nécessite PAS", "n'utilise pas", "does not require")
- is_hedged: true si incertitude ("peut nécessiter", "pourrait", "might", "may")
- is_conditional: true si condition ("si X alors", "when", "in case of")
- cross_sentence: true si la relation traverse plusieurs phrases

FORMAT DE SORTIE JSON :
{
  "relations": [
    {
      "subject_id": "c1",
      "object_id": "c2",
      "predicate_raw": "requires compliance with",
      "evidence": "EDPB requires compliance with GDPR for all EU organizations.",
      "confidence": 0.95,
      "flags": {
        "is_negated": false,
        "is_hedged": false,
        "is_conditional": false,
        "cross_sentence": false
      }
    }
  ],
  "unresolved_mentions": [
    {
      "mention": "ISO 27001",
      "context": "GDPR compliance may also require ISO 27001 certification.",
      "suggested_type": "standard"
    }
  ]
}

Si aucune relation détectée : {"relations": [], "unresolved_mentions": []}
```

### 3.3 Validation Closed-World Stricte

```python
def validate_relation_strict(
    rel_data: Dict,
    valid_indices: Set[str]
) -> Tuple[bool, Optional[str]]:
    """
    Validation closed-world : les index DOIVENT être dans le catalogue.

    Returns:
        (is_valid, error_message)
    """
    subject_id = rel_data.get("subject_id", "")
    object_id = rel_data.get("object_id", "")

    if subject_id not in valid_indices:
        return False, f"Invalid subject_id '{subject_id}' - not in catalogue"

    if object_id not in valid_indices:
        return False, f"Invalid object_id '{object_id}' - not in catalogue"

    if subject_id == object_id:
        return False, f"Self-relation not allowed: {subject_id}"

    return True, None
```

### 3.4 UnresolvedMention Node (Neo4j)

**Schéma Neo4j** :

```cypher
CREATE (um:UnresolvedMention {
    mention_id: $mention_id,           // ULID unique
    tenant_id: $tenant_id,
    mention_text: $mention_text,       // "ISO 27001"
    context: $context,                 // Evidence/phrase où apparaît
    suggested_type: $suggested_type,   // Type suggéré par LLM (optionnel)
    source_doc_id: $source_doc_id,
    source_chunk_id: $source_chunk_id,
    occurrence_count: 1,               // Incrémenté si même mention
    status: "pending",                 // pending | promoted | rejected
    created_at: datetime(),
    updated_at: datetime()
})

// Index pour recherche et dédup
CREATE INDEX um_mention_tenant IF NOT EXISTS
FOR (um:UnresolvedMention) ON (um.mention_text, um.tenant_id)
```

**Logique de gestion** :

```python
def write_unresolved_mention(
    mention_data: Dict,
    document_id: str,
    chunk_id: str,
    tenant_id: str
) -> str:
    """
    Écrit ou met à jour UnresolvedMention dans Neo4j.
    Si mention existe déjà → incrémente occurrence_count.

    Returns:
        mention_id
    """
    mention_text = mention_data.get("mention", "").strip()

    # MERGE pour dédup sur (mention_text, tenant_id)
    query = """
    MERGE (um:UnresolvedMention {
        mention_text: $mention_text,
        tenant_id: $tenant_id
    })
    ON CREATE SET
        um.mention_id = $mention_id,
        um.context = $context,
        um.suggested_type = $suggested_type,
        um.source_doc_id = $source_doc_id,
        um.source_chunk_id = $source_chunk_id,
        um.occurrence_count = 1,
        um.status = "pending",
        um.created_at = datetime(),
        um.updated_at = datetime()
    ON MATCH SET
        um.occurrence_count = um.occurrence_count + 1,
        um.updated_at = datetime()
    RETURN um.mention_id AS id
    """
    # ...
```

---

## 4. Modifications par Fichier

### 4.1 `src/knowbase/relations/llm_relation_extractor.py`

| Modification | Description |
|--------------|-------------|
| `RELATION_EXTRACTION_PROMPT_V3` | Prompt index-based (c1, c2...) |
| `_build_concept_catalogue()` | Génère JSON + index_to_concept_id map |
| `_create_relation_from_llm_v3()` | Parse avec index → concept_id resolution |
| `_validate_relation_closed_world()` | Validation stricte indices |
| `extract_relations_v3()` | Nouvelle méthode retournant (relations, unresolved) |
| Paramètre `use_id_first=True` | Nouveau mode par défaut |

### 4.2 `src/knowbase/relations/unresolved_mention_writer.py` (NOUVEAU)

| Élément | Description |
|---------|-------------|
| `UnresolvedMentionWriter` | Classe d'écriture Neo4j |
| `write_mention()` | MERGE avec dedup |
| `get_pending_mentions()` | Récupère mentions à reviewer |
| `promote_to_concept()` | Transforme mention en CanonicalConcept |

### 4.3 `src/knowbase/agents/supervisor/supervisor.py`

| Modification | Description |
|--------------|-------------|
| Supprimer `concept_id_map` | Plus besoin de map nom→id |
| Supprimer `_find_concept_by_name()` | Plus de matching textuel |
| Utiliser `extract_relations_v3()` | Appel nouvelle méthode |
| Passer `state.promoted` | Pour construction catalogue |
| Appeler `UnresolvedMentionWriter` | Écrire les mentions non résolues |

### 4.4 `src/knowbase/relations/raw_assertion_writer.py`

| Modification | Description |
|--------------|-------------|
| Aucune majeure | Reçoit déjà des IDs valides (concept_id résolus) |
| Garder `_concept_exists()` | Double vérification (défense en profondeur) |

---

## 5. Plan d'Implémentation

### Étape 1 : Prompt V3 + Catalogue Index-Based

1. Créer `RELATION_EXTRACTION_PROMPT_V3` avec format index (c1, c2...)
2. Implémenter `_build_concept_catalogue(concepts) -> (catalogue_json, index_map)`
3. Implémenter validation closed-world

### Étape 2 : Extract Relations V3

1. Créer `extract_relations_v3()` qui retourne `(relations, unresolved_mentions)`
2. Implémenter `_create_relation_from_llm_v3()` avec index resolution
3. Ajouter paramètre `use_id_first=True` (nouveau défaut)

### Étape 3 : UnresolvedMention Writer

1. Créer `src/knowbase/relations/unresolved_mention_writer.py`
2. Implémenter MERGE Neo4j avec dedup
3. Ajouter getter pour mentions pending

### Étape 4 : Intégration Supervisor

1. Supprimer ancien code de matching par nom
2. Appeler `extract_relations_v3()`
3. Écrire RawAssertions avec IDs résolus
4. Écrire UnresolvedMentions

### Étape 5 : Tests et Validation

1. Purger Neo4j (RawAssertions + UnresolvedMentions)
2. Relancer import sur 10+ documents
3. Vérifier ratio RawAssertions créées / relations LLM (cible: >90%)
4. Vérifier UnresolvedMentions capturées

---

## 6. Métriques de Succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| Taux relations conservées | ~18% | >90% |
| Relations avec IDs invalides | N/A | 0% |
| UnresolvedMentions capturées | 0 | 100% des mentions hors catalogue |
| Temps d'extraction | ~X sec | Équivalent (index = moins de tokens) |

---

## 7. Limitation Identifiée : Document-Level

### 7.1 Problème

Cette spécification définit une extraction au niveau **DOCUMENT** : le catalogue contient tous les concepts du document entier.

**Constat après implémentation (2025-12-21):**
- Gros documents (400+ concepts) → seulement 11-16% des concepts utilisés
- Petits documents (39 concepts) → 82% utilisés
- **85% des CanonicalConcepts restent isolés** (sans relations)

### 7.2 Solution → Phase 2.9

L'architecture OSMOSE prévoyait une extraction par **SEGMENT** (Topic Segmentation → Extraction par segment → PatternMiner cross-segment).

Voir **`doc/ongoing/PHASE2.9_SEGMENT_LEVEL_RELATIONS.md`** pour le plan d'implémentation.

---

## 8. Évolutions Futures

1. ~~**Top-K Global Concepts**~~ → Intégré dans Phase 2.9 (catalogue hybride)
2. **Auto-promotion UnresolvedMention** : Si occurrence_count > seuil → créer CanonicalConcept automatiquement
3. **UI Admin UnresolvedMentions** : Interface pour reviewer et promouvoir manuellement
4. **Evidence Validation** : Vérifier que evidence est substring du chunk (optionnel, peut être strict ou permissif)

---

## 9. Références

- Conversation Claude Code + ChatGPT (2025-12-21)
- Phase 2.8 RawAssertion Architecture Spec
- `src/knowbase/relations/types.py` : RawAssertion, RawAssertionFlags
