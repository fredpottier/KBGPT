# Guide de démo OSMOSIS — « La semaine de Claire »

*Guide opérateur, v4 — 06/06/2026 soir (ajout Acte 2bis : rebond sur la page
« Référentiel » — carte + frise chronologique — après la question lifecycle ;
climax lignée+toggle inchangé ; cf bloc « Objection contradictions » en fin de
guide). Toutes les questions et les DEUX bras (KG et RAG) ont été validés en
live ; la page Référentiel a été validée navigateur. Durée cible : 13-16 min.*

---

## 🧭 LE FIL DE L'HISTOIRE (à lire avant tout — c'est ta colonne vertébrale)

**La modification demandée par le client contient toute la logique de la démo :**

> Le client veut **intégrer un écran de divertissement (IFE) dans le dossier des
> sièges** et changer les ceintures.

Pourquoi c'est un sujet de certification ? Parce qu'en cas d'atterrissage
d'urgence, **la tête du passager assis derrière vient frapper le dossier du siège
de devant**. Tout ce qu'on ajoute sur ce dossier — un écran rigide — change la
surface que la tête percute. Les autorités encadrent la sévérité de cet impact
avec un critère chiffré : le **HIC** (Head Injury Criterion). Au-delà de
**1 000**, le siège n'est pas certifiable.

**La matinée de Claire, dans l'ordre :**
1. *« Quel est le seuil que mon écran ne doit pas faire dépasser ? »* → la
   limite HIC + la preuve à un clic (**acte 1**)
2. *« Quelle procédure d'approbation pour modifier un siège certifié ? »* → le
   vieux dossier référence l'AC 21-25A… qui est un document **mort** (**acte 2**)
   — puis **le coup d'œil** : la même information, visible sans poser de
   question, sur la carte et la frise du Référentiel (**acte 2bis**)
3. **LE TEST** : la même question posée à un assistant IA classique — sur les
   mêmes documents, avec le même modèle (**acte 3 — climax**)
4. *« Puis-je me fier à cet outil ? »* → elle le piège volontairement (**acte 4**)
5. La chute : l'Atlas (**acte 5**)

Chaque question DÉCOULE de la modification du client. Tu ne récites pas des
questions — tu déroules le raisonnement d'une ingénieure qui prépare un dossier.

---

## 🔤 LEXIQUE OPÉRATEUR (pour répondre aux questions de l'audience)

| Terme | En clair |
|---|---|
| **HIC** | *Head Injury Criterion* — score de sévérité d'un impact de la tête, calculé depuis les capteurs d'un mannequin de crash. **Limite : 1 000.** Au-delà = risque de blessure grave = non certifiable |
| **FAA / EASA** | Les deux autorités de certification : américaine / européenne. Un siège vendu mondialement doit satisfaire **les deux** |
| **AC** (Advisory Circular) | Document de la FAA expliquant **comment** se conformer à la réglementation. Ex : la série AC 21-25 = approbation des sièges **modifiés** — exactement le cas de Claire |
| **TSO / ETSO** | *Technical Standard Order* — l'agrément type d'un équipement (le siège lui-même). ETSO = version européenne |
| **CFR / CS-25** | La réglementation elle-même (US / EASA pour les gros avions) |
| **ATD** | *Anthropomorphic Test Device* — le mannequin de crash instrumenté |
| **Essai dynamique 16g** | Essai sur catapulte : le siège (avec mannequins) subit une décélération de 16 g, comme un crash survivable. C'est là qu'on mesure le HIC et les charges lombaires |
| **Charge lombaire** | Force de compression mesurée dans la colonne du mannequin. Limite : 1 500 lb |

---

## ✈️ AVANT LA DÉMO (checklist, ~10 min avant)

