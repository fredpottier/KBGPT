# Post-mortem — Bug `c.text` non propagé au cross-encoder + LLM Synthesize

> Date : 2026-05-24
> Sévérité : haute (probable bottleneck dominant Phase 2)
> Fix : 2 lignes (commit `af1edad` sur `feat/phase-b-augmentee`)

## TL;DR

Le champ `text` (verbatim Claim Neo4j) n'était propagé NI au cross-encoder reranker, NI au payload LLM Synthesize. Les 2 modules recevaient à la place un triplet reconstruit `subject + predicate + value` parfois quasi-vide (claims narratifs avec `value=None`). Conséquence : cross-encoder discriminait mal entre claims similaires, LLM Synthesize choisissait des claims non pertinents.

Test sur HUM_0028 isolé : réponse "transaction CGSADM" (FAUX) → "transaction CG5Z" (CORRECT) après fix.

## Symptômes observés

### Recall audit factual (P2.4-PRE)

Sur 9 questions factual score=0.0 du bench Config C :
- 3 cas dits "Synthesize bug" (A1) : claim attendu ∈ CE top-5 selon mon recall audit, mais bench réel ne citait pas ce claim
- 5 cas dits "query dilution" (A2) : claim ∈ RRF top-50 mais ∉ CE top-5

### Trace pipeline HUM_0028

Question : "Quelle transaction est utilisee pour le WWI Monitor dans SAP EHS ?"
Expected claim : `claim_5bebb77ee026` (text="WWI Monitor (transaction CG5Z) monitors the report generation...")

**Direct Neo4j (manuel)** :
- BM25 full-text : claim_5bebb77e en rank 1, score 6.48 ✅
- Vector cosine : claim_5bebb77e en rank 1, score 0.94 ✅

**Pipeline runtime_v6 (avant fix)** :
- Cross-encoder top-5 :
  - rank 1 : claim_8382ad0e (Workflow log and monitor / SWI1) score 0.326
  - rank 4 : claim_2291e41f (WWI + Expert / CGSADM) score 0.103
  - **claim_5bebb77e (CG5Z) ABSENT** du top-5
- Synthesize réponse : "transaction CGSADM" (FAUX)

## Diagnostic itératif

1. **Hypothèse 1 — score fusion RRF + CE** (Option α) : invalidée. Mon recall audit utilisait la question brute, le pipeline aussi en mode `question`. Donc le score fusion n'était pas la solution.

2. **Hypothèse 2 — sub_goal query dilution** (Option δ) : testée via Config C2 `V6_HYBRID_QUERY_MODE=question`. Régresse C1 -0.08pp. Pas le fix.

3. **Hypothèse 3 — subject_resolver remap faux** : testée en désactivant `V6_SUBJECT_RESOLVER_ENABLED=0`. Même réponse fausse CGSADM. Pas le fix.

4. **Hypothèse 4 (correcte) — propagation `text` cassée** : trouvée en lisant `_claim_from_node` (execute.py:1024). Le champ `text` du noeud Neo4j n'était pas mappé sur ClaimSummary.

## Cause root

Le code de mapping Neo4j → ClaimSummary n'avait jamais inclus le champ `text` :

```python
# execute.py:_claim_from_node — AVANT (bug)
return ClaimSummary(
    claim_id=str(node.get("claim_id") ...),
    subject_canonical=node.get("subject_canonical"),
    predicate=node.get("predicate"),
    value=node.get("object_canonical") or node.get("value") or ...,
    value_normalized=node.get("value_normalized"),
    confidence=node.get("confidence"),
    valid_from=node.get("valid_from"),
    valid_until=node.get("valid_until"),
    ingested_at=node.get("ingested_at"),
    invalidated_at=node.get("invalidated_at"),
    marker_type=node.get("marker_type"),
    source_doc_id=node.get("source_doc_id") or ...,
    # text MANQUANT !
)
```

Le ClaimSummary est défini avec `extra="allow"` (donc tolère champs additionnels), mais le mapping ne l'a jamais peuplé. Conséquence en cascade :

- **`ClaimReranker._claim_text_for_rerank`** (reranker.py) :
  ```python
  for key in ("text", "claim_text_full", "verbatim_quote", "passage_text"):
      val = extras.get(key)  # → None pour tous, car non peuplés
      if val: return val
  # Fallback : reconstruire depuis triplet
  parts = [subject_canonical, predicate.replace("_", " ").lower(), value]
  return " ".join(parts)
  ```
  → Cross-encoder recevait `"Monitor (transaction CG5Z) USES None"` au lieu du verbatim narratif.

- **`Synthesize._serialize_input`** (synthesize.py:211) :
  ```python
  claims_payload.append({
      "claim_id": c.claim_id,
      "subject": c.subject_canonical,
      "predicate": c.predicate,
      "value": c.value or c.value_normalized,  # None pour claims narratifs
      # ...
  })
  ```
  → LLM Synthesize voyait pour CG5Z : `{subject: "Monitor (transaction CG5Z)", predicate: None, value: None}` — quasi-vide.

