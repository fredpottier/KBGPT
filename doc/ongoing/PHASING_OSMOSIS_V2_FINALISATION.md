# Phasing OSMOSIS V2 — Finalisation totale

*Date : 30 avril 2026*
*Statut : Plan d'exécution pour les chantiers restants*
*Référentiel : VISION_RECENTREE_OSMOSIS_2026-04-30*

## Périmètre couvert

Ce phasing adresse l'intégralité des chantiers identifiés post-V2 (S0→S5) :
1. Hygiène V2 + bugs critiques d'ingestion (Phase 1)
2. Pipeline V2 finalisation (synthèse LLM, Subject Resolver, UI drill-down) (Phase 2)
3. Bugs critiques production (Qwen dégen, cache markdown, dispatcher) (Phase 3)
4. Sprint résilience ingestion (Phase 4)
5. Polish & documentation (Phase 5)

**Estimation cumulative : 10-13 semaines** (pour réalisation séquentielle).

---

## Phase 1 — Hygiène V2 (1 semaine)

**Objectif** : nettoyer le KG et le code des artefacts V1.1 maintenant que V2 est validée.

### P1.1 Cleanup LIFECYCLE_RELATION conf 0.50
- Supprimer la relation CS-25 Amdt 26→25 à confidence 0.50 (peu fiable)
- Cypher direct : `MATCH ()-[r:LIFECYCLE_RELATION]->() WHERE r.confidence < 0.7 DELETE r`

### P1.2 Suppression physique runtime V1.1
- Modules à supprimer : `src/knowbase/runtime/orchestrator.py`, `query_resolver.py`, `evidence_planner.py`, `trust_evaluator.py`, `response_composer.py`, `personas.py`, `fallback.py`
- Routes API à retirer : `/api/runtime/*`, `/api/runtime_calibration/*`
- Frontend page `/chat/runtime` (V1) à supprimer

### P1.3 Purge LOGICAL_RELATION legacy
- Les ~10 289 edges marquées `legacy=true` depuis S0 (CONTRADICTS/REFINES/QUALIFIES historiques)
- Dump JSONL avant suppression pour forensics
- Cypher : `MATCH ()-[r:LOGICAL_RELATION]-() WHERE r.legacy = true DELETE r`

### P1.4 Documentation des suppressions
- Memory entry sur le pivot V1→V2 effectif

**Acceptation** :
- Aucune route `/api/runtime` accessible
- `MATCH ()-[r:LOGICAL_RELATION]-() WHERE r.legacy=true RETURN count(r)` = 0
- Pas de fichier `runtime/orchestrator.py`

---

## Phase 2 — Pipeline V2 finalisation (2-3 semaines)

**Objectif** : transformer le pipeline V2 en système production-grade avec UX complète.

### P2.1 Synthèse LLM finale dans le pipeline
- Ajouter une étape de synthèse après le retrieval claims
- LLM Qwen2.5-14B → réponse en prose 2-3 phrases citant les claims
- Si conflicts non-résolus → mention explicite « Le corpus présente plusieurs versions… »
- Si escalade → message clair en langue de la question

### P2.2 Subject Resolver V2 intégré au pipeline
- Remplacer le pré-retrieval Qdrant naïf par SubjectResolverV2 existant
- Pipeline étape 1 : extraire le sujet de la question
- Restreindre Anchor Filter / Current Resolver au sujet identifié
- Ambiguïté irréductible → remontée explicite au user

### P2.3 Calibration Current Resolver (fix T1.4 borderline)
- Ajuster les poids : recency 0.55 (au lieu de 0.50), centrality 0.10 (au lieu de 0.15)
- Tester sur le golden set 18 questions pour confirmer 95%+

### P2.4 Frontend drill-down cross-doc
- Cliquer sur un doc dans la réponse → naviguer vers ses claims
- Graph view des LIFECYCLE_RELATION + CONFLICT (mode Audit étendu)
- Filtre par anchor type / date

### P2.5 Multi-preset themes (Dark Elegance + Fusion) — tâche #17
- Finaliser les 2 thèmes UI manquants
- Switcher dans header

**Acceptation** :
- Pipeline V2 retourne une réponse en prose synthétisée
- Subject Resolver V2 intégré (pré-retrieval Qdrant retiré)
- Score validation Test 1 ≥ 95%
- UI : drill-down opérationnel + 2 thèmes alternatifs

---

## Phase 3 — Bugs critiques production (1-2 semaines)

**Objectif** : débloquer les pipelines d'ingestion qui ont des bugs en attente.

### P3.1 Cache markdown full_text vide
- Investiguer pourquoi `.md` → cache.extraction.full_text = ''
- Référence : memory `project_bug_md_cache_fulltext.md`
- Comparaison avec PDF qui marche
- Fix dans le pipeline d'extraction MD

### P3.2 Dispatcher /docs_in route vers Stratified V2 obsolète
- Fix : router vers ClaimFirst (le pipeline actuel)
- Référence : memory `project_dispatcher_docs_in_stale.md`
- Fichiers : `folder-watcher`, `jobs_v2.py`

### P3.3 Qwen2.5-14B dégénérescence ClaimFirst
- Investiguer cause des 433 erreurs / 0 claims sur WEF Presidio
- Hallucinations SAP cross-corpus + JSON dégénéré
- Référence : memory `project_bug_qwen_degeneration_claimfirst.md`
- Si root cause prompt → fix prompt
- Si root cause modèle → bench Qwen3-235B en remplacement

