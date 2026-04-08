# Leiden / GraphRAG dans OSMOSIS — Réflexion

*Document de réflexion, pas un plan d'implémentation. À relire quand on voudra trancher si/comment intégrer Leiden dans OSMOSIS. Rédigé avril 2026 après lecture de littérature GraphRAG (dont article ayinedjimi-consultants.fr sur Leiden) et en marge du travail sur la couche Perspective V2 et la réflexion Atlas narratif.*

---

## 1. De quoi parle-t-on

**Leiden** est un algorithme de détection de communautés dans un graphe, amélioration de Louvain (Traag et al. 2019). Il identifie des sous-graphes densément connectés en optimisant la modularité, avec une garantie de convergence vers des communautés *bien connectées* que Louvain n'offre pas. Exposé dans Python via `leidenalg` + `igraph`.

**GraphRAG** (Microsoft, 2024) est l'application de Leiden à l'intérieur d'un pipeline RAG :

1. Extraction LLM d'entités et de relations depuis les documents → graphe de connaissances
2. Leiden appliqué **hiérarchiquement** sur ce graphe → N niveaux de communautés (niveau 0 = atomique, niveau N = très globale)
3. Pré-calcul d'un **résumé LLM** pour chaque communauté à chaque niveau (les "community summaries")
4. Au moment de la query : routage vers le niveau approprié selon la granularité de la question (atomique → niveau 0, globale → niveau N), puis synthèse à partir des résumés et/ou des claims eux-mêmes

La force du pattern n'est pas Leiden en soi, c'est la **hiérarchie multi-résolution pré-calculée** qui permet à un RAG de répondre à des questions dont le scope dépasse largement la taille d'un chunk (genre *"quels sont les thèmes transversaux de ce corpus ?"*).

---

## 2. Où on en est nous

OSMOSIS a déjà mis en place, au fil des itérations et sans le planifier comme ça, une **hiérarchie à trois niveaux** qui ressemble fortement à GraphRAG conceptuellement mais a été construite différemment :

```
NarrativeTopic  (macro — ~50-100, à construire)     ← cf. réflexion Atlas narratif
   └── Perspective  (meso — ~60, HDBSCAN V2 actuel)
         └── Claim   (atomique — ~15k, unité d'extraction)
```

À chaque niveau, on a déjà — ou on prévoit d'avoir — l'équivalent d'un "community summary" :

| Niveau OSMOSIS | Équivalent Microsoft | Mode d'obtention actuel |
|---|---|---|
| Claim | niveau 0 (atomique) | extraction LLM à l'ingestion |
| Perspective | niveau 1 | HDBSCAN sur embeddings E5-large → UMAP 15D, puis labellisation LLM (Haiku) |
| NarrativeTopic | niveau 2 (global) | *prévu* : community detection sur graphe biparti Perspective ↔ Subject |

Et on a déjà **le routage question → niveau** : c'est le rôle des `ResponseMode` (DIRECT / AUGMENTED / TENSION / STRUCTURED_FACT / PERSPECTIVE), décidés par un `strategy_analyzer` (LLM Haiku) informé par la topologie des preuves. Chaque mode injecte l'information au bon niveau de granularité :

- `DIRECT` : claims bruts (niveau 0)
- `PERSPECTIVE` : axes thématiques avec claims représentatifs (niveau 1)
- *(futur)* `ATLAS` ou équivalent : NarrativeTopic synthèse (niveau 2)

**Donc conceptuellement, OSMOSIS *est* déjà un GraphRAG hiérarchique**, simplement construit avec des algorithmes différents à chaque niveau et avec un routage qui n'est pas purement lexical.

---

## 3. Les trois endroits possibles pour Leiden dans OSMOSIS

### 3.1. Niveau macro (NarrativeTopic) — usage déjà décidé

C'est l'endroit où Leiden est **déjà inscrit sur la roadmap**. La réflexion Atlas (voir `doc/CHANTIER_ATLAS.md` section 7 et `memory/project_atlas_narratif.md`) répond à la question Q2 par :

