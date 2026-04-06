# ADR - SCOPE : Discursive Candidate Mining

**Statut**: ACCEPTED
**Date**: 2026-01-21
**Auteurs**: Équipe OSMOSE
**Dépend de**: ADR Relations Discursivement Déterminées, ADR Navigation Layer

---

## Contexte

L'ADR "Relations Discursivement Déterminées" définit 6 bases discursives dont `SCOPE` (maintien de portée entre spans). Cette ADR définit **comment** implémenter `SCOPE` de manière opérationnelle, en respectant les contraintes épistémiques du système.

**Problème identifié** : La tentation naturelle est de créer des relations Concept→Concept basées sur la co-présence dans un même scope documentaire. Cette approche viole le principe fondamental :

> *"Pas de relation sans possibilité d'expliquer pourquoi, preuve à l'appui."*

---

## Décision

### Positionnement architectural

**SCOPE n'est PAS un générateur de relations.**

SCOPE est un mécanisme à trois fonctions :

1. **Candidate Mining** : génère des paires de concepts à vérifier
2. **Validity Filtering** : fournit un cadre pour valider/invalider des assertions
3. **Routing** : justifie le mode Anchored quand aucun path sémantique n'existe

**Phrase contractuelle** :

> *"SCOPE is a candidate mining and validity-filtering mechanism. It never produces semantic relations by itself."*

---

## Invariants non négociables

### INV-SCOPE-01 : Pas de relation Concept→Concept

SCOPE ne crée **jamais** de relation directe entre concepts. Il produit uniquement des `CandidatePair` qui doivent être vérifiés avant de devenir des assertions.

```
❌ Interdit : Concept A ──APPLIES_TO──> Concept B (créé par SCOPE seul)
✅ Autorisé : CandidatePair(A, B) → Verifier → RawAssertion (si validé)
```

### INV-SCOPE-02 : Marquage obligatoire

Toute assertion issue de SCOPE **DOIT** porter :
- `assertion_kind = DISCURSIVE`
- `discursive_basis = ["SCOPE"]`

### INV-SCOPE-03 : Multi-span obligatoire

Toute assertion SCOPE **DOIT** avoir un `EvidenceBundle` contenant **≥2 DocItems distincts** :
- `span1` : scope_setter (HEADING ou premier DocItem de section)
- `span2+` : mention(s) des concepts impliqués

Si le bundle ne peut pas être construit avec ≥2 spans → `ABSTAIN(WEAK_BUNDLE)`.

### INV-SCOPE-04 : Abstain motivé (unifié)

Toute décision négative **DOIT** produire un `abstain_reason` structuré. L'ABSTAIN peut être émis à **trois niveaux** :

**Niveau Miner (déterministe, sans LLM) :**
- `WEAK_BUNDLE` : bundle insuffisant (<2 spans)
- `SCOPE_BREAK` : rupture de portée détectée (structural)
- `NO_SCOPE_SETTER` : section sans scope_setter valide

**Niveau Bridge Detector (déterministe, sans LLM) :**
- `NO_BRIDGE_EVIDENCE` : aucun DocItem ne contient les deux concepts A et B ensemble

**Niveau Verifier (LLM) :**
- `TYPE2_RISK` : risque de relation déduite
- `AMBIGUOUS_PREDICATE` : prédicat non défendable (pas de marqueur explicite)
- `SCOPE_BREAK_LINGUISTIC` : rupture de portée linguistique détectée

**Important** : Les ABSTAIN niveau Miner et Bridge Detector évitent l'appel LLM. Seuls les candidats avec bridge sont transmis au Verifier.

**Distribution typique observée (2026-01-21) :**
- ~75% des candidats : `ABSTAIN(NO_BRIDGE_EVIDENCE)` — sans appel LLM
- ~25% des candidats : transmis au LLM Verifier
  - ~22% de ceux-ci : `ASSERT` (relation validée)
  - ~78% de ceux-ci : `ABSTAIN(AMBIGUOUS_PREDICATE)` (pas de marqueur)

### INV-SCOPE-05 : Budgets = garde-fous sémantiques

Les paramètres de budget ne sont **pas des optimisations**. Ce sont des **garde-fous épistémiques** :

| Paramètre | Valeur V1 | Rationale |
|-----------|-----------|-----------|
| `top_k_pivots` | 5 | Limite l'explosion combinatoire aux concepts saillants |
| `max_concepts_per_scope` | 30 | Évite le bruit sur sections très denses |
| `max_pairs_per_scope` | 50 | Budget strict anti-explosion |
| `require_min_spans` | 2 | Garantit la défendabilité multi-span |

**Modifier ces valeurs nécessite une justification documentée.**

### INV-SCOPE-06 : Routing = query-time only

