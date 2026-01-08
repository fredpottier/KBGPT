# Analyse des Faux Positifs Markers - Janvier 2026

**Contexte** : Analyse pour review ChatGPT
**Date** : 2026-01-07

---

## 1. État Constaté (Avant Nettoyage)

### 1.1 Documents VARIANT_SPECIFIC avec markers problématiques

| Document | Markers bruts | Faux positifs identifiés |
|----------|---------------|--------------------------|
| `20251212_Business-Scope-2025-SAP-Cloud-ERP-Private` | ["2025", "Private", "Private"] | "Private" (x2) |
| `Business-Scope-S4HANA-Cloud-Private-Edition-FPS03` | ["FPS03", "Private", "2023", "based", "any"] | "Private", "based", "any" |
| `SAP-014_What's_New_..._2023_SPS04` | ["Edition 2023", "2023", "SPS04", "Content 2", "PUBLIC 3"] | "Content 2", "PUBLIC 3" |
| `SAP-016_..._Innovations_(2023_FPS03)` | ["Edition 2023", "FPS03", "Public 2", "Public 3", "2023"] | "Public 2", "Public 3" |
| `SAP-020_SAP_BTP_Guidance_Framework...` | ["January 30", "PUBLIC 2", "PUBLIC 3"] | "PUBLIC 2", "PUBLIC 3" |
| `SAP-021_SAP_Business_AI...` | ["PUBLIC 1", "2.6", "4.4", "EXTERNAL 2", "Resources 42", "PUBLIC 3"] | Multiples artefacts |

### 1.2 Catégorisation des faux positifs

| Type | Exemples | Origine probable |
|------|----------|------------------|
| **Numérotation sections** | "Content 2", "PUBLIC 3", "EXTERNAL 2", "Resources 42" | Pattern ENTITY_NUMERAL capture "MOT + chiffre" |
| **Mots courants seuls** | "based", "any" | Extraction incorrecte (source non identifiée) |
| **Type de déploiement** | "Private" | Pas une version, c'est un qualificatif |

---

## 2. Architecture CandidateGate (Implémentation Actuelle)

### 2.1 Pipeline d'extraction des markers

```
Document
    ↓
┌─────────────────────────────────────┐
│  CandidateMiner                     │
│  - SEMVER_PATTERNS (v1.2.3)         │
│  - ENTITY_NUMERAL_PATTERNS          │  ← PROBLÈME ICI
│  - RELEASE_FORM_PATTERNS            │
│  - STRUCTURED_CODE_PATTERNS         │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  CandidateGate (filtrage)           │
│  - DATE_FORMAT (MM/DD/YYYY)         │
│  - QUARTER (Q4 2023)                │
│  - COPYRIGHT (© 2023)               │
│  - MONTH_YEAR (January 2023)        │
│  - FISCAL_YEAR (FY2023)             │
│  - TEMPORAL_REF (since 2019)        │
│  - UNIT (100 kg, 50%)               │
│  - EXAMPLE (e.g., for instance)     │
│  - REFERENCE_ID (Note 123456)       │
│  - PAGE_REF (Page 23, Slide 5)      │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  LLM Validation (Arbitre)           │
│  - CONTEXT_SETTING                  │
│  - TEMPLATE_NOISE                   │
│  - AMBIGUOUS                        │
└─────────────────────────────────────┘
    ↓
DocContextFrame (strong_markers, weak_markers)
```

### 2.2 Le pattern ENTITY_NUMERAL problématique

**Fichier** : `src/knowbase/extraction_v2/context/candidate_mining.py`

```python
ENTITY_NUMERAL_PATTERNS = [
    r'\b([A-Z][a-zA-Z0-9/]*)\s+(\d{4})\b',  # ProductName 2023
    r'\b([A-Z][a-zA-Z0-9/]*)\s+(\d{1,2})\b',  # iPhone 15  ← TROP PERMISSIF
    r'\b([A-Z][a-zA-Z0-9/]*)\s+[Vv]?(\d+(?:\.\d+)?)\b',  # Windows v10
]
```