> *Découverte par graph community detection (Leiden/Louvain) sur le graphe biparti Perspective ↔ Subject déjà disponible via `TOUCHES_SUBJECT`. Chaque communauté dense = un NarrativeTopic candidat qui a une signature thématique ET un ancrage produit.*

Le graphe biparti a deux types de nœuds : d'un côté les Perspectives (~60), de l'autre les ComparableSubjects (~10-30 attendus). Les arêtes sont les relations `TOUCHES_SUBJECT`. Une communauté dense dans ce graphe = un ensemble de Perspectives qui partagent les mêmes Subjects = un thème transversal ancré sur un produit = un NarrativeTopic.

**Prérequis bloquant** : la dette `ComparableSubject` (cf. `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md`). Tant qu'on n'a qu'un seul Subject, le graphe biparti est trivial et Leiden retombe sur les Perspectives seules (perte totale de l'ancrage produit). Ce blocage est identifié, la réparation passe par brancher le `product_gazetteer` sur le `SubjectResolverV2`.

**Intérêt** : fort. Pas de risque architectural, le graphe biparti est un objet naturel, Leiden y est approprié, et on a déjà décidé que c'est l'approche.

### 3.2. Niveau meso (Perspective) — intéressant mais risqué

C'est la question vraiment neuve que soulève la lecture de l'article : **et si on utilisait Leiden au niveau Perspective aussi**, en remplacement ou en complément de HDBSCAN ?

HDBSCAN actuel = clustering **sémantique** (embeddings E5-large → UMAP 15D → clusters de densité).
Leiden hypothétique = clustering **structurel** sur un graphe de Claims (arêtes = ce qui les lie dans le KG).

**Ce que Leiden pourrait apporter** :

