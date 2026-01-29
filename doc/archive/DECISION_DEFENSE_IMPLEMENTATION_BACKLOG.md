# Decision Defense - Checklist d'Implémentation et Backlog

**Date:** 2026-01-19
**Ref:** ADR-001 (ADR_DECISION_DEFENSE_ARCHITECTURE.md)
**Branche:** feat/decision-defense-v1

---

## 0. Préambule : Ce Document N'est Pas une Liste de Features

Ce document décrit la **transformation architecturale** d'OSMOSIS vers le paradigme Decision Defense.

Ce n'est pas :
- Une liste de "nice to have"
- Un ajout de fonctionnalités
- Une amélioration incrémentale

C'est :
- Un **shift de paradigme** (Assertion-Centric → Proof Obligation)
- Une **refondation** du contrat produit
- Un **changement incompatible** avec certaines parties existantes

> **Principe directeur : Le code existant qui viole les règles R1-R5 de l'ADR doit être refactoré ou supprimé, pas contourné.**

---

## 1. Inventaire de l'Existant

### 1.1 Composants ALIGNÉS avec Decision Defense ✅

Ces composants sont **compatibles** et seront **conservés/adaptés** :

| Composant | Fichier | Alignement | Action |
|-----------|---------|------------|--------|
| **DocItem Model** | `src/knowbase/structural/models.py` | Types d'items structurés (TEXT, TABLE, etc.) | ✅ CONSERVER - Base pour Evidence |
| **Neo4j Facts Storage** | `src/knowbase/common/clients/neo4j_client.py` | Stockage des Fact nodes | ✅ CONSERVER - Adapter pour Claims |
| **Graph-Guided Search** | `src/knowbase/api/services/graph_guided_search.py` | Distinction SEMANTIC vs NAVIGATION | ✅ CONSERVER - Règle R2 respectée |
| **SourceRef Schema** | `src/knowbase/api/schemas/instrumented.py:112-141` | Localisation précise (page, bbox, excerpt) | ✅ CONSERVER - Base pour Evidence |
| **Evidence Bundles** | `src/knowbase/relations/evidence_bundle_*.py` | Regroupement d'evidence | ✅ ADAPTER - Vers Decision Package |

### 1.2 Composants en CONFLIT avec Decision Defense ⚠️

Ces composants violent explicitement les règles de l'ADR et doivent être **refactorés** :

| Composant | Fichier | Conflit | Action |
|-----------|---------|---------|--------|
| **Assertion Status "INFERRED"** | `src/knowbase/api/schemas/instrumented.py:22` | Viole R1 (pas de preuve = pas de support) | ⚠️ DEPRECATE - Remplacer par PARTIALLY_SUPPORTED |
| **LLM Assertion Generation** | `src/knowbase/api/services/assertion_generator.py` | LLM génère des conclusions | ⚠️ REFACTOR - LLM classify seulement |
| **InferenceEngine** | `src/knowbase/semantic/inference.py` | Inférence sémantique | ⚠️ DEPRECATE - Viole R1 |
| **TruthContract** | `src/knowbase/api/schemas/instrumented.py:245-259` | Mélange FACT/INFERRED | ⚠️ REPLACE - Par Coverage Report |

### 1.3 Composants ABSENTS à Construire 🆕

Ces composants n'existent pas et doivent être **créés** :

| Composant | Description | Priorité |
|-----------|-------------|----------|
| **Question Type Classifier** | Détection upgrade/feature/limitation/etc. | P0 - Critique |
| **Claim Template Registry** | Templates de claims par type de question | P0 - Critique |
| **Evidence Type Classifier** | Classification requirement/procedure/limitation/etc. | P0 - Critique |
| **Gap Qualification Engine** | Qualification NO_EXPLICIT_ASSERTION/MECHANISM_ONLY/etc. | P0 - Critique |
| **Decision Package Builder** | Orchestration et assemblage du package | P1 - Core |
| **Decision Status Derivation** | Calcul déterministe SUPPORTED/PARTIAL/NOT | P1 - Core |
| **Decision Package Schema** | Modèle Pydantic complet | P1 - Core |
| **Decision Board UI** | Interface de visualisation | P2 - UX |
| **Decision Package Persistence** | Stockage Neo4j des packages | P3 - Audit |

