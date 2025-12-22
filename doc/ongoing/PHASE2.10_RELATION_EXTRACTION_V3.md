# Phase 2.10 - Architecture V3 : Extraction Relations Hybride

**Date de création:** 2025-12-22
**Dernière mise à jour:** 2025-12-22
**Statut:** IMPLÉMENTÉ
**Objectif:** Résoudre le problème des 71% UNKNOWN tout en conservant le multi-sourcing

**Validation:** Document stress-testé avec ChatGPT (analyse collaborative 2025-12-22)

---

## 11. Implémentation Réalisée (2025-12-22)

### Fichiers Modifiés

#### Backend - Types et Structures
| Fichier | Modifications |
|---------|---------------|
| `src/knowbase/relations/types.py` | Ajout `PREVENTS`, nouveaux champs RawAssertion, `AMBIGUOUS_TYPE`, `CONTEXT_DEPENDENT` |
| `src/knowbase/relations/__init__.py` | Exports V4 (ExtractedRelationV4, TypeFirstExtractionResult) |

#### Backend - Extraction
| Fichier | Modifications |
|---------|---------------|
| `src/knowbase/relations/llm_relation_extractor.py` | Prompt V4 Type-First, `CORE_RELATION_TYPES_V4`, `extract_relations_type_first()` |
| `src/knowbase/relations/raw_assertion_writer.py` | Nouveaux paramètres V4 (relation_type, type_confidence, alt_type, etc.) |

#### Scripts - Consolidation
| Fichier | Modifications |
|---------|---------------|
| `app/scripts/consolidate_relations.py` | Query 7.2 enrichie, `determine_relation_type_v4()`, maturité épistémique, edges directs |

### Nouvelles Fonctionnalités

1. **12 Core Types** : PART_OF, SUBTYPE_OF, REQUIRES, ENABLES, USES, INTEGRATES_WITH, APPLIES_TO, CAUSES, PREVENTS, VERSION_OF, REPLACES, ASSOCIATED_WITH

2. **Maturité Épistémique** :
   - `negated_ratio > 0.20` → CONFLICTING
   - `hedged_ratio > 0.50` → block VALIDATED
   - `conditional_ratio > 0.70` → CONTEXT_DEPENDENT
   - `is_ambiguous_type` → AMBIGUOUS_TYPE

3. **Quarantaine ASSOCIATED_WITH** : max maturity = CANDIDATE, pas d'edge direct

4. **Edges Directs** : Matérialisés pour VALIDATED (pas ASSOCIATED_WITH)

### Instructions de Test

```bash
# 1. Tester extraction V4 sur un document
docker-compose exec app python -c "
from knowbase.relations.llm_relation_extractor import LLMRelationExtractor
from knowbase.common.llm_router import LLMRouter

router = LLMRouter()
extractor = LLMRelationExtractor(llm_router=router, model='gpt-4o-mini')

# Test avec concepts fictifs
concepts = [
    {'canonical_id': 'c1', 'name': 'GDPR', 'concept_type': 'standard'},
    {'canonical_id': 'c2', 'name': 'Data Privacy', 'concept_type': 'abstract'},
]
text = 'GDPR requires organizations to implement Data Privacy measures.'

result = extractor.extract_relations_type_first(
    concepts=concepts,
    full_text=text,
    document_id='test_doc',
    chunk_id='chunk_0'
)
print(f'Relations: {len(result.relations)}')
for rel in result.relations:
    print(f'  {rel.relation_type}: {rel.subject_surface_form} -> {rel.object_surface_form}')
"

# 2. Tester consolidation avec maturité épistémique
docker-compose exec app python /app/scripts/consolidate_relations.py --dry-run

# 3. Exécuter consolidation complète avec edges directs
docker-compose exec app python /app/scripts/consolidate_relations.py

# 4. Vérifier les stats de maturité
docker-compose exec app python /app/scripts/consolidate_relations.py --no-edges
```

### Prochaines Étapes (UX)

