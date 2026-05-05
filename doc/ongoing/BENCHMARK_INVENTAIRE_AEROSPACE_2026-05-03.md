# Inventaire benchmark — corpus aerospace V2

> **Statut** : CH-30.0 livrable (2026-05-03). Source de vérité pour la génération des questions T1/T2/T5/T6/T7.
> **KG** : 17 docs, 40 196 claims, 4 LIFECYCLE_RELATION (Doc→Doc), 4 328 LOGICAL_RELATION (Claim→Claim).

---

## 1. Corpus (17 docs ingérés)

### A. CS-25 Large Aeroplanes — EASA (11 docs, 30 124 claims)

#### Amendments (7 docs, 28 568 claims)

| doc_id | publication | claims | lifecycle | titre |
|---|---|---|---|---|
| `cs25_amdt_22_8e69026c` | 2018-11-05 | 2 646 | ACTIVE | CS-25 Amendment 22 (ED Decision 2018/010/R) |
| `cs25_amdt_23_0869bab2` | 2019-07-15 | 4 933 | ACTIVE | CS-25 Amendment 23 |
| `cs25_amdt_24_86b11545` | 2020-01-10 | 3 695 | ACTIVE | CS-25 Amendment 24 |
| `cs25_amdt_25_a41bdc85` | 2020-06-24 | 3 047 | ACTIVE | CS-25 Amendment 25 |
| `cs25_amdt_26_6450b31e` | 2020-12-15 | 4 353 | ACTIVE | CS-25 Amendment 26 |
| `cs25_amdt_27_992260a7` | 2021-11-24 | 4 760 | ACTIVE | CS-25 Amendment 27 |
| `cs25_amdt_28_32f1a9ac` | **2023-12-15** | 5 070 | ACTIVE | **CS-25 Amendment 28 (ED Decision 2023/021/R)** ← latest |

#### Change documents (4 docs, 1 556 claims) — supplémentaires (NPAs / ED Decisions accompagnant les amendments)

| doc_id | publication | claims | sujet |
|---|---|---|---|
| `cs25_change_amdt_23_2e2b5e95` | 2019 | 69 | Airplane Safety Regulations |
| `cs25_change_amdt_24_cdd7474b` | 2020 | 296 | Aeroelastic Stability Requirements |
| `cs25_change_amdt_26_28f2c375` | 2021 | 873 | Amendment to CS-25 |
| `cs25_change_amdt_28_69cf602f` | 2023 | 318 | Aviation Safety Regulations |

### B. EU Dual-Use Export Controls (6 docs, 10 136 claims)

| doc_id | publication | claims | lifecycle | titre |
|---|---|---|---|---|
| `dualuse_reg_428_2009_original_372b7ac3` | 2009-05-05 | 1 818 | **DEPRECATED** | Council Regulation (EC) No 428/2009 (repealed) |
| `dualuse_reg_2021_821_original_65eef5dc` | **2021-06-11** | 2 658 | ACTIVE | **Regulation (EU) 2021/821** (master, repeals 428/2009) |
| `dualuse_del_2023_66_cdc2b691` | 2022-10-21 | 1 875 | ACTIVE | Commission Delegated Regulation (EU) 2023/66 — Annex I update |
| `dualuse_del_2023_996_3616a044` | 2023-02-23 | 1 773 | ACTIVE | Commission Delegated Regulation (EU) 2023/996 — Annex I update |
| `dualuse_del_2024_2025_908a03cf` | 2024-07-15 | 177 | ACTIVE | Commission Delegated Regulation (EU) 2024/2025 (titre KG erroné = "Electronic Freight…", à valider) |
| `dualuse_del_2024_2547_cb08f84b` | 2024-09-05 | 1 835 | ACTIVE | Commission Delegated Regulation (EU) 2024/2547 — Annex I update |

---

## 2. Lifecycle relations (4 edges, Doc→Doc)

| kind | source → target | conf | evidence_quote |
|---|---|---|---|
| SUPERSEDES | `dualuse_reg_2021_821` → `dualuse_reg_428_2009` | 0.98 | *"Regulation (EC) No 428/2009 is repealed."* |
| EVOLVES_FROM | `dualuse_del_2023_66` → `dualuse_reg_2021_821` | 0.98 | *"Annex I to Regulation (EU) 2021/821 is replaced by the text in the Annex to this Regulation."* |
| EVOLVES_FROM | `dualuse_del_2023_996` → `dualuse_reg_2021_821` | 0.98 | (idem) |
| EVOLVES_FROM | `dualuse_del_2024_2547` → `dualuse_reg_2021_821` | 0.98 | (idem) |

