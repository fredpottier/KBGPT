# Gold-set AÉRO (certification sièges / crashworthiness)

Jeu d'évaluation ancré sur le corpus sièges-avion réellement ingéré (tenant `default` :
FAA ACs, EASA NPA/ETSO, brevets, recherche side-facing). Schéma identique au gold-set a38
(`gold_set_a38_50q.json`) → directement consommable par `bench_a38_runtime_v6.py`.

## Fichiers
- `gold_set_aero_150q.json` — **bench complet** (148 q). Réduit la variabilité run-à-run
  observée sur le 50q SAP.
- `gold_set_aero_50q.json` — **évals régulières** rapides. Sous-ensemble stratifié DU 150q
  (seed fixe) → cohérence stricte.
- *(à venir)* `gold_set_aero_cp.json` — paires de conflit (métrique `conflict_exposure`),
  couplé à la matérialisation des arêtes cross-doc (les vraies contradictions n'émergent
  qu'une fois les arêtes `CONTRADICTS`/`SUPERSEDES` posées).

## Provenance & garde-fou anti-hallucination
Généré par `app/scripts/build_gold_set_aero.py` :
- `exact_identifiers`, `supporting_doc_ids` et la **réponse de référence** proviennent de
  claims RÉELS du KG. Le LLM ne fait que **formuler** une question naturelle dont la réponse
  est ce claim (il ne peut pas inventer d'identifiant).
- `false_premise` / `unanswerable` : gabarits hand-craftés autour d'entités réelles
  (prémisse fausse plausible : « AC 25.562-1C », « TSO-C127d », « 30g horizontal », « femur
  3000 lb » ; ou hors-périmètre : prix, délais, parts de marché).
- Validation `groundedness` : tous les `supporting_doc_ids` existent dans le KG.

Régénérer : `docker exec knowbase-app python scripts/build_gold_set_aero.py`
Re-nettoyer les identifiants seuls : `python scripts/patch_aero_ids.py`

## Distribution 150q
factual 45 · list 15 · lifecycle 20 · comparison 20 (FAA↔EASA) · multi_hop 13 ·
contextual 10 · false_premise 15 · unanswerable 10

## Limites connues (v1)
- Les **comparaisons FAA/EASA** reposent sur un appariement par mot-clé de concept
  (16g, HIC, side-facing…) — corrects mais parfois peu tranchants.
- multi_hop = 13 (limité par le nb de paires de claims co-document exploitables).
- Les 2 extraits réglementaires reconstruits par pypdf (CS-25/Part 25 sièges) ont produit
  0 claim (soft-hyphens) → la paire 25.562 *pure* nécessiterait des PDF natifs.

## Révision 2026-06-05 — mise à niveau post-ré-ingestion staged (P1.4-bis)

Le corpus aéro a été intégralement ré-ingéré avec le pipeline d'extraction staged
(24 docs, ~17k claims, dont 4 nouveaux docs : AC 25-17 (1991), AC 25.785-1A/1B,
ETSO-C39b). Audit du gold-set contre le nouveau KG (`audit_gold_set_vs_kg.py`) :
**133/148 OK**, 5 false_premise conservées (identifiants absents par design),
2 conservées (identifiant = nom de document, présent en métadonnées), 1 faux
positif d'audit.

**7 questions re-labellisées `answerable → unanswerable`** (champ `revision` sur
chaque question) : leur phrase source (références croisées : AC 21-46, § 121.583,
ARP6337, « 1957 », § 21.8, AC 21-34) existait dans l'extraction legacy mais a été
filtrée par les gates staged. L'abstention devient la réponse correcte — véridique
dans le corpus actuel, et ces questions testent désormais l'abstention calibrée.
IDs : AERO_FACT_0028, AERO_FACT_0040, AERO_LIFE_0004, AERO_LIFE_0012,
AERO_CONT_0001, AERO_CMP_0002, AERO_CMP_0020 (3 d'entre elles aussi dans le 50q).

## Révision 2026-06-05 (bis) — ré-ancrage sur le wording staged (triage des 56q faibles)

Le bench run_20260604_223733 (post-staged) a montré des chutes C1 dont une partie
venait du **désancrage du gold** (réponses rédigées sur le wording des claims
legacy). Triage complet des 56 questions answerable à juge ≤ 0.5, chaque cas
vérifié contre les claims staged (substring sur `Claim.text`) :

**11 re-labellisées `answerable → unanswerable`** (ancre factuelle disparue du
KG staged) : AERO_FACT_0014, AERO_MH_0007 (AS6316 §3), AERO_FACT_0026
(memorandum 25.785(c)(2)), AERO_FACT_0042, AERO_MH_0010 (PSAIR100-9/8/2003),
AERO_LIFE_0001 (heart path analysis), AERO_LIFE_0005 (Appendix J),
AERO_LIFE_0006, AERO_LIFE_0013 (5e(5) deleted/redesignated), AERO_LIFE_0008
(paragraph (c) deleted), AERO_LIST_0014 (wear and damage limits).

**8 ré-ancrées/reciblées** (claim staged verbatim vérifié) : AERO_LIFE_0003
(25.789→25.791), AERO_LIFE_0015 (slip resistant floors §25.793),
AERO_FACT_0037 (« third standard » → UL 1439 explicite), AERO_FACT_0023 +
AERO_FACT_0045 (désambiguïsation : question identique avec 2 golds différents),
AERO_LIST_0006/0008/0015 (le but de l'assessment a été perdu par la
décomposition staged → gold ré-ancré sur « require an assessment »).

**Conservées telles quelles (vrais échecs système, ancres présentes vérifiées)** :
AERO_FACT_0006/0019/0024, AERO_LIFE_0017, AERO_MH_0002/0003/0013,
AERO_CMP_0012/0013/0017, AERO_FP_0002/0008/0012, et tous les juges 0.5
« réponse plus large que l'ancre ».

**En attente de décision** : AERO_CMP_0003/0007/0011 — paires comparison dont UN
côté gold a disparu du staged ; question vague → ni relabel ni ré-ancrage propre.

⚠ **Perte de couverture staged documentée** : ~10 ancres factuelles présentes en
legacy ont été perdues par les gates staged (sélection ou décomposition), dont un
cas typique de troncature Stage B (claim_1d990a6c8867_a : « require an
assessment » sans le but de l'assessment). À traiter côté extraction (backlog).

## Révision 2026-06-05 (ter) — audit #450 (perte de couverture) + réparation des 3 comparisons

**Audit #450 — cause racine des ~10 ancres perdues** (passages sources retrouvés
dans `data/extraction_cache/`) :
1. **« Note: » factuelles jetées** (PSAIR100, wear-and-damage, Appendix J) : le juge
   de la selection gate les classe `doc_meta`/`reference` = déchet franc → le
   garde-fou identifiant est suspendu (`guard_suppressed`) → DROP.
2. **Déclarations de changement réglementaire jetées** (« Deletes paragraph
   5e(5)(d)… », « Redesignates… ») : classées méta-document alors que c'est la
   matière première lifecycle d'OSMOSIS. Le garde supersession ne couvrait que
   supersede/cancel/replace.
3. **Décomposition ampute la finalité** (« an assessment must be conducted to
   verify that structural integrity… » → « require an assessment ») : la
   subordonnée de but n'était pas protégée par le prompt Stage B.

**Fixes livrés (effectifs à la prochaine ingestion)** :
- `is_regulatory_lifecycle_statement()` (verbes structurels + cible
  paragraphe/section/appendix, + provenance documentaire identifiée) → override
  du DROP y compris en déchet franc, comme la garde supersession.
- Garde EXIGENCE : identifiant + verbe d'exigence (requires/shall/must)
  neutralise la suppression déchet-franc.
- Prompt décomposition : règle « NEVER truncate a PURPOSE or OUTCOME clause ».
- Tests sur les ancres réelles perdues (76 verts).

**Réparation CMP_0003/0007/0011** (`apply_gold_cmp_repair_20260605.py`) :
questions précisées + golds reciblés sur des paires FAA/EASA **vérifiées des
deux côtés** dans le KG staged :
- CMP_0003 : belt cut/torn (AC 25.562-1B) vs seatbelt misalignment (ETSO-C127b)
- CMP_0007 : protection occupants CFR Part 25 vs « not optimal » NPA 2013-20
- CMP_0011 : underseat baggage — déplacement siège (AC 23.562-1) vs rétention
  gilet de sauvetage (ETSO-C127b)

⚠ Les questions relabellisées unanswerable le 05/06 (PSAIR100, 5e(5), Appendix J…)
devront être RE-RELABELLISÉES answerable après la prochaine ré-ingestion (les
gardes ci-dessus ressusciteront leurs ancres).
