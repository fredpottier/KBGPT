# Diagnostic : Extraction de version dans le DocumentContext

**Date :** 2026-02-06
**Contexte :** Projet OSMOSE — Pipeline Claim-First d'extraction de connaissances
**Objectif de ce document :** Partage inter-IA pour avis sur la stratégie de résolution

---

## 1. Contexte général du projet

OSMOSE est un système d'extraction de connaissances à partir de corpus documentaires hétérogènes. Le pipeline "Claim-First" ingère des documents (PDF, PPTX, DOCX) et construit un Knowledge Graph dans Neo4j.

Pour chaque document, le pipeline crée un nœud **DocumentContext** qui capture le **scope d'applicabilité** du document : de quoi parle-t-il, quelle version, quelle édition, etc. C'est la "carte d'identité" du document dans le graphe.

### Invariant fondamental : Agnosticisme de domaine

**Le système DOIT être domain-agnostic.** Il ne connaît pas a priori le domaine des documents (logiciel SAP, automobile, pharmaceutique, juridique, etc.). Les conventions de versioning varient radicalement selon les domaines :

- Logiciel SAP : "1809", "2023", "2025 FPS 03"
- Automobile : "Mk7", "Génération 4", "MY2024"
- Pharmaceutique : "Dosage 500mg", "Lot #A7842"
- Juridique : "Directive 2016/679", "amendement 2023"

Le système ne peut PAS hardcoder des patterns spécifiques à un domaine.

### Surcouche optionnelle : Domain Context

Une fonctionnalité "Domain Context" permet à l'administrateur de configurer manuellement un contexte métier (industrie, acronymes, concepts clés). Ce contexte peut être injecté dans les prompts LLM comme enrichissement. **Mais il ne peut pas être le fondement de la solution** — le pipeline doit fonctionner correctement même sans Domain Context configuré.

---

## 2. Architecture actuelle de l'extraction

### 2.1 Pipeline DocumentContext

```
Document (PDF/PPTX)
    ↓
Phase 0: Découpage en Passages (chunks de texte)
    ↓
Phase 0.5: ContextExtractor
    → Extrait primary_subject (sujet principal)
    → Extrait raw_subjects (sujets secondaires)
    → Extrait qualifiers bootstrap (version, region, edition via regex)
    ↓
Phase 0.55: SubjectResolverV2
    → Résout les sujets vers des ComparableSubject
    ↓
Phase 0.6: ApplicabilityAxisDetector
    → Détecte les axes discriminants (version, année, édition...)
    → AxisValueValidator valide via LLM
    → Met à jour doc_context.axis_values
    ↓
Phase 7: Persistence Neo4j
    → DocumentContext node avec primary_subject, qualifiers, axis_values
    → Relations HAS_AXIS_VALUE vers ApplicabilityAxis nodes
```

### 2.2 Extraction des axes (le cœur du problème)

L'`ApplicabilityAxisDetector` utilise une architecture "LLM-first" en 3 niveaux :

**Niveau 1 — LLM Primary :**
- Envoie un prompt au LLM avec un échantillon du document
- Le LLM identifie les "caractéristiques discriminantes" (version, année, édition...)
- Retourne des paires (axis_key, value) en JSON

**Niveau 2 — Fallback Patterns (si LLM échoue) :**
- Regex domain-agnostic : year (copyright), effective_date, edition, phase
- Scan de TOUS les passages

**Niveau 3 — Metadata :**
- Propriétés structurées du document (si disponibles)

**Puis validation :**
- L'`AxisValueValidator` demande au LLM de confirmer/rejeter chaque candidat

### 2.3 Le problème critique : fenêtre de contexte

**L'AxisDetector (Niveau 1 LLM) ne voit que les 5 premiers passages du document, tronqués à 600 caractères chacun.** Soit environ **3 Ko de texte** envoyés au LLM.

Pour un document de 1 Mo (1451 passages), cela représente **0.3% du contenu**.

