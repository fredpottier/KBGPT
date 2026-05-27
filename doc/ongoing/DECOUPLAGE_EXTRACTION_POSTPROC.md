# Découplage extraction / post-traitement ClaimFirst — identification & marche à suivre

> 2026-05-27. **Note d'identification, AUCUN code modifié.** Objectif : savoir OÙ couper et
> COMMENT traiter le sujet. Décision de la marche à suivre = à valider avec Fred.

## 1. Constat de départ

Run de nuit : **4 docs en 7,4h, post-traitement même pas terminé.** Mesures isolées (burst g6,
Qwen2.5-14B exact) :
- Concurrence LLM extraction : **32/32, parallélisme 25-31×** → PAS le problème.
- Grounding NLI : 12% → PAS le problème.
- Extraction claims seule : **0,36s/claim** (012 : 1147 claims en 6,9 min) → rapide.

**Le coût est dans les phases LLM PAR-DOC après l'extraction**, masquées sous l'étiquette
« EXTRACTING » par le heartbeat (`worker_job.py` l.231). Mesure par-phase (training_aa, 439s) :

| Phase | Temps | % | LLM | Étape page post-import ? | Dépendances |
|---|---|---|---|---|---|
| **1.8 SubjectIndexer** | 135,6s | **31%** | ✅ | ❌ **aucune** | peuple `subject_canonical` |
| 1 Extraction | 86,7s | 20% | ✅ | (cœur, à garder) | — |
| **2.5 Canonicalisation entités** | 80,6s | **18%** | ✅ | ✅ `canonicalize` | alimente 2.6, 2.8 |
| [Phase 0 / overhead] | 76,2s | 17% | partiel | — | contexte, passages, subject resolver |
| 1.7 Slot enrich | 18,4s | 4% | ✅ | ❌ aucune | claims sans structured_form |
| 2.9 Facet extract | 14,8s | 3% | ✅ | ✅ `facets` | — |
| 2.6 Independence | 12,8s | 3% | ✅ | ❌ aucune | besoin entités |
| 1.6 / 2.8 / 2.1 / 1.4 | < 6s ch. | — | mixte | partiel | — |

**Phases LLM-lourdes déférables ≈ 60% du temps par-doc.** Mais le n°1 (SubjectIndexer, 31%)
n'a **pas** d'étape dans la page post-import, et il produit `subject_canonical` — **critique
pour le retrieval/bench** (cf. mémoire « subject_canonical quasi-obligatoire »).

## 2. Réalité structurelle (pourquoi ce n'est pas « commenter 1 ligne »)

`orchestrator.process_and_persist` enchaîne **~15 phases par-doc** entremêlées
(extraction → gates → enrichment → SubjectIndexer → entités → canonicalisation →
independence → sujets-dérivés-des-entités → facets → clustering → linking → persist).
Le bloc **cross-doc** (worker_job Phases 9-13 : chains, canon cross-doc, clustering,
QS-comparison, hygiene) ne tourne **qu'après TOUS les docs** et n'avait pas encore consommé
de temps après 7,4h → **le couper ne sauve PAS le temps**. Le coût est dans les phases per-doc.

**Dépendances bloquantes** :
- 2.5 (canonicalisation) → 2.6 (independence) → 2.8 (sujets dérivés des entités canonicalisées).
- La canonicalisation de la page (`canonicalize_entities_cross_doc.py`) crée des `CanonicalEntity`
  **globalement** sur les entités persistées — c'est une **couche différente** de la per-doc 2.5
  (qui, elle, fusionne intra-doc et alimente 2.8). Déférer 2.5 ⇒ déférer aussi 2.6 + 2.8, et
  accepter que les sujets dérivés se calculent sur entités brutes (ou après canon cross-doc).

## 3. Insight important

**Le découplage RÉORGANISE le calcul, il ne le réduit pas.** SubjectIndexer prendra ses 135s
que ce soit dans le job ou dans la page (les phases post-extraction ne sont **pas parallélisées
32×** comme l'extraction — 0,86s/claim en série). Le gain du découplage :
1. **Extraction rapide + itérable** (on re-extrait sans repayer tout le post-traitement).
2. **Post-traitement global, re-jouable, optimisable séparément** (chantier optim = paralléliser
   SubjectIndexer + canonicalisation comme l'extracteur → ×6-10 attendu, mais plus tard).
3. Découple aussi la **sur-extraction** : on voit le volume de claims AVANT de payer le post.

## 4. Options de marche à suivre

### Option A — Frontière « claims bruts » (cut maximal, gros gain, +étapes page)
- **Job extraction** persiste : claims (text+verbatim+structured_form si présent) + entités
  brutes + liens ABOUT/SUPPORTED_BY. **Stop là.**
- **Défère à la page** : SubjectIndexer, slot_enrich, independence, canonicalisation, facets,
  clustering, embeddings, cross-doc.
- **À CRÉER** : 1 étape page « Finalisation claims » regroupant SubjectIndexer + slot_enrich +
  independence (les 3 sans couverture actuelle), à placer AVANT `canonicalize`.
- Gain : ~80% du temps sort du job. Risque : nouvelle étape + valider dépendances sur KG persisté.

### Option B — Frontière « claims finalisés » (cut minimal, zéro nouvelle étape, gain moyen)
- **Job extraction** garde les phases claim-level + **SubjectIndexer** (subject_canonical reste
  peuplé) + persiste.
- **Défère à la page (existant déjà)** : canonicalisation (18%), facets (3%), clustering,
  embeddings, cross-doc.
- Gain : ~25-30% du temps sort du job. Avantage : **zéro nouvelle étape**, risque minimal.
- Inconvénient : SubjectIndexer (31%) reste dans le job → le plus gros coût reste subi par doc.

### Option C — A + paralléliser SubjectIndexer/canonicalisation
- = Option A mais on traite tout de suite la parallélisation (optim). Fred a cadré l'optim comme
  **chantier séparé** → à garder pour après, mais c'est là qu'est le vrai gain de temps total.

## 5. Recommandation (à valider)

**Option A** est la seule qui sort le SubjectIndexer (31%, le plus gros) du chemin d'extraction et
rend l'extraction réellement rapide + itérable — au prix d'**une** étape page « Finalisation
claims » à créer. Mécaniquement c'est le bon design cible (extraction pure ⟂ enrichissement).
Si on veut zéro risque immédiat pour débloquer un KG ce matin, **Option B** donne un gain partiel
sans rien créer, et on fera A ensuite.

## 6. Questions ouvertes pour décider
1. On vise le cut maximal (A, +1 étape page) ou le cut minimal sans risque (B) d'abord ?
2. `subject_canonical` : OK pour le calculer en post (page) plutôt qu'en extraction ? (impacte
   quand il devient disponible pour le bench)
3. La canonicalisation per-doc (2.5) : on l'abandonne au profit du seul cross-doc de la page, ou
   on garde les deux couches ?
4. Mode de déclenchement : un flag `CLAIMFIRST_EXTRACTION_ONLY=1` sur le job + la page existante ?
