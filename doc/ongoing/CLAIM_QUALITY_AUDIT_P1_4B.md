# Audit qualité du KG staged (P1.4-bis) — 2026-05-26

> Validation de la ré-ingestion staged sur **2 docs réels** (training_aa + 012 Installation,
> Qwen2.5-14B-AWQ exact, burst g6). KG : **1046 claims**. Objectif : ne PAS conclure « c'est ok »
> trop vite (exigence Fred) — analyse poussée + littérature avant d'acter.

## 1. Mesures volume / temps (3 runs)

| Run | Granularité | Concurrence | Grounding | Volume | Temps |
|---|---|---|---|---|---|
| #1 | atomisé | 5 | sync | 1049 | 4884s |
| #2 | moléculaire (prompt) | 32 | sync | 1042 | 3377s |
| #3 | coarse-seg (no split :/;) | 32 | async | 1046 | 3423s |

**Constats** :
- **Volume bloqué à ~1046** : ni la granularité moléculaire (prompt) ni la segmentation grossière ne réduisent. → **Qwen2.5-14B ignore la consigne de granularité fine** (confirme Volet 3 SOTA). Sur de la PROSE, ~1 claim/phrase = granularité saine, PAS la pathologie ×23 (qui était le **catalogue** Feature Scope = énumérations, corrigé par le schéma `objects[]`).
- **Temps ~56 min plat** : le grounding async n'a pas aidé → le GPU est inactif (3 req/0 attente). Le goulot n'est NI le LLM NI le grounding NI la concurrence → **post-processing** (phase 10 canonicalisation = beaucoup d'appels LLM `EntityCanonicalizer`) ou latence série. **À profiler** (poller état Redis sur le prochain run).
- **Concurrence** : bug corrigé (`is_burst_mode_active` lisait le flag interne, pas Redis → bridé à 5 ; fix = `activate_burst_providers` in-process + cap 15→32). Mais gain limité (−31%) car le goulot est ailleurs. **Pas besoin de g6e** (GPU prouvé inactif).

## 2. Qualité par claim — globalement BONNE

- ✅ Spécifiques, **identifiants préservés** (`/CPD/CA_CPD_PFP_1`, KBA 3065607, chemins, `S_TABU_DIS`).
- ✅ **Modalité captée** : 44% PRESCRIPTIVE/PERMISSIVE/CONDITIONAL (vs 92% FACTUAL en P1.3.5) — gain net pour un guide procédural.
- ✅ Longueur saine : moyenne **92 chars**, max 513, seulement **2 claims >300 chars** (pas de blob multi-faits).
- ✅ Décontextualisation majoritairement OK (sujets nommés).

## 3. Le « faux problème » structured_form (36%) — RÉFUTÉ par la littérature

Constat initial inquiétant : seulement **36% des claims ont un structured_form** (triplet). Cause : les objets moléculaires/listes (« A, B, C ») ou phrases (« automatically when the connector is created ») échouent `is_valid_entity_name` → SF droppé.

**Vérification KG décisive** : **1031/1046 claims (98.6%) sont reliés à des entités** via `:ABOUT` (+ SAME_CANON_AS, IN_CLUSTER 440, SIMILAR_TO 7123). **La connectivité graphe / multi-hop passe par le graphe d'ENTITÉS, PAS par le structured_form** (projection secondaire).

**Littérature** (recherche 26/05) :
- **« Extraction loss » (GraphRAG 2025)** : forcer des triplets propres incite à jeter ce qui ne rentre pas → perte systématique. Garder le **texte primaire** + lien source.
- **OpenIE** : les arguments peuvent être des phrases/spans, pas que des entités → objets-phrases légitimes.
- **LLM-KGC** : one-to-many = extraction progressive + regroupement par entités, pas un objet-liste forcé dans un triplet.

→ **L'option « forcer `objects[]`/phrases dans le SF » est exactement l'anti-pattern.** Les claims sans SF gardent texte + verbatim (100%) + subject_canonical (86%) + liens entités (98.6%). **SF à 36% n'est PAS un défaut critique** ; le pousser à 100% dégraderait (extraction loss). **Décision : abandonner l'option A.**

## 4. Vrais (petits) gaps restants

| # | Gap | Mesure | Action |
|---|---|---|---|
| a | **subject_canonical 86%** (147 sans) | les 147 sont TOUS `marginal=true` (sans sujet naturel) : cross-réfs, lead-ins de titre, génériques | **durcir Stage A** (jeter cross-réfs pures + titres) → couverture monte sans forcer de sujet |
| b | **~5% titres/vacants** (« 7.20 X are for… », « the following X are relevant: ») | 50/1046 | **même fix Stage A** |
| c | Grounding marginal bruité | faux positifs sur verbatim format tableau `\| X \|` + « For example » retiré | mineur (flag only) ; raffinement futur |

**Lever consolidé** : (a) + (b) = **un seul durcissement de Stage A** (cross-références pures + fragments de titre/lead-in). Sans jeter les claims qui portent un fait + une référence.

## 5. Décision

- ❌ Abandonner l'option A (forcer le SF) — anti-pattern documenté.
- ✅ Représentation actuelle (texte + entités + verbatim + subject_canonical) **alignée bonnes pratiques** — conserver.
- ✅ Durcir Stage A (cross-réfs + titres) → vise subject_canonical ≥92% + retire le junk.
- ✅ Profiler le post-processing (poller) sur le prochain run.
- ✅ Puis ingestion multi-docs (dont **Feature Scope** = le vrai cas ×23, pour valider le collapse des énumérations à l'échelle).

*Rapports : `data/benchmark/dedup/*`. Probes réutilisables : `p1_dedup_tiered_probe.py`, `p1_utility_filter_smoke.py`.*
