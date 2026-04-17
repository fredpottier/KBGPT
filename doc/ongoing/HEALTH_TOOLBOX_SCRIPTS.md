# Health Toolbox — Scripts de maintenance KG

*Date : 12 avril 2026*
*Objectif : identifier les scripts pertinents pour une toolbox permanente de santé du KG*

## Principe

Certains scripts créés initialement comme "one-time fix" s'avèrent utiles de manière récurrente :
- Après chaque import de nouveau corpus
- Après un incident (eviction spot, crash worker, corruption partielle)
- Comme vérification de santé périodique

## Scripts retenus pour la Health Toolbox

### 1. Diagnostic / Audit (lancer AVANT de corriger)

| Script | Rôle | Quand l'utiliser |
|--------|------|-----------------|
| `diagnostic_facets_perspectives.py` | Vérifie la couverture facets (GO/NO-GO pour Perspectives) | Après import, avant build Perspectives |
| `audit_chain_quality.py` | Audite la qualité des CHAINS_TO et structured_form enrichies | Après post-import, pour valider le KG |
| `audit_dimension_quality.py` | Analyse la santé du registre QuestionDimension, détecte les doublons | Après post-import |
| `audit_claim_quality_thresholds.py` | Audite les seuils qualité des claims via embedding | Périodique |
| `validate_graph.py` | Valide la séparation des couches (semantic vs navigation) | Après import |

### 2. Correctif / Réparation (lancer pour corriger un problème identifié)

| Script | Rôle | Quand l'utiliser |
|--------|------|-----------------|
| `backfill_canonical_entities.py` | Crée CanonicalEntity + SAME_CANON_AS pour entités orphelines | Après canonicalisation, si entités non liées |
| `enrich_entities_from_structured_form.py` | Crée des entités depuis structured_form pour claims orphelines | **P1 : claims sans ABOUT** |
| `deduplicate_existing_claims.py` | Déduplique claims par texte et triplet S/P/O | Après multi-import sur même corpus |
| `fix_cluster_integrity.py` | Répare l'intégrité des ClaimClusters (compteurs, clusters vides) | Après crash ou import partiel |
| `fix_resolution_status.py` | Corrige resolution_status sur les DocumentContexts | Après import, si statuts incohérents |
| `archive_isolated_claims.py` | Archive les claims sans relation structurante | Nettoyage périodique |
| `cleanup_garbage_entities.py` | Marque les entités VALID/UNCERTAIN/NOISY | Nettoyage périodique |
| `cleanup_structured_forms.py` | Valide et répare les structured_form_json | Après import |
| **`relink_orphan_claims.py`** | **À CRÉER** : re-lie les claims sans ABOUT aux entités existantes par normalized_name | **P1 : fix principal** |

### 3. Rebuild / Backfill (lancer pour reconstruire un aspect du KG)

| Script | Rôle | Quand l'utiliser |
|--------|------|-----------------|
| `rebuild_facets.py` | Reconstruit le FacetRegistry depuis les claims existantes | **P2 : facets vides** |
| `backfill_claim_embeddings.py` | Génère les embeddings des claims + index vectoriel | Après import, pré-bridge |
| `backfill_claim_chunk_bridge.py` | Crée les liens Claim↔Chunk (substring + embedding) | Après embeddings, pour le retrieval |
| `resolve_subjects.py` | Re-résout les ComparableSubjects sans ré-ingérer | **P3 : Perspectives sans subject** |
| `build_perspectives.py` | Construit les Perspectives (clustering + labellisation) | Après facets, après resolve_subjects |
| `detect_cross_doc_chains.py` | Crée les CHAINS_TO cross-doc depuis S/P/O | Après canonicalisation |
| `backfill_relations_c4.py` | Pipeline C4 Relations evidence-first | Post-import, détection contradictions |
| `resolve_subject_anchors.py` | Normalise SubjectAnchors via domain pack aliases | Après activation domain pack |
| `backfill_chunk_axis_values.py` | Peuple axis_values dans Qdrant depuis Neo4j | Après resolve_subjects |

### 4. Infrastructure / Reset

| Script | Rôle | Quand l'utiliser |
|--------|------|-----------------|
| `reset_proto_kg.py` | Purge et réinitialise le KG (modes: data-only, full, skip-reinit) | Changement de corpus |
| `backup_neo4j.py` | Export complet Neo4j → JSON | Avant toute opération destructive |
| `repersist_qdrant.py` | Re-persiste Qdrant Layer R depuis les caches | Après corruption Qdrant |

## Scripts NON retenus (à archiver ou supprimer)

### Migrations one-shot (obsolètes)
- `migrate_context_id.py`, `migrate_coverage_to_option_c.py`, `migrate_facets_v2.py`
- `migrate_lex_key.py`, `migrate_navigation_layer.py`, `migrate_passages_to_properties.py`
- `migrate_qs_crossdoc_v2.py`, `migration_canonical_key.py`
→ **Action** : déplacer dans `app/scripts/archive/`

### Fix one-shot (probablement obsolètes)
- `fix_anchored_in_textual.py`, `fix_axis_ordering.py`, `fix_pass3_quotes.py`
- `repair_orphan_protos.py`
→ **Action** : vérifier si encore pertinents, sinon archiver

### Tests / POC / Démos
- `test_*.py` (7 scripts), `poc_*.py` (2), `demo_*.py` (1)
- `download_pmc_corpus.py`, `download_preeclampsia_corpus.py`
→ **Action** : déplacer dans `app/scripts/tests/` et `app/scripts/poc/`

### Pipeline steps intégrés au post-import
- `backfill_facet_registry.py`, `cluster_cross_doc.py`, `extract_question_signatures*.py`
- `canonicalize_entities_cross_doc.py`, `canonicalize_existing_entities.py`
→ **Action** : conserver comme fallback manuel si le post-import échoue sur un step

## Script à créer : `relink_orphan_claims.py`

Script P1 de rattrapage qui :
1. Trouve toutes les claims sans ABOUT
2. Pour chaque claim, exécute l'extraction d'entités (regex déterministe, identique à EntityExtractor)
3. Pour chaque entité candidate, cherche l'Entity node par normalized_name dans Neo4j
4. Crée la relation ABOUT si le match est trouvé
5. Log les claims qui restent orphelines après rattrapage (vraies orphelines vs bug)

Estimation : ~5 min d'exécution, 0 appel LLM, purement déterministe.
