# Glossaire des nodes Neo4j — OSMOSIS

*Référence rapide du rôle et de la fonction de chaque type de node dans le Knowledge Graph OSMOSIS. Mis à jour avril 2026 (post couche Perspective V2).*

---

## Vue synthétique

| Node | Question fonctionnelle | Granularité | Origine | Volume typique |
|---|---|---|---|---|
| `Document` | *quel fichier ?* | physique | ingestion | ~30 |
| `DocumentContext` | *quel chapitre/section dans le doc ?* | structurelle | ingestion | ~300 |
| `Claim` | *quel fait précis ?* | atomique | extraction LLM | ~15 000 |
| `Entity` | *quelle chose nommée est citée ?* | lexicale | extraction LLM | ~2 200 |
| `ComparableSubject` | *quel produit/version ?* | ancrage produit | résolution canonique | ~10-30 |
| `Facet` | *selon quelle dimension comparer ?* | axe d'analyse | bootstrap + consolidation | ~50-100 |
| `Perspective` | *quel thème transversal ?* | cluster sémantique | clustering global (V2) | ~60 |

---

## Détail par node

### `Document`
**Rôle** : l'unité physique ingérée. Un Document = un PDF, un PPTX, un fichier source.
**Exemple** : `027_SAP_S4HANA_2023_Security_Guide.pdf`
**À retenir** : tout part de là. Tous les autres nodes (sauf ontologie) sont rattachés directement ou indirectement à un Document.

### `DocumentContext`
**Rôle** : un sous-ensemble logique d'un Document (chapitre, section, slide range). Permet de localiser plus finement qu'au niveau du Document entier.
**Exemple** : *"Section 4.2 — Authorization Objects"* du Security Guide 2023
**À retenir** : c'est le pivot entre Document et Claim. Sert aussi de point d'attache pour `ABOUT_COMPARABLE` (le rattachement au ComparableSubject se fait au niveau du DocumentContext, pas du Document entier — un même Document peut traiter de plusieurs versions).

### `Claim`
**Rôle** : un fait atomique extrait d'un Document, formulé en langage naturel.
**Exemple** : *"L'objet d'autorisation S_TABU_NAM contrôle l'accès aux tables par nom dans S/4HANA 2023"*
**À retenir** : c'est la **matière première** du KG, les "molécules" sur lesquelles tout le reste opère. ~15 000 dans le corpus actuel. Chaque Claim porte un embedding (E5-large) et est relié à ses Entities, Facets et éventuellement Perspective(s).

### `Entity`
**Rôle** : une chose nommée mentionnée dans un Claim. Granularité technique fine.
**Exemple** : `S_TABU_NAM`, `BRFplus`, `HTTP Allowlist`, `/SCMTMS/`, `SAP Fiori`
**À retenir** : ~2 200 entités. **Une Entity ne porte aucun sens en elle-même** — elle existe parce qu'un ou plusieurs Claims la mentionnent. C'est la couche d'indexation lexicale du graphe. Sert aux questions directes ("Quel objet d'autorisation contrôle X ?") et au resolver d'intent.

