# Plateforme RAG Hybride (Qdrant + Graphiti) — North Star & Plan Phasé

Ce document décrit la vision cible, les principes d’architecture, et un plan de mise en œuvre phasé avec critères de passage stricts (« Aucune étape n’est validée tant que tous les critères ne sont pas atteints »). Il sert de référence unique aux équipes (humaines/IA) pour piloter, implémenter et valider l’avancement.

## 1) North Star (Ambition)
- Ingérer des documents hétérogènes (PPTX/PDF/Excel) avec **extraction unifiée** : un seul appel LLM Vision par slide produit simultanément chunks textuels (Qdrant) + entités/relations structurées (KG) depuis les sources complètes (texte brut + images + notes) avant toute condensation, garantissant contexte maximal et zéro coût additionnel.
- Soumettre entités/relations à une gouvernance (proposed → approved/rejected/merged) et alimenter le KG (Graphiti/Neo4j) avec identifiants canoniques stables.
- Relier les chunks Qdrant aux nœuds du KG (`related_node_ids`) pour un RAG hybride "graph-aware".
- Répondre en priorité avec des facts approuvés, puis compléter par des chunks candidats avec transparence (traçabilité sources).
- Multi‑domaine, traçable, time‑to‑value court pour tout onboarding.

## 2) Principes d'Architecture (non négociables)
- Séparation nette des responsabilités:
  - Qdrant = mémoire textuelle universelle (schéma core minimal stable), extensible via `custom_metadata`, infos techniques sous `sys`.
  - Graphiti/Neo4j = sémantique métier (entités, relations, temporalité) + gouvernance des facts structurés.
- **Dualité Entities vs Facts** (distinction critique):
  - **Entities** : Concepts/objets du domaine métier (ex: "SAP S/4HANA Cloud", "SAP Fiori", "Two-Tier ERP") → besoin de **canonicalisation** (normalisation noms variantes).
  - **Facts** : Assertions quantifiables avec valeur mesurable (ex: "SLA SAP S/4HANA PCE = 99.7%", "Rétention logs = 10 ans", "Limite quotas utilisateurs = 50k") → besoin de **détection conflits** (contradictions, obsolescence).
  - Workflows distincts mais complémentaires : entities → canonicalisation probabiliste (Phase 4), facts → gouvernance validation (Phase 3).
- **Extraction unifiée** (source-first): Un seul appel LLM Vision par slide extrait chunks + entities + relations + facts depuis sources complètes (texte brut + images + notes) avant condensation, garantissant qualité maximale avec zéro coût additionnel et cohérence parfaite.
- Normalisation en amont: canonicaliser au plus tôt (noms, dates, types), éviter scripts "correctifs" a posteriori.
- Lien explicite KG ↔ Qdrant: chaque chunk porte `related_node_ids` (candidats puis approuvés).
- Query Understanding (QU): couche qui transforme la question en intent + filtres (core) + graph_intent, avant les requêtes.
- Multi‑tenant & sécurité: propagation `group_id`, RBAC pour approbations/suppressions, traçabilité.
- Observabilité & tests: schéma validé en CI, métriques ingestion/extraction, tests E2E par phase.

## 3) Schéma Qdrant Cible (extrait)
```json
{
  "text": "...",
  "language": "en",
  "ingested_at": "2025-09-30T15:04:00Z",
  "title": "Slide 51 — Two-Tier ERP",
  "document": {
    "source_name": "Two-Tier-ERP_Q2_2025.pptx",
    "source_type": "pptx",
    "source_date_iso": "2025-09-27",
    "source_date_raw": "Month 00, 2025",
    "links": {
      "source_file_url": "https://.../presentations/Two-Tier-ERP_Q2_2025.pptx",
      "slide_image_url": "https://.../thumbnails/Two-Tier-ERP_Q2_2025_slide_51.jpg"
    }
  },
  "chunk": { "slide_index": 51 },
  "custom_metadata": {
    "solution": {"id":"S4_PUBLIC","name":"SAP S/4HANA Cloud, Public Edition"},
    "audience": ["CFO","CIO"]
  },
  "sys": {
    "tags_tech": ["pptx","megaparse_v2"],
    "prompt_meta": {"prompt_id":"slide_functional_v2_megaparse","version":"2024-09-23"}
  },
  "related_node_ids": {"candidates":[], "approved":[]},
  "related_facts": {"proposed":[], "approved":[]}
}
```