- *Clustering basé sur les connexions réelles du KG*, pas juste la ressemblance textuelle. Deux Claims qui parlent de la même chose en termes différents (par exemple *"Cette transaction est protégée par l'objet S_TABU_NAM"* et *"L'accès aux tables est restreint via les autorisations nommées"*) ne vont pas forcément se ressembler linguistiquement mais peuvent partager beaucoup d'entités et de facets → Leiden les regrouperait, HDBSCAN non.
- *Robustesse aux variations linguistiques et aux paraphrases* : le signal structurel est moins sensible au style d'écriture que le signal sémantique.
- *Multi-résolution native* : en ajustant le paramètre de résolution de Leiden, on peut demander plus ou moins de communautés sans refaire le pipeline.
- *Hiérarchie gratuite* : Leiden peut être appliqué récursivement pour obtenir plusieurs niveaux (c'est ce que fait Microsoft GraphRAG).

**Les caveats sérieux** :

1. **Leiden n'a pas de notion native d'outlier.** HDBSCAN rejette typiquement 20-30% des points comme "noise" si leur densité locale est trop faible. C'est précisément pour cette raison que HDBSCAN a été choisi en Phase B de la refonte Perspective : il évite le bug de la "méga-Perspective hégémonique" qui absorbait tout dans la V1 subject-scoped. Leiden mal paramétré peut reproduire exactement ce pattern — tous les Claims connectés entre eux forment une giant component qui devient une méga-communauté. **C'est le risque numéro 1.**

2. **La qualité du clustering dépend entièrement de la qualité des arêtes.** Sur quel critère relie-t-on deux Claims ?
   - Partage d'au moins 1 Entity → graphe trop dense, giant component
   - Partage d'au moins 3 Entities → probablement bon, à tester
   - Partage d'au moins 1 Facet → signal structurel fort mais rare
   - Relations explicites `CONTRADICTS`/`REFINES`/`SUPPORTS` → graphe trop éparse
   - Combinaison pondérée des trois → plus riche mais plus difficile à régler
   
   **Il n'y a pas de réponse a priori.** C'est exactement ce qu'un probe empirique va nous dire.

3. **Perte du domain-agnostic pur.** HDBSCAN sur embeddings fonctionne dans n'importe quelle langue et n'importe quel domaine sans rien configurer. Leiden sur graphe structurel demande de décider *quelles relations* comptent comme arêtes, ce qui introduit une dépendance au modèle d'extraction et aux conventions du domain pack. Moins portable.

4. **La V2 actuelle fonctionne.** Les tests post-B6/B7 montrent qu'elle trouve 6-7 concepts vs 1-4 pour le RAG baseline sur les questions cross-doc. Ce n'est pas une couche en crise qui cherche désespérément une alternative. C'est une couche qui fonctionne et qu'on pourrait *peut-être* améliorer.

**Mon opinion** : pas de remplacement à court terme. Par contre, un usage **complémentaire** serait potentiellement très intéressant. On pourrait imaginer :

- HDBSCAN reste le clustering principal de Perspective (sémantique, robuste, outlier-aware)
- Un Leiden parallèle sur le graphe structurel produit une *seconde vue* du corpus
- On compare les deux : si elles se recoupent largement, c'est une validation croisée rassurante ; si elles divergent fortement, chaque vue capte des axes que l'autre rate, et on peut les fusionner ou les exposer comme deux types de Perspectives

### 3.3. Niveau atomique (Entity / Claim canonicalisation)

Dernière piste, moins ambitieuse : Leiden sur un graphe Entity ↔ Entity (co-mention dans les mêmes Claims) pour aider à la **canonicalisation d'entités**. Deux entités qui co-apparaissent souvent dans les mêmes contextes sont probablement liées conceptuellement, voire synonymes.

**Utilité réelle** : faible. On a déjà `canonical_aliases` dans le domain pack `enterprise_sap` qui fait ce travail proprement pour les variantes lexicales connues. Leiden ajouterait une couche d'inférence mais au prix d'un risque de sur-normalisation (fusionner des entités voisines mais distinctes, type `S_TABU_NAM` et `S_TABU_LIN`).

**Pas prioritaire.**

---

## 4. Ce qui distingue GraphRAG Microsoft de OSMOSIS aujourd'hui

Au-delà de Leiden lui-même, l'intérêt de lire le papier Microsoft est de se positionner. Voici les différences clés.

### 4.1. Ils n'ont pas d'embeddings sémantiques de qualité sur leurs entités

Le choix Leiden/structurel chez Microsoft est **conditionné** par leur pipeline : ils extraient les entités par LLM directement depuis le texte, ils n'ont pas de `sentence-transformers` type E5 qui leur donne des vecteurs 1024D bien séparés. Ils sont donc *obligés* de passer par la topologie du graphe parce que c'est leur seul signal structurant riche.

**OSMOSIS a une option en plus** : le sémantique (via E5-large) est déjà une dimension de travail. Dans notre contexte, la question n'est pas "Leiden ou pas", c'est **"où est-ce que la structure apporte plus d'info que le sémantique pur"**. La réponse peut très bien être "pour le niveau macro oui, pour le niveau meso non".

### 4.2. Leur hiérarchie est unifiée par un seul algo, la nôtre est hybride

Chez Microsoft, Leiden produit tous les niveaux d'un coup (niveau 0, 1, 2...). C'est élégant et conceptuellement propre.

Chez OSMOSIS, on a :
- Claim = extraction LLM
- Perspective = HDBSCAN sur embeddings
- NarrativeTopic = (futur) Leiden sur graphe biparti

C'est moins élégant mais chaque algo est adapté à la nature de la donnée à son niveau. Leiden unifié supposerait que le même critère de distance fait sens à tous les niveaux, ce qui n'est pas évident dans notre cas (les Claims sont des textes courts et denses sémantiquement, les Perspectives sont des clusters abstraits, les NarrativeTopics sont des thèmes cross-produit).

### 4.3. Nous avons des relations sémantiques typées qu'ils n'ont pas

OSMOSIS a extrait des relations **typées** entre Claims : `CONTRADICTS`, `REFINES`, `SUPPORTS`, `CHAINS_TO`. C'est une richesse structurelle que le GraphRAG Microsoft n'a pas à ce niveau de typage. Ces relations sont actuellement exploitées par les modes `TENSION` et `STRUCTURED_FACT` mais **pas encore par le clustering Perspective**. Un Leiden qui prendrait ces relations comme arêtes pondérées selon leur type serait potentiellement beaucoup plus riche que leur approche.

### 4.4. Le routage question → niveau est plus fin chez nous

Microsoft route par une classification "query-level" simple (atomique vs global). OSMOSIS route via le `strategy_analyzer` (LLM informé par la topologie des preuves) vers 4-5 modes distincts selon le type de structure attendue dans la réponse (direct, tension, perspective, structured_fact, augmented). C'est un routage plus fin, construit empiriquement.

---

## 5. Questions ouvertes

**Q1. Le signal structurel est-il exploitable dans notre corpus ?**
C'est la question qui justifie un probe empirique. On ne sait pas a priori si un graphe Claim ↔ Claim (via Entities partagées) donne des communautés cohérentes ou une giant component inutilisable. Le probe va le dire en une heure de travail.

**Q2. Les clusters structurels recoupent-ils les clusters sémantiques ?**
Si oui → validation croisée, pas besoin de les combiner.
Si non → chaque vue capte des axes différents, potentiellement mergeable ou exposable comme deux types de Perspectives (ex: "Perspective thématique" vs "Perspective technique").

**Q3. Le routage des modes de réponse gagnerait-il à avoir un niveau explicite ?**
Aujourd'hui le `strategy_analyzer` choisit un mode, pas un niveau de granularité. On pourrait imaginer un routage plus explicite : question atomique → claims, question thématique → Perspectives, question globale → NarrativeTopics (mode ATLAS à créer). Mais ça demande que le niveau 2 existe vraiment, donc ça passe après la dette ComparableSubject + l'Atlas narratif.

**Q4. Faut-il encoder les relations typées (CONTRADICTS, REFINES, ...) comme arêtes pondérées dans un futur graphe Leiden ?**
Probablement oui, mais la pondération exacte est un paramètre sensible à valider empiriquement. Un Claim qui en contredit un autre est-il plus ou moins "proche" qu'un Claim qui le raffine ? La réponse dépend du cas d'usage.

**Q5. Dans quel ordre attaquer ?**
Proposition :
1. Probe Leiden sur Claim ↔ Claim (Entities partagées) — 1-2h, pas de risque
2. Fixer la dette ComparableSubject — dépendance dure pour les étapes suivantes
3. Leiden bipartie Perspective ↔ Subject pour NarrativeTopic (déjà décidé)
4. Si le probe (1) est concluant : explorer Leiden complémentaire au niveau Perspective
5. Si (3) et (4) fonctionnent : explorer la Leiden hiérarchique unifiée, mais seulement si on voit un gain clair sur les benchmarks

---

## 6. Ce qu'il ne faut PAS faire

- **Ne pas céder au "tout Leiden" par hype**. L'approche Microsoft est **conditionnée par leurs limitations** (pas d'embeddings de qualité). OSMOSIS a un signal sémantique fort qu'il serait idiot d'abandonner.

