# Audit Option ε — Synthesize rate les bons claims malgré CE top-1

> Date : 2026-05-24
> Référence : `DECISION_MATINALE_P2_4.md` Option ε, post-recall audit `p2_recall_audit_20260524.json`

## Constat des 3 cas paradoxaux

### Cas 1 — HUM_0028 (WWI Monitor / CG5Z)

| | Valeur |
|---|---|
| Question | "Quelle transaction est utilisee pour le WWI Monitor dans SAP EHS ?" |
| Ground truth | "La transaction CG5Z est utilisee pour le WWI Monitor" |
| **Recall audit (query=question brute)** | `claim_5bebb77e` (CG5Z) en **BM25/Vec/RRF/CE rank 1** ✅ |
| **Pipeline réel Synthesize output** | "La transaction utilisée [...] est **CGSADM** [claim_id=claim_2291e41f][claim_id=claim_813cede1]" ❌ |
| Judge | 0.0 — "different transaction code (CG5Z vs CGSADM)" |
| Verdict Evaluate | **CORRECT** (full coverage from tool results) |

Le pipeline a choisi `claim_2291e41f` ("Windows Wordprocessor Integration uses Transaction CGSADM") **au lieu de** `claim_5bebb77e` ("WWI Monitor (transaction CG5Z) monitors the report generation").

### Cas 2 — HUM_0003 (Client 066)

| | Valeur |
|---|---|
| Question | "Quel client SAP doit etre supprime avant la conversion vers S/4HANA ?" |
| Ground truth | "Le client 066 (Early Watch client) doit etre supprime" |
| **Recall audit (query=question brute)** | `claim_47c98a4f` ("Client 066 is not used in SAP S/4HANA") en CE top-1 |
| **Pipeline réel Synthesize output** | "**Aucune information spécifique** [...] n'a été trouvée" + cite des claims sur S/4HANA Cloud Public Edition génériques |
| Judge | 0.0 — "candidate claims no specific information was found but reference explicitly states" |
| Mode | ABSTENTION |

Le pipeline a ABSTAIN alors que `claim_47c98a4f` (Client 066) était trouvable. Les claims cités sont génériques (S/4HANA Cloud) — Client 066 n'apparaît pas du tout.

### Cas 3 — HUM_0020 (E-Recruiting authorization)

| | Valeur |
|---|---|
| Question | "Quels objets d'autorisation sont necessaires pour le scenario E-Recruiting Manager ?" |
| Ground truth | "P_RCF_POOL, P_RCF_STAT, P_RCF_ACT, CA_POWL" |
| **Recall audit (query=question brute)** | `claim_b90a0209` ("authorization object specifies which SAP E-Recruiting application") en CE top-4. `claim_b486e379` en RRF top-5 lost by CE. `claim_a185c575` ("SAP _ERC_REC_ADMIN_CI_4") en BM25 top-46. |
| **Pipeline réel Synthesize output** | "rôles standard et objets d'autorisation pertinents" (générique, aucun code P_RCF_*) |
| Judge | 0.0 — "does not specify the required authorization objects" |
| Mode | REASONED |

Le pipeline a vu des claims trop génériques. Les codes P_RCF_POOL / P_RCF_STAT / etc. ne sont pas cités.

## Cause root identifiée : query_text différent entre audit et pipeline

Le code `Execute._build_query_text_for_call` (`execute.py` ligne 297-334) lit l'env var `V6_HYBRID_QUERY_MODE` :
- **Défaut "sub_goal"** : query Lucene = `subject_canonical + predicate_hint + object_hint` du sub_goal Parse
- "question" : query Lucene = question brute utilisateur

**Mon recall audit utilisait la question brute** → trouve les bons claims en top-1/top-5.
**Le pipeline réel utilise le sub_goal construit par Parse** → trouve probablement d'autres claims (plus génériques sur "WWI Monitor" ou "client SAP" ou "objets autorisation").