⚠️ **Note** : `dualuse_del_2024_2025` n'a PAS de LIFECYCLE_RELATION détectée (titre KG suspect — à investiguer pour T6 unanswerable).

---

## 3. Vrais conflits (3 CONFLICT, conf=1.0, scope aligné)

### CONFLICT-01 : Glass impact energy ⚠️ **conflict majeur, valeur numérique**
- **claim_a** (`cs25_amdt_28_32f1a9ac`) : *"The large glass item should be subjected to a single impact... The impact energy should be **21 J**, caused by a 51mm diameter ball or, alternatively, by a 40-mm diameter ball..."*
- **claim_b** (`cs25_amdt_26_6450b31e`) : *"...The impact energy should be **3.5 J**, caused by a 51mm diameter ball..."*
- **Type** : évolution réglementaire (amdt 28 plus exigeant) — actuellement classé CONFLICT mais **devrait être SUPERSEDES** en V2

### CONFLICT-02 : CS 25.1309(c) flight crew alerting
- **claim_a** (`cs25_amdt_27_992260a7`) : version "designed to minimise flight crew errors..."
- **claim_b** (`cs25_change_amdt_24_cdd7474b`) : version étendue avec "warning indication must be provided if immediate corrective action is required"
- **Type** : nuance / précision (texte enrichi) — borderline conflict

### CONFLICT-03 : Service history (paraphrase quasi-verbatim)
- **claim_a** (`cs25_amdt_23_0869bab2`) ≈ **claim_b** (`cs25_amdt_24_86b11545`)
- **Type** : faux positif probable (texte ~identique avec nuances mineures de typographie)

---

## 4. Autres LOGICAL_RELATION exploitables

| type | n | usage bench |
|---|---|---|
| EQUIVALENT | 4 319 | T5 cross-doc (mêmes claims réaffirmés entre amendments) |
| CONFLICT | 3-4 | T2 contradictions |
| DISJOINT | 3 | T2 (non-overlapping scope) |
| SUBSET | 1 | T7 anchor scope hierarchy |
| DEFINITION_OF | 1 | T1 provenance (definitions) |

---

## 5. Faits clés extractibles par doc (samples KG)

### CS-25 Amendment 28 (latest)
- Annex to ED Decision 2023/021/R
- CS 25.629(d), CS 25.671, CS 25.672 amended (NPA 2014-02)
- CS 25.705 created (NPA 2018-12)
- CS 25.788 created (NPA 2015-19)
- CS 25.734 created (NPA 2013-02)
- CS 25.795 amended (NPA 2015-11)

### CS-25 Amendment 22 (oldest)
- Title of Appendix K amended (NPA 11/2004)
- CS 25.21 amended (NPA 2008-05)
- ED Decision 2018/010/R

### Reg (EU) 2021/821 — master dual-use
- "An authorisation shall be required for the export of dual-use items listed in Annex I."
- Notion : `large project authorisation`, `global export authorisation`
- "Authorisations issued or established under this Regulation shall be valid throughout the customs territory of the Union."
- "Regulation (EC) No 428/2009 is repealed."
- Personal data → Reg (EU) 2016/679 + 2018/1725
- 10-day extension max 30 working days

### Del 2024/2547 (latest dual-use)
- "amending Regulation (EU) 2021/821... as regards the list of dual-use items"
- Annex I replacement (Wassenaar Arrangement, MTCR, NSG updates)
- Defines "Intrusion software", "Network access controller", "Cryptographic activation"

---

## 6. Format JSON cible (compatible runner V2)

Le runner `benchmark/runners/run_osmosis_v2.py` lit un **JSON array flat** (pas de `metadata + questions` wrapper).

