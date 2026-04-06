# OSMOSIS — Vue d'ensemble des capacites actuelles

**Date :** Mars 2026
**Branche :** `feat/wiki-concept-assembly-engine`
**Usage :** Demo partenariat / revue technique externe

---

## 1. Pipeline d'Ingestion — Le Reacteur Central

### Vue d'ensemble

L'entree d'un document dans OSMOSIS declenche le `ClaimFirstOrchestrator`, un pipeline sequentiel a **17 phases** qui transforme du texte brut en un graphe de connaissances structure. Le pipeline est execute dans un worker RQ (Redis Queue) separe. Il consomme un cache d'extraction (PDF, PPTX, DOCX, etc.) et ne relit jamais les fichiers source.

### Phases detaillees

**Phase 0 — Creation des Passages**
Les `DocItems` sont indexes en `Passage` (unites de texte avec metadonnees : `section_title`, `page_no`, `reading_order`).

**Phase 0.5 — Extraction du DocumentContext**
Le LLM identifie : `primary_subject` (sujet principal), `raw_subjects` (topics secondaires), `qualifiers` (version, edition, region), `document_type`. Ce contexte est persiste comme noeud `DocumentContext` dans Neo4j — il encode l'applicabilite du document, pas la verite des assertions.

**Phase 0.55 — Resolution du ComparableSubject**
Classe le sujet principal en `AXIS_VALUE`, `DOC_TYPE` ou `NOISE`, et cree un noeud `ComparableSubject` — entite stable permettant de comparer des documents decrivant le meme sujet a travers des versions differentes.

**Phase 0.6 — ApplicabilityFrame (evidence-locked)**
Architecture en 4 couches :
- **Layer A** : segmentation en `EvidenceUnit` (phrases atomiques avec IDs stables)
- **Layer B** : scan deterministe exhaustif de markers (CONDITIONALITY, SCOPE, TEMPORAL...) et de `ValueCandidate` (versions, dates, identifiants)
- **Layer C** : le LLM recoit uniquement des IDs pre-existants, jamais le texte complet — il ne peut pas inventer de valeur
- **Layer D** : validation deterministe des sorties LLM

Resultat : un `ApplicabilityFrame` JSON stocke sur le `DocumentContext` Neo4j.

**Phase 1 — Extraction des Claims**
Le LLM produit des assertions synthetiques (`text`) accompagnees d'une `verbatim_quote` exacte extraite du texte source. Chaque claim est typee (`FACTUAL`, `PRESCRIPTIVE`, `DEFINITIONAL`, `CONDITIONAL`, `PERMISSIVE`, `PROCEDURAL`) et porte une `ClaimScope`.

**Phase 1.4 — Gate de Verifiabilite**
Similarite cosinus entre `claim.text` et `claim.verbatim_quote` (modele `multilingual-e5-large`) :
- score < 0.80 → rejet (fabrication)
- [0.80, 0.88] → zone grise → `EvidenceRewriter` tente une reecriture
- apres reecriture : cos ≥ 0.88 requis sinon rejet

**Phase 1.5 — Deduplication deterministe**
Double deduplication : texte exact (hash) + triplet S/P/O (structured_form).

**Phase 1.6 — Filtrage qualite**
Filtres deterministes : claims trop courtes, boilerplate, heading-like, tautologies, template leaks.

**Phase 1.6c — Atomicity Splitter**
Si une claim contient plusieurs assertions, elle est decoupee en claims atomiques.

**Phase 2 — Extraction d'Entites**
Identification deterministe des entites nommees. Contraintes : max 50 caracteres, max 6 mots, stoplist.

**Phase 2.5 — Canonicalisation des Entites**
Fusion LLM des entites referant au meme objet (ex: "SAP BTP" = "Business Technology Platform") produisant un graphe `Entity → SAME_CANON_AS → CanonicalEntity`.

**Phase 2.9 — Facet Candidate Extraction**
1 seul appel LLM par document pour extraire les dimensions classificatrices (ex: "compliance", "performance"). Le `FacetRegistry` accumule et valide cross-documents.

**Phase 3 — Facet Matching (deterministe)**
Attribution des facettes validees aux claims via 4 signaux.

**Phase 4 — Linking**
- Claim → Passage (contexte)
- Claim → Entity (relation `ABOUT`)
- Claim → Facet (relation `HAS_FACET`)

**Phase 4.5 — Domain Pack Enrichment**
Les Domain Packs actifs (containers Docker sidecar) enrichissent le graphe avec des entites specialisees (chimiques, pathologies, produits SAP).

**Phase 4.6 — Canonical Alias Resolution**
Les entites dont le nom matche un alias canonique des domain packs actifs sont renommees (ex: "RISE with SAP" → "SAP S/4HANA Cloud Private Edition").

**Phase 5 — Clustering inter-documents**
Regroupement des claims semantiquement similaires a travers les documents en `ClaimCluster`.

**Phase 6 — Detection de Relations**
- Value-level : compare les structured_forms S/P/O pour detecter les contradictions numeriques/booleennes
- Patterns regex : `REFINES`, `QUALIFIES`
- Chain detection : chaines compositionnelles S/P/O

