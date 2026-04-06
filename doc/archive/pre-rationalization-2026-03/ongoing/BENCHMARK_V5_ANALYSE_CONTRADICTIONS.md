# Benchmark V5 — Analyse détaillée de la gestion des contradictions

**Date** : 29 mars 2026
**Contexte** : Benchmark complet OSMOSIS vs RAG après activation du KG Signal-Driven
**Objectif** : Comprendre pourquoi OSMOSIS ne surfasse pas les contradictions malgré leur détection

---

## 1. État des lieux du KG

### Données disponibles dans Neo4j
- **15 566 claims** avec embeddings (100% couverture)
- **20 relations CONTRADICTS** cross-doc identifiées
- **11 849 claims** bridgés à des chunks Qdrant (76.1%)
- **Index vectoriel** `claim_embedding` (1024 dims, cosine) opérationnel
- **Signal-driven pipeline** fonctionnel : `_search_claims_vector()` → `detect_signals()` → `build_policy()` → `synthesis_additions`

### Thématiques des contradictions réelles dans le KG
1. **Dispute Management** (7 contradictions) : sync vs async BAPI, direction des IDocs, BAPI vs RFC
2. **Commodity Procurement** (6) : localisation données personnelles (VLOGP vs PEV vs BRFplus vs Pricing Conditions)
3. **SSO Logon tickets** (3) : ISF vs CA-TS vs E-Recruiting vs S/4HANA
4. **Naming** (2) : S/4HANA Cloud Private Edition vs Cloud ERP Private Edition
5. **Field Service Management** (1) : intégration ECC vs Cloud Integration
6. **Control cycles** (1) : planning procedure indépendant vs identique dans SUMA

---

## 2. Architecture actuelle de la chaîne contradictions

```
Question utilisateur
    │
    ▼
[1] _search_claims_vector() — Neo4j vector index
    → Retourne ~10 claims avec :
      - entity_names (via ABOUT→Entity)
      - contradiction_texts (via CONTRADICTS/REFINES/QUALIFIES)
      - chunk_ids (pont vers Qdrant)
    │
    ▼
[2] Retrieval Qdrant — INVARIANT : identique au RAG pur
    → 10 chunks vectoriels
    │
    ▼
[3] _build_kg_context_block() — Bloc séparé (pas dans les chunks)
    → "Entities identified: ..."
    → "Tensions detected: ⚠ CONTRADICTION: ..."
    → "Additional verified facts: ..."
    → Limité à 600 chars (guard-rail ~150 tokens)
    │
    ▼
[4] detect_signals() — Détection signal tension
    → Regarde si contradiction_texts non vides
    → Produit SignalReport avec signal "tension"
    │
    ▼
[5] build_policy() — Signal Policy
    → Si tension détectée :
      - fetch_missing_tension_docs = True
      - synthesis_additions += "IMPORTANT: Sources contain DIVERGENCES..."
    │
    ▼
[6] synthesize_response() — Claude Haiku
    → Reçoit : chunks RAG + KG Context block + Signal additions
    → Produit la réponse finale
```

---

## 3. Résultats benchmark V5 — Contradictions

### T2 Expert (25 questions manuelles, évaluation manuelle)

| Métrique | OSMOSIS | RAG | Δ |
|----------|---------|-----|---|
| Factual correctness avg | **0.62** | 0.56 | **+6pp** |
| Answers correctly | **44%** | 36% | **+8pp** |
| Both sides surfaced | **36%** | 28% | **+8pp** |
| Tension mentioned | 16% | 16% | = |

**Constat** : OSMOSIS surfasse mieux les deux côtés (+8pp) mais ne mentionne pas plus souvent la tension explicitement. Le KG aide à *trouver* les deux positions mais ne force pas le LLM à *signaler* la divergence.

### T5 Proactive Detection (5 questions simples qui cachent une contradiction)

| Métrique | OSMOSIS | RAG |
|----------|---------|-----|
| Proactive detection rate | **0%** | 0% |
| Both sides surfaced | **0%** | 0% |
| Contradictions dans les métadonnées | **3-8 par question** | 0 |

