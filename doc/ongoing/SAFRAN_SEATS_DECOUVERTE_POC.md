# Safran Seats — Guide de découverte (Armand) + Cadrage POC corpus public

> **Document vivant** (doc/ongoing). 2026-05-31. Préparation du déjeuner Armand (~10/06) et du POC.
> **Hypothèse à tester** : la conformité/certification siège chez Safran Seats est un problème
> *douloureux, coûteux et budgété*, où le raisonnement cross-document traçable + temporel + abstention
> apporte une valeur que ni l'enterprise search (Glean/Copilot) ni les ALM (Jama/Visure/DOORS) ne donnent.
> **But du déjeuner** : valider ou ENTERRER cette hypothèse, et tester l'appétit pour une co-innovation.
> Ce n'est PAS une démo de vente.

---

## PARTIE 1 — Guide de découverte

### 1.1 Posture (à ne pas oublier)
- **Extraire la douleur, pas pitcher.** Le piège mortel = récolter un « ah oui c'est intéressant »
  poli (faux signal qui tue les fondateurs).
- **Mom Test** : faire raconter du **passé concret et spécifique**, jamais de l'hypothétique
  (« la dernière fois que… », pas « est-ce que vous utiliseriez… »).
- **Chiffrer la douleur** : temps passé, coût d'une erreur, fréquence. Sans chiffre, pas de douleur.
- **Écouter l'émotion** : frustration, peur de l'erreur, charge mentale = signaux forts.
- Ne mentionner OSMOSIS qu'**à la fin**, et seulement pour ouvrir la porte co-innovation.

### 1.2 Le workflow d'aujourd'hui (comprendre l'existant)
- « Concrètement, quand tu dois établir/vérifier la conformité d'un siège à une exigence, tu pars
  d'où ? Tu ouvres quoi ? Combien d'allers-retours entre documents ? »
- « Quels documents tu croises en pratique : CS-25 / FAR 25, les ETSO/TSO-C127, les ACs, les
  rapports d'essai, les specs client ? Lesquels sont les plus pénibles à recouper ? »
- « Quels outils tu utilises aujourd'hui (matrices Excel, DOORS/Jama, PLM, SharePoint) ? Qu'est-ce
  qu'ils ne savent PAS faire ? »

### 1.3 La douleur & son coût (le cœur)
- « La dernière fois qu'une exigence a été **ratée, mal lue, ou périmée** — qu'est-ce que ça a
  coûté ? (cert finding, re-test, retard de livraison, programme bloqué) »
- « Combien de temps prend l'évaluation de conformité sur un nouveau programme / une nouvelle config ? »
- « Qu'est-ce qu'un ingénieur senior **re-vérifie systématiquement derrière un junior** ? »
  *(→ c'est exactement ce qu'OSMOSIS doit automatiser)*

### 1.4 Le change-impact (le différenciateur clé)
- « Quand un client demande un changement (housse, mousse, IFE, dinette…), comment tu déterminards
  **l'impact de certification** ? Combien de temps ? Qu'est-ce qui rend ça dur ? »
- « Le siège est certifié comme **assemblage complet** : comment tu traces qu'un petit changement
  ne casse pas la conformité ailleurs (flammabilité ↔ dynamique 16g) ? »

### 1.5 Le temporel & la confiance (l'angle OSMOSIS)
- « Comment tu sais quel **niveau d'amendement** (TSO-C127 a/b/c, amendement CS-25) s'applique à la
  base de certification d'un programme donné ? »
