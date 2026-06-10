# Catalogue Fonctionnel OSMOSIS — vue produit

> **But de ce document** : décrire, en langage clair et orienté valeur, **ce que sait
> faire OSMOSIS aujourd'hui** côté utilisateur final + les **capacités moteur**
> différenciantes sur lesquelles de nouvelles fonctionnalités peuvent s'appuyer.
>
> Périmètre : **fonctionnalités publiques vivantes + capacités moteur**. Exclut
> volontairement le cockpit admin/R&D et les chaînes legacy (RFP Excel, Documents UI,
> Wiki) pour ne pas brouiller une réflexion produit.
>
> **Usage prévu** : copier-coller dans un LLM de recherche (ChatGPT, etc.) pour
> brainstormer une fonctionnalité différenciante. Une amorce de prompt est fournie en §4.
>
> *Date : 2026-06-10 — Branche : feat/phase-b-augmentee. Source de vérité produit :
> `doc/VISION.md` (capacités C1-C5).*

---

## 0. En une phrase

OSMOSIS est un moteur de **questions-réponses traçable et auto-limité** sur un corpus
documentaire : au lieu de récupérer des passages (RAG classique), il extrait chaque
document en **claims atomiques vérifiables** stockés dans un **graphe de connaissances
bitemporel**. Conséquence : il sait **se taire** quand l'info n'existe pas, **citer la
phrase source exacte**, **détecter les contradictions** entre documents, et **suivre
l'évolution d'une règle dans le temps** — là où un RAG vanille répond toujours et à plat.

---

## 1. Fonctionnalités utilisateur (pages vivantes)

### 1.1 Chat traçable — `/chat`
Le cœur du produit. Recherche conversationnelle en langage naturel sur le corpus.
Ce qui le distingue d'un chat RAG classique :
- **Réponse sourcée claim par claim** : chaque affirmation de la réponse renvoie à une
  *claim* précise, elle-même rattachée à un **passage verbatim** et une page de document.
- **Abstention calibrée** : si le corpus ne couvre pas la question, le système répond
  honnêtement « je ne sais pas » plutôt que d'inventer (mesuré : ~87 % d'abstention
  correcte vs ~49 % pour un RAG vanille sur le même jeu de 248 questions).
- **Détection de faux présupposé** : si la question présuppose un fait absent du corpus
  (« Quand la règle X a-t-elle été abrogée ? » alors qu'elle ne l'a jamais été), le
  système le signale au lieu de fabriquer une date.
- **Surfaçage des contradictions** : si deux documents se contredisent sur le point
  interrogé, la réponse présente **les deux positions** au lieu d'en choisir une au hasard.
- **Surfaçage de la lignée** : « en vigueur AC 21-25B, qui a remplacé 21-25A → 21-25 ».
- **Badges bitemporels** (Phase C) : chaque citation porte son statut (en vigueur / obsolète)
  et ses dates de validité.

### 1.2 Viewer source in-app — déclenché depuis `/chat` (Phase C)
Au clic sur une citation, le **PDF source s'ouvre dans l'application** (modale), à la bonne
page, avec **le passage exact surligné** — sans avoir à ouvrir le fichier à côté.
Surlignage à 2 niveaux (span exact contigu → meilleure fenêtre approchée). Module
autonome et désactivable. *C'est le type de « petit » différenciateur d'usage qui rend la
traçabilité tangible.*

### 1.3 Carte du Référentiel — `/referentiel`
Visualisation cartographique des **lignées documentaires** (qui remplace quoi) et des
**tensions** (contradictions adjugées) du corpus : carte SVG data-driven, frise
chronologique, registre des documents, mode plein écran. *Identifié comme un
différenciateur fort, encore enrichissable (cf. §3).*

### 1.4 Atlas narratif — `/atlas` (+ `/atlas/theme/[id]`, `/atlas/topic/[id]`)
Exploration **thématique** du corpus : page d'accueil de thèmes, navigation thème → topic.
Entrée « par le haut » dans la connaissance, complémentaire de la recherche par question.

### 1.5 Comparaison — `/compare`
Comparaison de documents/concepts : récupération des *markers* et **diff de concepts**
entre deux sources.

### 1.6 Vérification de conformité — `/verify`
Upload d'un document **DOCX** → chaque assertion du document est **vérifiée contre le
corpus** (confirmée / contredite / non couverte). Pensé pour un usage type **AI Act** :
abstention élevée sur ce qui n'est pas couvert, plutôt qu'une validation complaisante.

