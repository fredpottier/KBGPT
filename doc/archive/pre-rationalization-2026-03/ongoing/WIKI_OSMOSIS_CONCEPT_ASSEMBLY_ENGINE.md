# Concept Assembly Engine — Architecture & Plan POC

**Version:** 1.2
**Date:** 2026-03-12
**Statut:** Design & POC Plan — compagnon de `WIKI_OSMOSIS_PROJECT_PRESCRIPTION.md`
**Contexte:** Raffinement de l'architecture Wikipedia OSMOSIS après analyse croisée (Claude + ChatGPT)
**Review:** Amendements v1.1 (pivot, evidence atomique, contradictions, scope_signature, scores). Vision 6 couches v1.2.

---

## 1. Constat : Pourquoi le KG seul ne suffit pas (et pourquoi ce n'est pas un problème)

Le document de prescription original suppose un modèle linéaire :

```
KG → Article Wikipedia
```

Or le KG actuel (Neo4j) n'est pas encore "encyclopédique" — il porte la **charpente** (entités canoniques, claims structurés, contradictions, axes temporels, facettes), mais pas la **chair** (formulations humaines, contexte local, nuances, détails fins).

Cette chair existe déjà dans **Qdrant** — 42 901 chunks vectoriels avec texte source, metadata structurelle, et axes de version.

### Le bon modèle est hybride

```
KG  → délimitation du sujet + sélection des preuves + structure + gouvernance
Qdrant → récupération du contexte textuel pertinent
KG + Qdrant → article généré sous contraintes de provenance
```

