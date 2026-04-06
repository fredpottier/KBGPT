# Evidence Bundle Resolver - Vue d'Ensemble

**Objectif**: Transformer un KG pauvre (1 relation) en KG utilisable (25+ relations)
**Philosophie**: Assembler des preuves fragmentées, jamais inventer
**Référence**: `ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md` v1.3

---

## Le Problème Fondamental

### Situation actuelle

```
Documents ingérés: 23
Concepts extraits: 850
Relations validées: 1   ← INUTILISABLE
```

### Cause racine: Approche "localiste"

Le système cherche une preuve **complète** dans une fenêtre de ~512 tokens:

```
"X relie Y"   ← Doit être dans le même chunk
```

Mais dans les vrais documents, l'information est **distribuée**:

```
Page 1: "X est notre produit phare"
Page 5: "Ce produit s'intègre avec Y"
Page 8: [Diagramme] X → Y
```

---

## La Solution: Evidence Bundle

### Principe

Assembler des **fragments de preuve** qui, ensemble, démontrent une relation:

```
EVIDENCE BUNDLE
===============
EA: Evidence du sujet     → "X" (page 1)
EB: Evidence de l'objet   → "Y" (page 5)
EP: Evidence du prédicat  → "s'intègre avec" (page 5)
EL: Evidence du lien      → "Ce produit" → X (coréférence)

confidence = min(EA, EB, EP, EL)  ← Maillon faible gouverne
```

### Ce que ce n'est PAS

| ❌ Ce n'est PAS | ✅ C'est |
|-----------------|----------|
| De l'inférence | De l'assemblage de preuves explicites |
| De la génération | De la reconnaissance de patterns |
| Du ML opaque | Du pattern-matching auditable |
| Spécifique à un domaine | Agnostique (tout domaine, toute langue) |

---

## Architecture en 2 Sprints

### Sprint 1: Safe Mode (Fondation)

| Scope | Valeur |
|-------|--------|
| Fenêtre | Intra-section uniquement |
| Topic Binding | Non |
| Relations visuelles | Non |
| Objectif | 5-10 relations, précision ≥95% |

**But**: Prouver que le mécanisme fonctionne sur les cas simples.

### Sprint 2: Extended Mode (Puissance)

| Scope | Valeur |
|-------|--------|
| Fenêtre | Cross-section (sections liées) |
| Topic Binding | Oui ("ce produit" → X) |
| Relations visuelles | Oui (diagrammes) |
| Objectif | 15-25 relations, précision ≥90% |

**But**: Débloquer les cas réels où l'info est distribuée.

---

## Flux de Données Complet

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DOCUMENT                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                │
│  │ Page 1  │  │ Page 3  │  │ Page 5  │  │ Page 8  │                │
│  │ "X..." │  │ "Ce     │  │ "Y..." │  │ [Diag]  │                │
│  │         │  │ produit"│  │         │  │ X → Y   │                │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PASS 3.5: Evidence Bundle Resolver                │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ A. Topic Binding │  │ B. Candidate     │  │ C. Visual        │  │
│  │                  │  │    Detection     │  │    Extraction    │  │
│  │ "Ce produit" → X │  │ Paires (X,Y)     │  │ Flèches, boxes   │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
│           │                     │                     │            │
│           └──────────┬──────────┴──────────┬──────────┘            │
│                      │                     │                        │
│                      ▼                     ▼                        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                 D. Bundle Builder                             │  │
│  │                                                               │  │
│  │  EA: "X" (page 1)           ┐                                 │  │
│  │  EB: "Y" (page 5)           │                                 │  │
│  │  EP: "s'intègre" (page 5)   ├─→ EvidenceBundle                │  │
│  │  EL: "Ce produit"→X (coref) │                                 │  │
│  │                             ┘                                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                      │                                              │
│                      ▼                                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                 E. Bundle Validator                           │  │
│  │                                                               │  │
│  │  ✓ Proximité (sections liées)                                │  │
│  │  ✓ Prédicat non modal (POS check)                            │  │
│  │  ✓ Prédicat non générique (not "is", "has")                  │  │
│  │  ✓ Topic Binding valide (dominance > 50%)                    │  │
│  │                                                               │  │
│  │  → CANDIDATE | REJECTED (avec raison)                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                      │                                              │
│                      ▼                                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                 F. Confidence Calculator                      │  │
│  │                                                               │  │
│  │  confidence = min(0.95, 0.90, 0.85, 0.65) = 0.65             │  │
│  │                                                               │  │
│  │  Si confidence >= 0.7 → PROMOTED                             │  │
│  │  Sinon → reste CANDIDATE (review Sprint 3)                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                      │                                              │
└──────────────────────┼──────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         NEO4J                                        │
│                                                                      │
│  (X:CanonicalConcept)──[HAS_RELATION]──>(r:SemanticRelation)        │
│                                          │                          │
│                                          └──[RELATES_TO]──>(Y)      │
│                                          │                          │
│                                          └──[PROVEN_BY]──>(Bundle)  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Garde-fous par Sprint

### Sprint 1: Garde-fous Stricts

