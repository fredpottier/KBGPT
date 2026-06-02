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

## PARTIE 3 — Analyse du corpus candidat : successions, remplacements, contradictions

> But (Fred 02/06) : choisir les docs de façon à contenir des relations que NI Glean NI
> Copilot ne savent exploiter — **lignées de version** (temporel/bitemporel) et **divergences**
> (détection de tension). C'est là qu'OSMOSIS démontre sa valeur. ⚠️ Principe de curation clé :
> **importer plusieurs VERSIONS du même document** (pas seulement la dernière) — c'est ce qui crée
> les relations de supersession dans le KG.

### 3.1 Chaînes de SUCCESSION / REMPLACEMENT (→ démo temporel/bitemporel)
Chaque document énonce lui-même ce qu'il annule → relation `SUPERSEDES`/`EVOLUTION_OF` extractible.

| Lignée | Chaîne (avec dates) | Point de démo |
|--------|---------------------|---------------|
| **TSO-C127** (FAA, MPS sièges) | C127 (1992, SAE AS8049) → C127a (1998, AS8049A) → **C127b (eff. 06/06/2014 ; C127a REFUSÉ après 06/12/2015** ← fenêtre de transition explicite) → C127c → C127d | « Puis-je encore certifier sous TSO-C127a ? » → **non depuis le 06/12/2015** |
| **ETSO-C127** (EASA, miroir) | ETSO-C127a → C127b → **C127c (CS-ETSO amd 17)** | « Version EASA courante ? » |
| **AC 25.562** (FAA, moyen de conformité) | AC 25.562-1 (06/03/1990) → -1A (19/01/1996, annule -1) → **-1B + Change 1 (30/09/2015, annule -1A)** | « Quelle AC est en vigueur pour l'essai dynamique ? » → **-1B**, et -1/-1A signalés superseded |
| **AC 20-146** (FAA, certif par analyse) | AC 20-146 (19/05/2003, **CANCELLED**) → **AC 20-146A (29/06/2018)** | idem |
| **SAE** (standards techniques référencés) | AS8049 → AS8049A → AS8049C ; ARP5526 → ARP5526D | profondeur de la lignée |

### 3.2 CONTRADICTIONS / DIVERGENCES (→ démo détection de tension)
| Type | Tension concrète | Source |
|------|------------------|--------|
| **FAA ↔ EASA (force réglementaire)** | FAA : HIC « **should** not exceed 1000 » vs EASA : « **must** not exceed 1000 units » (recommandation vs obligation) | AC 25.562-1B / CS-25 |
| **FAA ↔ EASA (harmonisation incomplète)** | « most — but not all — of the time harmonised » + **Deviation Request ETSO-C127c#1** (EASA dévie explicitement du standard) | EASA deviation request |
| **Ancien ↔ Nouveau (exigence remplacée)** | Essai **statique** (pré-25.562) **NE SUFFIT PLUS** depuis l'introduction du dynamique 16g | 14 CFR 25.562 |
| **Proposition ↔ En vigueur** | EASA **NPA 2013-20** « Seat crashworthiness improvement » (proposition) vs règle alors en vigueur | NPA 2013-20 |
| **Critères de blessure évolutifs** | HIC aviation (1000) vs HIC15 vs BrIC (1.0) — méthodologies qui se chevauchent/divergent | FAA tech reports |

### 3.3 CROSS-RÉFÉRENCE (→ démo raisonnement cross-document)
Chaîne de dépendance qu'une seule question peut traverser :
`14 CFR 25.562 (règle)` → `AC 25.562-1B (moyen de conformité)` → `TSO-C127c (MPS minimum)` → `SAE AS8049C (standard technique)` → `AC 20-146A (certif par analyse)` ; flammabilité : `25.853(c)` → `AC 25.853-1` → `Aircraft Materials Fire Test Handbook (DOT/FAA/AR-00/12)`.

### 3.4 Liste concrète à importer (tout PUBLIC) — inclure les LIGNÉES
- **FAA réglementation** : 14 CFR Part 25 (§25.561, 25.562, 25.785, 25.853).
- **FAA AC — les VERSIONS successives** (pour la supersession) : AC 25.562-**1**, **-1A**, **-1B+Chg1** ; AC 20-146 **+** 20-146A ; AC 25.853-1.
- **FAA TSO — la lignée** : TSO-C127, C127a, C127b, C127c.
- **EASA** : CS-25 (Book 1 + AMC) ; ETSO-C127a, C127b, C127c (CS-ETSO amd 17) ; NPA 2013-20 ; Deviation Request ETSO-C127c#1.
- **Méthodes d'essai** : Aircraft Materials Fire Test Handbook (DOT/FAA/AR-00/12).
- **SAE** (si versions publiques accessibles) : AS8049x, ARP5526x.

