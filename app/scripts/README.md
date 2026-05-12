# 🌊 OSMOSE — Scripts d'Administration

Catalogue des scripts utilitaires (~117 fichiers Python) pour gérer
l'infrastructure OSMOSE V2.

> **Convention** : tous les scripts s'exécutent depuis la racine du repo via
> `docker-compose exec app python scripts/<script>.py [options]`.

---

## 📂 Catégories

- [🩺 Diagnostic](#-diagnostic--audit-état-kgcorpus) — auditer l'état du KG / corpus, sans rien modifier
- [📊 Benchmark](#-benchmark) — mesurer la qualité du retrieval / extraction
- [🔧 Correctif](#-correctif--fix-cleanup-archive) — supprimer ou corriger des données existantes
- [♻️ Backfill / Rebuild](#-backfill--rebuild) — re-calculer une propriété sans tout reingérer
- [🔄 Migration](#-migration--changements-de-schéma) — changements de schéma one-shot
- [🛠️ Setup / Infra](#-setup--infra) — installer/configurer schémas, télécharger corpus
- [🧱 Build / Compute](#-build--compute) — pipelines d'enrichissement (atlas, perspectives, anchors, …)
- [🧪 Tests dev](#-tests-dev--scripts-de-validation-locale) — scripts de validation locale ad-hoc
- [🚀 POC / Demo](#-poc--demo) — prototypes, à promouvoir en prod ou archiver

> **⚠️ Candidats à archive (legacy/redondant)** : voir la section
> [Candidats archive](#-candidats-archive--cleanup-recommandé) en bas.

---

## 🩺 Diagnostic — audit état KG/corpus

Aucune écriture, lecture seule. Utiliser avant tout chantier qualité.

| Script | Rôle |
|---|---|
| `audit_chain_quality.py` | Qualité des chaînes claim → chunk → doc |
| `audit_claim_quality_thresholds.py` | Distribution confidence claims, calibration seuils |
| `audit_dimension_quality.py` | Couverture par dimension (axes, facets, perspectives) |
| `audit_entonnoir_pre_linking.py` | Audit pré-linking entités → claims |
| `compare_question_signatures.py` | Compare 2 indices de question signatures (v1 vs v2) |
| `diagnostic_facets_perspectives.py` | Distribution facets / perspectives, gaps |
| `diagnostic_locality.py` | Cohérence géographique des entités |
| `diagnostic_rerank_competition.py` | Quels chunks remontent / sont écartés au rerank |
| `diagnostic_triggers.py` | Vérifie quels triggers post-import sont actifs |
| `scope_analysis_dryrun.py` | Dry-run du scope analyzer V2 (anchor) |
| `survey_corpus_content.py` | Vue d'ensemble corpus (n docs, n claims, langues, etc.) |
| `validate_graph.py` | Sanity checks Neo4j (orphelins, types, consistency) |
| `validate_v2_inline.py` | Sanity inline V2 (rapide, no LLM) |

---

## 📊 Benchmark

| Script | Rôle |
|---|---|
| `bench_qwen3_235b_knowledge_extraction.py` | Bench claim extraction Qwen3-235B (TODO mémoire) |
| `bench_qwen3_extraction.py` | Bench claim extraction Qwen3 (variantes plus petites) |
| `bench_v2_mini.py` | Mini-bench V2 anchor-driven (5 questions, smoke) |
| `benchmark_kg_vs_no_kg.py` | OSMOSIS vs RAG pur — score global |
| `benchmark_llm_extraction.py` | Comparaison modèles d'extraction de claims |

> Bench full : voir aussi `benchmark/run_benchmark.py` et `benchmark/runners/run_osmosis_v2.py`.

---

## 🔧 Correctif — fix, cleanup, archive

Modifient le KG. **Lire le source avant exécution sur prod.**

| Script | Rôle |
|---|---|
| `archive_isolated_claims.py` | Archive les claims sans relations → `Claim_Archived` |
| `cleanup_garbage_entities.py` | Supprime les entités très génériques (IDF bas) |
| `cleanup_structured_forms.py` | Nettoyage structures redondantes |
| `consolidate_facet_roots.py` | Fusionne facets racine quasi-doublons |
| `consolidate_relations.py` | Fusion / dédup des relations |
| `deduplicate_existing_claims.py` | Détecte les claims doublons (même text, même doc) |
| `fix_anchored_in_textual.py` | Patch des anchored_in incorrects |
| `fix_axis_ordering.py` | Réordonne les ApplicabilityAxis ordinales |
| `fix_cluster_integrity.py` | Réintègre les clusters cassés |
| `fix_pass3_quotes.py` | Patch des quotes mal extraites Pass3 |
| `fix_resolution_status.py` | Recalcule le resolution_status après changement |
| `repair_orphan_protos.py` | Re-rattache les CandidateEntity orphelines |

---

## ♻️ Backfill / Rebuild

Recalcule une propriété ou une couche sans réingérer le PDF.
Idempotents (skip si déjà fait).

| Script | Rôle |
|---|---|
| `backfill_canonical_entities.py` | Reconstruit le mapping CanonicalEntity |
| `backfill_chunk_axis_values.py` | Set chunk.axis_value depuis claim |
| `backfill_claim_chunk_bridge.py` | Recrée les `MENTIONED_IN` claim → chunk |
| `backfill_claim_embeddings.py` | (Re-)calcule embeddings claim |
| `backfill_doc_lifecycle_status.py` | **CH-02.1** : DEPRECATED si SUPERSEDES, sinon ACTIVE |
| `backfill_facet_registry.py` | Reconstruit le registre Facet → claims |
| `backfill_lifecycle_relations_strict.py` | **CH-02.3** : LIFECYCLE_RELATION evidence-locked |
| `backfill_mentioned_in.py` | Recrée les liens MENTIONED_IN entité → claim |
| `backfill_qd_embeddings.py` | (Re-)calcule embeddings Qdrant |
| `backfill_qdrant_from_neo4j.py` | Repush des points Qdrant depuis le KG |
| `backfill_quality_status.py` | Recalcule le quality_status post-import |
| `backfill_relations_c4.py` | Backfill relations C4 (legacy contradictions) |
| `backfill_relations_c6.py` | Backfill relations C6 (legacy refines/qualifies) |
| `backfill_temporal_frame_claim_level.py` | **CH-02.4** : validity_start claim-level (LLM evidence-locked) |
| `rebuild_facets.py` | Reconstruction complète des facets |
| `relink_noun_chunks.py` | Re-rattache noun chunks aux claims |
| `relink_orphan_claims.py` | Recolle les claims orphelins (sans MENTIONED_IN) |
| `repersist_qdrant.py` | Re-persiste les points Qdrant (correction format) |
| `replay_phase28_subjects.py` | Replay phase 28 — subject extraction |
| `replay_qdrant_phase8.py` | Replay phase 8 — chunking + embeddings |
| `reset_proto_kg.py` | **Reset complet Proto-KG** (Neo4j + Qdrant) |
| `retrigger_orphan_claimfirst.py` | Re-trigger ClaimFirst sur claims orphelins |

---

## 🔄 Migration — changements de schéma

One-shot, à exécuter une seule fois lors d'une refonte.

| Script | Rôle |
|---|---|
| `migrate_context_id.py` | Renomme context_id → ... (one-shot) |
| `migrate_coverage_to_option_c.py` | Migration coverage_v1 → coverage_v2 (Option C) |
| `migrate_facets_v2.py` | Facets V1 → V2 |
| `migrate_lex_key.py` | Renomme lex_key → ... (one-shot) |
| `migrate_navigation_layer.py` | Migration navigation V1 → V2 |
| `migrate_passages_to_properties.py` | Passages embeddings → propriétés |
| `migrate_qs_crossdoc_v2.py` | Migration Question Signatures cross-doc V2 |
| `migration_canonical_key.py` | One-shot : ajout de canonical_key sur entités |

---

## 🛠️ Setup / Infra

À exécuter une fois au setup ou pour télécharger un nouveau corpus.

| Script | Rôle |
|---|---|
| `apply_doc_level_existing.py` | Applique doc-level extraction sur corpus existant |
| `backup_neo4j.py` | Backup Neo4j (dump) |
| `download_pmc_corpus.py` | Télécharge le corpus PubMed Central |
| `download_preeclampsia_corpus.py` | Télécharge le corpus Preeclampsia |
| `index_concepts_qdrant.py` | Indexe les concepts dans Qdrant |
| `setup_charspan_schema.py` | Crée le schéma Neo4j pour CharSpan |
| `setup_corpus_consolidation.py` | Setup corpus consolidation |
| `setup_relation_schema.py` | Crée constraints/indexes pour relations |
| `setup_wiki_schema.py` | Schéma pour Wiki / articles |

---

## 🧱 Build / Compute

Pipelines d'enrichissement post-import. Souvent appelés depuis le worker
(`post_import.py`) ou en batch via Atlas / FacetEngine.

| Script | Rôle |
|---|---|
| `build_narrative_topics.py` | **Atlas narratif** — community detection sur perspectives |
| `build_perspectives.py` | Construction des Perspectives (M2/CH-04) |
| `canonicalize_cross_lingual.py` | Canonicalisation cross-lingue des entités |
| `canonicalize_embedding_clusters.py` | Cluster d'embeddings → canonical entity |
| `canonicalize_entities_cross_doc.py` | Canonicalisation cross-document |
| `canonicalize_existing_entities.py` | Canonicalize sur entités déjà ingérées |
| `canonicalize_token_blocking.py` | Token-blocking pour speed-up canonicalization |
| `classify_contradictions.py` | Classifier 12-types LOGICAL_RELATION (V2-S3) |
| `cluster_cross_doc.py` | Clustering cross-doc des claims similaires |
| `compute_hub_scores.py` | PageRank-like sur le graphe |
| `compute_section_likelihood.py` | Probabilité de section (PDF parsing) |
| `detect_cross_doc_chains.py` | Détection chaînes claim cross-doc (T5) |
| `detect_existing_chains.py` | Détection sur chaînes déjà existantes (replay) |
| `detect_thematic_axes.py` | Détection des axes thématiques (atlas) |
| `detect_version_evolution.py` | Détecte l'évolution version → version |
| `enrich_entities_from_structured_form.py` | Enrichit entités depuis tableaux/formulaires |
| `enrich_existing_slots.py` | Enrichit les slots déjà extraits |
| `extract_question_signatures.py` | Extrait Question Signatures (V1) |
| `extract_question_signatures_v2.py` | **V2** — Question Signatures cross-doc |
| `generate_atlas.py` | ⚠️ POC — voir candidats archive |
| `generate_atlas_content.py` | **Atlas narratif (production, livré 01/05)** |
| `generate_robustness_questions.py` | Génère des questions de robustesse pour bench |
| `generate_surface_forms.py` | Génère les surface forms d'une entité |
| `resolve_subject_anchors.py` | Résout les subject anchors (anchor V1) |
| `resolve_subjects.py` | **Subject Resolver V2** (M1/CH-anchor) |
| `run_corpus_er.py` | Lance Entity Resolution sur le corpus |
| `run_facet_engine_v2.py` | FacetEngine V2 standalone |
| `run_pass2_on_existing.py` | Pass2 (entités) sur corpus existant |
| `summarize_lifecycle_dryrun.py` | Dry-run summary lifecycle |
| `sweep_subject_anchors.py` | Balayage des anchors (V2) |

---

## 🧪 Tests dev — scripts de validation locale

Pas dans `tests/` (ce sont des scripts ad-hoc, pas du pytest).
**Candidat naturel pour `app/scripts/_dev_tests/` ou `archive/`.**

| Script | Rôle |
|---|---|
| `auto_validate_runtime_v2.py` | Auto-validation runtime V2 (smoke quotidien) |
| `dryrun_qs_gating.py` | Dry-run question signature gating |
| `pass2_ab_test.py` | A/B test Pass2 (entités) |
| `reeval_t2t5_llm_judge.py` | Re-évaluation T2T5 avec autre juge |
| `rejudge_bench.py` | Re-judge un benchmark existant |
| `test_anchor_v2_s2.py` | Smoke V2-S2 anchor |
| `test_claim_extraction.py` | Smoke claim extraction |
| `test_concept_matching_p2.py` | Smoke concept matching P2 |
| `test_current_resolver_v2_s3.py` | Smoke Current Resolver V2-S3 |
| `test_dual_logging.py` | Smoke dual logging |
| `test_embeddings_1024d.py` | Smoke embeddings 1024d |
| `test_extraction_v2_complete.py` | Smoke extraction V2 complète |
| `test_extraction_v2_models.py` | Smoke modèles extraction V2 |
| `test_pipeline_v2_s4.py` | Smoke pipeline V2-S4 |
| `test_vision_gating.py` | Smoke vision gating |

---

## 🚀 POC / Demo

| Script | Rôle |
|---|---|
| `demo_cooccurrence.py` | Demo co-occurrence d'entités |
| `poc_evidence_pack.py` | POC bundle evidence pour drill-down |
| `poc_wiki_article.py` | POC génération article wiki |
| `poc_discursive` | (dossier POC) — voir contenu interne |

---

## 🗑️ Candidats archive — cleanup recommandé

À déplacer vers `app/scripts/_archive/` avec leur date d'origine.
**Validation user requise avant déplacement.**

| Script | Raison | Remplacement |
|---|---|---|
| `generate_atlas.py` | POC obsolète | `build_narrative_topics.py + generate_atlas_content.py` |
| `extract_question_signatures.py` | V1 obsolète | `extract_question_signatures_v2.py` |
| `backfill_relations_c4.py` | Legacy V1.1 | `classify_contradictions.py` (V2 12-types) |
| `backfill_relations_c6.py` | Legacy V1.1 | `classify_contradictions.py` |
| `migrate_context_id.py` | One-shot exécuté | `archive_done/` |
| `migrate_coverage_to_option_c.py` | One-shot exécuté | `archive_done/` |
| `migrate_lex_key.py` | One-shot exécuté | `archive_done/` |
| `migration_canonical_key.py` | One-shot exécuté | `archive_done/` |
| `replay_phase28_subjects.py` | One-shot rejoué | `archive_done/` |
| `replay_qdrant_phase8.py` | One-shot rejoué | `archive_done/` |
| `migrate_passages_to_properties.py` | One-shot exécuté | `archive_done/` |
| Tests `test_anchor_v2_s2`, `test_pipeline_v2_s4`, etc. | Smokes ad-hoc | `_dev_tests/` ou `archive/` |

---

## 🚀 Workflows typiques

### Reset Proto-KG complet (dev quotidien)

```bash
docker-compose exec app python scripts/reset_proto_kg.py
```

### Backup Neo4j avant chantier risqué

```bash
docker-compose exec app python scripts/backup_neo4j.py
```

### Audit qualité KG (quotidien)

```bash
docker-compose exec app python scripts/audit_chain_quality.py
docker-compose exec app python scripts/diagnostic_triggers.py
docker-compose exec app python scripts/validate_graph.py
```

### Backfill ciblé (post-CH-02 / CH-03)

```bash
docker-compose exec app python scripts/backfill_doc_lifecycle_status.py
docker-compose exec app python scripts/backfill_lifecycle_relations_strict.py --all
docker-compose exec app python scripts/backfill_temporal_frame_claim_level.py
```

### Build atlas narratif (post-import majeur)

```bash
docker-compose exec app python scripts/build_perspectives.py
docker-compose exec app python scripts/build_narrative_topics.py
docker-compose exec app python scripts/generate_atlas_content.py
```

---

## ⚠️ Avertissements

- Les scripts `cleanup_*`, `archive_*`, `repair_*` modifient le KG. **Backup avant.**
- Les `migrate_*` sont **one-shot** : exécuter une seule fois après refonte schéma.
- Les `replay_*` peuvent recalculer une phase — vérifier l'état avant.
- Les `reset_*` purgent — confirmer le scope (Proto-KG vs full KG).

---

## 🔗 Voir aussi

- `benchmark/` — runners + evaluators benchmarks
- `src/knowbase/api/routers/` — endpoints REST
- `doc/ongoing/` — chantiers en cours, ADRs, plans
- `kw.ps1` — script de gestion Docker (`./kw.ps1 info` pour les URLs)
