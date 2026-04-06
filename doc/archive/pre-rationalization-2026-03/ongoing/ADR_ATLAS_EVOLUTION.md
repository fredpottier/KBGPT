# ADR — Évolution Atlas : de la collection d'articles au système cognitif

**Date** : 2026-03-18
**Statut** : ACCEPTÉ
**Auteurs** : Fred (product owner), Claude (architecture court/moyen terme), ChatGPT (vision long terme)
**Contexte** : Review croisée Claude + ChatGPT après audit KG et implémentation Claim↔Chunk Bridge

---

## Contexte

L'Atlas (anciennement Wiki) génère des articles de concept fiables et traçables via un pipeline en 4 stages (Concept Resolution → EvidencePack → Section Planning → LLM Generation). Le pipeline fonctionne techniquement mais le résultat est **cognitivement insuffisant** : l'utilisateur doit déjà connaître les concepts, les articles sont plats, et il n'y a aucune vue d'orientation sur le corpus.

Le Chat fonctionne séparément avec un graph-first search en 3 modes (REASONED, ANCHORED, TEXT_ONLY). Il retourne des réponses sourcées mais ne fait aucun lien vers les articles Atlas.

**Diagnostic partagé** : le système fonctionne techniquement mais pas cognitivement. Il prouve, structure et génère — mais ne guide pas.

---

## Décision

L'évolution de l'Atlas se fait en **3 phases séquentielles**. Chaque phase délivre de la valeur utilisable avant de passer à la suivante.

---

## Phase 1 — Convergence Chat ↔ Atlas (immédiat)

**Principe** : le Chat devient un point d'entrée vers l'Atlas, et l'Atlas propose de questionner via le Chat.

### 1a. Chat → Atlas ("Explorer ce sujet")

Après chaque réponse du Chat, un bloc propose les articles Atlas liés :

```
🔍 Explorer ce sujet
  • Procalcitonin (article Tier 1)
  • Antibiotic Stewardship (article Tier 2)
  • sFlt-1/PlGF Ratio (article Tier 1)
→ Voir tous les concepts liés
```

**Algorithme de sélection :**
1. Extraire les concepts détectés dans la question + la réponse
2. Filtrer : `has_article = true` dans Neo4j (WikiArticle existe)
3. Trier par : `importance_score DESC`, `doc_count DESC`
4. Limiter à **3 articles max** (pas de bruit)
5. Optionnel : 1 concept sans article → CTA "Générer cet article"

**Implémentation :**
- Ajouter `related_articles` dans la réponse API du Chat
- Bloc frontend distinct visuellement (icône boussole, pas un lien banal)

### 1b. Atlas → Chat ("Poser une question")

Sur chaque page article `/wiki/[slug]`, un bouton :

```
💬 Poser une question sur ce sujet
→ [Ouvre le Chat pré-rempli avec le concept]
```

### 1c. Articles enrichis via chunk_context

Utiliser le `chunk_context` (Phase 5 du Bridge, déjà implémenté) dans le `constrained_generator` pour que le LLM de génération ait du contexte documentaire long. Les articles gagnent en profondeur sans changer l'architecture.

### 1d. Insight Hints dans le Chat ("Ce que vous devriez aussi regarder")

Après la réponse + le bloc "Explorer ce sujet", un bloc optionnel d'insights cognitifs :

```
💡 Ce que vous devriez aussi regarder
  • Ce sujet contient 3 contradictions entre études (→ voir)
  • Le concept "sFlt-1" est fortement lié mais absent de votre question
  • Couverture faible : seuls 2 documents traitent de ce point
```

**Source des insights (100% déterministe, pas de LLM)** :
- Contradictions : `CONTRADICTS` relations sur les claims de la réponse
- Concepts liés manquants : `related_concepts` de l'EvidencePack non mentionnés dans la question
- Couverture : `doc_count` faible sur les entités de la réponse
- Dépendance : concepts co-occurrents structurants (graph degree élevé)

