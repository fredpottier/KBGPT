# TODOLIST OSMOSIS — Plan d'execution

**Derniere mise a jour** : 31 mars 2026
**Regle** : Chaque tache terminee → mettre a jour le document source → supprimer la ligne ici.

---

## PHASE 1 — Retrieval solide ✅ TERMINEE

| # | Statut |
|---|--------|
| ~~1.1~~ | ✅ 23 docs, 7629 chunks, median 957 chars |
| ~~1.2~~ | ✅ Hybrid BM25+dense RRF — Context Relevance +15pp |
| ~~1.3~~ | ✅ RAGAS diagnostic — script + cockpit + frontend + RQ worker |
| ~~1.4~~ | ✅ Benchmark Baseline V5 |
| 1.1b | ⏳ 029/030 — bug crash post-Docling non resolu. Non bloquant. |

---

## PHASE 2 — KG exploitable ✅ TERMINEE

| # | Statut |
|---|--------|
| ~~2.1~~ | ✅ C1.1 Exact dedup — 123 canonicals fusionnes |
| ~~2.2~~ | ✅ C1.2 Token blocking — 126 groupes, 266 entites (Jaccard >= 0.70) |
| ~~2.3~~ | ✅ C1.3 Embedding clustering — 263 clusters, 605 entites (cosine >= 0.95) |
| ~~2.4~~ | ✅ C3 Garbage collection — 1053 NOISY, 1934 UNCERTAIN, 4343 VALID |
| ~~2.5~~ | ✅ Benchmark RAGAS post-Phase 2 — faith 0.806, ctx_rel 0.718 (stable) |

**Bilan** : Orphelines 78% → 56%. Entites VALID 59%. CanonicalEntity 1783 → 2265.

---

## PHASE 3 — Activation differenciation — EN COURS

| # | Tache | Statut | Detail |
|---|-------|--------|--------|
| ~~3.4~~ | ~~KG narratif → KG procedural~~ | ✅ | `_build_kg_findings()` retourne des instructions de lecture, pas du contenu narratif. INV-ARCH-06 documente. Benchmark en cours. |
| ~~3.3~~ | ~~ContradictionEnvelope~~ | ✅ Code ecrit | `ContradictionEnvelope` dataclass + builder + injection prompt MANDATORY + validation + fallback deterministe. Actif au prochain restart app. |
| ~~3.1~~ | ~~C4 — Relations evidence-first~~ | ✅ Deploye | 584 → 1766 relations (11.3%). 118 CONTRADICTS, 511 QUALIFIES, 1137 REFINES. Proactive detection 100%. |
| ~~3.2~~ | ~~C6 — Cross-doc pivots~~ | ✅ Deploye | +634 COMPLEMENTS, 12 SPECIALIZES, 3 EVOLVES_TO via pivots d'entites. Total KG: 2418 relations (15.5%). |
| ~~3.5~~ | ~~Benchmark post-Phase 3~~ | ✅ | T2/T5: tension 100%, proactive 100%. RAGAS: faith 84.8%, ctx 72.5%. |

---

## PHASE 3.5 — Qualite et Mesure (session 1-2 avril 2026)

| # | Tache | Statut | Detail |
|---|-------|--------|--------|
| ~~3.6~~ | ~~Dashboard benchmark 4 onglets~~ | ✅ | Vue ensemble + RAGAS + Contradictions + Robustesse. ScoreGauges D3, RadarChart, drill-down questions. |
| ~~3.7~~ | ~~Benchmark robustesse 246q~~ | ✅ | 10 categories, 25q/cat. false_premise, unanswerable, temporal, causal, hypothetical, negation, synthesis, conditional, set_list, multi_hop. |
| ~~3.8~~ | ~~LLM-juge~~ | ✅ | GPT-4o-mini remplace keyword matching (cross-lingue). Global 57% → 64.3%. |
| ~~3.9~~ | ~~Multi-provider synthese~~ | ✅ | OpenAI/Anthropic/vLLM via OSMOSIS_SYNTHESIS_PROVIDER. Prompts externalises YAML. |
| ~~3.10~~ | ~~Comparaison 3 modeles~~ | ✅ | Qwen 49% / Haiku 56% / GPT-4o-mini 56% (=Haiku, 6x moins cher). |
| 3.11 | Indicateur entropie frontend | A faire | Afficher "confiance faible" dans le chat quand entropy > seuil. Signal HALT/EPR implemente. |
| 3.12 | T2/T5 avec LLM-juge | En cours | Run propre + reevaluation. Evaluateurs keyword cross-lingue. |
| 3.13 | Unanswerable > 60% | Recherche | Logprob entropy (signal present mais overlap). CDA abandonne (2x cout). Piste R-Tuning si fine-tune. |

