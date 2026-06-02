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
