# ADR : Pipeline Hybride "Extract-then-Structure" (Pass 1 V2.2)

**Date :** 2026-02-01
**Statut :** DRAFT — En cours de conception
**Auteurs :** Fred (architecte produit), Claude (architecture technique), ChatGPT (revue critique)
**Remplace :** Pass 1 V2.1 (top-down pur : Subject → Themes → Concepts → Assertions)

---

## 1. Contexte et diagnostic

### 1.1 Deux échecs symétriques

| | V1 (bottom-up pur) | V2.1 actuelle (top-down pur) |
|---|---|---|
| **Approche** | Extraction chunk-par-chunk → ProtoConcepts → promotion | GlobalView → Themes → Concepts → Assertions → linking |
| **Échec principal** | Milliers de concepts orphelins, 2% de relations, graphe inutilisable | Concepts "hors-sol" inventés par le LLM, associations fausses (ex: SAC ↔ EDR) |
| **Cause racine** | Extraction sans compréhension globale | Classification avant extraction, structure auto-réalisatrice |
| **Symptôme** | ~4700 nodes/doc, graphe pur mais vide | SINK 34%, 37% concepts vides, routing "par couleur" |

### 1.2 Exemple concret du problème V2.1

Document 020 (RISE with SAP Cloud ERP Private) :

- Le LLM invente le thème "SAP Analytics Cloud — Live Connection" en Pass 1.1
- Le concept "SAP Analytics Cloud Live Connection" est créé avec des triggers ("sap cloud connector", "cloud connector sap")
- Ces triggers matchent des assertions sur EDR/antivirus, Cyber Security Centre, et monitoring 24x7
- Résultat : 3 assertions sur la sécurité réseau classées sous Analytics Cloud
- **Confidence 0.9** sur ces assertions — le score mesure la qualité de l'assertion, pas la pertinence du routing

Ce type d'erreur est **structurel** : il vient du fait que la taxonomie est inventée *avant* d'avoir vu les assertions.

### 1.3 Principe fondamental

> **Aucune catégorie n'existe sans support observable.**
> On n'autorise une structure conceptuelle que si elle émerge d'un ensemble d'assertions réelles.

---

## 2. Les 6 invariants du pipeline hybride

Ces règles garantissent qu'on ne retombe ni dans V1 ni dans V2.1.

### I1 — Set-before-Name (anti-V2)

Un concept ou thème n'est créé qu'à partir d'un **ensemble d'assertions existantes** qui le justifie. Le nom vient *après* le regroupement, jamais avant.

**V2.1 violait** : le LLM nommait des concepts sur un sommaire, puis cherchait quoi y mettre.

### I2 — Zone-First (anti-V1)

Le clustering se fait d'abord **localement** (par section ou macro-section), puis des fusions inter-zones sont autorisées uniquement si la similarité est forte. Jamais de clustering global sur tout le document.

> **LIGNE ROUGE** : Aucun clustering global plat sur l'ensemble des assertions du document n'est autorisé. Toute similarité inter-zones doit passer par une étape explicite de fusion contrôlée. Cette règle ne peut pas être contournée "pour simplifier" ou "parce que les zones sont petites".

**V1 violait** : clustering global de milliers de ProtoConcepts → explosion combinatoire, clusters faibles.

### I3 — Budget adaptatif (anti-V1)

Le nombre de concepts "actifs" dans le KG est borné par un budget adapté à la taille du document. Le reste est persisté en "draft" (consultable mais hors KG principal).

> **Le budget est une contrainte épistémique, pas une optimisation de performance.** Il définit la capacité maximale de compréhension stable du document par le système. Au-delà, la connaissance reste accessible (via retrieval) mais non structurée. "Augmenter le budget" n'est jamais la solution — c'est le chemin de retour vers V1.

| Taille document | Budget concepts actifs | Budget thèmes |
|---|---|---|
| < 50 pages | 10-20 | 3-7 |
| 50-150 pages | 20-40 | 5-12 |
| > 150 pages | 40-60 | 8-18 |

Un concept hors budget n'est pas "faux" — il est "non admis dans la vérité courante du KG".