**Note** : `related_facts` contient les IDs des facts structurés extraits de ce chunk (ex: SLA values, limites quotas, rétentions). Séparés de `related_node_ids` car workflow différent (détection conflits vs canonicalisation).

## 4) Règle de passage entre phases
- Gate strict: « Aucune étape n’est validée tant que tous les critères de la phase ne sont pas atteints ».
- Chaque phase comporte: objectif, critères d’achèvement, impacts sur l’existant, tests de validation.

---

## Phase 0 — Production Readiness (Prérequis Critiques)
- Objectif
  - Garantir robustesse production, résilience, et sécurité AVANT tout développement fonctionnel.
  - Implémenter 6 prérequis critiques identifiés (cold start, idempotence, undo, backfill, fallback, tenancy).
- Critères d'achèvement
  - **Cold Start Bootstrap**: Script auto-promotion entités fréquentes (≥10 occurrences, confidence ≥0.8) en "seed canonicals".
  - **Idempotence**: Headers `Idempotency-Key` sur merge/create, responses cachées (TTL 24h), rejouabilité garantie.
  - **Undo/Split**: Endpoint `/canonicalization/undo-merge` transactionnel avec rollback Qdrant + audit trail.
  - **Quarantaine**: Merges avec délai 24h avant backfill massif Qdrant (undo possible).
  - **Backfill Scalable**: Batching (100 chunks), retries exponentiels, monitoring p95 latence <100ms, exactly-once.
  - **Fallback Extraction**: Pipeline découplé (chunks-only si extraction unifiée échoue), async retry entities.
  - **Tenancy & RBAC**: Matrice permissions (admin/expert/user), filtres group_id obligatoires, audit trail complet.
  - **Déterminisme**: Features + scores persisted avec version algorithme/embeddings/poids (reproductibilité).
- Impacts sur l'existant
  - Nouveau module `src/knowbase/canonicalization/bootstrap.py` (KGBootstrapService).
  - Nouveau module `src/knowbase/tasks/backfill.py` (QdrantBackfillService).
  - API: ajout headers Idempotency-Key, endpoint `/undo-merge`, cache Redis.
  - Config: `config/rbac_matrix.yaml` (permissions par rôle).
  - Pipeline: refactor `process_slide_with_fallback()` avec try/except découplés.
  - Audit: `src/knowbase/audit/logger.py` (AuditLogger pour toutes actions sensibles).
- Tests de validation
  - Cold start: Bootstrap 20+ seed entities sur nouveau domaine en <5min.
  - Idempotence: Replay merge 10× → résultat identique (bit-à-bit).
  - Undo: Merge + undo → état initial restauré (KG + Qdrant).
  - Backfill: 10 000 chunks updated en <2min, success rate ≥99.9%.
  - Fallback: Injection échec LLM unifié → chunks-only fonctionne 100%.
  - Tenancy: Tests isolement inter-tenants (KG + Qdrant) 100% OK.
  - Déterminisme: Replay canonicalisation → scores identiques (hash features matching).
- Documentation détaillée
  - Voir `doc/OPENAI_FEEDBACK_EVALUATION.md` pour justifications et code complet.

---

## Phase 1 — Stabiliser l'ingestion (Core Schema + Migration)
- Objectif
  - Appliquer le schéma Qdrant cible (core/custom/sys/related_node_ids) et normaliser les champs (dates ISO, `audience` liste, `title` au bon niveau).
- Critères d'achèvement
  - 95%+ des nouveaux chunks valident le schéma (CI + échantillon manuel).
  - `related_node_ids` présent par défaut (candidats/approved vides).
  - `prompt_meta` déplacé sous `sys`.
  - URLs déplacées sous `document.links`.
- Impacts sur l'existant
  - Refactor `ingest_chunks()` dans `src/knowbase/ingestion/pipelines/pptx_pipeline.py`.
  - Nouveau module `src/knowbase/ingestion/schema.py` (Pydantic) + helpers de normalisation (dates, listes, solutions canoniques).
  - Script de migration Qdrant (déplacer champs SAP vers `custom_metadata`, harmoniser types/dates, init `related_node_ids`).
