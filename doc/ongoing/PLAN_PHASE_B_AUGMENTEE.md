# Plan d'exécution Phase B augmentée — OSMOSE Runtime KG-first

> Date : 2026-05-23
> Statut : plan complet 5 phases, 6-9 semaines, ~32-43 jours effectifs.
> Référence : `doc/ongoing/ETAT_ART_KG_RAG_2026_DIAGNOSTIC_OSMOSE.md` (état de l'art + diagnostic post-Phase A).
> Cible : C1 ≥ 0.75 sur 50q stratifié (gate Phase A non atteinte = 0.500), C3 lifecycle ≥ 0.50, latence p50 ≤ 30s.

---

## Cadre

OSMOSE = produit OSS de KG-RAG bitemporal multi-corpus. Le corpus de test actuel est SAP par circonstance, pas par design. **Toute pièce de code, prompt, ADR ou doc produite par ce plan reste applicable identiquement à un corpus médical / réglementaire / juridique / aerospace.**

**LLM runtime** : strictement open-source serverless (DeepSeek-V3.1, Llama-3.3-70B, Qwen2.5-72B) via DeepInfra ou Together AI. Pas de Claude / GPT-4o en chemin critique.

**Discipline gate-driven** : à chaque phase, gate quantitative go/no-go. Si gate échoue → STOP, diagnostic, pas d'enchaînement aveugle.

---

## Position dans la roadmap globale

Ce plan constitue la **Phase B étendue** de `doc/EXECUTION_ROADMAP.md` (la Phase B initiale "validation cross-domain" est repoussée tant que C1 Phase A reste sous seuil).

**Entrée** : Phase A clôturée techniquement avec C1 = 0.500 (gate ≥ 0.75 non atteinte). Diagnostic formalisé dans `doc/ongoing/ETAT_ART_KG_RAG_2026_DIAGNOSTIC_OSMOSE.md`.

**Sortie attendue** : Runtime V6 avec extraction hyper-relationnelle + retrieval cross-encoder + tools multi_hop/comparison + Cypher dynamique. C1 ≥ 0.75 sur gold-set v3, conflict detection active, latence p95 ≤ 90s.

**Post-Phase B (si gates atteints)** :
- Phase B initiale validation cross-domain juridique/médical (préalable à pivot OSMOSE pour de vrai)
- Phase C UX click-to-source enrichi (productionisation)
- Si gates non atteints malgré plan complet → décision pivot architectural (réintégrer Reading Agent V5.1 comme route principale ou réorganiser le KG)

---

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PHASE 0 (4j)    │ Préalables mesure : R10 gold-set + R11 judge stable   │
├─────────────────┼───────────────────────────────────────────────────────┤
│ PHASE 1 (13-18j)│ R6 hyper-relational extraction + ré-ingestion        │
├─────────────────┼───────────────────────────────────────────────────────┤
│ PHASE 2 (6-8j)  │ R1 cross-encoder + R2 RRF activé + R3 DeepSeek Parse │
├─────────────────┼───────────────────────────────────────────────────────┤
│ PHASE 3 (4-6j)  │ R5 tools `compare_by_axis` + `procedure_chain`        │
├─────────────────┼───────────────────────────────────────────────────────┤
│ PHASE 4 (5-7j)  │ R4 PredicateExpander + Cypher dynamique (pattern EKX) │
└─────────────────────────────────────────────────────────────────────────┘
```

Total effort : **32-43 jours** nominal = ~6-9 semaines selon parallélisation. **Calendrier réel attendu : 42-56 jours (8-11 semaines)** avec buffer 30% (pattern historique sessions OSMOSE).

Note d'ordonnancement : la **Phase 2 peut commencer en parallèle de la Phase 1** (le retrieval robuste ne dépend pas du schéma claim enrichi). C'est même recommandé pour avoir un gain intermédiaire mesurable rapide tant que la Phase 1 d'extraction tourne.

---

## Phase 0 — Préalables mesure (4j)

**Objectif** : éliminer le bruit de fond avant tout autre investissement. Sans gold-set propre et judge stable, toute mesure ultérieure est partiellement non-actionnable.

### P0.1 — R11 Judge LLM stable (1j)

**Constat** : sur les benchs récents A4.14 / A3.10 / A4.15, ~35% des questions ont `judge_score = NaN` ou erreur de parsing JSON sur le LLM judge. Le `C1 mean` final exclut ces cas, donc le bench mesure 65% des questions effectivement notées.

**Tâches** :
- (P0.1.1) Audit logs récents (`grep "llm_judge failed"` sur les 3 derniers benchs) pour catégoriser les erreurs (empty response, JSON malformé, timeout)
- (P0.1.2) Refactor `bench_a38_runtime_v6.py:_llm_judge_call()` :
  - Retry exponentiel 3 tentatives (2s, 4s, 8s)
  - Parsing tolérant (extract `\{[^}]*"score"[^}]*\}` regex fallback si JSON entier rate)
  - Logger erreurs avec id question + type erreur en fichier séparé pour diagnostic
- (P0.1.3) Smoke 10q : taux d'erreur judge cible < 5%
- (P0.1.4) Si > 5% : switcher judge LLM (Qwen3-235B → DeepSeek-V3.1 ou Llama-3.3-70B-Turbo Together AI)

**Fichiers** : `app/scripts/bench_a38_runtime_v6.py`
**Gate P0.1** : taux d'erreur judge < 5% sur smoke 10q
**Risque** : faible

### P0.2 — R10 Gold-set v3 rebuild (2-3j)

**Constat A4.7** : le gold-set 50q actuel a été constitué pré-ré-ingestion A2.12. Le matching `expected_doc_id` se fait par hash suffixe (fragile). Toute mesure C1 absolue est biaisée d'~5-10%.

**Tâches** :
- (P0.2.1) Audit gold-set actuel (`benchmark/questions/gold_set_*`) — combien d'`expected_doc_id` n'existent plus dans le KG post-A2.12 ?
- (P0.2.2) Script `app/scripts/rebuild_gold_set_v3.py` :
  - Pour chaque question, recherche fuzzy le `expected_doc_id` actuel via titre + hash text suffixe + Qdrant section match
  - Si match ≥ 0.85 cosine : update `expected_doc_id` + `expected_claims` (re-look-up via subject/predicate)
  - Si match < 0.85 : flag manuel pour révision
- (P0.2.3) Validation : exécuter Oracle audit script (A4.7 step 1) sur gold-set v3 → recall@5 baseline mesurable
- (P0.2.4) **Validation humaine sample 20q (40% du gold-set)** stratifié par type : 6 factual + 4 multi_hop + 4 comparison + 3 lifecycle + 2 false_premise + 1 unanswerable. Pour chacune : vérifier que `expected_doc_id` mappé est bien le doc qui contient la réponse. Cas ambigus → flag manuel + 2nd avis.
- (P0.2.5) Persister `benchmark/questions/gold_set_sap_v3.json` + README rebuild + log validation

**Fichiers** : nouveau `app/scripts/rebuild_gold_set_v3.py`, nouveau `benchmark/questions/gold_set_sap_v3.json`
**Gate P0.2** : ≥ 95% questions ont `expected_doc_id` mappé + recall@5 Oracle baseline calculable + 0 faux positif sur sample 20q validé manuellement
**Risque** : moyen (matching fuzzy peut produire faux positifs ; validation 40% obligatoire)

---

## Phase 1 — Hyper-relational extraction (R6, 13-18j)

**Objectif** : enrichir le modèle Claim avec qualifiers structurés + extraire les chaînes procédurales. Adresser les limites L1 (claims atomiques sans qualifiers) et L3 (pas de chaînes pré-extraites) du diagnostic.

### P1.1 — Design schéma enrichi (2j)

- (P1.1.1) ADR `doc/ongoing/adr/ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS.md` :
  - Modèle `Claim.qualifiers: dict[str, Any]` (free-form mais documenté)
  - Modèle `Claim.procedure_role: Literal["PREREQUISITE", "STEP", "OUTCOME", None]`
  - Modèle `Claim.procedure_id: Optional[str]`, `Claim.step_index: Optional[int]`
  - Nouveau node `(:Procedure {procedure_id, name, domain_neutral_label})`
  - Nouvelles relations `(:Claim)-[:STEP_OF {order:int}]->(:Procedure)`, `(:Claim)-[:PREREQUISITE_OF]->(:Claim)`, `(:Claim)-[:OUTCOME_OF]->(:Claim)`
  - Migration : claims existants ont `qualifiers = {}`, `procedure_role = None`
- (P1.1.2) Schéma Pydantic + Cypher constraints
- (P1.1.3) Tests unitaires Pydantic + Neo4j upsert

**Fichiers** :
- nouveau `doc/ongoing/adr/ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS.md`
- `src/knowbase/claimfirst/models/claim.py` (extension)
- `src/knowbase/claimfirst/persist/neo4j_claim_writer.py` (qualifiers + procedure_role columns)
- nouveau `src/knowbase/claimfirst/models/procedure.py`
- migration Cypher dans `scripts/setup_neo4j_phase_b.py`

**Gate P1.1** : tests Pydantic + Cypher migration smoke passent
**Risque** : faible (purement structurel)

### P1.2 — Prompt ClaimExtractor enrichi (3-4j)

- (P1.2.1) Refonte prompt extraction (cf. `src/knowbase/claimfirst/prompts/extract_claims.md` ou équivalent) :
  - Ajouter section "QUALIFIERS" : pour chaque claim, demander si applicable `{applies_to_version, valid_from, valid_until, conditions, requires, applies_in_context_of}` (domain-agnostic)
  - Ajouter section "PROCEDURE" : si claim décrit une étape procédurale, extraire `procedure_role` + `step_index` + `procedure_name`
  - Few-shot examples : 3 exemples corpus SAP + 1 médical + 1 juridique (pour preuve domain-agnostic du prompt)
- (P1.2.2) Test extraction sur 5 docs représentatifs :
  - 2 corpus actuel (Operations Guide + Release Note)
  - 1 doc juridique libre de droits (extrait GDPR ou Bâle III)
  - 1 doc médical open access (protocole de soin PubMed)
  - 1 doc procédural quelconque (recipe, walkthrough)
- (P1.2.3) Audit qualité extraction : taux de claims avec qualifiers non vides (cible ≥ 30%), taux de claims avec procedure_role (cible ≥ 10% sur docs procéduraux)

**Fichiers** :
- prompts ClaimExtractor (chemin exact à confirmer dans le code)
- nouveau `app/scripts/audit_phase_b_extraction.py`

**Gate P1.2** : sur 5 docs test, ≥ 30% claims ont qualifiers, ≥ 10% ont procedure_role sur docs procéduraux
**Risque** : moyen (DeepSeek-V3.1 sur extraction enrichie peut faire des qualifiers trop libres → validation)

### P1.3 — Détecteur de procédures post-import (3j)

- (P1.3.1) Nouveau pipeline post-import : `app/scripts/post_import_p1_3_extract_procedures.py`
  - Pour chaque document avec ≥ 3 claims `procedure_role != None`, agréger en `:Procedure`
  - LLM batch (DeepSeek-V3.1) : ordonner les steps par `step_index` ou par cohérence narrative
  - Persister `:Procedure` node + `:STEP_OF` relations
- (P1.3.2) Détecteur `:PREREQUISITE_OF` cross-claim : LLM batch sur claims avec `qualifiers.requires` non vide → résoudre vers claim_id cible
- (P1.3.3) Détecteur `:OUTCOME_OF` cross-claim : pattern symétrique
- (P1.3.4) Intégration dans `app/scripts/post_import_pipeline_complete.py` (15 étapes existantes → ajouter étape 16 "extract_procedures")

**Fichiers** :
- nouveau `app/scripts/post_import_p1_3_extract_procedures.py`
- update `app/scripts/post_import_pipeline_complete.py`

**Gate P1.3** : sur corpus test (5 docs avec procédures), ≥ 5 `:Procedure` créés, ≥ 20 `:STEP_OF`, ≥ 5 `:PREREQUISITE_OF`
**Risque** : moyen (qualité dépend de l'extraction P1.2)

### P1.4 — Ré-ingestion partielle corpus de test (2-3j)

- (P1.4.1) Sélectionner 10 docs représentatifs du corpus (mix procédural + descriptif + lifecycle)
- (P1.4.2) Re-ingest avec nouveau prompt P1.2 + post-import P1.3
- (P1.4.3) Audit qualité : distribution `qualifiers`, distribution `procedure_role`, count `:Procedure`/`:STEP_OF`
- (P1.4.4) **Si Gate P1.4 passe** : ré-ingestion complète du corpus (38 docs) en nuit (~6-8h CPU)

**Fichiers** : aucun nouveau code, juste exécution + monitoring
**Gate P1.4** : sur 10 docs, qualifiers présents ≥ 30% des claims, `:Procedure` ≥ 5 instances
**Risque** : ré-ingestion partielle peut diverger des claims pré-existants (drift) ; mitigation = isoler corpus test sur tenant séparé pendant validation

### P1.5 — Bench Phase 1 (1j)

- (P1.5.1) Bench 50q gold-set v3 (P0.2) sur runtime_v6 actuel (sans changement runtime, juste KG enrichi)
- (P1.5.2) Mesurer ΔC1 vs baseline A4.14 (0.500)
- (P1.5.3) Audit ciblé multi_hop (n=10) et comparison (n=10) — gain attendu

**Gate P1.5** : C1 ≥ 0.55 (gain attendu +0.05pp minimum sur effet structurel KG enrichi seul, sans runtime amélioré)
**STOP rule** : si C1 < 0.50, suspendre Phase 1, diagnostic qualité extraction P1.2

---

## Phase 2 — Retrieval robuste (R1+R2+R3, 6-8j)

**Objectif** : adresser les verrous V1 (subject_canonical fragile) et V2 (Parse JSON empty) avec 3 leviers documentés ayant chacun un gain mesuré littérature.

**Note d'ordonnancement** : Phase 2 peut démarrer en parallèle de Phase 1 (P1.2-P1.3 sont lourds en ré-ingestion donc temps mort exploitable). Bench final post-Phase 2 sur gold-set v3 + KG initial (avant Phase 1) ET post-KG enrichi (après Phase 1).

### P2.1 — R2 Activer RRF par défaut + logging config (1-2j)

- (P2.1.1) Activer `V6_HYBRID_RETRIEVAL=rrf` dans `docker-compose.yml` (app + worker services)
- (P2.1.2) Logger config retrieval/LLM en début de chaque pipeline run :
  - `logger.info("[CONFIG] V6_HYBRID_RETRIEVAL=%s, MAX_WALL_CLOCK_S=%s, parse_llm=%s, evaluate_llm=%s, synthesize_llm=%s", ...)`
  - Évite épisode A4.15 (config supposée active mais ne l'était pas)
- (P2.1.3) Smoke 10q : vérifier dans logs que mode RRF est actif sur 100% des questions
- (P2.1.4) Vérifier index Neo4j vector + fulltext encore opérationnels (créés en A4.11) : `claim_embedding_idx`, `claim_text_search`

**Fichiers** : `docker-compose.yml`, `src/knowbase/runtime_a3/orchestrator.py` (logger config init)
**Gate P2.1** : 100% questions smoke utilisent RRF en logs
**Risque** : faible (code existant, juste activation)

### P2.2 — R1 Cross-encoder reranker bge-reranker-v2-m3 (3-4j)

- (P2.2.1) Préparation dépendances :
  - Vérifier `sentence-transformers` installé dans `app/Dockerfile` (probablement déjà car embeddings)
  - Pré-télécharger `BAAI/bge-reranker-v2-m3` dans `data/models/` ou laisser HuggingFace cache (~600MB, 1ère exécution lente)
- (P2.2.2) Nouveau module `src/knowbase/runtime_a3/reranker.py` :
  - Classe `CrossEncoderReranker` :
    - `__init__(model_name, device='cpu', batch_size=16)`
    - `rerank(query: str, claims: List[ClaimSummary], top_k: int = 5) -> List[ClaimSummary]`
  - Cache singleton (un seul chargement modèle par worker)
  - Logging latence + score distribution
- (P2.2.3) Intégration dans `claim_filter.py` :
  - Toggle env `V6_CROSS_ENCODER_RERANK=1` (défaut OFF, à activer post-tests)
  - Si activé : RRF top-50 → reranker top-5 → ClaimFilter cosine top-5 (chainage)
  - Sinon : RRF top-50 → ClaimFilter cosine top-5 (comportement actuel)
- (P2.2.4) Tests unitaires + smoke 10q (latence + qualité)
- (P2.2.5) Bench 50q gold-set v3 : C1 + latence + per-type

**Fichiers** :
- nouveau `src/knowbase/runtime_a3/reranker.py`
- `src/knowbase/runtime_a3/claim_filter.py` (extension)
- `app/Dockerfile` (si dépendance manquante)
- tests `tests/runtime_a3/test_reranker.py`

**Gate P2.2** : C1 ≥ 0.55 sur 50q (gain attendu +0.05 à +0.15pp vs Phase 2 sans rerank)
**Risque** : latence p95 monte de ~85s à ~90s (acceptable). Modèle 600MB CPU = OK, mais GPU si possible accélère ×3-5

### P2.3 — R3 Switch Parse DeepSeek-V3.1 (1-2j)

- (P2.3.1) Modifier `src/knowbase/runtime_a3/parse.py` :
  - Re-pointer `_invoke_llm` sur `TaskType.RUNTIME_PARSE_EVALUATE` (DeepSeek-V3.1 déjà config en yaml)
  - Garder Evaluate sur `TaskType.FAST_CLASSIFICATION` (Qwen3-235B) — séparation préservée
  - Update commentaire (rollback A4.8 annulé car RRF désormais actif → couplage subject exact détruit)
- (P2.3.2) Smoke 10q : taux Parse JSON empty cible < 5% (vs ~30% Qwen3-235B)
- (P2.3.3) Bench 50q : C1 + latence

**Fichiers** : `src/knowbase/runtime_a3/parse.py`
**Gate P2.3** : taux Parse fallback déterministe < 10%, C1 non-régressif
**Risque** : régression A4.8 répétée si RRF pas réellement actif → garde-fou P2.1.3 obligatoire

### P2.4 — Bench global Phase 2 + ablation (1-2j)

- (P2.4.1) Bench 50q gold-set v3 (ou v2 si P0.2 pas encore livré) avec R1+R2+R3 actifs
- (P2.4.2) Bench 30q ConflictPending (`benchmark/questions/gold_set_a38_30q_cp.json`) pour mesurer impact sur conflict_exposure
- (P2.4.3) **Ablation study** (3 configs au lieu de 5, ~2h chacune sur 50q) :
  - Config baseline : R1+R2+R3 désactivés (référence A4.14)
  - Config RRF only : R2 activé seul (mesurer effet RRF isolé)
  - Config complet : R1+R2+R3 (mesurer effet cumulé)
- (P2.4.4) Comparaison vs baseline A4.14 (C1=0.500) — quel levier contribue le plus ?
- (P2.4.5) Audit per-type : factual, multi_hop, comparison, false_premise

**Gate P2.4** : **C1 ≥ 0.60** sur config complet (gain attendu +0.10 à +0.20pp)
**STOP rule** : si C1 < 0.55, diagnostic profond avant Phase 3 (peut-être un des 3 ne fonctionne pas comme attendu, ou variance)

---

## Phase 3 — Tools dédiés multi_hop / comparison (R5, 4-6j)

**Objectif** : adresser le verrou V3 (pas de tool dédié) avec 2 tools qui exploitent la nouvelle couche structurelle de Phase 1.

### P3.1 — Tool `compare_by_axis` (2-3j)

- (P3.1.1) Spec : `compare_by_axis(subject_a, subject_b=None, axis: Literal["version", "edition", "region", "time"])`
  - Si `subject_b` non fourni : axis=version → exploite `EVOLUTION_OF` relations
  - Construit `StructuredDiff` (algorithme ADR §4.7.1 existant)
- (P3.1.2) Cypher : `MATCH (a:Claim)-[r:EVOLUTION_OF|SAME_AS|CONTRADICTS]-(b:Claim) WHERE a.subject_canonical = $subj RETURN a, b, r, type(r) as rel_type`
- (P3.1.3) Plan mapping : `SubGoalKind.comparison` → tool `compare_by_axis` (au lieu de `kg_claims` × 2 actuel)
- (P3.1.4) Synthesize handles `comparison` mode dedié avec template structuré

**Fichiers** :
- `src/knowbase/runtime_a3/execute.py` (nouveau `_call_compare_by_axis`)
- `src/knowbase/runtime_a3/plan.py` (mapping comparison → compare_by_axis)
- `src/knowbase/runtime_a3/schemas.py` (toolname literal)
- tests `tests/runtime_a3/test_compare_by_axis.py`

**Gate P3.1** : sur 10q comparison du gold-set v3, C1 comparison ≥ 0.50 (vs 0.10-0.50 actuel)
**Risque** : nécessite que les relations `EVOLUTION_OF` soient peuplées (faible coverage actuel 6.2%) → bénéficie de Phase 1

### P3.2 — Tool `procedure_chain` (2-3j)

- (P3.2.1) Spec : `procedure_chain(subject_or_procedure_id, depth=3)` retourne la chaîne complète depuis `:Procedure`
- (P3.2.2) Cypher : `MATCH (p:Procedure)<-[:STEP_OF {order: o}]-(c:Claim) WHERE p.procedure_id = $pid OR p.name CONTAINS $subject RETURN c, o ORDER BY o`
- (P3.2.3) Plan mapping : `SubGoalKind.multi_hop` + détection pattern procédural → `procedure_chain`
- (P3.2.4) Synthesize handles `multi_hop` mode dedié avec template séquencé (1., 2., 3., ...)

**Fichiers** :
- `src/knowbase/runtime_a3/execute.py` (nouveau `_call_procedure_chain`)
- `src/knowbase/runtime_a3/plan.py` (mapping)
- `src/knowbase/runtime_a3/synthesize.py` (template procédural)
- tests `tests/runtime_a3/test_procedure_chain.py`

**Gate P3.2** : sur 10q multi_hop du gold-set v3, C1 multi_hop ≥ 0.30 (vs 0.10-0.15 actuel)
**Risque** : nécessite que `:Procedure` + `:STEP_OF` soient peuplés → strictement dépendant de Phase 1

### P3.3 — Bench Phase 3 (0.5j)

- (P3.3.1) Bench 50q post Phase 2 + Phase 3
- (P3.3.2) Focus mesure multi_hop + comparison

**Gate P3.3** : C1 ≥ 0.65 cumulé + C1 multi_hop ≥ 0.30 + C1 comparison ≥ 0.40
**STOP rule** : si gates non atteintes, audit ciblé sur les claims/procedures non utilisés

---

## Phase 4 — Pattern EKX : Cypher dynamique (R4, 5-7j)

**Objectif** : adresser V1 d'une manière complémentaire à R1+R2+R3 (R1/R2 = robustesse statistique ; R4 = précision sémantique runtime). C'est le pattern qui distingue EKX (0.86) d'OSMOSE.

### P4.1 — Module PredicateExpander (3j)

- (P4.1.1) Pré-load : extraire toutes les `predicate` uniques du KG (probablement ~50-100 prédicats au total dans le corpus). Persister dans `data/cache/kg_predicates.json`
- (P4.1.2) Nouveau module `src/knowbase/runtime_a3/predicate_expander.py` :
  - Classe `PredicateExpander` :
    - `expand(sub_goal: SubGoal, top_k: int = 5) -> ExpandedFilter`
    - Input : `sub_goal.predicate_hint` + `sub_goal.subject_canonical`
    - Appel LLM léger DeepSeek-V3.1 (~200 tokens) : "Étant donné le hint X et la liste de prédicats KG [...], renvoyer top-5 prédicats sémantiquement proches"
    - Cache LRU 1000 entries (hint × predicates set hash)
  - Output `ExpandedFilter` : `{predicates: List[str], subject_aliases: List[str]}`
- (P4.1.3) Tests : sample 20 hints variés, vérifier que les expansions sont sémantiquement correctes

**Fichiers** :
- nouveau `src/knowbase/runtime_a3/predicate_expander.py`
- nouveau `data/cache/kg_predicates.json`
- tests `tests/runtime_a3/test_predicate_expander.py`

**Gate P4.1** : taux expansion pertinente ≥ 80% sur 20 hints test (validation manuelle)
**Risque** : faible (LLM call léger, fallback = pas d'expansion = behavior actuel)

### P4.2 — Cypher dynamique sécurisé dans Execute (2j)

- (P4.2.1) Refactor `Execute._build_kg_claims_cypher` :
  - Si `expanded_filter` fourni : `WHERE c.predicate IN $predicates AND (c.subject_canonical IN $subject_aliases OR c.object_canonical =~ $alias_regex)`
  - Whitelist prédicats : valider que tous les prédicats expandus existent dans `kg_predicates.json` (anti-injection)
  - Regex échappée + case insensitive `(?i)` borné — taille regex max 200 chars
- (P4.2.2) Orchestrator : si Parse OK + PredicateExpander activé, expand puis Execute avec filter dynamique
- (P4.2.2b) **Suite tests adversariaux Cypher injection** (`tests/runtime_a3/test_predicate_expander_security.py`) :
  - Test 1 — Injection patterns SQL-like : `predicate_hint = "USES'; MATCH (x) DETACH DELETE x; //"` → assertion blocked
  - Test 2 — Regex malveillants : `subject_aliases = ["(.*?){10000}", ".*?.*?.*?.*?.*"]` → assertion bound 200 chars
  - Test 3 — Prédicats hors whitelist : `expanded.predicates = ["FAKE_PREDICATE_NOT_IN_KG"]` → exception ValidationError
  - Test 4 — UTF-8 boundary cases : surrogates, BOM, null bytes, RTL marks → rejet
  - Test 5 — Tentative escape Cypher string : `subject = "' OR 1=1 --"` → escaped properly
  - Test 6 — Whitelist contournée via casse : `predicates = ["uses"]` vs whitelist `["USES"]` → strict equality enforced
  - Gate : 100% des 6 tests passent, aucune query non-whitelisted exécutée
- (P4.2.3) Toggle `V6_PREDICATE_EXPANSION=1` (défaut OFF jusqu'à validation)

**Fichiers** : `src/knowbase/runtime_a3/execute.py`, `src/knowbase/runtime_a3/orchestrator.py`, nouveau `tests/runtime_a3/test_predicate_expander_security.py`
**Gate P4.2** : 6/6 tests P4.2.2b passent + smoke 10q sans erreur
**Risque** : sécurité — whitelist stricte obligatoire

### P4.3 — Bench Phase 4 + bench complet final (2-3j)

- (P4.3.1) Bench 50q gold-set v3 avec R1+R2+R3+R5+R4 (toute la chaîne) — ~1h
- (P4.3.2) Comparaison vs baseline A4.14 + vs Phase 2 + vs Phase 3
- (P4.3.3) Bench 30q ConflictPending (`benchmark/questions/gold_set_a38_30q_cp.json`, existant) — mesurer GA3-9 conflict_exposure — ~30min
- (P4.3.4) Latence p50, p95, max
- (P4.3.5) **Ablation study** (3 configs clés au lieu de 5, ~1h chacune sur 50q = ~3h total) :
  - Config A baseline : R1+R2+R3+R5+R4 désactivés (référence A4.14 = C1 0.500)
  - Config B Phase 2 only : R1+R2+R3 actifs, R5+R4 désactivés
  - Config C complet : R1+R2+R3+R5+R4 actifs
  - Mesure : contribution Phase 3+4 = (Config C - Config B)

**Gate P4.3 (gate finale Phase B)** :
- **C1 ≥ 0.75** (cible roadmap Phase A)
- **C3 lifecycle ≥ 0.50**
- **Latence p50 ≤ 30s**, p95 ≤ 60s (relaxé à 90s si trade-off qualité)
- **Conflict exposure ≥ 15%** sur 30q CP (gate revue à la hausse — voir justification ci-dessous)

**Justification gate conflict_exposure ≥ 15%** : la gate ADR originale 5% était calibrée sur une époque où 0% baseline. L'objectif VISION C4 "détection tensions ~100% surface" exige bien plus. Sur 30q CP où l'on sait qu'au moins 60% portent un conflict explicite (CP marker `confidence < 0.85`), 15% est un minimum strict — un système réellement opérationnel devrait viser 30-50%. Si C4 reste à 5% après Phase B complète, cela signale que la mécanique conflict_pending_warning de Synthesize n'est jamais déclenchée par le Verifier, et il faut un audit séparé.

**STOP rule** : si C1 < 0.65, audit pour identifier le levier inopérant et re-itérer

---

## Risques transverses et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Variance LLM-judge masque les gains | Élevée | Élevé | P0.1 obligatoire avant tout bench |
| Gold-set rebuild produit faux positifs | Moyenne | Moyen | Validation manuelle sample 10 questions |
| Ré-ingestion Phase 1 corrompt le KG | Moyenne | Élevé | Snapshot Neo4j avant + tenant isolé pendant test |
| Cross-encoder CPU trop lent | Faible | Moyen | Fallback batch_size=8 + acceptation latence +1s |
| DeepSeek-V3.1 Parse plus lent que Qwen3 | Faible | Faible | DeepSeek déjà utilisé Synthesize, latence connue 5-10s |
| Cypher dynamique injection | Élevée si non bordée | Critique | Whitelist stricte prédicats + 6 tests fuzz P4.2.2b |
| Drift sémantique nouveaux prompts vs anciens claims | Élevée | Moyen | Marquer schéma `claim.extraction_version` + decision tree drift (cf Risque A) |
| Prompts optimisés Claude dev mais runtime DeepSeek/Llama | Moyenne | Élevé | Validation systématique par phase prompt-heavy (cf Risque B) |
| Calendrier réel dépasse 32-43j (pattern historique sessions) | Élevée | Moyen | Buffer 30% assumé → planifier sur 42-56j (8-11 sem). Checkpoints hebdo |

### Risque A — Drift sémantique entre versions d'extraction

**Détection** : à chaque ré-ingestion Phase 1, marquer chaque claim avec `extraction_version` (v1 = avant Phase 1, v2 = nouveau prompt hyper-relational). Bench sur sample mixte (50 questions sur claims v1 uniquement + 50 sur v2 uniquement).

**Decision tree si drift détecté avec ΔC1 > 0.10 entre versions** :

```
ΔC1(v1 → v2) > +0.10  : Drift positif — v2 supérieur
  → Option 1 : Re-ingestion complète corpus en v2 (+ 6-8h CPU, garantit cohérence)
  → Option 2 : Garder v1 pour docs non-procéduraux, re-extract v2 pour procéduraux seulement
  → Décision : favoriser Option 1 sauf si volume corpus rend re-ingestion infaisable

