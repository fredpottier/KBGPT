# Backlog - ADR Relations Discursivement Déterminées

**Dernière mise à jour**: 2026-01-21
**ADR de référence**: `doc/ongoing/ADR_DISCURSIVE_RELATIONS.md`
**ADR complémentaire**: `doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md` ✅ APPROVED
**ADR extension**: `doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md` ✅ APPROVED – V1
**Statut global**: ADR validés — Prêt pour implémentation Phase A

---

## Vue d'ensemble

Ce document trace l'avancement de l'implémentation de l'ADR "Relations Discursivement Déterminées". L'objectif est de permettre l'extraction de relations reconstructibles par un lecteur rigoureux sans ajout de connaissance externe.

### Principe architectural clé (ADR Scope vs Assertion)

> **Le graphe d'assertions doit rester SPARSE (5-15% des relations potentielles).**
> **La navigation doit rester DENSE (90%+ de couverture).**
> **Ces deux couches ne doivent jamais être confondues.**

| Couche | Ce qu'elle exprime | Densité | Traversable |
|--------|-------------------|---------|-------------|
| **Scope Layer** | Ce que le document couvre | Dense | Non (navigation) |
| **Assertion Layer** | Ce que le document affirme | Sparse | Oui (raisonnement) |

L'objectif n'est **PAS** d'augmenter le taux de capture des assertions, mais de :
1. Garder les assertions fiables et défendables
2. Enrichir la Scope Layer pour la navigation
3. Exploiter le scope via le mode Anchored

### Légende

- ✅ **Fait** - Implémenté et testé
- 🔄 **En cours** - Travail commencé
- ⏳ **À faire** - Non commencé
- ⚠️ **Bloqué** - Dépendance non résolue
- 🔒 **Bloqué par ADR** - Attend validation ADR Scope vs Assertion

### Dépendance architecturale

> **L'ADR Scope vs Assertion (BLOCKING) doit être validé avant :**
> - Attribution DefensibilityTier
> - Stratégie d'escalade STRICT → EXTENDED → Anchored
> - Runtime traversal allowed_tiers
> - Promotion rules MIXED/DISCURSIVE

---

## 1. Types et Modèles de données

### 1.1 Enums de base

| Élément | Statut | Fichier | Notes |
|---------|--------|---------|-------|
| `AssertionKind` (EXPLICIT, DISCURSIVE) | ✅ | `types.py` | |
| `DiscursiveBasis` (ALTERNATIVE, DEFAULT, EXCEPTION, SCOPE, COREF, ENUMERATION) | ✅ | `types.py` | |
| `DiscursiveAbstainReason` | ✅ | `types.py` | Ajouté NO_BRIDGE_EVIDENCE |
| `SemanticGrade` (EXPLICIT, DISCURSIVE, MIXED) | ✅ | `types.py` | |
| `DefensibilityTier` (STRICT, EXTENDED, EXPERIMENTAL) | ✅ | `types.py` | |

### 1.2 Champs sur RawAssertion

| Champ | Statut | Notes |
|-------|--------|-------|
| `assertion_kind: AssertionKind` | ✅ | Default = EXPLICIT |
| `discursive_basis: List[DiscursiveBasis]` | ✅ | |
| `abstain_reason: Optional[DiscursiveAbstainReason]` | ✅ | Pour traçabilité ABSTAIN |

### 1.3 Champs sur CanonicalRelation

| Champ | Statut | Notes |
|-------|--------|-------|
| `explicit_support_count: int` | ⏳ | Compteur RawAssertion EXPLICIT |
| `discursive_support_count: int` | ⏳ | Compteur RawAssertion DISCURSIVE |

### 1.4 Champs sur SemanticRelation

| Champ | Statut | Notes |
|-------|--------|-------|
| `semantic_grade: SemanticGrade` | ⏳ | Calculé à la promotion |
| `defensibility_tier: DefensibilityTier` | ⏳ | Calculé selon matrice basis→tier |

---

## 2. Extraction des Patterns Discursifs

### 2.1 Pattern Extractors

