# OSMOSE vs. les alternatives — Pourquoi un Knowledge Graph documentaire et pas un simple RAG ?

## La question légitime

Quand on présente OSMOSE et son pipeline d'extraction, la réaction la plus fréquente est :

> "C'est intéressant, mais pourquoi ne pas simplement utiliser un RAG ? Je découpe mes documents en chunks, je les vectorise, je branche un ChatGPT dessus, et en une demi-journée c'est réglé."

C'est une question excellente. Et honnêtement, pour certains cas d'usage, un RAG suffit. Mais pour d'autres — et ce sont les cas qui comptent le plus en entreprise — un RAG seul est dangereusement insuffisant. Pas parce qu'il ne trouve pas l'information, mais parce qu'il ne sait pas qu'il donne une mauvaise réponse.

Ce document explique pourquoi, en comparant OSMOSE aux principales approches du marché.

---

## Les quatre familles de solutions

Avant de comparer, clarifions les approches existantes. Il y en a quatre grandes familles, et chacune représente une philosophie différente de la gestion documentaire.

### 1. La recherche classique (SharePoint, Confluence, Google Drive)

C'est ce que tout le monde utilise. On stocke des fichiers, on fait une recherche par mots-clés, on obtient une liste de documents.

**L'analogie** : c'est une bibliothèque avec un catalogue par mots-clés. Vous cherchez "politique de sécurité" et vous obtenez 47 documents. À vous de les ouvrir un par un pour trouver la bonne information, la bonne version, la phrase qui répond à votre question.

**Le problème** : ça retrouve des documents, pas des réponses. Et surtout, ça ne vous dit jamais que le document de 2023 contredit celui de 2024 sur le même sujet.

### 2. Le RAG (Retrieval-Augmented Generation)

Le RAG est l'approche à la mode depuis 2023. Le principe : on découpe les documents en morceaux (chunks), on transforme chaque morceau en vecteur mathématique qui capture son sens, et quand un utilisateur pose une question, on retrouve les morceaux les plus proches sémantiquement, on les injecte dans le prompt d'un grand modèle de langage, et le modèle génère une réponse.

**L'analogie** : c'est comme donner à un étudiant brillant 5 pages arrachées au hasard d'un livre de 500 pages, et lui demander de répondre à votre question. Il est intelligent, il fait de son mieux, et la plupart du temps sa réponse est plausible.

**Ce que le RAG fait bien** :
- Retrouver des passages pertinents par similarité sémantique
- Générer des réponses fluides en langage naturel
- Se mettre en place rapidement (quelques heures)
- Coûter peu en infrastructure

**Ce que le RAG ne fait pas** :
- Il ne sait pas que deux chunks viennent du même sujet traité différemment dans deux documents
- Il ne détecte pas les contradictions entre documents
- Il ne comprend pas l'évolution temporelle d'une information
- Il ne peut pas dire "cette information a été remplacée par une version plus récente"
- Il ne traçe pas la provenance de manière fiable — il "hallucine" parfois des sources
- Il ne distingue pas un fait d'une opinion, une prescription d'une observation

### 3. Le GraphRAG

Le GraphRAG est une évolution du RAG proposée notamment par Microsoft en 2024. L'idée : avant de faire la recherche vectorielle, on construit un graphe de connaissances automatiquement à partir des documents. Ensuite, la recherche utilise à la fois les vecteurs et la structure du graphe pour donner de meilleures réponses.

**L'analogie** : c'est comme donner à l'étudiant non seulement les 5 pages arrachées, mais aussi une carte mentale du livre. Il sait que le chapitre 3 parle de sécurité, que la sécurité est liée au chapitre 7 sur la conformité, etc.

**Ce que le GraphRAG améliore par rapport au RAG** :
- Meilleure compréhension des relations entre concepts
- Réponses plus globales (pas limitées à un seul chunk)
- Capacité à répondre à des questions de synthèse ("quels sont les thèmes principaux du corpus ?")

**Ce que le GraphRAG ne fait toujours pas** :
- Son graphe est construit automatiquement par un LLM — il est approximatif, non vérifié, non gouverné
- Il ne distingue pas les sources : une phrase dans un email vaut autant qu'une phrase dans un rapport certifié
- Il n'a aucune notion de contradiction, de version, d'obsolescence
- Il n'a pas de gouvernance : personne ne valide ce qui entre dans le graphe
- Si on pose la même question deux fois, on peut obtenir deux graphes différents

