# Osmosis – Architecture cible du pipeline d'extraction documentaire

**Version cible – avec Domain Context & Vision conditionnelle**
**Date: 2026-01-02**

---

## 0. Rôle de ce document

Ce document décrit **l'architecture cible** du pipeline d'extraction documentaire d'Osmosis.

Il a pour objectifs de :

* donner une compréhension claire de l'état cible à implémenter,
* expliquer **pourquoi** le pipeline actuel est insuffisant,
* définir les **principes non négociables** de la nouvelle approche,
* cadrer précisément l'usage de Docling, de la vision, et du Domain Context,
* servir de référence unique pour le développement (Claude Code).

Ce document est **architectural et conceptuel**.
Les règles détaillées de *Vision Gating v4* feront l'objet d'un document séparé.

---

## 1. Problème fondamental à résoudre

Les documents traités par Osmosis (architecture IT, cloud, réglementaire, lifescience, médical, etc.) :

* ne sont **pas** des documents purement textuels,
* ne sont **pas** linéaires,
* combinent texte, tableaux, hiérarchie visuelle et schémas.

Dans ces documents, **le sens est souvent porté par la structure visuelle** :

* disposition spatiale,
* regroupements,
* connecteurs,
* zones (ex : Customer vs Provider),
* relations implicites entre blocs.

👉 Toute extraction qui transforme trop tôt le document en texte linéaire **perd de l'information critique**.

---

## 2. État actuel (résumé) et limites

Le pipeline actuel :

* repose sur MegaParse / pdf2text,
* applique des heuristiques simples,
* déclenche la vision de manière partielle (souvent PPTX uniquement).

### Limites majeures

* Tables détruites ou aplaties
* Hiérarchie fragile
* Diagrammes en shapes (PPTX/PDF) traités comme du texte normal
* Vision déclenchée sur de mauvais critères
* Risque élevé de pollution du Knowledge Graph

---

## 3. Principe directeur de l'architecture cible

> **Toute extraction doit reconstruire le document tel qu'un humain le perçoit, avant toute tentative de compréhension.**

Cela impose :

* une extraction **structure-first**,
* une séparation stricte entre :

  * extraction factuelle,
  * interprétation visuelle,
  * raisonnement sémantique,
* un usage **conditionnel, justifié et contrôlé** de la vision.

---

## 4. Architecture globale – vue logique

```
Document brut (PDF / PPTX / Image)
          │
          ▼
Ingestion Router
          │
          ▼
Docling – Structural Extraction (socle)
          │
          ▼
Structural Analysis Layer
          │
          ▼
Vision Gating (décision)
          │
 ┌────────┴─────────┐
 │                  │
 ▼                  ▼
No Vision Path     Vision Path (LLM Vision)
 │                  │
 └────────┬─────────┘
          ▼
Structured Merge
          │
          ▼
RAG + Knowledge Graph
```

---

## 5. Ingestion Router

### Rôle

* Identifier le type de document :

  * PDF texte natif
  * PDF issu de PPTX
  * PPTX natif
  * Image seule

### Règle clé

> Le format **n'implique jamais à lui seul** l'usage de la vision.

Le format détermine **comment extraire**,
pas **comment comprendre**.

---

## 6. Docling – socle d'extraction structurelle

### Rôle fondamental

Docling est la **source de vérité structurelle** du pipeline.

Il est responsable de :

* l'extraction exhaustive du texte,
* la reconstruction de la hiérarchie (titres, sections),
* l'extraction fidèle des tableaux (y compris multi-pages),
* la détection des éléments visuels :

  * images raster,
  * zones graphiques,
  * drawings vectoriels (PDF),
  * espaces structurants.

### Propriétés non négociables

* Aucun raisonnement
* Aucune interprétation métier
* Aucune hallucination
* Verbosité assumée

👉 **Tout document passe par Docling, sans exception.**

---

## 7. Sortie Docling attendue (conceptuelle)

La sortie Docling est un **document structuré**, comprenant notamment :

* `blocks[]`

  * type (`heading`, `paragraph`, `table`, `figure`, `graphic_area`)
  * texte (si présent)
  * niveau hiérarchique
  * page / slide d'origine
* `tables[]`

  * structure ligne / colonne
* `visual_elements[]`

  * images raster
  * zones graphiques
  * drawings vectoriels
  * bounding boxes

⚠️ Cette sortie n'est **pas encore** optimisée pour le RAG.
Elle est **fidèle**, pas interprétée.

