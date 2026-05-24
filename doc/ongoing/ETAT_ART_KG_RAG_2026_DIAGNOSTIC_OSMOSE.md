# État de l'art KG-RAG 2026 + Diagnostic OSMOSE

> Document de décision post-Phase A. Date : 2026-05-23.
> Statut : Phase A clôturée techniquement, gates non atteintes (C1 0.500 vs cible 0.75 ; p95 85s vs cible 60s).
> Audience : décideur produit + tech lead. Format : aide à la décision, pas exposé académique.

---

## Cadre domain-agnostic (rappel)

OSMOSE est un produit OSS de KG-RAG bitemporal multi-corpus. Le corpus de test actuel est SAP par circonstance (données disponibles), pas par design. **Toutes les pistes et patterns évoqués doivent rester applicables à un corpus médical, réglementaire, juridique ou aerospace.** Les exemples SAP cités servent uniquement à illustrer un diagnostic — ils ne sont jamais une caractéristique du produit.

Les LLM runtime recommandés sont strictement open-source serverless (DeepSeek-V3.1, Llama-3.3-70B, Qwen2.5-72B, Mistral-Large) via DeepInfra ou Together AI. **Pas de Claude / GPT-4o en chemin critique** (cf. mémoire `feedback_no_proprietary_llm_in_production`).

---

## TL;DR

1. **La Phase A a posé une fondation valide (bitemporel, claims, runtime modulaire) mais le runtime KG-first plafonne à C1=0.500** sur 50q stratifié SAP, vs cible 0.75 (gap -0.25pp). 49/50 questions terminent en mode `ABSTENTION` avec 0 claims cités. Le système ne ramène quasiment jamais les claims attendus, **même quand ils existent en KG** (audit Oracle A4.7 : 18/18 questions où la preuve est prouvée présente → recall@5 strict = 0%).
2. **3 leviers testés en session ont régressé ou été neutres** : RRF retrieval BM25+vector isolé (-0.14pp), cascade Qdrant systématique (-0.34pp), switch LLM Synthesize (Qwen14B = DeepSeek-V3.1 = DeepSeek-V4-Pro). Seul gain réel : fixes infra timeout/retries (A4.14, +0.23pp). L'abstention est devenue une stratégie gagnante par défaut sur ce gold-set.
3. **Le verrou architectural principal n'est pas le retrieval brut mais l'amont** : Parse Qwen3-235B échoue JSON 30% des cas → sub_goal sans subject → Plan unmappable → 0 tool_call → Evaluate INSUFFICIENT → ABSTENTION. Quand le retrieval RRF est isolé, il marche structurellement mais reste pénalisé par la chaîne Parse/Plan/Evaluate au-dessus.
4. **L'état de l'art 2026 valide notre architecture** (Zep/Graphiti, VersionRAG, Microsoft GraphRAG, LeanRAG, LightRAG) mais signale **3 patterns que nous n'avons pas implémentés** : (a) cross-encoder reranker post-fusion (+5-15 NDCG@10 documenté), (b) Cypher dynamique généré par LLM (filtres prédicats sémantiques — pattern EKX), (c) hyper-relational claims (claims avec qualifiers structurés pour multi-hop).
5. **Extraction trop atomique** : sample de 10 claims aléatoires montre des assertions monoligne sans qualifiers (version, scope, conditions). Pour les questions multi_hop (C1=0.10/0.15) et comparison (0.10/0.50), il manque une couche de claims relationnels ou de chaînes pré-extraites.

---

## 1. État de l'art KG-RAG 2026

### 1.1 Tableau synthétique des patterns 2026