**Règles d'affichage** :
- Max 3 insights (qualité > quantité)
- Pas d'insight si rien de saillant (mieux vaut rien que du bruit)
- Chaque insight est cliquable (renvoie vers l'article, la contradiction, ou le concept)

**Pourquoi c'est un game changer** : le système passe de "je réponds à ta question" à "je t'aide à penser le sujet". L'utilisateur découvre ce qu'il ne savait pas qu'il ne savait pas.

**Effort estimé Phase 1** : 2-3 jours (incluant les insights)
**Impact** : Transforme la perception du produit — le Chat n'est plus un "ChatGPT interne" mais un copilote qui guide vers une base de connaissance structurée ET révèle les zones d'attention.

---

## Phase 2 — Orientation du corpus (court terme)

**Principe** : un nouvel utilisateur doit pouvoir comprendre le territoire documentaire avant de cliquer.

### 2a. Homepage Atlas refondée

La page `/wiki` passe de "classification par facettes" à "orientation intelligible".

**Contenu (100% déterministe, pas de LLM)** :

```
Corpus Overview
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 156 documents • 34 656 claims • 12 882 entités

Domaines principaux (basés sur les facettes validées) :
  🧬 Microbiome & Gut Health — 1 587 claims, 42 articles
  💊 Cancer Immunotherapy — 1 295 claims, 35 articles
  🔬 Gene Editing (CRISPR) — 522 claims, 18 articles
  🏥 Diagnostic Biomarkers — 327 claims, 12 articles

Concepts structurants (Tier 1) :
  PD-1 (636 claims, 42 docs) • Cas9 (434 claims, 38 docs) • ...

Couverture : 83.7% des claims liées à une entité
Contradictions détectées : 63
```

**Source des données :** requêtes Neo4j sur Facet, Entity (importance_score), Claim counts, WikiArticle counts.

### 2b. Pages facettes enrichies

Chaque facette validée devient une page `/wiki/domain/[facet_key]` avec :
- Description du domaine (template déterministe)
- Top 10 concepts du domaine (triés par importance)
- Articles disponibles
- Documents contributeurs
- Couverture et gaps

**Source :** `BELONGS_TO_FACET` + `ABOUT` + `WikiArticle` existants.

### 2c. Suggestions croisées

- Sur chaque article : "Articles liés" (via `LINKED` + related_concepts)
- Sur chaque page facette : "Questions fréquentes" (générées à partir des QuestionSignatures)
- Sur la homepage : "Commencer par..." (top 5 articles Tier 1)

### 2d. Blind Spots & Risques ("Zones à surveiller")

Sur la homepage et les pages facettes, un bloc d'alertes structurelles :

```
⚠️ Zones à surveiller dans ce corpus
  • Screening 1er trimestre — 3 contradictions entre études sur les seuils
  • Nanomédecine — couverture faible (2 documents seulement)
  • Biomarqueurs émergents — dépendance à 1 source unique
```

**Source (déterministe)** :
- Contradictions élevées : facettes avec le plus de `CONTRADICTS` relations
- Couverture faible : facettes avec `doc_count < 3`
- Dépendance source unique : facettes où 1 document contribue > 60% des claims
- Concepts importants sans article : `importance_score` élevé + `has_article = false`

**Pourquoi** : l'Atlas ne fait plus que montrer ce qu'il sait — il montre aussi ce qu'il ne sait pas assez bien. L'utilisateur peut décider si une zone faible est acceptable ou si elle nécessite des documents supplémentaires.

### 2e. Reading Paths ("Pour comprendre ce sujet, commencez par...")

Sur chaque article, un chemin de lecture suggéré :

```
🧭 Pour comprendre ce sujet, commencez par :
  1. Preeclampsia (concept fondateur)
  2. sFlt-1/PlGF Ratio (biomarqueur principal)
  3. Aspirin Prevention (intervention clé)
```

**Algorithme (déterministe)** :
1. Prendre les `related_concepts` de l'article
2. Trier par : a) importance_score DESC, b) lien sémantique (co-occurrence), c) `has_article = true`
3. Ordonner logiquement : concepts généraux d'abord, spécifiques ensuite
4. Limiter à 3-5 concepts

**Effort estimé Phase 2** : 4-6 jours (incluant blind spots + reading paths)
**Impact** : L'utilisateur peut entrer, comprendre, choisir une porte d'entrée, ET identifier les zones de risque. L'Atlas devient un outil de décision, pas juste de connaissance.

---

## Phase 3 — Atlas cognitif (moyen/long terme)

**Principe** : l'Atlas passe d'une collection d'articles à un système de compréhension du corpus.

> Cette phase est documentée comme vision cible. Elle sera activée une fois les Phases 1 et 2 validées en usage réel.

### 3a. Corpus Summary (synthèse LLM contrôlée)

Une synthèse globale **persistée** du corpus, générée par LLM mais contrainte par les données structurées :

- Input : stats Neo4j (facettes, coverage, top concepts, contradictions majeures, gaps)
- LLM : génère 3-5 paragraphes de synthèse
- Validation : chaque phrase doit être traçable à une stat ou un concept
- Refresh : régénéré manuellement ou après import significatif

**Pourquoi pas en Phase 2** : risque d'hallucination sur la synthèse globale. En Phase 2, le déterministe suffit. Le LLM contrôlé sera introduit quand les gardes seront en place.