**Problème** : Le pattern `[A-Z][a-zA-Z0-9/]*\s+(\d{1,2})` capture :
- ✅ "iPhone 15" (voulu)
- ❌ "PUBLIC 3" (faux positif - numéro de section)
- ❌ "Content 2" (faux positif - numéro de section)
- ❌ "ONLY 2" (faux positif - mot courant + chiffre)

### 2.3 Filtres CandidateGate existants

Le CandidateGate filtre correctement :
- Dates explicites (MM/DD/YYYY, YYYY-MM-DD)
- Trimestres (Q4 2023)
- Copyright (© 2023)
- Années fiscales (FY2023)
- Références temporelles (since 2019)
- Unités de mesure (100 kg)
- Numéros de page (Page 23)

**Mais ne filtre PAS** :
- Numérotation de sections/chapitres (PUBLIC 3, Content 2)
- Mots anglais courants suivis d'un chiffre

---

## 3. Conformité avec les ADRs

### 3.1 ADR_DOCUMENT_STRUCTURAL_AWARENESS.md

**Principe clé** (Section 2.1) :
> "Un marqueur n'est valide que s'il contribue à différencier le document en tant qu'artefact informationnel."

**Règle 3** :
> "`lexical_shape` ne doit JAMAIS être utilisé pour inférer un sens."

**Déviation constatée** : Le pattern ENTITY_NUMERAL infère implicitement qu'un mot en majuscule suivi d'un chiffre est une version/variante. C'est une inférence sémantique basée sur la forme lexicale.

### 3.2 ADR_MARKER_NORMALIZATION_LAYER.md

**Section 1.2** (Analyse des données) :
```
"Content 2": 5 docs     <- FAUX POSITIF (artefact)
"PUBLIC 3": 5 docs      <- FAUX POSITIF (artefact)
"based": 1 doc          <- FAUX POSITIF
"any": 1 doc            <- FAUX POSITIF
```

**Observation critique** : "~40% des markers actuels sont des faux positifs"

**Solution proposée dans l'ADR** (Section 4.3) :
> "Blacklist tenant-level + migration script"