### 2.4 Bootstrap qualifiers (ContextExtractor)

En parallèle, le `ContextExtractor` applique un mini-set de regex bootstrap :
```python
BOOTSTRAP_QUALIFIERS = {
    "version": re.compile(r"(?:version|release|v\.?)\s*(\d+(?:\.\d+)*|\d{4})", re.IGNORECASE),
    "region":  re.compile(r"(?:for|in)\s+(EU|US|APAC|China|global)", re.IGNORECASE),
    "edition": re.compile(r"(Enterprise|Standard|Professional|Private|Public)\s+(?:Edition|Cloud)", re.IGNORECASE),
    "year":    re.compile(r"\b(20\d{2})\b"),
}
```

Ces patterns sont appliqués sur les **5000 premiers caractères** du document seulement.

Le qualifier `year` matche `\b(20\d{2})\b` — le premier nombre au format année trouvé dans les premiers chars. Cela attrape souvent le copyright plutôt que la version produit.

---

## 3. Données de test : 3 documents SAP

Nous testons avec 3 documents SAP S/4HANA de périmètre fonctionnel (Business Scope / Feature Scope) :

### Document 018 — S/4HANA 1809 Business Scope (PPTX)
- **234 passages**, 48 618 caractères
- **Version réelle : 1809** (release octobre 2018)
- Fréquence "1809" : **7 passages**
- Fréquence "2025" : 4 passages (mentions récentes ajoutées au deck)
- Fréquence "2023" : 1 passage

### Document 023 — SAP Cloud ERP Private Edition 2025 (PPTX)
- **558 passages**, 95 929 caractères
- **Version réelle : 2025** (SAP S/4HANA Cloud Private Edition 2025)
- Fréquence "2025" : **17 passages**
- Fréquence "2023" : 8 passages (version précédente mentionnée)
- Le tout premier passage dit littéralement : `"based on SAP S/4HANA Cloud Private Edition 2025"`

### Document 025 — SAP S/4HANA 2023 Feature Scope Description (PDF)
- **1 451 passages**, 1 015 071 caractères (~1 Mo)
- **Version réelle : 2023** (SAP S/4HANA 2023 FPS 03)
- Fréquence "2023" : **3 passages** seulement (sur 1451)
- Fréquence "2025" : **0 passages**
- Info clé au passage [32] : `"Initial Version for SAP S/4HANA 2023"`
- Info clé au passage [34] : URL `help.sap.com/s4hana_op_2023`

---

## 4. Résultats actuels (incorrects)

### Ce qui a été extrait :

| Document | primary_subject | qualifiers | Axes HAS_AXIS_VALUE |
|----------|----------------|------------|---------------------|
| 018 (1809) | `S/4HANA` | `{"version": "1809"}` | version=`1809`, year=`2019` |
| 023 (2025) | `SAP S/4HANA Cloud Private Edition` | `{"edition": "Private"}` | version=`SAP S/4HANA Cloud Private Edition 2025`, product_name=`SAP Cloud ERP Private` |
| 025 (2023) | `SAP S/4HANA` | `{}` | year=`2025` |

### Problèmes identifiés :

**Problème 1 — Doc 025 (2023) : year = "2025" alors que "2025" n'existe nulle part dans le document**
- C'est une **hallucination du LLM** — il a inventé "2025" comme année probable pour un doc récent
- La vraie version "2023" apparaît dans les 5 premiers passages que le LLM a reçus
- Mais le LLM l'a soit raté, soit confondu avec une date de version de document (pas de produit)
- Les qualifiers sont vides `{}` — même le bootstrap n'a pas capturé "2023" comme version

**Problème 2 — Doc 023 (2025) : version = "SAP S/4HANA Cloud Private Edition 2025" au lieu de "2025"**
- Le LLM a inclus le nom complet du produit dans la valeur de version
- Le prompt dit "valeur COMPLÈTE (pas tronquée)" — le LLM a interprété cela comme "inclure tout le contexte"
- Devrait être simplement "2025" comme valeur de l'axe version