Sans le détail du `ParseOutput` réel dans `iterations_trace`, on ne peut pas voir ce que Parse a extrait. Mais l'hypothèse est forte : **Parse produit un `subject_canonical` trop générique qui dilue le retrieval RRF**.

Exemples plausibles de query Lucene pipeline :
- HUM_0028 : `subject_canonical="WWI Monitor"` (sans "transaction" ni "EHS") + `predicate_hint=USED_FOR` ou `RELATED_TO` → query Lucene `WWI Monitor used for` matche WWI Generation Servers, Windows Wordprocessor Integration, etc.
- HUM_0003 : `subject_canonical="SAP client"` (générique) + `predicate_hint=DELETED_BEFORE_CONVERSION` → matche tout claim "client" générique
- HUM_0020 : `subject_canonical="E-Recruiting authorization"` (combiné, trop général)

## Test proposé : Bench Config C2 (V6_HYBRID_QUERY_MODE=question)

Lancer le bench Config C complet avec **V6_HYBRID_QUERY_MODE=question** (utiliser la question brute au lieu du sub_goal pour le query Lucene RRF).

**Toggle** :
```bash
docker exec \
  -e V6_HYBRID_RETRIEVAL=rrf \
  -e V6_HYBRID_QUERY_MODE=question \
  -e V6_CROSS_ENCODER_RERANK=1 \
  -e V6_PARSE_LLM_DEEPSEEK=1 \
  knowbase-app sh -c 'cd /app && python -u scripts/bench_a38_runtime_v6.py'
```

**Hypothèses validables** :
- Si C1 factual remonte significativement (vers 0.50-0.55) → confirme cause root
- Si C1 factual reste ~0.367 → autre cause (peut-être Synthesize fail à utiliser le bon claim même quand il est en top-5)

**Effort** : 0.5j (juste un toggle env + bench ~1h-3h selon rate limit DeepInfra)

**Risque** : peut dégrader multi_hop/comparison si la question brute est trop générique pour ces types. Mesure A/B obligatoire.

## Alternative : fix Parse pour produire des sub_goals plus précis

Si test C2 montre que le mode "question" résout factual, on a 2 choix :
1. **Adopter `V6_HYBRID_QUERY_MODE=question` par défaut** (changement env simple)
2. **Améliorer Parse** pour produire un `subject_canonical` plus précis qui ne dilue pas le retrieval

Le choix 1 est plus rapide. Le choix 2 est plus fondamental (Parse Phase B).

## Synthèse des findings P2 (post Option ε)

Sur les 9 questions factual score=0.0 :
- **3 cas Synthesize bug** (HUM_0028, HUM_0003, HUM_0020) — probable cause : query_text construit par sub_goal trop générique → retrieval ramène mauvais top-5 → Synthesize cite mauvais claims
- **3 cas extraction manquante** (HUM_0014, HUM_0080, PPTX_0020) — claims absents du KG → Phase 1 ré-ingestion
- **2 cas gold-set obsolète** (HUM_0054, HUM_0033) — KG a OM17, gold attend OM13 → Phase 0 R10
- **1 cas RRF dégradé par CE** (HUM_0017) — score fusion utile (1/9 marginal)

**Reco priorisée** :
1. **Bench C2 V6_HYBRID_QUERY_MODE=question** (0.5j) — test rapide validation hypothèse
2. **Si C2 valide** : adopter par défaut → adresse 3/9 cas Synthesize bug
3. **Phase 0 R10 gold-set rebuild** (2-3j) — adresse 2/9 cas
4. **Phase 1 hyper-relational + ré-ingestion** (13-18j) — adresse 3/9 cas extraction
5. **Score fusion ou routing** (1-2j) — marginal 1/9 cas

---

*Document produit 24/05/2026 dans le cadre Option ε post-recall-audit P2.4-PRE. Référence audit : `data/benchmark/p2_recall_audit_20260524.json`. Référence bench Config C : `data/benchmark/a38_runtime_v6/run_20260524_084344.json`.*