ΔC1(v1 → v2) < -0.05  : Drift négatif — v2 inférieur
  → STOP Phase 1, audit qualité prompt P1.2
  → Vérifier que qualifiers/procedure_role ne dégradent pas le subject_canonical ou predicate
  → Itérer prompt avant ré-ingestion complète

|ΔC1| < 0.05  : Pas de drift significatif
  → Continuer Phase 1 (KG bénéficie mais le runtime ne sait pas encore exploiter)
  → Le gain réel sera mesuré après Phase 3 (tools dédiés qui exploitent la nouvelle structure)
```

### Risque B — Validation LLM runtime OSS vs développement avec Claude

**Constat** : le développement (toi/moi) se fait avec Claude. Les prompts P1.2 (extraction enrichie), P3.1/P3.2 (tools dédiés), P4.1 (PredicateExpander) peuvent involontairement être optimisés pour Claude. En runtime, on utilise DeepSeek-V3.1 / Qwen3-235B / Llama-3.3-70B-Turbo (charte open-source). Risque : prompt fonctionne en dev mais échoue en runtime.

**Mitigation par phase prompt-heavy** :

À chaque tâche qui définit un prompt LLM destiné au runtime (P1.2, P3.1, P3.2, P4.1), ajouter une tâche `x.y.z-validation` :

```
- (Px.y.z-validation) Test prompt avec runtime LLM cible sur 5 samples :
  - Sample : 5 inputs représentatifs du futur usage runtime
  - Exécution : 3 LLM en bake-off (DeepSeek-V3.1 + Qwen3-235B + Llama-3.3-70B-Turbo)
  - Métriques objectives : taux de réponse non vide, taux de JSON valide, métrique tâche-spécifique
    (ex : pour P1.2 = taux claims avec qualifiers non vides ; pour P4.1 = taux expansion pertinente)
  - Gate : ≥ 80% sur métrique tâche-spécifique pour au moins 1 des 3 LLM
  - Si gate échoue : prompt à reformuler avant continuation