- Tests de validation
  - Test de contrat de schéma (CI) sur 500 points scannés.
  - Ingestion d'un PPTX de test → inspection d'un sample de payloads.

## Phase 2 — Query Understanding (MVP) & Router
- Objectif
  - Ajouter une couche QU qui retourne `{intent, filters_core, graph_intent, keywords}` et route vers KG/Qdrant/hybride.
- Critères d’achèvement
  - Endpoint `/api/parse_query` renvoie un JSON stable sur 30 scénarios prédéfinis.
  - Router applique filtres core (source/date/lang/slide_index) et fallback hybride.
- Impacts sur l’existant
  - Nouveau service QU (règles+regex ou petit LLM), intégration côté chat service.
  - Docs d’usage et exemples.
- Tests de validation
  - Jeux de questions → sorties QU attendues; assertions sur filtres et intents.

## Phase 3 — Extraction Auto d'Entités/Relations/Facts (Proposed) via Extraction Unifiée + Gouvernance Facts
- Objectif
  - **Mutualiser l'appel LLM Vision existant** pour extraire simultanément `{chunks, entities, relations, facts_structurés}` depuis **sources complètes** (texte brut + images + notes) **avant condensation**, et pousser en statut `PROPOSED`.
  - **Dualité Entities vs Facts** :
    - **Entities/Relations** : Concepts et liens sémantiques (ex: "SAP S/4HANA Cloud", "utilise", "SAP Fiori") → workflow canonicalisation probabiliste (Phase 4)
    - **Facts structurés** : Assertions quantifiables avec valeur (ex: "SLA S/4HANA PCE = 99.7%", "Rétention données = 10 ans") → workflow gouvernance avec détection conflits
  - **Zéro coût LLM additionnel** : réutilisation de l'appel Vision déjà nécessaire pour la création de chunks.
  - **Qualité maximale** : extraction avec contexte complet (diagrammes, architecture visuelle, relations inter-slides) préservé.
  - **Résilience garantie** : Fallback découplé (chunks-only si extraction unifiée échoue) pour garantir ingestion critique même en cas d'échec partiel.
- Critères d'achèvement
  - `ask_gpt_slide_analysis()` renvoie le dict structuré `{chunks, entities, relations, facts}` sans dégrader l'ingestion Qdrant.
  - **Fallback découplé opérationnel** : Si extraction unifiée échoue (timeout/JSON invalide), pipeline bascule en chunks-only + planifie extraction entities asynchrone (taux échec <1%).
  - **Workflow Facts Gouvernance opérationnel** :
    - Endpoint `POST /api/facts` : Création facts avec statut `PROPOSED`
    - Endpoint `POST /api/facts/{id}/approve` : Validation par experts → `APPROVED`
    - Endpoint `POST /api/facts/{id}/reject` : Rejet avec motif → `REJECTED`
    - Endpoint `GET /api/facts/conflicts/list` : Détection automatique conflits (CONTRADICTS/OVERRIDES)
    - Endpoint `GET /api/facts/timeline/{entity}` : Historique temporel bi-temporel (valid_from/valid_until)
    - UI `/governance/facts` : Dashboard gouvernance avec métriques (proposed/approved/rejected/conflicts)
  - **Détection conflits automatique** : Algorithme détecte contradictions entre facts (ex: "SLA = 99.7%" vs "SLA = 99.5%") avec ConflictType (CONTRADICTS/OVERRIDES/DUPLICATES/OUTDATED).
  - 70%+ des slides non vides produisent ≥1 entité candidate + ≥1 fact structuré (confidence ≥0.7).
  - **Latence ingestion stable** : +0-10% max vs baseline (extraction parallèle dans même appel LLM).
  - **Cohérence parfaite** : chunks, entités et facts issus de la même analyse LLM (single source of truth).
  - **Monitoring résilience** : Logs structurés extraction_status (unified_success / chunks_only_fallback / failed), alertes si taux fallback >5%.
  - **Audit trail complet** : 100% actions loggées (created_by/approved_by/rejected_by + timestamps + reason).
