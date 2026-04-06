# ADR — Vision Out of the Knowledge Path (Evidence-First Constraint)

**Date:** 2026-01-26
**Statut:** Accepté
**Auteurs:** Fred Pottier, Claude, ChatGPT (diagnostic)

---

## 1. Contexte et Objectif

### 1.1 Le Contrat Evidence-First

Le pipeline OSMOSE V2 repose sur une séparation stricte :

- **Structure documentaire** = preuve et audit : `Document → Section → DocItem` (atomes)
- **Structure sémantique** = compréhension et navigation : `Subject → Theme → Concept → Information`

**Axiome fondateur** :

> **Pas d'assertion sans preuve localisable.**

Ce contrat est le cœur "cortex documentaire" : une `Information` persistée doit être `ANCHORED_IN` un `DocItem`, jamais sur un chunk "retrieval" ou une paraphrase.

### 1.2 Définition : Unité de Connaissance (Knowledge Unit)

> **Une Knowledge Unit est une assertion :**
> - **extraite textuellement** (verbatim ou near-verbatim),
> - **transportable** hors de son contexte narratif,
> - **ancrable de manière déterministe** à un DocItem.

Cette définition est **indépendante de la technologie** (Vision, OCR, LLM). Tout module produisant des candidats doit se conformer à ce critère.

### 1.3 Le Chemin Critique de Connaissance

> **Chemin critique** = Tout ce qui mène à une `Information` persistée et exploitable dans le raisonnement décisionnel.

| Composant | Dans le chemin critique ? |
|-----------|---------------------------|
| TEXT pipeline (parser + OCR) | ✅ OUI |
| Vision | ❌ NON |
| VisionObservation | ❌ NON (navigation uniquement) |

### 1.4 Le Problème

Vision (GPT-4o) était utilisée pour extraire des informations des pages visuelles (slides, diagrammes). Ces extractions étaient injectées dans le flux `InformationMVP → Information`.

Résultat observé : **taux d'ancrage très faible** (~12-17%) malgré plusieurs tentatives d'optimisation.

---

## 2. Données Expérimentales

### 2.1 Chronologie des Tests

| Test | Configuration | InformationMVP | Information (ancrées) | Anchor Rate |
|------|---------------|----------------|----------------------|-------------|
| Run 1 | Vision ON (prompt FR) | 831 | 149 | 17.9% |
| Run 2 | Vision ON (prompt EN) | 1040 | 125 | 12.0% |
| Run 3 | Vision "Extractive Only" v3.0 | 1066 | 151 | 14.2% |
| **Run 4** | **TEXT-ONLY (Vision OFF)** | **316** | **179** | **56.6%** |

### 2.2 Analyse par Langue (Run 2 - Vision ON)

| Langue | InformationMVP | Anchor OK | Taux |
|--------|----------------|-----------|------|
| Anglais | 386 (48%) | 149 | 38.6% |
| Français | 420 (52%) | 0 | 0% |

### 2.3 Distribution TEXT-ONLY (Run 4)

| Type | Count |
|------|-------|
| DEFINITIONAL | 213 |
| PRESCRIPTIVE | 101 |
| CAUSAL | 2 |
| **Total** | **316** |

- Assertions FR : **0%** (100% anglais)
- Promoted : 179
- Rejected : 176
- Abstained : 137

---

## 3. Diagnostic Final

### 3.1 Ce n'est PAS un problème de linking conceptuel

Le linking vers `Concept` fonctionne (97% des MVP sont PROMOTED_LINKED). Le blocage est à l'ancrage DocItem.

### 3.2 Ce n'est PAS un problème de langue

Le fix EN a éliminé le mismatch linguistique, sans résoudre l'ancrage.

### 3.3 La cause racine : Mismatch de Représentation

Vision produit naturellement des **descriptions interprétatives** (niveau "compréhension") :
```
"The slide presents a 'Shared Security Responsibility Model'..."
"It is divided into two main sections..."
"The diagram shows the architecture..."
```

L'ancrage exige du **texte extractif localisable** (niveau "preuve") :
```
"SAP Cloud Services Preventive Controls for Cloud Accounts"  // Exact DocItem text
```

**Même en demandant "verbatim only"**, Vision n'opère pas dans le même espace :
- Elle ne manipule pas un flux textuel segmenté identique à celui des DocItems
- Elle tend à synthétiser/nommer/structurer plutôt qu'à citer
- Elle génère des assertions **non-matchables par design**

### 3.4 Preuve Causale

