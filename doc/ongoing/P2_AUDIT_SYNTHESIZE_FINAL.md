# Audit Synthesize étendu — Distribution scénarios complète (Option ε)

> Date : 2026-05-24
> Audit sur 18 questions (10 factual + 8 multi_hop) du bench Config C avec score<1.0
> Données : `data/benchmark/p2_synthesize_audit_20260524.json`

---

## Distribution des scénarios

| Type | Scénario | Count | % |
|---|---|---|---|
| **factual** (10q) | | | |
| | A1 Synthesize bug (claim ∈ CE top-5 mais pas cité) | 3 | 17% |
| | A2 sub_goal query dilution (claim ∈ RRF top-50 mais pas CE top-5) | 2 | 11% |
| | B retrieval miss / extraction gap | 3 | 17% |
| | CITED (judge ou Synthesize bug subtil) | 2 | 11% |
| **multi_hop** (8q) | | | |
| | A2 sub_goal query dilution | 3 | 17% |
| | B retrieval miss / extraction gap | **5** | **28%** |
| **TOTAUX** | | | |
| | **B (extraction manquante)** | **8** | **44%** |
| | **A2 (query dilution)** | **5** | **28%** |
| | **A1 (Synthesize bug)** | **3** | **17%** |
| | **CITED (bug subtil)** | **2** | **11%** |

## Findings majeurs

### 1. Retrieval miss / extraction gap = 44% des échecs

C'est le scénario dominant. **Multi_hop est massivement touché** : 5/8 cas (62%) cherchent des claims absents du KG. Ces questions interrogent des concepts qui n'ont pas été extraits sous forme atomique exploitable.

Exemples :
- HUM_0044 "RFC destinations et configuration réseau inter-systèmes" : 3/3 candidats non trouvés
- HUM_0036 "Maintenance Planner" : 3/3 candidats non trouvés
- HUM_0004 "SAP Fiori dans le contexte des..." : 3/3 candidats non trouvés

→ **Phase 1 (hyper-relational extraction + ré-ingestion) est indispensable** pour adresser ces cas.

### 2. Query dilution sub_goal = 28% des échecs

Les claims pertinents EXISTENT dans le KG ET dans le top-50 RRF, mais le CE rerank les perd à cause du query construit par sub_goal trop générique.

→ **Test rapide en cours** : Config C2 avec `V6_HYBRID_QUERY_MODE=question` (en background).
→ **Fix potentiel** : 0 dev, juste toggle env si validé.

### 3. Synthesize bug = 17% des échecs

Le pipeline a les bons claims en CE top-5 mais Synthesize cite d'autres claims dans sa réponse.

Cas typique HUM_0028 :
- Question : "Quelle transaction WWI Monitor SAP EHS ?"
- CE top-5 contient `claim_5bebb77e` (CG5Z) — bon claim
- Synthesize cite `claim_2291e41f` + `claim_813cede1` (CGSADM, WWI Integration + Expert)
- Réponse : "transaction CGSADM" (FAUX)

→ Cause potentielle : Synthesize prompt sélectionne mal entre claims similaires (WWI Monitor vs WWI Integration). 

→ **Fix possible** : améliorer prompt Synthesize pour mieux distinguer subject_canonical entre claims similaires. 1-2j.

### 4. Cas CITED avec score<1.0 = 11%

Synthesize utilise le bon claim, mais le judge note < 1.0. Causes possibles :
- Réponse partielle (ne couvre pas tous les aspects de la question)
- Reformulation qui perd un détail clé
- Bug judge (mais P0.1 a normalisé)

→ Audit manuel des 2 cas requis. 0.5j.

## Math impact attendu par fix

Sur 25 questions factual + multi_hop (15 + 10) :

