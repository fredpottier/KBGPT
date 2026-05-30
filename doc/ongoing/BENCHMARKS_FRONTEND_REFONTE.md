# Refonte page `/admin/benchmarks` — alignement sur le bench réel (a38 runtime_v6 + RAG)

*Doc de travail — 2026-05-30. Analyse de l'existant + proposition de refonte.*

## 1. Constat : la page mesure ce qu'on ne suit plus, et cache ce qu'on pilote

La page actuelle (`frontend/src/app/admin/benchmarks/page.tsx` + `components/benchmarks/*`)
a **4 onglets** : Vue d'ensemble, RAGAS, Contradictions (T2/T5), Robustesse.

Elle est intégralement câblée sur **3 familles d'évaluateurs de l'ère V3** :

| Famille | Métriques affichées | Source backend |
|---------|--------------------|----------------|
| RAGAS | faithfulness, context_relevance, factual_correctness | `data/benchmark/results/` via `benchmarks.py` |
| Contradictions T2/T5 | both_sides_surfaced, tension, chain_coverage… | idem |
| Robustesse | paraphrase, negation, global_score | idem |

**Problème central** : aucune de ces familles n'est le benchmark qu'on exécute réellement
depuis des semaines. Le bench décisionnel actuel est `app/scripts/bench_a38_runtime_v6.py`
→ `data/benchmark/a38_runtime_v6/run_*.json`, dont **aucune** métrique n'apparaît dans la page :

- `exact_id_recall` (DÉTERMINISTE, métrique primaire — cible vision 0,75-0,80)
- `abstention_correct_rate` (DÉTERMINISTE)
- `exact_id_recall_per_type` + `per_type` juge (factual / list / lifecycle / multi_hop /
  comparison / false_premise / unanswerable) — **la grille de lecture qu'on utilise**
- `C1` (juge LLM, secondaire/bruité), `C3_lifecycle`
- latence p50/p95, `conflict_exposure_rate` (30q CP)
- gates `GA3-5/6/7/9` (✓/✗)
- **NOUVEAU** : bras **classic RAG** (`data/benchmark/a38_classic_rag/run_*.json`) pour
  le comparatif OSMOSIS vs RAG demandé.

Conséquences concrètes :
1. Le pill « Système : Sain / Critique » est calculé sur les scores RAGAS/T2T5/robustesse
   → **non significatif** (ces runs ne sont plus rafraîchis).
2. Les deltas « vs RAG pur » sont des placeholders **jamais peuplés** pour le runtime actuel.
3. La ventilation **par type de question** — notre principal outil de diagnostic — est absente.
4. La page mélange 3 jeux de questions + 3 systèmes de scoring hétérogènes, sans vue unique
   « où en est-on vs les ambitions de la vision ? ».

## 2. Ce que la page DOIT montrer (philosophie déterministe-first)

On pilote au **déterministe** (le juge LLM est bruité à ±0,3, cf mémoire). La refonte doit
hiérarchiser : métriques reproductibles en hero, juge LLM en diagnostic secondaire explicitement
étiqueté « bruité ». Et surtout matérialiser **la preuve de valeur** : OSMOSIS bat-il un RAG classique ?

## 3. Proposition de refonte

### 3.1 Backend — nouvel endpoint lecture seule

`GET /api/benchmarks/a38` → liste les runs des deux bras :
- `data/benchmark/a38_runtime_v6/run_*.json` (arm = `osmosis`)
- `data/benchmark/a38_classic_rag/run_*.json` (arm = `classic_rag`)

Réponse par run : `{timestamp, arm, agg_50q (exact_id_recall_mean, abstention_correct_rate,
exact_id_recall_per_type, per_type, C1_mean, C3_lifecycle_mean, latency_*, gates si présent),
config}`. Réutilise le pattern fichier de `benchmarks.py` (glob + tri + fallback dirs).
`GET /api/benchmarks/a38/{file}` → détail (results_50q) pour le drill-down par question.

### 3.2 Frontend — nouvel onglet primaire « Runtime v6 » (par défaut)