### 4. OSMOSE — Le Knowledge Graph documentaire gouverné

OSMOSE représente une quatrième approche, fondamentalement différente.

**L'analogie** : au lieu de donner des pages arrachées à un étudiant, on emploie un bibliothécaire expert qui lit intégralement chaque document, extrait chaque fait vérifiable sur une fiche bristol avec sa source, relie les fiches entre elles, détecte les contradictions, et construit un fichier ordonné. Quand vous posez une question, il ne cherche pas dans les documents — il cherche dans ses fiches, et chaque fiche pointe vers sa preuve.

---

## La comparaison concrète : un scénario réel

Prenons un cas concret pour illustrer les différences. Une entreprise pharmaceutique a 135 articles scientifiques sur le thème des biomarqueurs d'infection. Un médecin pose la question :

> "Quel biomarqueur est le plus fiable pour diagnostiquer une infection bactérienne aux urgences, et y a-t-il des contradictions entre les études ?"

### Ce que fait la recherche classique

Elle retourne 23 documents contenant le mot "biomarqueur" et "infection". Le médecin doit lire les 23 documents, repérer les passages pertinents, croiser mentalement les résultats, et noter les contradictions lui-même.

Temps : 3 à 6 heures. Fiabilité : dépend de l'attention du médecin.

### Ce que fait le RAG

Il retrouve 5 chunks pertinents, les injecte dans GPT-4, et génère une réponse :

> "La CRP et l'IL-6 sont considérées comme les biomarqueurs les plus fiables pour diagnostiquer une infection bactérienne aux urgences, avec des valeurs prédictives positives élevées."

C'est correct... mais incomplet et potentiellement trompeur. Le RAG a peut-être ignoré l'article qui dit que la PCT est supérieure à la CRP dans certains contextes. Il ne sait pas que deux études se contredisent sur les seuils optimaux. Il ne peut pas dire "3 études sur 5 convergent, mais 2 donnent des résultats différents pour les patients sous immunosuppresseurs".

Et surtout : si on lui repose la question, il peut donner une réponse différente si le retrieval ramène d'autres chunks.

### Ce que fait le GraphRAG

Il construit un graphe global des concepts et retrouve que CRP, IL-6, PCT et calprotectine sont liés au concept "diagnostic infection". Sa réponse est plus structurée, mentionne les différents biomarqueurs et leurs relations.

Mais il ne peut toujours pas dire qu'un article contredit un autre. Son graphe est une approximation statistique, pas un inventaire factuel. Il n'a pas de notion de claim vérifiable.

### Ce que fait OSMOSE

OSMOSE a extrait 29 967 claims des 135 articles. Pour cette question, il retrouve :

- 47 claims mentionnant les biomarqueurs CRP, IL-6, PCT et calprotectine dans un contexte de diagnostic d'infection aux urgences
- 12 claims regroupées en 4 clusters (convergences inter-études)
- 3 paires de claims contradictoires clairement identifiées, avec les sources exactes
- Un axe temporel montrant l'évolution des recommandations entre 2019 et 2024

La réponse qu'il peut fournir :

> "Sur 135 études, CRP et IL-6 sont les biomarqueurs les plus évalués pour le diagnostic d'infection aux urgences. 8 études convergent sur la supériorité de leur combinaison (PPV 95%, NPV 90%). Cependant, 2 études contredisent ce consensus : l'étude PMC8234567 montre que PCT est supérieur à CRP dans les populations sous corticothérapie, et l'étude PMC9345678 rapporte une performance dégradée de l'IL-6 au-delà de 24h post-admission. Chaque affirmation est liée à sa citation verbatim dans le document source."

Temps pour le médecin : 30 secondes de lecture. Fiabilité : chaque fait est traçable et vérifiable.

---

## Les cinq différences fondamentales

### 1. L'unité de connaissance