---

## 2. Règles d'Implémentation (Non Négociables)

### 2.1 Règles de l'ADR à Implémenter

| Règle | Énoncé | Implication Code |
|-------|--------|------------------|
| **R1** | Pas de preuve = Pas de support | `if not evidence: status = NOT_SUPPORTED` |
| **R2** | Navigation suggère, Evidence prouve | CO_OCCURS exclus de `evidence_search()` |
| **R3** | PARTIAL est un statut valide | Ne jamais forcer SUPPORTED sans preuve complète |
| **R4** | Statut dérivé, jamais décidé par LLM | `derive_status()` = pure function, no LLM call |
| **R5** | PARTIAL ≠ sécurité partielle | UI doit afficher warning explicite |

### 2.2 Invariants Système

```python
# INVARIANT 1: Tout gap DOIT avoir une preuve documentaire d'absence
class GapReason(BaseModel):
    type: GapType  # NO_EXPLICIT_ASSERTION, MECHANISM_ONLY, etc.
    description: str
    documentary_evidence: DocumentaryEvidence  # OBLIGATOIRE

# INVARIANT 2: Statut dérivé de façon déterministe
def derive_status(claims: List[Claim]) -> DecisionStatus:
    if all(c.status == SUPPORTED for c in claims):
        return SUPPORTED
    if any(c.status == SUPPORTED for c in claims):
        return PARTIALLY_SUPPORTED
    return NOT_SUPPORTED
# ⚠️ JAMAIS de LLM dans cette fonction

# INVARIANT 3: Le LLM ne décide JAMAIS du statut
# Autorisé: classify_question_type(), extract_parameters(), classify_evidence_type()
# Interdit: decide_status(), generate_conclusion(), fill_gap()
```

---

## 3. Phases d'Implémentation

### Phase 0 : Fondations (Semaine 1-2)

**Objectif :** Établir les structures de base sans casser l'existant.

| Tâche | Description | Fichier(s) | Dépendances |
|-------|-------------|------------|-------------|
| **0.1** | Créer module `src/knowbase/decision/` | Nouveau dossier | - |
| **0.2** | Créer `DecisionType` enum | `decision/types.py` | - |
| **0.3** | Créer `ClaimStatus` enum | `decision/types.py` | - |
| **0.4** | Créer `GapType` enum | `decision/types.py` | - |
| **0.5** | Créer `EvidenceType` enum | `decision/types.py` | - |
| **0.6** | Créer schéma `Claim` Pydantic | `decision/schemas.py` | 0.3, 0.5 |
| **0.7** | Créer schéma `GapReason` Pydantic | `decision/schemas.py` | 0.4 |
| **0.8** | Créer schéma `Evidence` Pydantic | `decision/schemas.py` | 0.5 |
| **0.9** | Créer schéma `DecisionPackage` Pydantic | `decision/schemas.py` | 0.2, 0.6, 0.7 |

**Checklist Phase 0 :**
- [ ] Module decision/ créé
- [ ] Types enum définis et testés
- [ ] Schemas Pydantic validés
- [ ] Tests unitaires passent

---

### Phase 1 : Question → Claims (Semaine 3-4)

**Objectif :** Transformer une question en obligations de preuve.

| Tâche | Description | Fichier(s) | Dépendances |
|-------|-------------|------------|-------------|
| **1.1** | Implémenter Question Type Classifier | `decision/question_classifier.py` | Phase 0 |
| **1.2** | Créer Claim Templates Registry | `decision/claim_templates.py` | 0.6 |
| **1.3** | Implémenter Claim Generator | `decision/claim_generator.py` | 1.1, 1.2 |
| **1.4** | Parser de paramètres (source_version, target_version, etc.) | `decision/param_parser.py` | 1.1 |
| **1.5** | Tests E2E question → claims | `tests/decision/test_claim_generation.py` | 1.1-1.4 |

**Templates de Claims par Type :**