**Phase 7 — Persistance Neo4j**
`MERGE` Cypher idempotents — chaque re-run est sur.

**Phase 8 — Persistance Qdrant**
Vectorisation et insertion dans Qdrant avec metadonnees d'applicabilite dans le payload.

---

## 2. Structure du Knowledge Graph

### Noeuds Neo4j

| Label | Description |
|---|---|
| `Claim` | Assertion atomique extraite d'un document (text, verbatim_quote, claim_type, structured_form) |
| `Entity` | Entite nommee (name, entity_type, normalized_name) |
| `CanonicalEntity` | Entite canonique fusionnant plusieurs Entity |
| `Facet` | Dimension classificatrice (domain, dimension_key) |
| `ClaimCluster` | Regroupement de claims semantiquement equivalentes |
| `Document` | Document source |
| `DocumentContext` | Contexte d'applicabilite (primary_subject, document_type, applicability_frame) |
| `SubjectAnchor` | Sujet canonique avec aliases types |
| `ComparableSubject` | Sujet stable pour comparaison cross-documents |
| `ApplicabilityAxis` | Axe d'applicabilite (version, release, date) |
| `WikiArticle` | Article wiki genere (slug, title, markdown, importance_tier) |
| `WikiCategory` | Categorie wiki |
| `HygieneAction` | Action d'hygiene KG avec snapshot pour rollback |

### Relations Neo4j

| Relation | Source → Cible | Semantique |
|---|---|---|
| `ABOUT` | Claim → Entity | La claim parle de cette entite |
| `HAS_FACET` | Claim → Facet | Dimension classificatrice |
| `IN_CLUSTER` | Claim → ClaimCluster | Membership cluster |
| `CONTRADICTS` | Claim ↔ Claim | Contradiction detectee |
| `REFINES` | Claim → Claim | Precision/specification |
| `QUALIFIES` | Claim → Claim | Conditionnement |
| `SAME_CANON_AS` | Entity → CanonicalEntity | Fusion canonique |
| `ABOUT` | WikiArticle → Entity | Article portant sur cette entite |
| `HAS_CONTEXT` | Document → DocumentContext | Contexte d'applicabilite |
| `HAS_AXIS_VALUE` | DocumentContext → ApplicabilityAxis | Axes detectes |
| `CHAINS_TO` | Entity → Entity | Lien compositionnel cross-doc |

---

## 3. Detection de Contradictions

### Niveau 1 — Value-Level (deterministe, a l'ingestion)
Compare les `structured_form` (triplets S/P/O) pour detecter les contradictions numeriques et les negations polaires. Un "non-exclusivity gate" empeche les faux positifs sur les predicats non-exclusifs.

### Niveau 2 — Classification epistemique (LLM, post-ingestion)
Classe selon deux axes :

**tension_nature** : `value_conflict` | `scope_conflict` | `temporal_conflict` | `methodological` | `complementary`

**tension_level** : `hard` | `soft` | `none`

Les **diffusion flags** sont deduits par code (jamais par le LLM) : `show_in_article`, `show_in_chat`, `show_in_homepage`, `requires_review`.

---

## 4. Recherche et Chat

### Recherche multi-couches

1. **Memory Layer** : contexte conversationnel (5 derniers messages si session active)
2. **Recherche Qdrant** : recherche vectorielle avec filtres (version/release, solution)
3. **Reranking** : cross-encoder post-retrieval
4. **KG Traversal** : traversee `CHAINS_TO` pour raisonnement transitif cross-document
5. **Claims Vector Search** : recherche directe sur les noeuds Claim Neo4j avec contradictions et entites associees
6. **Related Articles** : articles Atlas lies aux entites de la reponse
7. **Insight Hints** : signaux contextuels (contradictions, concepts lies, couverture faible)

### Difference vs RAG standard
OSMOSIS ne renvoie pas seulement des chunks de documents — il renvoie des claims avec leur contexte epistemique (type, scope, contradictions connues), permettant une synthese informee.

---

## 5. Knowledge Atlas (Wiki)

Pipeline de generation d'articles automatiques en 6 etapes :

1. **ImportanceScorer** : score = log(claims) + 1.5*log(docs) + 0.5*graph_degree → Tier 1/2/3
2. **ConceptResolver** : resolution du concept (exact, alias, fuzzy) vers les entites Neo4j
3. **EvidencePackBuilder** : pipeline deterministe 8 etapes (aucun LLM) assemblant les claims en evidence units avec roles rhetoriques, contradictions, evolution temporelle
4. **SectionPlanner** : planification deterministe des sections (overview, definition, key_properties, contradictions, sources)
5. **ConstrainedGenerator** : le LLM genere chaque section avec citations obligatoires (`[source, unit_id]`) — il ne peut citer que des sources pre-fournies
6. **ConceptLinker** : injection d'hyperliens inter-articles (batch)

