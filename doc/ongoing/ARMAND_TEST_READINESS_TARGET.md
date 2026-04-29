# Carte cible — Test de validation OSMOSIS auprès d'Armand Saulais

**Date** : 2026-04-26
**Statut** : Document de travail (préalable aux ADRs ciblés et à l'audit code)
**Auteur** : Fred + Claude Code
**Portée** : Cadrage de l'ambition — indépendant de l'état actuel du code

---

## 1. Contexte

Fred prépare un test de validation produit avec Armand Saulais (Directeur Juridique et Compliance, Safran Seats), positionné comme **client zéro potentiel** d'OSMOSIS. Le test portera sur un **corpus public** uniquement — aucun document confidentiel Safran ne sera utilisé.

Corpus de test ciblé :

- **EASA CS-25** (Certification Specifications — Large Aeroplanes), avec idéalement plusieurs amendements pour démontrer l'évolution réglementaire
- **Règlement UE 2021/821** sur les biens à double usage, avec ses **versions consolidées successives** (2021-09-09, 2023-05-26, 2024-11-08, 2025-11-15) — et idéalement le **prédécesseur 428/2009** pour exposer les vraies divergences

La fenêtre de préparation est **2 à 6 semaines** selon disponibilité d'Armand. L'objectif n'est pas de tenir un délai mais de présenter à Armand un système dont la maturité justifie son temps et son feedback de juriste senior.

Le RDV initial est un **déjeuner sans démo** (cadre amical, pas pro). La démo et le test s'enchaîneront ensuite, sur proposition de Fred et avec accord d'Armand, dans un second temps. Cette carte cible cadre l'ambition à atteindre **avant ce second temps**, pas avant le déjeuner.

Niveaux de résultat visés :

- **Niveau 2** (objectif) : Armand propose des introductions à 2-3 juristes/compliance de son réseau
- **Niveau 3** (idéal) : Armand propose un pilote Safran sur corpus semi-confidentiel, avec NDA

---

## 2. Cadre de priorisation

Trois dimensions hiérarchisent les capacités. Une capacité mérite un effort dédié si elle remplit au moins **deux des trois critères** :

- **Dimension A — Criticité pour le test** : Armand reconnaîtra-t-il la valeur sans cette capacité ?
- **Dimension B — Différenciation** : la capacité distingue-t-elle OSMOSIS d'un RAG générique ou d'un RAG+KG du marché ?
- **Dimension C — Risque de visible failure** : si on la promet et qu'elle se plante visiblement pendant le test, est-ce disqualifiant ?

Trois paniers en sortent : **Must / Should / Nice**. Le panier détermine le seuil d'engagement, pas le délai.

### Note transversale — Erreur défendable vs erreur aberrante

Pour les capacités à classification (M2 notamment), une métrique brute n'est pas suffisante. Une **erreur défendable** (le système hésite là où un juriste hésiterait aussi) est qualitativement différente d'une **erreur aberrante** (le système dit une chose qu'aucun humain informé ne dirait).

Règle de pondération qui sera appliquée :
- Une **erreur aberrante compte pour 5 erreurs défendables** dans l'évaluation finale
- Au-delà de **10% d'erreurs aberrantes**, une capacité est considérée non maîtrisée même si la précision globale est haute

Cette règle protège contre l'illusion d'un bon score moyen qui cacherait quelques sorties absurdes hautement disqualifiantes.

---

## 3. MUST-HAVE — sans ça, on reporte le test

### M1 — Détection fiable de tensions

**Quoi mesurer.** Sur le corpus de test, OSMOSIS détecte-t-il les vraies tensions présentes (rappel) sans flagger massivement des non-tensions (précision) ?

**Comment mesurer.** Construire un jeu de **20 vraies tensions** annotées manuellement (contradictions réelles, exigences divergentes, textes qui se chevauchent entre versions ou entre 2021/821 et 428/2009) et **20 non-tensions apparentes** (textes qui se ressemblent lexicalement mais portent sur des scopes différents, reformulations équivalentes, simples précisions d'amendements). Mesurer rappel et précision.

**Qui juge.** Fred, avec validation d'un sous-échantillon de 5-8 cas par un tiers (ChatGPT en mode juriste critique).

**Seuil de report (plancher)** : rappel < 70% **OU** précision < 60%.
> *Traduction concrète* : sur 20 vraies tensions, plus de 6 ratées **ou** sur 20 non-tensions, plus de 8 faux positifs → on reporte.

**Seuil de confort (cible)** : rappel ≥ 85% **ET** précision ≥ 75%.

**Note critique.** **La précision prime sur le rappel** dans ce cas d'usage. Un juriste tolère qu'OSMOSIS rate une tension (il la verra en lisant), il ne tolère pas qu'OSMOSIS invente des tensions qui n'existent pas (perte de temps + érosion de confiance). Si arbitrage : priorité à la précision.

---

### M2 — Classification des tensions (3 classes minimum)

**Quoi mesurer.** Parmi les tensions correctement détectées par M1, quelle proportion est classée dans la bonne catégorie ?

Classes minimales du Must :
1. **Contradiction réelle** — deux textes incompatibles sur le même objet, même portée, même temporalité
2. **Différence de portée / scope** — deux textes qui semblent diverger mais portent sur des périmètres distincts (civil vs militaire, UE vs export, etc.)
3. **Évolution temporelle ou précision entre versions** — un texte ultérieur qui clarifie, précise ou abroge un texte antérieur

**Comment mesurer.** Sur les tensions détectées au M1, annoter la classification attendue. Comparer à la classification produite par OSMOSIS. Pour chaque erreur, juger si elle est **défendable** ou **aberrante** (cf. note transversale §2).

**Qui juge.** Fred. Pour le critère défendable/aberrant, faire valider un échantillon par tiers.

**Seuil de report (plancher)** : moins de 50% de classifications justes **OU** plus de 20% d'erreurs aberrantes.
> *Traduction concrète* : si une tension sur deux est mal classée, ou si plus d'une erreur sur cinq est qualifiable d'absurde par un juriste → on reporte.

**Seuil de confort (cible)** : au moins 70% de classifications justes **ET** moins de 10% d'erreurs aberrantes.

**Note critique.** C'est le **chantier produit principal des prochaines semaines**. M2 est aujourd'hui le maillon faible reconnu d'OSMOSIS (détection forte, classification imparfaite). C'est aussi le cœur du pitch oral préparé pour Armand : la promesse de "détecter et mettre en évidence pour décision humaine" repose sur une classification suffisamment fiable pour ne pas crier au loup. Un ADR dédié sera produit pour ce chantier.

---

### M3 — Traçabilité claim-to-source

**Quoi mesurer.** Proportion des affirmations produites par OSMOSIS qui ont une source précise et **vérifiable** attachée.

**Comment mesurer.** Sur un lot de **25 réponses** (mix simple/complexe/avec tensions), pour chaque phrase affirmative dans la réponse, vérifier :
- (a) une source est citée
- (b) la source existe réellement dans le corpus
- (c) la source citée contient effectivement l'information rapportée

**Qui juge.** Fred. Manuellement, phrase par phrase.

**Seuil de report (plancher)** : moins de 90% des phrases ont une source valide, **OU** au moins une phrase a une source qui n'existe pas dans le corpus.
> *Traduction concrète* : **une seule source inventée est disqualifiante**. C'est la mort de la crédibilité.

**Seuil de confort (cible)** : 100% des phrases affirmatives ont une source valide et vérifiable.

**Note critique.** Critère **quasi-binaire et non-négociable**. La traçabilité est le ticket d'entrée d'OSMOSIS dans la catégorie "outil pour juriste". Sans elle, tout le pitch (réassurance documentaire, défendabilité devant un auditeur) s'effondre. C'est par construction ce qui distingue OSMOSIS d'un chatbot.

---

### M4 — Abstention calibrée hors-corpus

**Quoi mesurer.** Sur des questions dont la réponse n'est pas dans le corpus, OSMOSIS s'abstient-il, ou invente-t-il par complétion stylistique ?

**Comment mesurer.** Construire **15 questions délibérément hors-corpus** — plausibles mais sans réponse dans CS-25 ou 2021/821. Exemples : « quel est le nombre maximal de passagers autorisé en cabine selon CS-25 ? » (CS-25 ne fixe pas de nombre absolu, elle fixe des exigences par siège), « le règlement 2021/821 mentionne-t-il les exportations vers l'Antarctique ? ». Lancer, classer chaque réponse selon : abstention claire / abstention ambiguë / réponse synthétisée / hallucination nette.

**Qui juge.** Fred.

**Seuil de report (plancher)** : plus d'une **hallucination nette** sur 15 questions, **OU** moins de 80% d'abstentions claires.
> *Traduction concrète* : une seule hallucination nette sur sujet testable est gravissime — Armand la remarquera s'il teste de lui-même.

**Seuil de confort (cible)** : zéro hallucination nette **ET** au moins 90% d'abstentions claires.

**Note critique.** M3 et M4 sont **corrélés mais distincts**. M3 dit « quand OSMOSIS parle, il parle avec une source ». M4 dit « quand OSMOSIS ne peut pas parler, il se tait ». Les deux ensemble forment l'**invariant épistémique fondateur** d'OSMOSIS (INV-EPIST-01, evidence-locking).

---

### M5 — Baseline factual sur questions simples

**Quoi mesurer.** Sur des questions à réponse factuelle unique et non contestable (date, chiffre, article, définition), le taux de réponses correctes d'OSMOSIS, comparé à un RAG pur.

**Comment mesurer.** Construire **30 questions factuelles simples** sur CS-25 et 2021/821. Exemples : « date d'entrée en vigueur du règlement 2021/821 ? », « CS-25 article 25.561, quelle accélération vers l'arrière ? », « quel règlement 2021/821 abroge-t-il ? ». Comparer OSMOSIS vs RAG pur (ou ChatGPT+recherche / Perplexity sur corpus équivalent ingéré).

**Qui juge.** Fred. Classification : juste / partiellement juste / fausse / refus à tort.

**Seuil de report (plancher)** : OSMOSIS sous le RAG pur de **plus de 10 points**, **OU** taux de refus à tort > 20%.
> *Traduction concrète* : OSMOSIS à 60% là où RAG est à 75%, c'est un écart visible qui attire le regard d'Armand. 1 refus à tort sur 5 → l'outil paraît excessivement prudent.

**Seuil de confort (cible)** : OSMOSIS à moins de **5 points** sous le RAG pur **ET** refus à tort < 10%.

**Note critique.** Sur les corpus SAP actuels, OSMOSIS est à -4 points grâce à la délégation au RAG interne pour les questions simples. **Cette délégation doit être validée sur CS-25 et 2021/821** (corpus juridique anglais, phrases longues, terminologie technique différente). Le risque n'est pas l'absolu mais le différentiel de comportement entre corpus.

---

### M6 — Présentation lisible du raisonnement

**Quoi mesurer.** Pour une requête non triviale, un utilisateur non-développeur peut-il, sans manipulation technique ni explication verbale, voir comment OSMOSIS a construit sa réponse : textes retenus, textes écartés, tensions identifiées, zones silencieuses ?

**Comment mesurer.** Test d'usage "sur le dos d'une enveloppe". Prendre **5 requêtes représentatives** :
1. Question simple à réponse factuelle
2. Question avec tension détectée entre documents
3. Question hors-corpus → abstention attendue
4. Question complexe à information distribuée sur plusieurs docs
5. Question différentielle entre versions (CS-25 amdt N vs N-1, ou 2021/821 vs 428/2009)

Pour chacune, se mettre à la place d'Armand et juger : peut-il comprendre, en regardant l'interface seule, pourquoi cette réponse plutôt qu'une autre ?

**Qui juge.** Fred, en mode dissociation (regarder comme si on ne connaissait pas le code). Idéalement validation par un tiers non technique sur 2-3 requêtes.

**Seuil de report (plancher)** : moins de **3 requêtes sur 5** permettent une compréhension autonome.
> *Traduction concrète* : si plus de la moitié des réponses exigent que Fred explique « alors là en fait, derrière, le système fait... », c'est de la démo-dépendance — mauvais signe.

**Seuil de confort (cible)** : **5/5**.

**Note critique.** Critère le plus susceptible de compensation par la présence verbale de Fred si la démo est en live. Mais le test Armand sera vraisemblablement en autonomie après le déjeuner — donc viser **5/5** strict, pas le plancher.

---

## 4. SHOULD-HAVE — différenciateurs sans lesquels on part quand même

### S1 — Décomposition différentielle / raisonnement entre versions

OSMOSIS reconnaît qu'une question implicitement différentielle (« qu'est-ce qui change entre la version N et N-1 ? », « qu'est-ce que cette norme apporte de nouveau ? ») nécessite une décomposition : retrieve version A, retrieve version B, diff structuré, synthèse.

**Statut au 26/04/2026 (selon Fred)** : capacité validée fonctionnellement sur corpus SAP. À **confirmer sur CS-25 et 2021/821** spécifiquement (multi-versions disponibles, terrain idéal).

**Critère de confort** : sur 5 questions différentielles formulées implicitement, OSMOSIS produit un diff structurant (pas une simple réponse plate) dans au moins 4 cas, sans erreur d'attribution de version.

**Pourquoi Should et pas Must** : un test Armand peut être convaincant même sans cette capacité — les Must portent la valeur. Mais c'est l'un des **moments de démo les plus impressionnants** s'il fonctionne sur les amendements CS-25 successifs.

---

### S2 — Classification fine des tensions (2 classes additionnelles)

Au-delà des 3 classes du M2, ajouter :
4. **Précision-complément** — un avenant ou un amendement précise sans modifier le fond
5. **Équivalence reformulée** — deux textes disent la même chose dans des termes différents

**Pourquoi Should** : ces deux classes correspondent exactement à ce qu'un juriste fait mentalement en lecture fine. Si OSMOSIS y arrive, l'effet "tu vois les choses comme moi" est très fort. Sans elles, les 3 classes du Must suffisent à porter la promesse.

---

### S3 — Reconstitution de l'état du droit à une date donnée

OSMOSIS répond à « quelles règles s'appliquaient en juin 2022 ? » sans que l'utilisateur précise manuellement les versions. Implique des relations `SUPERSEDES` / `IS_SUPERSEDED_BY` correctement construites entre claims datés.

**Statut au 26/04/2026** : capacité partiellement implémentée. Une simple mention de date dans le prompt fonctionne (un RAG le ferait aussi). La **vraie temporalité first-class** (reconstruction automatique de l'état normatif) reste à mûrir.

**Choix éditorial pour le pitch et la démo** : la temporalité est **repositionnée en arrière-plan**. Pas un axe de promesse central. Si Armand interroge frontalement la temporalité, Fred répondra avec honnêteté : « c'est un axe important mais moins mûr que la détection de tensions, je travaille dessus ».

**Pourquoi Should et pas Must** : l'audit rétrospectif de conformité (cas d'usage 3 d'Armand) est le seul qui repose massivement sur cette capacité. Les autres cas tolèrent une temporalité approximative.

---

### S4 — Classification confident sur les statuts /verify

Le mode validation/jugement retourne 4 statuts distincts et fiables :
- **SUPPORTED** — corpus soutient l'assertion
- **REFUTED** — corpus contredit nettement
- **CONFLICTING_EVIDENCE** — éléments contradictoires dans le corpus
- **NOT_ENOUGH_EVIDENCE** — corpus silencieux

**Critère de confort** : sur 20 assertions soumises au mode `/verify` (5 de chaque catégorie attendue), au moins 16 statuts corrects. **La distinction CONFLICTING vs NOT_ENOUGH** est le point d'attention principal — souvent confondue par les LLMs et chacune appelle une action différente chez le juriste.

---

### S5 — Détection de tensions cross-corpus (CS-25 ↔ 2021/821)

OSMOSIS détecte une interaction entre une exigence CS-25 et une restriction du règlement 2021/821 (par exemple : un siège conforme CS-25 contenant un composant soumis à licence dual-use).

**Pourquoi Should** : c'est l'un des plus beaux moments de démo possibles, mais il demande un linking d'entités entre deux corpus distincts qui n'est pas trivial. **Bonus à viser, pas pilier**.

---

## 5. NICE-TO-HAVE — fonctionnalités utiles non centrales

### N1 — Export PDF de la trace d'audit
Bouton « exporter cette réponse + sources + raisonnement en PDF horodaté ». Quick win s'il y a du temps résiduel.

### N2 — Visualisation des grappes de tensions
Vue d'ensemble « voici les 12 points de tension détectés dans votre corpus, triés par intensité ». Ouvre une conversation sur l'usage périodique.

### N3 — Résumé exécutif d'un document long
« Voici en 10 points ce que contient ce document, chacun sourcé ». Pas un différenciateur OSMOSIS mais utile en day-to-day.

### N4 — Cross-lingual FR/EN
CS-25 et 2021/821 existent en plusieurs langues. Poser une question en français sur un corpus EN et obtenir une réponse correctement sourcée — démonstration gratuite de profondeur (multilingual-e5-large déjà en place).

### N5 — Comparaison side-by-side de claims en tension
Vue simple « voici claim A, voici claim B, voici où ils divergent textuellement », avec highlighting basique. Rend la détection tangible et visuelle.

---

## 6. Règle de décision

Une fois les critères benchmarkés sur le corpus de test, la décision s'écrit ainsi :

### 🟢 Feu vert — le test a lieu
- Tous les **M sont au-dessus de leur seuil de report**
- **Au moins 4 des 6 M sont au seuil de confort**
- **M3 et M4 sont impérativement au seuil de confort** (non négociables)

### 🟡 Feu orange — discussion / décision contextuelle
- Tous les M au-dessus du plancher mais **seulement 2-3 au seuil de confort**
- M3 et M4 au confort
- Dans ce cas : le test peut avoir lieu si Fred annonce **explicitement et préalablement à Armand** les capacités en zone grise — pas comme une excuse après-coup, comme un cadrage : « je te préviens, X et Y ne sont pas encore au niveau, je te montre quand même parce que Z et W le sont, et c'est ça que je veux tester avec toi »

### 🔴 Feu rouge — report
- **Au moins un M sous le seuil de report**
- **OU** M3 / M4 pas au seuil de confort

---

## 7. Engagement de report préparé à l'avance

Phrase rédigée maintenant pour ne pas se renégocier soi-même sous pression :

> « Armand, j'ai besoin de plus de temps pour stabiliser [X et Y] avant que notre échange soit productif pour toi et pour moi. Je préfère reporter le test plutôt que te montrer un système qui ne serait pas digne de ton feedback de juriste senior. Je te recontacte avant la fin de l'été pour caler un nouveau créneau. »

**Conditions de déclenchement** : feu rouge sur le bench préalable (cf. §6).

**Ce que cette phrase n'est pas** : une fuite, une excuse, un signal de faiblesse. C'est un acte de respect professionnel. Avec un ami proche, c'est aussi un acte de protection de la relation.

---

## 8. Hors-scope explicite

Ce qui n'est **pas** dans le périmètre des prochaines semaines, et qu'il faut acter pour protéger la focalisation :

- **Tout corpus non public** — pas de documents Safran, pas de simulation de corpus contractuel privé, pas de NDA
- **Optimisation de performance** au-delà du raisonnable (latence sub-seconde, scalabilité multi-tenant)
- **Améliorations UI** non strictement nécessaires à la lisibilité de la démo (M6)
- **Industrialisation infrastructure** (durcissement sécu, déploiement client) — sera nécessaire pour un pilote Safran réel, pas pour le test
- **Capacité S3** dans son ambition pleine (reconstruction automatique d'état normatif) — la version partielle suffit
- **Cas d'usage Cas 1 du briefing Armand** (assistance contractuelle sur contrats privés) — sans accès aux contrats, le cas n'est pas démontrable, on ne le force pas

---

## 9. Articulation avec les étapes suivantes

Cette carte cible est l'**étape 1** du chantier de préparation. Elle conditionne :

- **Étape 2 — Audit code OSMOSIS vs cette cible** (`ARMAND_TEST_READINESS_AUDIT.md`)
  Pour chaque M/S/N : composants concernés, statut réel (✅ / 🟡 / 🔴), gap, ADRs existants à articuler. Sortie : liste des chantiers méritant un ADR formel.

- **Étape 3 — ADRs ciblés**
  Probables candidats à ce stade :
  - `ADR_TENSION_CLASSIFICATION` (M2 — chantier produit principal)
  - `ADR_BENCH_PROTOCOL_ARMAND` (méthodologie du bench préalable)
  - `ADR_RAISONNEMENT_UI` (M6, si l'audit révèle un manque substantiel)

- **Étape 4 — Constitution du corpus de bench**
  Téléchargement EASA + EUR-Lex. Versions multiples requises pour générer les tensions inter-versions qui éclairent la valeur d'OSMOSIS (cf. note de Fred : ne pas se limiter aux versions récentes — chercher 428/2009, amendements anciens CS-25, etc.).

- **Étape 0 (à introduire) — Bench sur corpus actuel avant chantiers**
  Avant tout code, mesurer où OSMOSIS se situe **aujourd'hui** sur les seuils chiffrés ci-dessus, sur le corpus public. Le bench n'est pas seulement un filet de sécurité technique : c'est aussi la matière concrète pour le déjeuner avec Armand (« hier je faisais tourner le système sur CS-25 et il a détecté que… »).

---

## 10. Ce que cette carte n'est pas

- Pas un planning. Aucune date d'engagement par capacité — la fenêtre est 2 à 6 semaines, l'arbitrage se fait sur les seuils, pas sur le calendrier.
- Pas un ADR architectural. Les chantiers techniques identifiés feront l'objet d'ADRs séparés à l'étape 3.
- Pas une liste de fonctionnalités produit. C'est une grille d'évaluation de la **maturité suffisante pour un test client zéro spécifique**, sur un corpus public spécifique, auprès d'un profil utilisateur spécifique.