- **Ne pas remplacer HDBSCAN à la va-vite**. La V2 fonctionne, les tests post-B6/B7 valident l'approche, et HDBSCAN a la vertu spécifique de rejeter les outliers — ce qui nous a sauvés du bug "méga-Perspective hégémonique" de la V1. Tout remplacement doit d'abord prouver qu'il ne ré-introduit pas ce bug.

- **Ne pas appliquer Leiden sur un graphe trivial**. Tant que la dette ComparableSubject n'est pas fixée, le graphe biparti Perspective ↔ Subject est dégénéré (un seul Subject → toutes les Perspectives connectées au même unique nœud). Faire Leiden dessus maintenant serait une perte de temps.

- **Ne pas oublier l'invariant domain-agnostic**. Si on introduit du clustering structurel, il faut que le critère d'arête soit générique (applicable au pack biomedical comme au pack enterprise_sap) et qu'il se reconfigure via le domain pack, pas dans le code.

---

## 7. Résultats du probe empirique (avril 2026)

Probe exécuté via `benchmark/probes/leiden_claim_probe.py` sur le corpus actuel (15 566 Claims, 60 Perspectives V2 existantes). Graphe Claim ↔ Claim construit avec arête pondérée par le nombre d'entités partagées via la relation `Claim-[:ABOUT]->Entity`. Community detection via Louvain (`networkx.community.louvain_communities`, proxy exploratoire pour Leiden à ce stade). Trois seuils testés.