- Impacts sur l'existant
  - Modif prompt `config/prompts.yaml` (section slide) : ajouter sections `entities[]`, `relations[]`, `facts[]` au schéma de sortie JSON.
  - `ask_gpt_slide_analysis()` : parser et valider les 4 sections (concepts, entities, relations, facts) avec validation JSON stricte.
  - **Refactor pipeline résilience** : `process_slide_with_fallback()` avec try/except découplés (chunks critique vs entities/facts best-effort).
  - `process_pptx()` : collecte entités/relations/facts deck-wide, dédoublonnage, envoie vers API facts (proposed) avec provenance (chunk_id/slide_id).
  - Nouveau module `src/knowbase/ingestion/extractors/entity_utils.py` : dédoublonnage fuzzy, normalisation entités.
  - **Nouveaux modules Facts Gouvernance** :
    - `src/knowbase/api/schemas/facts_governance.py` : Schémas FactBase, FactCreate, FactStatus (proposed/approved/rejected/conflicted), ConflictDetail
    - `src/knowbase/api/services/facts_governance_service.py` : Méthodes create_fact(), approve_fact(), reject_fact(), detect_conflicts(), get_timeline()
    - `src/knowbase/api/routers/facts_governance.py` : 9 endpoints REST API gouvernance
  - Task queue : job async `extract_entities_async` pour retry extraction failed slides.
- Tests de validation
  - Ingestion d'un deck de 50 slides → ≥ N entités + M facts proposed (N ≥ 5 entités/slide, M ≥ 2 facts/slide en moyenne).
  - Vérification traçabilité (provenance slide_index + source_name).
  - Comparaison qualité extraction vs baseline post-chunking (échantillon annoté) : rappel ≥+30%.
  - **Test résilience** : Injection échec LLM (timeout simulé) → chunks-only successful 100%, entities/facts planned async.
  - **Test workflow Facts Gouvernance** :
    - Création 20 facts structurés (ex: SLA, rétention, limites quotas) → statut PROPOSED
    - Création 2 facts contradictoires (ex: "SLA = 99.7%" vs "SLA = 99.5%") → détection automatique CONTRADICTS
    - Approbation expert 15 facts → statut APPROVED
    - Rejet expert 3 facts (motif: "Information obsolète") → statut REJECTED avec raison tracée
    - Timeline temporelle entity "SAP S/4HANA PCE" → historique complet des facts avec valid_from/valid_until
    - Dashboard gouvernance → métriques correctes (proposed: 2, approved: 15, rejected: 3, conflicts: 1)
  - **Test isolation multi-tenant Facts** : User1 ne voit pas facts créés par User2 (via group_id).
- Documentation détaillée
  - Voir `doc/UNIFIED_LLM_EXTRACTION_STRATEGY.md` pour architecture extraction unifiée complète.
  - Voir `doc/GRAPHITI_POC_TRACKING.md` Phase 3 pour implémentation complète Facts Gouvernance (schémas, services, API, tests).

## Phase 4 — Gouvernance & Canonicalisation Probabiliste (UI + KG Update)
- Objectif
  - Valider/rejeter/merger les entités candidates via **canonicalisation probabiliste** : suggestions automatiques avec scores multi-dimensionnels (string + semantic + graph context) pour faciliter décisions humaines.
  - Créer/mettre à jour les nœuds KG, répercuter dans Qdrant (`related_node_ids.approved`) avec **backfill scalable** et **réversibilité garantie**.
  - **Éliminer dictionnaires hardcodés** : ontologie émergente par validation assistée IA (multi-domaine sans recoder).
  - **Garantir production-readiness** : idempotence, undo transactionnel, quarantaine, multi-lingue.
