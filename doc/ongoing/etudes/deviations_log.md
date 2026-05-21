# Log des déviations détectées — Vision Guardian

> Ce log est tenu par l'agent `vision-guardian` (slash command `/vision-guardian`).
>
> Chaque entrée correspond à une activité observée (commit, chantier, bench, fichier) qui **ne se rattache pas directement** à un principe de `doc/VISION.md` ou une phase de `doc/EXECUTION_ROADMAP.md`.
>
> **Une déviation N'EST PAS un échec.** C'est une **hypothèse de travail à examiner**. Elle peut être :
> - une bonne idée qui mérite d'enrichir le plan (→ ouvrir un ADR)
> - une distraction tactique sans valeur structurante (→ `dropped`)
> - un apprentissage qui doit faire évoluer la VISION (→ amendement ADR)
> - une priorité prématurée (→ `deferred` à une phase ultérieure)
>
> **L'agent trace, l'utilisateur décide.**

---

## Légende des statuts

| Statut | Signification |
|---|---|
| `new` | Détecté par l'agent, pas encore revu par l'utilisateur |
| `reviewed` | Lu par l'utilisateur, en attente d'arbitrage |
| `integrated` | Validé → intégré à VISION/ROADMAP ou phase courante (préciser comment) |
| `deferred` | Bonne idée mais pas maintenant → différé à phase X (préciser laquelle) |
| `dropped` | Abandonné après revue → tactique, sans valeur structurante, ou anti-pattern confirmé |

---

## Légende des types

| Type | Description |
|---|---|
| **tweak** | Petit ajustement (config, param, prompt tweak) qui vise un score sans changer l'archi |
| **chantier nouveau** | Nouveau chantier (CH-XX) qui n'est pas dans le backlog ADR de la roadmap |
| **bench / mesure** | Nouveau benchmark ou mesure ad-hoc qui ne sert pas une cible C1-C5 explicite |
| **refactor** | Refactoring (non lié à un objectif de phase) |
| **exploration** | POC / spike non rattaché à une phase |
| **violation axiome** | Code/config qui contredit un axiome AX-1 à AX-16 |

---

## Index chronologique

(Le plus récent en haut)

<!-- L'agent ajoute ici les nouvelles entrées au-dessus -->

### 2026-05-21 — Duplication des prompts LLM de classification de relations claim-claim (detect_contradictions vs c4_relations)

- **Type** : dette technique (qualité + maintenabilité) → `deferred`
- **Signal** : audit qualité post-A2.13 (refonte prompt `_LLM_COMPARE_SYSTEM` étape #7 `_run_detect_contradictions`). En lisant `nli_adjudicator.py:NLI_PROMPT` (utilisé par étape #13 `c4_relations`), on constate qu'il fait **la même tâche** que `_LLM_COMPARE_SYSTEM` (classifier une paire claim-claim en CONTRADICTS / REFINES / QUALIFIES / NONE) mais avec un prompt **différent et de qualité supérieure** (4 règles critiques déjà présentes : version/edition co-existantes, features parallèles, product rebranding, "same subject same context").
- **Description** : deux modules indépendants font la même classification avec deux prompts maintenus séparément :
  - `src/knowbase/api/routers/post_import.py:_LLM_COMPARE_SYSTEM` — étape #7 `_run_detect_contradictions` Phase B (claims cluster cross-doc sans S/P/O)
  - `src/knowbase/relations/nli_adjudicator.py:NLI_PROMPT` — étape #13 `c4_relations` (paires embedding cosine ≥ 0.85)

  Les deux ont :
  - Mêmes 4 labels cibles (CONTRADICTS / REFINES / QUALIFIES / NONE ou COMPATIBLE/UNRELATED)
  - Même output JSON
  - Mêmes pièges (version parallel, products parallel, list cumulative, pricing tiered)
  - Mais des wording, exemples et garde-fous **différents** → drift de qualité dans le temps si un seul est amélioré

  L'audit A2.12 a révélé ~80% FP sur les 113 CONTRADICTS de `_LLM_COMPARE_SYSTEM` alors que `nli_adjudicator.NLI_PROMPT` avait déjà mitigé ces cas. Cette divergence prouve que la duplication est nuisible.

- **Pourquoi c'est une déviation** : pas d'élément de VISION/ROADMAP qui parle d'unification des prompts. Mais correspond à un principe de maintenabilité implicite (Probability Isolation §3.5 : "1 LLM = 1 rôle" mais ici on a 2 rôles identiques avec 2 prompts différents — c'est de la duplication de surface API LLM).
- **Bénéfice potentiel** :
  - **Une seule source de vérité** pour la sémantique des relations claim-claim — amélioration une fois propagée partout
  - Réduction risque de drift qualité entre étapes #7 et #13
  - Documentation centralisée des règles "CONTRADICTS vs NONE" dans un module partagé (ex: `src/knowbase/relations/claim_relation_classifier.py`)
  - Plus facile à brancher sur le futur runtime A3 (Parse/Evaluate) qui devra potentiellement utiliser le même classifier