| # | Manipulation | Pourquoi |
|---|---|---|
| 1 | `./kw.ps1 status` → app, frontend, neo4j, qdrant, redis **Up** | Pas de surprise infra |
| 2 | Ouvrir http://localhost:3000/chat et poser une question quelconque | **Chauffer le système** : 1er appel ~50 s (chargement modèles), les suivants 25-45 s |
| 3 | Vérifier le toggle **« Knowledge Graph »** **activé** (bouton bleu) | L'acte 3 repose sur sa bascule |
| 4 | Ouvrir http://localhost:3000/atlas dans un 2e onglet | L'acte 5 doit s'ouvrir sans chercher |
| 5 | Ouvrir http://localhost:3000/referentiel dans un 3e onglet, **vérifier que la carte ET la frise s'affichent avec les dates** (si « date inconnue » partout : F5 dur) | L'acte 2bis doit basculer en 1 s ; la page charge ses données à l'ouverture |
| 6 | Deck de secours (captures) accessible | Plan B si le LLM tousse |

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
> de sécurité du siège. Et ce siège vole aux États-Unis ET en Europe : deux
> autorités, la FAA et l'EASA.
>
> Le problème de Claire n'est pas de trouver de l'information — elle en a trop :
> des centaines de pages de réglementations et de guides qui se citent, se
> remplacent, évoluent d'amendement en amendement. Son problème, c'est de savoir
> **ce qui fait foi aujourd'hui**. Une exigence ratée, c'est un dossier retoqué,
> des semaines de retard, un avion cloué au sol. Suivons sa matinée. »

---

## 🎬 ACTE 1 — Le seuil à ne pas dépasser, et la preuve à un clic (1 min 30)

**📖 Pourquoi Claire pose cette question :** l'écran dans le dossier change la
surface que la tête percute. Avant tout, Claire a besoin du **chiffre qui
gouverne son dossier** : jusqu'à quelle sévérité d'impact son siège modifié
reste-t-il certifiable ? C'est le critère HIC.

**🖱️ Manipulation :**
1. Poser :
   > **Quelle est la limite maximale autorisée du HIC pour la certification des sièges d'avion ?**
2. Attendu : *« 1 000 unités »*, références numérotées [1][2]…
3. **Déplier « sources citées »** et **cliquer un lien** → le PDF s'ouvre
   **à la bonne page**.

**🗣️ Pitch :**
> « Première question : le seuil. Réponse : 1 000 unités. Mais regardez le geste
> important : chaque affirmation est reliée à sa source. Je clique… et le
> document s'ouvre **à la page exacte**. Claire ne croit pas le système sur
> parole — elle vérifie en cinq secondes ce qui lui prenait dix minutes dans un
> PDF de 60 pages. »

**🎯 Ce qu'on démontre :** réponse factuelle sourcée au niveau de l'affirmation,
traçabilité cliquable jusqu'à la page.

**💎 Différenciateur :**
> Les assistants IA du marché citent des *documents* et vous laissent chercher.
> Ici, chaque **phrase** connaît sa source et sa page. C'est la différence entre
> un assistant qu'il faut **relire** et un assistant qu'on peut **auditer**.
> Dans un métier où l'on engage sa signature, c'est ce qui rend l'outil
> utilisable, pas juste impressionnant.

---

## 🎬 ACTE 2 — Le piège du document mort (2 min)

**📖 Pourquoi Claire pose cette question :** modifier un siège certifié suit un
**guide officiel d'approbation des sièges modifiés** (c'est littéralement le
sujet de la série AC 21-25). Claire ressort le dossier de certification
d'origine du siège — 2009 — qui référence l'**AC 21-25A** comme procédure.
Réflexe avant d'engager le travail : ce guide est-il encore la référence ?

**🖱️ Manipulation :**
1. Poser :
   > **Est-ce que l'AC 21-25A est toujours en vigueur, et sinon, par quoi a-t-elle été remplacée ?**
2. Attendu : *« Non… annulée et remplacée par l'AC 21-25B »* + **2 citations
   cliquables = les 2 maillons de la généalogie** : AC 21-25B p.1 (« this AC
   cancels AC 21-25A ») et AC 21-25A p.1 (« AC 21-25 … is canceled »).
3. **Cliquer la citation AC 21-25B** → le PDF s'ouvre p.1 sur la déclaration
   d'annulation.

**🗣️ Pitch :**
> « Le dossier d'origine dit : suivez l'AC 21-25A. Claire vérifie. Réponse : ce
> document est **mort** — annulé et remplacé par l'AC 21-25B. Et le système ne
> se contente pas de l'affirmer : il connaît toute la généalogie — 21-25, puis
> 21-25A, puis 21-25B aujourd'hui en vigueur — et il vous donne **la preuve de
> chaque maillon**. Je clique : voilà la déclaration d'annulation, page 1 du
> document remplaçant. Si Claire avait suivi la procédure de 2009, son dossier
> reposait sur un texte abrogé — l'erreur classique qu'on découvre six mois plus
> tard, au moment du refus. »

**🎯 Ce qu'on démontre :** le système connaît le **cycle de vie** des documents
(qui remplace quoi) et le **prouve** maillon par maillon.