**V1 violait** : aucun budget, milliers de concepts créés sans limite.

### I4 — No Empty Nodes (anti-V1 + anti-V2)

- `support_count == 0` → **interdit** (node jamais créé)
- `support_count < 3` → **draft** (non persisté dans le KG actif)
- `support_count >= 3` → **active** (persisté)

**V1 violait** : concepts promus sans support. **V2.1 violait** : 37% de concepts vides.

### I5 — Purity Gate (nouveau)

Après construction, chaque concept est vérifié : ses assertions doivent être sémantiquement cohérentes entre elles. Un concept dont les assertions parlent de sujets différents est soit splitté, soit rejeté.

**Test** : prendre N assertions du concept, demander "parlent-elles de la même chose ?" Si non → split ou reject.

### I6 — Abstention normale (anti-V2)

Une assertion qui ne rentre proprement dans aucun concept est classée UNLINKED. Ce n'est pas un échec, c'est un résultat attendu. L'assertion reste disponible pour le retrieval (Layer R / recherche vectorielle) mais n'apparaît pas dans le graphe de concepts.

> **UNLINKED est un état de haute intégrité** : il signifie que le système refuse de mentir. Un taux UNLINKED de 20% est infiniment préférable à un taux de 0% avec 30% d'associations fausses.

---

## 3. Architecture du pipeline

### 3.1 Vue d'ensemble

```
Pass 0    : Structural Graph (DocItems, Pages, Chunks)     [INCHANGÉ]
Pass 0.9  : GlobalView — carte du document                 [MODIFIÉ : rôle réduit]
Pass 1.A  : Extraction locale d'assertions                 [NOUVEAU]
Pass 1.B  : Clustering zone-first                          [NOUVEAU]
Pass 1.C  : Structuration (nommage, thèmes, sujets)        [NOUVEAU]
Pass 1.D  : Validation (purity + budget gate)               [NOUVEAU]
Pass 2    : Relations inter-concepts                        [INCHANGÉ]
```

### 3.2 Pass 0.9 — GlobalView comme carte, pas taxonomie

**Rôle actuel (V2.1)** : produire Subject, Themes, TOC enrichie → base de la taxonomie
**Nouveau rôle** : produire une **carte de navigation** du document

**Output** :
```yaml
global_view:
  document_summary: "Ce document traite de..."  # 2-3 phrases
  language: "en"
  zones:                                         # Découpage en macro-sections
    - zone_id: "z1"
      label: "Network Architecture"              # Label provisoire (informatif, pas prescriptif)
      sections: ["s1", "s2", "s3"]               # Sections couvertes
      page_range: [1, 45]
      keywords: ["VPN", "firewall", "TLS"]       # Signature lexicale
    - zone_id: "z2"
      label: "Security Operations"
      sections: ["s4", "s5", "s6"]
      page_range: [46, 90]
      keywords: ["EDR", "monitoring", "SIEM"]
    # ...
  estimated_complexity: "high"                   # Guide le budget adaptatif
```

**Ce qui change** :
- Plus de création de Themes/Concepts à ce stade
- Les labels de zone sont **provisoires** et informatifs — ils guident le clustering mais ne contraignent pas
- Les keywords servent de signature pour la fusion inter-zones en Pass 1.B

> **LIGNE ROUGE** : Le GlobalView n'a pas le droit de produire des entités destinées à être persistées dans le KG (Themes, Concepts, Subjects). Toute structure persistée doit émerger exclusivement de Pass 1.B et suivants. Le moindre glissement vers "suggested themes" ou "candidate taxonomy" dans Pass 0.9 rouvre la porte à V2.1.

### 3.3 Pass 1.A — Extraction locale d'assertions

**Principe** : lire chaque zone section par section, extraire les assertions ancrées, sans essayer de les classifier.

**Input** : zones de la GlobalView + DocItems/Chunks correspondants
**Output** : liste d'assertions brutes, chacune avec :

