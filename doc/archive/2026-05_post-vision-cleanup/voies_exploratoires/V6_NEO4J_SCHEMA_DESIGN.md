# V6 — Design schéma Neo4j (extensions DSG V5.2)

**Statut** : DRAFT — design only, no DB writes until batch V6-P2.2 validé.
**Date** : 2026-05-14
**Auteur** : Fred / Claude
**Lié à** : `V6_REFONTE_INGESTION_PROPOSITION.md`, `runtime_v5/neo4j_dsg.py`

## 1. Principe

V6 ajoute un **second étage** au-dessus du DSG V5 existant. Le DSG V5 reste responsable de la **structure documentaire** (Document, Section, Table, hiérarchie HAS_SECTION/HAS_CHILD). V6 ajoute la **couche sémantique extraite** (entités, faits, procédures, contraintes, références, concept cards).

Les deux étages cohabitent dans le même graphe via la relation `EVIDENCE_IN` qui lie chaque item V6 à une section V5 existante. **Pas de duplication de texte** : seul le `evidence_section_id` est stocké côté V6, le texte verbatim reste dans `V5Section.text_snippet`.

### Cohérence avec DSG V5
- Multi-tenant strict via `tenant_id` partout (validé par `TenantQueryGuard`)
- Préfixe `V6` sur tous les labels (parallèle à `V5*`)
- Composite keys `(tenant_id, *_id)` pour unicité
- Idempotence : `IF NOT EXISTS` sur constraints/indexes, `MERGE` pour writes
- Pas de relation V5→V6 directe : les V6 items pointent vers V5 sections (one-way dependency)

## 2. Labels

| Label | Rôle | Source extraction |
|---|---|---|
| `V6Entity` | Entité nommée (code, person, tool, standard, ...) | `NamedEntity` |
| `V6Fact` | Assertion subject-predicate-object | `AtomicFact` |
| `V6Procedure` | Procédure (nom + objectif + steps) | `Procedure` |
| `V6ProcedureStep` | Une étape d'une procédure | `ProcedureStep` |
| `V6Constraint` | Règle/condition/exception | `Constraint` |
| `V6Reference` | Pointeur interne/externe | `Reference` |
| `V6ConceptCard` | Page agrégée par entité importante | `ConceptCard` (Phase 4) |

## 3. Constraints (unicité + multi-tenant)

```cypher
-- V6Entity : un entity_id unique par tenant
CREATE CONSTRAINT v6_entity_tenant_unique IF NOT EXISTS
FOR (e:V6Entity) REQUIRE (e.tenant_id, e.entity_id) IS UNIQUE;

-- V6Fact : un fact_id unique par tenant
CREATE CONSTRAINT v6_fact_tenant_unique IF NOT EXISTS
FOR (f:V6Fact) REQUIRE (f.tenant_id, f.fact_id) IS UNIQUE;

-- V6Procedure : un procedure_id unique par tenant
CREATE CONSTRAINT v6_procedure_tenant_unique IF NOT EXISTS
FOR (p:V6Procedure) REQUIRE (p.tenant_id, p.procedure_id) IS UNIQUE;

-- V6ProcedureStep : composite (procedure_id, step_number) par tenant
CREATE CONSTRAINT v6_step_tenant_unique IF NOT EXISTS
FOR (s:V6ProcedureStep) REQUIRE (s.tenant_id, s.procedure_id, s.step_number) IS UNIQUE;

-- V6Constraint : un constraint_id unique par tenant
CREATE CONSTRAINT v6_constraint_tenant_unique IF NOT EXISTS
FOR (c:V6Constraint) REQUIRE (c.tenant_id, c.constraint_id) IS UNIQUE;

-- V6Reference : un reference_id unique par tenant
CREATE CONSTRAINT v6_reference_tenant_unique IF NOT EXISTS
FOR (r:V6Reference) REQUIRE (r.tenant_id, r.reference_id) IS UNIQUE;

-- V6ConceptCard : un card_id unique par tenant
CREATE CONSTRAINT v6_card_tenant_unique IF NOT EXISTS
FOR (cc:V6ConceptCard) REQUIRE (cc.tenant_id, cc.card_id) IS UNIQUE;
```

## 4. Indexes (accès performant)

