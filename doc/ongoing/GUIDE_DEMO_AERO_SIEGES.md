# Guide de démo OSMOSIS — « La semaine de Claire »

*Guide opérateur, 06/06/2026 (v2 — fil narratif explicité). Toutes les questions ont
été validées en live sur le corpus aéro (24 documents de certification sièges
FAA/EASA). Durée cible : 12-14 min.*

---

## 🧭 LE FIL DE L'HISTOIRE (à lire avant tout — c'est ta colonne vertébrale)

**La modification demandée par le client contient toute la logique de la démo :**

> Le client veut **intégrer un écran de divertissement (IFE) dans le dossier des
> sièges** et changer les ceintures.

Pourquoi c'est un sujet de certification ? Parce qu'en cas d'atterrissage
d'urgence, **la tête du passager assis derrière vient frapper le dossier du siège
de devant**. Tout ce qu'on ajoute sur ce dossier — un écran rigide, une tablette —
change la surface que la tête percute. Les autorités encadrent donc la sévérité
de cet impact avec un critère chiffré : le **HIC** (Head Injury Criterion, critère
de blessure à la tête). Si le HIC mesuré en essai dépasse **1 000**, le siège
n'est pas certifiable.

**D'où la matinée de Claire, dans l'ordre :**
1. *« Quel est le seuil que mon écran ne doit pas faire dépasser ? »* → la limite
   HIC (**acte 1**)
2. *« Quelle est la procédure d'approbation d'une modification de siège ? »* → le
   vieux dossier référence l'AC 21-25A, guide officiel de l'approbation des
   sièges modifiés… est-il encore valable ? (**acte 2**)
3. *« Comment dois-je conduire l'essai d'impact tête pour qu'il soit accepté par
   la FAA ET par l'EASA ? »* → et là, les deux autorités divergent (**acte 3**)
4. *« Puis-je faire confiance à cet outil ? »* → elle le piège volontairement
   (**acte 4**)
5. La chute : l'Atlas (**acte 5**)

Chaque question DÉCOULE de la modification du client. Tu ne récites pas des
questions — tu déroules le raisonnement d'une ingénieure qui prépare un dossier.

---

## 🔤 LEXIQUE OPÉRATEUR (pour répondre aux questions de l'audience)

| Terme | En clair |
|---|---|
| **HIC** | *Head Injury Criterion* — score de sévérité d'un impact de la tête, calculé depuis les capteurs d'un mannequin de crash. **Limite : 1 000.** Au-delà = risque de blessure grave = non certifiable |
| **FAA / EASA** | Les deux autorités de certification : américaine / européenne. Un siège vendu mondialement doit satisfaire **les deux** |
| **AC** (Advisory Circular) | Document de la FAA expliquant **comment** se conformer à la réglementation (le « guide pratique » officiel). Ex : AC 21-25B = approbation des sièges modifiés |
| **TSO / ETSO** | *Technical Standard Order* — l'agrément type d'un équipement (le siège lui-même). ETSO = version européenne |
| **CFR / CS-25** | La réglementation elle-même (Code of Federal Regulations US / Certification Specifications EASA pour les gros avions) |
| **ATD** | *Anthropomorphic Test Device* — le mannequin de crash instrumenté |
| **Essai dynamique 16g** | Essai sur catapulte : le siège (avec mannequins) subit une décélération de 16 fois la gravité, comme un crash survivable. C'est là qu'on mesure le HIC, les charges lombaires, la tenue des ceintures |
| **Impact franc / coup glissant** (*solid strike / glancing blow*) | La tête peut frapper le dossier de face (franc) ou en le rasant (glissant). Toute la divergence FAA/EASA de l'acte 3 porte sur : lequel des deux compte pour la démonstration ? |
| **Charge lombaire** | Force de compression mesurée dans la colonne du mannequin. Limite : 1 500 lb |

---

## ✈️ AVANT LA DÉMO (checklist, ~10 min avant)