| # | Pattern | Source | Gain mesuré reporté | Applicable OSMOSE ? |
|---|---|---|---|---|
| P1 | **Hybrid BM25 + Vector + RRF** | [Tech Bytes Hybrid RAG 2026](https://techbytes.app/posts/hybrid-rag-search-bm25-embeddings-deep-dive-2026/), [Neo4j HybridCypherRetriever](https://neo4j.com/blog/developer/enhancing-hybrid-retrieval-graphrag-python-package/) | Accuracy 62% → 91% (+48% rel.). Recall@5 0.72 → 0.91 | **Oui** — infra Neo4j vector index 1024d déjà créée. Code A4.9-ter prêt mais désactivé par défaut (factual régresse sans cross-encoder en aval) |
| P2 | **Cross-encoder reranker (ms-marco / bge-reranker-v2-m3)** | [Local AI Master 2026](https://localaimaster.com/blog/reranking-cross-encoders-guide), [BSWEN 2026](https://docs.bswen.com/blog/2026-02-25-best-reranker-models/) | +5-15 NDCG@10 sur MTEB/BEIR. BGE v2-m3 : 51.8 nDCG@10 (278M params, multilingue) | **Oui** — gain attendu net sur top-50 RRF → top-5. Open-source, pas de coût LLM |
| P3 | **HyDE / Multi-Query Rewriting** | [Medium 2026](https://medium.com/theultimateinterviewhack/hyde-query-expansion-supercharging-retrieval-in-rag-pipelines-f200955929f1), [MQRF-RAG ACM 2025](https://dl.acm.org/doi/10.1145/3728199.3728221) | +25-50% nDCG@10 sur queries difficiles. MQRF-RAG +7% vs HyDE sur HotpotQA | **Partiel** — bon sur descriptif, faible sur identifiants exacts. Latence +1 LLM call |
| P4 | **GraphRAG Communities (Microsoft)** | [arxiv 2404.16130](https://arxiv.org/pdf/2404.16130), [paperclipped.de 2026](https://www.paperclipped.de/en/blog/graph-rag-production/) | +35% vs vector-only sur global queries. 80-85% multi-hop vs 45-50% vector | **Partiel** — over-engineered, 58% tokens en entity extraction, re-indexation lourde |
| P5 | **LightRAG (flat graph dual-level)** | [paperclipped.de 2026](https://www.paperclipped.de/en/blog/graph-rag-production/) | 70-90% qualité GraphRAG à 1/100ème coût indexation | **Oui** — meilleur trade-off coût/qualité que MS GraphRAG. Mais pas de community detection |
| P6 | **Zep/Graphiti (temporal bitemporal KG)** | [arxiv 2501.13956](https://arxiv.org/html/2501.13956v1), [graphiti GitHub](https://github.com/getzep/graphiti) | P95 300ms, blueprint open-source Neo4j natif | **Oui** — architecture quasi-identique à la nôtre. Limitation : extraction OpenAI/Gemini (incompatible charte) |
| P7 | **LeanRAG (semantic aggregation bottom-up)** | [arxiv 2508.10391](https://arxiv.org/abs/2508.10391) | -46% retrieval redundancy. Bottom-up structure-guided | **Oui** — complémentaire de la hiérarchie Document→Section→Claim |
| P8 | **VersionRAG (version-aware RAG)** | [arxiv 2510.08109](https://arxiv.org/abs/2510.08109) | 90% précision changements explicites, 60% implicites | **Oui** — aligné Phase A1 bitemporal. Référence chiffrée pour C3 lifecycle |
| P9 | **Memento (bitemporal LongMemEval)** | [n1n.ai 2026-04](https://explore.n1n.ai/blog/building-bitemporal-knowledge-graph-llm-agent-memory-longmemeval-2026-04-11) | 92.4% LongMemEval. "Precision over recall pour éviter de confondre le modèle" | **Oui** — valide notre stratégie ClaimFilter top-5 stratifié |
| P10 | **Direct Fact Retrieval (bypass entity linking)** | [arxiv 2305.12416](https://arxiv.org/pdf/2305.12416) | Évite l'accumulation d'erreurs entity span detection + linking + relation classification | **Oui** — testé en A4.11 (Choix 2 vector-only) → C1=0.350 ex æquo RRF mais factual 0.400 meilleur. Sacrifie comparison |
| P11 | **Hyper-relational claims (qualifiers structurés)** | [arxiv 2211.10018](https://arxiv.org/pdf/2211.10018), [TrustGraph reification 2026](https://trustgraph.ai/guides/key-concepts/graph-reification/), [arxiv 2508.03280](https://arxiv.org/html/2508.03280v1) | Capture rich knowledge structure (qui, quand, conditions). Wikidata/YAGO4 pattern | **Oui** — gap critique côté OSMOSE pour multi_hop et lifecycle |
| P12 | **Atomic Fact Extraction QA-driven** | [Fact in Fragments arxiv 2506.07446](https://arxiv.org/pdf/2506.07446), [SocraticKG arxiv 2601.10003](https://arxiv.org/html/2601.10003) | "Granularity Score" supérieur à direct extraction et GraphRAG. Décompose claims complexes en atomic facts | **Oui** — pourrait améliorer la précision factual. Mais inverse trop atomique = perte de contexte multi-hop |
| P13 | **StepChain GraphRAG (multi-hop chain explicit)** | [arxiv 2510.02827](https://arxiv.org/html/2510.02827v1) | Pré-extraction chaînes de raisonnement → multi-hop QA améliorée | **Oui** — adresse directement notre trou multi_hop C1=0.10-0.15 |
| P14 | **HELP (HyperNode Expansion + Logical Path)** | [arxiv 2602.20926](https://arxiv.org/pdf/2602.20926) | Jusqu'à 28.8× speedup vs Graph-RAG baselines, qualité maintenue | **Partiel** — gain perfo plus que qualité |
| P15 | **Cypher dynamique LLM-generated (predicate-flexible filters)** | Pattern EKX observé (mémoire `project_ekx_inspiring_patterns`), [SAT-Graph API arxiv 2510.06002](https://arxiv.org/abs/2510.06002) | Non chiffré publiquement. EKX (RAG+KG tiers SAP) atteint 0.86 sur 30q hard où V3/V4.2 OSMOSE échouent | **Oui** — gap notable côté OSMOSE. Pattern domain-agnostic |

### 1.2 Trois patterns les plus prometteurs pour OSMOSE — détaillés

#### Pattern A — Cross-encoder reranker post-RRF (P2)

- **Principe** : le RRF parallèle BM25+Vector ramène top-50 candidats. Un cross-encoder (modèle séparé, encode `[query, claim_text]` ensemble) re-score les 50, ne garde que top-5 envoyés à Synthesize. Le cross-encoder voit les deux textes simultanément → bien plus précis qu'un bi-encoder cosinus.
- **Mise en œuvre technique** :
  - Modèle open-source : `BAAI/bge-reranker-v2-m3` (278M params, multilingue FR/EN/DE/ZH, 51.8 nDCG@10 sur BEIR). Hébergement vLLM ou sentence-transformers local.
  - Pipeline : `Execute RRF top-50` → `reranker.predict([(q, c.text) for c in top50])` → `sort desc, take top-5` → `ClaimFilter A3.11`.
- **Gain chiffré référence** : +5-15 NDCG@10 sur benchmarks BEIR/MTEB ([Local AI Master 2026](https://localaimaster.com/blog/reranking-cross-encoders-guide)). +5-7 NDCG documenté comme "le plus gros gain single-step dans la pile RAG typique".
- **Applicabilité OSMOSE** : très bonne. Sur le bench A4.14, 49/50 questions terminent en ABSTENTION car 0 claims cités par Synthesize. Si le reranker priorise correctement les claims oracle (qui existent en top-50 RRF d'après audit A4.7), C1 devrait monter mécaniquement.
- **Effort estimé** : **3-4 jours** (intégration sentence-transformers ou vLLM endpoint dédié, refactor `ClaimFilter`, bench, tuning seuil).
- **Risque** : latence +500-1500ms par question (acceptable, p95 actuel 85s). Dépendance modèle externe (à héberger).

#### Pattern B — Hyper-relational claims + chaînes pré-extraites (P11 + P13)

- **Principe** : actuellement nos `:Claim` sont des assertions atomiques `(subject, predicate, object, text)`. Pour répondre à du multi_hop (ex "quels prérequis ET dans quel ordre pour une conversion ECC→S/4HANA ?"), il faut des **claims avec qualifiers structurés** (`conditions[]`, `valid_in_context_of`, `prerequisite_for`, `step_index`) **et des chaînes pré-extraites** (relations `STEP_OF`, `PREREQUISITE_OF`, `CAUSE_OF`).
- **Mise en œuvre technique** :
  - **Phase ingestion** : enrichir le prompt ClaimExtractor pour extraire qualifiers (cf. [TrustGraph reification 2026](https://trustgraph.ai/guides/key-concepts/graph-reification/)). Pattern Wikidata : `{subject, predicate, object, qualifiers: {start_time, end_time, conditions, applies_to_version, ...}}`.
  - **Phase post-import** : un détecteur de chaînes pré-extrait les sequences (S/4HANA → Readiness Check → Simplification Item Check → SUM/DMO → Custom Code Migration). Stockage : `(:Claim)-[:STEP_OF {step_index:1}]->(:Procedure)`. Le pattern existe déjà partiellement (`CHAINS_TO` 1024 instances) mais sous-développé.
  - **Phase runtime** : pour les sub_goals `kind=multi_hop`, mapper vers un tool `procedure_query` qui ramène la chaîne complète (pas le claim isolé).
- **Gain chiffré référence** : StepChain GraphRAG ([arxiv 2510.02827](https://arxiv.org/html/2510.02827v1)) reporte une amélioration significative multi-hop vs baseline ; Microsoft GraphRAG 80-85% multi-hop vs 45-50% vector-only ([NVIDIA Blog](https://developer.nvidia.com/blog/boosting-qa-accuracy-with-graphrag-using-pyg-and-graph-databases/)).
- **Applicabilité OSMOSE** : forte sur les types qui plafonnent : multi_hop (C1=0.15), comparison (0.10-0.50), false_premise (0.00-1.00 selon LLM judge). **Domain-agnostic strict** : qualifiers et procedures sont des notions universelles (recette médicale, procédure légale, séquence aerospace).
- **Effort estimé** : **8-12 jours** (4j refonte prompt ClaimExtractor + tests sur 5 docs, 3j détecteur chaînes post-import, 3j tool `procedure_query` runtime + bench).
- **Risque** : ré-ingestion partielle ou complète nécessaire (dépend du périmètre — si on n'enrichit que les nouveaux docs, drift). Coût LLM extraction ×1.3 estimé (qualifiers = +30% tokens output).

#### Pattern C — Cypher dynamique généré par LLM (P15 + pattern EKX)

- **Principe** : aujourd'hui Execute utilise des templates Cypher fixes paramétrés par `subject_canonical`. EKX (RAG+KG SAP tiers à 0.86) génère un **filtre Cypher dynamique** sur les prédicats sémantiquement liés à la question :
  ```cypher
  -- au lieu de WHERE c.subject_canonical = $subject (exact, fragile)
  MATCH (c:Claim)
  WHERE c.predicate IN ['USES', 'REQUIRES', 'DEPENDS_ON', 'RUNS_ON']  -- LLM choisit
    AND c.object_canonical =~ '(?i)BTP|Business Technology Platform|SAP BTP'  -- LLM expand synonymes
  RETURN c
  ```
- **Mise en œuvre technique** :
  - **Parse + PredicateExpander** : un LLM call léger (~200 tokens) génère pour chaque sub_goal un set de prédicats sémantiquement proches du `predicate_hint` + un set d'alias d'entité.
  - **Execute** : applique le filtre comme un `IN` sur les prédicats + une regex case-insensitive sur les objects (full-text peut suffire si l'index est bien posé).
  - **Garde-fou** : la génération Cypher reste contrainte (whitelist `predicate IN [...]`, pas de Cypher arbitraire injectable). Pattern proche de [SAT-Graph API Deterministic Legal Agents (arxiv 2510.06002)](https://arxiv.org/abs/2510.06002).
- **Gain chiffré référence** : non chiffré publiquement, mais EKX bat OSMOSE V3+V4.2 de +0.45 à +0.62pp sur 30q hard (réf. mémoire `project_ch50_oracle_audit_results`). Le pattern est documenté comme contribuant significativement à cet écart.
- **Applicabilité OSMOSE** : très bonne. Adresse directement le diagnostic A4.7 (filtre exact subject_canonical trop fragile, retrieval recall = 0%). Reste **domain-agnostic** : "synonymes du sujet + prédicats sémantiquement proches" fonctionne identique sur médical ou réglementaire.
- **Effort estimé** : **5-7 jours** (3j module PredicateExpander LLM + cache, 2j refactor Execute Cypher dynamique sécurisé, 2j bench).
- **Risque** : sécurité injection Cypher (à border par whitelist stricte). Latence +1 LLM call par sub_goal (~5-10s). Mais nous économisons les retries Qwen3-235B JSON empty.

---

## 2. Audit "extraction plus fine"

### 2.1 Taxonomie d'extraction actuelle OSMOSE

Source : `doc/ARCH_CLAIMFIRST.md` + audit Neo4j `default` au 23/05/2026.

**Modèle de Claim actuel** (`src/knowbase/claimfirst/models/claim.py`) :
- `ClaimType` : `FACTUAL` (89.2%), `PRESCRIPTIVE` (7.4%), `DEFINITIONAL` (3.0%), `PERMISSIVE/PROCEDURAL/CONDITIONAL` (<0.4% chacun)
- `Claim` = `(claim_id, doc_id, text verbatim, subject_canonical, predicate, object_canonical, structured_form_json, unit_ids, ...)`
- `ClaimScope` = `(version, region, edition, conditions[])` — **présent dans le modèle, sous-exploité** : aucun champ scope.version sur le sample observé
- 4 timestamps bitemporels (`valid_from`, `valid_until`, `ingested_at`, `invalidated_at`) — Phase A1 livrée
- 11 622 claims `tenant=default`, dont 1025 sans `subject_canonical` (8.8%, après backfill A4)

**Granularité observée — sample 10 claims aléatoires (23/05) :**

| claim_id | subject | predicate | text (extrait) |
|---|---|---|---|
| 4ab2ff12a750 | Stock Projection Worksheet | NULL | "Stock Projection Worksheet calculates base inventory by taking into account all actual and expected incoming and outgoing movements." |
| 6e1bfbebdcc7 | NULL | NULL | "Up to 999,999 line items per document" |
| 4553781248ef | Receivables Line-Item Matching for Lockbox | NULL | "Receivables Line-Item Matching for Lockbox provides proposals for matching..." |
| 2d8617ddf741 | SAP ILM | USES | "SAP ILM is used to control the blocking and deletion of personal data in Product Safety and Stewardship for Process Industries." |
| 9efb200103a3 | SAP S/4HANA 2023 | USES | "SAP S/4HANA 2023 uses BOPF tools for developing and testing business objects." |
| d08f9c32988c | Intercompany Matching | NULL | "Intercompany Matching is a built-in solution in SAP S/4HANA that matches transactions without any ETL processes..." |

**Distribution des prédicats** (top 5) : USES (1524), PROVIDES (550), REQUIRES (409), SUPPORTS (297), PROCESSES (285).

**Distribution des relations claim-vs-claim** : ABOUT 41 963, IN_CLUSTER 15 163, SIMILAR_TO 402 356, CHAINS_TO 1024, QUALIFIES 745, REFINES 614, CONTRADICTS 103.

### 2.2 Limites observées

**(L1) Claims atomiques sans qualifiers structurés.** Le claim `"SAP S/4HANA 2023 uses BOPF tools for developing and testing business objects"` n'a pas de qualifier `valid_from=2023`, `applies_to=development workflow`, `excluded_from=production runtime`. Pour répondre à "BOPF est-il encore utilisé en 2024 ?" il faudrait croiser ce claim avec un autre. **Gap typique multi-hop.**

**(L2) Claims sans subject (8.8%) ou avec subject implicite.** Le claim `"Up to 999,999 line items per document"` n'a pas de subject — c'est une contrainte numérique. Pour la question "Quelle limite de line items par document dans S/4HANA ?", le retrieval subject-based ne trouvera rien. Le claim existe mais est invisible.

**(L3) Pas de chaînes de procédure pré-extraites.** `CHAINS_TO` existe (1024 instances) mais reste générique et non typé. Pour multi_hop "séquence migration ECC EHP6 → S/4HANA Cloud 2024", il faudrait `(:Step)-[:NEXT_STEP {order:1}]->(:Step)` ou un `:Procedure` avec sub-steps ordonnés. Aujourd'hui ces séquences sont diluées dans des claims indépendants.

**(L4) Comparaison cross-doc non extraite.** Les claims `"S/4HANA 2022 utilise SAP Note 3145277"` et `"S/4HANA 2023 utilise SAP Note 3307222"` sont 2 claims indépendants. Le runtime doit reconstruire la comparaison à la volée. Pattern `EVOLUTION_OF` existe en ADR mais peu peuplé (614 REFINES + 103 CONTRADICTS sur 11 622 claims = 6.2% coverage).

**(L5) Sample concret de la limite** : la question `"Quelle est la difference entre les Release Information Notes de S/4HANA 2022 et 2023 ?"` (HUM_0005, comparison) a abouti à ABSTENTION dans le bench A4.14, alors que **les 2 SAP Notes existent dans le KG** (vérifié sur sample). Le retrieval ne sait pas relier "Release Information Note 2022" et "2023" à une comparaison. Le pipeline aurait besoin soit (a) d'un claim "compound" `{subject:RIN, predicates:{2022→3145277, 2023→3307222}}`, soit (b) d'une relation `EVOLUTION_OF` peuplée entre les 2 claims, soit (c) d'un tool runtime `compare_claims_by_axis(subject, axis=version)`.

### 2.3 Taxonomies alternatives évaluées

| Approche | Description | Pour OSMOSE |
|---|---|---|
| **ATOMIC-10X facts** (Fact in Fragments) | Décompose chaque claim complexe en atomic facts vérifiables séparément ([arxiv 2506.07446](https://arxiv.org/pdf/2506.07446)) | Améliore factual précision MAIS perd contexte multi-hop si pas combiné. Notre granularité est déjà très atomique — ce n'est pas la voie principale |
| **DSPy assertions** | Programmatic chain-of-thought ; chaque assertion validée par un mini-verifier | Pas applicable à l'extraction ingest ; intéressant en runtime mais nécessite framework DSPy |
| **Multi-hop chains pré-extraites** (StepChain GraphRAG) | Pré-extrait les chaînes A→B→C pendant l'ingestion ; `:Step`/`:Procedure` typés | **Adresse directement L3**. Recommandé |
| **Qualifiers / hyper-relational** (Wikidata, YAGO4, TrustGraph) | Chaque triplet (S,P,O) porte qualifiers structurés `{when, where, condition, source_authority, applies_to}` | **Adresse directement L1**. Recommandé |
| **Hierarchical claims** (narrative claim + sub-claims) | Un claim narratif "Migration ECC→S/4HANA" contient sub-claims atomiques. Pattern LeanRAG | **Adresse partiellement L3 et L4**. Compatible avec hyper-relational |
| **Atomic + Aggregation à la requête** (LeanRAG bottom-up) | Garde l'atomicité à l'ingestion ; agrège dynamiquement au query-time selon le sub_goal | **Pattern complémentaire de Pattern B**. Hybride élégant |

### 2.4 Recommandation extraction

**Évolution proposée du modèle Claim** (sans changer la structure atomique de base) :

```python
class Claim:
    # --- existant ---
    claim_id: str
    text: str  # verbatim
    subject_canonical: Optional[str]
    predicate: Optional[str]
    object_canonical: Optional[str]
    claim_type: ClaimType

    # --- existant mais à peupler systématiquement ---
    scope: ClaimScope  # version, region, edition, conditions[]

    # --- enrichissement proposé (hyper-relational) ---
    qualifiers: dict[str, Any]  # {applies_to, requires, valid_in_context_of, ...}
    procedure_role: Optional[ProcedureRole]  # PREREQUISITE | STEP | OUTCOME | None
    procedure_id: Optional[str]              # foreign key vers (:Procedure)
    step_index: Optional[int]                 # ordre dans la procedure
```

Et nouveaux nodes :
- `(:Procedure {procedure_id, name, domain_neutral_label})` — agrégat de claims procéduraux
- Relations `(:Claim)-[:STEP_OF {order:int}]->(:Procedure)`, `(:Claim)-[:PREREQUISITE_OF]->(:Claim)`, `(:Claim)-[:OUTCOME_OF]->(:Claim)`

Le pattern est strictement domain-agnostic : applicable identiquement à des procédures médicales (diagnostic → bilan → traitement → suivi), réglementaires (saisine → instruction → décision → recours), aerospace (pre-flight → take-off → cruise → landing).

**Effort total extraction enrichie** : 8-12 jours dev + 2-3 jours ré-ingestion partielle (corpus de test).

---

## 3. Diagnostic gap EKX vs OSMOSE

### 3.1 Pattern EKX (rappel mémoire `project_ekx_inspiring_patterns`)

EKX (RAG+KG SAP interne, supposé Claude/GPT-based) testé sur questions ciblant ses faiblesses (false premise, evidence verbatim, entité fantôme, quantification). A passé les 4 proprement. 3 patterns supérieurs identifiés :

1. **SPARQL/Cypher avec filtres prédicat-sémantique dynamiques générés par LLM** : le LLM construit le filtre Cypher `WHERE p IN [USES, REQUIRES, DEPENDS_ON, RUNS_ON]` + `WHERE object MATCHES '(?i)BTP|Business Technology Platform'` selon l'intent.
2. **Exploration multi-formulation parallèle (entity expansion au query-time)** : 4-6 searches en parallèle sur entité + variantes lexicales + sous-composants AVANT la query précise.
3. **Distinction KG-evidence vs LLM-inference explicite dans la sortie utilisateur** : EKX étiquette explicitement "selon le graphe" vs "inférence architecturale".

### 3.2 État OSMOSE sur chacun de ces 3 patterns

| Pattern EKX | OSMOSE état actuel | Gap |
|---|---|---|
| **(1) Cypher dynamique prédicat-flexible** | ❌ Templates Cypher fixes paramétrés par `subject_canonical`. Pas de génération LLM des prédicats sémantiquement liés. Audit A4.7 montre que c'est le **bottleneck principal** (filtre exact `subject_canonical = $subject` rate 18/18 cas) | Critique |
| **(2) Multi-formulation parallèle au runtime** | 🟡 Partiel. `SubjectResolverV2` fait du resolving à l'extraction (variantes connues), mais runtime utilise top-1 du resolver. V5.1 a partiellement (`Voie A`) — pas runtime_v6 | Important |
| **(3) Distinction KG-evidence vs LLM-inference** | 🟡 Partiel. `ClaimFirst` force `verbatim_quote` à l'ingestion (clean côté KG). MAIS la sortie utilisateur Synthesize peut mélanger les 2 sans le signaler explicitement. UX presales gap | UX |

### 3.3 Analyse "pourquoi nos claims existent mais on n'arrive pas à les utiliser"

Sample 10 questions du bench A4.14 (`run_20260523_100040.json`) où mode=ABSTENTION malgré présence vraisemblable de claims pertinents. Vérification Neo4j directe (23/05/2026 PM) :

| # | id | Type | Question | Claim trouvé en KG ? (recherche text) | Hypothèse pourquoi pas utilisé |
|---|---|---|---|---|---|
| 1 | HUM_0028 | factual | "Quelle transaction est utilisee pour le WWI Monitor dans SAP EHS ?" | ✅ `claim_5bebb77ee026` "WWI Monitor (transaction CG5Z) monitors the report generation..." — subject="Monitor (transaction CG5Z)" | Parse échoué (Qwen3-235B JSON empty) ou subject canonical attendu "WWI Monitor" vs KG "Monitor (transaction CG5Z)" → mismatch exact filter |
| 2 | HUM_0017 | factual | "Quel role SAP est fourni pour le team lead dans le Payroll Control Center ?" | ✅ 3 claims `P_PYD_INST is required...` mais subject="P_PYD_INST" (l'objet d'auth, pas le rôle) | Subject de la question = "Payroll Control Center" ; KG indexe le claim sous "P_PYD_INST". Retrieval subject-based rate. RRF text aurait matché |
| 3 | HUM_0063 | factual | "Comment SAP S/4HANA utilise-t-il la recherche fuzzy HANA pour la classification commerciale ?" | ✅ `claim_463b2b65b190` "Trade classification proposals... use SAP HANA fuzzy search technology..." | Subject KG = "Trade classification proposals" ; question = "SAP S/4HANA / fuzzy". Multi-hop nécessaire |
| 4 | HUM_0005 | comparison | "Quelle est la difference entre les Release Information Notes de S/4HANA 2022 et 2023 ?" | ❌ Pas de claim avec "3145277" ou "3307222" trouvé | Soit claim absent KG (extraction loupée), soit indexé différemment. Doc présent (`027_SAP_S_4HANA_2023_Release_Information_Note`) mais claims précis non extraits |
| 5 | HUM_0033 | factual | "/SAPAPO/OM03 brief check" | ⚠ Cf A4.7 step 1+2 : top-1 ramène OM17 au lieu d'OM03 | Subject canonical trop générique ("transaction") — pas d'identifiant exact dans subject_canonical. BM25 sur text aurait matché OM03 |
| 6 | HUM_0049 | comparison | "Les deux guides d'installation (2021 et 2023) couvrent-ils le Management of Change de la meme facon ?" | ✅ probable (les deux docs en KG) | Comparison nécessite tool dédié `compare_by_axis(subject, axis=version)`. Inexistant. Sub_goal devient unmappable |
| 7 | HUM_0004 | comparison | "Le job /SCWM/R_ODO_POST_GI est-il mentionne dans les trois versions du Operations Guide ?" | À vérifier | Question intrinsèquement comparison cross-version, même verrou que #6 |
| 8 | HUM_0044 | multi_hop | "Que disent les documents sur les RFC destinations et la configuration reseau inter-systemes ?" | ✅ probable (claims sur RFC, network) | Question multi-hop "Que disent les documents sur X et Y" — requiert chaining. Pas de tool dédié multi-hop |
| 9 | GOLD_SAP_Q1_1 | false_premise | "Comment activer le module Embedded Reporting Studio dans S/4HANA Cloud Private Edition 2024 ?" | ❌ pas de claim "Embedded Reporting Studio" (n'existe pas dans SAP) | Le retrieval ne ramène rien (correct). Mais pipeline abstient sans expliquer "prémisse fausse" — judge récompense quand même l'abstention (1.0) |
| 10 | HUM_0080 | factual | "Quels codes statut existent pour les print requests WWI dans EHS ?" | ❌ pas trouvé "AA"/"ZS"/"ZD" en text | Soit doc absent KG, soit claim mal extrait (codes formels souvent perdus à l'extraction LLM) |

**Pattern dominant identifié (8/10) :** les claims pertinents existent dans le KG mais sont **indexés sous un `subject_canonical` différent du sujet utilisé par l'utilisateur** dans la question (HUM_0017, 0063, 0028 confirmés ; 0033, 0044, 0049, 0004, 0005 probables). Le filtre Cypher exact `subject_canonical = $subject` rate systématiquement.

**Verrou racine** : le pipeline d'ingestion peuple `subject_canonical` selon une logique de sujet structurel local du claim (ex "P_PYD_INST" parce que c'est le sujet grammatical), pas selon le **sujet attendu par une question utilisateur** (ex "Payroll Control Center" / "team lead role"). C'est un problème de granularité d'indexation, pas d'absence d'information.

### 3.4 Verrous architecturaux concrets identifiés

**Verrou V1 — Indexation subject-based trop fragile pour le retrieval Q&A.**
- **Preuve** : audit Oracle A4.7 → 18/18 questions ayant claims attendus en KG (cosine 0.80-0.93) → recall@5 retrieval strict = 0%.
- **Cause** : `subject_canonical` reflète le sujet grammatical du claim individuel, pas les multiples angles sous lesquels un utilisateur peut interroger le claim. Le retrieval Cypher filtre exact → mismatch systémique.
- **Solution** : (a) RRF BM25+Vector sur `claim.text` (bypass subject_canonical) + cross-encoder reranker, OU (b) Cypher dynamique LLM-generated qui élargit aux prédicats sémantiquement proches + alias d'entité.

**Verrou V2 — Pipeline Parse/Plan trop sensible aux échecs LLM amont.**
- **Preuve** : audit A4.13 + A4.14 → ~30% des questions Parse Qwen3-235B retourne JSON empty → fallback déterministe → sub_goal sans subject → Plan unmappable → 0 tool_call → Evaluate INSUFFICIENT → ABSTENTION.
- **Cause** : la chaîne Parse→Plan→Execute est strictement séquentielle ; toute défaillance amont propage. Pas de récupération.
- **Solution** : (a) re-tester DeepSeek-V3.1 sur Parse maintenant que RRF est isolé (A4.8 régressait via couplage Parse précis × filtre exact — n'existe plus si on adopte RRF/Cypher dynamique), (b) Plan plus tolérant (fallback hybride si subject=None, déjà partiellement en place), (c) Evaluate doit pouvoir AMBIGUOUS plutôt qu'INSUFFICIENT direct, et Plan re-décompose avec hints élargis.

**Verrou V3 — Pas de tools dédiés comparison ET multi_hop.**
- **Preuve** : C1 multi_hop = 0.10-0.15 (n=10), comparison = 0.10-0.50 (n=10), 8/10 questions de l'échantillon §3.3 nécessitent un tool dédié non existant.
- **Cause** : tools disponibles dans `Plan` sont `kg_claims`, `lifecycle_query`, `qdrant_sections`, mais pas `compare_by_axis(subject, axis)` ni `procedure_chain(subject, depth)`. Le sub_goal multi_hop ou comparison est reduced à kg_claims simple → claims isolés sans assembling.
- **Solution** : ajouter 2 tools dédiés en Phase B (`compare_by_axis` qui exploite `EVOLUTION_OF`/`SAME_AS` ; `procedure_chain` qui exploite nouvelles relations `STEP_OF`/`PREREQUISITE_OF` du Pattern B).

---

## 4. Recommandations actionnables

### 4.1 Tableau de pistes priorisées

| # | Piste | Effort (j) | Gain attendu (pp C1) | Risque | Source littérature |
|---|---|---|---|---|---|
| **R1** | **Cross-encoder reranker (bge-reranker-v2-m3) post-RRF** | 3-4 | +0.05 à +0.15 | Faible (latence +1s) | [Local AI Master 2026](https://localaimaster.com/blog/reranking-cross-encoders-guide), [BSWEN 2026](https://docs.bswen.com/blog/2026-02-25-best-reranker-models/) |
| **R2** | **Activer RRF Neo4j hybrid par défaut** (config A4.11-ter déjà codée) + bench rigoureux | 1-2 | +0.05 à +0.10 (en combinaison avec R1) | Moyen (sans R1, A4.15 a montré -0.14pp isolé) | [Tech Bytes Hybrid RAG 2026](https://techbytes.app/posts/hybrid-rag-search-bm25-embeddings-deep-dive-2026/) |
| **R3** | **Re-router Parse vers DeepSeek-V3.1** (Qwen3-235B JSON empty 30%) | 1-2 | +0.05 à +0.10 | Faible (sous RRF, le couplage qui a fait régresser A4.8 n'existe plus) | [config llm_models.yaml] |
| **R4** | **PredicateExpander LLM + Cypher dynamique (pattern EKX)** | 5-7 | +0.10 à +0.20 | Moyen (sécurité injection à border) | Pattern EKX + [SAT-Graph API arxiv 2510.06002](https://arxiv.org/abs/2510.06002) |
| **R5** | **Tools dédiés `compare_by_axis` + `procedure_chain`** (Phase B) | 4-6 | +0.10 à +0.15 (sur multi_hop + comparison) | Moyen | [StepChain GraphRAG arxiv 2510.02827](https://arxiv.org/html/2510.02827v1) |
| **R6** | **Hyper-relational extraction (qualifiers + procedures)** | 8-12 + 2-3 ré-ingestion | +0.10 à +0.20 (couvre L1+L3+L4) | Élevé (ré-ingestion partielle, drift) | [arxiv 2211.10018](https://arxiv.org/pdf/2211.10018), [TrustGraph reification 2026](https://trustgraph.ai/guides/key-concepts/graph-reification/) |
| R7 | False_premise detector pre-Synthesize (Mindful-RAG sufficiency check) | 2-3 | +0.05 (sur false_premise n=5) | Faible | [Mindful-RAG arxiv 2407.12216](https://arxiv.org/pdf/2407.12216) |
| R8 | Multi-formulation query (HyDE / MQRF) au query-time | 3-4 | +0.05 (descriptif) à neutre (factual) | Moyen (latence +1 LLM call) | [MQRF-RAG ACM 2025](https://dl.acm.org/doi/10.1145/3728199.3728221) |
| R9 | LightRAG flat graph dual-level retrieval (alternative à GraphRAG) | 10-15 (refonte partielle) | À mesurer | Élevé | [paperclipped.de 2026](https://www.paperclipped.de/en/blog/graph-rag-production/) |
| R10 | Re-build gold-set 50q post-A2.12 (doc_id matching propre) | 3 | Mesure fiable (gain de 0 actuel) | Faible | A4.7 piste E |
| R11 | LLM judge plus stable (taux judge_error ~35% sur run actuel) | 1 | Visibilité bench | Faible | A4.13 P2 |

### 4.2 Détail des 3 pistes top

#### Top 1 — R1 + R2 + R3 combinés : RRF + Cross-encoder + DeepSeek Parse

**Justification** : ce trio adresse simultanément les 2 verrous principaux V1 (retrieval fragile) et V2 (Parse fragile) en s'appuyant sur du code déjà écrit (RRF en A4.11-ter, code conservé inactif via toggle). Le cross-encoder est l'ajout le plus impactant single-step de la littérature 2026.

**Plan** :
1. (1j) Activer `V6_HYBRID_RETRIEVAL=rrf` par défaut + ajouter `os.environ.setdefault` dans bench script + ajouter log de config retrieval au démarrage (pour ne plus avoir l'épisode A4.15 où RRF n'était pas réellement actif).
2. (3-4j) Intégrer `BAAI/bge-reranker-v2-m3` : sentence-transformers local (~600MB) ou endpoint vLLM dédié. Refactor `ClaimFilter` pour appliquer rerank sur top-50 RRF → top-5. Tests unitaires + smoke.
3. (1-2j) Switcher Parse vers DeepSeek-V3.1 (revert partiel rollback A4.8, sur Parse seulement, garder Evaluate sur Qwen3 pour validation indépendante).
4. (1j) Bench 50q stratifié post-tout + 30q CP. Mesurer C1, par-type, latence, citation_coverage.

**Effort total** : **6-8 jours**.
**Gain attendu cumulé** : **+0.15 à +0.30pp** (croissance non additive, on parle d'un même bottleneck retrieval).
**Gate go/no-go** : C1 ≥ 0.60 sur 50q stratifié.

#### Top 2 — R4 : PredicateExpander LLM + Cypher dynamique (pattern EKX)

**Justification** : c'est le pattern qui distingue EKX (0.86) d'OSMOSE actuel (0.50). Domain-agnostic strict. Adresse V1 d'une manière complémentaire à R1/R2 (R1/R2 = robustesse statistique ; R4 = précision sémantique sur la requête).

**Plan** :
1. (3j) Module `PredicateExpander` : LLM call léger DeepSeek-V3.1 (~200 tokens) prend `(predicate_hint, subject_hint)` + sample des prédicats existants en KG, génère set de prédicats sémantiquement proches + alias d'entité. Cache LRU local (les sub_goals se répètent souvent).
2. (2j) Refactor `Execute.kg_claims` pour générer Cypher dynamique sécurisé (whitelist `predicate IN ['USES','REQUIRES',...]` validation contre liste KG actuelle, regex sur object_canonical avec garde anti-injection).
3. (2j) Bench 50q + ablation (avec / sans R4) pour mesurer contribution propre.

**Effort total** : **5-7 jours**.
**Gain attendu** : **+0.10 à +0.20pp** sur factual et multi_hop.
**Gate** : C1 multi_hop ≥ 0.30 (vs 0.15 actuel).

#### Top 3 — R6 : Hyper-relational extraction (qualifiers + procedures)

**Justification** : c'est le pattern structurellement le plus ambitieux mais le seul qui adresse réellement le trou multi_hop (C1=0.10-0.15) et comparison (C1=0.10-0.50). Sans cette couche, R4 et R5 plafonneront aussi (pas de chaîne pré-extraite à exploiter).

**Plan** :
1. (4j) Enrichir le prompt `ClaimExtractor` pour extraire `qualifiers` structurés + signaler `procedure_role` quand détecté. Tester sur 5 docs représentatifs (2 SAP + 2 PoC autre domaine si dispo).
2. (3j) Détecteur de procedures post-import : LLM batch sur les claims `procedure_role != None` du même doc, agrège en `:Procedure` avec sub-steps ordonnés. Persistance Neo4j.
3. (3j) Tool runtime `procedure_chain(subject, depth=3)` exploitable par Plan. Re-bench multi_hop spécifiquement.
4. (2-3j) Ré-ingestion partielle du corpus de test (28 docs SAP) avec nouveau prompt. Drift control.

**Effort total** : **8-12 jours + 2-3j ré-ingestion**.
**Gain attendu** : **+0.10 à +0.20pp** (concentré sur multi_hop, comparison, lifecycle).
**Gate** : C3 lifecycle ≥ 0.50 (cible Phase A non atteinte actuellement).

### 4.3 Pistes invalidées par cette session

Documenté pour ne plus les re-creuser sans nouveau signal :

- ❌ **RRF retrieval isolé sans cross-encoder** (A4.11 puis A4.15). Hypothèse de A4.11 "RRF winner" invalidée — variance n=20 + V6_HYBRID_RETRIEVAL pas réellement activé. A4.15 isolation propre → C1 -0.14pp. **Conclusion** : RRF est nécessaire mais pas suffisant ; doit être couplé à un reranker.
- ❌ **Cascade Qdrant systématique post-KG** (A3.10). C1 0.500 → 0.160 (-0.34pp). L'abstention salvatrice bat la cascade brute sur ce judge (false_premise 1.0 → 0.1). **Conclusion** : la cascade ne peut être qu'**ad-hoc et qualifiée**, pas systématique.
- ❌ **Switch LLM Synthesize** (A4.6). 3 LLMs (Qwen2.5-14B = DeepSeek-V3.1 685B = DeepSeek-V4-Pro flagship) → C1=0.250 identique sur 20q. **Conclusion** : le Synthesize n'est PAS le bottleneck quand les claims arrivent (et il ne hallucinerait pas non plus si les claims arrivaient).
- ❌ **GroundingVerifier ABSTAIN A4.5 comme amélioration de qualité** (mémoire `project_a44_root_cause_synthesize_hallucination` invalidée par A4.6). L'ABSTAIN cache les mauvaises réponses sans les corriger ; le judge récompense l'abstention. Pattern utile en production (ne pas mentir > mentir) mais pas comme amélioration de C1.
- ❌ **Tweak isolé sur prompt Synthesize / température / max_tokens** (sessions antérieures). Sans claims pertinents en entrée, aucun prompt ne sauvera la sortie.

---

## 5. Décision suggérée

Le décideur a 3 options structurantes à arbitrer. Les options sont **mutuellement non-exclusives** sur le moyen terme mais imposent des priorités différentes sur les 2-4 prochaines semaines.

### Option α — Industrialisation incrémentale du runtime KG-first (R1+R2+R3 puis R4)

**Trajectoire** : 6-8j R1+R2+R3 (retrieval robuste) → bench → si gate C1 ≥ 0.60 → 5-7j R4 (Cypher dynamique) → bench → si gate C1 ≥ 0.70 → R5 (tools dédiés). Total ~3-4 semaines.

**Pour qui** : si l'objectif est de livrer une Phase A+ "qualité production presales SAP" sans refonte structurelle. C'est la voie la plus prudente, la plus prédictible. Reste **strictement compatible** avec la VISION.md actuelle (KG-first, 5 modules, probability isolation).

**Contre** : ne touche pas au verrou structurel R6 (extraction trop pauvre). Plafond probable autour de C1=0.65-0.70 — sous les cibles VISION 0.80 pour C1, 0.50 pour C3.

### Option β — Refonte extraction + runtime tooling (R6 + R5 prioritaires)

**Trajectoire** : 8-12j R6 (hyper-relational extraction) + 2-3j ré-ingestion partielle → 4-6j R5 (tools dédiés) → 6-8j R1+R2+R3 retrieval polish → bench final. Total ~5-7 semaines.

**Pour qui** : si l'on accepte que les gates Phase A actuelles sont structurellement inatteignables sans enrichir le modèle de claims. C'est la voie qui adresse la VISION dans son intégralité (C3 lifecycle ≥ 0.50, multi_hop, comparison sérieuse).

**Contre** : risque ré-ingestion (drift, perte temporaire d'accès au corpus). Investissement upfront avant tout gain mesurable. Effort total ~7 semaines.

### Option γ — Hybride V5.1 fallback + KG-first incremental

**Trajectoire** : maintenir V5.1 Reading Agent comme route principale court terme (C1=0.45-0.62 mesuré, supérieur à runtime_v6 actuel 0.50) → R1+R2+R3 sur runtime_v6 en parallèle → router runtime décide en live (V5.1 si runtime_v6 abstient). En 4-6 semaines, basculer progressivement runtime_v6 comme primaire si gate passé.

**Pour qui** : si la priorité est de **ne pas régresser fonctionnellement** pendant la refonte et de pouvoir démontrer une qualité ≥ V5.1 en continu. C'est la voie la plus conservatrice opérationnellement.

**Contre** : double maintenance code pendant 4-6 semaines. Risque ne jamais déprécier V5.1 (le "fallback temporaire" devient permanent).

---

### Recommandation analyste (non-décisionnelle)

Aucune de ces options n'a de raison rédhibitoire. Les 3 sont défendables.

- **Option α** convient si l'on veut un livrable rapide et limiter le risque ; C1=0.65 plausible en 4 semaines.
- **Option β** convient si l'on accepte d'investir 7 semaines pour viser réellement les gates VISION ; C1=0.75 plausible mais non garanti.
- **Option γ** convient si la régression mesurée runtime_v6 < V5.1 (mémoire `project_runtime_v6_below_v51_alert`) est un signal politique fort dans l'organisation.

Le choix dépend de critères que seul le décideur produit a (deadline démo, tolérance refonte, état du fallback V5.1, signal externe sur extraction enrichie).

**Avant tout choix** : règler R10 (gold-set rebuild — préalable obligatoire ; toute mesure actuelle reste partiellement biaisée par le mismatch doc_id pré-A2.12) et R11 (judge stable). 4 jours combinés. Ces 2 fixes ne sont pas optionnels — sans eux, toutes les options ci-dessus mesureront un bruit de fond.

---

## 6. Annexe — sources externes

(Liste consolidée pour traçabilité. Inclut les sources A47 + ajouts session 23/05.)

**KG-RAG failure modes** :
- [What Breaks KG-based RAG? (arxiv 2508.08344)](https://arxiv.org/html/2508.08344v1)
- [Mindful-RAG (arxiv 2407.12216)](https://arxiv.org/pdf/2407.12216)
- [The Reasoning Bottleneck in Graph-RAG (arxiv 2603.14045)](https://arxiv.org/pdf/2603.14045)
- [Mitigating KG Quality Issues (arxiv 2603.14828)](https://arxiv.org/pdf/2603.14828)

**Hybrid retrieval** :
- [Tech Bytes Hybrid RAG 2026](https://techbytes.app/posts/hybrid-rag-search-bm25-embeddings-deep-dive-2026/)
- [Neo4j HybridCypherRetriever 2026](https://neo4j.com/blog/developer/enhancing-hybrid-retrieval-graphrag-python-package/)
- [Better RAG Accuracy with Hybrid BM25 + Dense (Medium 2026)](https://medium.com/@pbronck/better-rag-accuracy-with-hybrid-bm25-dense-vector-search-ea99d48cba93)
- [Hybrid Search Done Right (Medium feb 2026)](https://ashutoshkumars1ngh.medium.com/hybrid-search-done-right-fixing-rag-retrieval-failures-using-bm25-hnsw-reciprocal-rank-fusion-a73596652d22)

**Cross-encoder reranker** :
- [Local AI Master 2026 — Reranking guide](https://localaimaster.com/blog/reranking-cross-encoders-guide)
- [BSWEN 2026 — Best Reranker Models](https://docs.bswen.com/blog/2026-02-25-best-reranker-models/)
- [Ailog RAG — Cross-Encoder Reranking +40%](https://app.ailog.fr/en/blog/news/reranking-cross-encoders-study)

**Query expansion** :
- [HyDE + Query Expansion (Medium 2026)](https://medium.com/theultimateinterviewhack/hyde-query-expansion-supercharging-retrieval-in-rag-pipelines-f200955929f1)
- [MQRF-RAG (ACM 2025)](https://dl.acm.org/doi/10.1145/3728199.3728221)

**Microsoft GraphRAG + Neo4j** :
- [Microsoft GraphRAG (arxiv 2404.16130)](https://arxiv.org/pdf/2404.16130)
- [Neo4j GraphRAG Field Guide 2026](https://neo4j.com/blog/developer/graphrag-field-guide-rag-patterns/)
- [Graph RAG in 2026: What Works in Production (paperclipped.de)](https://www.paperclipped.de/en/blog/graph-rag-production/)
- [Boosting Q&A Accuracy with GraphRAG (NVIDIA)](https://developer.nvidia.com/blog/boosting-qa-accuracy-with-graphrag-using-pyg-and-graph-databases/)
- [Build GraphRAG Knowledge Graph Guide 2026 (Markaicode)](https://markaicode.com/graphrag-knowledge-graph-enhanced-retrieval-guide/)

**Bitemporal / Temporal KG** :
- [Zep / Graphiti (arxiv 2501.13956)](https://arxiv.org/html/2501.13956v1)
- [VersionRAG (arxiv 2510.08109)](https://arxiv.org/abs/2510.08109)
- [Memento bitemporal LongMemEval 92% (n1n.ai)](https://explore.n1n.ai/blog/building-bitemporal-knowledge-graph-llm-agent-memory-longmemeval-2026-04-11)

**Multi-hop & chains** :
- [StepChain GraphRAG (arxiv 2510.02827)](https://arxiv.org/html/2510.02827v1)
- [HELP HyperNode Expansion (arxiv 2602.20926)](https://arxiv.org/pdf/2602.20926)
- [LeanRAG semantic aggregation (arxiv 2508.10391)](https://arxiv.org/abs/2508.10391)
- [GraphRAG-Bench (arxiv 2506.02404)](https://arxiv.org/pdf/2506.02404)
- [LightRAG vs GraphRAG vs Graphiti 2026](https://www.paperclipped.de/en/blog/graph-rag-production/)

**Extraction granularity** :
- [Fact in Fragments — Atomic Fact Extraction (arxiv 2506.07446)](https://arxiv.org/pdf/2506.07446)
- [SocraticKG QA-Driven Fact Extraction (arxiv 2601.10003)](https://arxiv.org/html/2601.10003)
- [Hyper-Relational Cube-Filling (arxiv 2211.10018)](https://arxiv.org/pdf/2211.10018)
- [Hyper-relational KG Embedding (arxiv 2508.03280)](https://arxiv.org/html/2508.03280v1)
- [TrustGraph reification 2026](https://trustgraph.ai/guides/key-concepts/graph-reification/)
- [Direct Fact Retrieval (arxiv 2305.12416)](https://arxiv.org/pdf/2305.12416)
- [LINK-KG (arxiv 2510.26486)](https://arxiv.org/pdf/2510.26486)

**Deterministic agents** :
- [SAT-Graph API Deterministic Legal Agents (arxiv 2510.06002)](https://arxiv.org/abs/2510.06002)

**RAG evaluation** :
- [Scaling RAG with RAG Fusion: Industry Deployment (arxiv 2603.02153)](https://arxiv.org/pdf/2603.02153)
- [Practical RAG Evaluation Rarity-Aware (arxiv 2511.09545)](https://arxiv.org/pdf/2511.09545)
- [Reproducibility Limitations of RAG Systems (arxiv 2509.18869)](https://arxiv.org/pdf/2509.18869)

---

*Document produit le 2026-05-23 dans le cadre de la clôture Phase A. Auteur : analyse synthétique post-A4.14 / A4.15. Sources internes consultées : `doc/ongoing/A47_AUDIT_ORACLE_SYNTHESE.md`, `doc/ongoing/A411_BAKEOFF_RETRIEVAL_NUIT.md`, `doc/ongoing/A413_AUDIT_TYPES_ECHECS.md`, `doc/ongoing/A414_TIMEOUT_INVESTIGATION.md`, `doc/VISION.md`, `doc/ARCH_CLAIMFIRST.md`, `doc/ARCH_RETRIEVAL.md`, mémoires session.*
