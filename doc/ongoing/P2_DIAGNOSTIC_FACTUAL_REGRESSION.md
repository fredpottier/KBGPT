# Diagnostic régression factual P2.4 (R1+R2+R3) — 2026-05-24

> Bench Config C (run_20260524_084344) — Factual n=15, C1 = **0.367**
> Baseline A4.14 (run_20260523_100040) — Factual n=15, C1 = **0.600**
> **Régression : -0.233pp (factual seul)**

## Distribution des 15 questions factual

| Score | Question | ID | Mode | n_claims |
|---|---|---|---|---|
| 0.0 | Quel role SAP pour team lead Payroll Control Center ? | HUM_0017 | REASONED | 5 |
| 0.0 | Quelles options connectivité Azure RISE ? | HUM_0014 | ANCHORED | 1 |
| 0.0 | Que vérifie /SAPAPO/OM13 pour liveCache ? | HUM_0054 | ANCHORED | 3 |
| 0.0 | Quels codes statut print requests WWI ? | HUM_0080 | ANCHORED | 1 |
| 0.0 | Quelle transaction WWI Monitor SAP EHS ? | HUM_0028 | REASONED | 2 |
| 0.0 | Quels objets autorisation E-Recruiting Manager ? | HUM_0020 | REASONED | 4 |
| 0.0 | Quels outils SAP pour support client RISE ? | PPTX_0020 | ANCHORED | 1 |
| 0.0 | Quel client SAP supprimé avant conversion S/4HANA ? | HUM_0003 | ABSTENTION | 4 |
| 0.0 | Quelle transaction contrôle fonctionnel liveCache ? | HUM_0033 | REASONED | 1 |
| 0.5 | Quelle transaction cache Expert SAP EHS ? | HUM_0031 | REASONED | 3 |
| **1.0** | Quelle transaction Labeling Workbench Global Label Mgmt ? | HUM_0097 | REASONED | 1 |
| **1.0** | Comment SAP gère authentification accès systèmes clients ? | PPTX_0018 | REASONED | 5 |
| **1.0** | Quel est le role SAP Signavio ? | PPTX_0017 | ABSTENTION | 5 |
| **1.0** | Qu'est-ce que SAP Business Data Cloud ? | PPTX_0008 | ABSTENTION | 5 |
| **1.0** | Comment S/4HANA utilise fuzzy search HANA classification ? | HUM_0063 | REASONED | 5 |