| Règle | Description | Agnostique? |
|-------|-------------|-------------|
| SAME_SECTION | Tous fragments même section | ✅ Structurel |
| AUXILIARY_VERB | POS = AUX | ✅ POS-based universel |
| COPULA_ATTRIBUTIVE | Structure attributive (dep=cop/attr) | ✅ Dep-based universel |
| MODAL_POS | POS = AUX + Mood=Cnd | ✅ POS/Morph universel |
| INTENTIONAL | Complément infinitif (xcomp/advcl) | ✅ Dep-based universel |

**Résultat**: Très peu de faux positifs, mais peu de relations.

### Sprint 2: Garde-fous Étendus

| Règle | Description | Agnostique? |
|-------|-------------|-------------|
| SIBLING_SECTIONS | Sections avec parent commun | ✅ Structurel |
| MAX_DISTANCE_3 | Max 3 sections d'écart | ✅ Structurel |
| ANAPHORIC_PATTERN | DET défini/démonstratif + NOUN sans modifieur | ✅ POS/Morph universel |
| CONCEPT_FREQUENCY | Nom non extrait OU ratio < 0.2 | ✅ Statistique |
| COMPETING_ANTECEDENTS | Pas de compétiteur dans la section | ✅ Contextuel |
| AMBIGUOUS_VISUAL | Rejette grouped_with, near | ✅ Technique |

**Résultat**: Plus de relations, avec approche D+ conservatrice (ABSTAIN si doute).

---

## Exemples par Domaine

### Pharmaceutique

**Sprint 1** (intra-section):
```
Section "Interactions":
"La Metformine ne doit pas être associée avec l'alcool."

→ Metformine --[CONTRAINDICATED_WITH]--> Alcool
  (tout dans la même section, pas de coréférence)
```

**Sprint 2** (cross-section + topic binding):
```
Section 1: "La Metformine est un antidiabétique."
Section 3: "Ce médicament ne doit pas être pris avec l'alcool."

→ Topic Binding: "Ce médicament" → Metformine (dominance 65%)
→ Metformine --[CONTRAINDICATED_WITH]--> Alcool
```

### Juridique

**Sprint 1**:
```
Article 6: "Le traitement n'est licite que si la personne a consenti."

→ Traitement --[REQUIRES]--> Consentement
```

**Sprint 2**:
```
Article 6: "Le traitement des données..."
Article 7: "Le consentement visé à l'article 6 doit être libre."

→ Cross-section (articles liés via référence explicite)
→ Traitement --[REQUIRES]--> Consentement
```

### SAP/IT

**Sprint 1**:
```
Section "Architecture":
"SAP S/4HANA s'intègre nativement avec SAP BTP."

→ S/4HANA --[INTEGRATES_WITH]--> BTP
```

**Sprint 2** (avec visuel):
```
Page 5: [Diagramme] S/4HANA ──SSO──> BTP
Caption: "Single Sign-On flow"

→ S/4HANA --[SSO]--> BTP (via caption)
```

---

## Risques et Mitigations

| Risque | Sprint | Mitigation |
|--------|--------|------------|
| Faux positifs textuels | 1+2 | Validation POS stricte |
| Topic Binding incorrect | 2 | Dominance 50% + scope local |
| Cross-section trop large | 2 | Distance max 3 sections |
| Visuels ambigus | 2 | Whitelist technique (arrow_to ok, grouped_with rejeté) |
| Confiance trop haute | 1+2 | `confidence = min(fragments)` |

---

## Métriques de Succès Globales

| Métrique | Sprint 1 | Sprint 2 | Total |
|----------|----------|----------|-------|
| Relations promues | 5-10 | +10-15 | 15-25 |
| Précision | ≥95% | ≥90% | ≥90% |
| Faux positifs tolérés | 0-1 | 1-2 | 1-3 |
| Couverture cross-section | 0% | 30%+ | 30%+ |
| Relations visuelles | 0 | 2-5 | 2-5 |

---

## Questions à Challenger

Avant de lancer l'implémentation, valider ces points:

### 1. Topic Binding
> **Q**: Un topic à 51% de dominance est-il suffisant pour résoudre "ce médicament"?
>
> **Réponse actuelle**: Oui, avec garde-fou "topic mentionné dans scope local".
> **Alternative**: Monter le seuil à 60-70%?

### 2. Distance Cross-Section
> **Q**: 3 sections d'écart est-il trop permissif?
>
> **Réponse actuelle**: Non, car on exige aussi "parent commun" OU "référence explicite".
> **Alternative**: Réduire à 2 sections?

### 3. Confiance des Visuels
> **Q**: Une relation visuelle sans caption mérite-t-elle confidence=0.5?
>
> **Réponse actuelle**: Oui, mais elle reste CANDIDATE (non promue automatiquement).
> **Alternative**: Réduire à 0.4 pour forcer review?

### 4. Retypage Générique
> **Q**: "DIRECTED_RELATION" est-il utile comme type?
>
> **Réponse actuelle**: Oui, c'est mieux que rien et c'est auditable.
> **Alternative**: Ne pas créer de relation si pas de type précis?

---

## Décision Requise

Avant de lancer Sprint 1:

- [ ] Valider l'architecture globale (Sprint 1 + Sprint 2)
- [ ] Valider les seuils (dominance 50%, distance 3, confidence 0.7)
- [ ] Valider les exemples multi-domaines
- [ ] Confirmer que Sprint 1 est une fondation solide pour Sprint 2

---

*Vue d'ensemble Evidence Bundle Resolver*
*Dernière mise à jour: 2026-01-17*