### 7.1. Données brutes

| `min_shared` | Edges | Giant comp. | Isolés | Communautés | Max cluster | Couverture |
|---:|---:|---:|---:|---:|---:|---:|
| **1** | 764 926 | 9 094 (58.4%) | 5 596 (36.0%) | 41 | **1 441** | 58.4% |
| **2** | 53 889 | 2 593 (16.7%) | 11 380 (73.1%) | 29 | 281 | 16.7% |
| **3** | 5 188 | 172 (1.1%) | 14 129 (90.8%) | 13 | 57 | 1.1% |

Pour référence, **Perspective V2 actuelle** : 60 clusters, max 970, médiane 74, couverture 6 740 claims (43.3%).

### 7.2. Le signal structurel existe, mais il est plus épars que le sémantique

Trois constats solides :

1. **Confirmation du risque méga-cluster à `min_shared=1`**. Le cluster maximal fait 1 441 claims (9.3% du corpus), exactement le pattern "giant community hégémonique" qu'on a identifié comme le risque principal de Leiden dans la section 3.2. C'est empiriquement démontré sur notre corpus. Si on venait à utiliser Leiden au niveau Perspective, `min_shared=1` est **exclu**.

2. **Sweet spot à `min_shared=2`** : 29 communautés, distribution saine (max 281 vs 970 pour Perspective V2 — plus équilibrée !), pas de giant community pathologique. Mais la couverture est faible (16.7%) parce que la plupart des Claims extraits n'ont que 1-3 entités, et le recoupement à ≥2 entités communes est difficile.

3. **Qualitativement, les communautés structurelles sont cohérentes**. Sur les 10 plus grosses communautés à `min_shared=2`, on identifie des axes thématiques réels et exploitables :
   - SAP Marketing Cloud integration (consent records, user SAP_WFRT, business partner replication)
   - NetWeaver ABAP Platform / ABAP authentication stack (SSO, logon tickets, user management)
   - Business Workflow (CA-TS, Manager Self-Service, E-Recruiting partageant le moteur workflow)
   - Logging & tracing ABAP Platform (appraisal documents, performance management)
   - Security topology réseau (Investigative Case Management, Incentive Sales Force, Process Observer)
   - Adobe Document Services / NetWeaver Business Warehouse archive flow
   
   Ce sont des **axes technico-structurels** (quelle techno SAP partage ce Claim avec quel autre) plutôt que des axes thématiques purs comme ceux que produit HDBSCAN sémantique. C'est un signal différent, pas un signal redondant.

### 7.3. Ce que le probe change à la réflexion