**Constat critique** : Le KG détecte entre 3 et 8 contradictions par question dans les métadonnées. Le signal tension est activé. La policy ajoute "Sources contain DIVERGENCES" dans le prompt. **Mais Haiku ne mentionne aucune divergence dans la réponse.**

### Exemple concret — T5_PROACTIVE_0003

**Question** : "Où sont stockées les données personnelles pour le module Commodity Procurement and Commodity Sales ?"

**Ce que le KG détecte** (métadonnées de la réponse) :
- 5 contradiction_texts
- Entités : Commodity Procurement, VLOGP, PEV, BRFplus
- Signal tension activé → policy ajoute "DIVERGENCES detected"

**Ce que Haiku répond** :
> "Basé sur les sources disponibles, voici ce qui est documenté concernant le stockage des données personnelles..."
> → Liste VLOGP et quelques emplacements MAIS ne signale AUCUNE divergence entre les versions 2022 et 2023.

**Ce qu'OSMOSIS devrait répondre** :
> "⚠ Les documents SAP présentent des informations divergentes sur ce sujet. Le Security Guide 2022 indique que les données sont dans PeriodEnd Valuation (PEV), tandis que le Security Guide 2023 les place dans VLOGP et les BRFplus Decision Tables. Cette évolution peut refléter une migration entre versions."

---

## 4. Diagnostic : pourquoi ça ne fonctionne pas

### 4.1 Le KG fait son travail — le LLM ne suit pas

La chaîne de détection fonctionne parfaitement :
- `_search_claims_vector()` → trouve les claims avec CONTRADICTS ✅
- `detect_signals()` → signal tension détecté ✅
- `build_policy()` → ajoute "Sources contain DIVERGENCES" dans le prompt ✅
- `_build_kg_context_block()` → bloc KG avec tensions ✅

Mais Claude Haiku **ignore l'instruction** de mentionner les divergences. Le prompt synthesis dit :
```
MANDATORY RULES:
...
5. If sources contain contradictions or divergences, mention them explicitly
```

Et la policy ajoute :
```
IMPORTANT: Sources contain DIVERGENCES on this topic. Present BOTH positions with their sources.
```

Haiku voit ces instructions mais ne les exécute pas. Raisons possibles :
1. **Les instructions sont noyées** dans un prompt de 8000+ tokens. Le LLM priorise la réponse factuelle.
2. **Le bloc KG est limité à 600 chars** (guard-rail). Les tensions sont tronquées et perdent leur contexte.
3. **Le format des tensions n'est pas assez explicite** : `"⚠ CONTRADICTION: SAP S/4HANA supports..."` ne dit pas clairement "le Security Guide 2022 dit X, le Security Guide 2023 dit Y".
4. **Pas de section dédiée dans le template de réponse** qui forcerait le LLM à traiter les tensions.

### 4.2 Le retrieval ne ramène pas les deux côtés

Sur les 25 questions T2 Expert, ~10 échouent car les chunks des deux documents en tension ne sont pas dans le top 10 Qdrant. Le retrieval vectoriel est biaisé vers un seul document (le plus similaire sémantiquement).

Même quand le KG détecte la tension et que la policy demande `fetch_missing_tension_docs`, le retrieval ciblé ne ramène pas toujours les bons passages.

### 4.3 Le format du bloc KG est sous-optimal

Actuellement, le bloc KG ressemble à :
```
## KG Context
Entities identified: VLOGP, PEV, Commodity Procurement and Commodity Sales
Tensions detected:
  ⚠ CONTRADICTION: Commodity Procurement provides personal data in PEV...
  ⚠ CONTRADICTION: Commodity Procurement provides personal data in VLOGP...
```

Problèmes :
- Les tensions sont des **claims bruts** sans contexte (quel document ? quelle version ?)
- Le LLM ne comprend pas la **structure** de la contradiction (claim A du doc X vs claim B du doc Y)
- Le guard-rail de 600 chars **tronque** les tensions les plus informatives