Le test TEXT-ONLY prouve que Vision injecte **~750 assertions supplémentaires** (1066 - 316) qui sont majoritairement non-ancrables et dégradent mécaniquement le taux d'ancrage.

### 3.5 Clarification Importante

> **Cette décision ne remet pas en cause la valeur de Vision.**
>
> Vision est performante pour :
> - compréhension globale d'une page,
> - description de structures visuelles (diagrammes, schémas),
> - aide à la navigation et à l'exploration.
>
> Elle est écartée uniquement du **chemin de production des Knowledge Units**, en raison d'un mismatch structurel avec les exigences de preuve.

---

## 4. Décisions et Invariants

### Invariants Système (non négociables)

| # | Invariant | Conséquence |
|---|-----------|-------------|
| **I1** | Toute `Information` doit être ancrée sur un `DocItem` | Pas d'Information "flottante" |
| **I2** | Aucun contenu non-extractif ne peut produire une `InformationMVP` | Vision exclu du flux Knowledge |
| **I3** | Toute amélioration du taux d'ancrage ne doit pas réduire la défendabilité de la preuve | Pas de fuzzy permissif |

### Décision 1 — "Text is the Only Source of Truth for Knowledge Units"

Seul le pipeline textuel (parser + OCR si besoin) peut produire :
- `InformationMVP`
- `Information` (persistée et ancrée)

### Décision 2 — "Vision is Non-Ancrable by Design"

Vision ne produit **jamais** d'assertions destinées à l'ancrage DocItem.

### Décision 3 — Séparation Ontologique

Deux familles de sorties distinctes :

#### A) Knowledge Units (ancrables)

```
ExtractiveAssertion → InformationMVP → (si ancrée) Information
```

**Contrat** : doit contenir un `exact_quote` (verbatim) + ancre DocItem résolue.

#### B) Vision Observations (non-ancrables)

```
VisionObservation (nouveau type)
```

**Contenu** : description, structure visuelle, liste d'éléments, résumé de schéma

**Usage** : navigation/exploration/UX, mais **jamais preuve**, **jamais Information**

**Restriction critique** :
> Les `VisionObservation` **ne participent pas aux mécanismes de raisonnement, de justification ou de décision**.
> Elles sont strictement informatives et non normatives.
> Elles ne peuvent pas être reliées à `Concept` ou `Information` — afin d'éviter toute pollution du graphe conceptuel par des entités non prouvées.

**Évolutivité garantie** :
> Les `VisionObservation` peuvent évoluer librement (nouveaux modèles, nouveaux prompts, nouvelles structures) **sans impacter la fiabilité du graphe de connaissance**.
> Cette séparation n'est pas restrictive, elle est **protectrice**.

---

## 5. Conséquences Architecturales

### 5.1 Nouveaux Types Neo4j

```cypher
// Observation Vision (hors graphe de connaissance)
(:VisionObservation {
  observation_id: string,
  page_no: int,
  diagram_type: string,      // "slide" | "table" | "diagram" | "form"
  description: string,       // Texte descriptif généré par Vision
  key_entities: [string],    // Entités détectées visuellement
  confidence: float,
  model: string,
  prompt_version: string
})

// Relation : lié au document, pas aux concepts
(:VisionObservation)-[:DESCRIBES_PAGE]->(:DocItem)
// INTERDIT : (:VisionObservation)-[:SUPPORTS]->(:Concept)
```

### 5.2 Modification Pipeline

```python
# AVANT (Vision → InformationMVP)
if vision_semantic_result:
    assertions = extract_assertions(vision_semantic_result.semantic_text)
    for assertion in assertions:
        create_information_mvp(assertion)  # ❌ INTERDIT

# APRÈS (Vision → VisionObservation)
if vision_semantic_result:
    create_vision_observation(
        page_no=vision_semantic_result.page_no,
        description=vision_semantic_result.semantic_text,
        diagram_type=vision_semantic_result.diagram_type,
        key_entities=vision_semantic_result.key_entities
    )  # ✅ Séparé du graphe de connaissance
```

### 5.3 API/UI Gates

| Endpoint | Affiche |
|----------|---------|
| `/api/knowledge/*` | Information (ancrées) uniquement |
| `/api/assertions/*` | InformationMVP extractives |
| `/api/vision/*` | VisionObservation (navigation) |

L'UI doit séparer visuellement les observations Vision (autre onglet/couche).

---

## 6. Plan d'Implémentation

### Phase 1 : Couper Vision du flux InformationMVP (immédiat)