| # | Manipulation | Pourquoi |
|---|---|---|
| 1 | `./kw.ps1 status` → app, frontend, neo4j, qdrant, redis **Up** | Pas de surprise infra |
| 2 | Ouvrir http://localhost:3000/chat et poser une question quelconque | **Chauffer le système** : 1er appel ~50 s (chargement modèles), les suivants 25-40 s |
| 3 | Vérifier le toggle **« Knowledge Graph »** **activé** (bouton bleu) | L'acte 3 repose sur sa bascule |
| 4 | Ouvrir http://localhost:3000/atlas dans un 2e onglet | L'acte 5 doit s'ouvrir sans chercher |
| 5 | Deck de secours (captures) accessible | Plan B si le LLM tousse |

⚠️ Latence normale : **25-45 s**. À assumer : « il vérifie chaque fait, il ne
complète pas des phrases » — la latence devient un argument.

---

## 🎬 MISE EN SITUATION (1 min 30 — pas de manipulation)

**🗣️ Pitch :**
> « Je vous présente Claire. Elle est ingénieure certification chez un
> équipementier de sièges d'avion. Ce matin, un client compagnie aérienne lui
> demande une modification de sièges en service : **intégrer un écran de
> divertissement dans le dossier**, et changer les ceintures.
>
> Ça a l'air anodin. Ça ne l'est pas : en cas d'atterrissage d'urgence, la tête
> du passager assis derrière **vient frapper ce dossier**. Ajouter un écran
> rigide à l'endroit exact où une tête percute, c'est rouvrir la démonstration
> de sécurité du siège. Et ce siège vole aux États-Unis ET en Europe : il doit
> satisfaire **deux autorités**, la FAA et l'EASA.
>
> Le problème de Claire n'est pas de trouver de l'information — elle en a trop :
> des centaines de pages de réglementations et de guides qui se citent, se
> remplacent, et parfois se contredisent. Son problème, c'est de savoir **ce qui
> fait foi**. Une exigence ratée, c'est un dossier retoqué, des semaines de
> retard, un avion cloué au sol. Suivons sa matinée. »

---

## 🎬 ACTE 1 — Le seuil à ne pas dépasser (1 min 30)

**📖 Pourquoi Claire pose cette question :** l'écran dans le dossier change la
surface que la tête percute. Avant toute chose, Claire a besoin du **chiffre qui
gouverne tout son dossier** : jusqu'à quelle sévérité d'impact son siège modifié
reste-t-il certifiable ? C'est le critère HIC. Tout le reste (conception de
l'écran, campagne d'essais, coûts) découle de ce seuil.

**🖱️ Manipulation :**
1. Poser :
   > **Quelle est la limite maximale autorisée du HIC pour la certification des sièges d'avion ?**
2. Attendu : *« 1 000 unités »*, références numérotées [1][2]…
3. **Déplier « sources citées »** et **cliquer un lien** → le PDF s'ouvre
   **à la bonne page**.

**🗣️ Pitch :**
> « Première question de Claire : le seuil. Si la tête du passager subit un
> impact dont le score — le HIC — dépasse 1 000, le siège n'est pas certifiable.
> Réponse : 1 000 unités, c'est confirmé. Mais regardez le geste important :
> chaque affirmation est reliée à sa source. Je clique… et le document s'ouvre
> **à la page exacte**. Claire ne croit pas le système sur parole — elle vérifie
> en cinq secondes ce qui lui prenait dix minutes dans un PDF de 60 pages. »

**🎯 Ce qu'on démontre :** réponse factuelle sourcée au niveau de l'affirmation,
traçabilité cliquable jusqu'à la page.

**💎 Différenciateur :**
> Les assistants IA du marché citent des *documents* — « voir AC 25.562-1B » — et
> vous laissent chercher. Ici, chaque **phrase** connaît sa source et sa page.
> C'est la différence entre un assistant qu'il faut **relire** et un assistant
> qu'on peut **auditer**. Dans un métier où l'on engage sa signature, c'est ce
> qui rend l'outil utilisable, pas juste impressionnant.

---

## 🎬 ACTE 2 — Le piège du document mort (2 min)

**📖 Pourquoi Claire pose cette question :** modifier un siège certifié ne se
fait pas librement — il existe un **guide officiel de l'approbation des sièges
modifiés** (c'est littéralement le sujet de l'AC 21-25). Claire ressort donc le
dossier de certification d'origine du siège, qui date de 2009… et qui référence
l'**AC 21-25A** comme procédure à suivre. Réflexe avant d'engager le travail :
ce guide de 2009 est-il encore la référence ?

