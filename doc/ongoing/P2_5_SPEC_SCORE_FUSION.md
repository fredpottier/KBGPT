# P2.5 Spec — Score fusion RRF + Cross-encoder

> Statut : **spécification, en attente de validation Fred**
> Date : 2026-05-24
> Référence régression : [`P2_DIAGNOSTIC_FACTUAL_REGRESSION.md`](P2_DIAGNOSTIC_FACTUAL_REGRESSION.md)
> Référence décision : [`DECISION_MATINALE_P2_4.md`](DECISION_MATINALE_P2_4.md) Option α

---

## Contexte

Bench P2.4 Config C complet :
- ✅ Multi_hop +0.300pp (gain massif)
- ⚠ Factual **-0.233pp** (régression)
- Cause : cross-encoder bge-reranker-v2-m3 perd le signal lexical BM25 amont (RRF)

Recherche littérature confirme le pattern :
- "Pure dense retrieval fails silently on exact identifiers, code, and rare terms" (TianPan.co 2026)
- "Retrieval fusion increases recall, but these gains are largely neutralized after re-ranking" (TREC iKAT 2025 caveat)
- Solution standard : score fusion `final = α * CE_score + (1-α) * RRF_score`

---

## Objectif

Préserver le signal lexical de RRF (BM25 + Vector) en l'injectant dans le score final du reranker, pour récupérer la précision sur identifiants exacts sans casser le gain multi_hop sémantique.

---

## Architecture cible

```
Execute RRF(BM25 + Vector) top-50 candidates avec rrf_score persisté
  → ClaimReranker.rerank(question, claims[:50])
      → cross_encoder_score = model.predict([(q, c.text) for c in claims])
      → final_score[i] = α * normalize(ce_score[i]) + (1-α) * normalize(rrf_score[i])
      → sort DESC final_score → top-5
    → Synthesize sur top-5
```

**Pondération α** :
- Défaut : α = 0.7 (cross-encoder dominant mais RRF présent)
- Autres à bencher : α = 1.0 (CE pur, = Config C actuel) / 0.5 (équilibré) / 0.3 (RRF dominant)
- Le choix optimal sera celui qui minimise la régression factual SANS détruire le gain multi_hop

**Normalisation** :
- `normalize(ce_score)` : sigmoid sortie bge-reranker-v2-m3 ∈ [0, 1] déjà
- `normalize(rrf_score)` : RRF formula `1 / (k + rank)` avec k=60, donc score ∈ [0, 1/60] ≈ [0, 0.0167]. Re-normaliser via `rrf_score / max(rrf_score in batch)` pour scaler [0, 1].

---

## Modifications de code

### Fichier 1 : `src/knowbase/runtime_a3/execute.py`

Persister le score RRF dans le ClaimSummary retourné par `_call_kg_claims_rrf` :

```python
# Dans _call_kg_claims_rrf, après calcul RRF top-50 :
for rank, (claim_id, rrf_score) in enumerate(top50):
    claim = load_claim(claim_id)
    # Pydantic extra="allow" → on peut ajouter un champ
    claim_with_score = claim.model_copy(update={"rrf_score": rrf_score})
    output.append(claim_with_score)
```

**Impact** : ClaimSummary porte maintenant `rrf_score: Optional[float]` (via extras). Backward compat OK.

### Fichier 2 : `src/knowbase/runtime_a3/reranker.py`

Refactor `ClaimReranker.rerank` pour fusion pondérée :

```python
def rerank(
    self,
    question: str,
    claims: List[ClaimSummary],
    top_k: Optional[int] = None,
) -> Tuple[List[ClaimSummary], List[float]]:
    # ... [calcul ce_scores comme avant] ...

    # P2.5 : score fusion si rrf_score disponible sur claims
    alpha = float(os.getenv("V6_CE_FUSION_ALPHA", "0.7"))
    use_fusion = os.getenv("V6_CE_FUSION_ENABLED", "1") == "1"

    if use_fusion:
        # Extraire RRF scores depuis claims (Pydantic extras)
        rrf_scores = []
        for c in claims:
            extras = c.model_dump()
            rrf_scores.append(extras.get("rrf_score", 0.0))

        # Normaliser RRF scores [0, 1]
        max_rrf = max(rrf_scores) if rrf_scores else 1.0
        if max_rrf > 0:
            rrf_norm = [s / max_rrf for s in rrf_scores]
        else:
            rrf_norm = [0.0] * len(rrf_scores)

        # CE scores sont déjà sigmoid [0, 1] avec bge-reranker-v2-m3
        # Fusion pondérée
        final_scores = [
            alpha * ce + (1 - alpha) * rrf
            for ce, rrf in zip(ce_scores, rrf_norm)
        ]

        # Sort DESC + top-K (même logique qu'avant)
        scored = list(zip(range(len(claims)), final_scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        # ... [reste idem] ...
    else:
        # Comportement actuel (Config C)
        scored = list(zip(range(len(claims)), ce_scores))
        ...
```

