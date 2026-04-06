# OSMOSIS — Vision Produit Consolidee

**Date** : 24 mars 2026
**Statut** : Document de reference — fige apres consensus ChatGPT + Claude Web + Claude Code + fondateur
**Supersede** : Ce document remplace et consolide les sections vision/positionnement de :
- `STRATEGY_REPOSITIONNEMENT_OSMOSIS_2026-03.md` (positionnement et horizons — toujours valide pour la strategie go-to-market)
- `OSMOSE_VS_RAG_POSITIONNEMENT.md` (comparaison technique — reste valide comme whitepaper)
- `OSMOSIS_CAPABILITIES_OVERVIEW_2026-03.md` (inventaire technique — reste valide comme reference)
- `OSMOSE_USAGES_QUOTIDIENS.md` (use cases — reste valide comme materiel commercial)

---

## 1. Positionnement

### Ce qu'OSMOSIS n'est PAS
- **Pas un "RAG ameliore"** — un RAG fait deja tres bien son job sur les questions directes
- **Pas un moteur de recherche** — l'utilisateur ne cherche pas, il interroge
- **Pas un "Truth Engine"** — le mot "verite" est dangereux commercialement

### Ce qu'OSMOSIS EST
> **Un moteur d'analyse documentaire intelligent qui detecte ce que la recherche ne voit pas.**

Tagline : *"De la recherche documentaire a l'intelligence documentaire"*

Categorie produit : **Documentation Verification Platform**

### Positionnement en une phrase
> "OSMOSIS repond a vos questions, mais surtout il vous dit quand vos documents ne sont pas d'accord entre eux."

---

## 2. Les 5 Capacites Fondamentales

Definies par le fondateur le 24 mars 2026 — c'est la boussole produit.

### Capacite 1 — Reponse directe (baseline)
**"Repondre aux questions que pose un utilisateur"**

- Que ce soit le RAG ou le KG qui fournisse la reponse, c'est de la plomberie invisible
- L'utilisateur s'en fiche du mecanisme — il veut la bonne reponse
- **Invariant** : OSMOSIS ne doit JAMAIS etre pire qu'un RAG sur cette capacite

**Statut technique** : Implemente (search.py). Benchmark : 35% factual OSMOSIS vs 41% RAG sur questions simples — **a corriger en Sprint 1**.

### Capacite 2 — Synthese multi-document (non evidente)
**"Proposer une reponse qui n'est localisee dans aucun document unique mais fait appel a plusieurs docs sans lien evident"**

- Le KG permet de connecter des claims a travers des documents qui ne se citent pas mutuellement
- Entity→ABOUT + ClaimClusters + CHAINS_TO permettent de reconstruire une reponse distribuee
- **Differenciateur** : un RAG ne retourne que les chunks les plus proches — OSMOSIS peut assembler des pieces d'un puzzle reparti sur 5 documents

**Statut technique** : Partiellement implemente (Phase C light, ClaimClusters cross-doc 820). Benchmark T4 : OSMOSIS 68% completude vs RAG 49%.

### Capacite 3 — Raisonnement differentiel
**"Identifier ce qui est nouveau/modifie par comparaison entre versions"**

- Exemple : "quelles sont les nouvelles fonctionnalites de la derniere version ?"
- Si aucun document ne dit explicitement "nouveau", OSMOSIS doit comparer les fonctionnalites v2022 vs v2023 et deduire par difference
- S'appuie sur les relations MODIFIED/ADDED/REMOVED et l'ApplicabilityFrame (version, release)

**Statut technique** : Partiellement implemente (evolution tracking, QuestionSignatures avec extracted_value). Pas encore benchmarke specifiquement.

### Capacite 4 — Detection de tensions documentaires
**"Deceler quand deux documents ne disent pas la meme chose sur un meme prisme"**

- Contradictions, complements, modifications entre documents
- Prismes de comprehension : version, domaine, produit, perimetre d'application
- REFINES, QUALIFIES, CONTRADICTS dans le KG (252 tensions cross-doc actuelles)
- 5 couches de detection : bucketing → exclusivite predicat → ValueFrame → comparateur formel → arbitrage LLM

**Statut technique** : Implemente. Benchmark T2 : OSMOSIS 100% detection vs RAG 0%. **C'est LE game-changer.**

### Capacite 5 — Validation / Jugement + Transparence AI Act
**"Analyser un input et dire ce qui est vrai, faux ou inconnu selon la documentation"**

- L'utilisateur soumet un texte → OSMOSIS verifie chaque assertion contre le corpus
- Statuts : confirmed / contradicted / incomplete / unknown
- Tracabilite claim-level : chaque jugement est rattache a sa source
- 6 regimes de verite : NORMATIVE_STRICT, NORMATIVE_BOUNDED, EMPIRICAL_STATISTICAL, DESCRIPTIVE_APPROX, CONDITIONAL_SCOPE, TEXTUAL_SEMANTIC
- Evidence-locking : zero connaissance inventee (pointer mode sur unit_ids source)