| Pattern | Statut | Fichier | Marqueurs |
|---------|--------|---------|-----------|
| **ALTERNATIVE** | ✅ | `discursive_pattern_extractor.py` | "or", "either...or", "ou" |
| **DEFAULT** | ✅ | `discursive_pattern_extractor.py` | "by default", "par défaut" |
| **EXCEPTION** | ✅ | `discursive_pattern_extractor.py` | "unless", "except", "sauf si" |
| **SCOPE** | ✅ | `scope_candidate_miner.py` | Co-présence dans SectionContext |
| **COREF** | ⚠️ | Pass 0.5 existe | Intégration à valider |
| **ENUMERATION** | ⏳ | - | Listes explicites, chevauchement SCOPE |

### 2.2 SCOPE Mining (ADR dédié)

| Élément | Statut | Fichier | Notes |
|---------|--------|---------|-------|
| `ScopeCandidateMiner` | ✅ | `scope_candidate_miner.py` | Mine les paires de concepts |
| `ScopeVerifier` (LLM) | ✅ | `scope_verifier.py` | Vérifie marqueurs explicites |
| Bridge Detection | ✅ | `scope_candidate_miner.py` | INV-SCOPE-07 |
| `EvidenceSpanRole.BRIDGE` | ✅ | `types.py` | |
| `EvidenceBundle.has_bridge` | ✅ | `types.py` | |
| Garde-fou NO_BRIDGE | ✅ | `scope_verifier.py` | ABSTAIN déterministe |
| Whitelist SCOPE V1 (APPLIES_TO, REQUIRES) | ✅ | `scope_verifier.py` | |
| Fix `canonical_id` vs `concept_id` | ✅ | `scope_candidate_miner.py` | 2026-01-21 |

**ADR SCOPE**: `doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md`

### 2.3 Intégration Pipeline Pass 2

| Élément | Statut | Fichier | Notes |
|---------|--------|---------|-------|
| Appel SCOPE mining dans Pass 2 | ✅ | `pass2_orchestrator.py` | Phase ENRICH_RELATIONS |
| Persistance RawAssertion SCOPE | ✅ | `raw_assertion_writer.py` | Via `candidate_to_raw_assertion()` |
| Discursive Pattern Extractor dans Pass 2 | ⏳ | - | ALTERNATIVE, DEFAULT, EXCEPTION |

---

## 3. Contraintes et Garde-fous

### 3.1 Contrainte C3bis - ExtractionMethod

| Règle | Statut | Notes |
|-------|--------|-------|
| DISCURSIVE → PATTERN ou HYBRID uniquement | ⏳ | Validation à implémenter |
| Interdit: DISCURSIVE + LLM seul | ⏳ | |

### 3.2 Contrainte C4 - Whitelist RelationType

| RelationType | Autorisé DISCURSIVE | Condition | Statut |
|--------------|---------------------|-----------|--------|
| `ALTERNATIVE_TO` | ✅ | Toujours | ⏳ Validation |
| `APPLIES_TO` | ✅ | Toujours | ✅ SCOPE |
| `REQUIRES` | ✅ | Si obligation explicite | ✅ SCOPE |
| `REPLACES` | ✅ | Si temporalité explicite | ⏳ |
| `DEPRECATES` | ✅ | Si temporalité explicite | ⏳ |
| `CAUSES` | ❌ | Interdit (causalité) | ⏳ Validation |
| `PREVENTS` | ❌ | Interdit (causalité) | ⏳ Validation |
| `ENABLES` | ❌ | Interdit | ⏳ Validation |
| `DEFINES` | ❌ | Interdit (ontologique) | ⏳ Validation |

### 3.3 Validation pré-écriture

| Validation | Statut | Notes |
|------------|--------|-------|
| `validate_before_write()` | ⏳ | Vérifie C3bis + C4 + basis |
| Rejet si whitelist violation | ⏳ | |

---

## 4. Promotion (Ingestion-time)

### 4.1 SupportStrength

