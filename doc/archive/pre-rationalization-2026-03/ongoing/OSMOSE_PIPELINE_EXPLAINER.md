# OSMOSE — Comment transformer des documents en intelligence exploitable

## L'idée en une phrase

OSMOSE prend des documents — des PDF, des présentations PowerPoint, des fichiers Word, des tableurs Excel — et les transforme en un réseau de connaissances structuré, navigable et interrogeable. Pas un simple moteur de recherche. Un véritable cerveau documentaire.

---

## Le problème que ça résout

Imaginez une entreprise qui a 500 documents techniques sur un sujet. Un consultant arrive et doit répondre à la question : "Est-ce que la fonctionnalité X est compatible avec la version Y du produit Z ?"

Aujourd'hui, il fait quoi ? Il ouvre 15 documents, il fait Ctrl+F, il lit en diagonale, il croise mentalement les informations, et au bout de 2 heures il donne une réponse dont il n'est pas sûr à 100%.

OSMOSE fait ce travail automatiquement. Il lit tous les documents, extrait chaque affirmation, la relie à son contexte, détecte les contradictions entre documents, et construit un graphe de connaissances qu'on peut interroger comme une base de données intelligente.

---

## L'analogie : le bibliothécaire parfait

Imaginez un bibliothécaire extraordinaire. Vous lui donnez une pile de 500 livres sur un sujet.

Ce bibliothécaire va :

1. **Lire chaque livre** et surligner chaque affirmation importante — pas les titres, pas les introductions vagues, mais les faits précis, les chiffres, les règles.

2. **Écrire chaque affirmation sur une fiche bristol** avec, au dos, la référence exacte : quel livre, quelle page, quel paragraphe. Si quelqu'un doute, on peut toujours retrouver la source.

3. **Classer les fiches** par sujet, par produit, par thème. "Cette fiche parle du produit X." "Cette fiche concerne la sécurité." "Cette fiche mentionne la version 2024."

4. **Relier les fiches entre elles.** "Cette fiche précise celle-là." "Attention, ces deux fiches se contredisent — le document A dit oui, le document B dit non."

5. **Ranger tout dans un système** où n'importe qui peut poser une question et obtenir une réponse sourcée, avec les preuves.

C'est exactement ce que fait OSMOSE. Les "fiches bristol", on les appelle des **Claims**. Le système de rangement, c'est le **Knowledge Graph**. Et le bibliothécaire, c'est un pipeline automatisé qui utilise de l'intelligence artificielle.

---

## Le voyage d'un document : étape par étape

### Étape 1 — Le document arrive

Un utilisateur dépose un document dans le système — via l'interface web ou simplement en le glissant dans un dossier surveillé. Ça peut être un PDF de 200 pages, une présentation de 50 slides, un document Word, un tableur Excel.

Un gardien automatique — le Folder Watcher — détecte immédiatement le nouveau fichier et crée un ticket de travail dans une file d'attente. Le document rejoint la queue et attend son tour.

### Étape 2 — Comprendre de quoi parle le document

Avant de plonger dans les détails, le système prend du recul. Il demande à une intelligence artificielle : "De quoi parle ce document ? Quel est son sujet principal ? C'est un document technique ? Marketing ? Juridique ? De quelle époque date-t-il ?"

C'est comme quand vous prenez un livre pour la première fois : vous regardez le titre, la couverture, la table des matières. Vous ne lisez pas encore, vous situez l'ouvrage.

Le résultat : une fiche d'identité du document. Son sujet principal, son type, sa portée temporelle. Cette fiche d'identité va teinter toute la lecture qui suit.

### Étape 3 — Découper en passages

Le document est ensuite découpé en passages — des blocs de texte cohérents. Un paragraphe, une section, un groupe de slides.

Pourquoi ? Parce qu'une affirmation extraite plus tard doit toujours pouvoir être replacée dans son contexte. Si on vous dit "le produit supporte TLS 1.3", vous voulez savoir : c'était dans quel chapitre ? Avant ou après la section sur les limitations ? Le passage, c'est l'ancre de contexte.

### Étape 4 — Extraire les Claims (le cœur du système)

C'est l'étape la plus importante. L'intelligence artificielle lit chaque passage et en extrait des **Claims** — des affirmations atomiques, précises, vérifiables.

Pas des résumés. Pas des synthèses. Des faits bruts.

Par exemple, à partir d'un paragraphe qui dit : "Notre solution supporte TLS 1.2 et TLS 1.3. L'authentification multi-facteur est obligatoire pour les administrateurs. Les données sont chiffrées au repos avec AES-256."

Le système extrait trois claims distinctes :
- "La solution supporte TLS 1.2 et TLS 1.3"
- "L'authentification multi-facteur est obligatoire pour les administrateurs"
- "Les données sont chiffrées au repos avec AES-256"

Chaque claim garde un lien vers le passage source — la citation exacte, mot pour mot. C'est la preuve. On ne fait jamais confiance à la claim seule, on peut toujours vérifier dans le document original.

Pour un document de 50 pages, le système extrait typiquement entre 100 et 300 claims.

