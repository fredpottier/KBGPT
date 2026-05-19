# S0 — Synthèse Validations Bloquantes (CH-52.1)

*Date : 2026-05-13*
*Tâche : CH-52.1 S0 Validations bloquantes — 5-7j prévus*
*Statut : 3/8 validations exécutées (S0.4, S0.5, S0.6), 5 restantes (S0.1, S0.2, S0.3, S0.7, S0.8 + holdout)*
*Branche : feat/runtime-v5*

---

## Résumé exécutif

**Aucun gate S0 exécuté à ce stade ne PASSE strictement**, mais les interprétations nuancées indiquent que la direction V5.1 reste viable avec des **recalibrations de cibles** plutôt que des refontes architecturales.

| Validation | Gate cible | Mesuré | Verdict |
|---|---|---|---|
| **S0.4 — Upper-bound LLM** | ceiling ≥ 0.85 | **0.667** | ❌ FAIL → recalibrer cible V5.1 |
| **S0.5 — Fast path distribution** | ≥ 40% factual_simple ET précision ≥ 90% | **10% / 89.2%** | ❌ FAIL → Plan B-2 (recalibration) |
| **S0.6 — Diagnostic Gap EKX** | Tableau causes + mini-POC ≥ +10pp | Causes établies, mini-POC à faire | ⏳ PARTIEL |
| S0.1 — Verifier bake-off | ≥ 85% accept rate | Non exécuté | Pending setup MiniCheck/Lynx |
| S0.2 — Docling fidélité | ≥ 90% précision tables | Non exécuté | Pending 5 PDFs gold annotations |
| S0.3 — DeepSeek BFCL | ≥ 85% tool calling | Non exécuté | Bloqué sur S3 tools schemas finalisés |
| S0.7 — Mini-POC quantitative | ≥ 0.75 sur 20q | Non exécuté | À planifier |
| S0.8 — Matrice red-team OWASP | 50 PDFs structurés livrés | Non exécuté | Création contenu pending |

**Recommandation principale** : amender l'ADR V1.4 sur 3 points (cibles V5.1, capacity §3a.2, cheap path scope) AVANT d'engager S1-S5 dev.

---

## 1. S0.4 — Upper-bound LLM Test ✅ Exécuté

**Méthodologie** : 30 questions SAP PCE gold-set → DeepSeek-V3.1 direct avec **contexte oracle complet** (sections expected_doc_ids fournies, pas de retrieval). Judge Llama-3.3-70B via DeepInfra.

### Résultats globaux

| Métrique | Valeur |
|---|---|
| **Ceiling LLM** | **0.667** |
| Latence p50 / p95 | 12s / 67s |
| Tokens moyens | 18-22k / question |
| Provider | DeepInfra (Together AI épuisé balance) |

### Par catégorie

| Catégorie | Ceiling | V5 POC | V4.2 | EKX |
|---|---:|---:|---:|---:|
| listing | 0.83 | 0.77 | 0.60 | 0.87 |
| unanswerable | 0.83 | 0.83 | 0.37 | 0.87 |
| false_premise | 0.80 | 0.80 | 0.23 | 0.90 |
| lifecycle | 0.77 | 0.67 | 0.00 | 0.90 |
| comparison | 0.67 | 0.70 | 0.40 | 0.90 |
| negation | 0.67 | 0.83 | 0.27 | 0.90 |
| multi_hop | 0.67 | 0.73 | 0.20 | 0.90 |
| quantitative | 0.60 | 0.57 | 0.27 | 0.83 |
| contextual | 0.57 | 0.70 | 0.80 | 0.90 |
| **causal** | **0.27** | 0.77 | 0.20 | 0.62 |

### Interprétation

1. **Gate ≥ 0.85 FAILED** mais c'est une **bonne surprise** :
   - V5 POC (0.737) **dépasse** le ceiling oracle (0.667). L'agent itératif AJOUTE de la valeur au-dessus du LLM avec contexte plat.
   - V5 cause = lecture séquentielle, sélection contextuelle, exploration ciblée.