### Homepage Atlas
- Resume editorial genere (domain_summary auto-regenere apres batch)
- Top concepts (dedup canonical, filtres stoplist domain pack)
- Barre de couverture (% concepts avec article)
- Blind spots (contradictions, couverture faible, concepts sans article)

---

## 6. KG Hygiene

### Layer 1 — Deterministe (auto-apply)
- **StructuralEntityRule** : artefacts de mise en page
- **InvalidEntityNameRule** : noms trop longs, references biblio
- **DomainStoplistRule** : stoplist du domaine

### Layer 2 — LLM-assisted
- **AcronymDedupRule** : acronymes dupliques
- **SingletonNoiseRule** : entites mono-claim
- **WeakEntityRule** : entites non pertinentes
- **CanonicalDedupRule** : fusion paires equivalentes
- **SameCanonEntityDedupRule** : consolidation Entity partageant le meme canonical
- **MERGE_ENTITY** : transfert claims + suppression source, rollback complet

### Layer 3 — Axes d'applicabilite
- **LowValueAxisRule**, **RedundantAxisRule**, **MisnamedAxisRule**
- Propositions uniquement, jamais auto-apply

---

## 7. Domain Packs

Conteneurs Docker sidecar au format `.osmpack`. Lifecycle : Upload → Install → Activate → Deactivate → Uninstall.

### Pack Biomedical
- **NER** : scispaCy (en_ner_bc5cdr_md)
- **Entites** : Chemical, Disease + 7 types supplementaires
- **Stoplist** : 94 termes generiques scientifiques

### Pack SAP Enterprise
- **NER** : GLiNER zero-shot (gliner_medium-v2.1) — aucun entrainement requis
- **Gazetteer** : 528 produits SAP (force-include)
- **Acronymes** : 213 acronymes SAP
- **Canonical Aliases** : 134 mappings (RISE → S/4HANA Cloud Private Edition, etc.)
- **Phase 4.6** : resolution des aliases dans le pipeline d'ingestion

---

## 8. Framework d'Applicabilite

Architecture "evidence-locked" en 4 couches. Le LLM ne peut referencer que des IDs pre-existants — si une valeur n'est dans aucun `ValueCandidate` extrait de maniere deterministe, elle ne peut pas apparaitre dans le frame final.

Usage : filtrage par version/release dans la recherche (`axis_release_id` indexe dans Qdrant et Neo4j).

---

## 9. Quality Gates

| Gate | Mecanisme | Ce qu'elle elimine |
|---|---|---|
| **Verifiability** | cos(text, verbatim) | Fabrications LLM |
| **Evidence Rewriter** | vLLM reecriture | Claims zone grise |
| **Deterministic Gates** | Regles | Tautologies, template leaks |
| **Atomicity Splitter** | Regex + LLM | Claims composites |
| **Independence Resolver** | Resolution coreferences | Claims dependantes non resolues |

---

## 10. Infrastructure

| Composant | Technologie |
|---|---|
| **Backend** | FastAPI (Python 3.11) |
| **Frontend** | Next.js 14 + Chakra UI |
| **Vector Store** | Qdrant |
| **Knowledge Graph** | Neo4j 5.26 |
| **Queue** | Redis + RQ |
| **LLM Cloud** | OpenAI GPT-4o (vision, metadata) |
| **LLM Local** | Ollama Qwen 3.5 9B (classification rapide) |
| **LLM Burst** | vLLM + Qwen 2.5 14B AWQ sur EC2 Spot g6.2xlarge (GPU L4) |
| **Embeddings** | multilingual-e5-large |
| **Monitoring** | Grafana + Loki + Promtail |
| **Domain Packs** | Containers Docker sidecar (scispaCy, GLiNER) |

---

## 11. Ce qui differencie OSMOSIS d'un RAG classique

| Capacite | RAG classique | OSMOSIS |
|---|---|---|
| "Quelle est notre politique X ?" | Oui | Oui |
| "Cette politique a-t-elle change ?" | Non (aveugle) | Oui — timeline d'evolution |
| "Y a-t-il des contradictions ?" | Non (aveugle) | Oui — 2 niveaux de detection |
| "Que manque-t-il dans notre doc ?" | Non (aveugle) | Oui — analyse de completude |
| "Peut-on se fier a cette info ?" | Non (aveugle) | Oui — 6 types de claims + quality gates |
| "Quels concepts sont lies ?" | Non | Oui — graphe de connaissances navigable |
| "Generer un article de synthese" | Non | Oui — Knowledge Atlas avec citations |
| "Comparer deux versions" | Non | Oui — ApplicabilityFrame + axes |

---

## 12. Maturite par composant

| Composant | Maturite |
|---|---|
| Pipeline d'ingestion ClaimFirst | Production-ready |
| Quality Gates | Production-ready |
| Knowledge Graph Neo4j | Production-ready |
| Applicability Framework | Beta |
| Contradiction Detection L1 | Production-ready |
| Contradiction Classification L2 | Beta |
| Knowledge Atlas | Beta |
| KG Hygiene L1-L2 | Beta |
| Domain Packs | Beta |
| Recherche/Chat | Production-ready |
| Burst Mode vLLM | Production-ready |
