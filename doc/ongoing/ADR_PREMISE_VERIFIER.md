# ADR — PremiseVerifier : détection des faux présupposés (runtime_v6)

*Statut : ACCEPTÉ (auto-validé, 2026-05-30). Domain-agnostic strict.*

## Contexte & problème

Bench : `false_premise` = plus gros gap qualité. Sur 5 cas, OSMOSIS **confabule** 3 fois
(« Embedded Reporting Studio », « Oracle natif dans S/4HANA », « migration directe Business
One→S/4HANA ») : il décompose la question, récupère des claims sur les **parties réelles**
(S/4HANA, conversion, intégration native), l'Evaluate voit « des claims existent → répondre »,
et Synthesize **fabrique** une réponse plausible sans jamais vérifier que l'entité/relation
*spécifique* présupposée existe.

**Probe confirmé** : le retrieval vectoriel **ne distingue pas** un faux présupposé d'une vraie
question — les entités fausses scorent 0,82–0,90 (≥ contrôle 0,86) car le vecteur est dominé par
les termes *réels* ; la partie fausse est diluée. Donc aucun signal basé sur le score/présence
ne marche.

## État de l'art consulté

- **Kim et al., ACL 2021** (Presupposition Verification for QA) : framework *génération du
  présupposé → vérification NLI → explication*. Réponse expliquant l'échec **préférée** des users.
- **CREPE, ACL 2023** : 25% des vraies questions ont un faux présupposé ; vérification
  **bottleneck = retrieval de la preuve**.
- **FalseQA, ACL 2023** : le LLM *a* la connaissance (problème d'activation) ; zero-shot faible ;
  entraîner FP-only → **sur-rejet 24%** des questions valides ; « data replay » → 1,4%.
- **Premise Verification via RAG Logical Reasoning, 2025** : extraction de prémisses →
  **retrieval DÉDIÉ par prémisse** → SUPPORTED/CONTRADICTED/NOT_FOUND ; *« les prémisses
  invérifiables ne déclenchent PAS de rejet — distinguer faux confirmé vs absence de preuve »*.
- **Google « Sufficient Context », 2024** : ajouter du contexte **augmente** l'hallucination
  (fausse confiance) ; autorater LLM CoT+few-shot fiable à 93%.

## Décision

Nouveau module **`PremiseVerifier`** (runtime_a3), invoqué tôt dans `Synthesizer.synthesize()`
(toggle `V6_PREMISE_VERIFIER_ENABLED`, défaut OFF). Pipeline en 3 temps :

1. **Extraction** des présupposés de la question (LLM few-shot CoT, JSON, domain-agnostic) —
   propositions tenues pour acquises (existence d'entité/capacité/relation/procédure). Max 3.
2. **Retrieval DÉDIÉ par présupposé** : pour chaque présupposé, embedding + Qdrant chunks
   (`knowbase_chunks_v2`), pool dédupliqué (≤10 passages). *Clé* : on cherche la preuve du
   présupposé, pas de la question de surface.
3. **Vérification 3-voies** (LLM few-shot CoT, ancré sur l'evidence dédiée) → statut global :
   - **OK** : présupposés supportés/plausibles, aucun contredit → pipeline normal.
   - **FALSE_CONTRADICTED** : ≥1 présupposé directement contredit par l'evidence → **réponse
     corrective** citant le fait contredisant (« S/4HANA requiert HANA ; Oracle non supporté »).
   - **FALSE_UNSUPPORTED** : l'entité/capacité *spécifique* présupposée n'est **pas attestée**
     (seulement de l'adjacent) → **note honnête** (« le corpus ne documente pas X »).

### Handling asymétrique (anti-sur-abstention, conforme SOTA)
- CONTRADICTED → réponse corrective confiante (mode `REASONED`, cite l'evidence contredisante).
- UNSUPPORTED → note honnête (mode `REASONED`, pas d'abstention sèche), **uniquement** quand
  l'entité principale est clairement absente — conservateur.
- **Jamais** de rejet sur simple « réponse incomplète » (≠ SufficiencyChecker INSUFFICIENT qui
  sur-abstenait à 78%). On découple totalement de ce chemin.

### Pourquoi ça n'over-abstient pas
On ne juge plus « l'evidence suffit-elle à répondre » mais « le présupposé *précis* est-il
contredit / non attesté ». Le présupposé d'une vraie question est attesté → silence du détecteur.

## Garde-fous & mesure
- Domain-agnostic strict : prompts + few-shots **sans** token corpus-spécifique (exemples
  inventés type « ProductX / Quantum Cache module »).
- Fail-open : toute erreur LLM/retrieval → statut OK (ne bloque jamais le pipeline).
- **Bench discipline (FalseQA)** : mesurer l'attrape des 5 `false_premise` **ET** le taux de
  faux-rejet sur les questions normales (cible : ~0 régression). Le succès = améliorer FP sans
  dégrader factual/list/multi_hop/comparison/lifecycle.

## Alternatives écartées
- Réutiliser l'evidence d'Execute (surface) : invalidé par le probe + CREPE.
- Prompt one-liner « est-ce un faux présupposé ? » : zero-shot faible (FalseQA 8,7%).
- « NON-ATTESTÉ → abstenir » : piège à sur-abstention (papier 2025, open-world).
- Réactiver SufficiencyChecker INSUFFICIENT : sur-abstention 78% prouvée.

## Addendum (post-bench A/B) — confirmation lexicale anti-faux-positif

Bench A/B subset (19q, OFF vs ON) : **false_premise +40pp (0,50→0,90)** mais **4 faux
positifs** sur normaux (−10,7pp) — verdict `FALSE_UNSUPPORTED` qui confond *« retrieval
n'a pas trouvé »* avec *« n'existe pas »* (ex : « Labeling Workbench » existe = transaction
CBGLWB ; « P_PYC_POL » objet réel). C'est l'écueil open-world (papier 2025 : « exiger une
absence réelle, pas un raté de retrieval »).

**Correctif** : pour `FALSE_UNSUPPORTED` uniquement, **confirmation lexicale d'existence** de
l'`focal_entity` (extrait en même temps que les présupposés) — recherche ciblée sur le nom
seul, match lexical (substring/mots de contenu) sur **les chunks ET les claims KG** (le savoir
d'OSMOSIS vit surtout dans les claims : « Labeling Workbench » = 3 claims, 0 chunk). Si l'entité
est attestée → **rétrograde en OK** (c'était un raté de retrieval). `FALSE_CONTRADICTED`
(contradiction explicite) n'est JAMAIS rétrogradé. Validé : 5/5 cas corrects (3 vrais FP gardés,
faux positifs rescapés).

## Fichiers
- NEW `src/knowbase/runtime_a3/premise_verifier.py`
- EDIT `src/knowbase/runtime_a3/synthesize.py` (check précoce, toggle)
- NEW `tests/runtime_a3/test_premise_verifier.py`
- Bench : réutilise `bench_a38_runtime_v6.py` sur subset FP + normaux.