Le KG **décide** de quoi l'article doit parler.
Qdrant **fournit** la matière pour bien l'exprimer.
Le LLM **rédige** sous contraintes strictes (citations obligatoires, pas d'invention).

### Conséquence architecturale

On ne demande pas au graphe d'être "déjà Wikipedia". On lui demande d'être l'**orchestrateur fiable** d'une vue encyclopédique appuyée par le texte source.

Le risque principal n'est plus "le KG est trop pauvre" mais "sait-on orchestrer proprement la sélection et l'assemblage ?".

---

## 2. Architecture : Pipeline en 4 briques

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONCEPT ASSEMBLY ENGINE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐                      │
│  │   Brique 1   │    │     Brique 2     │                      │
│  │   Concept    │───>│  Evidence Pack   │                      │
│  │   Resolver   │    │    Builder       │                      │
│  │  (Neo4j)     │    │ (Neo4j + Qdrant) │                      │
│  └──────────────┘    └────────┬─────────┘                      │
│                               │                                 │
│                               ▼                                 │
│  ┌──────────────┐    ┌──────────────────┐                      │
│  │   Brique 3   │    │     Brique 4     │                      │
│  │   Section    │───>│   Constrained    │                      │
│  │   Planner    │    │   Generator      │                      │
│  │  (KG-driven) │    │   (LLM ancré)    │                      │
│  └──────────────┘    └──────────────────┘                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2b. Décision préalable : Pivot conceptuel de la vue Wiki

### Le problème

Dans OSMOSE, plusieurs niveaux d'abstraction coexistent pour représenter un "concept" :

| Nœud Neo4j | Count | Rôle |
|-------------|-------|------|
| `Entity` | 2 198 | Entité extraite par claim (granulaire, parfois bruitée) |
| `SubjectAnchor` | 131 | Sujet canonique d'un document (plus stable) |
| `ComparableSubject` | 62 | Pivot de comparaison inter-docs |
| `CanonicalEntity` | 0 | Couche de canonicalisation cross-doc (pas encore peuplée) |

### La décision

**Le pivot d'adressage pour la vue Wiki est `Entity`**, pour les raisons suivantes :

1. **C'est le seul nœud directement lié aux Claims** via `ABOUT` (5 824 relations)
2. **C'est le plus peuplé** (2 198 nœuds) — couverture maximale pour le POC
3. **Il porte un `name` et un `entity_type`** — suffisant pour résoudre et afficher
4. Les `SubjectAnchor` sont liés aux `DocumentContext`, pas aux Claims — utiles pour le scope mais pas comme pivot article
5. Les `ComparableSubject` et `CanonicalEntity` sont des couches supérieures qui pourront servir de **regroupement** dans une v2

### Conséquences

- Un "article Wiki" = 1 `Entity` (identifiée par `name` + `entity_type`)
- Les entités avec `name` très proches (ex: "DPAs" vs "Data Protection Authorities") doivent être détectées et regroupées → le `Concept Resolver` fait ce travail via les aliases
- À terme, quand `CanonicalEntity` sera peuplé, il pourra devenir le pivot de niveau supérieur (merge de plusieurs Entity sous un même article)

### Ce que le pivot Entity ne couvre PAS

- Les concepts qui n'ont pas d'Entity explicite mais sont présents dans les chunks Qdrant → hors scope POC
- Les sujets de niveau "document" (`SubjectAnchor`) qui ne sont pas des entités → pourront être des "portails" en v2

---

## 3. Brique 1 — Concept Resolver

### Rôle

À partir d'une entrée (nom de concept, entity_id, ou query textuelle), identifier et rassembler toutes les métadonnées structurelles depuis Neo4j.

### Input

```python
ConceptQuery:
  query: str                    # "Data Protection Authorities" ou entity_id
  tenant_id: str = "default"
```

### Output

```python
ResolvedConcept:
  entity_id: str                # ID Neo4j de l'entité
  canonical_name: str           # Nom canonique
  entity_type: str              # concept | actor | legal_term | standard | product
  aliases: List[str]            # Noms alternatifs trouvés dans le graphe

  # Claims liés
  claim_ids: List[str]          # Tous les claim_ids ABOUT cette entité
  claim_count: int
  claim_types: Dict[str, int]   # {"FACTUAL": 15, "PRESCRIPTIVE": 12, ...}

  # Couverture documentaire
  doc_ids: List[str]            # Documents distincts
  doc_count: int
  doc_titles: Dict[str, str]    # doc_id → titre

  # Facettes liées
  facet_ids: List[str]          # Facettes des claims (via BELONGS_TO_FACET)
  facet_domains: List[str]      # ex: ["compliance.gdpr", "security", "operations"]

  # Relations structurelles
  chains: List[ChainLink]       # Claims chaînés (CHAINS_TO) — évolution temporelle
  related_entities: List[RelatedEntity]  # Entités co-mentionnées dans les mêmes claims

  # Axes temporels
  axis_values: Dict[str, List[str]]  # ex: {"release_id": ["2022", "2023", "2024"]}
```

### Sources Neo4j

```cypher
-- Entité + claims
MATCH (c:Claim)-[:ABOUT]->(e:Entity {name: $name})
OPTIONAL MATCH (c)-[:BELONGS_TO_FACET]->(f:Facet)
OPTIONAL MATCH (c)-[:CHAINS_TO]->(c2:Claim)
RETURN e, c, f, c2

-- Documents
MATCH (c:Claim)-[:ABOUT]->(e:Entity {name: $name})
MATCH (dc:DocumentContext {doc_id: c.doc_id})
RETURN DISTINCT dc.doc_id, dc.title, dc.primary_subject
```

### Briques existantes réutilisables

- `Entity` model (`src/knowbase/claimfirst/models/entity.py`)
- `Claim` model + `ABOUT` relationship
- `Facet` model + `BELONGS_TO_FACET` relationship
- `DocumentContext` model + `axis_values`

---

## 4. Brique 2 — Evidence Pack Builder (BRIQUE CRITIQUE)

### Rôle

Construire un paquet de preuves structuré combinant KG (claims, contradictions, évolution) et Qdrant (chunks textuels). C'est **la brique qui fait ou défait la qualité** de l'article final.

### Input

```python
ResolvedConcept  # output de Brique 1
```

### Output : Architecture à 3 niveaux

L'EvidencePack n'est pas un blob monolithique. Il est structuré en **3 niveaux** pour permettre le debug et l'auditabilité :

```
Niveau 1 : EvidenceUnit[]     — atomes normalisés (1 claim ou 1 chunk = 1 unit)
Niveau 2 : EvidencePack       — agrégation structurée (timeline, contradictions, related)
Niveau 3 : ArticlePlan        — assignation evidence → sections (Brique 3)
```

#### Niveau 1 : `EvidenceUnit` (atome de preuve)

Chaque preuve, qu'elle vienne du KG ou de Qdrant, est normalisée en `EvidenceUnit` :

```python
EvidenceUnit:
  unit_id: str                  # claim_id ou chunk_id
  source_type: str              # "claim" | "chunk"
  text: str                     # Contenu textuel

  # Provenance
  doc_id: str
  doc_title: str
  section_id: Optional[str]
  page_no: Optional[int]

  # Classification
  rhetorical_role: str          # "definition" | "rule" | "exception" | "example" | "mention" | "context"
  claim_type: Optional[str]     # DEFINITIONAL | PRESCRIPTIVE | FACTUAL | PERMISSIVE (claims only)
  facet_domains: List[str]      # Facettes associées

  # Scope signature (amendement ChatGPT)
  scope_signature:
    doc_type: str               # "regulation" | "annual_report" | "guideline" | "technical_doc"
    axis_values: Dict[str, str] # {"release_id": "2023", "version": "1.0"}
    generality_level: str       # "universal" | "corpus_wide" | "doc_specific" | "section_local"

  # Scoring
  relevance_score: float        # 0-1, pertinence par rapport au concept
  weight: float                 # Poids dans le pack (après plafonnement par doc)
```

Le `rhetorical_role` est attribué par heuristiques :
- Claims DEFINITIONAL → `"definition"`
- Claims PRESCRIPTIVE → `"rule"`
- Claims avec QUALIFIES → `"exception"`
- Chunks de la première section d'un doc → candidats `"definition"` (heuristique de secours si pas de claim DEFINITIONAL)
- Sinon → `"mention"` ou `"context"` selon le score de pertinence

Le `scope_signature` permet de détecter les mélanges de portée : un evidence unit `generality_level=section_local` ne doit pas être présenté comme une règle universelle.

#### Niveau 2 : `EvidencePack` (agrégation structurée)

```json
{
  "concept": {
    "canonical_name": "Data Protection Authorities (DPAs)",
    "entity_type": "actor",
    "aliases": ["DPAs", "supervisory authorities"]
  },

  "evidence_units": [
    {
      "unit_id": "claim_xxx",
      "source_type": "claim",
      "text": "DPAs are independent bodies that...",
      "doc_id": "Full_GDPR_Text_bd84e63f",
      "doc_title": "GDPR Full Text",
      "rhetorical_role": "definition",
      "claim_type": "DEFINITIONAL",
      "facet_domains": ["compliance.gdpr"],
      "scope_signature": {
        "doc_type": "regulation",
        "axis_values": {},
        "generality_level": "universal"
      },
      "relevance_score": 0.95,
      "weight": 1.0
    },
    {
      "unit_id": "chunk_default:edpb_2024:texts/42",
      "source_type": "chunk",
      "text": "Each Member State shall provide for one or more independent public authorities...",
      "doc_id": "Full_GDPR_Text_bd84e63f",
      "doc_title": "GDPR Full Text",
      "section_id": "sec_chapter_vi",
      "page_no": 45,
      "rhetorical_role": "definition",
      "facet_domains": ["compliance.gdpr"],
      "scope_signature": {
        "doc_type": "regulation",
        "axis_values": {},
        "generality_level": "universal"
      },
      "relevance_score": 0.91,
      "weight": 0.8
    }
  ],

  "temporal_evolution": {
    "has_evolution": true,
    "axis_key": "release_id",
    "timeline": [
      {
        "axis_value": "2022",
        "doc_id": "edpb_2023_annual_report_2022_90286474",
        "unit_ids": ["claim_id_1", "claim_id_2"],
        "summary_chunk_id": "chunk_xxx"
      },
      {
        "axis_value": "2023",
        "doc_id": "edpb_2024_annual_report_2023_6f1d7975",
        "unit_ids": ["claim_id_3", "claim_id_4"],
        "changes": [
          {"type": "ADDED", "unit_id": "claim_zzz"}
        ]
      }
    ]
  },

  "confirmed_conflicts": [
    {
      "unit_a_id": "claim_aaa",
      "unit_b_id": "claim_bbb",
      "conflict_type": "VALUE_MISMATCH",
      "formal_verdict": "INCOMPATIBLE",
      "confidence": 0.9
    }
  ],

  "candidate_tensions": [
    {
      "unit_a_id": "claim_ccc",
      "unit_b_id": "claim_ddd",
      "conflict_type": "VALUE_MISMATCH",
      "formal_verdict": "NEED_LLM",
      "note": "Tension possible — nécessite arbitrage humain ou LLM"
    }
  ],

  "related_concepts": [
    {
      "entity_name": "EDPB",
      "entity_type": "actor",
      "co_occurrence_count": 18,
      "supporting_unit_ids": ["claim_id_5", "claim_id_6", "chunk_id_7"]
    },
    {
      "entity_name": "GDPR",
      "entity_type": "legal_term",
      "co_occurrence_count": 35,
      "supporting_unit_ids": ["claim_id_8", "chunk_id_9"]
    }
  ],

  "source_index": [
    {
      "doc_id": "Full_GDPR_Text_bd84e63f",
      "doc_title": "GDPR Full Text",
      "unit_count": 8,
      "doc_type": "regulation",
      "contribution_pct": 0.19
    },
    {
      "doc_id": "edpb_2024_annual_report_2023_6f1d7975",
      "doc_title": "EDPB Annual Report 2023",
      "unit_count": 25,
      "doc_type": "annual_report",
      "contribution_pct": 0.60
    }
  ],

  "quality_signals": {
    "total_units": 42,
    "claim_units": 30,
    "chunk_units": 12,
    "doc_count": 4,
    "type_diversity": 3,
    "has_definition": true,
    "has_temporal_data": true,
    "confirmed_conflict_count": 0,
    "candidate_tension_count": 1,
    "coverage_score": 0.82,
    "coherence_risk_score": 0.15
  }
}
```

**Deux scores distincts** (amendement ChatGPT) :
- `coverage_score` (0-1) : richesse du pack — nb claims, nb docs, présence définition, présence temporal
- `coherence_risk_score` (0-1) : risque de synthèse bancale — sur-représentation d'un doc, mélanges de scope, tensions non résolues. **Plus c'est haut, plus c'est risqué.**

**Contradictions en deux niveaux** (amendement ChatGPT) :
- `confirmed_conflicts` : verdicts formellement forts (INCOMPATIBLE après les 4 gates). Seuls ceux-ci sont exposés en UI comme contradictions établies.
- `candidate_tensions` : verdicts NEED_LLM. Affichés dans un bloc séparé "Tensions à confirmer", jamais présentés comme faits établis.

### Algorithme de construction

```
1. CLAIMS STRUCTURANTS → EvidenceUnits (Neo4j)
   ├── MATCH (c:Claim)-[:ABOUT]->(e:Entity {name: $name})
   ├── Pour chaque claim → créer EvidenceUnit(source_type="claim")
   ├── Assigner rhetorical_role par heuristique :
   │     DEFINITIONAL → "definition"
   │     PRESCRIPTIVE → "rule"
   │     FACTUAL → "mention"
   │     claim avec QUALIFIES → "exception"
   ├── Construire scope_signature depuis DocumentContext du doc_id
   └── Limiter à ~50 claims max (top par facette + type)

2. CHUNKS DÉFINITOIRES → EvidenceUnits (Qdrant)
   ├── Query vectorielle : embedding(canonical_name + "definition role scope")
   ├── Filtrer par doc_ids du ResolvedConcept (pas de recherche globale)
   ├── Top 10-15 chunks par pertinence
   ├── Pour chaque chunk → créer EvidenceUnit(source_type="chunk")
   ├── Heuristique de secours "definitionality" :
   │     Si aucun claim DEFINITIONAL trouvé en étape 1,
   │     les chunks de la 1ère section du doc principal
   │     avec score > 0.85 sont promus rhetorical_role="definition"
   └── Construire scope_signature depuis metadata Qdrant (axis_release_id, doc_type)

3. PLAFONNEMENT PAR DOCUMENT
   ├── Calculer contribution_pct par doc_id
   ├── Si un doc > 40% des units → réduire ses poids (weight)
   └── Recalculer les weights pour rééquilibrer

4. ÉVOLUTION TEMPORELLE (Neo4j)
   ├── Trouver les claims avec CHAINS_TO
   ├── Vérifier que les claims chaînés partagent Subject + Predicate (fingerprint SPO)
   ├── Grouper par axis_value (release_id ou version)
   ├── Détecter ADDED / REMOVED / MODIFIED / UNCHANGED
   └── Référencer par unit_ids (pas de duplication de texte)

5. CONTRADICTIONS — 2 niveaux (Neo4j)
   ├── Claims du même concept avec ClaimKey compatible
   ├── Appliquer les 4 gates de value_contradicts.py
   ├── Séparer :
   │     INCOMPATIBLE → confirmed_conflicts (exposables en UI)
   │     NEED_LLM → candidate_tensions (bloc "à confirmer", jamais présenté comme fait)
   └── Préférer l'absence à la fausse alarme (North Star OSMOSE)

6. CONCEPTS LIÉS (Neo4j) — prudence co-occurrence
   ├── Entités co-mentionnées dans les mêmes claims
   ├── Compter co-occurrences
   ├── Top 10 par fréquence
   ├── PAS de phrase relationnelle générée (risque pseudo-sémantique)
   │     → seulement : entity_name, entity_type, co_occurrence_count, supporting_unit_ids
   └── La description de la relation peut être ajoutée en v2 si appui solide

7. SCOPE / APPLICABILITÉ → scope_signature par unit
   ├── Chaque EvidenceUnit porte sa propre scope_signature
   ├── Agrégation au niveau pack : facettes, doc_types, geographic_scope
   └── Calcul de coherence_risk_score basé sur la variance des scope_signatures

8. QUALITY SIGNALS — 2 scores distincts
   ├── coverage_score : nb units, nb docs, diversité types, présence définition, temporal
   ├── coherence_risk_score : sur-représentation doc, variance scope_signatures, tensions
   └── Pas de score unique "qualité article" (mélange couverture et risque)
```

### Dangers à éviter (règles de sélection)

| Danger | Mitigation |
|--------|------------|
| **Mélange de scope** — chunk d'un doc local promu en règle générale | `scope_signature.generality_level` sur chaque EvidenceUnit. Le Section Planner regroupe par scope. |
| **Sur-représentation d'un doc** — 1 doc avec 80% des claims biaise l'article | Plafond par document : max 40% des units. Étape 3 de l'algorithme (recalcul weights). |
| **Faux positifs temporels** — CHAINS_TO sur claims non comparables | Vérifier que les claims chaînés partagent le même Subject + Predicate (fingerprint SPO). |
| **Chunk hors sujet** — embedding match sur un mot mais contexte différent | Filtrer Qdrant par `doc_id` IN (docs du ResolvedConcept), pas recherche globale. |
| **Confusion définition / exemple** — exemple local traité comme définition | Prioriser claim_type DEFINITIONAL. Chunks notés `kind=NARRATIVE_TEXT` > tables/figures pour les définitions. |

### Briques existantes réutilisables

| Composant existant | Utilisation dans Evidence Pack Builder |
|---|---|
| `value_contradicts.py` | Détection formelle contradictions (4 gates) |
| `evolution_detector.py` | Détection ADDED/REMOVED/MODIFIED/UNCHANGED |
| `temporal_query_engine.py` | Timeline, "since when", "still applicable" |
| `search.py` (service) | Embedding + query Qdrant |
| `qdrant_client.py` | Client Qdrant avec filtres `doc_id`, `axis_release_id` |
| `applicability_axis.py` | Axes temporels, ordering confidence |
| `facet_matcher.py` | Affectation claims → facettes |
| `facet_registry.py` | Facettes validées du corpus |

---

## 5. Brique 3 — Section Planner

### Rôle

Dériver automatiquement la structure de l'article depuis l'evidence pack, **sans LLM**. Le plan de sections est déterministe, basé sur ce qui est disponible.

### Règles de planification

```python
SECTION_RULES = [
    # (section_type, titre, condition d'inclusion)
    ("overview",        "Vue d'ensemble",              ALWAYS),
    ("definition",      "Définition",                  IF has_definitional_claims),
    ("key_properties",  "Caractéristiques principales", IF claim_count >= 5),
    ("obligations",     "Obligations et prescriptions", IF has_prescriptive_claims),
    ("temporal",        "Évolution temporelle",         IF has_temporal_data),
    ("contradictions",  "Contradictions détectées",     IF confirmed_conflict_count > 0),
    ("tensions",        "Tensions à confirmer",         IF candidate_tension_count > 0),
    ("scope",           "Portée et applicabilité",      IF facet_count >= 2),
    ("related",         "Concepts liés",                IF related_count >= 2),
    ("sources",         "Sources documentaires",        ALWAYS),
]
```

### Output

```python
ArticlePlan:
  title: str
  slug: str
  sections: List[PlannedSection]
    # Chaque PlannedSection contient :
    #   section_type: str
    #   title: str
    #   unit_ids: List[str]       # EvidenceUnit IDs assignés à cette section
    #   generation_instructions: str  # consignes pour le LLM
```

### Assignation evidence → sections

- **overview** : units avec `rhetorical_role` in ("definition", "rule"), top 3 par weight
- **definition** : tous les units avec `rhetorical_role="definition"` (claims DEFINITIONAL + chunks définitoires de secours)
- **key_properties** : units `rhetorical_role` in ("mention", "context") groupés par `facet_domains`
- **obligations** : units avec `claim_type` in (PRESCRIPTIVE, PERMISSIVE)
- **temporal** : units référencés dans `temporal_evolution.timeline[].unit_ids`
- **contradictions** : units référencés dans `confirmed_conflicts` uniquement
- **tensions** : units référencés dans `candidate_tensions` (bloc séparé, ton prudent)
- **scope** : agrégation des `scope_signature` des units
- **related** : `related_concepts` avec `supporting_unit_ids`
- **sources** : `source_index` complet

---

## 6. Brique 4 — Constrained Article Generator

### Rôle

Le LLM rédige **section par section**, sous contraintes strictes de provenance.

### Principes non-négociables

1. **Chaque phrase doit citer au moins 1 source** (claim_id ou chunk_id)
2. **Interdit d'inventer** — si l'evidence est insuffisante, le dire explicitement
3. **Signaler les zones incertaines** — "selon [source A]... mais [source B] indique..."
4. **Pas de généralisation abusive** — si un fait vient d'un seul doc, le préciser
5. **Respecter la granularité** — ne pas fusionner des claims de scopes différents

### Prompt pattern (par section)

```
Tu rédiges la section "{section_title}" d'un article encyclopédique interne.

RÈGLES STRICTES :
- Chaque affirmation doit citer sa source entre crochets : [doc_title, claim_id]
- N'invente RIEN. Si tu n'as pas de preuve, écris "Aucune information disponible."
- Si des sources se contredisent, présente les deux versions.
- Ne généralise pas un fait local en règle universelle.

EVIDENCE DISPONIBLE :
{evidence_json pour cette section}

FORMAT DE SORTIE :
{
  "content": "texte rédigé avec [citations]",
  "citations_used": ["claim_id_1", "chunk_id_2", ...],
  "confidence": 0.0-1.0,
  "gaps": ["aspects non couverts par les preuves"]
}
```

### TaskType LLM

- `METADATA_EXTRACTION` — structured JSON output
- Max ~2000 tokens par section
- 1 appel LLM par section (7-9 sections = 7-9 appels par article)
- Coût estimé : ~$0.02/article (GPT-4o-mini) ou ~$0.10/article (Claude Sonnet)

---

## 7. Inventaire de l'existant — État du KG au 2026-03-11

### Nœuds

| Label | Count | Rôle dans le Concept Assembly Engine |
|-------|-------|--------------------------------------|
| Claim | 7 378 | **Evidence primaire** — texte factuel ancré |
| Entity | 2 198 | **Concepts cibles** — sujets des articles |
| ClaimCluster | 792 | Regroupement thématique des claims |
| QuestionSignature | 152 | Questions implicites (enrichissement futur) |
| SubjectAnchor | 131 | Sujets canoniques des documents |
| DocumentContext | 76 | Contexte applicatif (axes, scope) |
| ComparableSubject | 62 | Pivots de comparaison inter-docs |
| Facet | 25 | Axes de navigation (migration v2 faite) |
| ApplicabilityAxis | 3 | Dimensions temporelles |

### Relations clés

| Relation | Count | Utilisation |
|----------|-------|-------------|
| `ABOUT` (Claim→Entity) | 5 824 | **Cœur** — lie claims aux concepts |
| `BELONGS_TO_FACET` (Claim→Facet) | 3 999 | Classification thématique |
| `IN_CLUSTER` (Claim→ClaimCluster) | 2 406 | Regroupement |
| `CHAINS_TO` (Claim→Claim) | 366 | **Évolution temporelle** |
| `ABOUT_SUBJECT` (DocumentContext→SubjectAnchor) | 166 | Sujet principal des docs |
| `EXTRACTED_FROM` (Claim→QuestionSignature) | 152 | Questions implicites |
| `QUALIFIES` (Claim→Claim) | 80 | Précisions / exceptions |
| `REFINES` (Claim→Claim) | 30 | Affinements |

### Qdrant

| Collection | Points | Dimensions | Champs payload clés |
|------------|--------|------------|---------------------|
| `knowbase_chunks_v2` | 42 901 | 1024 (cosine) | `text`, `doc_id`, `section_id`, `page_no`, `axis_release_id`, `axis_version`, `kind` |

### Concepts les plus riches (candidats POC)

| Entité | Type | Claims | Docs | Types claims | Chaînes | Intérêt POC |
|--------|------|--------|------|-------------|---------|-------------|
| **Data Protection Authorities (DPAs)** | actor | 42 | 4 | FACTUAL, PRESCRIPTIVE | oui | Cross-doc fort, rôle normatif |
| **controller** | concept | 59 | 2 | FACT, PRESC, DEF, PERM | oui (6) | Richesse sémantique, 4 types |
| **EDPB** | actor | 24 | 5 | 3 types | oui (12) | Max cross-doc, évolution annuelle |
| **EU AI Act** | legal_term | 24 | 2 | FACT, DEF, PRESC | non | Sujet d'actualité |
| **machine learning (ML) techniques** | concept | 21 | 3 | DEF, FACT | non | Concept technique, 3 docs |

---

## 8. Plan POC — Séquence en 4 étapes

### Objectif

Valider empiriquement que le couple KG + Qdrant actuel suffit pour produire un evidence pack sain, et par extension un article Wikipedia crédible.

**Question à trancher** : *"Savons-nous transformer de manière contrôlée cette richesse hybride en article fiable, lisible et prouvable ?"*

### Étape A — Sélection des 2 concepts cibles

| # | Concept | Raison |
|---|---------|--------|
| 1 | **EDPB** | Max cross-doc (5 docs), évolution annuelle (rapports 2022/2023/2024), chaînes temporelles (12), acteur central — bon test normatif/évolutif |
| 2 | **controller** | Max claims (59), 4 types de claims, 6 chaînes temporelles, concept fondamental GDPR — bon test richesse sémantique/définitoire |

### Étape B — Evidence Pack Only (pas de génération)

**Script** : `app/scripts/poc_evidence_pack.py`

Pour chaque concept :
1. **Concept Resolver** : requêtes Neo4j → `ResolvedConcept`
2. **Evidence Pack Builder** :
   - Claims structurants depuis Neo4j (groupés par type + facette)
   - Chunks définitoires depuis Qdrant (top 15 par semantic search filtrée)
   - Chaînes temporelles (CHAINS_TO, groupées par axis_value)
   - Contradictions (value_contradicts gates)
   - Concepts liés (co-occurrence dans les mêmes claims)
   - Index des sources
3. **Output** : `data/poc_wiki/evidence_pack_{concept}.json`

**Pas de LLM à cette étape.**

### Étape C — Revue humaine de l'evidence pack

Critères d'évaluation :

| Question | Bon signe | Mauvais signe |
|----------|-----------|---------------|
| Le cœur du sujet est-il capturé ? | Claims DEFINITIONAL pertinents, chunks définitoires riches | Manque de définition, que des mentions périphériques |
| Les scopes sont-ils mélangés ? | Chaque evidence porte son doc_id, pas de fusion abusive | Chunks de docs différents mélangés sans distinction |
| Un chunk local est-il sur-promu ? | Distinction claire entre "selon [GDPR]" et "selon [rapport interne]" | Un exemple local présenté comme règle générale |
| La timeline est-elle propre ? | Progression ordonnée, axis_values cohérents | Dates mélangées, claims non comparables chaînés |
| Les contradictions sont-elles vraies ? | Divergence factuelle vérifiable entre 2 sources | Faux positif dû à un scope différent |

### Étape D — Génération section par section

Seulement si l'étape C est validée :

1. **Section Planner** → dériver le plan depuis l'evidence pack
2. **Constrained Generator** → LLM par section, citations obligatoires
3. **Output** : `data/poc_wiki/article_{concept}.json` + rendu Markdown
4. **Évaluation** : provenance traçable ? Pas d'invention ? Contradictions bien présentées ?

### Livrables du POC

```
data/poc_wiki/
├── evidence_pack_edpb.json           # Pack brut
├── evidence_pack_controller.json     # Pack brut
├── article_plan_edpb.json            # Plan de sections
├── article_plan_controller.json      # Plan de sections
├── article_edpb.json                 # Article généré (étape D)
├── article_edpb.md                   # Rendu Markdown lisible
├── article_controller.json           # Article généré (étape D)
└── article_controller.md             # Rendu Markdown lisible
```

---

## 9. Décisions architecturales

| Décision | Choix | Raison |
|----------|-------|--------|
| **Stockage articles** | Générés dynamiquement, pas de nœuds WikiArticle en v1 | Éviter la désynchronisation KG/articles. Les articles sont des **vues**. |
| **Cache** | Redis avec TTL 1h, invalidation sur update KG | Perf lecture sans risque de stale data |
| **Éditeur/Annotations** | Hors scope POC et v1 | Valider d'abord la lecture seule. L'édition collaborative est prématurée. |
| **Génération** | Section par section, pas monolithique | Meilleur contrôle de la provenance, parallélisable |
| **Evidence scope** | Filtré par doc_ids du concept, pas recherche globale Qdrant | Éviter les chunks hors sujet qui matchent sur un mot |
| **Plafond par doc** | Max 40% des claims d'un evidence pack par doc | Éviter la sur-représentation d'une source unique |

---

## 10. Fichiers à créer

| Fichier | Rôle | ~Lignes |
|---------|------|---------|
| `src/knowbase/wiki/__init__.py` | Module wiki | 5 |
| `src/knowbase/wiki/concept_resolver.py` | Brique 1 — Résolution concept | ~150 |
| `src/knowbase/wiki/evidence_pack_builder.py` | Brique 2 — Construction evidence pack | ~400 |
| `src/knowbase/wiki/section_planner.py` | Brique 3 — Plan de sections | ~120 |
| `src/knowbase/wiki/constrained_generator.py` | Brique 4 — Génération LLM contrainte | ~200 |
| `src/knowbase/wiki/models.py` | Modèles Pydantic (EvidencePack, ArticlePlan, etc.) | ~250 |
| `app/scripts/poc_evidence_pack.py` | Script POC — génère evidence packs | ~200 |
| `tests/wiki/test_concept_resolver.py` | Tests Brique 1 | ~100 |
| `tests/wiki/test_evidence_pack_builder.py` | Tests Brique 2 | ~200 |

**Total estimé** : ~1 625 lignes, 9 fichiers

---

## 11. Séquence d'implémentation

```
Phase 1 — POC Evidence Pack (prioritaire)
  1. models.py           — Modèles de données
  2. concept_resolver.py  — Résolution Neo4j
  3. evidence_pack_builder.py — Construction hybride KG+Qdrant
  4. poc_evidence_pack.py — Script pour générer les 2 packs
  → REVUE HUMAINE → Go/No-Go

Phase 2 — Génération (si Phase 1 validée)
  5. section_planner.py   — Planification sections
  6. constrained_generator.py — Génération LLM
  → Articles POC générés → Évaluation

Phase 3 — Intégration (si Phase 2 validée)
  7. API endpoints /api/wiki/*
  8. Frontend /wiki/* (Next.js)
  9. Cache Redis + invalidation
```

**Go/No-Go après Phase 1** : Si l'evidence pack est sain sur les 2 concepts, on continue. Sinon, on identifie les faiblesses (facettes ? scope ? sélection ?) et on renforce avant de générer.

---

## 12. Vision stratégique : OSMOSE en 6 couches

### Repositionnement

Le Concept Assembly Engine n'est pas un module isolé. Il révèle l'architecture réelle d'OSMOSE, qui s'organise naturellement en **6 couches** — dont 3 sont déjà opérationnelles :

```
┌─────────────────────────────────────────────────────────────────┐
│            OSMOSE — Knowledge Composition Engine                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Couche 1 — INGESTION DOCUMENTAIRE              ✅ FAIT │   │
│  │  Docling + pipelines PDF/PPTX/DOCX/Excel                │   │
│  │  → unités documentaires traçables, chunks, metadata      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Couche 2 — STRUCTURATION SÉMANTIQUE             ✅ FAIT │   │
│  │  ClaimFirst pipeline : claims, entities, axes,           │   │
│  │  facettes, contradictions, QuestionSignatures            │   │
│  │  → savoir atomisé, gouvernable, auditable                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Couche 3 — PERSISTANCE DUALE                    ✅ FAIT │   │
│  │  3A. Neo4j : structure, canonicalisation, liens,         │   │
│  │      comparabilité, temporalité, gouvernance             │   │
│  │  3B. Qdrant : richesse textuelle, contexte local,       │   │
│  │      formulations, passages détaillés                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Couche 4 — ASSEMBLAGE DE CONNAISSANCE       🔨 EN COURS │   │
│  │  Concept Assembly Engine :                               │   │
│  │    Concept Resolver → Evidence Pack Builder               │   │
│  │    → Section Planner → validateurs de scope              │   │
│  │  → paquets de preuves structurés, auditable              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Couche 5 — GÉNÉRATION CONTRAINTE              📋 PLANIFIÉ │   │
│  │  LLM comme moteur de formulation (pas source de vérité)  │   │
│  │  Sorties : articles wiki, synthèses, timelines,          │   │
│  │  notes d'analyse, comparaisons, réponses argumentées     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              ↓                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Couche 6 — NAVIGATION & INSIGHT               📋 FUTUR  │   │
│  │  Paysages conceptuels, graphes de contradictions,        │   │
│  │  timelines multi-sources, cartes d'applicabilité,        │   │
│  │  points de tension documentaire                          │   │
│  │  → knowledge observability                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Le centre de gravité

Le centre de gravité d'OSMOSE n'est ni le KG, ni le LLM, ni l'UI. C'est la **couche 4 — l'assemblage de connaissance**. C'est elle qui fait le pont entre vérité structurée, richesse documentaire, et exploitation humaine.

### Ce que ça change

| Avant | Maintenant |
|-------|------------|
| OSMOSE = Knowledge Graph + RAG | OSMOSE = **Knowledge Composition Engine** |
| Le wiki est le produit | Le wiki est **une projection** parmi d'autres |
| Le LLM est le cerveau | Le LLM est **un moteur de formulation** contraint |
| Le graphe est la fin | Le graphe est **un des deux piliers** de la persistance |

### Projections possibles depuis la couche 4

Une fois l'assemblage de connaissance opérationnel, les sorties ne se limitent pas aux articles wiki :

| Projection | Description | Brique requise |
|------------|-------------|----------------|
| **Article Wiki** | Vue encyclopédique d'un concept avec provenance | Constrained Generator (Brique 4) |
| **Synthèse comparative** | Diff entre 2 versions d'un concept | Evidence Pack + diff temporel |
| **Rapport de conformité** | Claims prescriptifs par facette, couverture par doc | Evidence Pack filtré par claim_type |
| **Carte de contradictions** | Tensions détectées dans le corpus, par concept | confirmed_conflicts + candidate_tensions |
| **Timeline documentaire** | Évolution temporelle d'un sujet multi-sources | temporal_evolution du pack |
| **Réponse argumentée** | Réponse à une question avec citations prouvables | Evidence Pack + génération ciblée |
| **Audit de couverture** | Quels concepts sont bien/mal documentés | quality_signals de tous les packs |

### Priorité immédiate

Cette vision est la cible à moyen terme. La priorité **maintenant** reste le POC :

```
Couche 4 (Evidence Pack sur 2 concepts) → Revue humaine → Go/No-Go
```

La vision 6 couches confirme que ce POC est le bon investissement : si la couche 4 fonctionne, toutes les projections deviennent accessibles.

---

## Changelog

| Date | Version | Changements |
|------|---------|-------------|
| 2026-03-11 | 1.0 | Création — architecture hybride KG+Qdrant, plan POC 4 étapes |
| 2026-03-11 | 1.1 | Amendements review ChatGPT : (1) pivot conceptuel Entity verrouillé, (2) EvidenceUnit atomique + scope_signature, (3) contradictions 2 niveaux (confirmed/candidate), (4) related_concepts sans phrase relationnelle, (5) 2 scores séparés coverage/coherence_risk, (6) heuristique secours definitionality |
| 2026-03-12 | 1.2 | Vision stratégique 6 couches — repositionnement OSMOSE comme Knowledge Composition Engine. Table des projections possibles. Confirmation que la couche 4 (assemblage) est le centre de gravité et la priorité immédiate. |
