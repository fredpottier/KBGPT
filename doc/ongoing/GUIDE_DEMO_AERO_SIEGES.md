# Guide de démo OSMOSIS — « La semaine de Claire »

*Guide opérateur, 06/06/2026. Toutes les questions ont été validées en live sur le
corpus aéro (24 documents de certification sièges FAA/EASA). Durée cible : 12-14 min.*

---

## ✈️ AVANT LA DÉMO (checklist, ~10 min avant)

| # | Manipulation | Pourquoi |
|---|---|---|
| 1 | `./kw.ps1 status` → vérifier que app, frontend, neo4j, qdrant, redis sont **Up** | Pas de surprise infra |
| 2 | Ouvrir http://localhost:3000/chat et poser une question quelconque (ex. la question de l'acte 1) | **Chauffer le système** : le 1er appel après redémarrage charge les modèles (~50 s) ; les suivants tombent à 25-40 s |
| 3 | Vérifier que le toggle **« Knowledge Graph »** est **activé** (bouton bleu) | L'acte 3 repose sur sa bascule |
| 4 | Ouvrir http://localhost:3000/atlas dans un 2e onglet, navigation prête | L'acte 5 doit s'ouvrir sans chercher |
| 5 | Deck de secours (captures des réponses) accessible | Plan B si le LLM de synthèse tousse |

⚠️ Latence normale d'une réponse : **25-45 s**. Assumer : « il vérifie chaque fait,
il ne complète pas des phrases » — la latence devient un argument, pas une gêne.

---

## 🎬 MISE EN SITUATION (1 min — pas de manipulation)

**🗣️ Pitch :**
> « Je vous présente Claire. Elle est ingénieure certification chez un équipementier
> de sièges d'avion. Ce matin, son client compagnie aérienne veut modifier des sièges
> en service : nouvelle ceinture, écran intégré au dossier. Le siège est certifié
> **FAA et EASA** — la double certification, c'est la réalité du métier.
>
> Le problème de Claire n'est pas de trouver de l'information — elle en a *trop* :
> Advisory Circulars, ETSOs, CFR, normes SAE… des centaines de pages qui se citent,
> se remplacent, et parfois se contredisent. Son problème, c'est de savoir
> **ce qui fait foi**. Une exigence ratée, c'est un dossier retoqué, des semaines de
> retard, un avion cloué au sol. Regardons sa matinée. »

---

## 🎬 ACTE 1 — Vérifier un fait, et la preuve à un clic (1 min 30)

**🖱️ Manipulation :**
1. Dans le chat, poser :
   > **Quelle est la limite maximale autorisée du HIC pour la certification des sièges d'avion ?**
2. Réponse attendue : *« 1 000 unités »*, avec références numérotées [1][2]…
3. **Déplier « sources citées »** puis **cliquer le lien d'une citation** → le PDF
   s'ouvre dans un onglet, **directement à la bonne page**.

**🗣️ Pitch :**
> « Première vérification de Claire : le critère de blessure à la tête, le HIC.
> Réponse : 1 000 unités. Mais regardez le geste important : chaque affirmation est
> reliée à sa source. Je clique… et le document s'ouvre **à la page exacte**.
> Claire ne croit pas le système sur parole — elle vérifie en cinq secondes ce qui
> lui prenait dix minutes de recherche dans un PDF de 60 pages. »

**🎯 Ce qu'on démontre :** la réponse factuelle sourcée au niveau de l'affirmation
(pas du document), et la traçabilité cliquable jusqu'à la page.

**💎 Différenciateur :**
> Les assistants IA du marché citent des *documents* — « voir AC 25.562-1B » — et
> vous laissent chercher. Ici, chaque **phrase** de la réponse connaît sa source et
> sa page. C'est la différence entre un assistant qu'il faut **relire** et un
> assistant qu'on peut **auditer**. Dans un métier où l'on engage sa signature,
> c'est ce qui rend l'outil utilisable, pas juste impressionnant.

---

## 🎬 ACTE 2 — Le piège du document mort (2 min)

**🖱️ Manipulation :**
1. Poser :
   > **Est-ce que l'AC 21-25A est toujours en vigueur, et sinon, par quoi a-t-elle été remplacée ?**
2. Réponse attendue : *« Non… annulée et remplacée par l'AC 21-25B »* + la phrase
   d'annulation citée comme preuve + la lignée (21-25 → 21-25A → 21-25B).

**🗣️ Pitch :**
> « Le dossier de certification d'origine de ce siège date de 2009 et référence
> l'AC 21-25A. Claire vérifie. Réponse : ce document est **mort** — annulé et
> remplacé par l'AC 21-25B. Et regardez : le système ne se contente pas de
> l'affirmer, il **cite la déclaration d'annulation** comme preuve, et il connaît
> toute la généalogie : 21-25, puis 21-25A, puis 21-25B aujourd'hui en vigueur.
> Claire a failli bâtir sa réponse client sur un texte abrogé — c'est l'erreur
> classique qui fait retoquer un dossier six mois plus tard. »