| Métrique | Statut | Notes |
|----------|--------|-------|
| `support_count` | ⏳ | Nombre total RawAssertion |
| `explicit_count` | ⏳ | Nombre EXPLICIT |
| `discursive_count` | ⏳ | Nombre DISCURSIVE |
| `doc_coverage` | ⏳ | Documents distincts |
| `distinct_sections` | ⏳ | SectionContext distincts |
| `bundle_diversity` | ⏳ | Score 0-1 (sections/3) |

### 4.2 Seuils de promotion

| Type | min_support | min_sections | Statut |
|------|-------------|--------------|--------|
| EXPLICIT seul | 1 | - | ⏳ |
| DISCURSIVE seul | 2 | 2 | ⏳ |
| MIXED | 1 EXPLICIT + 1 DISCURSIVE | - | ⏳ |

### 4.3 Attribution DefensibilityTier

| SemanticGrade | Tier | Condition | Statut |
|---------------|------|-----------|--------|
| EXPLICIT | STRICT | Toujours | 🔒 Bloqué ADR |
| MIXED | STRICT | Toujours | 🔒 Bloqué ADR |
| DISCURSIVE | STRICT | Bases fortes (ALTERNATIVE, DEFAULT, EXCEPTION) | 🔒 Bloqué ADR |
| DISCURSIVE | EXTENDED | Bases faibles ou bundle insuffisant | 🔒 Bloqué ADR |

### 4.4 Matrice Basis → Tier (DISCURSIVE)

| DiscursiveBasis | Conditions STRICT | Sinon |
|-----------------|-------------------|-------|
| ALTERNATIVE | Marqueur "or" + options identifiées | EXTENDED |
| DEFAULT | Marqueur "by default" explicite | EXTENDED |
| EXCEPTION | Marqueur "unless/except" explicite | EXTENDED |
| SCOPE | ≥ 2 spans + anchor_type audité | EXTENDED |
| COREF | ≥ 2 spans + coref_path documenté | EXTENDED |
| ENUMERATION | Liste complète dans bundle | EXTENDED |

**Statut**: ⏳ À implémenter dans `tier_attribution.py`

---

## 5. Runtime (Traversal) — 🔒 Bloqué par ADR Scope vs Assertion

### 5.1 Paramètre de filtrage

| Élément | Statut | Notes |
|---------|--------|-------|
| `allowed_tiers: Set[DefensibilityTier]` | 🔒 | Paramètre mode Reasoned |
| Défaut = `{STRICT}` | 🔒 | Production |
| Extended = `{STRICT, EXTENDED}` | 🔒 | Exploration |

### 5.2 Stratégie d'escalade

| Étape | Statut | Notes |
|-------|--------|-------|
| 1. STRICT | 🔒 | Défaut |
| 2. EXTENDED (si vide) | 🔒 | Optionnel |
| 3. Anchored fallback | 🔒 | Dépend de Scope Layer |

### 5.3 Anti-contamination

| Règle | Statut | Notes |
|-------|--------|-------|
| Pas de transitivité EXPLICIT→DISCURSIVE→? | 🔒 | |
| Traçabilité semantic_grade sur chaque edge | 🔒 | |

---

## 6. Tests et Validation

### 6.1 Tests de régression Type 2

| Cas | Attendu | Statut |
|-----|---------|--------|
| "SAP is better than Oracle" | ABSTAIN (opinion) | ⏳ |
| "HANA enables real-time analytics" | ABSTAIN (ENABLES interdit) | ⏳ |
| "If you use BW, you need HANA" | ABSTAIN (causal implicite) | ⏳ |
| "Use HANA or Oracle" | ALTERNATIVE_TO | ⏳ |
| "S/4HANA uses HANA by default" | USES + DEFAULT | ⏳ |
| "All modules require HANA, unless legacy" | REQUIRES + EXCEPTION | ⏳ |

### 6.2 KPI Sentinel

| KPI | Seuil | Statut mesure |
|-----|-------|---------------|
| FP Type 2 | = 0% | ⏳ |
| Accept Type 1 | ≥ 80% | ⏳ |
| Abstain motivé | 100% | ✅ (abstain_reason) |

### 6.3 Tests existants