```json
[
  {
    "id": "T1_AERO_0001",
    "task": "T1_provenance",
    "question": "Quel règlement EU établit le régime d'exports d'items à double usage ?",
    "ground_truth_doc_id": "dualuse_reg_2021_821_original_65eef5dc",
    "ground_truth_answer": "Regulation (EU) 2021/821 du Parlement européen et du Conseil établit le régime de l'Union pour le contrôle des exports, du courtage, de l'assistance technique, du transit et du transfert de produits à double usage.",
    "verbatim_quote": "Regulation (EU) 2021/821 establishes a Union regime for the control of exports...",
    "category": "anchor_master_dualuse"
  }
]
```

**Champs** :
- `id` : `T<N>_AERO_<NNNN>` (ex: `T1_AERO_0001`)
- `task` : `T1_provenance` | `T2_contradictions` | `T5_cross_doc` | `T6_robustness` | `T7_v2_anchor`
- `question` : texte naturel (FR ou EN selon le doc cible)
- `ground_truth_doc_id` : doc_id principal (null pour T5 cross-doc / T6 unanswerable)
- `ground_truth_answer` : réponse de référence
- `verbatim_quote` (T1, T7) : citation exacte qui doit apparaître pour validation provenance
- `expected_doc_ids` (T5) : liste des docs attendus pour cross-doc chains
- `expected_behavior` (T6) : `reject_premise` | `state_unanswerable` | `multi_hop_synthesis` | etc.
- `expected_lifecycle_kind` (T7) : `SUPERSEDES` | `EVOLVES_FROM` | `REAFFIRMS` | `null`
- `category` : sous-type pour analyse (ex: `anchor_master_dualuse`, `lifecycle_supersedes`, `false_premise_numeric`)

---

## 7. Stratégie de génération (250-300 questions)

| Task | Volume cible | Sources | Effort |
|---|---|---|---|
| T1 Provenance | 50 | 2-3 q/doc, claims évidence-locked | 1j |
| T2 Contradictions | 40 | 3-4 vrais CONFLICT + tensions inventées (CS-25 vs dual-use, hypothétiques) | 0.75j |
| T5 Cross-doc | 30 | Chains 2-3 docs (évolutions intra-CS-25, intra-dual-use, cross-domain) | 0.75j |
| T6 Robustness | 120 | 10 catégories × 12 q (false_premise, unanswerable, temporal, causal, hypothetical, negation, synthesis_large, multi_hop, set_list, conditional) | 1.5j |
| T7 V2 anchor | 50 | 4 LIFECYCLE_RELATION ×~3q chacune + applicability + scope hierarchy + lifecycle filtering | 1j |
| **Total** | **290** | — | **~5j** |

---

## 8. Décisions ouvertes

1. **Langue** : FR uniquement / EN uniquement / mix selon doc (CS-25 EN, dual-use FR↔EN) ?
   - Recommandation : **mix** comme aujourd'hui, le KG contient les passages en EN (verbatim) mais OSMOSIS répond dans la langue de la question. Permet de tester la robustesse multilingue.

2. **Distribution T6 par catégorie** :
   - false_premise: 12, unanswerable: 12, temporal: 12, causal_why: 12, hypothetical: 10, negation: 10, synthesis_large: 12, multi_hop: 12, set_list: 14, conditional: 14 = 120

3. **Périmètre T7** :
   - 12 lifecycle queries (3-4 par LIFECYCLE_RELATION)
   - 12 applicability ("règles applicables à... [date / scope]")
   - 10 anchor scope hierarchy (subset/superset)
   - 8 lifecycle filtering (ACTIVE vs DEPRECATED)
   - 8 distinction CONFLICT vs LIFECYCLE (vrais conflits vs évolutions)

4. **Backup legacy** : déplacer `*_SAP_BACKUP.json` et `reg_*.json` vers `benchmark/questions/_legacy/` avant d'introduire les nouveaux fichiers ? **Recommandation : oui**, garde la trace.

---

## 9. Fichiers cibles (à créer)

```
benchmark/questions/
├── _legacy/                         # ancien (SAP + REG)
│   ├── task1_provenance_human_SAP.json
│   ├── reg_task1_provenance_human.json
│   └── ...
├── aero_t1_provenance.json          # 50 questions
├── aero_t2_contradictions.json      # 40 questions
├── aero_t5_cross_doc.json           # 30 questions
├── aero_t6_robustness.json          # 120 questions
└── aero_t7_v2_anchor.json           # 50 questions (NOUVEAU)
```