- Critères d'achèvement
  - UI "Canonicalisation Queue" avec suggestions top-K, scores détaillés, evidence explainability, actions 1-clic (Merge/Create New/Reject).
  - Algorithme similarité multi-dimensionnel (string + semantic embeddings + graph context) avec ≥80% suggestions top-3 pertinentes.
  - **Normalisation multi-lingue** : Support EN/FR/DE/ES/CJK, variantes locales (centre/center), symboles commerciaux (™/®) retirés.
  - **Idempotence API** : Headers `Idempotency-Key` obligatoires sur merge/create, responses cachées (TTL 24h), rejouabilité garantie.
  - **Undo/Split transactionnel** : Endpoint `/canonicalization/undo-merge` avec rollback KG + Qdrant + audit trail.
  - **Quarantaine merges** : Délai 24h avant backfill massif Qdrant (fenêtre undo sans impact).
  - **Backfill scalable** : Batching (100 chunks), retries exponentiels, monitoring p95 <100ms, exactly-once, success rate ≥99.9%.
  - **Déterminisme canonicalisation** : Features + scores persisted avec version (algorithme/embeddings/poids), reproductibilité bit-à-bit.
  - **RBAC strict** : Matrice permissions (admin/expert/user), filtres group_id obligatoires, tests isolement 100% OK.
  - **Benchmark qualité** : Top-1 ≥70% / Top-3 ≥90% sur set annoté 500 samples multi-domaine.
  - Active learning: poids ajustés automatiquement selon feedback humain (+10% précision après 500 validations).
- Impacts sur l'existant
  - Nouveau module `src/knowbase/canonicalization/probabilistic_matcher.py` (algorithme similarité).
  - Nouveau module `src/knowbase/canonicalization/normalizer.py` (LocaleAwareNormalizer multi-lingue).
  - Nouveau module `src/knowbase/tasks/backfill.py` (QdrantBackfillService scalable).
  - Réutilise `FactsGovernanceService`; ajoute endpoints `/canonicalization/queue`, `/canonicalization/merge`, `/canonicalization/create-new`, `/canonicalization/undo-merge`.
  - API: Headers Idempotency-Key, cache Redis (résultats merge), audit trail (AuditLogger).
  - Frontend: nouvelle page `/governance/canonicalization` avec table interactive, bulk actions, diff preview.
  - Config: `config/rbac_matrix.yaml` (permissions par rôle).
  - Job de mise à jour Qdrant post‑approval avec quarantaine 24h (rétrofit chunks).
  - Migration progressive: dictionnaire SAP → entités KG (Phase 2), puis déprécation dictionnaire (Phase 6).
- Tests de validation
  - Scénario E2E: propose → suggestions calculées → merge 1-clic → nœud KG créé → quarantaine 24h → backfill Qdrant → `related_node_ids` mis à jour → recherche hybride exploite le lien.
  - **Test undo**: Merge → undo avant backfill → état initial restauré (KG + Qdrant).
  - **Test idempotence**: Replay merge 10× avec même Idempotency-Key → résultat identique.
  - **Test backfill scalable**: 10 000 chunks updated en <2min, p95 latence <100ms, success rate ≥99.9%.
  - **Test tenancy**: Isolement inter-tenants (user A ne voit pas entities user B), filtres group_id forcés.
  - **Test multi-lingue**: Normalisation "SAP Cloud ERP™" (EN), "Centre de données" (FR), "数据中心" (CJK) → matching correct.
  - Validation qualité suggestions: top-3 contient bonne réponse ≥80% cas (échantillon annoté 500 samples).
  - Benchmark canonicalisation: Top-1 ≥70%, Top-3 ≥90%, ERR ≥0.75.
  - Active learning: précision s'améliore après 500 validations (+10% min vs baseline).
- Documentation détaillée
  - Voir `doc/CANONICALIZATION_PROBABILISTIC_STRATEGY.md` pour architecture technique complète, algorithmes, UI, migration, et comparaison dictionnaire statique vs ontologie émergente.
  - Voir `doc/OPENAI_FEEDBACK_EVALUATION.md` pour justifications production-readiness (idempotence, undo, backfill, multi-lingue).

## Phase 5 — RAG Graph‑Aware v1 (Ranking & Génération “Facts‑First”)
- Objectif
  - Combiner score vectoriel et proximité graphe; générer des réponses priorisant facts `APPROVED` + transparence.
- Critères d’achèvement
  - Formule de ranking: `final = α*vector + β*graph_proximity + γ*metadata_boost` tunée sur banc d’essai.
  - ≥80% des requêtes factuelles répondent uniquement avec facts approuvés (sur jeu interne).