| Test | Fichier | Statut |
|------|---------|--------|
| SCOPE candidate miner | `tests/relations/test_scope_candidate_miner.py` | ✅ |
| SCOPE verifier | `tests/relations/test_scope_verifier.py` | ✅ |
| Tier attribution | `tests/relations/test_tier_attribution.py` | ✅ |
| Discursive pattern extractor | `tests/relations/test_discursive_pattern_extractor.py` | ✅ |
| Tests régression Type 2 | - | ⏳ |

---

## 7. Scope Layer (nouveau - ADR Scope vs Assertion)

### 7.1 Formalisation du schéma

| Élément | Statut | Notes |
|---------|--------|-------|
| `Document.topic` (sujet principal) | ⏳ | Extraction du titre/metadata |
| `SectionContext.scope_description` | ⏳ | De quoi parle cette section |
| `DocItem.mentioned_concepts` | ⏳ | Liste sans relation (scope) |

### 7.2 Exploitation dans Anchored

| Élément | Statut | Notes |
|---------|--------|-------|
| Filtrage par `doc.topic` avant recherche | ⏳ | |
| Filtrage par `section.scope` | ⏳ | |
| Boost scoring par pertinence scope | ⏳ | |

### 7.3 Documentation

| Élément | Statut | Notes |
|---------|--------|-------|
| Guide "Quand assertion vs scope" | ⏳ | Pour développeurs |
| Tests de validation séparation | ⏳ | |

---