### P3.4 Facet linkage bloqué à 27%
- Reprendre approche embedding similarity sur facet.canonical_question
- Référence : memory `project_facet_linkage_chantier.md`
- 3 tentatives précédentes ont empiré (15.4%, 21.2%)

### P3.5 Bench Qwen3-235B sur extraction claims
- Si P3.3 ne résout pas Qwen2.5-14B → bench Qwen3-235B comme remplaçant
- Économie potentielle ~80% sur poste extraction

**Acceptation** :
- Cache .md génère un full_text non-vide
- /docs_in route vers ClaimFirst
- ClaimFirst fonctionne sur le corpus de test sans dégénérescence
- Facet linkage > 50%

---

## Phase 4 — Sprint résilience ingestion (4-6 semaines)

**Objectif** : rendre les imports robustes face aux interruptions (eviction spot, crash, etc.).

### P4.1 (L1) JobManager + state per-doc Redis
- Class `JobManager` qui suit chaque doc dans Redis : `pending`, `processing`, `done`, `failed`
- TTL 24h, recovery au démarrage
- Référence : pending tasks #20

### P4.2 (L2.A) Refactor claim_persister en méthodes granulaires
- Méthodes atomiques : `persist_claim`, `persist_chunk`, `persist_relation`
- Chaque step idempotent (MERGE)
- Référence : pending tasks #22

### P4.3 (L2.B) Callback on_block_complete
- claim_extractor déclenche callback à chaque bloc
- Callback met à jour Redis + persiste partiellement
- Référence : pending tasks #23

### P4.4 (L2.C) Logique reprise + 3 checkpoints orchestrator
- Checkpoints : post-extract, post-claim-persist, post-cross-doc
- Au démarrage : si checkpoint trouvé, reprendre à partir de là
- Référence : pending tasks #24

### P4.5 (L3) Cross-doc finalize en job RQ séparé
- Découpler le post-import (cross-doc analysis) en job RQ
- Permet de relancer le post-import sans re-extraire
- Référence : pending tasks #21

### P4.6 (L4) Pipeline V2 résilience
- Intégrer tout ce qui précède dans un pipeline cohérent
- Référence : pending tasks #26

### P4.7 (L5) Tests résilience + idempotence
- Tests : kill du worker au milieu d'un import → reprise OK
- Tests : double-import du même fichier → pas de duplicate
- Référence : pending tasks #25

**Acceptation** :
- Kill worker mid-import → reprise auto au restart
- Re-import du même fichier → idempotent
- 3 docs simultanés en parallèle sans interférence

---

## Phase 5 — Polish & documentation (1-2 semaines)

**Objectif** : rédiger les ADRs manquants, clore les side-quests stratégiques.

### P5.1 3 ADRs ciblés post-audit (préparation Armand)
- ADR_INGESTION_CONFIDENCE.md : seuils de qualité, échec d'ingestion explicite
- ADR_DOMAIN_PACK_LIFECYCLE.md : versioning, validation, déploiement
- ADR_RUNTIME_V2_OPERATIONAL.md : SLA, monitoring, disaster recovery

### P5.2 Atlas narratif — réflexion + light implementation
- Sortir du modèle "1 entité = 1 article"
- Atlas narratif 10-20 articles, sections dérivées des Perspectives V2
- Référence : memory `project_atlas_narratif.md`

### P5.3 Cockpit widget burst local
- Throughput tok/s temps réel, courbe, KV cache, prefix cache
- Source : vLLM `/metrics`
- Référence : memory `project_cockpit_widget_local_burst.md`

### P5.4 RAGAS re-benchmark V2
- Lancer compare_runs.py V2 vs V1.1 vs RAG pur
- Mesurer faithfulness, context_relevance
- Vérifier que V2 résout le gap -13.6 pts faithfulness identifié antérieurement

**Acceptation** :
- 3 ADRs Armand publiés dans doc/ongoing/
- Atlas narratif fonctionnel sur 1 sujet pilote
- Widget burst local affiché dans cockpit
- RAGAS V2 ≥ RAG pur sur faithfulness

---

## Total et planification

| Phase | Durée estimée | Cumul |
|---|---|---|
| Phase 1 — Hygiène V2 | 1 sem | 1 |
| Phase 2 — Pipeline finalisation | 2-3 sem | 3-4 |
| Phase 3 — Bugs critiques | 1-2 sem | 4-6 |
| Phase 4 — Résilience | 4-6 sem | 8-12 |
| Phase 5 — Polish & docs | 1-2 sem | 9-14 |

**10-14 semaines total** (~3 mois)

## Critères de validation globaux post-phasing

- ✅ Pipeline V2 production-ready avec synthèse LLM + Subject Resolver
- ✅ KG propre (aucune relation legacy)
- ✅ Ingestion robuste face aux crashs (resilience sprint)
- ✅ Bugs ingestion résolus (Qwen, cache MD, dispatcher, facet linkage)
- ✅ 3 ADRs Armand prêts
- ✅ UI complète avec drill-down + multi-themes

---

*Plan exécuté séquentiellement. Chaque phase produit son propre forensics + commit + memory entry de fin.*
