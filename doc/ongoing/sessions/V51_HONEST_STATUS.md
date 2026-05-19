# V5.1 — Status Honnête (audit 2026-05-13)

*Audit demandé par Fred : "pourquoi S3.5 est toujours pending ?"*
*Réponse : parce que j'ai marqué `completed` des sprints dont seule la **prep** était livrée, pas l'**exécution**.*

---

## Distinction des 4 niveaux de complétion

Pour chaque sprint/sub-sprint, on distingue :

| Niveau | Description |
|---|---|
| **L1** Architecture | Modules + interfaces + Pydantic schemas livrés |
| **L2** Tests unit | Tests unit avec mocks/in-memory |
| **L3** Tests intégration | Tests intégration mockés (LLM mock, Neo4j live) |
| **L4** Exécution prod | Lancé sur vrai LLM avec vrai corpus |

Marquer un sprint `completed` quand seul L1+L2+L3 est atteint **trompe** le suivi. La vraie complétion exige L4 (ou explicit "exécution post-Phase 1").

---

## Audit par sprint CH-52

| Sprint | L1 Arch | L2 Unit | L3 Intég | L4 Prod | Décompte honnête |
|---|---|---|---|---|---|
| **S0** Validations bloquantes | ✅ | n/a | n/a | ✅ | ✅ Sprint COMPLET |
| **S1** DSG Neo4j multi-tenant | ✅ | ✅ | ✅ | ✅ (38 docs migrés réels) | ✅ Sprint COMPLET |
| **S2** Ingestion atomique | | | | | |
|   ↳ S2.1 section_id stable | ✅ | ✅ (32 tests) | ✅ e2e Neo4j | n/a | ✅ COMPLET |
|   ↳ S2.2 Redlock | ✅ | ✅ (14 tests) | ✅ 50 threads | n/a | ✅ COMPLET |
|   ↳ S2.3 Two-phase publish | ✅ | ✅ (11 tests) | ✅ Neo4j live | n/a | ✅ COMPLET |
|   ↳ S2.0 Bench extractors | ❌ | ❌ | ❌ | ❌ | ⏸️ **DIFFÉRÉ** (bench Docling vs SmolDocling) |
|   ↳ S2.4 Object store text_uri | ❌ | ❌ | ❌ | ❌ | ⏸️ **DIFFÉRÉ** |
|   ↳ S2.5 Cache versioning contract | ❌ | ❌ | ❌ | ❌ | ⏸️ **DIFFÉRÉ** |
|   ↳ S2.6 ClaimFirst integration | ❌ | ❌ | ❌ | ❌ | ⏸️ **DIFFÉRÉ** |
| **S3** ReadingTools (14 tools) | | | | | |
|   ↳ S3.1 ToolRegistry | ✅ | ✅ (27 tests) | n/a | n/a | ✅ COMPLET |
|   ↳ S3.2 Migration 7 POC tools | ✅ | ✅ (12 tests) | n/a | ✅ (smoke utilise) | ✅ COMPLET |
|   ↳ S3.3 ToolCallSanitizer | ✅ | ✅ (16 tests) | n/a | n/a | ✅ COMPLET |
|   ↳ S3.4 navigate/footnotes/refs | ✅ | ✅ (18 tests) | ✅ corpus real | n/a | ✅ COMPLET |
|   ↳ S3.5 mini-POC quantitatif | ⚠️ specs only | ❌ | ❌ | ❌ | 🟡 **PREP only — handlers PAS implémentés, bench PAS exécuté, gate PAS mesurée** |
|   ↳ S3.6 compare_across_versions | ❌ | ❌ | ❌ | ❌ | ⏸️ DIFFÉRÉ |
|   ↳ S3.7 Tool selection metrics | ❌ | ❌ | ❌ | ❌ | ⏸️ DIFFÉRÉ post-bench |
| **S4** ReasoningAgent V5.1 | | | | | |
|   ↳ S4.1-4.4 + S4.7 modules | ✅ | ✅ (132 tests) | ✅ | n/a | ✅ COMPLET |
|   ↳ S4.6 intégration V5.1 | ✅ | ✅ (10 tests) | ✅ mocked LLM | ✅ smoke live 1q | ✅ COMPLET |
|   ↳ S4.5 Cheap path Plan B-2 | ❌ | ❌ | ❌ | ❌ | ⏸️ **DIFFÉRÉ** (classifier DeBERTa S2 + endpoint dédié) |
|   ↳ S4.6.bis Fallback model | partial | ❌ | ❌ | ❌ | ⏸️ DIFFÉRÉ (HTTPLLMCaller a le fallback Together→DeepInfra basique, mais pas le circuit breaker AdmissionController switchover) |
| **S5** Endpoint API | | | | | |
|   ↳ S5.1 Pydantic models | ✅ | ✅ (35 tests) | n/a | n/a | ✅ COMPLET |
|   ↳ S5.2 AdmissionController | ✅ | ✅ (23 tests) | ✅ | n/a | ✅ COMPLET |
|   ↳ S5.3 IdempotencyStore | ✅ | ✅ (19 tests) | n/a | n/a | ✅ COMPLET (backend in-memory ; Redis backend différé) |
|   ↳ S5.4 Async endpoint | ✅ | ✅ (30 tests) | ✅ TestClient | ❌ | 🟡 **L3 only — router PAS branché dans api/main.py** |
|   ↳ S5.5 SSE streaming | ✅ | ✅ (10 tests) | ✅ TestClient | ❌ | 🟡 idem |
| **S6** Observability | | | | | |
|   ↳ S6.1 PII Redactor | ✅ | ✅ (35 tests) | n/a | n/a | ✅ COMPLET (maison, charte stricte) |
|   ↳ S6.2-6.4 Tracer/Metrics/Sampling | ✅ | ✅ (40 tests) | n/a | n/a | ✅ COMPLET |
|   ↳ S6.5 Integration V5.1 | ✅ | ✅ (12 tests) | ✅ mocked | ✅ smoke confirme spans+metrics actifs | ✅ COMPLET |
|   ↳ S6.x Presidio install | ❌ | ❌ | ❌ | ❌ | ⏸️ DIFFÉRÉ (choix user "maison") |
|   ↳ S6.x OTel SDK + Phoenix exporter | ❌ | ❌ | ❌ | ❌ | ⏸️ DIFFÉRÉ (branche prod) |
| **S7** GroundingVerifier | | | | | |
|   ↳ S7.1-7.6 architecture | ✅ | ✅ (35 tests) | n/a | n/a | ✅ COMPLET |
|   ↳ S7.7 Bake-off exécution | ⚠️ doc only | ❌ | ❌ | ❌ | 🟡 **PREP only — handlers HHEM/MiniCheck PAS wrappés, panel 80q PAS constitué, bench PAS exécuté** |
| **S8** Threat Model + Domain Pack | ❌ | ❌ | ❌ | ❌ | ⏸️ PENDING |
| **S9** Frontend chat V5 | ❌ | ❌ | ❌ | ❌ | ⏸️ PENDING |
| **S10/S11** Deployment + Tests + Réingestion + Blind A/B | ❌ | ❌ | ❌ | ❌ | ⏸️ PENDING |