> **Pourquoi inclure les versions périmées** : un corpus « propre » (dernière version seulement) ne
> permet PAS de démontrer le bitemporel. En important AC 25.562-1 **et** -1A **et** -1B, le KG capte
> « -1B annule -1A le 30/09/2015 » → OSMOSIS répond « la version en vigueur est -1B » ET sait dire
> ce qui est périmé/depuis quand. C'est l'inverse de l'hygiène documentaire habituelle, mais c'est
> exactement le différenciateur à montrer.

### 3.5b Couche SAFRAN PUBLIQUE (02/06) — relier les affirmations maison aux normes
Ajout décisif : du matériel **émis par Safran, public**, pour démontrer le cas d'usage cible
(docs maison ↔ réglementation) **sans donnée confidentielle**.
- **Brevets** (USPTO, Safran Seats) : US9399518 (energy absorber crashworthy seat), US5788185
  (lumbar load during crash), US5842669 (crashworthy seat), US20200262563 (energy absorber,
  Dhermand). → techniques, sur les sujets réglementés (16g, charge lombaire, absorption).
- **Article technique Safran** « dynamic tests on aircraft seats » (catapulte 16g, 46 km/h).
- **Communiqué** Emirates (S-Lounge business, Z400 éco) + affirmation « 16g/21g, certifié FAA/EASA ».
- Démo cross-doc : « le brevet d'absorbeur Safran vise quelle charge lombaire vs limite 25.562 ? »,
  « Safran annonce conforme 16g/21g — quelle version de la norme s'applique ? ».
- ⚠️ Nuance que le système doit tenir : **brevet ≠ produit certifié** (invention vs certification).

### 3.6 Corpus TÉLÉCHARGÉ (état 02/06) — `data/corpus/Safran/`
16 PDF (~11 Mo) + 2 pages HTML Safran :
- **`faa/`** (8 PDF) : AC 25.562-**1A** + **1B** (lignée), AC 20-146 (cancelled) + **20-146A** (lignée),
  AC 23.562-1, AC 21-25B, AC 25.853-1 (flammabilité), side-facing seat research (CAMI 201218).
- **`easa/`** (4 PDF) : ETSO-C127**a** + **b** + **c** (lignée de supersession), NPA 2013-20
  (seat crashworthiness improvement).
- **`safran/`** (4 brevets PDF + 2 HTML) : 4 brevets ; article dynamic-tests + communiqué Emirates (HTML).
- **Manque / à compléter** : TSO-C127 FAA (sur drs.faa.gov, pas de lien PDF direct), 14 CFR Part 25
  (texte eCFR), CS-25 Easy Access Rules (gros PDF EASA), 16g benefit analysis `fire.tc.faa.gov/pdf/00-13.pdf`
  (503 temporaire, à retenter). ⚠️ Les 2 HTML Safran (avec nav/boilerplate) : à **convertir en texte/PDF
  propre** avant ingestion (Docling = PDF/Office, gère mal le HTML brut).

### 3.5 Questions-démo enrichies (succession + tension)
- **Succession** : « Quelle version de l'AC sur l'essai dynamique des sièges est en vigueur, et qu'a-t-elle remplacé ? » → -1B, annule -1A (30/09/2015), qui annulait -1.
- **Temporel borderline** : « Puis-je certifier un siège sous TSO-C127a aujourd'hui ? » → non, refusé depuis le 06/12/2015.
- **Tension FAA/EASA** : « FAA et EASA imposent-ils le HIC 1000 de la même façon ? » → tension : *should* (FAA) vs *must* (EASA) + deviation request EASA.
- **Faux présupposé** : « Puisque l'essai statique suffit pour le 16g, quelle est la procédure ? » → faux : le dynamique est requis depuis 25.562.

### 2.7 Définition de « POC réussi »
Armand, **en autonomie**, sur les 5 questions : (a) trouve les réponses tracées utiles, (b) voit
OSMOSIS s'abstenir/corriger là où un LLM grand public se planterait, (c) dit une variante de
« ça, ça me ferait gagner du temps / éviter une erreur » — et accepte un **prochain pas concret**
(tranche de docs internes non sensibles, intro ingénieur cert, 2e session).