```cypher
-- Lookup entité par canonical_name (lookup_entity tool runtime)
CREATE INDEX v6_entity_canonical IF NOT EXISTS
FOR (e:V6Entity) ON (e.tenant_id, e.canonical_name);

-- Lookup entité par kind (filter par type)
CREATE INDEX v6_entity_kind IF NOT EXISTS
FOR (e:V6Entity) ON (e.tenant_id, e.entity_kind);

-- Fulltext search sur canonical_name + aliases (alias[] sérialisé en string)
CREATE FULLTEXT INDEX v6_entity_fulltext IF NOT EXISTS
FOR (e:V6Entity) ON EACH [e.canonical_name, e.aliases_joined];

-- Lookup facts par subject (find_facts_about)
CREATE INDEX v6_fact_subject IF NOT EXISTS
FOR (f:V6Fact) ON (f.tenant_id, f.subject_normalized);

-- Lookup facts par predicate (find_facts_with_predicate)
CREATE INDEX v6_fact_predicate IF NOT EXISTS
FOR (f:V6Fact) ON (f.tenant_id, f.predicate);

-- ConceptCard lookup par entity_canonical_name (get_concept_card)
CREATE INDEX v6_card_entity_name IF NOT EXISTS
FOR (cc:V6ConceptCard) ON (cc.tenant_id, cc.entity_canonical_name);

-- Constraints lookup par applies_to
CREATE FULLTEXT INDEX v6_constraint_fulltext IF NOT EXISTS
FOR (c:V6Constraint) ON EACH [c.statement, c.applies_to_joined];
```

## 5. Relations (graph topology)

```
(V6Entity)-[:EVIDENCE_IN]->(V5Section)         ─ une entité a une section evidence primaire
(V6Fact)-[:EVIDENCE_IN]->(V5Section)           ─ idem facts (l'evidence_text est verbatim)
(V6Fact)-[:ABOUT]->(V6Entity)                  ─ relie le fact à son entité subject (optional, best-effort)
(V6Fact)-[:OBJECT_ENTITY]->(V6Entity)          ─ idem pour l'objet (optional)
(V6Procedure)-[:EVIDENCE_IN]->(V5Section)
(V6Procedure)-[:HAS_STEP]->(V6ProcedureStep)   ─ relation ordonnée par step_number
(V6Procedure)-[:HAS_PREREQUISITE]->(V6Entity)  ─ optional, si prereq mentionne une entité
(V6Constraint)-[:EVIDENCE_IN]->(V5Section)
(V6Constraint)-[:APPLIES_TO]->(V6Entity)       ─ optional, si applies_to mentionne une entité
(V6Constraint)-[:APPLIES_TO_PROC]->(V6Procedure)
(V6Reference)-[:EVIDENCE_IN]->(V5Section)
(V6Reference)-[:POINTS_TO_SECTION]->(V5Section) ─ si target_kind=internal_section ET résolution OK
(V6Reference)-[:POINTS_TO_ENTITY]->(V6Entity)   ─ si la ref pointe vers une entité connue
(V6ConceptCard)-[:DESCRIBES]->(V6Entity)       ─ relation 1:1 (card_id ↔ entity_id)
(V6ConceptCard)-[:DERIVED_FROM]->(V5Section)   ─ multi-source, plusieurs sections
(V6ConceptCard)-[:KEY_FACT]->(V6Fact)          ─ facts inclus dans la card
```

**Note** : pas de relation directe V6 → V5Document. On passe toujours par V5Section, qui elle est rattachée à V5Document via `HAS_SECTION`. Single source of truth pour la provenance.

## 6. Propriétés par label

### V6Entity
```
{
  tenant_id: string (partition key)
  entity_id: string (e.g. "ent_a1b2c3...")  -- pydantic uuid4 12 chars
  canonical_name: string
  aliases: string[]                          -- array
  aliases_joined: string                     -- " | "-joined for fulltext index
  entity_kind: string                        -- code|person|place|organization|...
  domain_type: string | null                 -- Domain Pack specialization
  description: string | null
  doc_id: string                             -- pour debug/audit
  evidence_section_id: string
  created_at: datetime
  extractor_model: string                    -- audit (e.g. "deepseek-ai/DeepSeek-V3.1")
}
```

### V6Fact
```
{
  tenant_id: string
  fact_id: string
  subject: string                            -- verbatim
  subject_normalized: string                 -- lowercase, trimmed (for index)
  predicate: string                          -- lowercase
  object: string
  modality: string                           -- asserted|conditional|negated|...
  evidence_text: string                      -- verbatim citation
  doc_id: string
  evidence_section_id: string
  confidence: float
  created_at: datetime
  extractor_model: string
}
```

### V6Procedure
```
{
  tenant_id: string
  procedure_id: string
  name: string
  goal: string
  prerequisites: string[]
  prerequisites_joined: string
  doc_id: string
  evidence_section_id: string
  step_count: int                            -- denormalized for fast lookup
  created_at: datetime
  extractor_model: string
}
```

### V6ProcedureStep
```
{
  tenant_id: string
  procedure_id: string                       -- composite key partner
  step_number: int
  action: string
  notes: string | null
}
```

### V6Constraint
```
{
  tenant_id: string
  constraint_id: string
  constraint_type: string                    -- requirement|prohibition|exception|...
  statement: string
  applies_to: string[]
  applies_to_joined: string                  -- for fulltext
  doc_id: string
  evidence_section_id: string
  created_at: datetime
  extractor_model: string
}
```