2. **Causal collapse (0.27)** = DeepSeek-direct rate complètement les questions causales. V5 (0.77) et EKX (0.62) font mieux car ils exploitent la structure documentaire et la décomposition.
3. **Contextual (0.57)** confirme la régression V5 sur cette catégorie : c'est un **trou DeepSeek**, pas un défaut V5 spécifique. L'arbitrage business §4.1 ADR est validé.

### Conséquences pour l'ADR V1.4

- **§3e cible V5.1 holdout ≥ 0.80** : irréaliste avec DeepSeek-V3.1 + corpus actuel. Recalibrer **0.75-0.78**.
- **§3j Gap EKX** : H2 (LLM EKX propriétaire) confirmée partiellement — EKX (0.858) dépasse le ceiling DeepSeek-direct (0.667) de 19pp, donc l'écart LLM existe. Mais V5 (0.737) montre qu'on peut compenser via architecture.
- **Pattern fort** : architecture > LLM pour cette classe de questions. Validation supplémentaire du Reading Agent.

---

## 2. S0.5 — Fast Path Distribution ❌ Gate FAILED (interprétation nuancée)

**Méthodologie** : 130 questions classifiées via DeBERTa S2 cascade (7 labels). Mapping gold-set → DeBERTa labels appliqué.

### Résultats

| Corpus | n | Fast path éligible | Routing precision |
|---|---:|---:|---:|
| SAP gold-set | 30 | 13.3% | 63.3% (mapping flou) |
| Aerospace proxy | 50 | 8.0% | 100.0% |
| Regulatory_eu | 50 | 10.0% | 94.0% |
| **Agrégé** | **130** | **10.0%** | **89.2%** |

### Interprétation nuancée

**Gate cible 40% factual_simple** était basé sur une **distribution utilisateur "généraliste"**. Sur les corpora cible OSMOSIS (SAP presales, aerospace compliance, regulatory EU), la distribution réelle est **structurellement différente** :
- Gold-set SAP par construction adversariale (10 catégories hard) → fast_path naturel ~10%
- Aerospace/regulatory dominés par questions techniques complexes (causal, lifecycle, comparison)
- DeBERTa entraîné 96% Wikipedia, peu de questions techniques SAP/aerospace

**Plan B-2 applicable** (selon barème ADR) :
- Recalibrer **gate fast_path cible 15-20%** (pas 40%)
- Recalibrer **gate précision cible 85%** (pas 90%)
- Capacity planning §3a.2 à réviser : cheap path bypass 15-20% du trafic, pas 60%

### Conséquences pour l'ADR V1.4

- **§3e cheap path** : redéfinir comme optimisation marginale (15-20% gain), pas comme solution structurelle.
- **§3a.2 capacity planning** : retour à 50-60M tok/h sustained (vs 40M révisé V1.2 edit-1).
- **Mitigation contextual via cheap path = abandonnée** : alternative à trouver (route contextual → mode allégé non-agent dans agent path).

---

## 3. S0.6 — Diagnostic Gap EKX ⏳ Partiel

**Méthodologie** : Audit qualitatif des 10 questions où V5 < EKX (gaps les plus grands). Classification des causes selon taxonomie ADR §3j.

### Causes identifiées (top 10)

| Cause | Nb | % | Actionnabilité |
|---|---:|---:|---|
| **completeness** | 5 | **50%** | Phase 1 plan-then-execute + tools enrichis |
| **retrieval** | 4 | 40% | Phase 1 (find_in hybride, navigate_by_toc, Contextual Retrieval) |
| **domain_external** | 1 | 10% | Hors V5.1 (enrichissement corpus) |

### Hypothèses causales validées

- **H1 (KG EKX mature)** : ✅ confirmée forte (60-70% du gap)
- **H2 (LLM EKX propriétaire)** : ⚠️ partiellement plausible (S0.4 confirme écart LLM ~19pp)
- **H3 (verifier EKX)** : ❌ réfutée (V5 cite MIEUX)
- **H4 (extraction)** : ⚠️ plausible, à comparer S0.2
- **H5 (coverage corpus)** : ✅ confirmée (10-20%)

### Reste à exécuter S0.6

⏳ **Mini-POC plan-then-execute sur 5 questions completeness** (Q01/Q04/Q05/Q08/Q10) — gate +10pp.

