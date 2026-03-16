# OSMOSE — Ce qu'on peut faire au quotidien avec un Knowledge Graph documentaire

## Introduction

Les deux premiers documents expliquaient comment OSMOSE construit son Knowledge Graph et pourquoi cette approche est plus robuste qu'un RAG classique. Mais la vraie question qu'un utilisateur se pose est plus terre-à-terre :

> "OK, j'ai mis mes 200 documents dans le système. Et maintenant ? Qu'est-ce que je fais avec ça concrètement, demain matin, à mon bureau ?"

Ce document présente les usages concrets — ceux qui existent déjà et ceux qui deviennent possibles — en les illustrant par des scénarios du quotidien.

---

## Usage 1 — Poser une question et obtenir une réponse sourcée

### Le scénario

Un consultant prépare une réunion client. Il doit répondre rapidement à la question : "Est-ce que notre solution supporte le chiffrement de bout en bout pour les données en transit ?"

### Ce qu'il fait avec OSMOSE

Il tape sa question dans le chat. Le système ne cherche pas dans les documents — il cherche dans les claims. En une seconde, il obtient :

- 3 claims pertinentes, issues de 2 documents différents
- Chaque claim avec sa citation exacte dans le document source
- Un indicateur : les 3 claims convergent (pas de contradiction)
- Les entités liées : "TLS 1.3", "chiffrement AES-256", "données en transit"

Le consultant copie la réponse dans sa présentation. Si le client demande "d'où vient cette information ?", il peut cliquer et retrouver la phrase exacte dans le document d'origine, à la page près.

### Pourquoi c'est différent d'un RAG

Avec un RAG, le consultant aurait obtenu une réponse fluide mais sans garantie de source exacte. Et si deux documents se contredisent sur le sujet, le RAG en aurait choisi un silencieusement. Avec OSMOSE, la contradiction serait signalée.

---

## Usage 2 — Vérifier un texte avant publication

### Le scénario

L'équipe marketing a rédigé une fiche produit de 2 pages. Avant publication, le responsable technique veut vérifier que chaque affirmation est correcte et cohérente avec la documentation technique.

### Ce qu'il fait avec OSMOSE

Il colle le texte dans l'outil de vérification. Le système découpe automatiquement le texte en assertions, puis confronte chacune au Knowledge Graph :

- "Le produit supporte TLS 1.3" → **Confirmé** (3 sources concordantes)
- "Le déploiement prend moins de 2 heures" → **Non trouvé** (aucune claim ne mentionne ce délai)
- "Compatible avec toutes les versions de Windows" → **Contredit** (une claim indique "Windows 10 et supérieur uniquement")

Le résultat est un rapport assertion par assertion, avec un code couleur : vert (confirmé), orange (non vérifié), rouge (contredit). Chaque verdict est accompagné des sources.

### Pourquoi c'est puissant

Sans cet outil, la vérification prend 2 heures de relecture croisée de documents. Avec OSMOSE, c'est 30 secondes. Et surtout, un humain peut rater une contradiction noyée dans un document de 150 pages. Le système, lui, a tout indexé.

---

## Usage 3 — Générer un article de synthèse (Atlas / Wiki)

### Le scénario

Un chef de projet rejoint une équipe qui travaille sur un sujet depuis 2 ans. Il y a 80 documents — des rapports, des présentations, des notes techniques. Il a besoin de comprendre rapidement le sujet sans tout lire.

### Ce qu'il fait avec OSMOSE

Il va sur l'Atlas — une encyclopédie générée automatiquement à partir du Knowledge Graph. Il cherche le concept qui l'intéresse, par exemple "procalcitonin" ou "SAP BTP".

Le système a déjà compilé un article structuré :

- **Définition** : ce que c'est, basé sur les claims extraites de tous les documents
- **Contexte d'utilisation** : dans quels contextes ce concept apparaît
- **Évolution temporelle** : comment les informations ont changé au fil des documents
- **Points de désaccord** : les contradictions entre sources, clairement signalées
- **Sources** : chaque paragraphe est relié aux claims d'origine

C'est une synthèse vivante — elle se met à jour quand de nouveaux documents sont importés. Pas une synthèse statique qu'il faudrait réécrire manuellement.

### Pourquoi c'est unique

Aucun RAG ne peut faire ça. Un RAG répond à une question ponctuelle. Il ne construit pas une vue consolidée, sourcée et contradictions-aware d'un concept à travers 80 documents.