**Problème** : Cette solution est domain-specific (on doit connaître "Content", "PUBLIC", etc. à l'avance).

### 3.3 Principe d'agnosticisme violé

**ADR_MARKER_NORMALIZATION_LAYER.md - Section 4.4** :
> "PAS DE DOMAIN-SPECIFIC DANS LE MOTEUR"
> "Le moteur de normalisation ne contient AUCUNE regle métier hardcodée"

**Déviation** : Le pattern ENTITY_NUMERAL encode une hypothèse implicite que "MOT_MAJUSCULE + CHIFFRE" = version/variante. Cette hypothèse n'est valide que pour certains domaines (tech, auto) mais génère du bruit pour d'autres (documents avec sections numérotées).

---

## 4. Analyse Racine du Problème

### 4.1 Hypothèse implicite du pattern ENTITY_NUMERAL

Le pattern suppose que :
- `iPhone 15` = produit + génération ✅
- `PUBLIC 3` = produit + génération ❌ (c'est une section)
- `Content 2` = produit + génération ❌ (c'est une section)

**Le pattern ne distingue pas** :
- Entité (iPhone, Windows, S/4HANA) vs Mot générique (PUBLIC, Content, ONLY)
- Numéro de version vs Numéro de section/chapitre

### 4.2 Pourquoi le LLM ne filtre pas ces cas ?

Le LLM reçoit les candidats pré-extraits et doit arbitrer entre CONTEXT_SETTING et TEMPLATE_NOISE.

**Mais** :
1. "PUBLIC 3" peut apparaître dans le corps du document (pas footer)
2. Le LLM n'a pas de signal structurel indiquant "c'est un numéro de section"
3. Sans context suffisant, le LLM peut valider le candidat

### 4.3 Le vrai problème : conflit de forme vs sens

Les patterns actuels capturent une **forme lexicale** (MOT + CHIFFRE) sans pouvoir distinguer le **sens** (version vs section).

---

## 5. Pistes de Résolution (Domain-Agnostic)

### Piste A : Enrichir les signaux structurels

**Idée** : Détecter les patterns de numérotation de sections dans le document.

**Signaux possibles** :
- Présence de "1.", "2.", "3." ou "Chapter 1", "Section 2" dans le même document
- Séquentialité : si on trouve "PUBLIC 1", "PUBLIC 2", "PUBLIC 3", c'est probablement une numérotation
- Position : numéros de sections souvent en début de ligne/paragraphe

**Avantage** : Agnostique - détecte le pattern de numérotation quel que soit le mot.

### Piste B : Exiger un Entity Anchor fort

**Idée** : Ne valider un pattern ENTITY_NUMERAL que si l'entité est aussi un concept extrait du document.

**Exemple** :
- "iPhone 15" → Si "iPhone" est un concept du document → Valide
- "PUBLIC 3" → "PUBLIC" n'est pas un concept → Rejet

**Avantage** : Utilise le KG existant comme validation croisée.

**Inconvénient** : Dépend de la qualité de l'extraction de concepts.

### Piste C : Analyse de co-occurrence séquentielle

**Idée** : Si plusieurs candidats forment une séquence (1, 2, 3), c'est probablement une numérotation, pas des versions.

**Exemple** :
- Document avec ["PUBLIC 1", "PUBLIC 2", "PUBLIC 3"] → Séquence détectée → Rejet de tous
- Document avec ["Edition 2023", "FPS03"] → Pas de séquence → Conservé

**Avantage** : Pattern universel de numérotation.

### Piste D : Renforcer le filtre PAGE_REF du CandidateGate

**Idée** : Étendre le filtre PAGE_REF pour capturer les patterns de sections.

**Patterns à ajouter** :
```python
SECTION_PATTERNS = [
    r'\b(Chapter|Section|Part|Appendix|Module)\s+(\d+)\b',
    r'\b([A-Z]+)\s+(\d+)\b(?=\s*[:\.\-])',  # "PUBLIC 3:" ou "PUBLIC 3."
]
```

**Problème** : Peut être trop restrictif (rejette des vrais markers).

### Piste E : Score de "genericité" du préfixe

**Idée** : Certains mots sont statistiquement plus susceptibles d'être des sections que des produits.

**Méthode** :
1. Calculer la fréquence du mot dans le corpus général (ex: "PUBLIC" très fréquent)
2. Plus le mot est fréquent/générique, plus le seuil de validation est haut

**Avantage** : Basé sur la statistique, pas sur une liste.

**Inconvénient** : Nécessite un corpus de référence.

---

## 6. Questions pour ChatGPT

1. **Piste recommandée** : Quelle(s) piste(s) semblent les plus prometteuses tout en restant agnostiques ?

2. **Combinaison** : Faut-il combiner plusieurs pistes (ex: A + B) ?

3. **Seuil de tolérance** : Quel niveau de faux positifs est acceptable si on veut éviter les faux négatifs ?

4. **Pattern ENTITY_NUMERAL** : Faut-il restreindre ce pattern (ex: exiger 4+ chiffres) ou le supprimer entièrement et compter sur d'autres signaux ?

5. **LLM comme filet** : Le LLM devrait-il avoir plus de pouvoir pour rejeter des candidats même sans signaux structurels forts ?

---

## 7. Données Nettoyées (Post-Fix)

Après nettoyage manuel des faux positifs identifiés :

| Document | Markers nettoyés |
|----------|------------------|
| `20251212_Business-Scope-2025-...` | ["2025"] |
| `Business-Scope-S4HANA-...-FPS03` | ["FPS03", "2023"] |
| `SAP-014_What's_New_..._2023_SPS04` | ["Edition 2023", "2023", "SPS04"] |
| `SAP-016_..._Innovations_(2023_FPS03)` | ["Edition 2023", "FPS03", "2023"] |

**Résumé** :
- Documents GENERAL : 3 (0 markers) ✓
- Documents VARIANT_SPECIFIC : 4 (markers cohérents) ✓