### Étape 5 — Identifier les entités

Maintenant que les claims sont extraites, le système identifie les **entités** mentionnées. Une entité, c'est un "truc" reconnaissable : un produit (SAP S/4HANA), un concept (chiffrement AES-256), un acteur (administrateur), un standard (ISO 27001).

Le système utilise des techniques déterministes — pas besoin d'IA pour cette partie. Il repère les termes en majuscules, les acronymes, les noms propres, les patterns syntaxiques ("X permet de...", "X est compatible avec...").

### Étape 6 — Tisser les liens

C'est ici que la magie opère. Le système crée des **relations** :

- **Claim → Entité** : "Cette claim parle de TLS 1.3" (relation ABOUT)
- **Claim → Passage** : "Cette claim est prouvée par ce passage" (relation SUPPORTED_BY)
- **Claim → Facette** : "Cette claim concerne le thème Sécurité" (navigation thématique)

À ce stade, les claims ne sont plus des fiches isolées. Elles sont connectées entre elles et aux entités dans un réseau — le Knowledge Graph.

### Étape 7 — Enrichissement spécialisé (Domain Packs)

Voici quelque chose d'unique. Le système de base est volontairement généraliste — il ne connaît aucun domaine métier spécifique. Il fonctionne aussi bien pour des documents SAP que pour des articles de recherche biomédicale ou des textes juridiques.

Mais certains domaines ont des vocabulaires très spécifiques. En biomédecine, par exemple, des termes comme "sepsis", "procalcitonin", "IL-6" sont des concepts cruciaux, mais ils sont écrits en minuscules — le détecteur générique les rate parce qu'il cherche surtout des termes capitalisés.

C'est là qu'interviennent les **Domain Packs**. Ce sont des modules enfichables — comme des extensions pour un navigateur web. Chaque pack est un petit conteneur indépendant qui embarque un modèle d'intelligence artificielle spécialisé dans un domaine.

Le pack biomédical, par exemple, contient un modèle entraîné sur des millions d'articles scientifiques. Il reconnaît automatiquement les noms de molécules, de maladies, de biomarqueurs, sans qu'on ait besoin de lui fournir une liste.

Le principe est simple et fondamental : **le pack propose, le cœur décide**. Le pack soumet des candidats entités, et le cœur du système les valide avec les mêmes règles que pour toutes les autres entités. Pas de passe-droit. Pas de porte dérobée. Le pack enrichit la détection, mais il ne change jamais les règles du jeu.

Un administrateur peut activer ou désactiver un pack en un clic. L'activer démarre son conteneur. Le désactiver l'arrête et libère les ressources. On peut même installer de nouveaux packs en uploadant un simple fichier dans l'interface d'administration — comme installer une application sur un téléphone.

### Étape 8 — Regrouper les claims similaires

Quand on importe 50 documents sur le même sujet, il est fréquent que plusieurs documents disent la même chose avec des mots différents. "TLS 1.3 est supporté" dans un document, "Le système prend en charge TLS version 1.3" dans un autre.

Le système détecte ces doublons sémantiques et les regroupe en **clusters**. Un cluster dit : "Ces 4 claims, issues de 3 documents différents, expriment la même information."

C'est puissant pour deux raisons : ça évite la redondance dans les résultats de recherche, et ça donne une mesure de confiance — si 4 documents disent la même chose, c'est probablement vrai.

### Étape 9 — Détecter les relations entre claims

Le système va plus loin. Il compare les claims entre elles et détecte des relations :

- **Contradiction** : Le document A dit "TLS 1.2 est obsolète", le document B dit "TLS 1.2 est toujours supporté". Le système signale : attention, ces deux claims se contredisent.

- **Précision** : Le document A dit "Le chiffrement est AES", le document B dit "Le chiffrement est AES-256 en mode GCM". La deuxième claim précise la première.

- **Nuance** : "L'authentification MFA est obligatoire" et "L'authentification MFA est obligatoire sauf pour les comptes de service". La deuxième claim nuance la première.

Ces relations sont cruciales. Dans un corpus de 500 documents qui évoluent sur plusieurs années, les contradictions sont inévitables. Le système les détecte au lieu de les ignorer.

### Étape 10 — Persister dans le Knowledge Graph

Tout est sauvegardé dans deux bases de données complémentaires :

- **Neo4j** — le Knowledge Graph. C'est une base de données en graphe : des nœuds (claims, entités, passages, documents) reliés par des relations (ABOUT, SUPPORTED_BY, CONTRADICTS...). On peut naviguer de lien en lien, comme on suit des fils dans une toile d'araignée.

- **Qdrant** — la base vectorielle. Chaque claim est transformée en un vecteur mathématique qui capture son sens. Ça permet la recherche sémantique : on pose une question en langage naturel, et le système retrouve les claims les plus pertinentes, même si les mots exacts ne correspondent pas.

---

## Après l'import : les opérations manuelles

Le pipeline automatique s'arrête là. Le document est lu, découpé, extrait, relié, persisté. Mais trois opérations complémentaires peuvent être lancées manuellement par l'administrateur :