**Pattern observé** :
- **9/15 score 0.0** : 7-8 questions concernent des **identifiants exacts** (transactions `/SAPAPO/OMxx`, codes statut WWI, clients SAP numériques, objets d'autorisation `P_xxxxx`, rôles techniques)
- **4/15 score 1.0** : 3 narrative/sémantique (Signavio, Business Data Cloud, fuzzy search HANA classification, authentification), 1 abstention judgée OK
- **1/15 score 0.5** : transaction cache Expert — partiellement trouvé

## Vérification KG : claims attendus EXISTENT

Confirmation Neo4j (échantillon 23/05) :
- **HUM_0028 (WWI Monitor)** : `claim_5bebb77ee026` existe — `subject_canonical = "Monitor (transaction CG5Z)"`, text complet `"WWI Monitor (transaction CG5Z) monitors the report generation..."`. **Réponse correcte = "CG5Z"**. Pipeline score 0.0 → le claim n'a pas été utilisé.
- HUM_0054 (`/SAPAPO/OM13`) : claim formel non trouvé en match exact texte mais probable variation (transaction OM13 sans préfixe complet)

Le claim **existe** dans le KG mais n'est **pas retourné par le pipeline** ou pas utilisé par Synthesize. C'est cohérent avec le verrou V1 du diagnostic (subject_canonical fragile) + nouvelle hypothèse (cross-encoder rate les identifiants courts/rares).

## Hypothèse architecturale

Le pipeline P2.4 Config C exécute :

```
Execute RRF(BM25 + Vector) top-50 candidates
  → ClaimReranker.rerank(question, claims[:50]) → top-5 cross-encoder bge-reranker-v2-m3
    → Synthesize sur top-5
```

Le cross-encoder bge-reranker-v2-m3 est un modèle **sémantique pur** : il encode `(question, claim_text)` ensemble et produit un score de similarité sémantique. **Il IGNORE complètement le score RRF amont** (qui combinait BM25 + Vector).

Conséquence : tout le travail de RRF pour capturer le signal lexical exact (BM25 sur identifiants courts) est **détruit par le reranker** qui ne voit plus que le texte. Si "CG5Z" apparaît dans le claim mais pas dans la question (qui dit "WWI Monitor"), le cross-encoder voit deux textes qui se ressemblent peu → score faible → claim ne passe pas top-5.

## Recherche littérature 2026 — pattern documenté

Sources web consultées :
- [Hybrid Search in Production: Why BM25 Still Wins on the Queries That Matter — TianPan.co 2026-04](https://tianpan.co/blog/2026-04-12-hybrid-search-production-bm25-dense-embeddings)
- [Hybrid Search + Reranking Playbook — OptyxStack 2026](https://optyxstack.com/rag-reliability/hybrid-search-reranking-playbook)
- [Injecting the BM25 Score as Text Improves BERT-Based Re-rankers — arxiv 2301.09728](https://arxiv.org/pdf/2301.09728)
- [BM25S Reranker — Emergent Mind 2026](https://www.emergentmind.com/topics/bm25s-reranker)
- [BAAI/bge-reranker-v2-m3 — Hugging Face](https://huggingface.co/BAAI/bge-reranker-v2-m3)

**Findings clés** :

1. **"Pure dense retrieval fails silently on exact identifiers, code, and rare terms"** — TianPan.co 2026. Les embeddings denses (cross-encoder inclus) excellent en sémantique mais sous-performent sur "rare tokens, error codes, IDs, version strings, legal clauses, negation, anything where literal precision matters".

2. **"BM25 outperforms SOTA dense retrieval on financial/structured documents"** — pattern récurrent en domaine financier, médical, légal, technique structuré (notre corpus SAP entre dans cette catégorie pour les transactions et codes formels).

3. **"BM25 is a more effective exact lexical matcher than cross-encoder rankers"** — confirmé par recherche BGE documentation.

4. **Solution standard documentée** :
   > Production pattern: BM25 + dense candidate gen → fuse (RRF) → rerank (cross-encoder) **WITH BM25 score injection** → generate with citations.

5. **3 patterns de fix possibles** :
   - **Score fusion** : `final_score = w1 * cross_encoder_score + w2 * rrf_score_normalized` (typiquement w1=0.7, w2=0.3)
   - **BM25 score injection** : ajouter le score BM25 en token text dans l'input du cross-encoder ([arxiv 2301.09728](https://arxiv.org/pdf/2301.09728))
   - **BGE-M3 Multi-Functionality** : utiliser le mode "unified dense + sparse + colbert" de BGE-M3 (le retriever, pas le reranker) — mais c'est un changement de retriever, pas de reranker

## Hypothèses pour fix (à valider par Fred)

### Hypothèse 1 (recommandée) — Score fusion RRF + Cross-encoder

Préserver les 2 signaux :
```python
# Dans ClaimReranker.rerank()
for claim_idx, claim in enumerate(claims):
    rrf_score = claim.rrf_score  # déjà calculé par Execute, à exposer
    ce_score = self._model.predict([(question, claim_text)])
    # Score fusion pondéré
    final = 0.7 * ce_score + 0.3 * normalize(rrf_score)
```

**Avantages** : pattern standard littérature 2026. Aucun classifier de question requis. Reste **domain-agnostic strict**.
**Effort** : 1-2j (exposer RRF score depuis Execute + intégrer dans Reranker).
**Risque** : tuning des poids (w1, w2) — bench A/B avec quelques combinaisons.

### Hypothèse 2 — BM25 score injection dans cross-encoder input

Ajouter le score BM25 en token texte dans l'input du cross-encoder :
```
input = f"{question} [SEP] [bm25_score={bm25_score:.2f}] {claim_text}"
```

**Avantages** : effet documenté ([arxiv 2301.09728](https://arxiv.org/pdf/2301.09728)). Pas de changement de modèle.
**Effort** : 0.5-1j (modifier construction de pairs dans ClaimReranker).
**Risque** : le modèle bge-reranker-v2-m3 n'est pas fine-tuné sur ce format, gain incertain.

### Hypothèse 3 (NON recommandée — non domain-agnostic) — Routing par regex identifiant

Si question contient regex `[A-Z]+\d+` (transactions SAP-style) ou `/[A-Z]+/\w+` (transactions SAPAPO) → skip cross-encoder, garder RRF pur.

**Pourquoi NON recommandée** : pattern régex est **corpus-spécifique** (SAP). Violation charte AX-11 domain-agnostic. Inapplicable identiquement à médical (codes ICD-10), juridique (articles), aerospace (numéros pièces).

## Décision suggérée

Implémenter **Hypothèse 1 (score fusion)** comme P2.5 — séparée des autres modifs Phase 2 pour isoler l'effet :

1. Exposer `rrf_score` au niveau `ClaimSummary` (modifier `Execute._call_kg_claims_rrf` pour persister)
2. Refactor `ClaimReranker.rerank` avec fusion pondérée
3. Bench A/B avec poids (1.0, 0.0) [baseline cross-encoder seul] vs (0.7, 0.3) vs (0.5, 0.5)
4. Choisir le poids optimal sur factual + multi_hop

**Effort estimé** : 2 jours. **Gain attendu sur factual** : récupérer +0.10-0.20pp (sans détruire le gain multi_hop +0.300pp).

---

*Document produit dans le cadre de l'analyse autonome P2.4 (matinée 24/05/2026). Auteur : Claude (audit + recherche littérature). Décision finale : Fred à son retour.*