**🖱️ Manipulation :**
1. Poser :
   > **Est-ce que l'AC 21-25A est toujours en vigueur, et sinon, par quoi a-t-elle été remplacée ?**
2. Attendu : *« Non… annulée et remplacée par l'AC 21-25B »* + la phrase
   d'annulation citée + la lignée (21-25 → 21-25A → 21-25B).

**🗣️ Pitch :**
> « Le dossier d'origine du siège date de 2009. Il dit : pour modifier ce siège,
> suivez la procédure de l'AC 21-25A. Claire vérifie. Réponse : ce document est
> **mort** — annulé et remplacé par l'AC 21-25B. Et le système ne se contente
> pas de l'affirmer : il **cite la déclaration d'annulation** comme preuve, et
> il connaît toute la généalogie — 21-25, puis 21-25A, puis 21-25B aujourd'hui
> en vigueur. Si Claire avait suivi la procédure de 2009, son dossier reposait
> sur un texte abrogé — l'erreur classique qu'on découvre six mois plus tard,
> au moment du refus. »

**🎯 Ce qu'on démontre :** le système connaît le **cycle de vie** des documents
(qui remplace quoi) et le restitue avec preuve.

**💎 Différenciateur :**
> Une recherche classique vous donne *tous* les documents qui ressemblent à votre
> question — y compris les morts, sans vous le dire. Les moteurs d'entreprise
> indexent ce qui existe ; ils ne savent pas ce qui **fait encore foi**. Ici, la
> généalogie documentaire est une connaissance de premier rang : le système
> distingue l'histoire de l'état courant. Pour tout métier réglementé — aéro,
> pharma, juridique, finance — c'est LA question quotidienne.

---

## 🎬 ACTE 3 — LE CLIMAX : la divergence que personne ne voit (3-4 min)

**📖 Pourquoi Claire pose cette question :** la procédure est claire, le seuil
aussi. Reste à **planifier l'essai** qui démontrera que la tête peut frapper ce
nouvel écran sans dépasser HIC 1 000. Or pendant un essai, la tête du mannequin
peut frapper le dossier **de face** (impact franc) ou **en le rasant** (coup
glissant). La question à plusieurs dizaines de milliers d'euros : *lequel des
deux compte comme démonstration valable ?* Si elle se trompe, l'essai est à
refaire. Et son siège doit convaincre **deux autorités**.

**🖱️ Manipulation (en 2 temps) :**
1. Poser :
   > **Selon la FAA et l'EASA, l'évaluation du HIC à 1000 doit-elle provenir d'un impact franc (solid strike), ou s'applique-t-elle aussi en cas de coup glissant (glancing blow) ?**
2. Attendu : **bandeau rouge « Divergence entre autorités réglementaires »** +
   les deux positions citées (FAA : impact franc exigé ; EASA : la limite
   s'applique quel que soit le contact).
3. **Coup de théâtre** : désactiver le toggle **« Knowledge Graph »** (gris) et
   **reposer exactement la même question**.
4. Attendu : badge violet « RAG seul » ; la réponse passe à côté de la
   divergence (affirme à tort qu'il n'y a pas de distinction, ou avoue ne pas
   savoir — les deux servent le propos).
5. **Réactiver le toggle.**

**🗣️ Pitch (temps 1) :**
> « Claire planifie maintenant son essai d'impact tête. Détail technique qui
> vaut très cher : pendant l'essai, la tête du mannequin peut frapper l'écran
> de face — un impact franc — ou en le rasant — un coup glissant. Lequel des
> deux compte comme démonstration ? Elle pose la question… et le système lève
> un **drapeau rouge** : les deux autorités ne disent pas la même chose. La FAA
> exige que la démonstration provienne d'un impact franc. L'EASA applique la
> limite quel que soit le type de contact. Les deux textes sont là, cités. Si
> Claire avait conçu sa campagne d'essais selon la seule FAA, son dossier EASA
> était mauvais. Concrètement : **un essai sur catapulte à refaire — des
> dizaines de milliers d'euros et six semaines de programme.** »

**🗣️ Pitch (temps 2 — la bascule) :**
> « Maintenant, une expérience honnête. Je désactive le graphe de connaissances —
> il ne reste que la recherche documentaire moderne, la même technologie que
> les assistants IA que vous connaissez, sur les **mêmes documents**, avec le
> **même modèle d'IA**. Même question… Regardez : la divergence a disparu.
> L'information existe pourtant — mais elle vit dans **deux documents
> différents**, et un moteur de recherche lit des passages : il ne **confronte**
> jamais deux textes entre eux. Ici, la contradiction a été détectée au moment
> de l'ingestion des documents — elle attendait Claire. »

**🎯 Ce qu'on démontre :** détection de contradictions inter-sources pré-calculée
dans le graphe + preuve A/B en direct que le modèle d'IA n'y est pour rien.

**💎 Différenciateur :**
> C'est le cœur. Tous les acteurs du marché répondent à « que disent mes
> documents ? ». Aucun ne répond à « mes documents sont-ils **d'accord entre
> eux** ? ». Cette question-là exige de mémoriser des affirmations, pas des
> pages, et de les confronter en permanence. Vous venez de le constater : même
> corpus, même modèle — seule la **structure de la mémoire** change le résultat.
> Ce n'est pas une course au meilleur modèle d'IA ; c'est une autre catégorie
> d'outil.

---

## 🎬 ACTE 4 — La confiance : savoir se taire (1 min 30)

**📖 Pourquoi Claire pose cette question :** Claire est ingénieure — elle ne
fait pas confiance à un outil qu'elle n'a pas **piégé**. Avant de s'appuyer sur
lui pour un dossier qu'elle signera, elle lui pose volontairement une question
dont elle SAIT que la réponse n'est pas dans sa base documentaire (les sièges
éjectables militaires — un tout autre monde que les sièges passagers civils).

