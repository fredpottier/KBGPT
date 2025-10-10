# KnowBase Promise Alignment Report
## 1. Context and Value Proposition

- **Ambition**: position KnowBase as the semantic layer that "knows where to know", understands every document, tracks versions, and guarantees sourced, reliable answers without creating a new silo.
- **Game-changer promise**:
  - **Instant access to knowledge**: deliver the exact answer ("Budget 2024 for project Alpha is on page 5 of the 12/10/2023 minutes") instead of a list of files.
  - **Valorise the existing information estate**: connect SharePoint, Confluence, CRM, intranet, and local folders at the content level so that every deliverable stays discoverable and reusable.
  - **Accelerate informed decisions**: provide trustworthy, traceable insights (what, where, who, when) that compress hours of search into seconds and build confidence in the recommended action.
- **Key claims in the pitch**: extract meaning from every format (pptx, pdf, docx, xlsx, intranet pages), maintain version histories, understand intent in natural language, and act as a trusted guide rather than a keyword search box.

## 2. Capabilities Already Delivered
- **Rich PPTX ingestion** (`src/knowbase/ingestion/pipelines/pptx_pipeline.py`): unified prompt extracts concepts, facts, entities, relations, plus deck-wide metadata.
- **Storage layers**:
  - Qdrant vectors with contextual payload (solutions, version, deck summary, etc.).
  - Neo4j for entities, relations, facts (with governance) and episodes (document groupings).
- **Facts governance**: facts stored as first-class nodes with proposed/approved workflow, numeric conflict detection, and timeline queries.
- **Entity normalisation**: `KnowledgeGraphService.get_or_create_entity` combined with `EntityNormalizer` to align outputs with curated catalogues.
- **Where this already serves the promise**:
  - The ingestion + Qdrant combo gives a first pass at â€œinstant accessâ€.
  - Facts governance provides the seed of traceability needed for trusted answers.
  - Entity normalisation begins to declutter silos, albeit with manual catalogues.

## 3. Gaps Versus the Promise (with detail)

> The sections below highlight where the current implementation falls short of the â€œknow where to knowâ€ vision, and what architectural work is required to close the gap.

### 3.1 Document modelling is too shallow
- **What we see**:
  - Qdrant payload keeps `source_date`, `version`, `file_uid`, but Neo4j episodes only store JSON arrays (`chunk_ids`, `fact_uuids`, ...).
  - There is no structural link between successive documents on the same concept; a refreshed report neither references nor supersedes the former one.
- **Why it matters** (promise impact):
  - Prevents the system from acting as the go-to index that knows *where* the authoritative answer lives.
  - Breaks the traceability pledge: no way to cite the latest version with confidence.
- **Architectural changes**:
  1. **New Neo4j nodes**: `(:Document {source_path, owner, created_at})`, `(:DocumentVersion {version_label, effective_date, checksum, status})`.
  2. **Relationships**:
     - `(:Document)-[:HAS_VERSION]->(:DocumentVersion)`
     - `(:DocumentVersion)-[:PRODUCES]->(:Episode)` to chain extracted knowledge.
     - `(:DocumentVersion)-[:UPDATES {change_summary}]->(:DocumentVersion)` to capture lineage.
  3. **Ingestion updates**:
     - Parse `version`, `source_date`, `creator` early and create or update the nodes above.
     - Compute file checksum to avoid duplicates and to detect re-ingested copies.
  4. **Services**:
     - Introduce a `DocumentRegistryService` to resolve "latest" vs historical versions.
     - Provide APIs `/documents` and `/documents/{concept}` summarising version history.

### 3.2 Concept definition drift is not monitored
- **What we see**: `get_or_create_entity` simply returns the existing node and overwrites the name; description changes are lost.
- **Why it matters** (promise impact):
  - Undermines the â€œmemory collectiveâ€ vision: users cannot see how the definition of Customer Retention Rate evolved across decks or policies.
  - Makes it risky to surface a direct answer because we cannot certify that the explanation reflects the latest approved definition.