Selon l'analyse ChatGPT sur "Progressive Disclosure of Truth" :

1. **Response Contract API** : Ajouter endpoint qui retourne CONFIRMED/REFUTED/NO_EVIDENCE
2. **Vue Simplifiée** : Interface utilisateur avec réponse simple + "voir détails"
3. **Drilldown** : Accès aux evidences et sources pour utilisateurs experts

---

## 0. Résumé Exécutif

### Décision Architecturale
V3 = **Set fermé à l'extraction** + **Multi-assertions conservées** + **Maturité épistémique**

### Garanties
- ✅ Plus d'écrasement d'information (multi-sourcing)
- ✅ Plus de 71% UNKNOWN (type choisi à l'extraction)
- ✅ Contradictions et incertitudes capturées (flags)
- ✅ Navigation directe possible (edges VALIDATED)

### Limites Assumées
- ⚠️ Consensus faux possible si sources homogènes
- ⚠️ Contexte local peut être perdu lors de l'agrégation
- ⚠️ Complexité à médiatiser pour utilisateurs non-experts

---

## 1. Contexte et Problème

### Architecture V1 (Ancien système)
- **Set fermé de 9 RelationType** forcé à l'extraction
- **Edges directs** : `(Concept)-[:REQUIRES]->(Concept)`
- **Logique upsert "winner takes all"** : seule la meilleure confidence conservée
- **Problème** : Écrasement des informations, perte du multi-sourcing

### Architecture V2 (Actuelle)
- **Prédicats libres** (`predicate_raw`) pour préserver l'audit
- **RawAssertion** : chaque assertion stockée séparément
- **Flags détaillés** : is_negated, is_hedged, is_conditional, cross_sentence
- **Consolidation via regex** : mapping `predicate_raw` → `relation_type`
- **Problème** : 71% des prédicats → UNKNOWN (regex ne couvre pas la variété)

### Architecture V3 (Cible)
- **Set fermé à l'extraction** (LLM choisit parmi 12 types)
- **Multi-sourcing conservé** (RawAssertion, pas d'écrasement)
- **Consolidation simplifiée** (rollup par type, plus de regex)
- **Dual representation** : CanonicalRelation + edges directs VALIDATED

---

## 2. Les 12 Types de Relations (Core Set Domain-Agnostic)

### Structurel
| Type | Description | Exemples |
|------|-------------|----------|
| `PART_OF` | A fait partie de B | "Fiori is part of S/4HANA" |
| `SUBTYPE_OF` | A est un type/sous-classe de B | "S/4HANA Cloud is a type of ERP" |

### Dépendance / Fonctionnel
| Type | Description | Exemples |
|------|-------------|----------|
| `REQUIRES` | A nécessite B (obligatoire) | "NIS2 requires risk management" |
| `ENABLES` | A permet/active B | "HANA enables real-time analytics" |
| `USES` | A utilise B (optionnel) | "SAP uses ABAP" |
| `INTEGRATES_WITH` | A s'intègre avec B | "SAP integrates with Salesforce" |
| `APPLIES_TO` | A s'applique à / gouverne B | "GDPR applies to data processors" |

### Causalité / Contrainte
| Type | Description | Exemples |
|------|-------------|----------|
| `CAUSES` | A cause/entraîne B | "Breach causes notification obligation" |
| `PREVENTS` | A empêche/interdit B | "Encryption prevents data theft" |

### Temporel / Évolution
| Type | Description | Exemples |
|------|-------------|----------|
| `VERSION_OF` | A est une version de B | "AI Act 2024 is version of AI Act" |
| `REPLACES` | A remplace B | "S/4HANA replaces ECC" |

### Fallback
| Type | Description | Exemples |
|------|-------------|----------|
| `ASSOCIATED_WITH` | Association faible (dernier recours) | Relation claire mais non typable |

---

## 3. Prompt V3 Complet

### System Prompt

```text
You are OSMOSE Relation Extractor (V3).

Goal:
Extract factual relations between concepts from a text segment, using a CLOSED, domain-agnostic set of relation types.
You must be strict and conservative. Do not invent facts. Do not infer unstated relations.

You will be given:
1) A text segment (evidence source)
2) A catalog of concepts with IDs (c1, c2, ...), labels, and optional metadata.

Hard constraints:
- You may ONLY use the provided concept IDs as subject/object (no new concepts).
- Output must be ONLY valid JSON (no markdown, no commentary).
- Every relation MUST have an evidence snippet from the text (verbatim or near-verbatim).
- If the text does not explicitly support a relation, do NOT output it.

Relation types (choose exactly ONE primary type):
STRUCTURAL
- PART_OF         (A is part of B / contained in B / belongs to B)
- SUBTYPE_OF      (A is a type/kind/subclass of B)

DEPENDENCY / FUNCTIONAL
- REQUIRES        (A requires/needs B to function/comply/occur)
- ENABLES         (A enables/allows/supports B)
- USES            (A uses/utilizes/leverages B)
- INTEGRATES_WITH (A integrates/interoperates/connects with B)
- APPLIES_TO      (A applies to/governs/regulates/targets B)

CAUSALITY / CONSTRAINT
- CAUSES          (A causes/leads to/results in B)
- PREVENTS        (A prevents/prohibits/blocks B)

TEMPORAL / EVOLUTION
- VERSION_OF      (A is a version/variant of B)
- REPLACES        (A replaces/supersedes B)

FALLBACK
- ASSOCIATED_WITH (weak association; only if nothing stronger fits AND the text clearly links them)

Typing requirements:
- Also return predicate_raw: the exact wording used in the text that expressed the relation (as close as possible).
- Return type_confidence for the chosen relation_type between 0 and 1.
- Optionally provide alt_type (one alternative relation_type) ONLY if ambiguity is real and supported; also include alt_type_confidence.

Anti-junk rules (very important):
- Do NOT output relations where subject or object is:
  (a) a purely structural reference (e.g., "Article 12", "Annex III", "Chapter IV", "Section 3", "Recital 28"),
  (b) a generic vague term used without a concrete role (e.g., "Health", "Justice", "Market", "Guidance"), unless the text clearly makes it a specific entity or defined concept.
- Do NOT output "includes/contains" as relations unless it truly expresses PART_OF and the components are meaningful concepts.
- Do NOT output relations that are only list co-occurrence (A and B mentioned in the same list) without a connective claim.

Negation / modality / conditions:
For each relation, set flags:
- is_negated: true if the text asserts the negation (e.g., "does not require", "shall not")
- is_hedged: true if uncertain (e.g., "may", "might", "can", "could", "typically")
- is_conditional: true if conditional (e.g., "if/when/in case/subject to")
- cross_sentence: true ONLY if the relation needs more than one sentence to be explicit (otherwise false)

Evidence:
- evidence must be a short snippet that directly supports the relation (15–40 words recommended).
- Provide evidence_start_char and evidence_end_char as offsets into the provided text segment IF possible; otherwise set them to null.

Deduplication:
- Do not repeat exact duplicates (same subject_id, relation_type, object_id, and same negation flag).

Directionality:
- Preserve direction: "A requires B" => subject=A, object=B.
- If the sentence is passive, normalize direction logically (e.g., "B is required by A" => A REQUIRES B).

If no valid relations exist, return {"relations": []}.
```

### User Prompt Template

```text
Extract relations between the concepts from the text.

TEXT:
{text_segment}

CONCEPT CATALOG (use ONLY these IDs):
{concept_catalog_json}

Output ONLY valid JSON following the schema.
```

---

## 4. Format JSON de Sortie

### Schema (enrichi après stress-test)

```json
{
  "relations": [
    {
      "subject_id": "c12",
      "object_id": "c07",

      "relation_type": "REQUIRES",
      "type_confidence": 0.92,
      "alt_type": "ENABLES",
      "alt_type_confidence": 0.58,

      "predicate_raw": "requires",
      "relation_subtype_raw": "requires compliance with",

      "flags": {
        "is_negated": false,
        "is_hedged": false,
        "is_conditional": true,
        "cross_sentence": false
      },

      "context_hint": "for medical devices",

      "evidence": "If the provider places the system on the market, it requires appropriate risk management measures.",
      "evidence_start_char": 1280,
      "evidence_end_char": 1386
    }
  ]
}
```

### Champs Ajoutés (stress-test)

| Champ | Description | Usage |
|-------|-------------|-------|
| `relation_subtype_raw` | Nuance sémantique fine (optionnel) | Audit uniquement, pas de navigation |
| `context_hint` | Scope/contexte local extrait | Visible API, pas de raisonnement |

### Règles de Validation Pipeline

| Règle | Condition |
|-------|-----------|
| Type valide | `relation_type` ∈ {12 types définis} |
| Confidence minimale | `type_confidence` ≥ 0.70 pour stocker |
| Alt type différent | `alt_type` ≠ `relation_type` si présent |
| Predicate non vide | `predicate_raw` != "" |
| Evidence non vide | `evidence` != "" |
| Pas d'auto-relation | `subject_id` != `object_id` |
| Négation structurelle | Drop si `is_negated=true` ET `relation_type` ∈ {PART_OF, SUBTYPE_OF, VERSION_OF} |

---

## 5. Règles Anti-Junk

### Dans le prompt (LLM)
1. **Co-occurrence ≠ relation** : "A, B, C" dans une liste → aucune relation
2. **Références structurelles** : "Article 12", "Annex III" → pas de sujet/objet
3. **Termes génériques** : "Market", "Health" sans rôle concret → exclus

### En post-traitement (code)
1. **Verbes faibles** : "includes", "contains" → uniquement si PART_OF clair
2. **Ratio ASSOCIATED_WITH** : max 20% par document
3. **APPLIES_TO** : exiger cue explicite ("governs", "regulated under")
4. **INTEGRATES_WITH** : exiger cue d'interop clair

---

## 6. Impact sur la Consolidation

### Avant (V2)
```python
# Mapping regex predicate_raw → relation_type
relation_type, confidence = map_predicate_to_type(predicate_norm)
# 71% → UNKNOWN
```

### Après (V3)
```python
# relation_type déjà connu depuis l'extraction
# Consolidation = simple rollup
groupby(subject_id, object_id, relation_type, is_negated)
→ aggregate(count, distinct_docs, confidence_stats)
→ compute_maturity()
```

---

## 7. Dual Representation (CR + Edges Directs)

### CanonicalRelation (Source of Truth)
- Porte toutes les métadonnées agrégées
- Trace vers RawAssertions sources
- Gère contradictions et hedging

### Edges Directs (Projection pour Navigation)
Créés uniquement pour :
- `maturity = VALIDATED`
- `relation_type != ASSOCIATED_WITH`
- `confidence_p50 >= 0.75`
- `distinct_docs >= 2`

```cypher
(A:CanonicalConcept)-[:REQUIRES {cr_id, conf_p50, docs, last_seen}]->(B:CanonicalConcept)
```

### Principe Fondamental (stress-test)
> **Les edges directs sont un INDEX, pas une vérité.**

- Reconstruisibles à tout moment depuis les CR
- Rebuild on maturity change ou nightly
- Aucune information métier unique sur l'edge

---

## 8. Garde-fous et Contraintes (issus du stress-test)

### 8.1 Gestion de l'Ambiguïté de Type

**Problème:** Erreur de typage "propre" qui se canonise silencieusement.

**Règle AMBIGUOUS_TYPE:**
```python
if alt_type is not None:
    delta = abs(type_confidence - alt_type_confidence)
    if delta < 0.15:
        maturity = "AMBIGUOUS_TYPE"  # Jamais VALIDATED
        allow_direct_edge = False
```

### 8.2 Quarantaine ASSOCIATED_WITH

**Problème:** ASSOCIATED_WITH devient un "trou noir" du graphe.

**Règles strictes:**
```python
if relation_type == "ASSOCIATED_WITH":
    max_maturity = "CANDIDATE"      # Jamais VALIDATED
    allow_direct_edge = False       # Jamais matérialisé
    # C'est une relation de DIAGNOSTIC, pas de connaissance
```

### 8.3 Maturité Épistémique (sensible aux flags)

**Problème:** Flags sous-exploités = KG qui affirme des choses contestées.

**Règles de maturité:**
```python
# Ratios calculés sur les RawAssertions du groupe
if negated_ratio > 0.20:
    maturity = "CONFLICTING"

if hedged_ratio > 0.50:
    block_validated = True

if conditional_ratio > 0.70:
    maturity = "CONTEXT_DEPENDENT"
```

### 8.4 Détection Similarité Sources

**Problème:** Consensus faux mais stable (majority fallacy).

**Règle (future):**
```python
if distinct_docs >= 2 and textual_similarity(evidences) > 0.85:
    flag = "SUSPECTED_COMMON_SOURCE"
    block_validated = True
```

> **Note:** Non implémenté en Phase 2.10, documenté comme limite connue.

---

## 9. Zones Grises et Limites Connues

### 9.1 Consensus Faux Stable (Majority Fallacy)

**Description:**
Plusieurs documents indépendants peuvent affirmer la même chose erronée (source secondaire commune, formulation similaire héritée).

**Impact:**
Relation devient VALIDATED alors qu'elle est fausse dans le monde réel.

**Mitigation actuelle:**
Aucune (hors scope Phase 2.10).

**Mitigation future possible:**
- Détection similarité textuelle entre evidences
- Clustering de documents par origine

### 9.2 Context Leakage (Perte de Contexte Local)

**Description:**
"X requires Y **for medical devices**" agrégé en "X REQUIRES Y" perd le contexte.

**Impact:**
Vérité locale transformée en vérité globale "amoindrie".

**Mitigation actuelle:**
- Champ `context_hint` pour conserver le scope (non structuré)
- Flag `is_conditional` + `conditional_ratio` en maturité

### 9.3 Absence ≠ Négation (Limite Épistémologique)

**Description:**
Le KG ne distingue pas :
- "A ne requiert pas B" (négation explicite, `is_negated=true`)
- "Aucune info sur A→B" (absence de connaissance)

**Impact:**
Utilisateurs peuvent confondre "pas de relation trouvée" avec "relation niée".

**Mitigation actuelle:**
À traiter au niveau API/UX, pas dans le KG.

**Règle UX:**
- "No evidence found" ≠ "Evidence of absence"
- Doit être explicite dans les réponses

---

## 10. Principes UX : Vue Simplifiée vs Experte

### Problème
Un KG sophistiqué (AMBIGUOUS_TYPE, CONFLICTING, hedged_ratio 62%, etc.) est illisible pour 80% des utilisateurs.

### Solution : Deux Vues

#### Vue Simplifiée (API / UI grand public)
| État Affiché | Conditions |
|--------------|------------|
| **Confirmed** | maturity = VALIDATED |
| **Contested** | maturity = CONFLICTING ou negated_ratio > 0.20 |
| **Uncertain** | maturity = CANDIDATE ou hedged_ratio > 0.30 |
| **No evidence** | Aucune relation trouvée |

#### Vue Experte (API détaillée / Debug)
Tous les champs disponibles :
- maturity, confidence_p50, type_confidence
- alt_type, alt_type_confidence
- negated_ratio, hedged_ratio, conditional_ratio
- distinct_docs, distinct_chunks
- all evidences, all source_doc_ids

---

## 11. Plan d'Implémentation

### Étape 1 : Mise à jour types.py
- [ ] Ajouter `CAUSES` et `PREVENTS` à `RelationType`
- [ ] Ajouter champs `type_confidence`, `alt_type`, `alt_type_confidence` à `RawAssertion`
- [ ] Ajouter `relation_subtype_raw` et `context_hint` (optionnels)

### Étape 2 : Nouveau prompt dans llm_relation_extractor.py
- [ ] Créer `RELATION_EXTRACTION_PROMPT_V3` (system + user)
- [ ] Implémenter `extract_relations_v3()` avec parsing JSON étendu
- [ ] Ajouter validation closed-world + anti-junk
- [ ] Extraire `context_hint` depuis l'evidence si conditionnel

### Étape 3 : Adapter raw_assertion_writer.py
- [ ] Stocker `relation_type` directement (pas juste `predicate_raw`)
- [ ] Stocker `type_confidence`, `alt_type`, `alt_type_confidence`
- [ ] Stocker `relation_subtype_raw`, `context_hint`

### Étape 4 : Enrichir consolidate_relations.py
- [ ] Supprimer mapping regex `PREDICATE_TYPE_PATTERNS`
- [ ] Rollup direct par `relation_type`
- [ ] Implémenter maturité épistémique (section 8.3)
- [ ] Implémenter règle AMBIGUOUS_TYPE (section 8.1)
- [ ] Implémenter quarantaine ASSOCIATED_WITH (section 8.2)
- [ ] Calculer negated_ratio, hedged_ratio, conditional_ratio

### Étape 5 : Matérialisation edges directs
- [ ] Créer script/fonction pour edges VALIDATED uniquement
- [ ] Exclure ASSOCIATED_WITH et AMBIGUOUS_TYPE
- [ ] Marquer edges comme "reconstruisibles" (pas de données uniques)

### Étape 6 : Tests et Validation
- [ ] Test extraction sur document AI Act
- [ ] Vérifier taux UNKNOWN < 10%
- [ ] Vérifier taux ASSOCIATED_WITH < 20%
- [ ] Valider navigation graph
- [ ] Tester cas limites (negated, hedged, conditional)

---

## 12. Métriques de Succès

| Métrique | Avant (V2) | Cible (V3) |
|----------|------------|------------|
| Taux UNKNOWN | 71% | < 5% |
| Taux ASSOCIATED_WITH | N/A | < 20% |
| Relations avec type explicite | 29% | > 95% |
| Écrasement info | N/A (résolu) | 0% |
| Contradictions capturées | ✅ | ✅ (+ CONFLICTING) |
| Incertitudes capturées | ✅ | ✅ (+ hedged_ratio) |
| Navigation directe | ❌ | ✅ (VALIDATED only) |

---

## 13. Références

### Documents Techniques
- `neo4j_writer.py` : Architecture V1 (edges directs, upsert winner-takes-all)
- `raw_assertion_writer.py` : Architecture V2 (RawAssertion, predicate_raw libre)
- `consolidate_relations.py` : Consolidation actuelle avec regex mapping
- `llm_relation_extractor.py` : Extracteur actuel (prompt V2)

### Analyses Collaboratives
- Analyse ChatGPT 2025-12-22 : Proposition architecture V3
- Stress-test ChatGPT 2025-12-22 : 6 challenges + parades
- Validation finale ChatGPT 2025-12-22 : 3 zones grises + principes UX

---

## 14. Historique des Révisions

| Date | Version | Changements |
|------|---------|-------------|
| 2025-12-22 | 1.0 | Création initiale (prompt V3, schema JSON, plan implémentation) |
| 2025-12-22 | 1.1 | Ajout garde-fous stress-test (AMBIGUOUS_TYPE, quarantaine ASSOCIATED_WITH, maturité épistémique) |
| 2025-12-22 | 1.2 | Ajout zones grises (consensus faux, context leakage, absence≠négation) |
| 2025-12-22 | 1.3 | Ajout principes UX (vue simplifiée vs experte) |
| 2025-12-22 | 1.4 | Ajout champs `relation_subtype_raw` et `context_hint` |

---

*Document Phase 2.10 OSMOSE - Architecture V3 Relations*
*Stress-testé et validé collaborativement avec ChatGPT*