- **Coût d'opportunité** : ~0.5j de refacto pour extraire un `ClaimRelationClassifier` partagé + ré-tester les 2 chemins (sans bénéfice immédiat car les 2 prompts marchent maintenant). À faire **plus tard** quand on aura besoin de modifier la sémantique des relations (Phase A3 runtime, ou nouvelle relation type).
- **Recommandation agent** :
  - [ ] **`deferred`** : créer task `A2-DEBT-PROMPTS-UNIFY` dans le backlog (statut `pending`, sans phase rattachée), à promouvoir si :
    - Phase A3 nécessite cette classification (probable — Evaluate module CRAG-style va sans doute réutiliser le même test "co-exist simultaneously")
    - Ou une troisième impl émerge (risque de divergence à 3 voies)
  - [ ] Tant que `deferred` : ajouter un commentaire `# DEVIATION 2026-05-21 — prompt duplication, voir deviations_log.md` dans les 2 fichiers concernés pour éviter qu'un futur dev modifie un seul prompt sans synchronisation manuelle
- **Statut** : `deferred` (arbitré 2026-05-21 par utilisateur produit : "inscris l'utilité de cette unification dans deviations_log.md")

---

### 2026-05-19 — Architecture Parse+Evaluate pour query understanding (vs single-shot classifier)

- **Type** : exploration → integrated immédiatement (correction architecturale critique)
- **Signal** : analyse de l'état de l'art 2026 sur "query understanding + tool routing" demandée par utilisateur produit (19/05/2026)
- **Description** : V5.1 et l'EXECUTION_ROADMAP Phase A3 (état initial) reposent sur un **single-shot classifier** (`answer_shape` factual/list/temporal/comparison/causal) qui détermine **irréversiblement** le routing tool. État de l'art 2026 (CRAG arxiv 2401.15884, Iterative Routing arxiv 2501.07813, QAgent arxiv 2510.08383, Adaptive RAG) prescrit une architecture en 5 étapes : **Parse (sub-goals) → Plan (déterministe) → Execute → Evaluate (lightweight evaluator CRAG-style) → (Re-plan if AMBIG)**, avec feedback loop max 2 itérations + hard cap anti-thrash.
- **Pourquoi c'est une déviation** : ne se rattache PAS à un élément actuel de VISION ou ROADMAP. **MAIS** correspond à une **lacune architecturale fondamentale** : sans ce mécanisme de récupération d'erreur de classification, le système plafonne quel que soit le LLM utilisé (cf observation V5.1 plafond 0.61 + V6-J1/J2 outils dormants). Le principe "Decomposition over Classification" + "Lightweight Evaluator" est documenté comme **prérequis** dans l'état de l'art 2026 pour atteindre 80%+ de fiabilité.
- **Bénéfice potentiel** :
  - Robustesse aux erreurs de classification initiale (rattrapage par evaluator)
  - Conformité Probability Isolation (parser + evaluator + format = 2-3 LLM calls max)
  - Cible C1 ≥80% et C3 ≥80% deviennent atteignables (vs plafonnement V5.1)