- **Architectural changes**:
  1. Add `(:EntityDefinition {text, extracted_at, source_version})` nodes linked to `(:Entity)` with `[:DEFINED_AS]`.
  2. Connect each definition to its `(:DocumentVersion)` with `[:FROM]`.
  3. During ingestion, compare the new description with the latest one (hashing or diff); create a new definition node when meaning changes.
  4. Expose `GET /entities/{uuid}/definitions` returning the ordered history with optional diffs.
  5. Schedule audits that flag entities whose definition is stale or contradictory.

### 3.3 Governance coverage stops at numeric facts
- **What we see**:
  - Conflict detection compares numeric `Fact` nodes that share subject/predicate and status (approved vs proposed).
  - `valid_from` defaults to the ingestion timestamp when prompts do not surface effective dates.
- **Why it matters** (promise impact):
  - Users could receive outdated business rules, jeopardising the â€œdecision-ready in secondsâ€ value proposition.
  - â€œKnow where to knowâ€ requires that methodological guidance be consistent and automatically flagged when superseded.
- **Architectural changes**:
  1. Extend fact types with `METHODOLOGY` (and similar textual categories) storing formulas, business rules, and scope notes.
  2. Build a diff pipeline for methodological facts (lexical comparison plus embedding similarity).
  3. When a newer approved fact exists, mark predecessors as overridden or outdated automatically via new relationships.
  4. Improve prompts and extraction rules so `valid_from` is captured (fallback on document version metadata when absent).
  5. Enforce business rules: reject or retire "approved" facts when their source document version is superseded.

### 3.4 Provenance ("who / what / when") is incomplete
- **What we see**: ingestion parses `dc:creator` but never persists it; there is no graph representation of authors, reviewers, or approvers.
- **Why it matters** (promise impact):
  - Direct answers must indicate who authored the source and when to build trust; without it the â€œtraceable knowledgeâ€ USP is compromised.
  - Limits adoption in regulated contexts where accountability is mandatory.
- **Architectural changes**:
  1. Introduce `(:Person)` nodes (or integrate with a directory) and link them with `[:AUTHORED_BY]`, `[:REVIEWED_BY]`, `[:APPROVED_BY {role}]`.
  2. Store business unit / team metadata to support escalation workflows.
  3. Display author, validator, and approval timestamp in both API responses and UI.
  4. Notify the responsible person when conflicts or overrides occur.

### 3.5 "Sense overlay" vs enriched silo
- **What we see**:
  - Episodes keep lists of UUIDs instead of actual graph edges; there is no `(:Episode)-[:CONTAINS_FACT]->(:Fact)` relationship.
  - Answer generation relies mostly on Qdrant + reranking + LLM synthesis.
- **Why it matters** (promise impact):
  - Weakens the claim of an intelligent overlay; traversing knowledge remains difficult and prevents instant context assembly.
  - Makes it harder to surface one-click answers with precise references (page, slide, version) as promised in the pitch.
- **Architectural changes**:
  1. Refactor episode modelling to replace JSON arrays with explicit relationships to facts, entities, and relations; optionally add hub nodes such as `(:Concept)`.
  2. Build a bridge service that resolves a Qdrant chunk back to its Episode, DocumentVersion, Facts, Entities, and Document lineage.
  3. Offer graph-centric APIs (REST or GraphQL) so downstream tools and LLM agents can query the semantic layer directly.
  4. Enrich answer synthesis so citations include document version, concept, and linked facts.

### 3.6 Normalisation still depends on YAML catalogues
- **What we see**: the normaliser reads YAML catalogues; the SQL registry and planned Neo4j ontology are not yet the master source.
- **Why it matters** (promise impact):
  - Without automated catalog alignment, the platform cannot reliably â€œknow where to knowâ€ across new document types or business domains.
  - Limits the ability to keep the semantic layer in sync with the living knowledge base.