**🖱️ Manipulation :**
1. (Toggle KG réactivé.) Poser :
   > **Quelles sont les exigences de certification des sièges éjectables militaires selon la MIL-S-9479 ?**
2. Attendu : **refus motivé** — le corpus ne couvre pas ce point, le système le
   dit au lieu d'inventer.

**🗣️ Pitch :**
> « Dernière question — et Claire la pose en connaissance de cause : les sièges
> éjectables militaires, un monde qui n'a rien à voir avec sa base documentaire.
> Elle piège l'outil. Et il donne la réponse la plus importante de toute la
> démo : **"je ne sais pas, et voici pourquoi"**. En certification, une réponse
> inventée est pire que pas de réponse : elle finit dans un dossier avec une
> signature dessous. Sur notre banc d'évaluation, cette discipline d'abstention
> atteint 83 %, contre 65 % pour la même IA sans le graphe. C'est *ça* qui
> permet à Claire de s'y fier les 95 autres fois où il répond. »

**🎯 Ce qu'on démontre :** l'abstention calibrée — le système connaît les
limites de son corpus et les déclare.

**💎 Différenciateur :**
> Le réflexe du marché est de toujours répondre — optimisé pour la satisfaction
> immédiate, pas pour la fiabilité. Un outil qui ne sait pas se taire reporte la
> vérification sur l'humain à **chaque** réponse : le gain de temps s'évapore.
> La valeur d'un assistant professionnel ne se mesure pas à ce qu'il sait dire,
> mais à la confiance qu'on peut accorder à ce qu'il dit.