```

Cette mitigation ajoute ~0.5j par tâche prompt-heavy (4 tâches concernées = +2j budget total).

---

## Domain-agnostic check (charte AX-11)

Chaque livrable de ce plan doit respecter :

1. **Prompts ClaimExtractor (P1.2)** : few-shot avec 3 exemples corpus actuel SAP + 1 médical + 1 juridique. Pas de mention de SAP-spécifique dans les instructions générales.
2. **Tools `compare_by_axis` + `procedure_chain`** : axes universels (version, time, region, edition), pas d'`axis="sap_release"` ou similaire.
3. **PredicateExpander** : opère sur les prédicats observés dans le KG (data-driven), pas sur une liste hardcodée corpus-spécifique.
4. **Tests** : chaque module a au moins 1 test sur un cas non-SAP (synthetic ou small extract).
5. **ADR** : `ADR_PHASE_B_HYPER_RELATIONAL_CLAIMS.md` doit explicitement prouver l'agnosticité sur ≥ 2 corpus types.

**Sanction si violation** : revert + refonte.

---

## Plan d'exécution Nuit 1 (≈8-10h autonomes)

Vu que la séquence complète demande 32-43 jours, la nuit 1 démarre les éléments à **haute valeur, faible risque, autonomes** :

```
00:00-00:30  Pré-flight
             - git status clean
             - docker-compose ps (services up)
             - Backup Neo4j snapshot (sécurité avant tout changement)
             - Créer branche feat/phase-b-augmentee depuis main

