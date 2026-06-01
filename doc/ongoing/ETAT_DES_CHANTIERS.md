# État des chantiers — OSMOSE / OSMOSIS

> **Document vivant** (doc/ongoing). Tableau consolidé : terminé / en cours / restant.
> **Dernière mise à jour** : 2026-05-31. **Branche** : `feat/phase-b-augmentee`.
> Sources : liste de tâches de session, mémoire, `git log`. Remplace comme vue d'ensemble
> le `PLAN_PHASE_B_AUGMENTEE.md` (23/05, désormais partiel — précède le travail qualité récent).

---

## 🟢 TERMINÉ (livré + benché/validé + committé)

### Qualité runtime answering (semaine du 24–31/05)
| Chantier | Résultat | Commit |
|----------|----------|--------|
| **Preuve OSMOSIS > RAG classique** | exact_id_recall +16.5pp, abstention_correct +56pp, 1 vs 30 abstentions à tort | `2064f96` |
| **PremiseVerifier (faux présupposés)** | false_premise **+40pp**, exact_id flat, activé par défaut, 13 tests | `50740c8`,`eed1f7c`,`a5efe88` |
| **Synthèse comparative** (rerank équilibré + prompt contrastif) | Q4_1 0.0→0.5 bilatéral, gratuit en LLM | `08bb3e2` |
| **multi_hop — retrieval emphasé par aspect** | A/B propre **+6.4pp eir**, +10pp comparison, zéro régression | `050b4e9`,`578c83d` |
| **Fiabilité synthèse Novita** (timeout par tâche 240s + retries 5→2) | réduit les fallbacks template sur gros prompts | `a439950` |
| **Bras RAG classique comparatif** + refonte page benchmarks lisible | dashboard langage clair + timeless | `2064f96`,`ecbb3fb`,`c6f778e` |
| **Métriques déterministes** (exact_id_recall, abstention_correct) dans le bench | pilotage anti-bruit juge | `4f2f707` |
| **Juge LLM recalibré** orienté rappel + parallélisation Execute (latence) | mesure fiable + p50 réduit | `573e3bf` |
| **P3 retrieval-liste + cross-encoder + planner multi-aspect + merge anti-fragmentation** | gains multi_hop/list | `4f2f707` |
| **Lifecycle EVOLUTION_OF temporel** (valid_from) | gate C3 | `4f2f707` |
| **Fix Lucene escaping subject_resolver FTS** | bug retrieval majeur corrigé | `6dc9837` |

### Cadrage / docs stratégiques
| Chantier | Résultat |
|----------|----------|
| **Guide repo Osmosis** (3 projets, sans legacy) | `OSMOSIS_NEW_REPO_GUIDE.md` |
| **Carte de reachability autoritative** (13 deltas, 6 corrections durcissantes) | `OSMOSIS_REACHABILITY_MAP.md` |
| **Décisions produit Fred** (search→answering, Wiki/RFP Excel/Documents UI retirés, admin morts purgés) | intégrées au guide §0 |
| **ADR PremiseVerifier** + **ADR programme retrieval** | `ADR_PREMISE_VERIFIER.md`, `ADR_RETRIEVAL_PROGRAM.md` |

---

## 🟡 EN COURS

| Chantier | État | Prochaine étape |
|----------|------|-----------------|
| **R-L1 — Gate final fusionné** (verbatim c.text + signal lexical) | **code livré + 33 tests verts** ; A/B 50q en cours (baseline vs λ=0.25) | analyser exact_id_recall **par type** → décider λ + passage L2 |
| **P1.4b — ré-ingestion staged de validation** | pipeline staged construit+testé (~66 tests) ; ré-ingestion 3 docs **suspendue** (burst détruite) | mesurer volume/qualité vs P1.3.5 sur burst g6 |

---

## 🔴 RESTANT À RÉALISER

### A. Programme retrieval (suite L1) — « meilleur retrieval possible »
| # | Chantier | Coût LLM |
|---|----------|----------|
| **L2** | Routing du poids lexical par `sub_goal.kind` (factual/list → lexical ; multi_hop/comparison → sémantique) | 0 |
| **L3** | RRF pondéré BM25/vector + boost exact-substring d'identifiants | 0 |
| **L5** | Qualité requête : préservation verbatim des identifiants dans la requête BM25 | 0 |
| (suite) | Ré-ajout éventuel du cross-encoder comme **3e signal fusionné** (pas pure-rerank) si L1+L2 insuffisants | +1 appel (à gater) |

### B. Qualité runtime
| Chantier | Note |
|----------|------|
| **#428 — PremiseVerifier précision/gating** | réduire 2→1 appel via **gating sûr** (pas merge lossy, déjà reverté). Levier convergent multi_hop + comparison + coût LLM |
| **B2 — Evaluate** | boucle d'évaluation runtime (non livré) |
| **D2 — dedup mislabel 62%** | qualité KG |

### C. Extraction P1.4-bis (clôture)
1. Finir la validation ré-ingestion staged (volume/qualité réels vs P1.3.5)
2. Rendre le **staged pipeline par défaut** + **retirer le méga-prompt legacy**
3. Ré-ingestion complète des 38 docs
4. Bench P1.5

### D. Productionisation / décision produit
| Chantier | Note |
|----------|------|
| **Promouvoir `runtime_a3` (→ `answering`) en moteur de prod** | ⚠️ découverte 31/05 : `/search` (chat prod) **n'utilise PAS** runtime_a3 = tout notre travail qualité. Rebrancher l'UI chat sur `answering`. Renommer (nom non versionné). |
| **Migration Osmosis** (3 repos propres) | **après** stabilisation P1.4-bis. Guide + carte prêts. |

### E. Phase sécurité dédiée (findings audit, reportés par Fred)
- Rotation secrets (S2/S10), auth sur les routers (S1/S3/S5/S6/S7)
- Bugs tenant **C1/C2 du PremiseVerifier** (introduits, à corriger : filtre tenant manquant)
- Rate-limiting (S8), validation `pack_name` (S5), Next.js 14.0.3→14.2.35 (S13)

---

## Cibles & repères

- **Vision** : exact_id_recall 0.75–0.80 (✅ atteint à 0.788), C1 ≥ 0.75 (actuel ≈ 0.47–0.52, raisonnement compréhensif sous la cible).
- **Pilotage** : métriques déterministes en premier (juge LLM bruité, recalibré à 0.52).
- **Discipline** : un levier benché isolé (config loggée, n≥50) — leçon A4.15.
- **Charte** : domain-agnostic strict ; pas de scope minimal ; ne pas multiplier les appels LLM.
