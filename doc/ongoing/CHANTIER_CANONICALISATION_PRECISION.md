# CHANTIER — Précision de la canonicalisation KeyPoint / détection de débats (OPEN)

> **Statut : OPEN, non résolu.** La couche `CanonicalKeyPoint` est livrée et FONCTIONNELLE
> (surface des débats, bat le RAG), mais la **précision** (« même question → même débat précis »,
> détection déterministe du débat-vedette) n'est PAS atteinte. À reprendre avec **consensus
> octopus + littérature**, PAS un énième patch. Indexé depuis `ETAT_DES_CHANTIERS.md` §G.
> Branche : `feat/keypoint-remediation`. Voir aussi mémoire `project_canonical_keypoint_layer`.

## 1. Le problème
La couche débats repose sur la **canonicalisation** : regrouper les ~4452 `normative_question`
fragmentées (le même concept existe en N variantes de surface) en familles `CanonicalKeyPoint`,
le flag `is_debate` vivant sur la famille. Le surfaçage runtime = 1-hop déterministe
`claim → KeyPoint → CANON_OF → CanonicalKeyPoint{is_debate}`.

**Symptôme vécu (Fred, 12/06)** : deux formulations quasi identiques (« quel est le niveau sans
risque » vs « y a-t-il un niveau sans risque ») donnent des résultats différents et ne surfacent
pas le **même** débat (parfois un débat tangentiel, parfois rien).

## 2. Diagnostic (le whack-a-mole observé)
Le cœur du problème : on regroupe par **égalité de chaîne EXACTE** sur la `canonical_question`
produite par le LLM — or **même un bon LLM formule sa sortie canonique de façon variable**
(« is safe » vs « minimizes health risk »). Donc le 1er passage ne suffit jamais ; c'est la
2ᵉ couche (dédup par embedding + confirm LLM) qui fait le vrai regroupement. Réglages essayés :

| Réglage | Résultat |
|---|---|
| **14B (Qwen2.5-14B burst)** normalisation | **SOUS-FUSIONNE** : le concept « niveau sûr » reste éclaté en ~10 familles → incohérence de formulation (le symptôme de Fred). |
| **Novita (llama-3.3-70b)** normalisation | **SUR-DÉCOUPE LE SCOPE** : extrait trop agressivement (« …pendant la grossesse / pour la démence / pour le cancer ») → éclate le débat-vedette GBD par scope → **perd** « zéro vs non-zéro santé globale ». |
| Dédup **union-find + confirm 14B** (seuil 0.93) | **SUR-FUSION CATASTROPHIQUE** transitive (famille GBD polluée par ~78 questions mortalité/dose ; « cancer » fusionné à « mortalité »). |
| Dédup **best-anchor, ancres non fusionnées** (14B) | Conservateur, pas de sur-fusion, mais **sous-fusionne** (ne réunit pas health-risk/health-loss/safe-level). |
| Dédup **best-anchor + fusion d'ancres + confirm Novita fort** (seuil 0.93) | Propre (cancer reste cancer, pas de méga-cluster) **mais** combinée à la normalisation Novita sur-découpée → GBD non détecté. |
| **Détection débat au niveau canonique** (tier1 + juge) | **NON-DÉTERMINISTE** : la famille GBD « minimizes health risk/loss » est parfois flaggée débat, parfois non (normalisation non-déterministe + claims qui clusterisent différemment). Garde-fou « GBD doit être un débat » passé en **avertissement non bloquant** (sinon l'assert laissait la couche VIDE). |

**État live actuel** : 15 familles-débats (cancer correctement non-débat) ; les 2 formulations
« niveau sans risque » surfacent un débat (souvent tangentiel : « have health benefits », AVC),
**pas** le débat précis « seuil zéro vs non-zéro ».

## 3. Tension fondamentale à arbitrer (le curseur)
Trois échecs opposés sur un même curseur :
- **Sous-fusion** (14B) → familles trop fines → incohérence de formulation, débat dispersé.
- **Sur-fusion** (union-find + gate faible) → familles trop grosses → faux débats (cancer=mortalité).
- **Sur-scope** (Novita) → bonne dé-paraphrase MAIS scope trop découpé → le débat « global » se
  dissout dans les sous-scopes.
Aucun (modèle × seuil × règle de fusion) testé n'atteint le bon équilibre.

## 4. Pistes à instruire au prochain tour (littérature + consensus octopus)
- **Ne PAS reposer sur l'égalité de chaîne exacte** de la sortie LLM (intrinsèquement fragile).
  Regrouper par **embedding + confirm LLM fort**, mais **borné** (pas d'union-find transitif aveugle
  — cf. le piège des 1481 / cancer=mortalité).
- **Calibrer l'extraction de scope** : le 14B n'extrait pas, Novita sur-extrait. Cible probable :
  n'extraire que les vraies restrictions de **sous-population** (sexe/âge), garder l'**outcome/
  condition** dans la question — pour que le débat « global » survive à côté des scopes.
- **Détection de débat ROBUSTE/déterministe** : le débat-vedette doit se former de façon fiable
  (peut-être : détecter le débat AVANT/indépendamment de la canonicalisation, sur les claims, puis
  rattacher ; ou ancrer la détection sur des paires de docs connues — GBD2018 vs GBD2020).
- **Séparer SURFAÇAGE et STOCKAGE** : router la question utilisateur vers le bon débat par un
  mécanisme plus robuste que « quels claims le retrieval a touché » (ex matching question↔question
  canonique de débat, avec garde anti-tangentiel — déjà étudié, tension cosinus/garde-LLM-runtime
  fragile au burst down). À reconsidérer avec la couche canonique en place.
- **Référence littérature déjà rassemblée** : Key Point Hierarchy (Bar-Haim ACL 2023, arXiv
  2306.03853), EDC (2404.03868), canonical-question/QPR. La hiérarchie de key points par
  entailment directionnel avait été ÉCARTÉE (octopus : over-engineering vs canonical plat) — à
  reconsidérer si le plat ne converge pas.

## 5. Commits / artefacts de référence
- Script : `app/scripts/canonicalize_keypoints.py` (3 phases + flags `--full-reset`, `--novita`,
  `--reset-canon`). Vérificateur débats agnostique : `app/scripts/keypoint_verify_debates.py`.
- Runtime : surfaçage 1-hop `CANON_OF` dans `runtime_v6.py` (_build_debate_appendix) + `execute.py`
  (_attach_keypoint_debates).
- Arc de commits : c4cb6bb (best-anchor), a6592ec (couche + runtime), 6bb0b08 (garde-fou non bloquant).

---
*Créé le 12/06/2026. À reprendre : arbitrer le curseur sous/sur-fusion/sur-scope + détection débat
robuste, avec consensus octopus avant de coder.*