**Problème 3 — Doc 018 (1809) : year = "2019"**
- Le bootstrap qualifier `\b(20\d{2})\b` a matché un copyright "2019" dans le texte
- C'est l'année de copyright, pas une année de release pertinente
- La vraie version "1809" est correctement capturée, mais "year" est parasite

**Problème 4 — 3 ComparableSubjects non fusionnés**
- "S/4HANA", "SAP S/4HANA", "SAP S/4HANA Cloud Private Edition" sont 3 nœuds séparés
- Ils représentent le même produit (ou des variantes proches)
- Empêche la comparaison cross-document

**Problème 5 — Axes parasites extraits du doc_id**
- Pour le doc 018, des axes `file_checksum`, `file_id`, `file_type` ont été extraits du nom de fichier
- Ce sont des artefacts techniques, pas des axes sémantiques

---

## 5. Causes racines

### 5.1 Fenêtre de contexte trop petite pour le LLM

Le LLM ne voit que 5 passages × 600 chars = ~3 Ko sur un document qui peut faire 1 Mo. Pour le doc 025 (2023), l'info de version est présente dans les passages [32] et [34] que le LLM a bien reçus, mais il ne l'a pas correctement interprétée — et a halluciné "2025".

### 5.2 Aucun signal statistique fourni au LLM

Le LLM reçoit un fragment de texte brut et doit deviner la version. Il n'a aucune information sur :
- La fréquence d'apparition des candidats dans le document complet
- Les co-occurrences entre candidats et le sujet principal
- La distribution positionnelle des mentions

Sans ces signaux, le LLM opère "à l'aveugle" sur un fragment.

### 5.3 Le bootstrap qualifier `year` est trop naïf

`\b(20\d{2})\b` sur les premiers 5000 chars matche systématiquement le copyright ou une date incidentelle, rarement la version du produit.

### 5.4 Le Domain Context n'est pas injecté dans l'AxisDetector

Bien que configuré, le Domain Context n'est jamais utilisé par l'AxisDetector. Le prompt est 100% générique.

---

## 6. Contraintes de design

1. **Agnosticisme de domaine (INV-25)** — La solution DOIT fonctionner sans connaître le domaine. SAP, pharmaceutique, automobile, juridique — les mêmes algorithmes doivent s'appliquer.

2. **Evidence obligatoire (INV-26)** — Chaque valeur extraite doit être traçable vers un passage source. Pas de valeur inventée.

3. **Discriminants découverts, pas hardcodés (INV-10)** — On ne peut pas coder en dur "pour SAP, la version est au format YYYY".

4. **Le titre/nom de fichier n'est PAS fiable** — Un utilisateur peut nommer son fichier comme il veut (`monErp_v3_2026.pdf`). Le contenu du document est la seule source de vérité.

5. **Le Domain Context est un enrichissement optionnel** — Il améliore la précision quand configuré, mais n'est pas requis pour le fonctionnement de base.

6. **Le contenu complet doit être exploité** — Il est statistiquement probable que la version réapparaisse dans le contenu. Un scan exhaustif est préférable à un échantillon de 5 passages.

---

## 7. Pistes de résolution envisagées

### Piste A — Scan fréquentiel full-document (pré-LLM)

**Principe :** Scanner TOUS les passages du document avec des regex légers pour extraire les candidats "version-like" et construire un profil statistique.

**Étapes :**
1. Regex domain-agnostic : `\b\d{4}\b` (années), `\bv?\d+\.\d+\b` (versions numériques), etc.
2. Pour chaque candidat : compter la fréquence, noter la co-occurrence avec `primary_subject`, noter la position
3. Passer ce profil (pas le texte brut) au LLM pour classification

**Avantages :** Exploite 100% du contenu, signal robuste, domain-agnostic
**Risques :** Les regex pour "version-like" peuvent eux-mêmes être biaisés ; `\b\d{4}\b` matche autant une version qu'un numéro de page

