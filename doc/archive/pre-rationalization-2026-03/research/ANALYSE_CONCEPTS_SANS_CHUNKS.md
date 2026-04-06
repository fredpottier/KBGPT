# Analyse : ProtoConcepts sans relation ANCHORED_IN vers DocumentChunk

**Contexte** : Projet OSMOSE (Knowledge Graph pour documentation SAP)
**Date** : 2026-01-08
**Objectif** : Arbitrage architectural - faut-il imposer l'ancrage chunk pour tous les ProtoConcepts ?

---

## ATTENTION - Lecture importante

**Ce document concerne spécifiquement les ProtoConcepts** (instances de concepts extraits d'un document unique), **PAS les CanonicalConcepts** (concepts unifiés cross-document).

**Le problème** : 43% des ProtoConcepts n'ont pas de relation `ANCHORED_IN` vers un `DocumentChunk`, bien qu'ils aient tous une relation `EXTRACTED_FROM` vers leur `Document` source.

---

## 1. Modèle de Données Neo4j (Simplifié)

### 1.1 Nœuds

| Nœud | Description | Exemple |
|------|-------------|---------|
| `Document` | Document PDF source | "Conversion_Guide_SAP_S4HANA_2025.pdf" |
| `DocumentChunk` | Fragment de texte (256 tokens) | Paragraphe du document |
| `ProtoConcept` | Concept extrait d'UN document | "SAP S/4HANA 2023" dans Doc A |
| `CanonicalConcept` | Concept unifié cross-documents | "SAP S/4HANA 2023" (toutes occurrences) |

### 1.2 Relations

```
┌────────────────────────────────────────────────────────────────────────┐
│                          MODÈLE RELATIONNEL                            │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ProtoConcept ──EXTRACTED_FROM──▶ Document        ✅ 100% présent      │
│       │                                                                │
│       ├──────INSTANCE_OF────────▶ CanonicalConcept ✅ 100% présent     │
│       │                                                                │
│       └──────ANCHORED_IN────────▶ DocumentChunk   ⚠️ 57% seulement    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Définitions** :
- `EXTRACTED_FROM` : "Ce ProtoConcept a été trouvé dans ce Document"
- `INSTANCE_OF` : "Ce ProtoConcept représente ce CanonicalConcept dans ce document"
- `ANCHORED_IN` : "Ce ProtoConcept apparaît textuellement dans ce chunk précis"

---

## 2. Le Problème Précis

### 2.1 Statistiques

Sur **1246 ProtoConcepts** extraits :

| Statut | Nombre | Pourcentage |
|--------|--------|-------------|
| Avec `EXTRACTED_FROM` + `ANCHORED_IN` | 710 | **57%** |
| Avec `EXTRACTED_FROM` **SANS** `ANCHORED_IN` | 536 | **43%** |
| Sans `EXTRACTED_FROM` (orphelins) | 0 | 0% |

**Reformulation du problème** :
- Tous les ProtoConcepts sont reliés à leur Document source (traçabilité OK)
- Mais 536 ProtoConcepts ne peuvent pas être localisés dans un passage textuel précis

### 2.2 Données par Document

| Document | Total | Avec Chunk | Sans Chunk | % Ancré |
|----------|-------|------------|------------|---------|
| Conversion_Guide_2025 | 247 | 169 | 78 | 68% |
| Upgrade_Guide_2023 | 202 | 123 | 79 | 61% |
| What's_New_2023_SPS04 | 184 | 112 | 72 | 61% |
| Installation_Guide_2021 | 141 | 48 | 93 | **34%** |
| Installation_Guide_2023 | 136 | 66 | 70 | 49% |
| Conversion_Guide_2022 | 91 | 53 | 38 | 58% |
| Upgrade_Guide_PCE_2025 | 84 | 48 | 36 | 57% |
| Conversion_Guide_2023 | 71 | 48 | 23 | 68% |
| Getting_Started_2023 | 38 | 23 | 15 | 61% |
| Access_Customer_Systems | 38 | 16 | 22 | 42% |
| Highlights_2023_FPS03 | 14 | 4 | 10 | **29%** |

### 2.3 Exemples de ProtoConcepts Sans ANCHORED_IN

```
┌────────────────────────────────────┬───────────────────────────────────┐
│ ProtoConcept (name)                │ Document source                   │
├────────────────────────────────────┼───────────────────────────────────┤
│ Interactive learning content       │ Getting_Started_Guide             │
│ Disclaimer and legal information   │ Getting_Started_Guide             │
│ SAP S/4HANA 2023                   │ Getting_Started_Guide             │
│ SAP S/4HANA Product Family         │ Getting_Started_Guide             │
│ Warranty Disclaimer                │ Conversion_Guide_2025             │
│ Software Update Manager (SUM)      │ Conversion_Guide_2025             │
└────────────────────────────────────┴───────────────────────────────────┘
```

Ces concepts ont bien `EXTRACTED_FROM → Document`, mais **pas** `ANCHORED_IN → DocumentChunk`.

---

## 3. Cause Technique

### 3.1 Pipeline d'Extraction

1. **Extraction PDF** (Docling) : PDF → texte structuré
2. **Segmentation** : Découpage en sections sémantiques
3. **Extraction LLM** : Le LLM extrait des concepts avec ou sans positions textuelles (spans)
4. **Chunking** : Découpage en chunks de 256 tokens
5. **Anchor Mapping** : Si le concept a un span, on trouve le chunk correspondant

### 3.2 Mécanisme d'Ancrage

```python
# Le concept doit avoir char_start et char_end pour être ancré
if anchor.char_start is not None and anchor.char_end is not None:
    # Trouver le chunk qui contient cette position
    for chunk in chunks:
        if chunk.start <= anchor.char_start < chunk.end:
            create_anchored_in_relation(concept, chunk)
            break
```

**Si un concept n'a pas de span textuel** (char_start/char_end = None), il ne peut pas être ancré à un chunk.

### 3.3 Pourquoi Certains Concepts N'ont Pas de Span ?

1. **Métadonnées** : Titre du document, auteur, version (pas de position dans le corps)
2. **Inférence LLM** : Concepts déduits du contexte global sans mention textuelle exacte
3. **Sections courtes** : Content extrait d'une zone trop petite pour générer un chunk
4. **Tables/Figures** : Concepts extraits de légendes ou cellules non chunkées

---

## 4. Question Architecturale

> **Faut-il exiger que TOUS les ProtoConcepts aient une relation ANCHORED_IN vers un DocumentChunk ?**

### 4.1 Arguments POUR l'Ancrage Obligatoire

| Argument | Détail |
|----------|--------|
| **Traçabilité totale** | Chaque concept peut être vérifié dans le texte source exact |
| **Cohérence modèle** | Pas de cas particuliers dans les requêtes Cypher |
| **RAG efficace** | Les chunks sont le point d'entrée pour la retrieval augmented generation |
| **Vérification factuelle** | L'utilisateur peut voir exactement où le concept est mentionné |

### 4.2 Arguments CONTRE l'Ancrage Obligatoire

| Argument | Détail |
|----------|--------|
| **Concepts globaux** | "SAP S/4HANA 2023" est le sujet de tout le document, pas d'un chunk |
| **Faux positifs RAG** | Forcer l'ancrage sur un chunk arbitraire pollue les résultats |
| **Traçabilité suffisante** | `EXTRACTED_FROM → Document` garantit déjà la provenance |
| **Perte d'information** | Rejeter les concepts sans span = perte de connaissances valides |

---

## 5. Options de Résolution

### Option A : Statu Quo
- Accepter que ~40% des ProtoConcepts soient "document-level" (sans ANCHORED_IN)
- Adapter les requêtes Cypher pour gérer les deux cas
- **Avantage** : Pas de modification du pipeline
- **Risque** : Incohérence dans les résultats de recherche par chunk

### Option B : Ancrage Fallback au Premier Chunk
- Créer `ANCHORED_IN` vers le premier chunk du document pour les concepts sans span
- Ajouter une propriété `anchor_type: "fallback"` pour distinguer
- **Avantage** : Modèle homogène (tous ancrés)
- **Risque** : Faux positifs lors de la recherche "concepts dans ce passage"

### Option C : Relation Alternative BELONGS_TO
- Créer une nouvelle relation `BELONGS_TO` vers Document pour les concepts globaux
- Garder `ANCHORED_IN` pour les concepts avec position précise
- **Avantage** : Sémantique claire (ancré vs appartient)
- **Risque** : Deux types de relations à gérer

### Option D : Filtrage à l'Extraction
- Ne garder que les concepts avec span textuel valide
- Rejeter ou taguer différemment les concepts "globaux"
- **Avantage** : Pureté du modèle
- **Risque** : Perte d'information (concepts légitimes sans position)

### Option E : Label Différent
- `AnchoredProtoConcept` : avec ANCHORED_IN
- `DocumentProtoConcept` : sans ANCHORED_IN (niveau document)
- **Avantage** : Distinction explicite dans le graphe
- **Risque** : Complexité accrue du schéma

---

## 6. État Actuel du KG

```
Nœuds :
- Document           : 13
- DocumentChunk      : 1,753
- ProtoConcept       : 1,246
- CanonicalConcept   : 959

Relations :
- EXTRACTED_FROM     : 1,246 (100% des ProtoConcepts)
- INSTANCE_OF        : 1,246 (100% des ProtoConcepts)
- ANCHORED_IN        : 731   (57% des ProtoConcepts)
```

---

## 7. Questions pour Arbitrage

1. **Quel est le use case prioritaire ?**
   - Recherche sémantique par chunk (RAG) → ancrage important
   - Diff entre versions SAP → ancrage moins critique
   - Vérification factuelle → ancrage idéalement requis

2. **Accepte-t-on deux "classes" de ProtoConcepts ?**
   - Ancrés (position précise) vs Document-level (sans position)

3. **Quelle option recommandez-vous ?**
   - A, B, C, D, E ou autre proposition ?

4. **Implications pour les requêtes et l'évolution ?**
   - Impact sur les requêtes Cypher existantes
   - Compatibilité avec les phases futures (consolidation, cross-doc)