| Fix | Cas adressés | Gain local (sur 25q) | Gain global (sur 50q) |
|---|---|---|---|
| Mode `query=question` (Config C2) | 5 (A2) | +0.20pp | +0.10pp |
| Fix Synthesize bug (A1) | 3 | +0.12pp | +0.06pp |
| Phase 1 extraction (B) | 8 | +0.32pp | +0.16pp |
| Audit cas CITED | 2 | +0.04pp (×0.5) | +0.02pp |
| **Total cumulé estimé** | 18/18 | **+0.68pp local** | **+0.34pp global** |

**Math finale** :
- C1 actuel Config C : 0.480
- **+ Mode query=question** : ~0.58 (si C2 confirme)
- **+ Fix Synthesize bug** : ~0.64
- **+ Phase 0 R10 (cas CITED + gold obsolète)** : ~0.66
- **+ Phase 3 tools** : ~0.71-0.76 (gain spécifique multi_hop/comparison)
- **+ Phase 1 extraction** : ~0.80-0.85 (couvre les 8 cas B)

**Sans Phase 1, plafond probable C1 ~0.65-0.70**. Gate 0.75 inatteignable.

## Séquence d'exécution recommandée (révisée)

```
[En cours]  Bench Config C2 (V6_HYBRID_QUERY_MODE=question)
            → si gain ≥+0.05pp : adopter mode=question par défaut (0j dev)

[Étape 1]   Fix Synthesize bug A1 (1-2j)
            → audit prompt Synthesize sur HUM_0028, HUM_0003, HUM_0020
            → identifier pourquoi Synthesize choisit mauvais claims similaires
            → fix prompt + bench

[Étape 2]   Phase 0 R10 ciblée (1-2j)
            → rebuild 4 questions problématiques (2 CITED + 2 gold obsolète)
            → bench validation

CHECKPOINT  C1 attendu ~0.60-0.65 après étapes 1+2

[Étape 3]   Phase 3 tools compare_by_axis + procedure_chain (4-6j)
            → adresse comparison + multi_hop architecturalement
            → bench : viser C1 ~0.68-0.72

CHECKPOINT  C1 attendu ~0.68-0.72

[Étape 4]   Phase 1 hyper-relational extraction + ré-ingestion (13-18j + EC2 Burst)
            → couvre les 8 cas B (44% des échecs)
            → bench : viser C1 ≥ 0.75 (gate Phase A)
            → CRITIQUE pour atteindre la gate
```

## Risques et incertitudes

### Risque 1 : Mode `query=question` régresse sur d'autres types
Cohérent avec ce qu'on a vu en bench A4.15 : la question brute peut diluer le RRF sur les questions sémantiques pures. À mesurer A/B.

### Risque 2 : Phase 1 ré-ingestion casse des choses qui marchent
38 docs à ré-extraire. Drift possible. Mitigation : snapshot Neo4j + tenant isolé pour validation.

### Risque 3 : Coût EC2 Burst Qwen2.5-14B AWQ
Phase 1 ré-ingestion nécessite EC2 (crédit DeepInfra insuffisant selon Fred). Coût + complexité opérationnelle.

### Risque 4 : Phase 3 plafonne sans Phase 1
Si les claims procéduraux n'existent pas en KG (gap B), les tools `procedure_chain` n'auront rien à exploiter. **Phase 3 nécessite Phase 1 pour donner son plein potentiel sur multi_hop**.

Implication : peut-être faire Phase 1 AVANT Phase 3 ? Ré-évaluer après étapes 1+2.

## Décision en attente Fred

1. **Confirmer séquence** : ε → R10 → Phase 3 → Phase 1 ?
2. **OU prioriser Phase 1** (couvre 44% des échecs) avant Phase 3 ?
3. **Contrainte calendrier Viseo** : si deadline serrée, options de dernier recours (relaxer gate, frontier model temporaire, top-100 RRF)

---

*Document produit en autonomie 24/05/2026. Audit complet 18 questions factual+multi_hop avec score<1.0.*
*Données brutes : `data/benchmark/p2_synthesize_audit_20260524.json`*
*Référence recall audit : `data/benchmark/p2_recall_audit_20260524.json`*