## 8. Prochaines étapes (priorité révisée)

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 0 - FONDATION (BLOQUANTE)                                │
│  ADR Scope vs Assertion = VALIDÉ                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE A - SCOPE LAYER (Haute priorité)                         │
│  Peut avancer immédiatement                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE B/C/D - Assertion + Promotion + Runtime                  │
│  Débloquées une fois Scope Layer opérationnelle                 │
└─────────────────────────────────────────────────────────────────┘
```

### Phase 0 - Fondation architecturale (✅ COMPLÈTE)

- [x] ADR Scope vs Assertion - ✅ APPROVED (BLOCKING)
- [x] ADR NormativeRule & SpecFact - ✅ APPROVED – V1
- [x] Définition des invariants INV-SEP-01 à INV-SEP-04
- [x] Définition des invariants INV-NORM-01 à INV-NORM-04 + INV-AGN-01
- [x] Backlog mis à jour avec dépendances

### Phase A - Scope Layer (Haute priorité - DÉBLOQUÉE)

> **Objectif** : Rendre OSMOSIS "utile" très vite via navigation dense + réponses citables
> **KPI** : L'utilisateur trouve l'info sans que le graphe soit dense

#### A.1 — Formaliser le schéma Scope en Neo4j

| Champ | Noeud | Description | Statut |
|-------|-------|-------------|--------|
| `topic` | Document | Sujet principal du document | ⏳ |
| `scope_description` | SectionContext | De quoi parle cette section | ⏳ |
| `mentioned_concepts` | DocItem | Concepts mentionnés (liste, pas relations) | ⏳ |

**But** : Pouvoir faire un filtrage "intelligent" avant même la recherche vectorielle.

#### A.2 — Extraire `doc.topic` + "scope setters" au Pass 1

| Élément | Source | Statut |
|---------|--------|--------|
| `doc.topic` | Titre + métadonnées + fréquence concepts pivot | ⏳ |
| Scope setters | Titres de sections + captions + entêtes listes/tableaux | ⏳ |

**But** : Préparer le terrain pour retrouver "TLS 1.2" ou "pression pneus" sans inventer de relation.

#### A.3 — Brancher le Scope dans le mode Anchored

| Fonctionnalité | Description | Statut |
|----------------|-------------|--------|
| Filtre par `doc.topic` | Restreindre la recherche au sujet | ⏳ |
| Boost par section | Keywords "requirements", "security", "configuration" | ⏳ |
| Renvoi chunks + citations | Résultats traçables | ⏳ |

#### A.4 — Tests de la séparation Scope/Assertion

| Test | Statut |
|------|--------|
| Scope ne crée pas d'assertion | ⏳ |
| Assertion a toujours une preuve locale | ⏳ |
| Anchored utilise le scope pour filtrer | ⏳ |

#### A.5 — NormativeRule & SpecFact (Assertions Non-Relationnelles)

> **ADR**: `doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md` ✅ APPROVED V1
> **Contexte**: Capturer les informations "high-value" qui ne sont pas des relations A→B

| Type | Description | Statut |
|------|-------------|--------|
| **NormativeRule** | Règles avec marqueurs modaux (must/shall/required) | ⏳ |
| **SpecFact** | Valeurs structurées (tableaux, listes clé-valeur) | ⏳ |

**NormativeRule — Détection par patterns** :

| Élément | Description | Statut |
|---------|-------------|--------|
| Pattern Matcher | Détecte marqueurs modaux EN/FR | ⏳ |
| Parser sujet/contrainte | Extrait subject_text + constraint | ⏳ |
| Enums `NormativeModality` | MUST, SHOULD, MAY, MUST_NOT, SHOULD_NOT | ⏳ |
| Enums `ConstraintType` | EQUALS, MIN, MAX, RANGE, ENUM, PATTERN | ⏳ |
| `NormativePatternExtractor` | Implémentation dans `relations/` | ⏳ |

**Marqueurs détectés** :
- EN: must, shall, are to be, is required, required, mandatory, should, recommended, may, optional
- FR: doit, doivent, obligatoire, requis, impératif, devrait, recommandé, peut, peuvent, optionnel

**SpecFact — Extraction structurelle** :

| Élément | Description | Statut |
|---------|-------------|--------|
| Structure Detector | Identifie TABLE, KEY_VALUE_LIST, BULLET_LIST | ⏳ |
| Table Parser | Extrait headers + cells | ⏳ |
| Key-Value Parser | Pattern `Label: Value` ou `Label = Value` | ⏳ |
| Enums `SpecType` | VALUE, MIN, MAX, DEFAULT, RECOMMENDED | ⏳ |
| Enums `StructureType` | TABLE, KEY_VALUE_LIST, BULLET_LIST, DEFINITION_LIST | ⏳ |
| `StructureParser` | Implémentation dans `relations/` | ⏳ |

**Invariants** :
- INV-NORM-01 : Preuve locale obligatoire
- INV-NORM-02 : Marqueur explicite requis pour NormativeRule
- INV-NORM-03 : Structure explicite requise pour SpecFact
- INV-NORM-04 : Pas de sujet inventé
- INV-AGN-01 : Domain-Agnostic Semantics (pas de prédicats métier)

### Phase B - Compléter l'extraction assertions (Moyenne priorité - DÉBLOQUÉE)

5. [ ] Intégrer `DiscursivePatternExtractor` dans Pass 2
6. [ ] Valider intégration COREF avec Pass 0.5
7. [ ] Implémenter `validate_before_write()` (C3bis + C4)
8. [ ] Implémenter `can_create_assertion()` (INV-SEP-01, INV-SEP-02)

### Phase C - Pipeline de promotion (Moyenne priorité - 🔒 ATTEND PHASE A)

9. [ ] Ajouter compteurs sur `CanonicalRelation`
10. [ ] Implémenter `SupportStrength` calcul
11. [ ] Implémenter attribution `DefensibilityTier` (matrice basis→tier)
12. [ ] Ajouter `semantic_grade` et `defensibility_tier` sur `SemanticRelation`
13. [ ] Implémenter seuils de promotion différenciés

### Phase D - Runtime Reasoned (Moyenne priorité - 🔒 ATTEND PHASE A+C)

14. [ ] Ajouter paramètre `allowed_tiers` au mode Reasoned
15. [ ] Implémenter filtrage traversée par tier
16. [ ] Implémenter stratégie d'escalade STRICT → EXTENDED → Anchored

### Phase E - Tests et validation (Continue en parallèle)

17. [ ] Créer suite de tests régression Type 2
18. [ ] Tests de validation séparation Scope/Assertion
19. [ ] Dashboard KPI Sentinel

---

## Évolutions futures (V1.x / V2) — Non-goals V1

> **Ces éléments sont hors-scope V1 mais doivent être tracés pour ne pas être oubliés.**

### V1.x — Extensions incrémentales

| Élément | Description | Priorité estimée |
|---------|-------------|------------------|
| **Multi-langues** | Ajouter marqueurs DE, IT, ES, PT, NL... | Haute |
| **Lexiques enrichis** | Expressions idiomatiques, variations régionales | Moyenne |
| **Patterns conditionnels** | Meilleure gestion "if/when/unless" avec conditions structurées | Moyenne |
| **Unités normalisées** | Parser automatique GB→bytes, minutes→seconds | Basse |

### V2 — Évolutions architecturales

| Élément | Description | Dépendances |
|---------|-------------|-------------|
| **Promotion complexe** | Scoring multi-critères, merge de règles similaires | V1 stabilisé |
| **Traversabilité conditionnelle** | Autoriser traversée Rules/Facts dans certains contextes | Évaluation usage V1 |
| **Conflits de règles** | Détection et résolution de contradictions normatives | Promotion complexe |
| **Temporal Rules** | Gestion des règles avec validité temporelle ("until 2025", "from v2.0") | V1.x conditionnels |
| **Inheritance Rules** | Règles héritées de sections parentes avec override | Scope Layer mature |

### V2+ — Explorations

| Élément | Description | Notes |
|---------|-------------|-------|
| **Rule reasoning** | Inférence simple sur règles (si A MUST X et B MUST Y...) | Risque Type 2 |
| **Compliance checker** | Vérification automatique conformité config vs règles | Dépend V2 |
| **Rule versioning** | Historique des évolutions de règles entre versions docs | Complexité élevée |

### Critères de passage V1 → V1.x

- [ ] V1 déployé et stable en production
- [ ] Métriques de précision validées (≥95% NormativeRule, ≥90% SpecFact)
- [ ] Feedback utilisateurs sur lacunes linguistiques
- [ ] Cas d'usage multi-domaines validés (pas juste SAP)

### Critères de passage V1.x → V2

- [ ] Couverture linguistique suffisante (≥5 langues)
- [ ] Volume de règles/facts significatif pour justifier promotion complexe
- [ ] Demande utilisateur pour traversabilité ou conflits
- [ ] Stabilité des invariants INV-NORM-* et INV-AGN-01 prouvée

---

## Historique des changements

| Date | Changement | Auteur |
|------|------------|--------|
| 2026-01-21 | Ajout section "Évolutions futures V1.x/V2" pour tracer les non-goals | Claude |
| 2026-01-21 | **VALIDATION** : ADR Scope vs Assertion APPROVED + NormativeRule APPROVED V1 | Claude |
| 2026-01-21 | ADR NormativeRule & SpecFact complété (review ChatGPT) + Phase A.5 | Claude |
| 2026-01-21 | ADR Scope vs Assertion - Recadrage architectural | Claude |
| 2026-01-21 | Ajout section Scope Layer au backlog | Claude |
| 2026-01-21 | Création du backlog | Claude |
| 2026-01-21 | Fix `canonical_id` SCOPE mining | Claude |
| 2026-01-20 | Bridge detection SCOPE | Claude |
| 2026-01-20 | ADR SCOPE candidate mining | Claude |
| 2026-01-19 | Discursive pattern extractor (ALTERNATIVE, DEFAULT, EXCEPTION) | Claude |
| 2026-01-18 | Types de base (enums, champs RawAssertion) | Claude |

---

## Références

- ADR principal: `doc/ongoing/ADR_DISCURSIVE_RELATIONS.md`
- ADR Scope vs Assertion: `doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md`
- ADR SCOPE mining: `doc/ongoing/ADR_SCOPE_DISCURSIVE_CANDIDATE_MINING.md`
- ADR NormativeRule & SpecFact: `doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md` ✅ APPROVED V1
- POC v3 results: 90.5% accuracy, 0% FP Type 2
- POC v4 results: 87.5% accuracy, 0% FP Type 2