```python
CLAIM_TEMPLATES = {
    "upgrade": [
        "Le chemin {source} → {target} est officiellement supporté",
        "Les prérequis sont documentés",
        "L'outil requis est identifié",
        "Aucune incompatibilité bloquante n'est documentée"
    ],
    "feature": [
        "La fonctionnalité {feature} est documentée dans SAP S/4HANA",
        "Les capacités et limites de {feature} sont explicitement décrites"
    ],
    "prerequisite": [
        "Les prérequis pour {component} sont explicitement listés",
        "Les dépendances techniques de {component} sont documentées"
    ],
    # ... autres types
}
```

**Checklist Phase 1 :**
- [ ] Classifier détecte correctement les 9 types de questions
- [ ] Claims générés correspondent aux templates
- [ ] Paramètres extraits correctement
- [ ] Tests sur 20+ questions diversifiées

---

### Phase 2 : Claims → Evidence (Semaine 5-6)

**Objectif :** Rechercher et classifier les preuves pour chaque claim.

| Tâche | Description | Fichier(s) | Dépendances |
|-------|-------------|------------|-------------|
| **2.1** | Implémenter Evidence Searcher | `decision/evidence_searcher.py` | Phase 1 |
| **2.2** | Intégrer recherche vectorielle existante | Adapter `search.py` | 2.1 |
| **2.3** | Implémenter Evidence Type Classifier | `decision/evidence_classifier.py` | 0.5 |
| **2.4** | Filtrer relations CO_OCCURS (R2) | `decision/evidence_searcher.py` | 2.1 |
| **2.5** | Scorer pertinence claim ↔ evidence | `decision/relevance_scorer.py` | 2.1, 2.3 |
| **2.6** | Tests E2E claims → evidence | `tests/decision/test_evidence_search.py` | 2.1-2.5 |

**Types d'Evidence à Classifier :**

```python
class EvidenceType(str, Enum):
    REQUIREMENT = "requirement"      # Exigence explicite
    PROCEDURE = "procedure"          # Étape documentée
    LIMITATION = "limitation"        # Restriction documentée
    SCOPE = "scope"                  # Périmètre d'application
    DEFINITION = "definition"        # Définition d'un concept
    MECHANISM = "mechanism"          # Mécanisme de vérification
```

**Checklist Phase 2 :**
- [ ] Evidence searcher retourne des résultats pertinents
- [ ] CO_OCCURS exclus de la recherche d'evidence
- [ ] Evidence classifier atteint 80%+ accuracy
- [ ] Scoring relevance fonctionne

---

### Phase 3 : Evidence → Gap Qualification (Semaine 7-8)

**Objectif :** Qualifier les gaps avec preuve documentaire d'absence.

| Tâche | Description | Fichier(s) | Dépendances |
|-------|-------------|------------|-------------|
| **3.1** | Implémenter Gap Qualifier | `decision/gap_qualifier.py` | Phase 2 |
| **3.2** | Logique "Proof of Absence" | `decision/gap_qualifier.py` | 3.1 |
| **3.3** | Extraire "found_instead" des documents | `decision/gap_qualifier.py` | 3.1 |
| **3.4** | Valider structure GapReason obligatoire | `decision/gap_validator.py` | 0.7 |
| **3.5** | Tests E2E gaps qualifiés | `tests/decision/test_gap_qualification.py` | 3.1-3.4 |

**Invariant Gap Evidence :**

```python
# JAMAIS de gap sans preuve documentaire
def qualify_gap(claim: Claim, context: SearchContext) -> GapReason:
    # Chercher ce qui a été trouvé À LA PLACE de l'assertion attendue
    found_instead = search_related_content(claim)

    if not found_instead:
        raise SystemError("DÉFAILLANCE: Gap sans contexte documentaire")

    return GapReason(
        type=infer_gap_type(found_instead),
        description=generate_description(claim, found_instead),
        documentary_evidence=DocumentaryEvidence(
            found_instead=found_instead.summary,
            source=found_instead.source,
            excerpt=found_instead.excerpt,
            demonstrates_absence=f"Aucune assertion '{claim.expected}' n'est présente"
        )
    )
```