### 3b. Thematic Views (parcours utilisateur)

Au-delà des pages facettes (Phase 2), des **parcours d'entrée par intention** :

- "Comprendre les obligations GDPR" (≠ facette `legal_term`)
- "Évaluer la sécurité cloud" (≠ facette `security`)
- "Préparer un audit conformité" (≠ facette `compliance`)

**Différence clé avec les facettes** : une facette = dimension de classement, un thème = intention utilisateur. Les thèmes combinent plusieurs facettes et concepts selon un besoin métier.

**Pourquoi pas en Phase 2** : nécessite une compréhension des profils utilisateurs qui n'existe pas encore. Les facettes enrichies (Phase 2) fourniront les données d'usage nécessaires.

### 3c. Exploration cross-concept

- Navigation visuelle inter-concepts (graphe interactif)
- Timeline cross-concept (évolution temporelle multi-axes)
- Vue "contradictions majeures du corpus" (les points de désaccord structurants)
- Vue "gaps" (concepts sous-documentés, questions sans réponse)

### 3d. Articles vivants

- Versioning (garder les 3 dernières versions)
- Détection automatique de stale (import récent a ajouté des claims non reflétées)
- Suggestions de régénération ("Cet article a 45 nouvelles claims depuis sa dernière génération")
- Drill-down intégré : claims source, chunks contextuels, documents, timeline

### 3e. Atlas comme système de guidance (pas juste navigation)

L'Atlas doit passer de "je rends le corpus accessible" à "je rends le corpus intelligible et actionnable". Concrètement :

- **Proactive insights** : le système prend l'initiative cognitive ("Vu votre historique de questions, vous devriez regarder X")
- **Comparaison assistée** : "Comparer les approches de dépistage 1er trimestre vs 3ème trimestre"
- **Impact analysis** : "Si vous ajoutez ces 5 documents, voici ce qui changerait dans le KG"
- **Profils utilisateur** : le système adapte la navigation selon le rôle (clinicien vs chercheur vs auditeur)

### 3f. Convergence avancée Chat ↔ Atlas

- Le Chat utilise un article existant comme backbone de réponse quand pertinent
- Le Chat détecte les gaps (question sans claim) et les signale comme opportunité d'enrichissement
- L'article propose des "questions type" générées à partir des QuestionSignatures
- Le Chat peut scroller directement à la section pertinente d'un article

---

## Invariants

Quel que soit la phase :

1. **Claims first, chunks as proof** — chaque contenu affiché est traçable à des claims vérifiées
2. **Le KG n'est jamais bypassé** — même les synthèses LLM sont contraintes par les données structurées
3. **Pas d'hallucination tolérée** — toute phrase dans l'Atlas doit être justifiable par le corpus
4. **3 liens max** — quand on propose des articles liés, qualité > quantité

---

## Métriques de succès

### Phase 1
- % de réponses Chat avec articles liés : > 60%
- Taux de clic sur "Explorer ce sujet" : > 15%
- Taux de clic sur "Poser une question" (article → chat) : mesurer

### Phase 2
- Temps moyen avant premier clic (homepage) : < 10s
- % d'utilisateurs qui explorent > 3 pages : > 40%
- Pages facettes avec > 5 articles : > 80%

### Phase 3
- Score de satisfaction utilisateur sur la compréhension du corpus
- % de questions Chat auxquelles un article existant contribue à la réponse
- Taux de régénération d'articles déclenchée par détection de stale

---

## Posture produit

L'ADR ne vise pas "un meilleur RAG + un meilleur wiki". Il vise :

> **Un système qui comprend le corpus mieux que l'utilisateur.**

Chaque phase pousse vers cette posture :
- Phase 1 : "je te guide vers ce que tu cherches" (convergence)
- Phase 2 : "je te montre ce que tu ne sais pas que tu ne sais pas" (orientation + blind spots)
- Phase 3 : "je prends l'initiative cognitive pour toi" (guidance active)

## Résumé

| Phase | Quoi | Posture | Effort |
|-------|------|---------|--------|
| **1** | Chat ↔ Atlas + insights + articles enrichis | Réactive intelligente | 2-3 jours |
| **2** | Homepage orientante + pages facettes + blind spots + reading paths | Orientante + alertante | 4-6 jours |
| **3** | Synthèse LLM, thematic views, guidance active, articles vivants | Cognitive proactive | À évaluer |

La Phase 1 transforme la perception du produit. La Phase 2 rend le corpus intelligible et actionnable. La Phase 3 fait d'OSMOSE un système cognitif indispensable.