**Statut technique** : Implemente dans `/verify` (API + frontend) depuis fevrier 2026. Pipeline : AssertionSplitter → EvidenceMatcher (Neo4j + fallback Qdrant) → statut + correction. **Pas encore benchmarke.**

---

## 3. Matrice Capacites vs Concurrence

| Capacite | RAG classique | OSMOSIS | Microsoft Copilot |
|----------|:---:|:---:|:---:|
| 1. Reponse directe | **oui** | oui (= RAG) | **oui** |
| 2. Synthese multi-doc | partiel (top-k) | **oui** (KG cross-doc) | partiel |
| 3. Raisonnement differentiel | **non** | **oui** (evolution tracking) | non |
| 4. Detection tensions | **non** | **oui** (5 couches) | non |
| 5. Validation / AI Act | **non** | **oui** (/verify) | non |

**Zone de differenciation absolue** : Capacites 3, 4, 5 — aucun concurrent actuel ne les propose.

---

## 4. Modes d'Execution (Architecture)

Chaque capacite correspond a un mode d'execution avec des regles differentes :

| Mode | Capacite(s) | KG actif | Prompt | Metrique cle |
|------|------------|----------|--------|-------------|
| **Type A** — Reponse directe | 1 | **Non** (hard constraint) | Permissif | factual_correctness |
| **Type B** — Comparatif cross-doc | 2, 3, 4 | **Oui** (tensions, evolution) | Structure | both_sides_surfaced, tension_mentioned |
| **Type C** — Audit / completude | 2, 4 | **Oui** (clusters, entities) | Exhaustif | completeness, coverage |
| **Type D** — Factuel comparable | 1, 3 | **QD seulement** | Structure | exact_match |
| **Type V** — Validation | 5 | **Oui** (evidence matching) | Ultra strict | precision (vrai/faux) |

### Invariant non-negociable
> **Type A (70% des questions) = chunks strictement identiques au RAG. Zero KG dans le prompt. Zero variance.**

---

## 5. Ce qui Fonctionne vs Ce qui Ne Fonctionne Pas (Mars 2026)

### Valide par le benchmark (275 questions, 2 juges, convergence 0.3%)
| Dimension | Score | Verdict |
|-----------|-------|---------|
| T2 Contradictions OSMOSIS | 100% detection | **Game-changer** |
| T4 Completude OSMOSIS | +19pp vs RAG (KG) | Fort |
| T4 Tracabilite | 94-100% | Excellent |
| ClaimClusters | 2620 (820 cross-doc) | Exploitable |
| IntentResolver | 4.4% ambiguite (regex) | A implementer directement en classificateur ML (Adaptive-RAG) — pas de regex transitoire |
| Calibration inter-juges | 0.3% ecart | Robuste |

### Problematique — a corriger
| Dimension | Score | Cause identifiee |
|-----------|-------|-----------------|
| T1 Factual OSMOSIS (human) | 35% vs RAG 41% | KG perturbe les questions simples |
| False IDK | 33% | 100% probleme prompt (pas retrieval) |
| False Answer | 22% | Reponses partiellement correctes |
| Irrelevant | 26% (vs 17% RAG) | Enrichissement KG elargit hors-sujet |
| Partial hallucination (neg) | 30% (vs 10% RAG) | KG fournit contexte adjacent |
| Bloc KG dans prompt | DEGRADE -8pp | LLM construit biais initial |

---

## 6. Principes Non-Negociables

1. **Agnosticite domaine** : zero code specifique a un domaine (SAP, biomedical, reglementaire)
2. **Auditabilite** : chaque reponse tracable jusqu'au passage source (evidence-locking)
3. **Non-regression** : OSMOSIS >= RAG sur toutes les metriques de base
4. **Transparence AI Act** : pas de black box — chaque jugement explicable
5. **Verite epistemique** : OSMOSIS ne dit jamais "c'est vrai" — il dit "selon les documents X, Y, Z"

---

## 7. Documents de Reference

| Document | Contenu | Statut |
|---------|---------|--------|
| Ce document | Vision produit consolidee | **Reference** |
| `STRATEGY_REPOSITIONNEMENT_OSMOSIS_2026-03.md` | Go-to-market, horizons, cibles | Valide (complementaire) |
| `OSMOSE_VS_RAG_POSITIONNEMENT.md` | Whitepaper technique | Valide (evergreen) |
| `OSMOSIS_CAPABILITIES_OVERVIEW_2026-03.md` | Inventaire technique pipeline | Valide (reference) |
| `OSMOSE_USAGES_QUOTIDIENS.md` | 10 use cases | Valide (commercial) |
| `OSMOSE_PIPELINE_EXPLAINER.md` | "Comment ca marche" | Valide (onboarding) |
| `SPRINT0_RAPPORT_EXHAUSTIF.md` | Benchmark + diagnostics | Valide (donnees) |
| `OSMOSE_CHANTIERS_PROCHAINES_ETAPES.md` | Taches fevrier 2026 | **Deprecie** — remplace par `OSMOSE_TRAVAUX_RESTANTS_2026-03.md` |
| `DEMO_USE_CASES_PLAN_2026-03-20.md` | Plan demo 20 mars | **A archiver** |