---

## Usage 4 — Détecter les évolutions et les obsolescences

### Le scénario

Une entreprise édite des rapports annuels sur la satisfaction client. Le rapport 2022 dit "le taux de rétention est de 87% calculé selon la méthode A". Le rapport 2023 dit "le taux de rétention est de 91% calculé selon la méthode B". Le rapport 2024 ne mentionne plus de taux.

Un auditeur demande : "Quel est le taux de rétention actuel et comment a-t-il été calculé ?"

### Ce qu'il fait avec OSMOSE

Il cherche "taux de rétention" dans le système. Le Knowledge Graph lui montre :

- **Claim 2022** : "Le taux de rétention est de 87% (méthode A)" → source : rapport 2022, page 14
- **Claim 2023** : "Le taux de rétention est de 91% (méthode B)" → source : rapport 2023, page 8
- **Relation** : La claim 2023 REFINES la claim 2022 (précision/mise à jour)
- **Alerte** : La méthode de calcul a changé entre 2022 et 2023 — les chiffres ne sont pas directement comparables
- **Absence** : Aucune claim sur le taux de rétention dans les documents 2024

L'auditeur voit immédiatement que les chiffres ne sont pas comparables, que la méthode a changé, et qu'il n'y a plus de données récentes. En 10 secondes, il a une vue que 3 heures de lecture n'auraient peut-être pas fournie aussi clairement.

---

## Usage 5 — Explorer les connexions cachées

### Le scénario

Un chercheur travaille sur les biomarqueurs d'infection. Il connaît bien la CRP et la PCT. Mais y a-t-il d'autres concepts liés qu'il n'a pas encore explorés ?

### Ce qu'il fait avec OSMOSE

Il utilise le module de découverte. Le système analyse le graphe et lui montre :

- **Concepts-ponts** : des entités qui relient des clusters de claims qu'il n'aurait pas connectés. Par exemple, le concept "gut microbiota" apparaît dans des claims liées à la fois aux biomarqueurs d'infection et aux traitements immunosuppresseurs — une connexion non évidente à la lecture des articles individuels.
- **Signaux faibles** : des concepts mentionnés dans peu de documents mais avec une fréquence croissante. "Calprotectin" apparaît dans 3 articles récents comme biomarqueur alternatif — un signal émergent.
- **Trous structurels** : des zones du graphe où on s'attendrait à trouver des connexions mais il n'y en a pas. "Aucune étude dans le corpus ne relie directement PCT et population pédiatrique" — une lacune identifiable.

### Pourquoi c'est différent

Un moteur de recherche, même sémantique, ne répond qu'aux questions qu'on lui pose. OSMOSE peut révéler des connexions qu'on n'avait pas pensé à chercher, parce qu'il a une vue structurelle globale du corpus.

---

## Usage 6 — Préparer une réponse à un appel d'offres

### Le scénario

L'entreprise reçoit un appel d'offres avec 150 questions techniques. "Supportez-vous le SSO ?" "Quel est votre PRA ?" "Êtes-vous certifiés ISO 27001 ?"

### Ce qu'il fait avec OSMOSE

Pour chaque question de l'appel d'offres, le système recherche automatiquement dans le Knowledge Graph les claims pertinentes. Pour la question "Supportez-vous le SSO ?", il trouve :

- "Le système supporte SAML 2.0 et OpenID Connect pour l'authentification unique" (source : doc technique v4.2, page 23)
- "L'intégration SSO est disponible pour Azure AD, Okta et Ping Identity" (source : guide intégration, page 7)

L'opérateur obtient une réponse pré-remplie avec sources. Il valide, ajuste le ton, et passe à la question suivante. Un appel d'offres qui prenait 2 semaines peut être traité en 2 jours.

---

## Usage 7 — Onboarding d'un nouveau collaborateur

### Le scénario

Un nouveau consultant rejoint l'équipe. Il doit se mettre à niveau sur un écosystème technique complexe en quelques jours.

### Ce qu'il fait avec OSMOSE

Au lieu de lui donner une pile de 50 documents en lui disant "lis ça", on lui donne accès à l'Atlas. Il navigue par concept :