**🎯 Ce qu'on démontre :** le système connaît le **cycle de vie** des documents
(qui remplace quoi, depuis quand) et le restitue avec preuve.

**💎 Différenciateur :**
> Une recherche classique vous donne *tous* les documents qui ressemblent à votre
> question — y compris les morts, sans vous le dire. Les moteurs d'entreprise du
> marché indexent ce qui existe ; ils ne savent pas ce qui **fait encore foi**.
> Ici, la généalogie documentaire est une connaissance de premier rang : le
> système distingue l'histoire de l'état courant. Pour tout métier réglementé
> (aéro, pharma, juridique, finance), c'est LA question quotidienne.

---

## 🎬 ACTE 3 — LE CLIMAX : la divergence que personne ne voit (3-4 min)

**🖱️ Manipulation (en 2 temps) :**
1. Poser :
   > **Selon la FAA et l'EASA, l'évaluation du HIC à 1000 doit-elle provenir d'un impact franc (solid strike), ou s'applique-t-elle aussi en cas de coup glissant (glancing blow) ?**
2. Réponse attendue : **bandeau rouge « Divergence entre autorités réglementaires »**
   + les deux positions citées (FAA AC 25.562-1B : impact franc exigé ; EASA
   ETSO-C127c : la limite s'applique quel que soit le contact).
3. **Coup de théâtre** : désactiver le toggle **« Knowledge Graph »** (il devient
   gris) et **reposer exactement la même question**.
4. Réponse attendue : le badge violet « RAG seul » s'affiche ; la réponse passe à
   côté de la divergence (elle affirme à tort qu'il n'y a pas de distinction, ou
   avoue ne pas savoir — les deux servent le propos).
5. **Réactiver le toggle** avant l'acte suivant.

**🗣️ Pitch (temps 1) :**
> « Le siège modifié doit repasser les essais d'impact tête — côté FAA *et* côté
> EASA. Claire vérifie le protocole. Et là… le système lève un drapeau rouge :
> les deux autorités ne disent **pas la même chose**. La FAA exige que la
> démonstration provienne d'un impact franc. L'EASA applique la limite quel que
> soit le type de contact. Les deux textes sont là, cités. Si Claire avait
> qualifié son essai selon la seule FAA, son dossier EASA était mauvais.
> Concrètement ? **Un essai sur catapulte à refaire : des dizaines de milliers
> d'euros et six semaines de programme.** »

**🗣️ Pitch (temps 2 — la bascule) :**
> « Maintenant, une expérience honnête. Je désactive le graphe de connaissances —
> il ne reste que la recherche documentaire moderne, la même technologie que les
> assistants IA que vous connaissez, sur les **mêmes documents**, avec le **même
> modèle d'IA**. Même question… Regardez : la divergence a disparu. L'information
> existe pourtant — mais elle vit dans **deux documents différents**, et un moteur
> de recherche lit des passages, il ne **confronte** jamais deux textes entre eux.
> Ici, la contradiction a été détectée au moment de l'ingestion des documents —
> elle attendait Claire. »

**🎯 Ce qu'on démontre :** la détection de contradictions inter-sources calculée
à l'avance dans le graphe + la preuve A/B en direct que ce n'est pas le modèle
d'IA qui fait la différence.

**💎 Différenciateur :**
> C'est le cœur. Tous les acteurs du marché — moteurs d'entreprise, copilotes,
> RAG — répondent à la question « que disent mes documents ? ». Aucun ne répond à
> « mes documents sont-ils **d'accord entre eux** ? ». Cette question-là exige de
> mémoriser des affirmations, pas des pages, et de les confronter en permanence.
> Et vous venez de le constater vous-mêmes : même corpus, même modèle — seule la
> **structure de la mémoire** change le résultat. Ce n'est pas une course au
> meilleur modèle d'IA, c'est une autre catégorie d'outil.

---

## 🎬 ACTE 4 — La confiance : savoir se taire (1 min 30)

**🖱️ Manipulation :**
1. (Toggle KG réactivé.) Poser une question hors corpus, ex. :
   > **Quelles sont les exigences de certification des sièges éjectables militaires selon la MIL-S-9479 ?**
2. Réponse attendue : **refus motivé** — le corpus ne couvre pas ce point, le
   système le dit au lieu d'inventer.

**🗣️ Pitch :**
> « Dernière question de la matinée — volontairement hors du périmètre des
> documents. Et la réponse la plus importante de toute la démo : **"je ne sais
> pas, et voici pourquoi"**. En certification, une réponse inventée est pire que
> pas de réponse : elle finit dans un dossier avec une signature dessous. Sur
> notre banc d'évaluation, cette discipline d'abstention atteint 83 %, contre
> 65 % pour la même IA sans le graphe. C'est *ça* qui permet à Claire de s'y
> fier les 95 autres fois où il répond. »

**🎯 Ce qu'on démontre :** l'abstention calibrée — le système connaît les limites
de son corpus et les déclare.

**💎 Différenciateur :**
> Le réflexe du marché est de toujours répondre — c'est optimisé pour la
> satisfaction immédiate, pas pour la fiabilité. Un outil qui ne sait pas se
> taire reporte la vérification sur l'humain à **chaque** réponse, ce qui annule
> le gain de temps. La valeur d'un assistant professionnel ne se mesure pas à ce
> qu'il sait dire, mais à la confiance qu'on peut accorder à ce qu'il dit.

*(Option audience technique — Acte 4 bis : poser « Une charge lombaire de 1590 lb
a été mesurée lors d'un essai dont le pic était de 15g au lieu des 14g requis. À
quelle valeur cette charge peut-elle être ramenée par proportionnalité, selon la
guidance ? » → attendu : la règle ET le calcul, 14/15 × 1590 = **1484 lb**, sourcés.
Pitch : « il a chaîné deux faits : la règle de proportionnalité, puis son
application chiffrée — c'est du raisonnement sur des faits vérifiés, pas de la
recherche. »)*

---

## 🎬 ACTE 5 — La chute : l'Atlas (2 min)

**🖱️ Manipulation :**
1. Basculer sur l'onglet **http://localhost:3000/atlas** déjà ouvert.
2. **Naviguer 30 secondes EN SILENCE** (c'est le silence qui prépare la chute) :
   homepage → un thème (ex. « Conformité et vérification réglementaires ») →
   un chapitre (ex. « Energy-Absorbing Seating in Crash Scenarios ») → faire
   défiler l'article (sections, résumé).
3. Puis poser la question à l'audience (pitch ci-dessous).

**🗣️ Pitch :**
> « Une dernière chose. Quand Claire a rejoint ce programme, il a fallu se former.
> Voici la documentation de référence de l'équipe. » *(navigation silencieuse)*
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
> et qu'aucune ne maintient : elle est périmée le jour où elle est publiée. Ici,
> ce n'est plus un livrable, c'est un **sous-produit permanent** du système. Les
> outils du marché cherchent dans vos documents ; celui-ci en **redistille le
> savoir** — et le tient à jour sans qu'on le lui demande.

---

## 🎬 CLÔTURE (1 min — pas de manipulation)

**🗣️ Pitch :**
> « Tout ce que vous avez vu repose sur une seule idée : ce système ne stocke pas
> des *pages*, il stocke des **affirmations vérifiables** — qui les a dites, quand,
> ce qui les remplace, ce qui les contredit. Vous l'avez vu répondre et prouver,
> repérer un document mort, confronter deux autorités, refuser d'inventer, et
> même rédiger sa propre documentation. La différence avec un assistant IA
> générique, ce n'est pas l'intelligence du modèle — vous avez vu le même modèle
> échouer sans le graphe. C'est **la structure de la mémoire**. Et c'est ce qui
> change un outil de recherche en un outil de décision. »

---

## 🧯 PLAN B / INCIDENTS

| Symptôme | Réflexe |
|---|---|
| Réponse > 60 s ou erreur de synthèse | « Le fournisseur d'IA a un hoquet — c'est précisément pour ça qu'on ne fait jamais confiance à une IA sans preuve » → reposer la question (le retry interne récupère en général) ; sinon capture du deck |
| Abstention inattendue sur une question des actes 1-3 | Reposer la question telle quelle (variance fournisseur) ; si 2e échec → capture du deck + « je vous montre le résultat d'hier, on regardera en direct après » |
| La divergence acte 3 ne s'affiche pas | Reposer la question EXACTEMENT comme écrite (les termes solid strike / glancing blow comptent) |
| Le RAG (toggle off) répond CORRECTEMENT à l'acte 3 | Assumer avec le sourire : « il a eu de la chance sur ce tirage — c'est justement ça le problème : sans graphe, la détection est une loterie ; avec, elle est systématique » |
| Page Atlas vide / thème vide | Rafraîchir ; sinon passer directement à la clôture (l'acte 5 est sautable) |

## 📝 Notes opérateur

- Questions à copier-coller depuis ce guide (la formulation exacte compte pour
  les actes 3 et 4 bis).
- Ne PAS purger, ré-ingérer ni redémarrer quoi que ce soit entre la répétition et
  la démo.
- Répétition complète recommandée la veille : dérouler les 5 actes dans l'ordre,
  chronométrer, faire les captures du deck de secours à cette occasion.