00:30-02:30  P0.1 — Judge LLM stable
             - Audit logs récents (taux d'erreur judge actuel)
             - Refactor _llm_judge_call avec retry exponentiel + parsing tolérant
             - Smoke 10q : verif taux erreur < 5%
             - Si échoue : switch judge LLM (DeepSeek-V3.1 ou Llama-3.3-70B-Turbo)

02:30-03:30  P2.1 — Activer RRF par défaut + logging
             - V6_HYBRID_RETRIEVAL=rrf dans docker-compose.yml
             - Logger config retrieval/LLM en début pipeline (anti-épisode A4.15)
             - Smoke 5q : confirmer RRF actif dans logs

03:30-07:00  P2.2 — Cross-encoder reranker
             - Vérifier sentence-transformers dans Dockerfile
             - Télécharger BAAI/bge-reranker-v2-m3 (~600MB)
             - Coder src/knowbase/runtime_a3/reranker.py
             - Intégrer dans claim_filter.py (toggle V6_CROSS_ENCODER_RERANK=1)
             - Smoke 10q + tests unitaires
             - Si gate échoue (modèle DL fail, latence > 5s/q) : log + ne pas activer

07:00-08:00  P2.3 — Switch Parse DeepSeek-V3.1
             - parse.py : TaskType.RUNTIME_PARSE_EVALUATE
             - Smoke 10q : taux JSON empty < 5%

08:00-09:00  Bench 50q Phase 2 complet (R1+R2+R3 actifs)
             - Sur gold-set actuel (v2, gold-set v3 sera fait plus tard en Phase 0)
             - Mesurer C1, per-type, latence
             - Comparaison vs baseline A4.14 (C1=0.500)

09:00-10:00  Analyse + rapport + mémoires
             - Bilan ΔC1 par levier (avec ablation simple : RRF only vs +reranker vs +DeepSeek Parse)
             - Update mémoires session
             - Doc tracking dans doc/ongoing/PLAN_PHASE_B_AUGMENTEE_NUIT1.md
             - Commit propre branche feat/phase-b-augmentee

10:00+        Si gate P2.4 atteint (C1 ≥ 0.60) :
             - Préparation P0.2 gold-set rebuild (lecture script à écrire)
             - Ou démarrage P1.1 design schéma enrichi
             Si gate échoue :
             - Diagnostic profond + rapport décision matinale
```

### Pré-requis blocants pour la nuit

- Docker stack up + healthy (`./kw.ps1 status`)
- Snapshot Neo4j avant tout (sécurité totale, restoration en 5min si problème)
- Pas de redémarrage Docker pendant la nuit sans autorisation explicite (charte)
- Espace disque pour modèle bge-reranker-v2-m3 (~600MB) + HuggingFace cache

### Livrables fin de nuit 1 attendus

1. Branche `feat/phase-b-augmentee` avec commits propres
2. Judge LLM stable (P0.1 fait)
3. RRF activé par défaut + logging config (P2.1 fait)
4. Cross-encoder reranker intégré + toggle (P2.2 fait)
5. Parse DeepSeek-V3.1 (P2.3 fait)
6. Bench 50q Phase 2 complet : un C1 mesuré net contre baseline
7. Mémoires + doc tracking

### Hors scope nuit 1

- P0.2 gold-set v3 rebuild (2-3j, nécessite review humaine sur cas ambigus)
- Toute la Phase 1 (ré-ingestion lourde)
- Phase 3 (dépend de Phase 1)
- Phase 4 (en aval)

### Plan B nuit 1 — si P2.2 cross-encoder bloque

Si à 04:30 le téléchargement BAAI/bge-reranker-v2-m3 échoue OU latence > 5s/q OU OOM CPU/GPU :

```
04:30  Logger blocker + screenshot stack trace dans doc/ongoing/PLAN_B_NUIT1_BLOCKER.md
04:30-05:00  Skipper P2.2 — passer directement à P2.3 (Parse DeepSeek)
05:00-06:00  P2.3 Switch Parse + smoke
06:00-07:00  Bench 50q Phase 2 partielle (R1 désactivé, R2+R3 actifs)
07:00-08:00  Mesurer gain Phase 2 partielle vs baseline
             - Si C1 ≥ 0.55 : gain RRF+Parse seul confirmé, P2.2 reportée jour 2
             - Si C1 < 0.55 : signal fort, audit retrieval RRF + diagnostic matinal
08:00-10:00  Investigation cross-encoder alternative :
             - Modèle plus léger ms-marco-MiniLM-L-6-v2 (~80MB, plus rapide)
             - Endpoint Together AI cohere-rerank API (test compat charte OSS)
             - Bench séparé sur 10q pour valider modèle alternatif
```

**Principe Plan B** : ne jamais bloquer une nuit sur un seul composant. Si cross-encoder bloque, livrer Phase 2 partielle avec gain mesurable et reporter ré-attaque cross-encoder en jour 2 avec investigation déjà préparée.

---

## Validation requise avant lancement

- [ ] Plan complet validé par le décideur
- [ ] Branche `feat/phase-b-augmentee` autorisée
- [ ] Snapshot Neo4j autorisé
- [ ] Disponibilité DeepInfra / Together AI confirmée (clés API valides)
- [ ] Espace disque ≥ 2GB pour modèles + cache

---

*Document produit le 2026-05-23. Auteur : Claude (assistant Phase A clôture). Validation : décideur produit.*
