# Historique des Pivots OSMOSIS

> **Niveau de fiabilite** : Historique factuel. Dates et metriques issues des sources archivees. Certains chiffres sont des snapshots d'epoque, pas l'etat actuel.

*Document consolide — Mars 2026*

---

## 1. Timeline chronologique

```
2024                        2025                              2026
|                           |                                 |
Sept 2024                   Oct 2025                          Jan 2026        Mars 2026
|                           |                                 |               |
v                           v                                 v               v
[SAP KB]     [KnowWhere]   [OSMOSE]                          [Graph-First]   [KG2RAG]
RAG basique  Vision produit Hybrid Anchor + Neo4j Native      Le graph route  Le graph reorganise
Qdrant only  Semantic Core  2-pass pipeline, -70% temps       Qdrant valide   les chunks
```

### Evenements declencheurs de chaque pivot

| Date | Nom | Declencheur | Decision |
|------|-----|-------------|----------|
| **Sept 2024** | SAP KB | Besoin personnel de base de connaissances SAP | RAG vectoriel basique avec Qdrant |
| **Oct 2024** | KnowWhere | Les outils existants retrouvent des mots, pas le contexte narratif | Vision "Cortex Documentaire", extraction de concepts, cross-lingual |
| **Dec 2024** | Hybrid Anchor Model | Traitement a 35 min/doc, 11 713 concept-focused chunks/doc | Architecture 2 passes, -70% temps, -98% chunks |
| **Oct 2025** | OSMOSE / Neo4j Native | Graphiti stocke les facts comme texte dans les edges, pas comme entites structurees | Migration vers Neo4j custom, facts = first-class nodes |
| **Jan 2026** | Graph-First Architecture | Bug "semantic anchoring" — le mot "transformation" biaise vers le mauvais sens | Le KG devient le routeur, Qdrant devient la source de preuves |
| **Jan 2026** | Structural Graph (Docling) | Le linearizer aplatit la structure riche de Docling, on essaie de la reinferrer | DocItem nodes natifs, structure consommee structuree |
| **Mars 2026** | KG2RAG | Benchmark Sprint 0 — le bloc KG dans le prompt degrade les reponses de -8pp | Le KG reorganise les chunks, pas le prompt |

### Nomenclature

| Periode | Nom | Usage |
|---------|-----|-------|
| 2024 | SAP KB / KnowBase | Base de connaissances RAG pour documentation SAP |
| Oct 2024 - Oct 2025 | KnowWhere | "Le Cortex Documentaire des Organisations" |
| Nov 2025 - present | OSMOSE (code technique) / OSMOSIS (nom commercial) | Organic Semantic Memory Organization & Smart Extraction |

---

## 2. Les pivots architecturaux majeurs

### 2.1 Graphiti vers Neo4j Native (oct 2025)

**Probleme** : Graphiti stocke les facts comme texte dans les relations (edges), pas comme entites structurees. Detection de conflits a 500ms + LLM parsing. Timeline temporelle complexe a implementer.

**Decision** : Migrer vers Neo4j Native + Custom Layer. Facts = first-class nodes avec attributs structures (`subject`, `predicate`, `value`, `unit`).

**Impact mesure** :
- Detection conflits : 500ms + LLM → 50ms (comparaison directe)
- Workflow gouvernance : proposed → approved/rejected
- Timeline bi-temporelle : valid_time + transaction_time
- Effort : 10-12 jours, ROI < 1 mois

### 2.2 Bottom-up vers Stratified Reading (oct 2025 - jan 2026)

**Probleme** : L'approche "concept-focused chunks" generait des reformulations LLM pour chaque concept — 11 713 chunks par document, 35+ minutes de traitement, explosion combinatoire.

**Decision** : Architecture 2 passes (Hybrid Anchor Model).
- Pass 1 (socle, ~10 min) : extract → gate_check → relations → chunk → systeme exploitable
- Pass 2 (enrichissement, non bloquant) : classify_fine → enrich_relations → cross_doc

**Impact mesure** :

| Metrique | Avant | Apres | Amelioration |
|----------|-------|-------|-------------|
| Temps Pass 1 | 35+ min | ~10 min | **-70%** |
| Chunks / doc | 11 797 | ~180 | **-98%** |
| Batches embeddings | 2 950 | ~45 | **-98%** |