**Toggle** : `V6_CE_FUSION_ENABLED=1` (défaut ON post-validation), `V6_CE_FUSION_ALPHA=0.7` (tunable).

### Fichier 3 : `src/knowbase/runtime_a3/schemas.py` (optionnel)

Si on veut typer formellement le champ rrf_score sur ClaimSummary plutôt que via extras :

```python
class ClaimSummary(BaseModel):
    # ... champs existants ...
    rrf_score: Optional[float] = None  # P2.5 — score RRF amont pour fusion reranker
```

Avantage : typage strict, autocomplete IDE.
Inconvénient : breaking si autres code dépend de la structure actuelle (à vérifier).

---

## Plan de bench (séquentiel, 1 modif → 1 bench)

### Bench P2.5a — Fusion α=0.7 (recommandé par défaut)

```bash
docker exec \
  -e V6_HYBRID_RETRIEVAL=rrf \
  -e V6_CROSS_ENCODER_RERANK=1 \
  -e V6_PARSE_LLM_DEEPSEEK=1 \
  -e V6_CE_FUSION_ENABLED=1 \
  -e V6_CE_FUSION_ALPHA=0.7 \
  knowbase-app sh -c 'cd /app && python -u scripts/bench_a38_runtime_v6.py'
```

**Cible** : C1 factual ≥ 0.50 (récupération partielle vs 0.367 Config C), C1 multi_hop ≥ 0.30 (préservation gain).

### Bench P2.5b — Fusion α=0.5 (équilibré)

Si P2.5a insuffisant ou trop neutre, tester α=0.5.

### Bench P2.5c — Fusion α=0.3 (RRF dominant)

Pour cas extrême : RRF dominant, CE en simple tie-breaker.

---

## Gates P2.5

**Gate P2.5 (go/no-go avant Phase 3)** :
- C1 factual ≥ 0.50 (récupération vs 0.367 Config C, attendu 0.50-0.55)
- C1 multi_hop ≥ 0.25 (préservation vs 0.40 Config C, attendu 0.30-0.40)
- C1 global ≥ 0.52 (cumulé attendu)
- Latence p95 ≤ Config C (pas d'augmentation, fusion = calcul léger)

**STOP rule** : si C1 global < 0.48, diagnostic profond avant Phase 3 (peut-être problème fondamental dans la combinaison).

---

## Risques

| Risque | Probabilité | Mitigation |
|---|---|---|
| α=0.7 ne récupère pas assez factual | Moyenne | Tester α=0.5 et 0.3, garder le meilleur |
| Préservation multi_hop dégradée | Faible | RRF gardait déjà les claims sémantiques (vector top-25), fusion conserve |
| RRF scores pas exposés correctement par Execute | Faible | Test unitaire dédié, vérif Pydantic extras flow |
| Régression sur d'autres types (lifecycle, contextual) | Moyenne | Bench complet par-type obligatoire |

---

## Effort + planning

| Tâche | Effort |
|---|---|
| P2.5.1 — Modif `Execute._call_kg_claims_rrf` exposer rrf_score | 0.5j |
| P2.5.2 — Refactor `ClaimReranker.rerank` avec fusion | 0.5j |
| P2.5.3 — Tests unitaires fusion (normalisation, pondération) | 0.5j |
| P2.5.4 — Bench P2.5a α=0.7 + analyse | 0.5j |
| P2.5.5 — Bench A/B α=0.5 + 0.3 si nécessaire | 0.5j |
| **Total** | **2-2.5j** |

---

## Validation requise

- [ ] Fred valide l'option α (score fusion vs alternatives)
- [ ] Choix α initial (0.7 défaut, ou autre)
- [ ] Implémentation en isolation (pas de cumul avec autres modifications Phase 2)
- [ ] Bench A/B rigoureux séquentiel

---

*Spec produite en autonomie 24/05/2026 matin. À valider par Fred à son retour.*