- Impacts sur l’existant
  - Module ranking hybride; adaptation synthèse pour injection “facts‑first”.
- Tests de validation
  - NDCG@10 amélioration mesurée vs baseline vector‑only.
  - Vérification citations/sources.

## Phase 6 — Industrialisation (Multi‑agent, Probabiliste, Events, Observabilité)
- Objectif
  - Réduire le bruit, accélérer la revue, scaler.
- Critères d’achèvement
  - Pipeline multi‑agent (LLM propose → règles/NER filtrent → graph‑matching dédoublonne).
  - Canonicalisation probabiliste (suggest top‑k merge 1‑clic) en UI.
  - Événements (pub/sub) clés: `chunk.ingested`, `entities.proposed`, `entity.approved`, `kg.updated`, `qdrant.reindexed`.
  - Tableaux de bord (ingestion, extraction, promotion, usage filtres/intents).
- Impacts sur l’existant
  - Bus d’événements (Redis Streams/Kafka/NATS sous feature‑flag).
  - UI “merge suggestions”, métriques & logs structurés.
- Tests de validation
  - Réduction 40–60% des faux positifs (échantillons labellisés).
  - −50% du temps de revue/100 entités.

---

## 5) Risques & Parades (Enrichis via Feedback OpenAI)
- **Rigidification (SAP‑centré)** → Séparer core/custom; sémantique dans le KG; tests multi‑domaine.
- **Bruit d'extraction** → Multi‑agent + suggestions probabilistes + human‑in‑the‑loop.
- **Dette de migration** → Script unique "rewrite payload" + tests; rollback par collection.
- **Sur‑complexité** → Démarrage simple, features en drapeau (QU, events, ranking β/γ).
- **Faux positifs merge** → Seuils + multi-signal (2 dimensions fortes) + undo transactionnel + quarantaine 24h avant backfill massif Qdrant.
- **Explosion mises à jour Qdrant** → Batching (100 chunks), idempotency keys, backpressure sur file update, métriques lag (p95 <100ms).
- **Drift poids active learning** → Versionner poids, A/B test sur sous-ensemble, rollback possible.
- **Sur-couplage LLM (extraction unifiée)** → Fallback découplé (chunks-only) + validation JSON stricte + retries ciblés async.
- **Multi-tenant: fuite croisée** → Forcer group_id en clause obligatoire toutes requêtes (KG/Qdrant/API), tests isolement inter-tenants.
- **Évolution embeddings** → Plan migration vectorielle (double-write temporaire, backfill asynchrone, compat layer).
- **False-merge non détecté** → Audit trail complet (qui a mergé quoi, quand, pourquoi), undo transactionnel, quarantaine avant impact massif.

## 6) KPI Transverses (Enrichis via Feedback OpenAI)
- **Qualité schéma**: ≥95% chunks conformes (CI + audits réguliers).
- **Promotion**: taux proposed→approved; temps médian de validation **≤30s/entité**.
- **Pertinence**: NDCG@10, taux réponses "facts‑only".
- **Onboarding**: temps d'intégration d'un nouveau domaine ≤ 1 semaine.
- **Canonicalisation**: Top-1 accuracy ≥70% / Top-3 accuracy ≥90% / ERR ≥0.75 sur benchmark 500 samples multi-domaine.
- **Backfill Qdrant**: p95 latence <100ms par batch 100 chunks, success rate ≥99.9%, exactly-once garanti.
- **Résilience extraction**: Taux échec extraction unifiée <1%, fallback chunks-only 100% fonctionnel.
- **Tenancy**: Tests isolement inter-tenants (KG + Qdrant) 100% passés, aucune fuite croisée.
- **Audit trail**: 100% actions sensibles loggées (merge/undo/delete) avec user_id + timestamp + raison.
- **Production readiness**: Cold start bootstrap <5min, idempotence 100% testée, undo transactionnel validé.

## 7) Annexes (référence rapide)

### Différence Entities vs Facts (Exemples Concrets)