**💎 Différenciateur :**
> Une recherche classique vous donne *tous* les documents qui ressemblent à
> votre question — y compris les morts, sans vous le dire. Les moteurs du marché
> indexent ce qui existe ; ils ne savent pas ce qui **fait encore foi**. Pour
> tout métier réglementé — aéro, pharma, juridique, finance — c'est LA question
> quotidienne.

---

## 🎬 ACTE 2bis — Le coup d'œil : le Référentiel (2 min)

**📖 Pourquoi ce moment :** Claire vient d'obtenir la réponse en *posant une
question*. Mais la généalogie qu'elle vient de lire n'a pas été fabriquée pour
elle à cet instant — elle **existe en permanence**, pour tout le corpus. Ce
moment montre que la réponse du chat n'était que la partie émergée : en dessous,
il y a un référentiel **structuré, daté et prouvé** qu'on peut regarder
directement. C'est le passage de « un assistant qui répond » à « une plateforme
qui connaît votre patrimoine documentaire ».

**🖱️ Manipulation :**
1. Basculer sur l'onglet navigateur **Référentiel** (pré-ouvert, checklist #5).
2. Sur la **Carte** : montrer le sceau « Référentiel cohérent » et les fils
   ambrés, puis **double-cliquer sur AC 21-25B** → tout disparaît sauf la
   lignée et son voisinage. **Cliquer le fil ambré** AC 21-25B → AC 21-25A →
   la fiche preuve s'ouvre (« this AC cancels AC 21-25A ») → *« Ouvrir le PDF
   à la page »* si l'audience accroche.
3. Échap (ou double-clic dans le vide), puis onglet **Frise chronologique** :
   pointer le couloir AC 21-25 → 21-25A (1997) → 21-25B, la barre **verte**
   qui court jusqu'à « aujourd'hui », et les ✝ aux remplacements.
4. Laisser 5 secondes de silence — la frise se lit seule.
5. Revenir sur l'onglet **Chat** pour l'acte 3.

