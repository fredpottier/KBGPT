# Scénario de démo — « La semaine de Claire » (certification sièges aéro)

*Draft 06/06/2026 — à retravailler avec Fred. Toutes les questions/réponses ont été
validées en live les 05-06/06 sur le corpus aéro staged (tenant default).*

## Le principe

Pas un catalogue de fonctionnalités : **une personne, un dossier, une deadline**.
Chaque question découle de la précédente dans SON travail. Le spectateur ne voit
jamais « une fonctionnalité » — il voit Claire éviter une erreur ou gagner une heure.

## Mise en situation (1 min)

> **Claire est ingénieure certification chez un équipementier de sièges d'avion.**
> Lundi, son client compagnie aérienne veut modifier des sièges en service :
> nouvelle ceinture, écran IFE intégré au dossier. Le siège est certifié **FAA
> et EASA** (bi-certification — la réalité du métier). Claire doit dire au client
> ce qui est requis, vite, et **sans erreur** : une exigence ratée = un dossier
> retoqué = des semaines de retard et un avion cloué.
>
> Son problème n'est pas de trouver *de l'information* — elle en a trop : ACs,
> ETSOs, CFR, SAE, NPAs… des centaines de pages qui se citent, se remplacent et
> parfois se contredisent. Son problème est de savoir **ce qui fait foi**.

## Acte 1 — S'orienter : l'Atlas (2 min)

Claire ouvre l'**Atlas** : la cartographie narrative que le système a construite
tout seul depuis les documents — thèmes, articles de synthèse, claims sourcés.
Elle parcourt le thème « Safety & Compliance » pour se remettre le domaine en tête.

**Valeur racontée** : « Personne n'a écrit ces articles. Le système a lu les 24
documents et a organisé le savoir. C'est l'onboarding d'un nouvel ingénieur,
ou la revue de périmètre avant un dossier. » *(le mode « parcourir »)*

## Acte 2 — Vérifier un fait, et la preuve à un clic (1 min 30)

Claire passe au chat *(le mode « interroger »)*. Première vérification basique :

> **« Quelle est la limite maximale autorisée du HIC pour la certification des sièges d'avion ? »**

Réponse : 1 000 unités, sourcée. **Le geste clé : elle clique la citation → le
PDF s'ouvre À LA BONNE PAGE.** « Elle ne croit pas le système sur parole — elle
vérifie en 5 secondes au lieu de chercher dans 60 pages. C'est la différence
entre un assistant qu'on doit relire et un assistant qu'on peut auditer. »

## Acte 3 — Le piège du document mort (2 min)

Dans le dossier de certification d'origine (2009), le siège référence l'AC 21-25A.

> **« Est-ce que l'AC 21-25A est toujours en vigueur, et sinon, par quoi a-t-elle été remplacée ? »**

Réponse : annulée, remplacée par l'AC 21-25B — **avec la phrase d'annulation
citée comme preuve**, et la lignée complète (21-25 → 21-25A → 21-25B).

**Valeur racontée** : « Le système connaît la *généalogie* des documents. Claire
a failli bâtir sa réponse client sur un texte mort — l'erreur classique qui fait
retoquer un dossier. Et remarquez : il ne dit pas seulement "remplacée", il
**prouve** l'annulation. »

## Acte 4 — Le climax : la divergence que personne ne voit (3 min)

Le siège modifié doit repasser les essais dynamiques HIC, côté FAA **et** EASA.
Claire vérifie le protocole d'impact tête :

> **« Selon la FAA et l'EASA, l'évaluation du HIC à 1000 doit-elle provenir d'un impact franc (solid strike), ou s'applique-t-elle aussi en cas de coup glissant (glancing blow) ? »**

→ **Bandeau rouge « Divergence entre autorités »** : la FAA exige un impact
franc ; l'EASA applique la limite quel que soit le contact. Les deux textes, cités.

**Puis le coup de théâtre** : Fred désactive le toggle « Knowledge Graph »
(« voyons ce que répondrait un assistant IA classique sur les mêmes documents »)
et repose la question. → Le RAG répond à côté ou avoue ne pas savoir.

**Valeur racontée** : « Les deux exigences existent, dans deux documents
différents. Un moteur de recherche — même excellent — lit des passages ; il ne
*confronte* jamais deux textes. Ici, la contradiction a été détectée à
l'ingestion et attend Claire. Si elle avait qualifié son essai selon la seule
FAA, le dossier EASA était mauvais. **C'est un essai sur catapulte à refaire :
des dizaines de milliers d'euros et six semaines.** »

## Acte 5 — La confiance : savoir se taire (1 min 30)

Claire pousse une question dont la réponse n'est PAS dans le corpus
(ex : une question sur un standard non couvert).

→ Le système **refuse de répondre** et dit pourquoi, au lieu d'inventer.

**Valeur racontée** : « En certification, une réponse inventée est pire que pas
de réponse. Ce refus est calibré : sur notre banc de test, 83 % de discipline
contre 65 % pour un RAG classique. C'est ce qui permet à Claire de s'y fier. »

*(Option si l'audience est technique — Acte 5 bis : le calcul réglementaire :*
> *« Une charge lombaire de 1590 lb a été mesurée lors d'un essai dont le pic était de 15g au lieu des 14g requis. À quelle valeur cette charge peut-elle être ramenée par proportionnalité, selon la guidance ? »*
*→ règle + calcul 14/15 × 1590 = 1484 lb, sourcés. « Il a retrouvé la règle ET
son application chiffrée — deux faits chaînés. »)*

## Clôture (1 min)

> « Tout ce que vous avez vu repose sur une seule idée : ce système ne stocke pas
> des *pages*, il stocke des **affirmations vérifiables** — qui les a dites, quand,
> ce qui les remplace, ce qui les contredit. La différence avec un assistant IA
> générique, ce n'est pas l'intelligence du modèle — c'est **la structure de la
> mémoire**. Et c'est ce qui change un outil de recherche en un outil de décision. »

## Logistique / plan B

- **Durée totale : ~12 min** + questions. Chaque acte est sautable indépendamment.
- Toutes les questions sont **pré-validées** ; les rejouer 1× samedi pour confirmer
  (les gardes stabilité sont en place, mais on ne démontre jamais sans répétition).
- **Plan B par acte** : captures d'écran des réponses validées dans un deck de
  secours (si Novita tousse en live).
- Premier appel après redémarrage app = lent (~50 s, chargement modèles) →
  **chauffer le système avant la démo** (poser 1 question quelconque).
- Ne PAS toucher au corpus / pas de ré-ingestion avant la démo (décision 06/06).

## À décider avec Fred

1. **Audience exacte** ? (technique aéro / dirigeant / juriste) → ajuste la
   profondeur de l'acte 4 et l'option 5 bis.
2. L'Atlas en ouverture (acte 1) ou en « et il y a aussi… » de clôture ?
3. Qui pilote ? (Fred narre + clique, ou narration partagée)
4. Chiffres du bench à l'écran ou seulement en voix off ?
