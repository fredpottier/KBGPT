# Étude — « La Carte du Référentiel » : visualiser les relations entre documents

*Étude produit, 06/06/2026, à la demande de Fred. Question posée : une page de
visualisation des relations inter-documents (supersession, tensions, historique)
ferait-elle sens, et que proposer qui apporte de la valeur — sachant que la
capacité à créer ces relations « by design » est rare sur le marché ?*

---

## 1. Verdict : oui — et c'est probablement la matérialisation la plus vendeuse de l'actif invisible

Le cœur différenciant d'OSMOSIS (claims + relations + lignées + adjudication)
est aujourd'hui **invisible** : il ne se manifeste qu'à travers des réponses de
chat. Or l'actif lui-même est une **structure** — et une structure se montre.
Une carte du référentiel transforme « faites-moi confiance, il y a un graphe
derrière » en « voici votre référentiel, regardez-le ».

Trois faits rendent l'étude favorable :

1. **Les données existent déjà, sans aucun travail d'ingestion supplémentaire** :
   - 13 nœuds Document, 7 chaînes `SUPERSEDES_DOC` avec preuves
     (`DECLARES_SUPERSESSION` → claim verbatim cliquable, page exacte) ;
   - les agrégats claim-level par paire de documents racontent la structure
     documentaire à eux seuls (mesuré sur le corpus aéro) :

     | Paire | Relation dominante | Lecture |
     |---|---|---|
     | AC 25-17A ↔ AC 25-17 (1991, annulée) | 457 REFINES + 39 CONTRADICTS | « révision » : la nouvelle édition raffine et corrige l'ancienne |
     | AC 25-17A ↔ CFR Part 25 | 104 REFINES | « guidance » : l'AC explicite le règlement |
     | ETSO-C127b ↔ ETSO-C127a | SUPERSEDES_DOC (convention corroborée) | lignée d'éditions |

   - les verdicts d'**adjudication** (06/06) qualifient chaque tension :
     confirmée / portées différentes / équivalence / citation historique — avec
     raison rédigée. La carte peut donc être **honnête par construction**
     (pas de fausses alertes rouges).
2. **Les briques UI existent** : `reactflow` + `d3` en dépendances,
   `components/graph/KnowledgeGraph.tsx` et `ProofGraphViewer.tsx` déjà écrits,
   click-to-source opérationnel (PDF à la page).
3. **Le différenciateur est structurel** : les RAG du marché n'ont AUCUNE
   relation sémantique inter-documents (au mieux des dossiers et métadonnées) ;
   les graph-RAG construisent des graphes d'**entités**, pas de **cycle de vie
   documentaire** ; Glean cartographie l'organisation (qui/quoi/où), pas le
   CONTENU des documents. Personne ne peut afficher « ce contrat amende
   celui-ci, preuve à l'appui » sans refaire notre pipeline.

## 2. La proposition : une page « Référentiel » en 3 couches

### Couche 1 — La carte (MVP)
Graphe interactif (reactflow) :
- **Nœuds = documents.** Taille = volume de claims ; couleur = statut
  (🟢 en vigueur / ⚫ annulé / 🟠 retiré-partiel) ; badge = source/autorité.
