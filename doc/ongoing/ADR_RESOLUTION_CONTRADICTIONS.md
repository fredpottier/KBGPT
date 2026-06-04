# ADR — Résolution des contradictions : cascade de preuves & droit d'invalider

> **Statut** : ACCEPTÉ (Fred, 04/06/2026) · **Branche** : `feat/phase-b-augmentee`
> **Contexte corpus** : décision prise sur le corpus aéro (sièges), mais **domain-agnostic
> par construction** — toute heuristique spécifique est isolée et extensible par domaine.

---

## 1. Contexte & problème

Après la ré-ingestion staged du corpus aéro (~17 000 claims, 23 docs dont 6 familles
de versions délibérées), l'audit du 04/06 a trouvé :

- **567 relations `CONTRADICTS`** (vs 69 sur l'ancien corpus) ;
- **0 résolues** par la règle bitemporelle §9.4, **635 `ConflictPending`** dont
  **548 en CAS_1** (les deux dates présentes — le cas censé trancher !) ;
- Cause mécanique : les détecteurs émettent des confiances **codées en dur ≤ 0.80**
  (`relation_detector.py`), alors que le droit de superséder exige **≥ 0.85**
  (`marker_type='inferred'`). **Les deux seuils ne peuvent jamais se rencontrer**
  → la branche de résolution est structurellement morte.

L'audit qualitatif a montré que « contradiction » recouvre **trois natures distinctes** :

| Nature | Part (aéro) | Exemple | Bon traitement |
|---|---|---|---|
| **Évolution** (versions d'un même document) | ~58 % | AC 25-17 (1991) « thermocouples métal » vs AC 25-17A (2009) « céramique » | l'ancien n'est **plus en vigueur** (invalidé, conservé pour l'historique) |
| **Divergence** (sources vivantes) | ~6 % | FAA 0,09 s vs EASA 0,08 s | les deux restent **vifs**, exposés avec attribution |
| **Artefact** (faux positif de détection) | ~36 % | near-duplicates (un AC citant le CFR), opposés décontextualisés | ne pas créer la relation |

## 2. Le piège qui a façonné la décision

Cas soulevé par Fred : *doc 1 « la fonctionnalité A déclenche le process xx » ;
doc 2 (postérieur) « la fonctionnalité A déclenche le process yy ».*
**Rien dans le corpus ne dit si yy s'ajoute à xx ou le remplace.**

Deux conclusions structurantes :

1. **Arité des prédicats.** `déclenche/inclut/supporte` sont **multi-valués** : deux
   objets différents ne sont PAS une contradiction (→ `COMPLEMENTS`). Une vraie
   contradiction exige un **slot exclusif** (seuil, délai, valeur désignée unique :
   « ≤ 6 in » vs « ≤ 8 in »). La classification doit le vérifier EN AMONT.
2. **Une date n'est pas un remplacement.** « Plus récent » ne prouve jamais
   « à la place de ». Si le corpus ne contient pas l'information de remplacement,
   **le système ne doit pas l'inventer** — il expose, il ne tranche pas.

## 3. Décision — la cascade de preuves

Pour toute paire `CONTRADICTS` détectée, dans l'ordre, **de la preuve la plus forte
à la plus faible** :

| Niveau | Preuve | Droit d'INVALIDER le perdant ? |
|---|---|---|
| **1. Lignée documentaire explicite** | phrase verbatim « This AC cancels AC 25-17 » → `SUPERSEDES_DOC` (détecteur #443) | ✅ **OUI** — le document entier est prouvé hors vigueur ; tout claim du doc superséd é qui contredit un claim du successeur est invalidé (`invalidated_at` + `valid_until`), **conservé** pour les requêtes lifecycle/timeline |
| **2. Convention de versionnage des identifiants** | `ETSO-C127a → b → c`, `25.785-1A → 1B` : le suffixe de révision est le système formel de l'autorité émettrice | ✅ **OUI** — édition successeur du même document (marker `inferred`, heuristique étiquetée extensible par domaine) |
| **3. Dates seules** (même autorité, AUCUNE lignée) | `valid_from` doc/claims | ❌ **NON — jamais d'invalidation.** Les deux claims restent vivants. La **synthèse** présente temporellement (« le document de 2023 indique yy ; celui de 2019 indiquait xx ») et l'humain tranche « en plus / à la place » |
| **4. Inter-autorités** | FAA vs EASA (via `regulatory_authority`, heuristique étiquetée) | ❌ **JAMAIS de résolution automatique** — divergence vive, exposée attribuée (« ⚠ Divergence entre autorités ») |
| **5. Aucune preuve** | — | ❌ `ConflictPending` = **abstention au niveau relation** : « je ne peux pas déterminer lequel prévaut », les deux exposés. C'est une feature (marque OSMOSIS), pas un échec |

**Principe pivot : l'invalidation n'est permise QUE lorsqu'un *document* est prouvé
remplacé (niveaux 1-2).** Là, « à la place » est établi au niveau du conteneur —
y compris pour les faits additifs. Les dates seules ne donnent qu'un **ordre de
présentation**, jamais un droit de destruction.

## 4. Gardes amont (réduire les artefacts — #446)

1. **Arité des prédicats** : table déterministe (multi-valué vs slot exclusif) ;
   prédicat multi-valué + objets différents → `COMPLEMENTS`, jamais `CONTRADICTS`.
2. **Garde near-duplicate** : overlap lexical élevé entre les deux verbatims
   (un doc citant l'autre) → pas une contradiction (au plus `REFINES`).
3. **Compatibilité de contexte/qualifiers** : des conditions d'applicabilité
   différentes (« Table 3 » vs « Table 4 », contextes de test différents)
   → `DIFFERENT_SCOPE`, pas `CONTRADICTS`.

## 5. Conséquences / plan d'implémentation

1. **Étape post-import « résolution par lignée »** (niveaux 1-2) : après
   `explicit_lineage`, pour chaque `CONTRADICTS` entre docs reliés par
   `SUPERSEDES_DOC` (direct ou transitif, y compris lignée inférée par convention
   de version), invalider le claim du doc superséd é. Idempotent, traçable
   (`invalidation_reason='doc_lineage'` + lien vers la preuve).
2. **Synthèse — présentation temporelle** (niveau 3) : règle de prompt — une paire
   contradictoire datée NON résolue se présente avec les deux dates et sources,
   sans privilégier silencieusement la récente.
3. **Gardes amont** (§4) dans `relation_detector` / `c4` (#446).
4. **Règle morte documentée** : le chemin « confiance ≥ 0.85 → supersession » est
   inatteignable avec les confiances codées en dur ; il est REMPLACÉ par la
   cascade ci-dessus (la confiance de classification ne donne plus de droit
   d'invalider — seule la lignée documentaire le donne).
5. **Re-mesure** post-implémentation : attendu sur l'aéro ≈ 327 paires résolues
   par lignée, 36 divergences vives exposées, artefacts en baisse via les gardes.

## 6. Alternatives rejetées

- **Abaisser le seuil 0.85 / élever les confiances** pour réactiver §9.4 :
  rejeté — une date ne prouve pas un remplacement (cas « en plus / à la place »).
  La classification, même très confiante, ne porte pas l'information de succession.
- **Auto-résolution CAS_1 (deux dates) sans lignée** : rejeté pour la même raison ;
  invaliderait des faits additifs et propagerait les ~204 faux positifs.
- **Tout laisser en ConflictPending** (statu quo) : rejeté — 85 % du « conflit »
  affiché est en réalité de l'historique de versions ; le bruit masque les 36
  divergences réelles qui, elles, ont une valeur produit majeure.

## 7. Amendements (revue croisée du 04/06/2026 — ACCEPTÉS)

### A. Niveau 2 (convention de version) — corroboration obligatoire (ex-B1)
Le suffixe de révision est une **inférence**, pas un verbatim. Droit d'invalider
seulement si TROIS signaux concordent : même base-ID **ET** même autorité émettrice
**ET** ordre des suffixes concordant avec l'ordre des `valid_from` quand les dates
existent. Désaccord ou date absente → rétrogradé en `EVOLUTION_OF` (présentation),
**sans invalidation**. Locus cible : parser de convention = asset **Domain Pack**
(heuristique étiquetée en attendant).

### B. Arité des prédicats — défaut CONSERVATEUR (ex-B2)
Pour tout prédicat NON répertorié : défaut = **slot exclusif** (la contradiction
est préservée et exposée). Seuls les prédicats explicitement répertoriés additifs
(`includes/triggers/supports`-like) passent en `COMPLEMENTS`. Table = asset Domain
Pack. Micro-spike de couverture sur les prédicats du corpus avant commit.

### C. État de l'arête après résolution niveaux 1-2 (ex-B3)
L'arête `CONTRADICTS` résolue est **convertie en `:SUPERSEDES`**
(`marker_type='inferred'`, `detection_method='doc_lineage'`) — préserve
l'invariant d'exclusion mutuelle et la visibilité dans les requêtes lifecycle
runtime (`EVOLUTION_OF|SUPERSEDES`).

### D. Cancellation de document = DEUX NIVEAUX (ex-B4, décision Fred)
Pour un document prouvé remplacé (`SUPERSEDES_DOC`, **scope='full'** uniquement) :
- **(a) Invalidation dure** : claims du doc superséd é **contredits** par un claim
  du successeur → `invalidated_at` + conversion `:SUPERSEDES` (cf C).
- **(a′) Retrait verbatim explicite** : si le corpus énonce noir sur blanc le
  retrait d'un contenu précis (« the requirements of X no longer apply ») →
  invalidation dure aussi, même sans contrepartie contradictoire.
- **(b) Marqueur souple épistémique** pour les AUTRES claims du doc annulé :
  l'axe lifecycle EXISTANT (`lifecycle_status_current='withdrawn'`,
  `reason='container_cancelled_by:<doc_id>'`, `change_date=successor.valid_from`)
  — PAS de champ parallèle, PAS de `invalidated_at`.
  **Sémantique épistémique stricte** : « le document porteur a été annulé et
  aucun successeur ne se prononce sur ce point » — JAMAIS « ce claim n'est plus
  valide » (on ne le sait pas ; inventer le remplacement = le piège xx/yy).
  Caveat de synthèse : *« selon <doc> (document annulé en <date>) ; le successeur
  ne restate pas ce point »*.

### E. Précondition scope full/partial sur SUPERSEDES_DOC (raffinement bloquant)
`SUPERSEDES_DOC` porte `scope: 'full'|'partial'` (+ `sections:[…]` si partiel).
Seul `scope='full'` déclenche le marqueur souple en bloc ; `partial` ne touche
que les sections nommées. État actuel : le détecteur #443 rejette les formes
partielles (garde « paragraphs/sections ») → tous les edges existants sont
de facto full ; le rendre explicite à la matérialisation.

### F. Runtime — withdrawn = tie-breaker + déclencheur de caveat, PAS pénalité de rang
Un claim `withdrawn` n'est dé-priorisé qu'**à pertinence égale** face à un claim
actif. S'il est la seule formulation pertinente, il SURFACE (avec caveat). Une
pénalité de score dure réintroduirait le trou de réponse par le ranking.

### G. Renversement explicite de §9.4 (ex-I1)
Cet ADR ne corrige pas seulement le seuil 0.85 inatteignable : il **retire
l'invalidation par comparaison de dates au niveau claim** (§9.4 CAS 1/2 de
`ADR_RELATIONS_CLAIM_CLAIM` sont REMPLACÉS par la cascade). Amendement à
reporter dans l'ancien ADR.

### H. Honnêteté des projections (ex-I2) + séquencement (ex-I3) + cascade arêtes (ex-I4)
- Le « ≈327 résolues » devient une **fourchette à mesurer** (couverture lignée
  réelle constatée le 04/06 : 2/5 chaînes après ré-ingestion staged — cf bug
  selection-gate ci-dessous). Pessimiste/attendu/optimiste à publier avec la mesure.
- Les 3 leviers (gardes, lignée, synthèse) sont benchés **séquentiellement**,
  un delta attribué chacun.
- Le hook `invalidated_relation_at` (estampillage des arêtes du claim perdant)
  est conservé mais couvert par un test explicite.
- Mineurs : `valid_until = date d'effet du successeur, sinon successor.valid_from,
  sinon NULL` ; les gardes amont peuvent utiliser du NLI (le « zéro LLM » ne vaut
  que pour la cascade de résolution) ; la lignée écrase délibérément la date du
  claim perdant.

### I. Bugs découverts à l'application (04/06, corpus staged)
1. **La selection gate du pipeline staged JETTE les déclarations de supersession**
   (« This AC cancels… » absentes des claims) → bypass déterministe obligatoire :
   toute phrase matchant le langage de supersession documentaire est conservée
   (classe lifecycle-critique).
2. **Le parseur de lignée ignore la négation** (« does not supersede » matche) →
   garde de négation obligatoire.

## 8. Charte

Domain-agnostic : la cascade est générique. Les seules touches spécifiques —
`regulatory_authority` (FAA/EASA) et la convention de suffixe de révision — sont
des **heuristiques clairement étiquetées, extensibles par corpus** (médical :
FDA/EMA, « guideline 2019 → 2023 »). Aucun vocabulaire corpus-spécifique dans la
logique cœur. Zéro appel LLM dans la résolution (déterministe, auditable).
