# Quality Gates — Analyse Baseline & Résultats A/B

**Date** : 2026-02-17 (baseline) / 2026-02-18 (résultats)
**Modèle** : Qwen3-14B-AWQ sur vLLM (identique baseline et test)
**Objectif** : Capturer l'état des claims AVANT activation des quality gates V1.3
pour pouvoir comparer après ré-import.

---

## 3 documents sélectionnés pour le test A/B

| # | Doc ID | Nom court | Total claims | Raison de sélection |
|---|--------|-----------|-------------|---------------------|
| 1 | `021_SAP_S4HANA_2023_Admin_Guide_Implementation_Best_Practices_08ad145e` | Admin Guide 2023 | 74 | Petit doc, 79% orphelins, 3 tautologies, représentatif |
| 2 | `025_SAP_S4HANA_2023_Feature_Scope_Description_bf3d5700` | Feature Scope 2023 | 3473 | Plus gros doc, 585 claims longues, 28 anaphores, 705 orphelins |
| 3 | `028_SAP_S4HANA_2022_Security_Guide_44f7ec32` | Security Guide 2022 | 1490 | 11 tautologies exactes (pire du corpus), 179 orphelins |

---

## Métriques Baseline par document

### Doc 021 — Admin Guide 2023 (74 claims)

| Métrique | Valeur | % |
|----------|--------|---|
| Total claims | 74 | 100% |
| Avec structured_form | 57 | 77.0% |
| Orphelins (0 entities) | 57 | 77.0% |
| Claims longues (>160 chars) | 3 | 4.1% |
| Claims courtes (<30 chars) | 1 | 1.4% |
| Anaphores (It/This/These/They) | 0 | 0% |
| Tautologies exactes (S=O) | 3 | 4.1% |

**Échantillons tautologiques :**
1. `claim_22f0cb642764` : "The SAP S/4HANA Cloud Implementation Guide describes procedures for adapting SAP Best Practices solutions for the private edition of SAP S/4HANA Cloud to the company's needs." → S=O="SAP S/4HANA Cloud Private Edition"
2. `claim_42a58cf6ce2a` : "SAP GUI is compatible with SAP GUI" → S=O="SAP GUI"
3. `claim_0f629ddea7cb` : "S/4HANA Cloud Public Edition is based on S/4HANA Cloud Public Edition" → S=O="SAP S/4HANA Cloud"

**Échantillons orphelins (sans entité liée) :**
- "SAP GUI is compatible with SAP GUI"
- "SAP S/4HANA Cloud Private Edition 2023 uses SAP Best Practices."
- "SAP S/4HANA Cloud Private Edition 2023 uses SAP Best Practices" (doublon !)
- "SAP S/4HANA Cloud requires the use of SAP S/4HANA Cloud Public Edition"
- "S/4HANA Cloud 2302" (heading-like, <30 chars)
- "SAP S/4HANA Cloud Public Edition" (heading-like, fragment)
- "Activating multiple countries in the same client" (heading-like)

---

### Doc 025 — Feature Scope Description 2023 (3473 claims)

| Métrique | Valeur | % |
|----------|--------|---|
| Total claims | 3473 | 100% |
| Avec structured_form | 1637 | 47.1% |
| Orphelins (0 entities) | 705 | 20.3% |
| Claims longues (>160 chars) | 585 | 16.8% |
| Claims très longues (>300 chars) | 7 | 0.2% |
| Claims courtes (<30 chars) | 0 | 0% |
| Anaphores (It/This/These/They) | 28 | 0.8% |
| Tautologies exactes (S=O) | 3 | 0.1% |

**Échantillons tautologiques :**
1. `claim_ef9f67b9c6dc` : "Delegated user administration enables delegated user administration" → S=O
2. `claim_1fbb692549d5` : "You can extend the area of validity of a BOM that you defined when you first created it." → S=O="BOM"
3. `claim_ee1feb606742` : "Billing plans enables definition of start and end dates for periodic billing plans" → S=O="Billing plans"

