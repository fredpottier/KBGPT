# Analyse des claims P1.4 (partiel) — sur-extraction vs gain qualité

> Date : 2026-05-25
> Périmètre : 4 docs ré-ingérés (sur 6 prévus) avec le prompt P1.3.5 sur Qwen2.5-14B (EC2 g6e burst).
> Branche : `feat/phase-b-augmentee`. KG purgé puis ces 4 docs ré-extraits.

## Données (8530 claims, docs 1-4)

| Doc | Claims |
|---|---|
| 025 Feature Scope Description | **6934** |
| 017 Operations Guide | 1055 |
| 012 Installation Guide | 479 |
| training ops | 62 |

**Comparaison clé** : 8530 claims pour **4 docs** ≈ **73% de l'ancien corpus entier** (11 622 claims / 39 docs). → **sur-extraction massive**, surtout Feature Scope (6934 ≈ 60% de l'ancien corpus complet à lui seul).

## Nature de la sur-extraction

- **Longueur** : médiane 99 chars, p25=75, p75=127, fragments <40 chars = **1%**. → **PAS de sur-atomisation** : les claims sont des phrases bien formées, pas des bouts.
- **Redondance** (préfixe 55-60 chars identique) : 6% des claims. Deux formes :
  1. **Sur-décomposition de contenu liste/catalogue** : « Master Data Governance is available in [Custom Objects / Financials / ...] central governance application » → **11 claims** au lieu d'1. « MRO supports processes for [hardware maintenance / component repair / line maintenance] » → 5 claims.
  2. **Quasi-doublons** : « hub systems require this add-on » / « must install this add-on » / « systems require this add-on » → 5 claims pour 1 fait.
- → La sur-extraction = **trop de claims** (chaque phrase/sous-point devient un claim) + sur-décomposition des listes, PAS de la fragmentation en bouts.

## Gain qualité (RÉEL et mesuré)

- ✅ **Décontextualisation : 96% des claims auto-porteurs** (4% démarrent par une anaphore). Le fix « contexte passage » **fonctionne à l'échelle** — c'est la crainte historique (version OSMOSIS précédente) qui est **levée**. Exemples : « Public Sector Collection and Disbursement (PSCD) is used to manage taxes », « The 'Versions' section in Transaction /sapapo/om13 displays... ».
- ✅ **Claims bien formés** : phrases complètes, médiane 99 chars, sujet nommé.
- ✅ **structured_form (triplets relationnels)** : 26% des claims.

## Enrichissement Phase B : faible rendement sur CE corpus

| Type/champ | Volume | % |
|---|---|---|
| FACTUAL | 7835 | 92% |
| DEFINITIONAL | 342 | 4% |
| PRESCRIPTIVE | 314 | 4% |
| **PROCEDURAL** | **15** | **0.2%** |
| CONDITIONAL | 10 | 0.1% |
| qualifiers | 247 | 2% |
| open_predicate | 19 | <1% |

→ Les docs SAP testés sont du **factuel/catalogue de features**, pas du procédural/conditionnel. Les leviers qualifiers (lifecycle) et procédures (multi_hop) trouvent **peu de matière** ici (2% / 0.2%). Ça explique l'échec du linking procédures (15 claims PROCEDURAL seulement) et confirme que **multi_hop ne viendra pas des procédures sur ce corpus**.

## Conclusions

1. **Sur-extraction réelle** (×3,5 à ×23 selon doc) — surtout volume + sur-décomposition de listes, pas fragmentation. Rend la ré-ingestion 38 docs impraticable (Feature Scope seul = 2,3h) ET risque de **diluer le retrieval** (562 quasi-doublons, milliers de claims catalogue de granularité fine).
2. **Décontextualisation = vrai gain validé à l'échelle** (96%). À GARDER.
3. **Qualifiers/procédures = faible rendement** sur corpus factuel SAP → ne pas sur-investir ; multi_hop via PropRAG (runtime) plutôt que procédures.

## Recommandations (prochain chantier)

1. **Recalibrer le prompt d'extraction** : viser des claims **saillants** (~même volume qu'avant, ~300/doc), garder la décontextualisation, mais :
   - **anti-redondance** : ne pas décomposer une énumération en N claims quasi-identiques (1 claim avec la liste, ou dédup sémantique post-extraction) ;
   - retirer/atténuer le « extract EVERY genuine claim » + le question-guided agressif qui sur-produit ;
   - garder qualifiers + open-predicate (peu coûteux, utiles quand présents).
2. **Dédup sémantique** post-extraction (le pipeline a déjà du clustering/redundant — vérifier pourquoi les 11× MDG passent).
3. Re-test 2-3 docs : **cible volume ~300-500/doc** + décontextualisation maintenue, AVANT toute ré-ingestion complète.
4. Pour la ré-ingestion : **g6 (pas g6e)** + 14B, ou recalibrer pour réduire le nb d'appels LLM (le coût/temps est proportionnel au nb de claims).

*KG laissé en l'état (4 docs) — sera re-purgé à la prochaine ré-ingestion. Infra burst détruite (stack supprimée, frais arrêtés).*