- **Coût d'opportunité** : 0j car correction effectuée AVANT démarrage Phase A3. Si on n'avait pas intégré cette idée, on aurait construit runtime_v6 sur le pattern single-shot et atteint le même plafond.
- **Recommandation agent** :
  - [x] **Faire évoluer VISION/ROADMAP** — amendement immédiat (avant Phase A3) :
    - VISION.md §3.5 : enrichir Probability Isolation avec "parse + evaluate + format" (vs "intent + format")
    - VISION.md §4.4 : refondre pipeline runtime cible avec boucle Parse → Plan → Execute → Evaluate
    - VISION.md §8.1 : ajouter "single-shot classification routing rigide" comme anti-pattern documenté
    - EXECUTION_ROADMAP §1.2 : ajouter composant "Runtime Parse+Evaluate Architecture" à la matrice maturité
    - EXECUTION_ROADMAP §2 Phase A3 : refonte explicite intégrant 5 modules (Parse / Plan / Execute / Evaluate / Synthesize)
    - EXECUTION_ROADMAP §4 : ajouter `ADR_PARSE_EVALUATE_RUNTIME.md` en P0 (à rédiger avant code Phase A3)
- **Statut** : `integrated` (arbitré 2026-05-19 par utilisateur produit)

**Sources externes consultées** :
- Iterative Routing in Multi-agent Systems — [arxiv 2501.07813](https://arxiv.org/pdf/2501.07813)
- QAgent — Interactive Query Understanding — [arxiv 2510.08383](https://arxiv.org/pdf/2510.08383)
- Corrective RAG (CRAG) — [arxiv 2401.15884](https://arxiv.org/pdf/2401.15884)
- Adaptive RAG — [Meilisearch 2026](https://www.meilisearch.com/blog/adaptive-rag)

**Amendement enrichi par retour Claude Web (2026-05-19) — 4 risques addressed** :

Claude Web a passé les amendements appliqués (VISION.md + EXECUTION_ROADMAP.md Phase A3) en revue critique le 2026-05-19. 4 points soulevés, tous validés par utilisateur produit, intégrés au plan :

1. **AX-3 ne couvrait pas le runtime** (critique) — L'axiome AX-3 disait "LLM = extracteur evidence-locked à l'ingestion" mais ne mentionnait pas les 3 points de contrôle au runtime (Parse + Evaluate + Format). Risque : ambiguïté qui pouvait laisser passer un LLM ailleurs dans le pipeline. **Résolution** : AX-3 amendé pour couvrir explicitement runtime + ingestion (cf VISION.md §2 AX-3).

2. **Evaluator = SPOF non-mesuré** (risque) — Le module Evaluate (CRAG lightweight) devient le composant qui décide si re-plan ou pas. Si son accuracy est faible, soit on re-plan inutilement (latence explose) soit on accepte des mauvais résultats (qualité chute). **Résolution** : sous-tâche **A3.4-bis** ajoutée à EXECUTION_ROADMAP §2 Phase A3 — bench evaluator isolé sur cas synthétiques (correct/partial/incorrect/ambiguous), gate **≥85% accuracy** avant intégration runtime.

3. **Pas de mesure delta vs alternatives** (risque) — Sans ablation study, on ne sait pas si le gain de runtime_v6 (Parse+Evaluate+KG) vient réellement de l'architecture ou si V5.1 + prompt-tuning aurait obtenu pareil. **Résolution** : sous-tâche **A3.9** ajoutée — ablation study comparant runtime_v6 vs V5.1 + meilleur prompt-tuning possible sur bench 100q. Gate **delta ≥10pp** sinon revoir le choix d'architecture.

4. **Latence p95 non quantifiée + manque kill switch** (risque) — Architecture Parse → Plan → Execute → Evaluate → (Re-plan) ajoute 2-3 LLM calls + boucle. Si Parse échoue souvent (re_plan_rate élevé), latence p95 peut dépasser 60s. **Résolution** : Kill switch **K-7** ajouté à EXECUTION_ROADMAP §3 — surveille `re_plan_rate >30%`, `evaluator_accuracy <85%`, et `latency_p95 >60s` avec re-plan. Pause si déclenché.

Statut : 4 amendements appliqués en séquence après validation utilisateur ("oui je valide tout cela"). Aucun ne remet en cause le pivot d'architecture lui-même — c'est un durcissement des gates et garde-fous.

---

### 2026-05-19 — 11 tâches héritées non rattachées à la roadmap A→D

- **Type** : chantier nouveau (gouvernance backlog)
- **Signal** : 11 tâches `pending` ou `in_progress` dans le tracker au moment de la première invocation de `vision-guardian` :
  - `#70` Fix facet linkage 27% biomédical (embedding similarity)
  - `#246` CH-52.9 S8 Threat Model + Domain-Agnostic + Red-team + Domain Packs
  - `#247` CH-52.10 S9 Frontend chat V5 + workspace drill-down
  - `#248` CH-52.11 S10/S11 Deployment Strategy + Tests + Réingestion + Blind A/B
  - `#305` V6-P2.2 Batch extraction 3 docs complets SAP
  - `#308` Voie B — V6 évolution ClaimFirst pipeline + purge KG + réingestion
  - `#309` Voie A.2 — Valider multiform seul sur bench 50q complet
  - `#312` V6-J2 Reference typée (in_progress)
  - `#313` V6-J3 ConceptCard auto-générée
  - `#314` V6-J0 Purge KG + réingestion complète corpus 38 docs
- **Description** : Ces tâches ont été créées avant la refondation Vision (18/05/2026). Aucune ne se rattache explicitement à une phase A→D ni à un ADR au backlog (§4 EXECUTION_ROADMAP). Plusieurs sont des héritages directs de la dérive 08-18/05 (V6-J2, V6-J3, V6-J0, Voie A.2, Voie B = continuation de l'approche "tweaks bench V5.1 sans plafond") qui est précisément ce que VISION §8.4 identifie comme anti-pattern à arrêter.
- **Pourquoi c'est une déviation** : VISION §11.3 dit explicitement *"Si un nouveau chantier est proposé sans pouvoir être rattaché à un principe de ce document, il doit être tracé dans le log des déviations pour arbitrage explicite"*. Ces 11 tâches n'ont jamais été arbitrées vs la roadmap A→D. Les garder telles quelles risque de re-déclencher la boucle de tweaks (anti-pattern §8.4) au premier moment de baisse d'attention.
- **Bénéfice potentiel** :
  - `#246, #247, #248` (CH-52.9/10/11) : peuvent contenir des éléments d'infrastructure réutilisables pour runtime_v6 (cf audit code 18/05 — 65% réutilisable) → à arbitrer en lien avec Phase A
  - `#314` V6-J0 (purge KG + réingestion) : peut s'aligner avec Phase A2 (relations claim-vs-claim qui nécessitent ré-extraction)
  - Les autres (`#312, #313, #305, #308, #309`) : majoritairement continuation du paradigme V5.1+outils dormants, peu d'alignement avec KG-first runtime
- **Coût d'opportunité** : si on garde tout telles quelles → risque de re-démarrer ces tâches en mode "tweak" alors que Phase A1 (bitemporel) devrait être la priorité. Coût direct : ~0.5j d'arbitrage maintenant ; coût d'inaction : potentiellement 1-2 sem de re-dérive plus tard.
- **Recommandation agent** :
  - [x] **Différer à phase ultérieure** : `#246` CH-52.9 (Domain-Agnostic + Domain Packs) → Phase D1 (Domain Pack mécanisme) ; `#247` CH-52.10 (Frontend chat V5) → Phase C ; `#248` CH-52.11 (Deployment + réingestion) → Phase D2-D4
  - [x] **Différer à phase ultérieure** : `#314` V6-J0 (purge + réingestion) → Phase A2 (sera nécessaire post-bitemporel pour ré-extraire les claims avec les 4 timestamps)
  - [x] **Différer + ré-examiner** : `#70` facet linkage biomédical → après Phase B (validation cross-domain), c'est un fix V5 sur un domaine qui pourrait être impacté par le pivot
  - [x] **Ignorer / dropped** : `#312` V6-J2, `#313` V6-J3, `#305` V6-P2.2, `#309` Voie A.2 → continuation V5.1+outils dormants, hors paradigme KG-first runtime. À marquer `dropped` ou `deferred` selon décision utilisateur.
  - [x] **Ignorer / dropped** : `#308` Voie B (V6 évolution ClaimFirst + purge + réingestion) → est en partie absorbé dans Phase A2 du nouveau plan, doublonne avec V6-J0 (#314)
- **Statut** : `integrated` (arbitré 2026-05-19 par l'utilisateur)

**Décisions appliquées dans le tracker (2026-05-19)** :
- `#314` V6-J0 → **integrated** Phase A2 (subject mis à jour : "PHASE A2 — V6-J0 Purge KG + réingestion 38 docs")
- `#70` facet linkage biomédical → **deferred** post-Phase B (subject prefix "DEFERRED post-Phase B")
- `#246` CH-52.9 → **deferred** Phase D1 (subject prefix "DEFERRED Phase D1")
- `#247` CH-52.10 → **deferred** Phase C (subject prefix "DEFERRED Phase C")
- `#248` CH-52.11 → **deferred** Phase D2-D4 (subject prefix "DEFERRED Phase D2-D4")
- `#305` V6-P2.2 → **dropped** (status: deleted dans tracker)
- `#308` Voie B → **dropped** (status: deleted, absorbé par Phase A2 via #314)
- `#309` Voie A.2 → **dropped** (status: deleted, multiform contredit Probability Isolation)
- `#312` V6-J2 → **dropped** (status: deleted, outil dormant confirmé ; infra Neo4j Reference conservée pour usage futur si runtime_v6 le sollicite)
- `#313` V6-J3 → **dropped** (status: deleted, idem paradigme outil dormant)

---

## Statistiques (à mettre à jour à chaque revue)

| Période | Déviations détectées | Statut majoritaire | Note |
|---|---|---|---|
| 19/05/2026 (init) | 0 | — | Premier état |

---

## Comment l'utilisateur traite ce log

Workflow recommandé :

1. **Lecture en début de session** : `cat doc/ongoing/etudes/deviations_log.md` pour voir les déviations `new` depuis la dernière session
2. **Arbitrage** : pour chaque entrée `new`, l'utilisateur :
   - Lit la description + bénéfice/coût/recommandation
   - Décide : `integrated` / `deferred` / `dropped` / continue à `reviewed` si ambigu
   - **Modifie le statut** dans le log (et la section "Statuts" de l'entrée si besoin)
   - Si `integrated` : crée la tâche correspondante ou met à jour VISION/ROADMAP (avec ADR si rupture d'axiome)
   - Si `deferred` : note la phase cible
3. **Revue périodique** des `deferred` : en début de Phase B, C, D, relire les `deferred` pour les promouvoir si pertinent.

---

## Anti-patterns à ne PAS faire

- ❌ **Supprimer une entrée `new`** : préférer `dropped` avec une raison (préserve la mémoire d'apprentissage)
- ❌ **Tout marquer `integrated`** : si tout devient prioritaire, plus rien ne l'est. Discipline = direr "non" ou "plus tard" 80% du temps
- ❌ **Ignorer le log pendant 1 mois** : il devient illisible. Mieux vaut une revue de 5 min/jour qu'une revue de 1h/mois

---

*Log initialisé le 19/05/2026 par REFONDATION P4 (création agent vision-guardian).*