### Le ménage du Knowledge Graph (KG Hygiene)

Au fil des imports, le Knowledge Graph accumule des imperfections. Des entités en doublon ("SAP S/4HANA" et "S4HANA" sont la même chose). Des entités parasites (le mot "Table" extrait comme entité alors que c'était juste un titre de tableau).

L'outil KG Hygiene est un nettoyeur autonome qui fonctionne en trois couches :
- **Couche 1** : Normalisation des noms (majuscules, accents, variantes orthographiques)
- **Couche 2** : Détection des doublons sémantiques (deux entités qui désignent le même concept)
- **Couche 3** : Cohérence structurelle (entités orphelines, relations aberrantes)

L'outil propose des actions correctives. L'administrateur valide ou rejette chaque proposition. Rien n'est fait dans le dos de l'humain.

### Le retraitement Domain Pack

Si un administrateur active un Domain Pack après avoir déjà importé des documents, il peut lancer un retraitement rétroactif. Le système reprend les claims qui n'ont pas encore d'entités associées et les soumet au pack spécialisé. Pas besoin de ré-importer les documents.

### La génération Wiki

À partir du Knowledge Graph construit, le système peut générer des articles de type encyclopédique. L'administrateur sélectionne un concept et le système compile automatiquement toutes les claims associées, croisées depuis les différents documents, pour produire un article synthétique avec sources.

---

## Le mode Turbo : Burst Mode

Tout ce qui précède fonctionne avec des services d'IA dans le cloud — OpenAI, Anthropic. Mais quand on doit importer 200 documents d'un coup, les appels cloud deviennent lents et coûteux.

Le Mode Burst résout ce problème. Il démarre une machine GPU dans le cloud (une instance Amazon EC2 Spot, peu coûteuse) avec un modèle d'IA embarqué. Toutes les étapes qui nécessitent de l'IA sont alors routées vers cette machine locale au lieu du cloud.

Résultat : traitement 10 fois plus rapide, coût divisé par 5. Quand l'import massif est terminé, la machine GPU est éteinte automatiquement.

C'est comme avoir un traducteur freelance qu'on appelle quand on a un gros lot de documents à traduire, au lieu de passer par une agence au cas par cas.

---

## Ce qui rend OSMOSE unique

### La souveraineté des preuves

Chaque information dans le système est tracée jusqu'à sa source verbatim dans le document original. On ne fait jamais confiance à une extraction "parce que l'IA l'a dit". On peut toujours vérifier.

### La détection de contradictions

Les systèmes classiques de recherche documentaire vous donnent la réponse la plus pertinente. Ils ne vous disent pas qu'un autre document dit le contraire. OSMOSE détecte et signale ces contradictions.

### L'architecture modulaire

Le cœur est généraliste. Les packs spécialisés sont enfichables. Pas besoin de modifier le système pour l'adapter à un nouveau domaine — on branche un pack.

### La rejouabilité

Tout est rejouable. Si on active un nouveau pack, on peut enrichir le corpus existant sans ré-importer. Si on corrige une règle de nettoyage, on peut la rejouer sur tout le graphe. Le système est conçu pour évoluer sans perdre le travail déjà fait.

---

## En résumé visuel

```
Documents (PDF, PPTX, DOCX, Excel)
        │
        ▼
   File d'attente Redis
        │
        ▼  (optionnel: Mode Burst = GPU locale)
   ┌────────────────────────────┐
   │   PIPELINE AUTOMATIQUE     │
   │                            │
   │   Comprendre le document   │
   │        ↓                   │
   │   Découper en passages     │
   │        ↓                   │
   │   Extraire les claims      │  ← IA
   │        ↓                   │
   │   Identifier les entités   │  ← déterministe
   │        ↓                   │
   │   Tisser les liens         │
   │        ↓                   │
   │   Enrichir (Domain Packs)  │  ← container spécialisé
   │        ↓                   │
   │   Regrouper les doublons   │
   │        ↓                   │
   │   Détecter contradictions  │
   │        ↓                   │
   │   Sauvegarder dans le KG   │
   └────────────────────────────┘
        │
        ▼
   Knowledge Graph (Neo4j + Qdrant)
        │
        ▼  (manuel, par l'admin)
   ┌────────────────────────────┐
   │   OPÉRATIONS POST-IMPORT   │
   │                            │
   │   Ménage KG (Hygiene)      │
   │   Retraitement Domain Pack │
   │   Génération Wiki          │
   └────────────────────────────┘
```

---

## Chiffres clés sur un corpus réel

Sur un corpus de recherche biomédicale (135 documents scientifiques) :

- **29 967 claims** extraites automatiquement
- **7 841 entités** identifiées
- **3 186 clusters** de claims similaires inter-documents
- **206 sujets** résolus (SubjectAnchors)
- Taux de couverture entités : **43%** des claims reliées à au moins une entité (le Domain Pack biomédical vise à porter ce chiffre à **70-80%**)
- Chaque claim est traçable jusqu'à sa citation verbatim dans le document source