---

## 5. Ce qui manque dans OSMOSIS

### 5.1 Injection structurée des contradictions

Au lieu d'un texte libre `"⚠ CONTRADICTION: ..."`, injecter un **bloc structuré** :

```
## ⚠ Divergences documentaires détectées

### Divergence 1 : Stockage des données personnelles Commodity
- **Position A** (Security Guide 2022) : données dans PeriodEnd Valuation (PEV)
- **Position B** (Security Guide 2023) : données dans VLOGP et BRFplus Decision Tables
- **Impact** : vérifier quelle version s'applique à votre release

INSTRUCTION : Vous DEVEZ mentionner cette divergence dans votre réponse.
```

### 5.2 Template de réponse avec section contradictions obligatoire

Quand le signal tension est actif, le prompt de synthèse devrait imposer un **template** :

```
Répondez en suivant cette structure :
1. Réponse principale (basée sur les sources)
2. ⚠ Points de vigilance (divergences entre documents)
3. Sources
```

Forcer la section "Points de vigilance" quand des tensions sont détectées.

### 5.3 Retrieval ciblé par document en tension (Phase C)

Quand le KG détecte CONTRADICTS entre doc A et doc B :
1. Identifier les chunk_ids des deux claims en contradiction
2. Si ces chunks ne sont pas dans le top 10 RAG, les **injecter** comme sources supplémentaires
3. Pas en remplacement des chunks RAG — en **complément** (invariant respecté)

Actuellement, `fetch_missing_tension_docs` fait une recherche vectorielle filtrée par doc_id. Mais la recherche retourne des chunks vaguement similaires, pas les chunks qui contiennent le fait contradictoire. L'amélioration serait d'utiliser les **chunk_ids du bridge** pour récupérer exactement les bons chunks.

### 5.4 Seuil de guard-rail KG trop restrictif

Le guard-rail de 600 chars / ~150 tokens pour le bloc KG est issu du Sprint 0 (quand le KG polluait les réponses). Avec le bloc séparé et le prompt amélioré, ce seuil peut être relevé à **1000-1200 chars** pour les cas où des tensions sont détectées (pas pour le silence).

### 5.5 Métriques de différenciation dans le benchmark

Le benchmark actuel ne mesure pas :
- **Proactive contradiction detection** : le système signale une tension que l'utilisateur n'a pas demandée
- **Cross-doc reasoning quality** : la réponse utilise des faits de 3+ documents de manière cohérente
- **Version-awareness** : la réponse distingue les versions quand c'est pertinent

Ces métriques sont implémentées dans T5 (rule-based judge) mais les scores montrent 0% de proactive detection — ce qui confirme que c'est le chantier prioritaire.

---

## 6. Résumé des priorités

| Priorité | Action | Impact attendu | Effort |
|----------|--------|---------------|--------|
| **P0** | Injection structurée des contradictions (pas du texte libre) | Proactive detection 0% → 50%+ | 1-2j |
| **P1** | Template réponse avec section "divergences" obligatoire | Tension mentioned 16% → 60%+ | 0.5j |
| **P2** | Retrieval ciblé via chunk_ids du bridge (pas vector search) | Both sides 36% → 60%+ | 1j |
| **P3** | Relever le guard-rail KG à 1200 chars quand tension active | Meilleur contexte pour le LLM | 0.5j |
| **P4** | Métriques T5 comme KPI principal (pas T1/T4) | Focus sur la différenciation | 0.5j |

### Conclusion

Le KG fonctionne parfaitement pour la **détection**. Le gap est dans le **dernier maillon** : transformer une tension détectée en information visible dans la réponse. C'est un problème de **prompt engineering** et de **format d'injection**, pas d'architecture KG.

La bonne nouvelle : les données sont là (20 CONTRADICTS, 8 tensions détectées par question, signal-driven actif). Il reste à les **surfacer** efficacement dans la synthèse.
