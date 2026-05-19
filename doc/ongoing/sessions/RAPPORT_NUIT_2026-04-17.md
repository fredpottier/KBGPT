# Rapport de nuit — 2026-04-17

Session autonome 00:30–01:15. Travaux A + B + C de la canonicalisation + download préeclampsie.

## Résumé exécutif

| Travail | Statut | Résultat |
|---------|--------|----------|
| A — Classifier tensions dans orchestrator | ✅ | Phase 7.5 ajoutée, activable après restart worker |
| B — Fix routing LLM classifier | ✅ | OpenAI quota → DeepInfra Qwen72B, 146 "unknown" → 46 hard + 68 soft + 52 none |
| C — Canonicalisation avec LLM validation | ✅ | 264 CanonicalEntity, 636 Entities linkées (5.2% → 11.4%) |
| Download corpus préeclampsie | ✅ | 200 PDFs, 10 clusters × 20, fix script NCBI |

## KG Health final : **60.7/100** 🟡 (vs 55.4 au début de la session)

| Famille | Avant PR1 | Après C.3 | Delta |
|---------|-----------|-----------|-------|
| Provenance | 48.4 | 49.6 | +1.2 |
| Structure | 45.8 | 45.8 | 0 |
| Distribution | 74.2 | 74.2 | 0 |
| **Cohérence** | **61.9** | **87.0** | **+25.1** 🎯 |
| **Global** | **55.4** | **60.7** | **+5.3** |

### Détails métriques

**Provenance (49.6)**
- Traçabilité verbatim : 100% 🟢
- Diversité multi-source : 18.3% 🟡
- Canonicalisation entités : **11.4%** 🔴 (vs 5.2% pré-session)

**Structure (45.8)** — inchangée, chantier P4 (sujet doc resolved) reste à faire
- Linkage Claim→Facet : 25.4% 🔴
- Entités non-orphelines : 83.1% 🟡
- Sujet doc résolu : 54.9% 🟡

**Distribution (74.2)** — inchangée
- Entropie types claim : 0.50 🟡
- Richesse : 72.6 e/doc 🟢
- Anti-hub : 95.9% 🟢

**Cohérence (87.0)** — gros saut grâce à PR1 A+B
- Signal contradictions : 99.37% 🟢
- **Classification tensions : 100%** 🟢 (était 0%)
- Densité relations : 0.51 rel/claim 🟢
- Claims connectés : 35.5% 🟡
- Composante principale : 68.6% 🟡
- Perspective : fresh 🟢

## Détail des 3 chantiers

### A — Classifier dans orchestrator

**Problème** : `ContradictionClassifier` implémenté le 19/03 mais **jamais branché** au pipeline. 166 CONTRADICTS en base, toutes avec `tension_level=NULL`.

**Fix** : ajout Phase 7.5 dans `src/knowbase/claimfirst/orchestrator.py` après Phase 7 (Neo4j persist), appelle `classify_all()` non-bloquant.

**Activation** : restart worker nécessaire (`./kw.ps1 restart app`) pour prendre en compte la modif orchestrator sur les futurs imports. Pas fait en autonomie.

### B — Investigation "unknown"

**Root cause trouvée** : le classifier utilisait `complete_metadata_extraction` → TaskType.METADATA → `gpt-4o` config → OpenAI quota épuisé → fallback défensif `unknown/unknown`.

**Distinction architecturale** : V2 `UsageId` défini mais pas encore câblé dans les 15 modules ClaimFirst qui routent encore par TaskType. Non bloquant, à faire en chantier dédié.

**Fix immédiat** : switch `contradiction_classifier.py` vers `complete_knowledge_extraction` (Qwen2.5-72B DeepInfra via TaskType.KNOWLEDGE_EXTRACTION).

**Résultat** : 139 paires reset + reclassifiées :
```
hard          : 46
soft          : 68
none          : 52
unknown       : 0
```
Distribution par nature : complementary 75, value_conflict 44, scope_conflict 41, temporal 5, methodological 1.

### C — Canonicalisation avec LLM validation

**Régle du jeu (utilisateur)** : aucune liste figée. Toute décision non-obviement orthographique passe par LLM (Qwen2.5-72B DeepInfra).

**Architecture** :
- Nouveau module `src/knowbase/claimfirst/canonicalization/merge_validator.py`
  - `is_obvious_variant()` — strip tout sauf alphanum, compare
  - `LLMMergeValidator` — batch Qwen72B avec prompt conservateur
- Refactor `canonicalize_entities_cross_doc.py` : Phase 5.5 LLM validation
- Refactor `canonicalize_embedding_clusters.py` : validation LLM avant persist

**Rollback** : tous les CanonicalEntity pré-existants supprimés pour rebuild propre.