La fonction "Routing" de SCOPE (justification du mode Anchored) est **exclusivement query-time**. Elle n'écrit **rien** dans le graphe à l'ingestion.

```
❌ Interdit : Créer un edge "SCOPE_FALLBACK" ou "ANCHORED_PATH" à l'ingestion
✅ Autorisé : À la requête, si pas de path sémantique, utiliser ANCHORED_IN via section
```

### INV-SCOPE-07 : Bridge Eligibility (VALIDÉ expérimentalement 2026-01-21)

> **Loi structurelle** : Une relation ne peut être évaluée par le LLM que s'il existe une **unité textuelle locale** (DocItem) capable de la porter — c'est-à-dire contenant **les deux concepts A et B ensemble**.

Cette unité minimale s'appelle le **BRIDGE**.

```
❌ Sans BRIDGE : Le LLM voit A dans phrase1, B dans phrase2 → ne peut PAS trouver de marqueur A↔B
✅ Avec BRIDGE : Le LLM voit "A applies to B" dans une même phrase → peut valider
```

**Conséquences opérationnelles :**

1. **Garde-fou déterministe** : Si `has_bridge = false`, le candidat est `ABSTAIN(NO_BRIDGE_EVIDENCE)` **sans appeler le LLM** (économie de tokens)

2. **Model Interchangeability** : Quand le bridge existe, Qwen 2.5 14B ≈ Claude 3 Haiku en performance (22% vs 18.6% ASSERT)

3. **Qualité architecturale** : La qualité vient de l'architecture (bridge detection), pas du modèle LLM

**Validation expérimentale (2026-01-21) :**

| Métrique | Sans bridge detection | Avec bridge detection |
|----------|----------------------|----------------------|
| Candidats testés | 890 | 50 (filtrés) |
| ASSERT | 0 (0%) | 11 (22%) |
| Économie appels LLM | - | ~75% |

### INV-SCOPE-08 : Role Separation

Le pipeline SCOPE respecte une **séparation stricte des rôles** :

| Composant | Rôle | Ne fait PAS |
|-----------|------|-------------|
| **Miner** | Propose des candidats (A, B) | Ne juge pas la relation |
| **Bridge Detector** | Qualifie l'éligibilité textuelle | Ne juge pas la sémantique |
| **LLM Verifier** | Tranche sur la relation | Ne répare pas une absence de preuve |

> **Principe** : Le LLM ne **répare jamais** une absence de preuve. Il ne fait que **confirmer ou infirmer** une relation déjà supportée textuellement.

---

## Entrées / Sorties contractuelles

### Entrées (ce que SCOPE consomme)

| Entrée | Source |
|--------|--------|
| `SectionContext` | Navigation Layer |
| `DocItem` | Structural Layer |
| `ProtoConcept → CanonicalConcept` | Concept Layer |
| `ANCHORED_IN` | Linking |

### Sorties (ce que SCOPE produit)

| Sortie | Destination |
|--------|-------------|
| `CandidatePair` | Verifier (Pass 3) |
| `EvidenceBundle (basis=SCOPE)` | RawAssertion (si validé) |
| `ABSTAIN(reason)` | Logs / Observabilité |

### Non-sorties (ce que SCOPE ne produit PAS)

- ❌ `CanonicalRelation`
- ❌ `SemanticRelation`
- ❌ Navigation edge Concept→Concept
- ❌ Nouveau concept
- ❌ Node `EvidenceBundle` (pas de nœud dédié)

### Stockage V1 : EvidenceBundle sérialisé

L'`EvidenceBundle` n'est **pas** un nœud Neo4j. Il est **sérialisé en JSON** dans la propriété `evidence_bundle` de `RawAssertion` :

```cypher
// Exemple de RawAssertion avec bundle sérialisé
CREATE (ra:RawAssertion {
  assertion_kind: "DISCURSIVE",
  discursive_basis: ["SCOPE"],
  relation_type: "APPLIES_TO",
  evidence_bundle: '{"spans": [{"doc_item_id": "...", "role": "scope_setter"}, ...], "basis": "SCOPE"}'
})
```

**Rationale** : Évite la prolifération de nœuds. Le bundle est reconstituable via les `doc_item_id` référencés.

---

## Pipeline SCOPE V1.1 (avec Bridge Detection)