**Échantillons anaphores :**
- "This special procurement extension is primarily used by the airline industry..."
- "This helps indicate whether a team can be used for agent determination."
- "It also has the capability to stock and repair customer-owned parts..."
- "This re-usable component is based on the UploadSet control from the SAP UI5 foundation."
- "This data can be used for user specific ranking of search results..."

**Échantillons non-atomiques (>300 chars) :**
- `claim_bd560c4eb85d` (493 chars) : "Business objects for change records can be integrated from the process and discrete industries, such as materials, bill of materials, BOM items, documents, engineering bill of materials, manufacturing bill of materials, planning scopes, production orders, purchase orders, engineering snapshots, master recipes, inspection plans, recipes, specifications, label sets, order specific routings, planning routings, production routings, product structure variants, and shop floor routing templates."
- `claim_5e8e2d217a84` (418 chars) : "SAP S/4HANA 2023 provides KPIs that provide insight into purchase order value over time, future purchasing spend based on purchase requisitions..."
- `claim_ea86f3303765` (378 chars) : "SAP S/4HANA 2023 provides KPIs that provide real-time insight into areas of improvement..."

---

### Doc 028 — Security Guide 2022 (1490 claims)

| Métrique | Valeur | % |
|----------|--------|---|
| Total claims | 1490 | 100% |
| Avec structured_form | 912 | 61.2% |
| Orphelins (0 entities) | 179 | 12.0% |
| Claims longues (>160 chars) | 122 | 8.2% |
| Claims courtes (<30 chars) | 2 | 0.1% |
| Anaphores (It/This/These/They) | 15 | 1.0% |
| Tautologies exactes (S=O) | 11 | 0.7% |

**Échantillons tautologiques (11 — pire du corpus) :**
1. `claim_9acbb38ff18a` : "SAP S/4HANA 2022 is a version of SAP S/4HANA 2022" → S=O (idem)
2. `claim_f98bea650d81` : "SAP S/4HANA 2022 is a specific version of SAP S/4HANA 2022" → S=O (idem)
3. `claim_f7dc73d2122d` : "SAP S/4HANA 2022 uses SAP S/4HANA 2022" → fabrication pure
4. `claim_114b8eea9cb9` : "The Security Guide for SAP S/4HANA 2022 is based on the Security Guide for SAP S/4HANA 2022" → tautologie évidente
5. `claim_5c6b28376b0b` : "SAP S/4HANA 2022 uses the SAP BTP platform for integration with SAP SuccessFactors" → S=O="SAP S/4HANA 2022" (faux positif partiel — le texte est correct mais le S=O est mal extrait)
6. `claim_fdc272a1c37c` : "Blocking access to data in SAP S/4HANA 2023" → heading-like, S=O="SAP S/4HANA 2023"
7. `claim_783c5a2e5eda` : "Secure network communications can be protected using Secure Sockets Layer (SSL)..." → S=O="Secure network communication"
8. `claim_56fbc6cb207e` : "SAP S/4HANA 2022 uses the ABAP programming model..." → S=O="ABAP"
9. `claim_0582ed917a41` : "SAP S/4HANA 2022 is compatible with the Security Arrangements" → S=O="SAP S/4HANA"
10. `claim_0d8cac628c3c` : "The configuration of settings for the blocking of business partner master data is done via the SAP Fiori platform." → S=O="SAP Fiori"
11. `claim_c34d66584d71` : "SAP S/4HANA 2022 uses the Business Network" → S=O="SAP S/4HANA 2023" (doc 2022 mais S/O dit 2023 !)

---

## Résumé des défauts attendus à corriger par les quality gates