---

## PHASE 4 — Produit visible

| # | Tache | Doc source | Effort |
|---|-------|-----------|--------|
| 4.0 | **Refonte page chat** | Reponse trop complexe, KG non mis en valeur | 1-2j |
| 4.1 | Atlas Phase 1 | `CHANTIER_ATLAS.md` §1 | 2-3j |
| 4.2 | ~~UI tensions~~ | Deprioritise — peu de valeur utilisateur (admin only) | — |
| 4.3 | Verify V1 — refactorer moteur | Reutiliser pipeline search au lieu de evidence_matcher. Coquille OK. | 1.5j |
| 4.4 | Verify V2 — positions documentaires | C4/C6 dans les commentaires Word | 1sem |

---

## BUGS / DETTE TECHNIQUE

| Bug | Statut | Impact |
|-----|--------|--------|
| ~~Delete RAGAS rapport~~ | ✅ Deploye | — |
| ~~Doublons rapports RAGAS~~ | ✅ Fix deploye | — |
| ~~Fix ApplicabilityAxis~~ | ✅ Code ecrit | Actif au prochain ClaimFirst |
| ~~Animation pipeline cockpit~~ | ✅ SVG animate | Hard refresh pour tester |
| Redis state benchmark | ✅ Fix ecrit (singleton) | A verifier au prochain run |
| 029/030 crash post-Docling | Non resolu | Mineur — 2 docs secondaires |
| SIMILAR_TO score 0.5 hardcode | Backlog | Modifier merge_arbiter pour vrai cosine |

---

## SCORES RAGAS — Historique

| Run | Date | Faithfulness | Ctx Relevance | Delta vs precedent |
|-----|------|-------------|---------------|-------------------|
| Pre-hybrid | 30 mars | 0.743 | 0.580 | — |
| Post-hybrid RRF | 31 mars AM | 0.793 | 0.730 | faith +5pp, ctx +15pp |
| Post-Phase 2 (C1+C3) | 31 mars PM | 0.806 | 0.718 | faith +1pp, ctx -1pp |
| Post-KG-procedural | 31 mars PM | 0.815 | 0.715 | faith +1pp, ctx stable |

### T2/T5 Gate — Baseline Pre-C4 (31 mars 2026)

| Metrique | Score | Interpretation |
|---|---|---|
| tension_mentioned | **93.6%** | Mentionne une tension dans 94% des cas |
| both_sides_surfaced | **58.8%** | Presente les deux cotes dans 59% des cas |
| both_sources_cited | **64.0%** | Cite les deux documents dans 64% des cas |
| proactive_detection | **80.0%** | Detecte 4/5 contradictions cachees |
| chain_coverage | **51.0%** | Couvre la moitie des chaines cross-doc |
| multi_doc_cited | **81.6%** | Cite les documents requis dans 82% des cas |

Rapport : `t2t5_run_20260331_155830_BASELINE_PRE_C4.json`

---

## BACKLOG

| Tache | Prerequis |
|-------|-----------|
| C2 — Epistemic Type Guidance | Phase 2 |
| C5 — Facettes navigation | Phase 2 |
| Concept Assembly Engine POC | Phase 4.1 |
| Cockpit operationnel V1 MVP | Independant |
| Layer P + Layer C (Qdrant) | Phase 3 |
| Graph-First Runtime complet | Phase 3 |
| Source Enrollment multi-sources | Phase 4 |
| Decision Defense complet | Phase 3 |
| Coref Named-Named Phases B-D | Phase 2 |
| Evidence Bundle Resolver extended | Phase 3 |
| Indicateur entropie dans chat frontend | Phase 3.5 |
| LLMLingua-2 compression prompts (si besoin reduction couts) | Independant |
| Purge ciblee par document (corpus vivant ADR) | Phase 4+ |
| Connecteurs OneDrive/SharePoint (corpus vivant) | Phase 4+ |
| R-Tuning Qwen pour abstention (si fine-tune envisage) | Phase 4+ |
| Re-ranking cross-encoder (ameliorer context relevance) | Phase 4 |