- « Quand une réglementation ou un AD change, comment tu retrouves **tout** ce qui est affecté ? »
- « Tu préférerais un outil qui te donne une réponse **confiante**, ou un qui te dit *“je ne peux pas
  le confirmer depuis les textes, voici les 2 exigences en tension”* ? » *(test direct de l'abstention)*

### 1.6 Ouverture co-innovation (la fin)
- « Si un outil savait répondre à ces questions **en citant le texte exact**, en **signalant ce qui
  est périmé**, et en **s'abstenant** plutôt qu'inventer — ça te ferait gagner quoi ? »
- « Est-ce que ça vaudrait le coup que je te montre une démo sur le **corpus réglementaire public**
  (sans aucune donnée Safran) ? Et si c'est convaincant, explorer une tranche de docs internes
  non sensibles en co-innovation ? »

### 1.7 Signaux à lire
- 🟢 **Vert** : il chiffre la douleur sans qu'on insiste ; raconte un incident précis ; dit « ça me
  changerait la vie » ; propose lui-même des cas ; parle budget/équipe.
- 🔴 **Rouge** : tiède, généraliste, « intéressant mais… » ; pas d'exemple concret ; « il faudrait voir
  avec X » sans engagement. → écouter ce signal, NE PAS le rationaliser.

### 1.8 Pièges
- Pitcher trop tôt → il devient poli, plus de vraie douleur.
- Questions qui mènent (« ce serait utile, non ? ») → réponses de complaisance.
- Confondre enthousiasme et intention. Seul un **prochain pas concret** (docs partagés, 2e réunion,
  intro à un ingénieur cert) compte.

---

## PARTIE 2 — Cadrage du POC « corpus public »

### 2.1 Objectif du POC
Démontrer, sur un corpus **100 % public et non sensible** (aucune donnée Safran/ITAR), qu'OSMOSIS
fait **4 choses que les incumbents ne font pas** sur un corpus de certification :
1. **Traçabilité** — chaque réponse cite la clause exacte (CS-25 / AC / TSO).
2. **Temporel / supersession** — connaît les niveaux d'amendement, signale ce qui a changé/est périmé.
3. **Change-impact cross-document** — relie un changement à toutes les exigences affectées.
4. **Abstention honnête / faux-présupposé** — dit « je ne peux pas confirmer » au lieu d'inventer.

Critère de réussite : **un expert (Armand) juge les réponses “fiables, j'agirais dessus”**, et voit
la différence nette avec un ChatGPT/Copilot (confiant mais non sourcé / faux sur les amendements /
n'abstient jamais).

### 2.2 Corpus (tout PUBLIC — à ingérer)
- **EASA CS-25** (Certification Specifications, Large Aeroplanes) : sous-parties pertinentes
  25.561 / 25.562 (atterrissage d'urgence, dynamique), 25.785 (sièges), 25.853 (flammabilité) + AMC.
- **FAA 14 CFR Part 25** (équivalents 25.562 / 25.785 / 25.853).
- **TSO/ETSO-C127** (versions **a / b / c** — le levier TEMPOREL).
- **FAA Advisory Circulars** : AC 20-146A (dynamic seat), AC 25.562-1B (dynamic testing),
  AC 25.853-1 (seat cushion flammability).
- **Aircraft Materials Fire Test Handbook** (DOT/FAA/AR-00/12) — méthodes d'essai flammabilité.
- (Option) SAE ARP siège cabine si versions publiques accessibles.

> ⚠️ Tous publics. Démarrer ainsi évite tout risque ITAR/confidentialité et reste **domain-réel**.

### 2.3 Les 5 questions-démo (chacune cible UN différenciateur)
> ⚠️ Les réponses « attendues » ci-dessous sont **indicatives** : elles doivent être **dérivées du
> texte ingéré** et **validées par Armand / le texte officiel**, pas asséner ma mémoire comme vérité.

1. **Factuel tracé** — « Quelles sont les exigences d'essai dynamique d'un siège passager 16g, et la
   limite HIC ? » → réponse avec valeurs + **citation exacte** 25.562 + AC 25.562-1B.
2. **Temporel / supersession** — « Qu'est-ce qui a changé entre ETSO-C127b et C127c pour les sièges ? »
   → identifie le **delta d'amendement**, distingue courant vs périmé.
3. **Change-impact cross-doc** — « Si on change la housse/mousse du siège, quelles exigences de
   certification sont affectées ? » → croise **flammabilité** (25.853(c) + AC 25.853-1 + Fire Test
   Handbook) **ET** la base **dynamique** (siège certifié comme assemblage complet).
4. **Abstention / hors-corpus** — « Quel est le statut de conformité 16g du siège [modèle Safran] sur
   [avion] ? » → **doit s'abstenir** : « absent du corpus public, je ne peux pas confirmer » (vs un
   LLM qui inventerait).
5. **Faux présupposé** — « Puisque l'essai statique suffit pour certifier un siège 16g, quelle est la
   procédure ? » → **détecte la fausse prémisse** (le statique ne suffit pas depuis 25.562, dynamique
   requis) et **corrige** au lieu de répondre à la question piégée.

> Étendre à ~15-20 questions (gold-set mini) pour mesurer, pas juste illustrer.

### 2.4 Ce qu'on réutilise (peu de dev)
- Le **pipeline d'ingestion ClaimFirst** existant (docs_in → claims KG).
- Le **runtime answering `runtime_a3`** (celui qu'on benche) : il a déjà PremiseVerifier (faux
  présupposé), abstention, temporel (valid_from), citations. ⚠️ C'est le moteur **non câblé au /search
  de prod** — le POC est donc aussi l'occasion de **câbler runtime_a3 à une UI démo** (synergie avec
  la décision « promouvoir runtime_a3 en prod »).
- Une **UI démo minimale** qui montre : réponse + **citations cliquables** + **bandeau supersession**
  + **abstention explicite**. Le `ReasoningTracePanel` (déjà esquissé, cf archive CH-24 « test Armand »)
  expose « ce qui a été retenu / écarté / en tension » — exactement ce qu'un ingénieur cert veut voir.

### 2.5 Travail réel à faire (POC)
1. **Acquérir** les docs publics (PDF EASA/FAA) → `docs_in`.
2. **Ingérer** (pipeline staged P1.4-bis si stabilisé, sinon legacy) → vérifier que le KG capte
   exigences + valeurs + amendements + relations.
3. **Construire le mini gold-set** (~15-20 Q + réponses sourcées, validées texte/Armand).
4. **Câbler `runtime_a3` à une UI démo** (citations / supersession / abstention visibles).
5. **Mesurer** : traçabilité (citation correcte), supersession détectée, change-impact couvert,
   abstention correcte sur hors-corpus + faux présupposé. Comparer à un ChatGPT/Copilot vanilla sur
   les mêmes Q (le contraste EST l'argument).
6. **Itérer la lisibilité** pour un non-développeur (Armand doit comprendre seul — cf leçon CH-24 :
   le test sera en autonomie, pas avec Fred à côté pour commenter).

### 2.6 Garde-fous (honnêteté)
- **Exactitude domaine** : ne jamais inventer une valeur réglementaire — tout doit venir du texte
  ingéré et être vérifiable. Une erreur factuelle devant un expert cert = crédibilité détruite.
- **Périmètre POC ≠ produit** : démontrer 4 capacités sur un corpus étroit, pas livrer une solution.
- **Le contraste fait l'argument** : montrer côte à côte OSMOSIS (sourcé, abstenant, temporel) vs un
  LLM grand public (confiant, faux sur les amendements) sur les mêmes questions.
- **Dépendances** : idéalement après stabilisation P1.4-bis ; sinon POC sur pipeline actuel (suffisant
  pour un corpus réglementaire bien structuré).

### 2.7 Définition de « POC réussi »
Armand, **en autonomie**, sur les 5 questions : (a) trouve les réponses tracées utiles, (b) voit
OSMOSIS s'abstenir/corriger là où un LLM grand public se planterait, (c) dit une variante de
« ça, ça me ferait gagner du temps / éviter une erreur » — et accepte un **prochain pas concret**
(tranche de docs internes non sensibles, intro ingénieur cert, 2e session).