| Défaut | Doc 021 | Doc 025 | Doc 028 | Gate responsable |
|--------|---------|---------|---------|------------------|
| Tautologie (S=O exact) | 3 | 3 | 11 | `REJECT_TAUTOLOGY` (cos > 0.96) |
| Fabrication (cos<0.80) | ? | ? | ? | `REJECT_FABRICATION` |
| Gray zone (0.80-0.88) | ? | ? | ? | `REWRITE_EVIDENCE_LOCKED` |
| Non-atomique (>160 chars) | 3 | 585 | 122 | `SPLIT_ATOMICITY` |
| Anaphore | 0 | 28 | 15 | `RESOLVE_INDEPENDENCE` |
| SF désalignée | ? | ? | ? | `DISCARD_SF_MISALIGNED` |
| Heading/fragment | ~3 | ~0 | ~2 | Existant (quality_filters) |

**Note** : Les métriques "?" seront révélées par les quality gates embedding-based
lors du ré-import. Seules les tautologies exactes (S=O string match) sont mesurables
ici. Les tautologies sémantiques (cos > 0.96 mais pas string-equal) seront plus nombreuses.

---

## Résultats A/B — Doc 021 (2026-02-18)

**Conditions** : Même modèle Qwen3-14B-AWQ, même vLLM, même document source.
Seule différence : quality gates V1.3 activées.

### Pipeline — Flux de claims

```
Phase 1  : 6507 passages → 175 claims extraites
Phase 1.4: Verifiability gate
           → 43 rejetées (REJECT_FABRICATION, cos < 0.80)
           → 80 en gray zone [0.80, 0.88] → 35 réécrites, 45 ABSTAIN (non-claimables)
           → 87/175 conservées
Phase 1.5: Dedup → ~51 claims uniques
Phase 1.6: Quality filters existants (heading, too short, etc.)
Phase 1.6b-c: Gates déterministes + atomicité
           → 3 tautologies rejetées (REJECT_TAUTOLOGY, cos S=O > 0.96)
           → 0 template leak
           → 7 SF supprimées (DISCARD_SF_MISALIGNED, cos SF/text < 0.85)
           → 5 claims splittées → 17 sub-claims atomiques
           → 60 claims en sortie
Phase 2.6: Independence resolver
           → 5 claims envoyées (entity anchoring trigger)
           → 1 anaphore résolue, 4 skipped (UNCHANGED)
           → 60/60 conservées
TOTAL    : 60 claims persistées (vs 74 baseline)
```

### Comparaison directe

| Métrique | Baseline (sans QG) | Avec QG | Delta |
|----------|:------------------:|:-------:|:-----:|
| Claims extraites (Phase 1) | ~74* | 175 | — |
| **Claims persistées** | **74** | **60** | **-19%** |
| Tautologies (S=O exact) | 3 | **0** | -3 |
| Fabrications passées | ? (non mesuré) | **0** (43 rejetées) | — |
| Non-claimables (headings, nav) | ~3 visibles | **0** (45 filtrées) | — |
| Claims réécrites (evidence-locked) | 0 | 11 | +11 |
| SF supprimées (désalignées) | 0 | 7 | +7 |
| Claims splittées en atomiques | 0 | 5 → 17 | +12 net |
| Anaphores résolues | 0 | 1 | +1 |
| Avec structured_form | 57 (77%) | 27 (45%) | -30 |
| Claims >160 chars | 3 | 5 | +2 |
| Durée pipeline | ~15 min | ~18 min | +20% |

*\* Le baseline n'avait pas de gate verif → les 74 claims sont celles qui passaient les filtres existants (dedup + quality_filters). L'extraction Qwen3 produit ~175 claims brutes mais l'ancien pipeline n'en conservait que 74.*

### Distribution quality_status (Neo4j)

| quality_status | Count |
|:-:|:-:|
| NULL (PASS) | 41 |
| REWRITE_EVIDENCE_LOCKED | 11 |
| DISCARD_SF_MISALIGNED | 7 |
| RESOLVE_INDEPENDENCE | 1 |
| **Total persistées** | **60** |

Claims éliminées (non persistées) :
- REJECT_FABRICATION : 43
- BUCKET_NOT_CLAIMABLE : 45
- REJECT_TAUTOLOGY : 3
- **Total éliminées** : **91**

### Échantillons — Claims réécrites (evidence-locked)