```yaml
assertion:
  text: "All hosts are equipped with EDR, antivirus, and anti-malware agents."
  type: FACTUAL                    # FACTUAL | PRESCRIPTIVE | DEFINITIONAL | PROCEDURAL | ...
  zone_id: "z2"                    # Zone source
  section_id: "s5"                 # Section source
  page_no: 67
  anchor_docitem_id: "di_234"      # Ancrage DocItem
  confidence: 0.9                  # Qualité intrinsèque de l'assertion
```

**Points clés** :
- Pas de `concept_id` à ce stade — l'assertion n'est rattachée à rien
- Le LLM lit 1-3 pages et extrait ce qu'il voit — c'est son mode le plus fiable
- On réutilise le mode Pointer-Based existant (performant, 8.5% ABSTAIN)
- Volume attendu : 300-1000 assertions par document

**Prompt LLM (principe)** :
```
Tu lis un extrait d'un document technique. Extrais les affirmations factuelles,
prescriptions, définitions et procédures. Pour chaque assertion :
- Cite le texte original (ou paraphrase minimale)
- Indique le type (FACTUAL/PRESCRIPTIVE/DEFINITIONAL/PROCEDURAL)
- N'essaie PAS de classifier ou catégoriser l'assertion
```

### 3.4 Pass 1.B — Regroupement sémantique contraint

**Principe** : regrouper les assertions similaires, d'abord au sein de chaque zone, puis fusionner les clusters inter-zones quand la similarité est forte.

#### Étape 1 : Clustering intra-zone

Pour chaque zone :
1. Calculer les embeddings des assertions (réutilise les embeddings Layer R si disponibles, sinon calcul local)
2. Clustering par similarité sémantique (HDBSCAN ou agglomératif, seuil configurable)
3. Chaque cluster = un **proto-concept** (candidat)

**Contraintes** :
- Cluster de 1 assertion → pas un concept, assertion reste UNLINKED (sauf si fusion inter-zone)
- Cluster de 2 assertions → draft
- Cluster de 3+ assertions → candidate

#### Étape 2 : Fusion inter-zones

Comparer les centroïdes des clusters entre zones :
- Similarité cosinus > 0.85 → fusion automatique
- Similarité 0.70-0.85 → fusion si les keywords de zone se recoupent
- Similarité < 0.70 → pas de fusion

**Garde-fous anti-V1** :
- Budget max de clusters actifs (selon taille doc)
- Clusters trop petits (< 3 assertions après fusion) → restent draft
- Pas de clustering global "flat" — toujours zone-first puis fusion

#### Output :
```yaml
clusters:
  - cluster_id: "cl_001"
    zone_ids: ["z2"]                    # Zones d'origine
    assertions: ["a_045", "a_046", "a_051", "a_078"]
    centroid_embedding: [0.12, ...]     # Pour fusion et recherche
    support_count: 4
    status: "candidate"                 # candidate | draft | rejected
```

### 3.5 Pass 1.C — Structuration a posteriori

**Principe** : nommer les clusters, les organiser en thèmes et sujets. Le LLM structure ce qui existe, il n'invente pas.

#### Étape 1 : Nommage des concepts (par cluster)

Pour chaque cluster "candidate", on soumet les N assertions au LLM :

```
Voici un groupe d'assertions extraites d'un document technique.
Elles ont été regroupées par similarité sémantique.

[assertions du cluster]

1. Propose un nom court et descriptif pour ce groupe (max 5 mots)
2. Propose 3-5 variants/alias
3. Quel rôle joue ce concept dans le document ? (CENTRAL / TRANSVERSAL / CONTEXTUAL)
```

**Invariant I1** : le nom vient du contenu, pas d'un sommaire.

#### Étape 2 : Regroupement en thèmes

Les concepts nommés sont regroupés en thèmes par proximité sémantique et localité (zones partagées) :

```
Voici les concepts identifiés dans ce document, avec leurs zones d'origine.

[liste des concepts avec zone_ids et 2-3 assertions exemples]

Regroupe-les en 5-15 thèmes cohérents. Un thème = un axe de lecture du document.
```

#### Étape 3 : Identification du sujet

À partir des thèmes, extraction de 1-3 sujets de haut niveau.

#### Output final (avant validation) :