**Checklist Phase 3 :**
- [ ] 100% des gaps ont une preuve documentaire
- [ ] 0 gaps génériques ("Not found")
- [ ] Types de gaps correctement inférés
- [ ] Tests sur claims délibérément non-prouvables

---

### Phase 4 : Decision Package Assembly (Semaine 9-10)

**Objectif :** Assembler le Decision Package complet et dériver le statut.

| Tâche | Description | Fichier(s) | Dépendances |
|-------|-------------|------------|-------------|
| **4.1** | Implémenter Decision Package Builder | `decision/package_builder.py` | Phases 1-3 |
| **4.2** | Implémenter `derive_status()` (pure function) | `decision/status_derivation.py` | 0.3 |
| **4.3** | Calculer coverage metrics | `decision/metrics.py` | 4.1 |
| **4.4** | Générer summary textuel (non-engageant) | `decision/summary_generator.py` | 4.1 |
| **4.5** | Endpoint API `/decision/ask` | `api/routers/decision.py` | 4.1-4.4 |
| **4.6** | Tests E2E complets | `tests/decision/test_package_e2e.py` | 4.1-4.5 |

**Checklist Phase 4 :**
- [ ] Decision Package complet généré
- [ ] Statut dérivé sans LLM
- [ ] Coverage metrics correctes
- [ ] API endpoint fonctionnel
- [ ] Tests E2E sur 30+ questions

---

### Phase 5 : UI Decision Board (Semaine 11-12)

**Objectif :** Interface utilisateur pour visualiser et explorer les Decision Packages.

| Tâche | Description | Fichier(s) | Dépendances |
|-------|-------------|------------|-------------|
| **5.1** | Composant ClaimCard | `frontend/src/components/decision/ClaimCard.tsx` | Phase 4 |
| **5.2** | Composant EvidencePanel | `frontend/src/components/decision/EvidencePanel.tsx` | 5.1 |
| **5.3** | Composant GapExplanation | `frontend/src/components/decision/GapExplanation.tsx` | 5.1 |
| **5.4** | Page Decision Board | `frontend/src/app/decision/page.tsx` | 5.1-5.3 |
| **5.5** | Warning UI pour PARTIAL (R5) | `frontend/src/components/decision/PartialWarning.tsx` | 5.4 |
| **5.6** | Export PDF/DOCX | `api/services/decision_export.py` | 4.1 |

**Checklist Phase 5 :**
- [ ] Claims affichés avec statut visuel
- [ ] Evidence navigable (clic → document)
- [ ] Gaps expliqués avec preuve documentaire
- [ ] Warning PARTIAL visible
- [ ] Export fonctionnel

---

### Phase 6 : Deprecation de l'Ancien Système (Semaine 13-14)

**Objectif :** Supprimer le code en conflit avec Decision Defense.

| Tâche | Description | Fichier(s) | Action |
|-------|-------------|------------|--------|
| **6.1** | Retirer status INFERRED | `api/schemas/instrumented.py` | REMOVE |
| **6.2** | Retirer TruthContract | `api/schemas/instrumented.py` | REMOVE |
| **6.3** | Deprecate InferenceEngine | `semantic/inference.py` | DEPRECATE |
| **6.4** | Refactor assertion_generator | `api/services/assertion_generator.py` | REFACTOR |
| **6.5** | Migrer endpoint `/search` vers Decision | `api/routers/search.py` | MIGRATE |
| **6.6** | Documentation migration | `doc/migration/` | CREATE |

**Checklist Phase 6 :**
- [ ] Aucune référence à INFERRED
- [ ] InferenceEngine marqué @deprecated
- [ ] /search utilise Decision Defense
- [ ] Guide migration documenté

---

## 4. Backlog Priorisé

### P0 - Bloquant (Must Have)