```
┌─────────────────────────────────────────────────────────────────┐
│ SCOPE CANDIDATE MINING (Pass 2.5 ou début Pass 3)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Pour chaque SectionContext :                                   │
│                                                                 │
│  1. ScopedConceptSet                                            │
│     └─ Top-k concepts par salience (mention_count, position)    │
│                                                                 │
│  2. Pivot Selection (CG-1)                                      │
│     └─ Pivots = top_k_pivots concepts les plus saillants        │
│                                                                 │
│  3. Pair Generation (CG-2)                                      │
│     └─ Paires (pivot, other) uniquement                         │
│     └─ Budget: max_pairs_per_scope                              │
│                                                                 │
│  4. Bundle Building + Bridge Detection                          │
│     └─ scope_setter (SCOPE_SETTER)                              │
│     └─ bridge = intersection(pivot.doc_items, other.doc_items)  │
│     └─ Si bridge existe → span BRIDGE (A+B ensemble)            │
│     └─ mentions séparées (MENTION)                              │
│     └─ has_bridge = true/false                                  │
│     └─ Si <2 spans → ABSTAIN(WEAK_BUNDLE)                       │
│                                                                 │
│  5. Output: List[CandidatePair] avec has_bridge                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ BRIDGE ELIGIBILITY GATE (déterministe, sans LLM)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Si has_bridge = false:                                         │
│     → ABSTAIN(NO_BRIDGE_EVIDENCE) immédiat                      │
│     → Pas d'appel LLM (économie ~75% des tokens)                │
│                                                                 │
│  Si has_bridge = true:                                          │
│     → Transmettre au VERIFIER LLM                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ VERIFIER LLM (Pass 3)                                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Input: CandidatePair (avec BRIDGE) + Whitelist                 │
│                                                                 │
│  Prompt V2 (focalisé sur le bridge):                            │
│    "CRITICAL EVIDENCE - Both concepts appear together:          │
│     {bridge_text}"                                              │
│                                                                 │
│  Output:                                                        │
│    ├─ ASSERT(relation_type, direction, confidence, marker)      │
│    │   └─ marker = "for", "in", "requires", etc.                │
│    │                                                            │
│    └─ ABSTAIN(AMBIGUOUS_PREDICATE) si pas de marqueur           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ WRITE (si ASSERT)                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  RawAssertion:                                                  │
│    assertion_kind = DISCURSIVE                                  │
│    discursive_basis = ["SCOPE"]                                 │
│    relation_type = (from verifier, whitelist-checked)           │
│    evidence_bundle = (multi-span avec BRIDGE)                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Scope Setter Selection (algorithme déterministe)

Le `scope_setter` est le DocItem qui définit le contexte de portée. Sa sélection est **déterministe** (pas de LLM) :

**Ordre de priorité :**

1. **HEADING de section** : Si `SectionContext` contient un DocItem avec `item_type = "heading"`, c'est le scope_setter
2. **Premier DocItem textuel** : Sinon, premier DocItem de la section avec `len(text) > 20`
3. **Fallback** : Premier DocItem de la section (même court)
4. **Échec** : Si section vide → pas de candidate pour cette section (log warning)

```python
def select_scope_setter(section: SectionContext) -> Optional[DocItem]:
    # 1. Heading
    headings = [d for d in section.doc_items if d.item_type == "heading"]
    if headings:
        return headings[0]

    # 2. Premier DocItem textuel substantiel
    textual = [d for d in section.doc_items if len(d.text or "") > 20]
    if textual:
        return textual[0]

    # 3. Fallback
    if section.doc_items:
        return section.doc_items[0]

    # 4. Échec
    return None
```

---

## Whitelist RelationType pour SCOPE V1

Pour éviter la dérive "APPLIES_TO partout", SCOPE V1 utilise une whitelist **plus stricte** que la whitelist discursive générale :

| RelationType | Condition d'autorisation |
|--------------|-------------------------|
| `APPLIES_TO` | Marqueur explicite dans les spans ("for", "in context of", "applies to") |
| `REQUIRES` | Modalité normative explicite ("shall", "must", "required") |
| Autres | `ABSTAIN(AMBIGUOUS_PREDICATE)` |

Cette whitelist peut être élargie en V2 si le taux de faux positifs reste à 0%.

---

## Scope Break Detection

Une relation SCOPE n'est valide que si la portée est maintenue entre les spans.

### Ruptures structurelles (détection déterministe)

- Changement de `section_id` (sortie du scope)
- Heading sibling ou parent (nouvelle section)

### Ruptures linguistiques (détection heuristique, V2)

- Marqueurs de contraste : "however", "in contrast", "but"
- Marqueurs de restriction : "only for", "except for"

En cas de rupture détectée → `ABSTAIN(SCOPE_BREAK)`.

**V1** : Scope = `section_id` strict (pas de descendants).

---

## Liens avec les autres ADR

### S'appuie sur

| ADR | Usage |
|-----|-------|
| ADR Relations Discursivement Déterminées | `assertion_kind`, `discursive_basis`, `abstain_reason`, whitelist |
| ADR Navigation Layer | `SectionContext`, `ContextNode`, séparation navigation/sémantique |
| ADR Multi-Span Evidence Bundles | Structure `EvidenceBundle`, `EvidenceSpan` |

### N'étend PAS

- Le modèle de graphe (pas de nouveau node type)
- La whitelist RelationType globale (whitelist SCOPE-only)
- Le pipeline de promotion (CanonicalRelation → SemanticRelation inchangé)

---

## Métriques de succès V1.1

| Métrique | Cible | Observé (2026-01-21) |
|----------|-------|----------------------|
| Candidates / section | p95 < 50 | ✅ 45-50 |
| Taux bridge coverage | > 20% | ✅ 24.1% |
| Taux ASSERT (sur bridged) | > 15% | ✅ 22% |
| FP Type 2 | = 0% | ✅ 0% (tests) |
| Multi-span compliance | = 100% | ✅ 100% |
| Économie tokens (vs naive) | > 50% | ✅ ~75% |

---

## Résultats expérimentaux (2026-01-21)

### Test 1 : Bridge Coverage

Sur 10 sections avec ≥3 concepts :

```
Candidats totaux: 440
  - Avec BRIDGE (A+B ensemble): 106 (24.1%)
  - Sans BRIDGE (A et B séparés): 334 (75.9%)