- **Architectural changes**:
  1. Finalise Neo4j ontology migration (`(:OntologyEntity)`, `(:OntologyAlias)`, strict uniqueness constraints) per the existing guide.
  2. Replace YAML lookups with a Neo4j-backed normaliser; use YAML only as bootstrap data.
  3. Connect EntityTypeRegistry approvals to ontology persistence (auto-create catalogue entries once an entity is approved).
  4. Surface registry and ontology metrics in admin tooling (pending types, auto-discovered entities, merge suggestions).

## 4. Architectural Change Matrix

> Each row ties the technical work to one or more pitch pillars: **IA** (instant access), **VE** (valorisation of existing assets), **DR** (decision speed & reliability).

| Area | Graph model impact | Backend / services impact | Ingestion & governance | Product / UX impact |
| --- | --- | --- | --- | --- |
| Document lifecycle (IA, VE) | Add `Document`, `DocumentVersion`, refactor `Episode` edges | New `document_service`, `/documents` APIs | Parse version metadata, checksum, owner | Timeline view, obsolescence flags, change log |
| Definition tracking (IA, DR) | Add `EntityDefinition`, `DEFINED_AS`, `FROM` | Extend `KnowledgeGraphService`, diff utilities | Detect definition drift during ingestion | Definition history UI and diffing |
| Fact governance expansion (DR) | Add `METHODOLOGY`, `OVERRIDES` edges | Extend `FactsService`, `ConflictDetector` | Capture true effective dates, retire old facts | Conflict dashboard, reviewer tasks |
| Provenance (DR) | Add `Person`, `AUTHORED_BY`, `APPROVED_BY` | Identity integration, audit logging | Persist author/approver metadata | Display ownership in every answer |
| Semantic overlay (IA, VE) | Replace episode arrays with edges, add `Concept` hubs | Bridge Qdrantâ†”Neo4j, GraphQL search layer | Sync chunk IDs with graph identifiers | Graph navigation and provenance cards |
| Ontology pipeline (VE) | Host catalogues in Neo4j linked via `catalog_id` | `EntityNormalizerNeo4j`, registry orchestrator | Auto-save ontology after approval | Admin UI for type/alias management |

## 5. Suggested Roadmap (high level)
1. **Phase A â€“ Document backbone (IA + VE)**: implement Document/DocumentVersion nodes, migrate episode structure, persist author metadata, expose basic document APIs.
2. **Phase B â€“ Definition and methodology governance (DR)**: add entity definition versioning, extend facts to methodological information, add diff detection and override rules.
3. **Phase C â€“ Semantic overlay and APIs (IA + VE)**: build the Qdrant-to-Neo4j bridge, expose graph APIs, update answer synthesis with structured provenance.
4. **Phase D â€“ Ontology migration and auto-learning (VE)**: finalise Neo4j ontology storage, plug the normaliser, wire the EntityTypeRegistry workflow to catalogue updates.
5. **Phase E â€“ AI alignment and monitoring (IA + DR)**: adjust prompts to leverage version knowledge, track KPIs (document coherence, contradiction resolution, governance SLA).

## 6. Success Metrics to Track
- **IA (instant access)**: Time from user query to answer; percentage of answers citing exact page/slide references.
- **VE (valorisation)**: Percentage of key business concepts with definition history in Neo4j; backlog reduction of pending ontology entries after approvals.
- **DR (decision speed & reliability)**: Time from new document ingestion to promotion of its version as "latest"; number of contradictions detected versus resolved each quarter; share of generated answers that surface version, source document, author, and approval date.

---

**Next steps**: validate this analysis with ingestion, graph, and product leads; map effort versus impact; refine the roadmap with dependencies (Neo4j infrastructure, governance processes, UI streams). The document can now be fed to other AI agents for further refinement and planning.