---

## 2. Capacités moteur différenciantes (matière première pour de nouvelles features)

Ces capacités existent dans le moteur et sont déjà exploitées en surface ; elles
constituent le **socle réutilisable** pour imaginer de nouvelles fonctionnalités.

| Capacité | Ce que ça permet | Différenciation vs RAG classique |
|----------|------------------|----------------------------------|
| **Modèle claim-centric** | Le contenu est décomposé en assertions atomiques vérifiables, pas en chunks opaques | Permet citation à la phrase, vérif, contradiction — impossible sur des chunks |
| **Bitemporel / lifecycle** (C3) | Chaque claim a des dates de validité + un statut (en vigueur/obsolète/abrogé) ; requêtes « à la date T » | Un RAG ignore le temps : il mélange versions périmées et à jour |
| **Adjudication de contradictions** (C4) | Un juge LLM lit les **passages sources** (jamais les claims seuls) et confirme une vraie contradiction (≠ similarité) | 100 % de surfaçage vs **0 %** pour un RAG (game-changer) |
| **Lignée documentaire** (SUPERSEDES) | Chaîne « X remplace Y remplace Z » détectée et exploitée à la réponse | Un RAG ne sait pas qu'un doc en périme un autre |
| **Multi-autorité** | Attribution des règles à leur émetteur (ex. FAA vs EASA) → divergences inter-autorités explicites | — |
| **Abstention calibrée** (C5) | Refus motivé sur question non couverte / faux présupposé | Un RAG répond toujours, même sans matière |
| **Multi-tenant** | Corpus totalement isolés (domaines/clients distincts) | — |
| **Retrieval hybride + rerank équilibré** | BM25 + vectoriel (RRF) ; quota par côté en comparaison | Évite l'écrasement du minoritaire dans les comparaisons |

**Cibles de fiabilité produit (VISION §5)** : C1 réponse directe ≥80 %, C2 synthèse
multi-doc ≥80 %, C3 lifecycle ≥80 %, C4 contradictions 100 % de surface (atteint),
C5 validation ≥95 % d'abstention sur l'inconnu.

---

## 3. Pistes d'extension déjà identifiées (pour amorcer, pas pour borner)

- **Carte du Référentiel V2** : frise chronologique enrichie + **vue doc-centrique
  scalable à 500+ documents** (la V1 agrège les paires/lignées ; la V2 doit tenir à
  l'échelle d'un gros corpus).
- **Mode exploratoire pour questions larges** : un RAG sait construire une réponse
  structurée à une question vague (« parle-moi de X ») ; le KG, plus précis sur les
  questions directes, est aujourd'hui plus lacunaire sur le très large. Piste : un mode
  qui agrège les claims par thème pour produire une synthèse structurée.
- **Verbosité/structuration de la synthèse** : marge de progression sur la richesse des
  réponses longues (déjà amorcé via leviers top_k + règle de complétude).

---

## 4. Amorce de prompt pour recherche d'état de l'art

> *À coller dans ChatGPT après ce catalogue. La langue française n'empêche pas la
> recherche de sources internationales.*

```
Voici le catalogue fonctionnel d'OSMOSIS, un moteur de Q/A traçable basé sur un
knowledge graph bitemporel de "claims" (et non un RAG par chunks). Son socle :
abstention calibrée, traçabilité click-to-source, détection de contradictions,
lignée documentaire, raisonnement temporel/lifecycle.

Fais une recherche sur l'état de l'art international (2025-2026) des produits et de
la recherche en RAG / knowledge-graph QA / "trustworthy retrieval", et identifie
2 ou 3 fonctionnalités UTILISATEUR potentiellement disruptives qui :
  1) exploitent spécifiquement le socle claim-centric + bitemporel + contradictions
     (et seraient difficiles à répliquer pour un RAG vanille type Copilot/Glean) ;
  2) apportent une valeur métier tangible dans un domaine réglementé (juridique,
     aéronautique, médical, finance) ;
  3) ne sont pas déjà couvertes par la liste ci-dessus.

Pour chaque piste : le problème utilisateur, pourquoi le socle d'OSMOSIS la rend
possible, l'effort estimé, et un ou deux exemples concrets côté concurrence/recherche.
```

---

*Document de travail — à actualiser à chaque livraison de fonctionnalité publique.
Complète le #468 (hygiène méta).*