- **Arêtes pleines = lignée** (`SUPERSEDES_DOC`), orientées, avec au clic la
  **preuve verbatim** (déclaration d'annulation) + lien PDF à la page.
- **Arêtes fines = relations agrégées** (REFINES/COMPLEMENTS/CONTRADICTS par
  paire), épaisseur = volume ; **rouge uniquement si tensions CONFIRMÉES** par
  l'adjudication (sinon gris neutre) — la carte ne crie pas au loup.
- Panneau latéral au clic sur un nœud : métadonnées, position dans la lignée,
  tensions adjugées avec leurs raisons, lien source.

### Couche 2 — Le registre des tensions
Vue tabulaire des paires de documents avec leurs verdicts d'adjudication :
chaque ligne = une tension examinée, son verdict, sa raison, les deux passages.
C'est l'**audit trail** de la cohérence du référentiel — l'argument « 281
tensions examinées, corpus cohérent » devient un écran montrable.

### Couche 3 — La frise (v2)
Mode chronologique : les documents sur un axe temporel (dates d'effet), les
succession en cascade. Pour les contrats : contrat-cadre → avenant 1 → avenant 2,
d'un coup d'œil.

## 3. Valeur par vertical (le même écran, trois métiers)

| Vertical | Ce que la carte répond en un coup d'œil |
|---|---|
| **Réglementaire** (cas actuel) | « Quel est l'état de mon référentiel ? Quels textes font foi, lesquels sont morts, où sont les tensions réelles ? » |
| **Contrats** (exemple Fred) | « Quels avenants modifient quel contrat ? Y a-t-il des clauses incompatibles entre documents liés ? Quelle est la chaîne contractuelle de ce client ? » — la lignée = avenants ; les tensions adjugées = clauses incompatibles ; la preuve cliquable = l'article exact |
| **Pharma/QMS, finance** | Procédures et leurs révisions, SOPs obsolètes encore référencées, écarts entre politique groupe et déclinaisons locales |

Le pitch transverse : **« votre base documentaire a une anatomie — nous sommes
les seuls à pouvoir vous la montrer, preuve par preuve »**.

## 4. Honnêteté de l'étude : limites et conditions

1. **Petit corpus = belle carte ; gros corpus = bouillie.** À 13 documents la
   carte est lisible ; à 500 il faudra filtres (par lignée, par statut, par
   tension), clustering ou entrée par document. Le MVP doit prévoir le filtre
   dès le départ (par famille de documents / recherche).
2. **La qualité de la carte = la qualité des détecteurs.** La lignée explicite
   dépend des motifs d'identifiants (#443 — aujourd'hui typés réglementaire ;
   pour les contrats il faudra le pack de motifs « avenant n° / annexe / se
   substitue à »). C'est le même chantier d'extensibilité déjà identifié.
3. **Les arêtes CONTRADICTS brutes sont majoritairement des FP** — c'est
   précisément pourquoi la carte n'affiche en rouge QUE l'adjugé confirmé, et
   montre le reste comme « examiné, non contradictoire » (ce qui est une
   feature de confiance, pas un aveu).
4. **Ne PAS construire avant la démo de dimanche** (règle des 48 h). En
   secours, la requête Neo4j Browser existe déjà si un spectateur demande à
   « voir le graphe » : `MATCH path = (d:Document {tenant_id:'default'})-
   [:SUPERSEDES_DOC*1..]->(old:Document) RETURN path`.

## 5. Effort estimé (MVP couches 1+2)

| Lot | Contenu | Effort |
|---|---|---|
| Backend | endpoint `/api/referentiel/map` : documents + lignées (avec preuves) + agrégats par paire + verdicts d'adjudication | ~0,5 j |
| Frontend | page `/referentiel` réutilisant KnowledgeGraph/reactflow + panneau latéral + registre des tensions | ~1-1,5 j |
| Polish démo | statuts visuels, click-to-source, filtre | ~0,5 j |

**Total MVP : ~2-2,5 jours** — démontrable dès la prochaine itération.

## 6. Recommandation

GO en **chantier n°1 post-démo** (avec la ré-ingestion #450/#451) :
1. C'est la matérialisation visuelle du wedge (« relations by design ») au
   moment où le pipeline vient d'apprendre à ne montrer que du vérifié ;
2. Le coût est faible (données + briques UI existantes) ;
3. C'est l'écran qui transformera la démo « chat » en démo « plateforme » — et
   pour le déjeuner Armand (contrats !), c'est exactement l'écran qui parle à
   un juriste.

*Option d'extension naturelle (v2+) : depuis la carte, cliquer une arête de
lignée ouvre le chat pré-rempli (« que change [doc B] par rapport à [doc A] ? »)
— la carte devient le point d'entrée de l'exploration, le chat l'outil de
forage. Boucle parcourir ↔ interroger, comme l'Atlas.*