```

**Conclusion** : ~75% des candidats sont éliminés sans appeler le LLM.

### Test 2 : Qwen 2.5 14B avec Bridge Detection

Sur 50 candidats avec bridge, vérifiés par Qwen 2.5 14B (vLLM) :

```
ASSERT: 11 (22.0%)
ABSTAIN: 39 (78.0%)
  - Raison: AMBIGUOUS_PREDICATE (pas de marqueur explicite)
```

**Comparaison avec Claude 3 Haiku (sans bridge detection) :**

| Modèle | ASSERT rate | Note |
|--------|-------------|------|
| Qwen 2.5 14B (sans bridge) | 0% | Candidats non éligibles |
| Qwen 2.5 14B (avec bridge) | 22% | ✅ Comparable |
| Claude 3 Haiku | 18.6% | Référence |

**Conclusion** : La qualité vient de l'architecture (bridge detection), pas du modèle.

---

## EvidenceSpanRole (V1.1)

Les spans dans un `EvidenceBundle` portent un rôle explicite :

| Role | Description | Obligatoire |
|------|-------------|-------------|
| `SCOPE_SETTER` | DocItem définissant le contexte (heading ou premier) | Oui (1) |
| `BRIDGE` | DocItem contenant A **ET** B ensemble | Non (0-1) |
| `MENTION` | DocItem contenant une mention de A ou B séparément | Non (0-n) |

**Structure typique d'un bundle avec bridge :**

```json
{
  "basis": "SCOPE",
  "has_bridge": true,
  "spans": [
    {"role": "SCOPE_SETTER", "doc_item_id": "di_001", "text_excerpt": "SAP S/4HANA Features"},
    {"role": "BRIDGE", "doc_item_id": "di_005", "text_excerpt": "TLS encryption is required for all API calls"},
    {"role": "MENTION", "doc_item_id": "di_003", "concept_id": "c_tls", "text_excerpt": "...TLS 1.3..."},
    {"role": "MENTION", "doc_item_id": "di_007", "concept_id": "c_api", "text_excerpt": "...API endpoints..."}
  ]
}
```

---

## Limitations V1.1

1. **Scope = section strict** : pas de propagation aux sous-sections
2. ~~**Pas de bridge spans**~~ ✅ **RÉSOLU** : Bridge detection implémentée
3. **Pas de document fallback** : si section pauvre, pas de remontée au document
4. **Whitelist très stricte** : APPLIES_TO et REQUIRES uniquement
5. **Bridge = intersection stricte** : pas de fenêtre ±1 phrase (V2)

Ces limitations seront levées en V2 si les métriques V1.1 sont satisfaisantes.

---

## Conséquences

### Positives

1. SCOPE devient opérationnel sans compromettre l'intégrité épistémique
2. Les invariants protègent contre les dérives futures
3. Le pipeline reste auditable (tout ABSTAIN est motivé)
4. Compatible avec l'architecture existante (pas de nouveau node type)

### Négatives

1. Taux d'ABSTAIN probablement élevé au début (conservateur)
2. Whitelist SCOPE-only peut manquer des relations valides
3. Scope = section strict peut être trop restrictif

---

## Prochaines étapes

1. **Validation de cet ADR** → Statut ACCEPTED
2. **Implémentation** strictement conforme aux invariants
3. **Tests** sur 3-5 sections réelles
4. **Mesures** : volume candidates, taux ABSTAIN, distribution raisons
5. **Itération V2** si métriques satisfaisantes

---

## Références

- [ADR Relations Discursivement Déterminées](./ADR_DISCURSIVE_RELATIONS.md)
- [Spec ChatGPT SCOPE](conversation_2026-01-21) - Structures de données et Cypher templates