1. [ ] Modifier `semantic_reader.py` : ne plus retourner `semantic_text` pour assertion extraction
2. [ ] Modifier `pass1/orchestrator.py` : ignorer chunks VISION pour assertion extraction
3. [ ] Créer modèle `VisionObservation` dans Neo4j
4. [ ] Persister Vision outputs dans `VisionObservation` au lieu de `InformationMVP`

### Phase 2 : Vision comme aide indirecte (optionnel)

Vision peut produire :
- **Hints** : "page likely contains a diagram about X"
- **Regions of interest** : index de pages/slides pertinentes

Ces hints déclenchent ensuite une extraction textuelle/OCR ciblée, qui seule peut produire des assertions.

---

## 7. Plan d'Amélioration de l'Ancrage (sans fuzzy permissif)

**Objectif** : 56.6% → ~65-75%

> **Cadrage** : Cette cible n'est pas un objectif d'optimisation absolu, mais un ordre de grandeur attendu pour un corpus réel, hétérogène et non rédigé pour l'extraction automatique.
> Elle ne doit jamais être atteinte au détriment de la défendabilité de la preuve.

### Levier A — Granularité DocItems

- S'assurer que les DocItems sont atomiques (phrase/paragraphe court)
- Normaliser : enlever artefacts (hyphenation, bullets, whitespace)

### Levier B — Renforcer l'extractif

- Exiger `exact_quote` (verbatim) pour toute assertion candidate
- Si pas d'exact_quote → ABSTAIN

### Levier C — OCR ciblé et robuste

- Détecter pages "non-textual dominant"
- Lancer OCR ciblé pour produire du texte ancrable
- Intégrer dans DocItems avec provenance page/zone

### Levier D — Ancrage déterministe

- Matching exact/near-exact après normalisation
- Alignement par substring windows
- Ancrage multi-étapes (candidate DocItems par page/section puis match local)

### Levier E — Réduire faux candidats

- Filtre interrogatif (questions)
- Filtre meta/boilerplate enrichi
- Filtre fragments et titres isolés

---

## 8. Métriques de Pilotage

| Métrique | Cible | Actuel |
|----------|-------|--------|
| Anchor Rate (TEXT-ONLY) | >65% | 56.6% |
| Assertions extractives vs non | >95% | - |
| VisionObservations (UX) | Séparé | N/A |

**Distribution échecs d'ancrage à monitorer** :
- `NO_DOCITEM_MATCH`
- `AMBIGUOUS_SPAN`
- `CROSS_DOCITEM`
- `TEXT_NORMALIZATION_MISMATCH`

---

## 9. Alternatives Rejetées

### 9.1 Baisser le seuil fuzzy matching

❌ **Rejeté** : Augmente artificiellement le taux d'ancrage au prix de faux positifs. Casse l'invariant I3 "preuve défendable".

### 9.2 Forcer Vision à être verbatim via prompt

❌ **Rejeté** : Test A/B prouve que GPT-4o ne respecte pas les instructions "verbatim only". Gain marginal (+2.2 pts).

### 9.3 Utiliser un modèle plus discipliné

❌ **Rejeté** : Le problème est structural (mismatch de représentation), pas un problème de compliance du modèle.

---

## 10. Conclusion

> **Vision est excellente pour aider à comprendre et naviguer, mais inapte (par nature) à produire des unités de connaissance ancrables.**
>
> **La connaissance doit rester textuelle et extractive. Vision devient une couche descriptive séparée.**

---

## Glossaire

| Terme | Définition |
|-------|------------|
| **Knowledge Unit** | Assertion extraite textuellement, transportable, ancrable à un DocItem |
| **Evidence-First** | Principe : toute assertion doit avoir une preuve localisable |
| **VisionObservation** | Description visuelle non-ancrable, pour navigation/UX uniquement |
| **Anchor Rate** | % d'InformationMVP résolues en Information avec ancre DocItem |

---

## Références

- `doc/ongoing/DIAGNOSTIC_ROOT_CAUSE_FOUND.md` : Diagnostic initial langue
- `doc/ongoing/SPEC_VISION_ANCHOR_FIX_2026-01-26.md` : Fix prompt v2.0/v3.0
- `src/knowbase/extraction_v2/vision/semantic_reader.py` : Implémentation Vision
- `src/knowbase/stratified/models/assertion_v1.py` : Modèles assertions

---

*ADR créé le 2026-01-26*
*Renforcé avec les recommandations ChatGPT (clarifications, invariants, définitions)*