```
┌─ Runtime v6 (a38)  ·  run 2026-05-29 15:54  ·  Novita deepseek-v3.2 ──────────┐
│                                                                               │
│   ★ exact_id_recall      ★ abstention_correct      Latence        Gates       │
│      ╭───────╮              ╭───────╮             p50  31s      GA3-5 ✗ 0.48   │
│      │ 0.79  │ cible 0.75   │ 96 %  │             p95 296s      GA3-6 ✓ 0.50   │
│      ╰───────╯ ✓            ╰───────╯ ✓                         GA3-7 ✗        │
│      DÉTERMINISTE            DÉTERMINISTE                        GA3-9 ✓        │
│                                                                               │
├─ OSMOSIS  vs  RAG classique ────────────────────── (preuve de valeur) ───────┤
│                         OSMOSIS    RAG classique     Δ                        │
│   exact_id_recall        0.79         0.61        +18 pp  ✓                    │
│   abstention_correct     96 %         72 %        +24 pp  ✓                    │
│   C1 (juge, bruité)      0.48         0.41        +7  pp                       │
│   factual                0.62         0.58        +4  pp                       │
│   multi_hop              0.45         0.18        +27 pp  ✓✓                    │
│   comparison             0.45         0.22        +23 pp  ✓✓                   │
│   false_premise          0.30         0.15        +15 pp                       │
│   lifecycle              0.50         0.20        +30 pp  ✓✓                    │
│   latence p50            31 s         4 s         RAG +rapide (attendu)        │
├─ Par type (déterministe + juge) ─────────────────────────────────────────────┤
│   type          n   exact_id_recall   C1(juge)   vs cible                      │
│   factual      12      0.62             0.58      ───                          │
│   multi_hop     6      0.50             0.45      ↗                            │
│   false_premise 5      0.20             0.30      ✗ gap principal              │
│   …                                                                            │
├─ Désaccords juge ↔ déterministe (top) ───────────────────────────────────────┤
│   les questions où C1 et exact_id_recall divergent de >0.3 (signal de bruit)   │
├─ Historique des runs (osmosis + classic_rag) ────────────────────────────────┤
│   date         arm          eir    abst   C1    p95    gates                   │
└───────────────────────────────────────────────────────────────────────────────┘
```

Composants : réutilise `ScoreGauge`, `MetricBar`, `RadarChart`, le pattern `Card`. Ajoute
un tableau comparatif 2-bras + une matrice per-type. La cible vision (0,75-0,80 sur
exact_id_recall) est affichée comme repère sur la gauge.

### 3.3 Onglets V3 → regroupés sous « Archive V3 »

RAGAS / Contradictions / Robustesse **conservés** (valeur historique + règle domain-agnostic :
on ne supprime pas un composant utile), mais déplacés dans un groupe secondaire « Archive V3 »
clairement étiqueté legacy, pour ne plus suggérer qu'ils reflètent l'état courant.

## 4. Découpage proposé

- **Phase 1 (lecture seule)** — endpoint `a38` + onglet « Runtime v6 » + comparatif 2-bras +
  matrice per-type + historique. Démote les onglets V3. ~1 endpoint backend + ~1 gros composant
  front. C'est le cœur de la demande (« redisposer d'une page dédiée aux benchmarks »).
- **Phase 2 (optionnel, lancement)** — bouton « Lancer bench a38 (OSMOSIS + RAG) » via endpoint
  background-task qui shell les 2 scripts. Pré-requis connu : câbler `NOVITA_API_KEY` dans
  `docker-compose` (aujourd'hui le bench tourne en CLI avec `-e NOVITA_API_KEY`). À faire après
  la phase 1.

## 5. Garde-fous

- Déterministe en hero, juge LLM **toujours** étiqueté « bruité » (ne pas reproduire le mirage
  des benchs gonflés A4.14).
- La cible vision n'est PAS SAP-spécifique — les libellés de type (factual/multi_hop…) sont
  domain-agnostic, on garde ce vocabulaire.
- Pas de score « global » unique trompeur : on montre exact_id_recall (factuel) ET les per-type
  (raisonnement) séparément, car la mémoire montre qu'ils racontent deux histoires différentes
  (factuel ≈ cible, raisonnement ~0,5).
```