**🗣️ Pitch :**
> « Claire a eu sa réponse en posant la question. Mais regardez d'où elle
> vient. Voici son référentiel — pas une liste de fichiers : son **anatomie**.
> Chaque pastille est un document, chaque fil ambré une succession **prouvée** —
> je clique : voilà la phrase d'annulation, page 1, dans le texte officiel.
>
> Et maintenant la même chose dans le temps. [Frise] Chaque couloir est une
> famille de documents. La barre verte, c'est le texte qui fait foi
> **aujourd'hui**. Les croix, les remplacements. La question de tout à l'heure —
> "l'AC 21-25A est-elle en vigueur ?" — Claire peut aussi y répondre **d'un
> coup d'œil**, sans rien taper : 21-25A s'arrête en chemin, 21-25B court
> jusqu'à aujourd'hui.
>
> Personne n'a dessiné cet écran. Personne n'a saisi ces dates ni ces liens.
> Tout a été **lu dans les documents eux-mêmes** au moment de l'ingestion — y
> compris les dates des documents disparus, retrouvées dans la phrase
> d'annulation de leur remplaçant. Et quand le système ne sait pas dater, il le
> dit : "date inconnue". Il n'invente rien, ici non plus. »
>
> *(Transition vers l'acte 3 :)* « Une question légitime à ce stade : est-ce que
> ce n'est pas simplement l'IA qui est douée ? Testons ça. »

**🎯 Ce qu'on démontre :** le cycle de vie d'une chaîne de documents, positionnés
les uns par rapport aux autres dans le temps, **lisible sans poser de question**
— et chaque lien porte sa preuve cliquable. La réponse du chat et cet écran
sont deux vues du **même actif structuré**.

**💎 Différenciateur :**
> Les outils du marché ont des listes de fichiers et des dossiers ; au mieux un
> historique de versions saisi à la main. Aucun ne sait **reconstruire seul**
> qui remplace qui, depuis quand, preuve à l'appui — parce qu'aucun ne lit le
> contenu pour en faire une structure. C'est ce qui transforme une pile de PDF
> en référentiel : on ne *cherche* plus l'état de son patrimoine documentaire,
> on le *regarde*. Et pour vos contrats, ce même écran montrerait :
> contrat-cadre → avenant 1 → avenant 2, avec l'article exact qui amende quoi.

---

## 🎬 ACTE 3 — LE CLIMAX : la même question, sans la mémoire structurée (2-3 min)

**📖 Pourquoi ce moment :** l'audience vient de voir une réponse impressionnante.
La question légitime dans toutes les têtes : *« c'est l'IA qui fait ça, non ? »*
On y répond par une expérience en direct, à armes égales.

**🖱️ Manipulation :**
1. **Désactiver le toggle « Knowledge Graph »** (il devient gris).
2. **Reposer EXACTEMENT la même question** (l'historique du chat la garde) :
   > **Est-ce que l'AC 21-25A est toujours en vigueur, et sinon, par quoi a-t-elle été remplacée ?**
3. Attendu : badge violet « RAG seul — Knowledge Graph désactivé » +
   > *« INSUFFICIENT_CONTEXT : Le contexte fourni ne contient aucune mention de
   > l'AC 21-25A, ni d'information sur son statut actuel ou sur un éventuel
   > document de remplacement. »*
4. **Réactiver le toggle** avant l'acte suivant.

**🗣️ Pitch :**
> « Expérience honnête. Je désactive le graphe de connaissances. Il reste la
> recherche documentaire moderne — la même technologie que les assistants IA
> que vous connaissez — sur les **mêmes documents**, avec le **même modèle
> d'IA**. Même question…
>
> *"Le contexte ne contient aucune mention de l'AC 21-25A."* Aucune mention ?
> La déclaration d'annulation est dans le corpus — vous venez de la lire, page 1.
> Mais un moteur de recherche découpe les documents en fragments et récupère les
> plus *ressemblants* à la question. La phrase d'annulation ne ressemble pas à
> la question — elle n'est jamais remontée. Et surtout : même remontée, rien
> dans cette architecture ne *relie* les documents entre eux.
>
> Le graphe, lui, a construit la généalogie **au moment de l'ingestion** — elle
> n'attend pas d'avoir de la chance au moment de la question. **La différence
> n'est pas l'intelligence du modèle — vous venez de voir le même modèle
> échouer. C'est la structure de la mémoire.** »

**🎯 Ce qu'on démontre :** l'A/B en direct — même corpus, même LLM, seule
l'architecture de mémoire change. Le différenciateur cesse d'être un argument :
il devient un fait observé par l'audience.

**💎 Différenciateur :**
> C'est le cœur. Les outils du marché répondent à « quels passages ressemblent
> à ma question ? ». Celui-ci répond à « que sait-on, qui le dit, et qu'est-ce
> qui fait encore foi ? ». Ce n'est pas une course au meilleur modèle d'IA —
> c'est une autre catégorie d'outil.

---

## 🎬 ACTE 4 — La confiance : savoir se taire (1 min 30)

**📖 Pourquoi Claire pose cette question :** Claire est ingénieure — elle ne
fait pas confiance à un outil qu'elle n'a pas **piégé**. Avant de s'appuyer sur
lui pour un dossier qu'elle signera, elle pose volontairement une question dont
elle SAIT que la réponse n'est pas dans sa base (les sièges éjectables
militaires — un autre monde que les sièges passagers civils).

**🖱️ Manipulation :**
1. (Toggle KG réactivé.) Poser :
   > **Quelles sont les exigences de certification des sièges éjectables militaires selon la MIL-S-9479 ?**
2. Attendu : **refus motivé** — le corpus ne couvre pas ce point, le système le
   dit au lieu d'inventer.

**🗣️ Pitch :**
> « Dernière question — et Claire la pose en connaissance de cause : elle piège
> l'outil. Et il donne la réponse la plus importante de toute la démo : **"je ne
> sais pas, et voici pourquoi"**. En certification, une réponse inventée est
> pire que pas de réponse : elle finit dans un dossier avec une signature
> dessous. Sur notre banc d'évaluation, cette discipline d'abstention atteint
> 83 %, contre 65 % pour la même IA sans le graphe. C'est *ça* qui permet à
> Claire de s'y fier les 95 autres fois où il répond. »

**🎯 Ce qu'on démontre :** l'abstention calibrée — le système connaît les
limites de son corpus et les déclare.

**💎 Différenciateur :**
> Le réflexe du marché est de toujours répondre — optimisé pour la satisfaction
> immédiate, pas pour la fiabilité. Un outil qui ne sait pas se taire reporte la
> vérification sur l'humain à **chaque** réponse : le gain de temps s'évapore.

*(**Option audience technique — Acte 4 bis : sauver un essai déjà payé.**
Contexte : dans les archives d'essais, Claire trouve un essai dynamique où la
catapulte a tiré trop fort — pic à 15g au lieu des 14g requis — et la charge
lombaire mesurée, 1 590 lb, dépasse la limite de 1 500 lb. Essai à jeter, ou
corrigeable ? Poser :*
> *« Une charge lombaire de 1590 lb a été mesurée lors d'un essai dont le pic était de 15g au lieu des 14g requis. À quelle valeur cette charge peut-elle être ramenée par proportionnalité, selon la guidance ? »*
*→ attendu : la règle ET le calcul, 14/15 × 1590 = **1 484 lb** < 1 500 →
l'essai est sauvé. Pitch : « il a chaîné la règle de proportionnalité et son
application chiffrée. Claire vient d'éviter de repayer un essai. »)*

---

## 🎬 ACTE 5 — La chute : l'Atlas (2 min)

**📖 Pourquoi on montre ça :** la démo des questions est finie — l'audience
pense avoir tout vu. On introduit l'Atlas comme un élément *banal* du décor
(la documentation de formation de l'équipe) pour révéler ensuite qu'il est
généré. La surprise ne marche que si la navigation silencieuse laisse croire à
une documentation rédigée à la main.

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
> plus un livrable, c'est un **sous-produit permanent** du système.

---

## 🎬 CLÔTURE (1 min — pas de manipulation)

**🗣️ Pitch :**
> « Tout ce que vous avez vu repose sur une seule idée : ce système ne stocke
> pas des *pages*, il stocke des **affirmations vérifiables** — qui les a dites,
> quand, ce qui les remplace. Vous l'avez vu répondre et prouver, repérer un
> document mort, refuser d'inventer, rédiger sa propre documentation — et vous
> avez vu le même modèle d'IA échouer dès qu'on lui retire cette mémoire. La
> différence n'est pas l'intelligence du modèle — c'est **la structure de la
> mémoire**. Et c'est ce qui change un outil de recherche en un outil de
> décision. »

---

## ❓ OBJECTION PROBABLE : « Et les contradictions entre documents ? »

*(Ne pas l'aborder spontanément — mais si la question vient, c'est un point FORT :)*

> « Excellente question. Le système détecte les tensions candidates entre
> documents à l'ingestion — sur ce corpus, il en a repéré 281. Puis il fait ce
> qu'un bon analyste ferait : il **relit les passages sources de chaque paire**
> pour vérifier qu'elles parlent bien de la même chose, dans les mêmes
> conditions. Verdict, traçé paire par paire : ce corpus est **cohérent** — ce
> qui est normal, FAA et EASA harmonisent volontairement leurs exigences
> sièges. La plupart des tensions apparentes étaient des conversions d'unités,
> des conditions d'essai différentes, ou des citations historiques.
>
> Et c'est exactement le comportement que vous voulez : un système qui ne crie
> pas au loup. Le jour où un document **réellement** contradictoire entrera
> dans votre base — une nouvelle révision qui change un seuil, une exigence
> client incompatible — lui seul déclenchera l'alerte, preuve à l'appui. »

---

## ❓ OBJECTION (connaisseur) : « Pourquoi votre RAG n'a pas trouvé le chunk ? L'info y est forcément ! »

*(Objection LÉGITIME et probable d'un profil technique après l'acte 3. Mesuré
sur le corpus réel, 06/06 — ces chiffres sont les nôtres, vérifiés :)*

**Les faits (à dérouler calmement) :**

> « Vous avez raison : la phrase "this AC cancels AC 21-25A" est bien dans un
> passage indexé — page 1 de l'AC 21-25B. On a mesuré : face à cette question,
> ce passage est classé **au-delà du 200e rang**. L'IA ne lit que les 12
> premiers. Il n'avait aucune chance d'arriver jusqu'à elle. Pourquoi ?
>
> Trois mécanismes qui se cumulent, et aucun n'est de la malchance :
> 1. **La recherche sémantique est quasi aveugle aux identifiants.** Pour un
>    modèle vectoriel, "AC 21-25A", "AC 25-17A" et "AC 25.562-1A" sont presque
>    le même vecteur. Or le seul mot qui distingue la question… c'est
>    l'identifiant.
> 2. **L'écrasement par la masse.** Le document qui contient la réponse fait
>    21 passages ; ses voisins en font des centaines. Sur une question au
>    profil générique ("ce texte est-il en vigueur ?"), il suffit de 12
>    passages "ressemblants" venus des gros documents pour saturer la fenêtre.
> 3. **La dilution.** La phrase d'annulation est une ligne administrative sur
>    une page de garde pleine d'en-têtes : le vecteur du passage "ressemble" à
>    une page de garde, pas à une annulation. »

**Si l'objection se précise (« avec un retrieval hybride BM25 vous l'auriez ») :**

> « Exact — un index lexical remonterait probablement *ce* passage, et nous
> utilisons nous-mêmes l'hybride en interne. Mais ça reste améliorer ses
> chances à une **loterie de classement** jouée au moment de chaque question.
> Et même remonté, ce passage ne donne qu'UN maillon : rien dans cette
> architecture ne relie 21-25 → 21-25A → 21-25B en généalogie datée et
> prouvée. Nous ne jouons pas à cette loterie : la lignée a été **lue et
> construite à l'ingestion**, une fois pour toutes. La différence n'est pas un
> réglage de recherche — c'est la structure de la mémoire. »

---

## ❓ OBJECTION (si la page benchmarks est montrée) : « Le RAG classique vous bat sur les questions factuelles ! »

*(Vrai sur ce run : précision des références 69 % vs 80 %. Instruit ligne par
ligne le 06/06 — 7 questions perdantes, deux causes connues :)*

> « Bien vu — et on sait exactement pourquoi, question par question. Sur la
> recherche brute d'un identifiant isolé, un lecteur de fragments a aujourd'hui
> un léger avantage : deux des sept écarts viennent de faits que notre filtre
> d'extraction a écartés (correctif déjà codé, actif à la prochaine ingestion),
> les cinq autres d'un réglage de recherche d'identifiants identifié dans
> notre backlog. Rien d'inexpliqué.
>
> Maintenant regardez les colonnes d'à côté : quand il s'agit de savoir **ce
> qui fait foi**, de **comparer** deux sources, ou surtout de **ne pas
> inventer** quand l'information n'existe pas, le rapport s'inverse largement.
> Dans vos métiers, l'erreur qui coûte n'est pas de rater un numéro de
> paragraphe — c'est de fonder un dossier sur un texte abrogé ou sur une
> réponse fabriquée. C'est là que nous mettons la fiabilité. »

---

## 🧯 PLAN B / INCIDENTS

| Symptôme | Réflexe |
|---|---|
| Réponse > 60 s ou erreur de synthèse | « Le fournisseur d'IA a un hoquet — c'est précisément pour ça qu'on ne fait jamais confiance à une IA sans preuve » → reposer la question ; sinon capture du deck |
| Abstention inattendue sur les actes 1-2 | Reposer telle quelle (variance fournisseur) ; 2e échec → capture du deck + « résultat d'hier, on regardera en direct après » |
| Le RAG (toggle off) répond correctement à l'acte 3 | Sourire : « il a eu de la chance sur ce tirage — c'est justement le problème : sans graphe, retrouver la généalogie est une loterie ; avec, elle est pré-construite et systématique » *(validé 2× en échec, risque faible)* |
| Citation non cliquable / PDF ne s'ouvre pas | Passer à l'autre citation ; le fix de résolution couvre tous les docs mais un onglet bloqué par le navigateur peut nécessiter d'autoriser les pop-ups |
| Référentiel : « date inconnue » partout / frise sans graduations | Données chargées avant un redémarrage backend → **F5 dur** sur l'onglet (Ctrl+Shift+R). Vérifié à la checklist #5 pour ne pas le découvrir en live |
| Référentiel : carte brouillonne après manipulations | Chip « ⟲ Réorganiser » (layout auto) ; Échap sort du focus |
| Page Atlas vide / thème vide | Rafraîchir ; sinon sauter à la clôture (l'acte 5 est sautable) |

## 📝 Notes opérateur

- Questions à **copier-coller depuis ce guide** (formulations validées en live,
  bras KG ET bras RAG pour l'acte 2/3).
- Ne PAS purger, ré-ingérer ni redémarrer quoi que ce soit entre la répétition
  et la démo.
- Répétition complète la veille : dérouler les 6 actes dans l'ordre (dont le
  2bis Référentiel), chronométrer, faire les captures du deck de secours à
  cette occasion (inclure : carte en focus AC 21-25B, fiche preuve ouverte,
  frise avec le couloir AC 21-25).
- Acte 2bis : répéter le **geste** double-clic → fil ambré → preuve → frise ;
  c'est une chorégraphie de 30 s qui doit être fluide pour porter le « coup
  d'œil ». Si le temps presse, la frise SEULE suffit (sauter la carte).
- Question de fond aéro de l'audience : le **lexique** couvre 95 % des cas ;
  sinon « excellente question, je la note pour nos experts métier ».