### V6Reference
```
{
  tenant_id: string
  reference_id: string
  reference_text: string                     -- verbatim
  target_kind: string                        -- internal_section|external_document|...
  resolved_target: string | null             -- section_id or doc_id after resolution
  resolution_confidence: float | null        -- 0-1 if resolved
  doc_id: string
  evidence_section_id: string
  created_at: datetime
}
```

### V6ConceptCard (Phase 4)
```
{
  tenant_id: string
  card_id: string
  entity_id: string                          -- 1:1 with V6Entity
  entity_canonical_name: string
  summary: string                            -- 2000 chars max
  typical_usage: string | null
  key_facts: string                          -- JSON-serialized list
  procedures_associated: string[]
  constraints_associated: string[]
  references_associated: string[]
  related_entities: string[]
  contexts: string[]
  source_section_ids: string[]
  generated_at: datetime
  generator_model: string
}
```

## 7. Migration script (JSONL → Cypher)

**Module à créer** : `src/knowbase/runtime_v6/persistence/neo4j_loader.py`

**Pipeline** :
1. Lire le JSONL `benchmark/runs/v6_extractions/{doc_id}.jsonl` (1 ligne/section)
2. Pour chaque section, batch UNWIND insert :
   - 1 batch entities (MERGE par `(tenant_id, entity_id)`)
   - 1 batch facts (MERGE + create EVIDENCE_IN, ABOUT relationships)
   - 1 batch procedures (+ steps via UNWIND nested)
   - 1 batch constraints
   - 1 batch references
3. Post-pass : résoudre les ABOUT relations (matcher fact.subject_normalized → entity.canonical_name lowercase)
4. Post-pass : résoudre les references internal_section (matcher reference_text → V5Section.numbering ou title fuzzy)
5. Statistics : log nodes/relations créés par label

**Stratégie idempotence** :
- `MERGE` partout (re-runable)
- Pas de DELETE en batch loader (à faire séparément si re-extraction)
- Versioning : si re-extraction d'une section, on peut soit garder l'historique (ajouter `extraction_version`), soit overwrite. **Décision pour Phase 1** : overwrite (DELETE puis re-MERGE par section_id).

## 8. Tools runtime V6 (Phase 4)

Tools agentiques qui consommeront ce schema :

```python
# lookup_entity(canonical_name) → entity + facts + procedures associés
# get_concept_card(entity_canonical_name) → V6ConceptCard complet
# find_facts_about(entity_name, predicate=None) → list[V6Fact]
# find_procedure(goal_or_name) → V6Procedure with steps
# find_constraints_on(entity_or_procedure) → list[V6Constraint]
# resolve_reference(reference_text) → V6Reference + resolved target
```

Tous via `TenantQueryGuard` strict, comme runtime V5.

## 9. Multi-tenant — réutilisation V5

Le `TenantQueryGuard` existant valide TOUTES les queries Cypher V6 en injectant `tenant_id` dans les params et en refusant les requêtes sans filter. **Aucun nouveau code de garde** : V6 hérite des protections V5.

## 10. Migration path (déploiement)

1. **Local dev** : appliquer schema sur le Neo4j local (`./kw.ps1 start` puis script `setup_v6_schema.py`).
2. **Validation extraction** : v6_batch_extract.py doit avoir produit les JSONL pour les 3 docs SAP.
3. **Load test** : charger 1 doc dans Neo4j, vérifier counts par label.
4. **Audit qualité** : audit manuel sur 5 sections random après loading.
5. **Production** : si OK, créer tâche V6-P5 (réingestion 38 docs corpus complet).

## 11. Hors scope V6 Phase 1

- Versioning des extractions (extraction_version=v1/v2)
- TimeSeries des facts (validity_start/end) — peut être ajouté Phase 2 si besoin
- Cross-document relations (deduplication d'entités identiques entre docs) — Phase 2
- Embedding sur V6Fact pour semantic similarity — Phase 2

## 12. Décisions en attente

- [ ] **Naming convention** : `V6Entity` ou `Entity`? Choix `V6*` retenu pour cohabiter avec V5 sans collision et préparer migration future (V7?).
- [ ] **Singleton entities cross-section** : si la même entité (CGSADM) apparaît dans 5 sections, on crée 5 V6Entity ou 1? **Décision** : 5 distincts à l'extraction (1 par section), puis post-pass dedup via `canonical_name + entity_kind` peut créer un singleton (label `V6CanonicalEntity` + relation `INSTANCE_OF`). À traiter en V6-P4.
- [ ] **fact.subject = entity ?** : on essaie de matcher mais ce n'est pas obligatoire. Décision : best-effort, fallback string-only.

---

**Next step** : attendre fin batch V6-P2.2 (~60 min ETA), auditer 5 sections random, puis créer `runtime_v6/persistence/neo4j_loader.py` + script `setup_v6_schema.py` pour charger 1 doc en test.