---

## 8. Structural Analysis Layer

### Rôle

Analyser la sortie Docling pour identifier **où la structure visuelle porte le sens**.

Cette couche :

* ne fait pas de LLM,
* ne fait pas de vision,
* applique uniquement des **mesures structurelles**.

### Exemples de signaux analysés

* densité de blocs texte courts
* dispersion spatiale du texte
* ratio drawings / texte
* présence de connecteurs (PDF / PPTX)
* images volumineuses avec texte intégré
* tableaux visuels non tabulaires

👉 Cette couche produit des **indicateurs**, pas des décisions finales.

---

## 9. Domain Context (nouvelle brique transverse)

### Définition

Le *Domain Context* est un **contexte d'usage explicite**, fourni par Osmosis, décrivant :

* le domaine principal (SAP, réglementaire, lifescience, etc.),
* le vocabulaire attendu,
* les règles de désambiguïsation,
* les concepts clés,
* les ambiguïtés connues.

### Règle fondamentale

> Le Domain Context **ne crée pas d'information**.
> Il **réduit l'espace des interprétations possibles**.

Il est utilisé :

* uniquement pour guider l'analyse,
* jamais pour ajouter un fait absent visuellement.

---

## 10. Vision Gating (concept)

### Principe

Décider **page / slide / zone** si la compréhension nécessite une lecture visuelle.

La décision repose sur :

* signaux structurels (section 8),
* présence d'images **ou** de shapes complexes,
* complexité visuelle réelle.

👉 Un diagramme peut être :

* une image raster,
* un ensemble de shapes + texte,
* un mélange des deux.

⚠️ Le détail des règles est défini dans *Vision Gating v4*.

---

## 11. Vision Path (LLM Vision + Domain Context)

### Rôle

Extraire **ce qui est explicitement visible dans la structure graphique**
lorsque le texte seul est insuffisant.

### Entrées du Vision Path

1. Image rendue (page / slide / zone)
2. Contexte Docling associé (titres, légendes, texte local)
3. **Domain Context**
4. Règles anti-hallucination strictes

---

### Injection du Domain Context

Le Domain Context est injecté comme :

* un cadre d'interprétation,
* un dictionnaire de désambiguïsation,
* un ensemble de règles restrictives.

Il **n'autorise jamais** :

* l'invention de concepts absents,
* l'application de bonnes pratiques génériques,
* l'inférence non visible.

---

### Exemple de Domain Context (SAP)

**INTERPRETATION RULES**

* Interpret acronyms strictly in SAP context.
* Disambiguate "Cloud" (S/4HANA PCE, GROW, BTP).
* Prefer explicit visual relations over inferred ones.
* If ambiguous, declare ambiguity.

**DOMAIN VOCABULARY**
ERP: S/4HANA, RISE, GROW
Platform: BTP, CPI, SAC
HCM: SuccessFactors
Spend: Ariba, Concur, Fieldglass

**EXTRACTION FOCUS**
Identify which SAP solution is associated with each concept **only if explicitly visible**.

---

### Règles strictes imposées au LLM Vision

* No inference without visual evidence
* No domain expansion
* Every relation must reference a visual cue
* Ambiguity must be declared, not resolved

---

## 12. Sortie Vision attendue

La sortie Vision est :

* strictement structurée (JSON),
* factuelle,
* sourcée,
* traçable,
* annotée avec incertitudes si nécessaire.

Elle **n'écrase jamais** le texte Docling.

---

## 13. Structured Merge

### Règle d'or

> **Aucune fusion implicite.**

* Docling = socle
* Vision = enrichissement attaché
* Chaque ajout est traçable et optionnel

---

## 14. Préparation RAG & Knowledge Graph

À l'issue du merge :

* le document est complet,
* structurellement fidèle,
* explicable,
* prêt pour :

  * chunking intelligent,
  * KG robuste,
  * raisonnement fiable.

---

## 15. Ce que cette architecture résout

✅ Tables préservées
✅ Hiérarchie fiable
✅ Diagrammes images **et** shapes
✅ Vision contextuelle, conditionnelle
✅ Aucune hallucination systémique
✅ Scalabilité grands documents

---

## 16. Prochaine étape

👉 **Vision Gating v4 – Spécification détaillée**

* règles explicites,
* scoring unifié,
* pseudo-code prêt à implémenter,
* images raster + shapes vectoriels + tables visuelles.