### Piste B — Échantillonnage stratégique (au lieu de "premiers 5")

**Principe :** Remplacer "5 premiers passages" par un échantillon intelligent :
- Passages contenant des patterns de table des matières / historique de versions
- Passages contenant le primary_subject + un nombre
- Premiers ET derniers passages (copyright, date publication)

**Avantages :** Meilleure couverture, coût LLM contrôlé
**Risques :** L'heuristique de sélection peut manquer des passages importants

### Piste C — Two-pass : Scan statistique + LLM classification (recommandée)

**Principe :** Combiner les forces du scan exhaustif et du LLM.

**Pass 1 (cheap, sans LLM) :**
- Scanner tous les passages avec regex légers
- Extraire tous les candidats avec leur contexte ±50 chars
- Calculer : fréquence, co-occurrence avec primary_subject, position moyenne

**Pass 2 (LLM) :**
- Envoyer les top-N candidats avec leurs statistiques au LLM
- Le LLM choisit la bonne valeur en ayant un signal statistique solide

**Exemple de prompt Pass 2 :**
```
Le document "SAP S/4HANA Feature Scope Description" (1451 passages) contient ces candidats version :

1. "2023" — 3 occurrences, co-occurrence avec "SAP S/4HANA" dans 2/3 cas
   Contextes : "Initial Version for SAP S/4HANA 2023", "help.sap.com/s4hana_op_2023"
2. "2024" — 1 occurrence, contexte : "2024-02-28" (date ISO dans un tableau de versions)
Aucune mention de "2025" dans le document.

Quelle est la version produit de ce document ?
```

**Avantages :**
- Le LLM ne peut pas halluciner une valeur absente (les stats le prouvent)
- Le signal fréquentiel discrimine copyright vs version
- La co-occurrence primary_subject + candidat est un très bon signal
- Reste domain-agnostic

**Risques :** Deux étapes = plus de complexité

### Piste D — Injection du Domain Context (enrichissement)

**Principe :** Quand configuré, injecter le Domain Context dans le prompt de l'AxisDetector.

**Impact :** Le LLM sait que "dans ce domaine, les versions SAP sont au format YYYY ou YYYY FPS XX" → meilleure précision.

**Position :** Surcouche optionnelle, pas fondement. Le pipeline DOIT fonctionner sans.

### Recommandation

**Piste C + D** semble la plus robuste :

1. **Scan fréquentiel exhaustif** (tous les passages, regex léger, zéro coût LLM) → profil statistique
2. **LLM informé** qui reçoit les candidats avec statistiques (pas du texte brut aveugle)
3. **Domain Context injecté** dans le prompt si disponible (amélioration, pas prérequis)

---

## 8. Questions ouvertes

1. **Quels patterns regex utiliser pour le scan fréquentiel sans être domain-specific ?** Les nombres à 4 chiffres (`\d{4}`) matchent beaucoup de faux positifs (numéros de page, codes). Les patterns `version X.Y` sont déjà domain-specific.

2. **Comment distinguer statistiquement un copyright d'une version produit ?** Un copyright apparaît typiquement 1-2 fois (footer/header). Une version produit apparaît dans le contenu métier. Mais pour des petits documents ?

3. **Faut-il pré-filtrer les candidats avant le LLM ?** Si le scan retourne 50 candidats, comment choisir les top-N à envoyer au LLM ?

4. **Comment gérer les documents où la version n'apparaît que 1-2 fois ?** Le signal fréquentiel est faible. Exemple : doc 025 (2023) ne mentionne "2023" que 3 fois sur 1451 passages.

5. **Le scan fréquentiel doit-il exploiter le contexte autour du candidat ?** `"SAP S/4HANA 2023"` est plus informatif que juste `"2023"`. Mais analyser le contexte pour tous les candidats augmente la complexité.