| Approche | Unité | Problème |
|----------|-------|----------|
| Recherche classique | Le document | Trop gros — un document de 200 pages contient 300 informations distinctes |
| RAG | Le chunk (morceau de texte) | Arbitraire — un chunk peut couper une idée en deux ou mélanger deux idées |
| GraphRAG | Le triplet (entité-relation-entité) | Trop schématique — "CRP → diagnostique → infection" perd toute nuance |
| **OSMOSE** | **La claim (assertion documentée)** | **Précise, atomique, sourcée, vérifiable** |

La claim est l'unité fondamentale d'OSMOSE. C'est une assertion précise extraite d'un document, liée à sa citation verbatim. "La combinaison CRP et IL-6 atteint une valeur prédictive positive de 95% pour l'infection chez les patients avec qSOFA ≥ 2." C'est un fait, pas un morceau de texte.

### 2. La traçabilité

Le RAG vous donne une réponse et cite vaguement "d'après le document X". Mais il ne cite pas la phrase exacte, et parfois il invente la source — c'est ce qu'on appelle l'hallucination de citation.

OSMOSE ne peut pas halluciner une source. Chaque claim contient un champ "verbatim_quote" qui est la citation exacte, copiée mot pour mot, du passage du document original. La claim est reliée à son passage par une relation SUPPORTED_BY. On peut remonter du fait au document en un clic.

C'est la différence entre un journaliste qui dit "des études montrent que..." et un chercheur qui écrit "Smith et al. (2023, p. 47) rapportent que...". Le premier est plausible, le second est vérifiable.

### 3. La détection de contradictions

C'est peut-être la différence la plus importante et la plus sous-estimée.

Un RAG, quand il retrouve deux chunks qui se contredisent, ne le sait pas. Il choisit celui qui est le plus proche sémantiquement de la question, et l'utilise pour générer sa réponse. Il ne vous alerte jamais : "Attention, il y a un désaccord dans vos documents."

OSMOSE, grâce à son pipeline de détection de relations, identifie explicitement les contradictions. Il crée une relation CONTRADICTS entre les deux claims, avec un score de confiance et une justification. Quand vous posez une question, le système ne choisit pas silencieusement une version — il vous présente le désaccord.

Dans un contexte médical, juridique ou réglementaire, ignorer une contradiction peut avoir des conséquences graves. Imaginez un système qui vous dit avec assurance "la posologie recommandée est de 500mg" alors qu'un document plus récent la modifie à 250mg. Un RAG peut faire cette erreur. OSMOSE signale la contradiction.

### 4. L'intelligence cross-document

Un RAG travaille chunk par chunk. Chaque chunk est indépendant. Le RAG ne sait pas que le chunk 347 du document A et le chunk 12 du document B parlent du même concept avec des conclusions différentes.

OSMOSE construit un graphe global. Les claims sont reliées aux mêmes entités, regroupées en clusters inter-documents, positionnées sur des axes temporels. On peut naviguer dans le graphe : "Montre-moi toutes les claims sur la CRP, groupées par année, avec les contradictions signalées."

C'est la différence entre avoir 500 documents dans un tiroir et avoir un dossier thématique organisé avec un sommaire, des renvois croisés et des notes signalant les points de désaccord.

### 5. La gouvernance et la qualité

Un RAG est une boîte noire. On met des documents dedans, on récupère des réponses. Si un document contient une erreur, le RAG la propage sans broncher. Si un mauvais chunk est retrouvé, la réponse est mauvaise et personne ne le sait.

OSMOSE a un système de gouvernance explicite :
- Les entités sont validées et canonicalisées (pas de doublons silencieux)
- Le KG Hygiene détecte et corrige les anomalies
- Un administrateur peut valider, rejeter, ou corriger les assertions
- Chaque modification est tracée et réversible
- Les Domain Packs proposent, le cœur décide — jamais de porte dérobée dans la qualité

---

## Quand utiliser quoi ?

Il ne s'agit pas de dire qu'OSMOSE est toujours meilleur. Chaque outil a son créneau.

### Utilisez un RAG simple quand :

- Vous avez une petite base documentaire (moins de 50 documents)
- Les documents ne se contredisent pas entre eux
- Vous avez besoin de réponses rapides sur des questions simples
- La traçabilité exacte n'est pas critique
- Les documents sont stables (pas de versioning)
- Vous acceptez un taux d'erreur de 10-15% sur les réponses

