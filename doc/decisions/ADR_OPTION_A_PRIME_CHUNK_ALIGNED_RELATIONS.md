# ADR Addendum : Option A' - Extraction de Relations Alignée sur DocumentChunks

**Date** : 2024-12-30
**Statut** : Accepté
**Contexte** : Phase 2 - Hybrid Anchor Model - Pass 1.5 Relations
**Auteurs** : Claude Code + ChatGPT (analyse collaborative)

---

## 1. Contexte et Problème

### Symptôme observé
L'extraction de relations via vLLM (Qwen 8192 tokens) échoue systématiquement :
```
This model's maximum context length is 8192 tokens.
However, your request has 21237 input tokens.
```

### Cause racine identifiée
**Deux systèmes de chunking concurrents** créent une incohérence architecturale :

| Système | Taille | Utilisation | Problème |
|---------|--------|-------------|----------|
| `HybridAnchorChunker` | 256 tokens | Qdrant, anchors, `anchored_concepts` | Unité canonique ✅ |
| `_chunk_text_for_v3()` | 3000 chars | Extraction relations | Système parallèle ❌ |

Le catalogue de concepts est construit avec TOUS les concepts du document (~600+), générant ~21000 tokens au lieu de respecter la limite de 8192.

---

## 2. Décision : Option A' - Alignement sur DocumentChunks

### Énoncé de la décision

> **L'extraction de relations DOIT opérer sur les DocumentChunks (unités canoniques).
> Tout chunking indépendant du full_text pour les relations est INTERDIT dans l'architecture cible.**

### Principe de la solution

1. **Itérer sur les DocumentChunks** (pas sur `_chunk_text_for_v3`)
2. **Fenêtre de contexte [i-1, i, i+1]** pour chaque chunk central `i`
3. **Shortlist de concepts en 3 niveaux** (pas anchors-only)
4. **Closed-world avec doc_ids stables** (d001, d002...)

---

## 3. Shortlist de Concepts - 3 Niveaux

```
S_anchor  = concepts ancrés dans fenêtre [i-1, i, i+1]     # Signal FORT
S_doc_top = top K concepts doc-level (fréquence anchors)   # Signal faible
S_lex     = lexical fallback (word boundaries + aliases)   # Dernier recours

Catalogue = dedup(S_anchor ∪ S_doc_top ∪ S_lex) ≤ 100 concepts
```

### Règles de composition

- `S_anchor` : TOUJOURS inclus (concepts des `anchored_concepts` des 3 chunks)
- `S_doc_top` : top 10-15 concepts pivots du document entier
- `S_lex` : UNIQUEMENT si `|S_anchor| < 8` (alerte : extraction anchors défaillante)

---

## 4. Invariants Architecturaux

### Invariant 1 : Unité canonique unique
```
Relations extraction must operate on DocumentChunks,
not raw full_text chunking.
```

### Invariant 2 : Anchors-first, pas anchors-only
```
Anchors-first selection, lexical-only forbidden except fallback.
```

### Invariant 3 : Limite du catalogue
```
Max concepts in prompt ≤ 100
```

### Invariant 4 : Evidence obligatoire
```
No relation emitted without text evidence in window.
L'extraction doit retourner un `evidence` (quote) validable.
```

### Invariant 5 : doc_id déterministe
```
doc_ids (d001, d002...) attribués par tri stable des concepts
avant attribution (par canonical_id ou (label, canonical_id)).
```

---

## 5. Fenêtre de Contexte [i-1, i, i+1]

### Comportement standard
Pour le chunk central `i`, la fenêtre inclut :
- Chunk `i-1` (contexte précédent)
- Chunk `i` (chunk central)
- Chunk `i+1` (contexte suivant)

### Cas aux bords
- `i = 0` → fenêtre `[0, 1]`
- `i = last` → fenêtre `[last-1, last]`

### Estimation tokens
| Composant | Tokens estimés |
|-----------|----------------|
| Texte 3 chunks | ~750 tokens |
| Catalogue 40-60 concepts | ~1200 tokens |
| Prompt système | ~800 tokens |
| **TOTAL** | **~2750 tokens** ✅ |

---

## 6. Cohérence avec Architecture 2 Passes

### Pass 1.5 (local - Option A')
- Relations **locales** dans la fenêtre
- Evidence-based (texte présent)
- Précis, justifié, peu coûteux

### Pass 2 (global - existant)
- Relations **longue portée** (cross-window)
- Relations **cross-document**
- Hiérarchie, inférences

> Les relations longue portée ne sont PAS perdues : elles sont **déplacées**
> vers Pass 2 où elles appartiennent.

---

## 7. Observabilité Requise

### Par fenêtre/chunk
1. `catalog_size_total` + split `{anchors, doc_top, lex}`
2. `prompt_tokens_estimate`
3. `relations_raw`, `relations_validated`, `relations_rejected` (+ raisons)

### Par document
- Distribution du `catalog_size_total` (p95)
- % de chunks où `|S_anchor| < threshold`
- Top raisons de rejet

---

## 8. Impact sur le Code

### Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `llm_relation_extractor.py` | Ajouter `extract_relations_chunk_aware()` |
| `osmose_agentique.py` | Passer `chunks` à `_extract_intra_document_relations()` |
| `llm_relation_extractor.py` | Déprécier `_chunk_text_for_v3()` |

### Nouvelles méthodes

```python
def extract_relations_chunk_aware(
    self,
    document_chunks: List[Dict[str, Any]],  # Avec anchored_concepts
    all_concepts: List[Dict[str, Any]],      # Catalogue global
    document_id: str,
    tenant_id: str,
    window_size: int = 1,                    # i±1 par défaut
    max_concepts: int = 100
) -> TypeFirstExtractionResult:
    """
    Extraction de relations alignée sur DocumentChunks (Option A').
    """
```

---

## 9. Références

- ADR principal : `doc/decisions/ADR_HYBRID_ANCHOR_MODEL.md`
- Phase 2.8+ : ID-First Extraction
- Phase 2.10 : Type-First Extraction (12 Core types)

---

## 10. Validation

- [x] Analyse validée par ChatGPT (2024-12-30)
- [x] Architecture cohérente avec Pass 1.5 / Pass 2
- [ ] Implémentation (en cours)
- [ ] Tests unitaires
- [ ] Métriques observabilité
