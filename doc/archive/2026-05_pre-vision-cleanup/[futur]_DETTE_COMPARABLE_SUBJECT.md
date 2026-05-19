# Dette ComparableSubject — diagnostic avril 2026

## Constat

Le KG OSMOSIS contient actuellement **1 seul `ComparableSubject`** : `SAP S/4HANA Cloud Private Edition`.

Or le corpus ingéré (~30 documents) couvre en réalité **plusieurs produits distincts** :

- **SAP S/4HANA** (le produit ombrelle, traité dans la majorité des Security/Operations/Conversion Guides)
- **SAP S/4HANA Cloud, Private Edition** (une déclinaison de déploiement de S/4HANA, *pas* un produit séparé)
- **SAP S/4HANA Cloud, Public Edition** (autre déclinaison)
- **SAP S/4HANA On-Premise** (autre déclinaison)
- **SAP ILM** (un seul document, mais produit clairement distinct)
- *Possiblement d'autres selon les guides ingérés*

Toutes ces réalités sont actuellement collées sur l'unique Subject `SAP S/4HANA Cloud Private Edition`, **qui n'est même pas le bon canonical** (Private Edition est *sous* S/4HANA, pas l'inverse).

---

## Cause racine

Le `SubjectResolverV2` (`src/knowbase/claimfirst/resolution/subject_resolver_v2.py`) **n'utilise pas** le `product_gazetteer` du domain pack `enterprise_sap`.

Vérification (`grep`) : aucune occurrence de `product_gazetteer`, `canonical_aliases`, ou `context_defaults` dans `subject_resolver_v2.py`.

Pourtant, le fichier `src/knowbase/domain_packs/enterprise_sap/context_defaults.json` contient déjà :

- **528 produits SAP** dans `product_gazetteer`, avec la **hiérarchie correcte** :
  ```
  SAP S/4HANA
  SAP S/4HANA Cloud
  SAP S/4HANA Cloud Public Edition
  SAP S/4HANA Cloud Private Edition
  SAP S/4HANA On-Premise
  SAP ECC
  SAP ERP
  ...
  ```
- Une table `canonical_aliases` qui mappe les variantes vers leurs canonical (ex: `S/4` → `SAP S/4HANA`, `S4HC` → `SAP S/4HANA Cloud`, `PCE` → `SAP S/4HANA Cloud Private Edition`)
- Une liste de 100+ acronymes dans `common_acronyms`

**Le gazetteer existe, est bien chargé, mais il sert uniquement à la résolution d'alias d'`Entity`** (`orchestrator.py:_resolve_canonical_aliases` ligne 2539) et à l'API de consultation des domain packs. **Pas du tout à la création/canonicalisation des `ComparableSubject`.**

Le SubjectResolverV2 fait sa propre détection ex nihilo, sans bénéficier de la connaissance produit déjà encodée → il :

1. **Ne distingue pas** les niveaux de la hiérarchie (S/4HANA vs S/4HANA Cloud Private Edition deviennent un seul Subject)
2. **Choisit le mauvais canonical** (probablement le match lexical le plus long → "Cloud Private Edition")
3. **Loupe les produits à faible volume** (SAP ILM, un seul doc, n'a pas franchi son seuil interne)

---

## Composants impactés (présent et futur)

### Aujourd'hui

- **`TOUCHES_SUBJECT` dans le scoring Perspective** : avec 1 seul Subject, chaque Perspective touche le même unique nœud → le `subject_overlap_bonus` est **un signal mort** (toujours actif, jamais discriminant). Heureusement neutralisé après le bug du runtime infinite loop, donc pas de régression visible — mais ça veut dire que la couche Perspective tourne **sans ancrage produit utile**.

### Bloqué dès qu'on s'y appuiera

- **Détection cross-version cohérente (mode TENSION)** : pour qu'OSMOSIS dise *"le Security Guide 2022 dit X, le 2023 dit Y, c'est une évolution de la même chose"*, il faut grouper les documents par produit puis distinguer par version. Avec un Subject unique mal canonicalisé, ce mécanisme **ne peut pas fonctionner correctement**. Cette dette recoupe le bug ApplicabilityAxis 0 noté en mémoire (le release_id n'est pas propagé vers les qualifiers du DocumentContext).

- **Atlas narratif (NarrativeTopic via community detection sur Perspective ↔ Subject)** : la réflexion d'avril 2026 a décidé que les NarrativeTopics émergeraient d'une community detection sur le **graphe biparti Perspective ↔ Subject**. Avec 1 seul Subject, ce graphe biparti est **trivial** (toutes les Perspectives sont connectées au même unique nœud) → la community detection retombe sur les Perspectives seules, et on perd toute la dimension "ancrage produit" qui devait rendre les NarrativeTopics distincts (ex: "Sécurité S/4HANA" vs "Sécurité Ariba"). **Ça remet directement en cause Q2 de la réflexion Atlas.** Voir `doc/CHANTIER_ATLAS.md` section 7.

---

## Pistes de fix (à implémenter ultérieurement, pas maintenant)

### Fix minimal — exploiter le gazetteer existant

1. Charger `product_gazetteer` + `canonical_aliases` + `common_acronyms` dans le `SubjectResolverV2`
2. À la résolution, prioriser le **match avec le canonical le plus court** dans la hiérarchie quand plusieurs candidats matchent (S/4HANA gagne sur S/4HANA Cloud Private Edition pour un Security Guide générique)
3. Promouvoir les variantes de déploiement (Cloud/Public/Private/On-Premise) en **qualifiers** du DocumentContext, pas en Subjects à part
4. Baisser le seuil de création de Subject pour ne plus écarter les produits à 1 doc (SAP ILM)

### Fix structurel — ontologie produit minimaliste

Plus ambitieux : encoder explicitement la **hiérarchie produit** dans le pack `enterprise_sap` (parent/enfant), pour que le resolver puisse raisonner sur la subsomption au lieu de matcher juste sur la chaîne. Le gazetteer actuel est plat — il a la liste mais pas les relations entre items.

### Propagation release_id

Indépendant mais lié : faire en sorte que le `ContextExtractor` propage l'année/version (extraite du nom de fichier ou du full_text) vers les qualifiers du `DocumentContext`. Sans ça, même un Subject correctement canonicalisé ne pourra pas porter la dimension version. (Bug ApplicabilityAxis 0 déjà noté.)

---

## Décision actuelle

**Ne rien fixer pour l'instant.** Cette dette est tracée ici pour qu'on s'en souvienne dès qu'on activera réellement la détection cross-version ou qu'on attaquera le chantier Atlas narratif. Elle bloquera ces deux briques **dès la première vraie utilisation**, donc il faudra la résoudre avant.

La couche ComparableSubject n'étant **pas exploitée à ce jour** (en dehors du `subject_overlap_bonus` qu'on a déjà neutralisé), il n'y a **aucune régression visible côté utilisateur**. Le risque est entièrement futur.

---

## Voir aussi

- `doc/ongoing/KG_NODES_GLOSSAIRE.md` — section ComparableSubject (note dégradée)
- `doc/CHANTIER_ATLAS.md` section 7 — réflexion Atlas narratif et dépendance à la couche Subject
- `doc/ongoing/ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md` — historique V1 → V2 et rôle de TOUCHES_SUBJECT
- `src/knowbase/domain_packs/enterprise_sap/context_defaults.json` — gazetteer existant inutilisé par le SubjectResolver
- `src/knowbase/claimfirst/resolution/subject_resolver_v2.py` — le composant à modifier