| ID | Tâche | Phase | Effort |
|----|-------|-------|--------|
| DD-001 | Module decision/ avec types | 0 | S |
| DD-002 | Schemas Decision Package | 0 | M |
| DD-003 | Question Type Classifier | 1 | M |
| DD-004 | Claim Templates Registry | 1 | S |
| DD-005 | Claim Generator | 1 | M |
| DD-006 | Evidence Searcher | 2 | L |
| DD-007 | Evidence Type Classifier | 2 | M |
| DD-008 | Gap Qualifier | 3 | L |
| DD-009 | Package Builder | 4 | L |
| DD-010 | API Endpoint /decision/ask | 4 | M |

### P1 - Important (Should Have)

| ID | Tâche | Phase | Effort |
|----|-------|-------|--------|
| DD-011 | Summary Generator (non-engageant) | 4 | M |
| DD-012 | Coverage Metrics | 4 | S |
| DD-013 | Relevance Scorer | 2 | M |
| DD-014 | Gap Validator | 3 | S |

### P2 - Nice to Have

| ID | Tâche | Phase | Effort |
|----|-------|-------|--------|
| DD-015 | Decision Board UI | 5 | XL |
| DD-016 | Export PDF/DOCX | 5 | L |
| DD-017 | Partial Warning Component | 5 | S |

### P3 - Cleanup

| ID | Tâche | Phase | Effort |
|----|-------|-------|--------|
| DD-018 | Remove INFERRED status | 6 | S |
| DD-019 | Deprecate InferenceEngine | 6 | M |
| DD-020 | Migrate /search endpoint | 6 | L |

---

## 5. Métriques de Succès

### 5.1 Métriques Techniques

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Claim Coverage | ≥ 90% | % claims avec evidence |
| Gap Qualification Rate | 100% | % gaps avec preuve documentaire |
| Generic Gap Rate | 0% | % gaps "Not found" |
| Determinism | 100% | Même input → même output |

### 5.2 Métriques Produit

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Question Types Supported | 9 | upgrade, conversion, feature, architecture, limitation, integration, compatibility, prerequisite, compliance |
| Evidence Types Classified | 6 | requirement, procedure, limitation, scope, definition, mechanism |
| Gap Types Supported | 4 | NO_EXPLICIT_ASSERTION, MECHANISM_ONLY, SCOPE_UNSPECIFIED, CONTRADICTION |

### 5.3 Critères d'Échec

Le système **échoue** si :
- [ ] Un claim est marqué SUPPORTED sans evidence
- [ ] Un gap n'a pas de preuve documentaire
- [ ] Le statut varie entre deux exécutions identiques
- [ ] Le LLM décide du statut final

---

## 6. Risques et Mitigations

| Risque | Impact | Mitigation |
|--------|--------|------------|
| Question mal classifiée | Claims inadaptés | Fallback "generic" + human review |
| Evidence non pertinente | Faux positifs | Threshold de relevance strict |
| Gap sans contexte documentaire | DÉFAILLANCE | Obligation structurelle dans GapReason |
| Confusion utilisateur PARTIAL | Mauvaise décision | Warning UI explicite |

---

## 7. Notes de Migration

### 7.1 Ce qui Change pour les Utilisateurs

| Avant | Après |
|-------|-------|
| Score de confiance (%) | Decision Status + Coverage |
| Assertions FACT/INFERRED | Claims SUPPORTED/PARTIAL/NOT |
| Réponse textuelle | Decision Package structuré |
| "Le système pense que..." | "Les documents affirment que..." |

### 7.2 Ce qui Change pour les Développeurs

| Avant | Après |
|-------|-------|
| `InstrumentedAnswer` | `DecisionPackage` |
| `TruthContract` | `CoverageReport` |
| `AssertionStatus.INFERRED` | Supprimé |
| `generate_assertions()` | `generate_claims()` |
| Statut calculé par LLM | `derive_status()` pure function |

---

## 8. Références

- **ADR-001**: `doc/ongoing/ADR_DECISION_DEFENSE_ARCHITECTURE.md`
- **POC Results**: `data/decision_package_poc_results.json`
- **Existing Schemas**: `src/knowbase/api/schemas/instrumented.py`
- **Graph-Guided Search**: `src/knowbase/api/services/graph_guided_search.py`

---

*Document créé le 2026-01-19 - Transformation vers Decision Defense Architecture*
