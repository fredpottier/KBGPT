# Protocole de non-régression multi-corpus

**But** : pouvoir attribuer toute variation de qualité soit au **CODE** (régression à corriger), soit au **CORPUS** (effet attendu d'un jeu documentaire différent) — et ne plus « bouger des curseurs » à l'aveugle par corpus.

## Principe directeur

| Couche | Règle |
|--------|-------|
| **Moteur (code)** | Strictement **domain-agnostic**. Aucun curseur calibré sur un corpus précis. Une modif moteur doit améliorer (ou ne pas dégrader) **tous** les corpus de référence. |
| **Corpus** | Vit dans un **tenant distinct** du KG. On **ne purge jamais** pour changer de corpus (sinon on perd la référence). |
| **Gold-set** | **Figé par corpus** (`gold_set_<corpus>_*.json`). C'est lui — pas le moteur — qui varie légitimement d'un corpus à l'autre. |
| **Réglage spécifique** | Si un comportement doit dépendre du corpus → **config / domain-pack**, jamais un curseur dans le code. |

## Mécanique

Chaque run de bench est **étiqueté `(corpus, git_sha, timestamp)`** (cf `bench_a38_runtime_v6.py`,
champs `corpus`/`tenant`/`git_sha` dans le JSON de sortie).

Deux axes de comparaison (`compare_runs.py`) :

1. **Non-régression (CODE)** — *même corpus, git_sha différents*. Toute baisse > seuil sur une
   métrique **déterministe** (`exact_id_recall`, `abstention_correct`) = **régression code** → on rejette.
   ```
   python scripts/compare_runs.py --corpus aero_seats        # 2 derniers runs du corpus
   python scripts/compare_runs.py <run_avant>.json <run_après>.json
   ```
2. **Typologie (CORPUS)** — *même git_sha, corpus différents*. L'écart est l'**effet corpus**, attendu.
   ```
   python scripts/compare_runs.py --typology --git-sha <sha>
   ```

> Le juge LLM (C1) est bruité → **pas de gate de régression dessus**. On pilote au déterministe.
> Une comparaison *même corpus + même code* mesure la **variance** (reproductibilité).

## Règle opératoire (à appliquer systématiquement)

1. **Avant** toute modif moteur : `bench_a38` sur **chaque corpus de référence** → baselines (taguées sha).
2. Faire la modif (agnostique).
3. **Après** : re-bench chaque corpus de référence → `compare_runs.py --corpus <c>` pour chacun.
4. **Merge autorisé seulement si aucun corpus ne régresse.** Une amélioration sur un corpus qui
   dégrade un autre = à revoir (probable curseur déguisé).

## Corpus de référence

| Corpus | Tenant | Gold-set | Statut |
|--------|--------|----------|--------|
| Aéro (sièges/crashworthiness) | `default` | `gold_set_aero_50q.json` / `_150q.json` | ✅ chargé, baseline 02/06 (exact_id 0.92) |
| SAP presales | `sap_ref` | `gold_set_a38_50q.json` (+ `_30q_cp.json`) | ✅ **importé** depuis backup via `import_corpus_as_tenant.py` (38 595 claims + embeddings). Baseline 02/06 : exact_id **0.66 — fidèle** (le runtime n'utilise PAS le contexte domaine, cf note ci-dessous ; 0.66 est donc directement comparable). Écart vs 0.788 de mai = évolution du code, comparaison « mixte » non isolable. |
| Médical (futur) | `medical` | à créer | 🔜 à l'import |

**Action structurante** : les prochains imports de corpus se font **sous un tenant dédié** (ex.
`import_corpus_as_tenant.py --tenant medical` depuis un backup, ou `--tenant medical` à l'ingestion),
jamais en purgeant `default`. Ainsi les corpus coexistent et restent benchmarkables à tout moment.

## Convention de lancement (capture du git_sha)

Le conteneur `/app` n'a pas de `.git` → **passer le sha de l'hôte via l'env `GIT_SHA`** :
```bash
SHA=$(git rev-parse --short HEAD)
docker exec -e GIT_SHA=$SHA knowbase-app python scripts/bench_a38_runtime_v6.py \
  --tenant sap_ref --corpus sap_ref --gold-50q benchmark/questions/gold_set_a38_50q.json
docker exec -e GIT_SHA=$SHA knowbase-app python scripts/bench_a38_runtime_v6.py \
  --tenant default --corpus aero_seats --gold-50q benchmark/questions/gold_set_aero_50q.json --skip-30q-cp
python scripts/compare_runs.py --corpus aero_seats   # non-régression
python scripts/compare_runs.py --typology            # effet corpus
```
Sans `GIT_SHA`, le sha tombe à `unknown` et l'attribution code-vs-corpus n'est plus fiable.

## Note — le runtime n'utilise pas le contexte domaine

`runtime_a3` (pipeline de **réponse** : parse/plan/execute/evaluate/synthesize) **ne lit pas** le
contexte domaine (table PG `domain_contexts`). Le `DomainContextInjector` n'intervient qu'à
l'**ingestion** ClaimFirst. Conséquence : seeder/restaurer un contexte ne change rien au bench ;
la baseline d'un corpus est donc fidèle indépendamment du contexte. Le contexte ne redevient utile
que si le corpus est **ré-ingéré** sous son tenant.

## Limite connue

Tant qu'un seul corpus de référence est chargé (aéro aujourd'hui), la non-régression n'est
vérifiable que sur lui. Recréer SAP (et plus tard médical) sous tenants dédiés = condition pour
le contrôle bi/tri-corpus complet. Coût : ré-ingestion (LLM) par corpus.