```
Subject: "RISE with SAP Cloud ERP Private — Security & Operations"
├── Theme: "Network Security Architecture"
│   ├── Concept: "IPSEC VPN" (7 assertions, zones z1+z2)
│   ├── Concept: "Web Application Firewall" (6 assertions, zone z3)
│   └── Concept: "TLS Encryption" (5 assertions, zone z3)
├── Theme: "Security Operations Center"
│   ├── Concept: "Endpoint Detection & Response" (4 assertions, zone z2)
│   ├── Concept: "24x7 Security Monitoring" (3 assertions, zone z2)
│   └── ...
└── UNLINKED: 55 assertions (pas de cluster suffisant)
```

### 3.6 Pass 1.D — Validation (Purity + Budget Gate)

#### Purity Check

Pour chaque concept avec 5+ assertions, on échantillonne 5 assertions et on demande au LLM :

```
Ces 5 phrases sont censées parler du même sujet.
Est-ce le cas ? Si non, lesquelles sont hors-sujet ?
```

**Actions** :
- Toutes cohérentes → concept validé ✅
- 1-2 hors-sujet → assertions déplacées vers UNLINKED, concept conservé
- 3+ hors-sujet → concept splitté ou rejeté

#### Budget Gate

1. Trier les concepts par `support_count` décroissant
2. Garder les top-K selon le budget (adapté à la taille du doc)
3. Le reste → draft (persisté séparément, accessible en recherche mais pas dans le KG actif)

#### Output final persisté :

```yaml
active_concepts: 35      # Dans le KG
draft_concepts: 15        # Hors KG, consultable
unlinked_assertions: 55   # Disponible via Layer R / retrieval
purity_rejections: 3      # Concepts échoués au purity check
```

---

## 4. Comparaison avec V1 et V2.1

| Aspect | V1 | V2.1 | V2.2 (hybride) |
|---|---|---|---|
| **Direction** | Bottom-up aveugle | Top-down inventif | Bottom-up guidé |
| **Concepts créés par** | Extraction chunk | LLM sur sommaire | Clustering d'assertions réelles |
| **Concepts vides possibles** | Oui (milliers) | Oui (37%) | **Non** (I4: no empty nodes) |
| **Routing faux** | N/A (pas de routing) | Oui (SAC↔EDR) | **Non** (I1: set-before-name) |
| **Explosion combinatoire** | Oui (4700 nodes/doc) | Non | **Non** (I3: budget + I2: zone-first) |
| **GlobalView** | Absente | Taxonomie prescriptive | **Carte informative** |
| **SINK/UNLINKED** | N/A | Échec (34%) | **Normal** (I6) |
| **Purity check** | Absent | Absent | **Systématique** (I5) |

---

## 5. Ce qui est réutilisé de V2.1

| Composant | Statut | Notes |
|---|---|---|
| Pass 0 (Structural Graph) | **INCHANGÉ** | DocItems, Pages, Chunks |
| Pass 0.9 (GlobalView) | **MODIFIÉ** | Rôle réduit : carte + zones, plus de taxonomie |
| Pointer-Based extraction | **RÉUTILISÉ** | Mécanisme d'extraction locale, adapté pour Pass 1.A |
| Layer R (embeddings) | **RÉUTILISÉ** | Embeddings des assertions pour le clustering |
| Pass 2 (Relations) | **INCHANGÉ** | Relations inter-concepts |
| Persister Neo4j | **ADAPTÉ** | Nouveau schéma : active vs draft, UNLINKED |
| EmbeddingModelManager | **RÉUTILISÉ** | Pour le clustering sémantique |

---

## 6. Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Clustering trop fin → retour V1 | Moyenne | Fort | I3 (budget) + seuil min 3 assertions |
| Clustering trop large → concepts poubelles | Faible | Moyen | I5 (purity check) |
| Nommage LLM hallucine | Faible | Faible | Le nom est révisable, le contenu ne dépend pas du nom |
| Performance clustering sur 1000+ assertions | Faible | Moyen | Zone-first réduit à ~100-200 assertions/zone |
| Perte d'info vs V2.1 | Moyenne | Moyen | Draft concepts + UNLINKED restent consultables via retrieval |