### 2.3 Concept-focused vers 2-pass Hybrid Anchor

**Probleme** : Les concept-focused chunks causaient une duplication semantique massive (ratio 140:1 entre concept-focused et chunks generiques). Corpus de 70 documents = 40+ heures de traitement.

**Decision** : 6 invariants non-negociables etablis :
1. Aucun concept sans anchor (tracabilite)
2. Aucun texte indexe genere par LLM (pas d'hallucinations)
3. Chunking independant des concepts (volumetrie previsible)
4. Neo4j = verite, Qdrant = projection
5. Pass 1 toujours exploitable (pas de dependance cachee)
6. Payload Qdrant minimal

### 2.4 Retrieval-first vers Graph-First (jan 2026)

**Probleme** : Bug "semantic anchoring" — la question "Quel est le processus de transformation d'une proposition commerciale en contrat executable ?" retournait les concepts "Digital Transformation" et "AI-assisted Cloud Transformation" au lieu de "Solution Quotation Management". Le mot "transformation" biaisait la recherche vectorielle vers le mot, pas le sens.

**Decision** : Le KG devient le routeur, Qdrant la source de preuves.

```
AVANT : Question → Embedding → Qdrant (chunks) → Top-K → Graph Context → Synthese
APRES : Question → Concept Seeds → Graph Paths → Evidence Plan → Qdrant (filtree) → Synthese
```

Trois modes de reponse : REASONED (chemin KG trouve), ANCHORED (ancrage structurel), TEXT-ONLY (rien dans le KG).

### 2.5 Vision in KG vers Vision UX-only (jan 2026)

**Probleme** : Tenter d'injecter le contenu visuel (schemas, diagrammes) dans le Knowledge Graph ajoutait de la complexite pour un benefice faible — les schemas visuels sont mieux presentes tels quels a l'utilisateur.

**Decision** : Les visuels restent dans la couche UX (thumbnails, preview). Le KG ne contient que des faits textuels verificables. Certaines questions benchmark PPTX ciblent des faits absents du corpus car presents uniquement dans des schemas visuels non extraits — c'est une limitation acceptee.

### 2.6 Bloc KG dans le prompt vers KG2RAG (mars 2026)

**Probleme** : Test empirique sur 50 questions — le bloc KG enrichi dans le prompt (SPO + tensions + QuestionSignatures, ~144 tokens) degrade les resultats.

| Metrique | Sans KG | Avec KG | Delta |
|----------|---------|---------|-------|
| factual_correctness | 0.40 | 0.32 | **-8pp** |
| false_idk_rate | 0.28 | 0.349 | **+6.9pp** |

Le LLM (Qwen 14B) construit un etat mental partiel a partir des SPO avant de lire les chunks, puis ne corrige pas.

**Decision** : Strategie "bloc KG dans le prompt" abandonnee. Nouvelle direction KG2RAG : le KG reorganise les chunks (ordre, selection, adjacence contradictoire) sans modifier le contenu du prompt.

### 2.7 IntentResolver : routing par type de question (mars 2026)

**Decision** : 4 types de questions avec strategies differentes :

| Type | Frequence | Strategie |
|------|-----------|-----------|
| A (factuel simple) | 70% | Chunks identiques au RAG, zero KG dans le prompt |
| B (comparatif) | 5% | KG identifie les docs en tension, chunks en adjacence contradictoire |
| C (audit/completude) | 20% | Toutes les entites via Entity→ABOUT + ClaimClusters, top_k=20 |
| D (comparable) | <5% | QuestionDimension match exact, reponse structuree |

---

## 3. Phases completees

### Phase 1 — Semantic Core v2.1 (oct 2025)

**Statut** : Complete (10 semaines, ~4 500 lignes, 62 tests)

**Livrable** : Pipeline d'extraction multilingue :
- TopicSegmenter (segmentation semantique)
- ConceptExtractor (NER + Clustering + LLM)
- SemanticIndexer (canonicalisation cross-lingual, seuil 0.85)
- ConceptLinker (linking cross-documents + DocumentRole)

**USP prouve** : FR "authentification" = EN "authentication" = DE "Authentifizierung" — language-agnostic knowledge graph sans hardcoded keywords.

### Phase 1.5 — Pilote Agentique (nov 2025)

**Statut** : Complete a 95% (6 agents, 18 tools, 13 458 lignes, 165 tests)

**Livrable** : Architecture agentique orchestree — Supervisor FSM, Extractor Orchestrator (routing NO_LLM/SMALL/BIG/VISION), Pattern Miner, Gatekeeper, Budget Manager, LLM Dispatcher.

**Cout maitrise** : $1.00/1000 pages PDF textuels, $3.08 complexes, $7.88 PPT-heavy.

### Phase 2.3 — InferenceEngine + Living Ontology (dec 2025)

**Statut** : Complete

**Livrable** : 6 types d'insights (transitive inference, bridge concepts, hidden clusters, weak signals, structural holes, contradictions). Graph-Guided RAG a 4 niveaux d'enrichissement (none=0ms, light=30ms, standard=50ms, deep=200ms).

Note : Living Ontology desactivee car genere trop de bruit en mode domain-agnostic.

### Phase 2.5 — Memory Layer (dec 2025)

**Statut** : Complete (~1 800 lignes, 14 endpoints API)

**Livrable** : Sessions persistantes, ContextResolver (resolution de references implicites — pronoms, references documentaires, ordinales), IntelligentSummarizer (3 formats : business, technical, executive), export PDF.

### Phase 2.7 — Concept Matching Engine (dec 2025 - jan 2026)

**Statut** : En cours (10% au moment de l'archivage dec 2025, puis supersede par la refonte ClaimFirst)

**Probleme resolu** : `extract_concepts_from_query()` etait casse — LIMIT 500 sur 11 796 concepts (96% ignores), filtre `len(word) > 3` eliminait AI, NIS2, IoT, DPO. Architecture cible 3 paliers (full-text Neo4j + vector Qdrant + fusion ranking).

### Phase B — Refonte ClaimFirst + Benchmark (jan-mars 2026)

**Statut** : Sprint 0 complete (10/10 livrables), Sprint 1 en cours

**Livrable** : Pipeline ClaimFirst (81 modules Python), benchmark 275 questions + 20 PPTX, double juge (Qwen + Claude, convergence 0.3%), strategie KG2RAG validee.

---

## 4. Roadmap macro actuelle

Roadmap sur ~45 semaines, revisee au fil des pivots :

| Phase | Semaines | Statut | Description |
|-------|----------|--------|-------------|
| Phase 1 | Sem 1-10 | Complete | Semantic Core v2.1, extraction multilingue |
| Phase 1.5 | Sem 11-13 | Complete (95%) | Pilote agentique, 6 agents + 18 tools |
| Phase 2 | Sem 14-24 | ~45% | Intelligence relationnelle (TaxonomyBuilder et TemporalDiffEngine non demarres) |
| Phase 2.3 | Sem 18-20 | Complete | InferenceEngine + Living Ontology |
| Phase 2.5 | Sem 25-28 | Complete | Memory Layer conversationnelle |
| Phase 2.7 | Sem XX | Supersede | Concept Matching Engine (absorbe par ClaimFirst) |
| Phase B | Jan-Mars 2026 | En cours | ClaimFirst pipeline + benchmark + KG2RAG |
| Phase 3 | Sem 29-32 | Non demarree | Multi-source simplifiee |
| Phase 3.5 | N/A | ~70% | Frontend Explainable Graph-RAG |
| Phase 4 | Sem 40+ | Non demarree | Production hardening, beta clients |

---

## 5. Gains mesures des pivots

### Gains quantitatifs

| Pivot | Metrique | Avant | Apres | Gain |
|-------|----------|-------|-------|------|
| Hybrid Anchor | Temps par document | 35+ min | ~10 min | **-70%** |
| Hybrid Anchor | Chunks par document | 11 797 | ~180 | **-98%** |
| Hybrid Anchor | Batches embeddings | 2 950 | ~45 | **-98%** |
| Neo4j Native | Detection conflits | 500ms + LLM | 50ms | **-90% + zero cout LLM** |
| Burst Mode (AWQ) | Vitesse inference | 3.2 t/s | 26.8 t/s | **8.5x** |
| KG2RAG | Factual Type A | 0.32 (avec KG prompt) | 0.40 (sans KG prompt) | **+8pp** |

### Gains qualitatifs

| Pivot | Gain |
|-------|------|
| Graph-First | Elimination du biais "semantic anchoring" (mots vs sens) |
| Structural Graph | Precision `item_type=TABLE` est une verite, pas une inference |
| ClaimFirst | 15 861 claims tracables jusqu'a la citation verbatim source |
| Domain-agnostic (INV-25) | Zero regex specifique a un domaine — fonctionne sur SAP, biomedical, reglementaire |

### Score global benchmark (Sprint 0, mars 2026)

| Dimension | Questions KG | Questions humaines |
|-----------|-------------|-------------------|
| T1 Factual | OSMOSIS +15pp | RAG +5.5pp |
| T2 Contradictions | **OSMOSIS 100% vs 0%** | OSMOSIS mieux |
| T4 Completude | OSMOSIS +19pp | OSMOSIS +5pp |
| T4 Tracabilite | OSMOSIS +10pp | Quasi-egal |

---

## 6. Lecons apprises

### Principes architecturaux valides

| Principe | Illustration |
|----------|-------------|
| **Structure > Inference** | DocItem nodes natifs vs parsing de markers textuels — 90% des sections etaient classees HIGH/MEDIUM, le filtre ne filtrait pas |
| **Graph-First > Retrieval-First** | Le KG route, Qdrant valide — elimine le biais vectoriel sur les mots polysemiques |
| **Preuves > Assertions** | Toute relation doit avoir evidence_ids — zero connaissance inventee |
| **Pass 1 standalone** | Systeme exploitable sans enrichissement — pas de dependance cachee |
| **Agnostic domaine** | POS-based, pas de whitelists metier — configuration via Domain Context JSON |

### Anti-patterns identifies

| Anti-pattern | Ce qui s'est passe | Lecon |
|-------------|-------------------|-------|
| Concept-focused chunks | Explosion combinatoire (ratio 140:1), 35 min/doc | Ne jamais generer de texte indexe par LLM |
| Graphiti pour Facts | Texte dans edges, impossible de comparer structurellement | Les facts doivent etre des entites structurees |
| Linearisation comme source | Structure riche de Docling aplatie puis re-inferred | Consommer la structure sous forme structuree |
| Retrieval-first RAG | Biais vectoriel ("transformation" → mauvais concept) | Le KG doit router, pas seulement enrichir |
| Bloc KG dans le prompt | -8pp factual, LLM construit biais initial | Le KG reorganise les chunks, il ne s'injecte pas dans le prompt |
| Living Ontology sans contexte | Trop de bruit en mode domain-agnostic | Desactiver les features qui ajoutent du bruit sans valeur |

### Decisions contre-intuitives qui ont paye

1. **Accepter 33% de refus plutot que risquer 25% de fausses reponses** — trade-off asymetrique. Un "je ne sais pas" est toujours moins grave qu'une reponse fausse.
2. **Ne pas implementer de regex transitoire** — implementer directement la cible. Chaque regex temporaire devient une dette technique permanente.
3. **Desactiver des features qui marchent** (Living Ontology, Research Axes) — mieux vaut pas de feature qu'une feature qui genere du bruit.

---

## 7. References archive

Tous les documents sources sont archives dans `doc/archive/pre-rationalization-2026-03/` :

| Source | Emplacement archive |
|--------|-------------------|
| Histoire du projet (jan 2026) | `OSMOSIS_PROJECT_HISTORY.md` |
| Roadmap integree v3.1 | `phases/OSMOSE_ROADMAP_INTEGREE.md` |
| Phase 1 Semantic Core | `phases/PHASE1_SEMANTIC_CORE.md` |
| Phase 2.5 Memory Layer | `phases/PHASE2.5_MEMORY_LAYER.md` |
| Status actuel (dec 2025) | `tracking/TRACKING-OSMOSE_STATUS_ACTUEL.md` |
| Ambition produit & roadmap | `phases/OSMOSE_AMBITION_PRODUIT_ROADMAP.md` |
| Sprint 0 rapport exhaustif | `ongoing/SPRINT0_RAPPORT_EXHAUSTIF.md` |