*(**Option audience technique — Acte 4 bis : sauver un essai déjà payé.**
Contexte-histoire : en fouillant les archives d'essais du siège, Claire trouve un
essai dynamique où la catapulte a tiré un peu trop fort — pic à 15g au lieu des
14g requis — et la charge lombaire mesurée, 1 590 lb, dépasse la limite de
1 500 lb. Cet essai est-il bon à jeter, ou la guidance permet-elle de corriger
proportionnellement ? Poser :*
> *« Une charge lombaire de 1590 lb a été mesurée lors d'un essai dont le pic était de 15g au lieu des 14g requis. À quelle valeur cette charge peut-elle être ramenée par proportionnalité, selon la guidance ? »*
*→ attendu : la règle ET le calcul, 14/15 × 1590 = **1 484 lb** < 1 500 → l'essai
est sauvé. Pitch : « il a chaîné deux faits — la règle de proportionnalité, puis
son application chiffrée. Claire vient d'éviter de repayer un essai. »)*

---

## 🎬 ACTE 5 — La chute : l'Atlas (2 min)

**📖 Pourquoi on montre ça :** la démo des questions est finie — l'audience
pense avoir tout vu. On introduit l'Atlas comme un élément *banal* du décor
(la documentation de formation de l'équipe) pour révéler ensuite qu'il est
généré. La surprise ne marche que si la navigation silencieuse laisse croire
à une documentation rédigée à la main.

**🖱️ Manipulation :**
1. Basculer sur l'onglet **http://localhost:3000/atlas** déjà ouvert.
2. **Naviguer 30 secondes EN SILENCE** : homepage → un thème (ex. « Conformité
   et vérification réglementaires ») → un chapitre (ex. « Energy-Absorbing
   Seating in Crash Scenarios ») → faire défiler l'article.
3. Puis poser la question à l'audience (pitch).

**🗣️ Pitch :**
> « Une dernière chose. Quand Claire a rejoint ce programme, il a fallu se
> former. Voici la documentation de référence de l'équipe. » *(navigation
> silencieuse)*
>
> « Une question : d'après vous, **qui a écrit cette documentation ?** …
> Personne. Le système l'a générée tout seul, en lisant les mêmes 24 documents :
> les domaines, les chapitres, les articles, les liens entre thèmes. Chaque
> affirmation reste reliée à sa source. Et quand un nouveau document arrive —
> un amendement, une révision — **cette documentation se régénère**. Elle ne
> peut pas être périmée. »

**🎯 Ce qu'on démontre :** le même socle de faits sert aussi à *rédiger et
maintenir* le savoir — onboarding, revue de périmètre, documentation vivante.

**💎 Différenciateur :**
> La documentation interne est le projet que toutes les organisations commencent
> et qu'aucune ne maintient : périmée le jour de sa publication. Ici, ce n'est
> plus un livrable, c'est un **sous-produit permanent** du système. Les outils du
> marché cherchent dans vos documents ; celui-ci en **redistille le savoir** —
> et le tient à jour sans qu'on le lui demande.

---

## 🎬 CLÔTURE (1 min — pas de manipulation)

**🗣️ Pitch :**
> « Tout ce que vous avez vu repose sur une seule idée : ce système ne stocke
> pas des *pages*, il stocke des **affirmations vérifiables** — qui les a dites,
> quand, ce qui les remplace, ce qui les contredit. Vous l'avez vu répondre et
> prouver, repérer un document mort, confronter deux autorités, refuser
> d'inventer, et même rédiger sa propre documentation. La différence avec un
> assistant IA générique, ce n'est pas l'intelligence du modèle — vous avez vu
> le même modèle échouer sans le graphe. C'est **la structure de la mémoire**.
> Et c'est ce qui change un outil de recherche en un outil de décision. »

---

## 🧯 PLAN B / INCIDENTS

| Symptôme | Réflexe |
|---|---|
| Réponse > 60 s ou erreur de synthèse | « Le fournisseur d'IA a un hoquet — c'est précisément pour ça qu'on ne fait jamais confiance à une IA sans preuve » → reposer la question ; sinon capture du deck |
| Abstention inattendue sur une question des actes 1-3 | Reposer telle quelle (variance fournisseur) ; 2e échec → capture du deck + « résultat d'hier, on regardera en direct après » |
| La divergence acte 3 ne s'affiche pas | Reposer EXACTEMENT comme écrit (les termes *solid strike* / *glancing blow* comptent) |
| Le RAG (toggle off) répond correctement à l'acte 3 | Sourire : « il a eu de la chance sur ce tirage — c'est justement le problème : sans graphe, la détection est une loterie ; avec, elle est systématique » |
| Page Atlas vide / thème vide | Rafraîchir ; sinon sauter à la clôture (l'acte 5 est sautable) |

## 📝 Notes opérateur

- Questions à **copier-coller depuis ce guide** (la formulation exacte compte
  pour les actes 3 et 4 bis).
- Ne PAS purger, ré-ingérer ni redémarrer quoi que ce soit entre la répétition
  et la démo.
- Répétition complète la veille : dérouler les 5 actes dans l'ordre, chronométrer,
  faire les captures du deck de secours à cette occasion.
- Si l'audience pose une question de fond sur l'aéro : le **lexique** en tête de
  guide couvre 95 % des cas ; pour le reste, « excellente question, je la note
  pour nos experts métier » est une réponse d'avant-vente parfaitement honorable.