Le RAG est rapide à mettre en place, peu coûteux, et suffisant pour beaucoup de cas d'usage internes informels.

### Utilisez un GraphRAG quand :

- Vous avez besoin de réponses qui synthétisent plusieurs documents
- Vous voulez comprendre la structure thématique de votre corpus
- La qualité des réponses doit être meilleure qu'un RAG simple
- Mais vous n'avez pas besoin de traçabilité garantie ni de détection de contradictions

### Utilisez OSMOSE quand :

- Votre corpus est volumineux (centaines ou milliers de documents) et évolue dans le temps
- Les documents se contredisent, se complètent, s'annulent — et il faut le savoir
- La traçabilité est non négociable : chaque réponse doit être prouvable par une citation exacte
- Vous êtes dans un domaine réglementé (santé, finance, juridique, conformité) où une erreur a des conséquences
- Vous avez besoin de comparer des versions, suivre l'évolution d'un concept, détecter les obsolescences
- Plusieurs équipes doivent travailler sur le même corpus avec une vision partagée et gouvernée
- Vous voulez aller au-delà de la simple recherche : naviguer dans la connaissance, pas juste la retrouver

---

## Le coût de la simplicité

Le RAG est séduisant par sa simplicité. Mais cette simplicité a un coût caché.

### Le coût de la non-détection

Quand un RAG vous donne une réponse incorrecte, vous ne le savez pas. La réponse est formulée avec assurance, dans un français impeccable, avec parfois une fausse citation. Vous faites confiance. Vous prenez une décision basée sur cette réponse. Et trois mois plus tard, vous découvrez que l'information était obsolète, contredite par un document plus récent que le RAG a ignoré.

Ce coût n'apparaît pas dans le budget de mise en place. Il apparaît dans les décisions erronées, les non-conformités, les audits qui révèlent des incohérences.

### Le coût de la non-gouvernance

Un RAG n'a pas de mémoire organisée. Chaque requête est indépendante. On ne peut pas dire "supprime cette information erronée du système". On ne peut pas dire "marque cette version comme obsolète". On ne peut pas faire d'audit de qualité sur les connaissances extraites, parce qu'il n'y a pas de connaissances extraites — il n'y a que des chunks et des vecteurs.

### Le coût de la non-scalabilité intellectuelle

Avec 50 documents, un RAG fonctionne bien. Avec 500, il commence à ramener des chunks non pertinents. Avec 5 000, la qualité se dégrade significativement parce que l'espace vectoriel devient bruité — trop de chunks similaires, trop d'ambiguïtés non résolues.

OSMOSE, au contraire, s'améliore avec le volume. Plus il y a de documents sur le même sujet, plus les clusters sont riches, plus les contradictions sont détectées, plus les axes d'applicabilité sont précis. Le graphe de connaissances devient plus intelligent avec chaque document ajouté.

---

## En résumé

| Critère | RAG | GraphRAG | OSMOSE |
|---------|-----|----------|--------|
| **Mise en place** | Quelques heures | Quelques jours | Quelques semaines |
| **Unité de connaissance** | Chunk de texte | Triplet de graphe | Claim documentée |
| **Traçabilité** | Approximative | Approximative | Exacte (verbatim) |
| **Contradictions** | Non détectées | Non détectées | Détectées et signalées |
| **Cross-document** | Non | Partiel | Complet |
| **Gouvernance** | Aucune | Aucune | Validations, rollback, audit |
| **Scalabilité** | Se dégrade | Correcte | S'améliore avec le volume |
| **Domaines spécialisés** | Même traitement pour tout | Même traitement pour tout | Domain Packs enfichables |
| **Coût erreur** | Invisible (hallucinations) | Réduit mais présent | Minimisé (preuves) |
| **Cas d'usage idéal** | FAQ interne, support client | Synthèse thématique | Conformité, recherche, veille critique |

La question n'est pas "est-ce que c'est plus complexe ?" — oui, ça l'est. La question est "est-ce que la complexité du problème justifie la complexité de la solution ?" Et quand vos documents peuvent se contredire, quand une erreur a des conséquences, quand vous avez besoin de preuves et pas juste de réponses plausibles — alors oui, un bibliothécaire expert vaut mieux qu'un étudiant brillant avec des pages arrachées.