Exemples de claims dont le texte a été reformulé à partir du verbatim uniquement :
- "SAP recommends using SAP Data Services to migrate data into an S/4HANA (on premise) system."
- "BC sets are attributable and reusable snapshots of customizing settings."
- "Decentralized EWM on an SAP S/4HANA stack is a deployment option of the EWM application on the SAP S/4HANA on-premise stack."

### Échantillons — Claims splittées (atomicité)

Claim parente `claim_db81fa0be094` (>160 chars, listait plusieurs apps) éclatée en 4 :
1. "Certain scope items enable the integration of remote applications into SAP S/4HANA Cloud Private Edition."
2. "SAP Cloud Platform is an example of a remote application that can be integrated."
3. "SAP Ariba is an example of a remote application that can be integrated."
4. "SAP SuccessFactors is an example of a remote application that can be integrated."

### Échantillons — Anaphore résolue

Claim originale (anaphorique) → résolue avec sujet explicite :
- "Activating additional Enterprise Extensions or Business Functions (in addition to the required business functions mentioned for SAP Best Practices deployment) before content activation can result in errors during SAP Best Practices content activation."

### Tautologies baseline — Vérification

| Tautologie baseline | Résultat |
|---------------------|----------|
| "SAP GUI is compatible with SAP GUI" | **Éliminée** (REJECT_TAUTOLOGY ou REJECT_FABRICATION) |
| "S/4HANA Cloud Public Edition is based on S/4HANA Cloud Public Edition" | **Éliminée** |
| "Implementation Guide describes procedures..." (S=O mal extrait) | **Conservée** (claim valide, S!=O sémantiquement) |

### Évaluation critères de succès

| Critère | Objectif | Résultat | Status |
|---------|----------|----------|:------:|
| Tautologies exactes | 0 | 0 | PASS |
| Faux positifs gates | <5% | 0% observé* | PASS |
| Temps pipeline | +10-30% | +20% (~3 min) | PASS |
| Anaphores réduites | >50% | 1 résolue / 1 détectée | PASS |

*\* Aucune claim légitime visiblement rejetée à tort dans les échantillons examinés.*

### Bug corrigé

Le LLM ajoutait un préfixe `"Resolved claim:"` dans la réponse d'indépendance.
Fix appliqué dans `independence_resolver.py` : nettoyage regex des préfixes LLM courants.

---

## Résultats A/B — Doc 025 (en attente)

*À compléter après ré-import.*

---

## Résultats A/B — Doc 028 (en attente)

*À compléter après ré-import.*

---

## Commandes pour le ré-import

```bash
# 1. Purger les 3 docs de Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (n) WHERE n.doc_id IN ['021_SAP_S4HANA_2023_Admin_Guide_Implementation_Best_Practices_08ad145e', '025_SAP_S4HANA_2023_Feature_Scope_Description_bf3d5700', '028_SAP_S4HANA_2022_Security_Guide_44f7ec32'] AND n.tenant_id = 'default' DETACH DELETE n"

# 2. Ré-importer (les .knowcache.json sont préservés)
# Copier les PDFs dans data/docs_in/ et laisser le worker traiter

# 3. Vérifier la distribution quality_status après import
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass \
  "MATCH (c:Claim {tenant_id: 'default'}) WHERE c.doc_id STARTS WITH '021' OR c.doc_id STARTS WITH '025' OR c.doc_id STARTS WITH '028' RETURN c.doc_id, c.quality_status, count(*) ORDER BY c.doc_id, count(*) DESC"
```

---

## Critères de succès post-import

1. **Tautologies exactes** : 0 (les 17 actuelles doivent être rejetées ou corrigées)
2. **Claims >300 chars** : 0 (splittées en atomiques)
3. **Anaphores** : réduites de >50% (résolues par entity anchoring)
4. **Faux positifs gates** : <5% des rejets doivent être des faux positifs
5. **Temps pipeline** : +10-30% (acceptable, budget LLM pour rewrite/split/resolve)