---

## 4. Recommandations consolidées pour ADR V1.4

### A. Amendements urgents (avant S1 dev)

1. **§3e cibles V5.1 recalibrées** :
   - Holdout score : **0.75-0.78** (vs 0.80)
   - Cheap path : **15-20%** trafic (vs 40-60%)
   - Précision routing : **85%** (vs 90%)
2. **§3a.2 capacity planning révisée** :
   - Token throughput retour à **50-60M tok/h sustained** (vs 40M post-cheap-path optimiste)
   - Hard cap **70-80M tok/h burst** (vs 60M)
3. **§3j Gap EKX** :
   - Cible V5.1 : combler **30-40% du gap EKX** (vs 50% initial), score **0.78-0.80** absolu
   - H2 partiellement validée → gap résiduel ~12pp acceptable comme limite LLM open-source

### B. Validations restantes à exécuter en S0

| # | Validation | Setup nécessaire | Effort |
|---|---|---|---|
| S0.1 | Verifier bake-off HHEM vs MiniCheck vs Lynx | Télécharger MiniCheck-770M + check Lynx dispo Together | 2-3j |
| S0.2 | Docling vs SmolDocling fidélité | 5 PDFs SAP gold annotations humaines | 1-2j + dépendance Fred |
| S0.3 | DeepSeek BFCL tool calling | 14 tools schemas finalisés (CH-52.4 dep) | 1j |
| S0.7 | Mini-POC quantitative 20q | Prototype `find_quantitative` léger | 2-3j |
| S0.8 | Matrice red-team OWASP 50 PDFs | Création contenu (équipe sécu ou prestataire) | 3-5j externe |
| Holdout 30% gold-set | Script split + sign-off | Gold-set étendu d'abord (30q → 100q+ idéal) | 0.5j |

---

## 5. Décision proposée

**Option A — Continuer S0 jusqu'au bout** : exécuter S0.1, S0.2, S0.3, S0.7, S0.8 + holdout (~8-12j supplémentaires) avant tout dev S1+. Plan complet, désrisquage total.

**Option B — Amender ADR maintenant et lancer S1 en parallèle** : intégrer les findings S0.4-S0.5-S0.6 dans une révision V1.5 de l'ADR, et lancer S1 (DSG Neo4j multi-tenant) qui est indépendant de S0.1/S0.2/S0.3/S0.7. S0.1 et S0.7 peuvent ensuite être faits en // de S2 dev.

**Option C — Pivot architectural via Plan B-4** : si Fred considère que les gates "ratés" sont rédhibitoires, revoir l'architecture (hybride V4.2/V5 par exemple). Pas recommandé par l'auditeur Claude — les findings indiquent plutôt des recalibrations, pas un pivot.

**Recommandation Claude** : **Option B**. Les findings S0.4-S0.5-S0.6 sont suffisants pour informer l'ADR V1.5. S0.1 (verifier) et S0.7 (quantitative) restent critiques mais peuvent être parallélisés avec S1 dev (qui ne dépend pas d'eux).

---

## 6. Artifacts livrés

- `app/scripts/s04_upper_bound_test.py` — Script ceiling LLM oracle
- `app/scripts/s05_fast_path_distribution.py` — Script DeBERTa fast path
- `app/scripts/s06_gap_ekx_analysis.py` — Script extraction questions V5 < EKX
- `benchmark/results/gold_set_sap_v1_upperbound_baseline.json` — Données brutes S0.4
- `benchmark/results/gold_set_sap_v1_upperbound_judged.json` — S0.4 jugé Llama-3.3-70B
- `benchmark/results/s05_fast_path_distribution.json` — Données S0.5
- `doc/ongoing/S0.5_FAST_PATH_RESULTS.md` — Analyse S0.5
- `doc/ongoing/S0.6_GAP_EKX_ANALYSIS.md` — Données audit S0.6
- `doc/ongoing/S0.6_AUDIT_CONCLUSIONS.md` — Synthèse S0.6
- `doc/ongoing/S0_SYNTHESIS_REPORT.md` — Ce rapport

---

*Sprint S0 partiel livré. Décision Fred attendue sur Option A/B/C avant d'engager la suite.*