- Il clique sur le produit principal → article synthétique avec définition, fonctionnalités clés, limitations connues
- Il explore les concepts liés → chaque concept a son propre article
- Il voit les contradictions → "Attention, la doc marketing dit X mais la doc technique dit Y"
- Il peut poser des questions en langage naturel et obtenir des réponses sourcées

En 2 jours, il a une compréhension structurée que 2 semaines de lecture désordonnée n'auraient pas fournie. Et surtout, il sait où sont les zones d'ombre et les contradictions — il ne part pas avec de fausses certitudes.

---

## Usage 8 — Audit de conformité documentaire

### Le scénario

Un auditeur externe doit vérifier que la documentation de l'entreprise est cohérente et à jour. "Vos documents disent-ils tous la même chose sur la politique de conservation des données ?"

### Ce qu'il fait avec OSMOSE

Il cherche "conservation des données" dans le Knowledge Graph. Le système lui montre :

- 12 claims provenant de 7 documents différents qui mentionnent la conservation des données
- 3 clusters de claims convergentes (les documents sont d'accord)
- 1 contradiction signalée : le document RH dit "conservation 5 ans" et le document IT dit "conservation 3 ans"
- Un axe temporel : la politique est passée de 3 ans (2021) à 5 ans (2023), mais le document IT n'a pas été mis à jour

L'auditeur identifie en 5 minutes un problème de cohérence qui aurait pu lui prendre une journée de lecture croisée. Et il a les preuves sourcées pour son rapport.

---

## Usage 9 — Veille concurrentielle ou scientifique

### Le scénario

Une équipe de veille importe régulièrement de nouveaux articles ou rapports sur un sujet. Chaque semaine, 5 à 10 nouveaux documents entrent dans le système.

### Ce que fait OSMOSE automatiquement

À chaque import, le pipeline détecte :
- Les nouvelles claims qui confirment des connaissances existantes (renforcement)
- Les claims qui contredisent des connaissances existantes (alerte)
- Les nouveaux concepts qui n'existaient pas avant (émergence)
- Les clusters qui grossissent (tendance de fond)

L'équipe de veille reçoit un résumé : "Cette semaine, 3 nouvelles études confirment l'efficacité du biomarqueur X. Mais attention : 1 étude contredit les résultats précédents sur la population Y. Nouveau concept détecté : Z, mentionné dans 2 articles."

C'est de la veille augmentée — pas juste "voici les nouveaux documents", mais "voici ce que les nouveaux documents changent à ce qu'on savait déjà".

---

## Usage 10 — Comparer deux sujets ou deux versions

### Le scénario

Un architecte solution doit comparer deux versions d'un produit pour conseiller un client. "Qu'est-ce qui a changé entre la version 2023 et la version 2024 ?"

### Ce qu'il fait avec OSMOSE

Le système connaît les axes d'applicabilité. Il peut filtrer les claims par version et montrer :

- Claims présentes en 2023 mais absentes en 2024 (fonctionnalités retirées)
- Claims présentes en 2024 mais absentes en 2023 (nouveautés)
- Claims présentes dans les deux mais avec des valeurs différentes (évolutions)
- Claims contradictoires entre les deux versions

C'est un diff sémantique entre versions — pas un diff de fichiers texte, mais un diff de ce que les documents affirment.

---

## En résumé

| Usage | Bénéfice | Temps gagné |
|-------|----------|-------------|
| **Recherche sourcée** | Réponse + preuve verbatim, pas juste un résumé | 80% |
| **Vérification de texte** | Chaque affirmation confrontée au KG | 90% |
| **Article de synthèse (Atlas)** | Encyclopédie vivante auto-générée | Jours → minutes |
| **Détection d'obsolescence** | Évolutions temporelles visibles | Impossible manuellement |
| **Découverte de connexions** | Relations cachées révélées par la structure du graphe | Impossible autrement |
| **Réponse appel d'offres** | Pré-remplissage sourcé des réponses | 70% |
| **Onboarding** | Compréhension structurée en jours, pas en semaines | 60% |
| **Audit de conformité** | Incohérences détectées automatiquement | 85% |
| **Veille augmentée** | Ce qui change, pas juste ce qui est nouveau | 50% |
| **Comparaison de versions** | Diff sémantique entre documents ou versions | Impossible manuellement |

Le Knowledge Graph n'est pas une fin en soi. C'est un socle sur lequel se construisent des usages impossibles avec une approche traditionnelle. OSMOSE ne remplace pas les documents — il les rend intelligents.