---

## 7. Métriques de succès

| Métrique | V2.1 actuelle | Cible V2.2 |
|---|---|---|
| Concepts vides | 37% | **< 5%** |
| SINK / UNLINKED | 34% (considéré échec) | **15-25%** (considéré normal) |
| Purity check pass rate | Non mesuré | **> 90%** |
| Associations fausses (sondage 20 concepts) | ~30% incohérents | **< 5%** |
| Precision concept→assertion (sondage humain) | Non mesuré | **> 85%** |
| Budget respecté | N/A | **100%** |

**Note sur la precision** : sur 20 concepts échantillonnés, pourcentage d'assertions jugées pertinentes par un humain. C'est exactement le test qui a révélé le problème SAC↔EDR en V2.1 — il doit être formalisé comme métrique de validation.

---

## 8. Plan d'implémentation (séquence)

| Étape | Description | Dépendances |
|---|---|---|
| 1 | Modifier Pass 0.9 : zones au lieu de taxonomie | Aucune |
| 2 | Pass 1.A : extraction assertions brutes (adapter Pointer-Based) | Pass 0.9 modifié |
| 3 | Pass 1.B : clustering zone-first (HDBSCAN + fusion) | Pass 1.A + embeddings |
| 4 | Pass 1.C : nommage + structuration LLM | Pass 1.B |
| 5 | Pass 1.D : purity check + budget gate | Pass 1.C |
| 6 | Adapter Persister Neo4j (active/draft/unlinked) | Pass 1.D |
| 7 | Validation sur docs 014 + 020 | Tout |

---

## 9. Preuve par l'absurde — le cas SAC↔EDR dans V2.2

Vérifions que les 3 assertions mal routées vers "SAP Analytics Cloud Live Connection" en V2.1 ne peuvent **pas** produire la même erreur dans V2.2.

**Les 3 assertions** :
1. "All hosts are equipped with agents for EDR, antivirus, and anti-malware software."
2. "SAP Internal Cyber Security Centre, dedicated to identifying & mitigating Cyber Security risks"
3. "Continuous 24x7 monitoring of security events, managing event triage"

**Trajet V2.2** :

- **Pass 1.A** : ces 3 assertions sont extraites dans la zone "Security Operations" (z2), sans concept assigné. Aucune mention de "Analytics Cloud".
- **Pass 1.B** : clustering intra-zone z2. Ces 3 assertions sont sémantiquement proches (sécurité endpoint/SOC). Elles forment un cluster avec d'autres assertions de sécurité opérationnelle. Le concept "SAP Analytics Cloud" ne peut pas émerger car aucune assertion de z2 ne parle d'Analytics Cloud.
- **Pass 1.C** : le cluster est nommé par le LLM sur base de son contenu réel → "Security Operations Center" ou "Endpoint Security". Pas "Analytics Cloud".
- **Pass 1.D** : purity check → les 3 assertions parlent bien de la même chose → validé.

**Résultat** : le concept "SAP Analytics Cloud Live Connection" n'existe tout simplement pas dans V2.2, car aucun cluster d'assertions ne le supporte. Les 3 assertions sont correctement classées sous un concept de sécurité opérationnelle.

**Pourquoi V2.1 échouait** : en V2.1, le LLM inventait "SAP Analytics Cloud" comme thème en Pass 1.1 (sur le sommaire), créait le concept avec des triggers lexicaux larges ("cloud", "connector"), et le reranker forçait un match. Dans V2.2, cette séquence est **impossible par construction** (I1 : set-before-name).

---

## 10. Questions ouvertes

1. **Algorithme de clustering** : HDBSCAN (auto-détecte le nombre de clusters) vs agglomératif (plus contrôlable) ?
2. **Seuil de fusion inter-zones** : 0.85 cosinus est-il le bon seuil ?
3. **Purity check** : combien d'assertions échantillonner ? 5 suffit-il ?
4. **Draft concepts** : les persister dans Neo4j avec un label séparé, ou dans un sidecar JSON ?
5. **Rétrocompatibilité** : les consumers existants (API recherche, frontend) doivent-ils voir les draft concepts ?