## Fix

Commit `af1edad` — 2 endroits, 2 lignes minimales :

### Fix #1 — execute.py:_claim_from_node
```python
return ClaimSummary(
    # ... [tous les champs existants] ...
    # Extra (Pydantic extra="allow") — verbatim Claim text pour cross-encoder
    text=node.get("text"),
)
```

### Fix #2 — synthesize.py:_serialize_input
```python
extras = c.model_dump() if hasattr(c, "model_dump") else {}
claim_text = extras.get("text")
claims_payload.append({
    # ... [champs existants] ...
    "text": (claim_text[:600] if isinstance(claim_text, str) else None),
})
```

Aucune autre modification. Pas de refonte d'architecture, pas de nouveau modèle, pas de ré-ingestion.

## Validation isolée

Test HUM_0028 via `app/scripts/p2_debug_hum0028.py` :

**Cross-encoder top-5 (après fix)** :
- rank 1 : `claim_5bebb77e` (Monitor (transaction CG5Z)) score **0.965** ✅✅✅
- rank 2 : claim_8382ad0e (SWI1) score 0.676
- rank 3-4 : SWI1 0.489, 0.448
- rank 5 : security audit log 0.341

**Synthesize réponse (après fix)** :
> "Le WWI Monitor utilise la transaction CG5Z [claim_id=claim_5bebb77ee026]. Cette transaction surveille la génération de rapports et l'envoi de rapports sous Edit Report Shipping Orders (transaction CVD1)."

Réponse correcte avec claim_id correct + détail enrichi du verbatim.

## Impact attendu

Selon analyse Claude Web et nos audits :

| Scénario impact | Cas adressés | Gain global attendu |
|---|---|---|
| Pessimiste (3 cas A1 seulement) | 3/50 | +0.04-0.06pp |
| Réaliste (3 A1 + partie A2) | 5-6/50 | +0.08-0.12pp |
| Optimiste (3 A1 + tous A2) | 8/50 | +0.15-0.20pp |

Le bench Config C3 en cours (lancé après commit `af1edad`) mesurera l'impact réel.

## Apprentissages méthodologiques

1. **Recall audit avant tout** (validation Claude Web) : sans cet audit, j'aurais codé un score fusion RRF+CE qui n'aurait rien résolu — le bug était en aval du retrieval.

2. **Trace pipeline pas-à-pas** : le script `p2_debug_hum0028.py` lance UNE question avec logging du top-5 réel. C'est cet outil qui a révélé que CG5Z n'était pas dans le top-5 du pipeline, contrairement à mon recall audit manuel qui le trouvait en top-1.

3. **Investigation séquentielle des hypothèses** :
   - Score fusion → invalidé
   - Query dilution → invalidé (Config C2 régresse)
   - Subject_resolver remap → invalidé (test bypass)
   - **Propagation données** → cause root identifiée en lisant le code de mapping

4. **Bug de plomberie de données peut masquer le potentiel d'une architecture entière**. Phase 2 (RRF + Cross-encoder + DeepSeek Parse) ressemblait à une faillite avec C1=0.480 vs cible 0.75. En réalité, l'architecture marchait — c'était juste un mapping incomplet qui privait les modules d'une donnée clé.

## Prévention future

Recommandations pour éviter ce type de bug à l'avenir :

1. **Tests unitaires sur mapping Neo4j → ClaimSummary** : vérifier que tous les champs critiques sont présents.

2. **Test E2E pipeline** : vérifier que le payload Synthesize contient bien `text` pour chaque claim narratif.

3. **Monitoring logs traces** : logger `len(claim.text)` dans les traces du cross-encoder pour détecter rapidement si la propagation casse.

4. **Documentation explicite** dans ClaimSummary docstring : "Champs Pydantic extra (allow) attendus en pipeline : `text` (verbatim Claim Neo4j) — peuplé par `_claim_from_node`".

## Fichiers livrés

- `src/knowbase/runtime_a3/execute.py` (fix #1 ligne 1029)
- `src/knowbase/runtime_a3/synthesize.py` (fix #2 ligne 211)
- `app/scripts/p2_debug_hum0028.py` (script reproduction)
- `doc/ongoing/P2_AUDIT_SYNTHESIZE_BUG.md` (audit initial)
- `doc/ongoing/P2_AUDIT_SYNTHESIZE_FINAL.md` (audit étendu)
- `doc/ongoing/P2_POSTMORTEM_TEXT_PROPAGATION_BUG.md` (ce doc)

---

*Post-mortem rédigé 24/05/2026 pendant bench validation Config C3. Auteur : Claude. Validation Fred attendue post-bench.*