---

## Score honnête

- **Vraiment livrés (L1+L2+L3+L4)** : S0, S1, S4 (modules+intégration), S6 (intégration), S4.6 (avec smoke live)
- **Architecture livrée sans exécution L4** : S2.1-2.3, S3.1-3.4, S5.1-5.5, S6.1-6.5, S7.1-7.6
- **Prep uniquement (L0)** : S3.5, S7.7, S2.0
- **Pending complets** : S2.4-2.6, S3.6-3.7, S4.5, S8, S9, S10, S11

**Tests** : 636 passent dont 13 nouveaux HTTPLLMCaller. **1 question** validée end-to-end live (smoke OK, 21.2s, citation correcte).

---

## Plan de rattrapage pour vraiment finir V5.1

### Étape 1 — Branchement HTTP (B2-B3)
- [x] **B1** HTTPLLMCaller ✅
- [x] **B3.smoke** 1 question live ✅
- [ ] **B2** Mount `create_router()` dans `api/main.py`
- [ ] **B3.full** Smoke 8 questions panel quantitative complet via curl

### Étape 2 — Exécutions différées (en ordre dépendance)
- [ ] **S3.5 exécution réelle** : implem handlers 5 tools quantitatifs (find_quantitative, get_table, extract_numeric_evidence, compute_derived_metric, resolve_unit_or_alias) → bench Phase A/B sur 8q → gate ≥15pp decision
- [ ] **S7.7 exécution réelle** : wrap HHEMBackend (modèle déjà dans projet via runtime_v3) → constituer 80 claims annotés → bench 4 backends → gate winner
- [ ] **Bench complet 143q** sur gold_set_sap_v2 avec V5.1 (vs V5 POC baseline) → mesure vraie progression

### Étape 3 — Sprints différés (post-confirmation valeur V5.1)
- [ ] **S2.0** bench Docling vs SmolDocling (préalable S2.6)
- [ ] **S4.5** Cheap path Plan B-2 (classifier S0.5 + endpoint)
- [ ] **S8** Threat Model + Domain Pack scaffold
- [ ] **S9** Frontend chat V5

---

## Reconnaissance de l'anti-pattern

Le système de marquage `completed` a été abusé : un sprint dont l'**exécution** est conditionnée (décisions user, bench long, modèles à installer) **ne doit pas être marqué completed** sur la base de la seule prep. Ce document corrige le score réel.

**Action immédiate** : ce document remplace le statut affiché. Les tasks fictivement `completed` (S3.5, S7.7 exécution) restent dans la liste pour traçabilité mais leur description marque explicitement "PREP only".

**Action récurrente** : à chaque "enchaine", si je différé une exécution, **dire explicitement** "L4 différé, sprint à L3" plutôt que "completed".