### `ComparableSubject`
**Rôle** : un **produit canonique versionné**. Répond à *"de quel produit/release ce contenu parle ?"*.
**Exemple cible** : `SAP S/4HANA 2023`, `SAP S/4HANA 2022`, `SAP Ariba Network`, `SAP BTP`
**À retenir** : ~10-30 items attendus, **petit et stable**. C'est ce qui permet à OSMOSIS de comprendre que "Security Guide 2022" et "Security Guide 2023" parlent **du même produit à deux moments** → base mécanique des évolutions cross-version, des tensions documentaires et des comparaisons.
**Différence avec Perspective** : Subject est **descendant** (imposé par la nature du document, résolu à l'ingestion). Perspective est **ascendante** (émergente du contenu, découverte par clustering).

> ⚠️ **État dégradé actuel (avril 2026)** : le KG ne contient qu'**1 seul ComparableSubject** (`SAP S/4HANA Cloud Private Edition`) qui agglomère à tort plusieurs produits distincts du corpus (S/4HANA umbrella, ses 3 variantes de déploiement, SAP ILM…). La couche n'est **pas exploitable en l'état**. Voir `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md` pour le diagnostic complet et l'impact sur la couche Perspective et l'Atlas narratif.

### `Facet`
**Rôle** : un **axe de description structurel** que peut porter un Claim. C'est une propriété typée, pas un thème.
**Exemple** : `release_id`, `deployment_mode`, `authorization_object`, `security_level`, `installation_step`
**À retenir** : ~50-100 facets. Deux Claims qui partagent la même Facet sont **comparables sur cet axe**. C'est la **grille d'analyse structurelle** du KG — elle alimente les comparaisons fines, les détections de divergence, et nourrit le clustering Perspective via le vecteur composite (50% facet membership + 50% embedding).

### `Perspective`
**Rôle** : un **thème transversal émergent** du corpus. Un cluster dense de Claims qui se ressemblent sémantiquement.
**Exemple** : *"User authentication and SSO"*, *"Migration tooling"*, *"Authorization objects lifecycle"*
**À retenir** : ~60 perspectives en V2. **Découverte par HDBSCAN** sur les embeddings de Claims (1024D → 15D via UMAP), labellisée par LLM (Haiku). Une Perspective peut **toucher plusieurs ComparableSubjects** via `TOUCHES_SUBJECT` — c'est ce qui en fait un thème *transversal* (par opposition à Subject qui est ancré sur un seul produit).
**À quoi ça sert** : structurer les réponses du mode `PERSPECTIVE` aux questions ouvertes ("quels sont les axes de sécurité dans S/4HANA ?") en présentant les preuves par axe thématique plutôt qu'en vrac.

---

## Astuce mnémotechnique

- **Subject** = *"de quoi ça parle"* (produit)
- **Facet** = *"comment on le décrit"* (dimension)
- **Entity** = *"ce qui est cité dedans"* (mention)
- **Perspective** = *"ce qui en émerge transversalement"* (thème)

Subject et Perspective sont les deux qu'on confond le plus facilement. La distinction clé :

| | Subject | Perspective |
|---|---|---|
| Sens | descendant (donné par le document) | ascendant (émergent du contenu) |
| Cardinalité | ~10-30 | ~60 |
| Quand est-il créé ? | à l'ingestion (résolution canonique) | par batch après ingestion (clustering global) |
| Stable dans le temps ? | oui (évolue lentement) | recalculé à chaque rebuild |
| Sert à | comparer des versions du même produit | structurer des réponses thématiques |

---

## Relations principales

```
(Document)-[:HAS_CONTEXT]->(DocumentContext)
(DocumentContext)-[:ABOUT_COMPARABLE]->(ComparableSubject)
(Claim)-[:IN_DOCUMENT]->(Document)
(Claim)-[:MENTIONS]->(Entity)
(Claim)-[:BELONGS_TO_FACET]->(Facet)
(Claim)-[:CONTRADICTS|REFINES|SUPPORTS]->(Claim)

(ComparableSubject)-[:HAS_PERSPECTIVE]->(Perspective)
(Perspective)-[:INCLUDES_CLAIM]->(Claim)
(Perspective)-[:SPANS_FACET]->(Facet)
(Perspective)-[:TOUCHES_SUBJECT]->(ComparableSubject)
```

`TOUCHES_SUBJECT` est la relation **transversale** qui distingue V2 de V1 : une Perspective peut maintenant toucher plusieurs Subjects, alors qu'en V1 chaque Perspective était strictement scopée à un Subject (ce qui produisait la "méga-Perspective hégémonique" que la refonte a éliminée).

---

## Voir aussi

- `doc/ongoing/ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md` — architecture détaillée de la couche Perspective et historique V1 → V2
- `doc/CHANTIER_ATLAS.md` — section 7, où Perspective et Subject deviennent les briques de base de l'Atlas narratif (NarrativeTopic)