**ENTITIES** (nécessitent canonicalisation):
```json
{
  "name": "SAP Cloud ERP",
  "entity_type": "PRODUCT",
  "description": "Suite ERP cloud de SAP",
  "candidates_canonical": [
    {"name": "SAP S/4HANA Cloud, Public Edition", "score": 0.85},
    {"name": "SAP Business Suite", "score": 0.15}
  ]
}
```
→ **Problème** : Nom variante, besoin de normaliser vers entité canonique
→ **Solution** : Canonicalisation probabiliste (Phase 4) avec suggestions top-K

**FACTS** (nécessitent détection conflits):
```json
{
  "subject": "SAP S/4HANA Cloud, Private Edition",
  "predicate": "SLA_garantie",
  "object": "99.7%",
  "fact_type": "SERVICE_LEVEL",
  "status": "proposed",
  "valid_from": "2024-01-01",
  "source_chunk_id": "chunk_uuid_123",
  "confidence": 0.95
}
```
→ **Problème** : Si autre fact dit "SLA = 99.5%", détection automatique CONTRADICTS
→ **Solution** : Workflow gouvernance (Phase 3) avec validation expert + timeline temporelle

### Événements (pub/sub) — grammaire minimale:
- `chunk.ingested {chunk_id, doc_id}`
- `entities.proposed {chunk_id, candidates:[...]}`
- `facts.proposed {chunk_id, facts:[...]}`
- `entity.approved {entity_id, canonical_id}`
- `fact.approved {fact_id, conflict_resolved: bool}`
- `kg.updated {node_ids:[...]}`
- `qdrant.reindexed {chunk_ids:[...]}`

### Ranking hybride (démarrage): `α=0.6, β=0.3, γ=0.1` (à tuner).

### **Extraction unifiée LLM** (référence détaillée):
- Document technique : `doc/UNIFIED_LLM_EXTRACTION_STRATEGY.md`
- Analyse coûts/bénéfices : `doc/ANALYSE_LLM_PIPELINE_OPTIMISATION.md`
- Principe : UN appel Vision par slide → `{concepts, entities, relations, facts}`
- Économie : 0€ additionnel, 0s latence additionnelle, qualité +30% vs post-chunking
- **Dualité Entities/Facts préservée** : LLM extrait simultanément concepts sémantiques ET assertions quantifiables
### **Canonicalisation Probabiliste** (référence détaillée):
- Document technique complet : `doc/CANONICALIZATION_PROBABILISTIC_STRATEGY.md`
- Algorithme similarité : string (30%) + semantic (50%) + graph (20%)
- Ontologie émergente : élimination dictionnaires hardcodés, multi-domaine sans recoder
- Active learning : amélioration continue via feedback humain

### **Facts Gouvernance** (référence détaillée):
- Documentation tracking complet : `doc/GRAPHITI_POC_TRACKING.md` (Phase 3)
- Implémentation complète backend :
  - Schémas : `src/knowbase/api/schemas/facts_governance.py` (12 classes Pydantic)
  - Service : `src/knowbase/api/services/facts_governance_service.py` (10 méthodes)
  - API : `src/knowbase/api/routers/facts_governance.py` (9 endpoints REST)
  - Tests : `tests/integration/test_facts_governance.py` (16 tests)
- Workflow : proposed → approved/rejected, détection conflits (CONTRADICTS/OVERRIDES), timeline bi-temporelle
- UI Admin : `frontend/src/app/governance/*` (dashboard, pending, conflicts, facts)
- Status : ✅ Code 100% implémenté (tests nécessitent infrastructure Neo4j active)

### **Production Readiness (Feedback OpenAI)** (référence détaillée):
- Évaluation complète : `doc/OPENAI_FEEDBACK_EVALUATION.md`
- 6 prérequis critiques P0 : cold start, idempotence, undo, backfill, fallback, tenancy
- Solutions techniques implémentables : code Python complet pour chaque point
- Effort estimé : ~15 jours Phase 0 (critiques) + ~8 jours Phase 1-2 (importants)

---

Notes de mise en œuvre
- Ce plan est auto‑portant: les principes d’architecture, gates, critères et tests suffisent à guider les développements sans document additionnel.
- Les IA de développement peuvent créer des sous‑tâches par phase à partir des critères d’achèvement et des impacts listés.