**Le probe conforte l'approche HDBSCAN sémantique comme couche principale** :
- Couverture 43.3% vs 16.7% — HDBSCAN capte 2.6x plus de claims
- HDBSCAN ne dépend pas de la qualité des relations extraites (moins de dépendance au pipeline d'extraction)
- HDBSCAN est naturellement domain-agnostic
- Pas de risque méga-cluster à un paramètre raisonnable

**MAIS le probe ouvre une piste de complémentarité non triviale** :

Les 29 communautés Louvain à `min_shared=2` ne sont **probablement pas le même découpage** que les 60 Perspectives V2. Elles sont structurellement organisées (techno/stack commun) là où HDBSCAN est sémantiquement organisé (thème/sujet commun). Deux claims comme :

- *"CA-TS uses authentication mechanisms provided with the SAP NetWeaver platform"*
- *"Process Observer uses the authorization concept provided by the SAP NetWeaver for Application Server ABAP"*

parlent de choses **différentes thématiquement** (time sheet vs process monitoring) mais **identiques structurellement** (tous deux s'appuient sur NetWeaver ABAP auth stack). HDBSCAN les sépare, Louvain les regroupe. Aucun des deux n'a tort — ils captent des dimensions distinctes.

**Gain potentiel exploitable** : sur des questions de type *"quelles sont toutes les briques SAP qui dépendent de NetWeaver ABAP pour l'authentification ?"*, les communautés structurelles pourraient donner de meilleurs résultats que les Perspectives sémantiques, parce que la question porte justement sur la dépendance technique, pas sur le sujet métier.

### 7.4. Le vrai insight surprenant

Le point le moins attendu du probe : **la distribution des tailles de communautés Louvain est plus équilibrée** que celle des Perspectives V2 (max 281 vs 970). La Perspective V2 la plus grosse contient 970 claims, ce qui est énorme et probablement un signe que HDBSCAN laisse encore une forme de sur-concentration dans certains axes. Louvain sur signal structurel n'a pas ce problème (modulo le fait qu'il couvre moins).

**Cela suggère que Louvain pourrait servir à "diagnostiquer" les Perspectives surchargées** : si une Perspective V2 fait 970 claims, peut-être qu'elle agglomère en réalité plusieurs communautés structurelles distinctes qu'il serait utile de scinder. C'est un usage du signal structurel comme **outil de contrôle qualité** du clustering sémantique, pas comme remplacement.

### 7.5. Ce que je conclus

1. **Ne pas remplacer HDBSCAN.** La couche Perspective V2 reste l'approche principale. Confirmé par la couverture largement supérieure.

2. **Leiden pour NarrativeTopic (niveau macro) reste une bonne idée**, mais reste bloqué sur la dette ComparableSubject. Inchangé.

3. **Piste nouvelle : signal structurel comme seconde vue**. Deux usages possibles à explorer ultérieurement, mais sans urgence :
   
   a) **Diagnostic qualité** : lancer Louvain périodiquement et identifier les Perspectives V2 dont les claims se répartissent en plusieurs communautés structurelles distinctes. Ce sont probablement des Perspectives "trop larges" qui gagneraient à être scindées.
   
   b) **Mode de réponse complémentaire** : pour les questions portant explicitement sur les dépendances techniques entre composants SAP ("qu'est-ce qui utilise X ?"), un sous-graphe structurel pourrait donner de meilleurs résultats qu'une Perspective thématique. À valider si on rencontre ce type de question dans les benchmarks.

4. **Abandonner l'idée d'un Leiden hiérarchique unifié remplaçant tout**. La couverture 16.7% vs 43.3% est un verdict empirique : dans OSMOSIS, le sémantique est plus riche que le structurel au niveau atomique. L'approche Microsoft GraphRAG n'est pas directement transposable parce qu'on a un signal en plus qu'eux (les embeddings E5-large), et le probe confirme qu'on aurait tort de l'abandonner.

### 7.6. Limite du probe

Louvain n'est pas Leiden. La différence entre les deux est marginale dans ce contexte (Leiden garantit des communautés "well-connected", Louvain peut produire occasionnellement des communautés bancales), mais elle pourrait jouer sur les bordures. Si on décide de creuser sérieusement une des deux pistes de 7.5.3, il faudra refaire le probe avec `leidenalg` installé. Pour l'instant, le signal est suffisamment clair pour prendre les décisions ci-dessus sans ce raffinement.

---

## 8. Voir aussi

- `doc/ongoing/ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md` — architecture de la couche Perspective V2, historique V1 → V2, pourquoi HDBSCAN a été retenu
- `doc/CHANTIER_ATLAS.md` section 7 — réflexion Atlas narratif, Q2 acte l'usage de Leiden pour NarrativeTopic
- `doc/ongoing/[futur]_DETTE_COMPARABLE_SUBJECT.md` — le blocage qui empêche Leiden bipartie aujourd'hui
- `doc/ongoing/KG_NODES_GLOSSAIRE.md` — cartographie des nodes qu'on pourrait potentiellement faire entrer dans un graphe Leiden
- `benchmark/probes/leiden_claim_probe.py` *(à créer)* — le probe empirique Claim ↔ Claim qui va donner le premier signal