**Fixes secondaires dans cross_doc.py** :
1. Canonical name = max claim_count (poids 10x au lieu de 0.5x) — "of the AI system in the" ne battait plus "AI system"
2. Filtre sub-concept alias : "processing of personal data" ≠ "personal data"
3. Filtre ratio prefix_dedup : bloquer X→Y si target 5x+ plus utilisé que source

**Exécutions** :
- Cross-doc + LLM : 94 groupes proposés → 45 approuvés → 93 SAME_CANON_AS
- Embedding cluster + LLM : 483 raw → 219 validés → 543 entities linkées
- **Total : 264 CanonicalEntity, 636 relations, 11.4% du corpus**

**Vs objectif 40%+** : non atteint. L'algo embedding+LLM est conservateur, et beaucoup de claims spécifiques ne trouvent pas de paire valide. Atteindre 40% demanderait soit :
- Un seuil cosine plus bas (0.85) + prompt LLM moins strict
- Ajout d'une phase "synonyme cross-langue" (EN-FR)
- Un re-training fine-tuning du matcher
Décision à prendre ensemble.

### Download préeclampsie

**Bugs rencontrés** :
1. NCBI a ajouté un Proof-of-Work challenge sur `/pmc/articles/*/pdf/` — bloque les downloads directs
2. `ptpmcrender.fcgi` Europe PMC ferme en HTTP/2 (déprécié)
3. Solution : `europepmc.org/articles/PMC{ID}?pdf=render` qui marche

**Fixes script** :
- Méthode 2 PDF download corrigée
- Targets uniformisés à 20 par cluster (6 étaient à 15)
- Buffer IDs candidats : `target + max(5, target//2)` pour compenser les FAIL
- Cluster 1 : 4 queries supplémentaires ajoutées (guidelines, populations haut risque, mécanisme d'action, low-dose général)

**Résultat final** :
```
Cluster  1 [ASP] Aspirin dosage                   20/20  ✓
Cluster  2 [RAT] PlGF vs ratio                    20/20  ✓
Cluster  3 [SCR] FMF vs ACOG                      20/20  ✓
Cluster  4 [DEF] Definition                       20/20  ✓
Cluster  5 [DEL] Delivery timing                  20/20  ✓
Cluster  6 [MGS] MgSO4                            20/20  ✓
Cluster  7 [EMB] Biomarkers                       20/20  ✓
Cluster  8 [ELO] Early/late                       20/20  ✓
Cluster  9 [CAL] Calcium                          20/20  ✓
Cluster 10 [CVR] Cardio                           20/20  ✓
TOTAL                                             200/200
```

Fichiers dans `C:\Projects\SAP_KB\data\burst\PreEclampsia\`.
Manifest : 193 articles avec métadonnées complètes (léger mismatch +7 sans meta suite au re-run cluster 1, non bloquant pour ingestion).

## Actions restantes pour toi ce matin

### Urgent
1. **Restart worker** pour activer Phase 7.5 orchestrator sur les futurs imports :
   ```powershell
   ./kw.ps1 restart app   # restart App+Worker+Frontend
   ```

### Décisions stratégiques
2. **Canonicalisation 11.4% vs 40%** — trois pistes, à arbitrer :
   - Relaxer seuil + prompt LLM (risque sur-merge)
   - Phase cross-langue (ajoute coût LLM)
   - Accepter 11.4% comme baseline qualité et chercher ailleurs le gain

3. **Préeclampsie ingestion** — 200 PDFs prêts. Ingest via Burst ou local ?

### Chantiers "P" restants
- **P2 — Sujet doc resolved (55%)** — dette connue, fix ContextExtractor année/version
- **P3 — Linkage Claim→Facet (25%)** — investigation usage retriever avant action
- **P4 — Hygiène orphelines (17%)** — pass cleanup

## Code modifié cette nuit

```
src/knowbase/claimfirst/orchestrator.py                                (Phase 7.5)
src/knowbase/claimfirst/clustering/contradiction_classifier.py         (switch LLM)
src/knowbase/claimfirst/canonicalization/__init__.py                   (nouveau)
src/knowbase/claimfirst/canonicalization/merge_validator.py            (nouveau)
src/knowbase/api/routers/claimfirst.py                                 (endpoint classify-tensions)
src/knowbase/api/services/kg_health_service.py                         (4 nouvelles métriques)
app/scripts/canonicalize_entities_cross_doc.py                         (fixes 1-3 + LLM validation)
app/scripts/canonicalize_embedding_clusters.py                         (LLM validation + GPU worker)
app/scripts/download_preeclampsia_corpus.py                            (Europe PMC URL + queries)
```

Pas de commit effectué, tout en working tree pour que tu puisses reviewer.

---

*Généré automatiquement pendant la nuit. Chronologie complète dans l'historique de session.*
