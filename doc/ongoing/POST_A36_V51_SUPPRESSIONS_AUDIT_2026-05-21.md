# Audit A3.6 — Suppressions ciblées V5.1 (2026-05-21)

**Status** : audit terminé. **5 modules DEPRECATED** (banner + warning import),
**1 module KEEP** (`domain_pack_loader`, charte agnostique l'impose).
**0 module REMOVE** effectivement (V5.1 reste actif tant que bench A3.8 +
Phase B cross-domain ne sont pas validés).

---

## 1. Contexte

L'ADR §10.2 liste 6 modules V5.1 candidats à suppression UNE FOIS A3 validé
(GA3-5 + GA3-6 + GA3-7 atteints via bench A3.8). Tant que le bench n'est pas
exécuté, V5.1 reste l'endpoint actif et ces modules doivent rester opérationnels.

**Charte stricte** appliquée :
- Grep exhaustif des consumers `src/` + `frontend/src/app/` + `app/scripts/` +
  `tests/` + `benchmark/` (cf [[feedback-audit-must-grep-all-consumers]]).
- Pas de REMOVE si "inutile sur le corpus actuel" (cf
  [[feedback-domain-agnostic-pipeline-components]]).

---

## 2. Audit module par module

### 2.1 `runtime_v5/query_reformulator.py` (172 lignes)

**Rôle** : multi-formulation query (pattern EKX P1), feature passive via
`V5_MULTIFORM_ENABLED=1`.

**Consumers** :
- `src/knowbase/runtime_v5/reasoning_agent_v51.py` (V5 prod, agent reading)

**Verdict** : **DEPRECATE**.
- Multi-formulation remplacée par décomposition `sub_goals` dans Parse (A3.1).
- V5 prod l'utilise encore (toggle env var) → banner + warning, pas REMOVE.

### 2.2 `runtime_v5/domain_pack_loader.py` (204 lignes)

**Rôle** : loader des Domain Packs (enterprise_sap, biomedical, aerospace_compliance,
regulatory) avec acronymes/aliases/synonymes.

**Consumers** :
- `src/knowbase/claimfirst/resolution/subject_resolver_v2.py` (pipeline ingestion
  ClaimFirst — **CRITIQUE** prod)
- `src/knowbase/domain_packs/{aerospace_compliance,biomedical,enterprise_sap,
  regulatory,base,registry,__init__}.py` (infrastructure complète)
- `src/knowbase/runtime_v5/reasoning_agent_v51.py`
- `frontend/src/app/admin/domain-packs/page.tsx` (UI admin)
- `tests/domain_packs/test_orchestrator_hook.py`, `test_registry.py`

**Verdict** : **KEEP** (PAS de banner DEPRECATED).
- La charte [[feedback-domain-agnostic-pipeline-components]] (21/05) est explicite :
  "Si DeepSeek-V3.1 connaît SAP nativement et rend Domain Pack inopérant sur
  ce corpus, NE PAS REMOVE — le prochain corpus médical/légal/aerospace niche
  pourra en avoir besoin."
- Consumer critique côté ingestion (`subject_resolver_v2`) — supprimer casserait
  le pipeline.
- L'ADR §10.2 mentionne "Domain Packs réservés à Phase D" — c'est une feature
  future, pas du legacy. Le module et toute l'infrastructure `domain_packs/`
  doivent rester disponibles.
- **Action** : amender ADR §10.2 pour retirer `domain_pack_loader` de la liste
  des suppressions.

### 2.3 `runtime_v5/doc_topics_loader.py` (134 lignes)

**Rôle** : loader DocumentContext enrichis (doc_title, doc_summary, key_topics,
key_terms) pour routage agent V5.

**Consumers** :
- `src/knowbase/runtime_v5/reasoning_agent_v51.py` (V5 prod)

**Verdict** : **DEPRECATE**.
- V6 utilise lookup canonical entities via Execute kg_claims (pas besoin de
  topics agrégés par doc).
- V5 prod l'utilise → banner + warning, REMOVE post-A3.8.

### 2.4 `runtime_v5/anthropic_llm_caller.py` (222 lignes)

**Rôle** : wrapper Anthropic API (Claude Sonnet/Opus/Haiku) pour bench de
calibration uniquement.

**Consumers** :
- `src/knowbase/api/routers/runtime_v5.py` (toggle env `V5_LLM_PROVIDER=anthropic`)

**Verdict** : **DEPRECATE** (priorité élevée — viole charte open-source).
- Mémoire [[feedback-no-proprietary-llm-in-production]] (10/05/2026) interdit
  Claude en runtime production OSMOSIS.
- Module existe pour bench de calibration ponctuel uniquement (mesure plafond LLM).
- Banner + warning + restriction usage bench-only documentée.

### 2.5 `runtime_v5/agent/loop_signature.py` (~250 lignes)

**Rôle** : anti-thrash robuste (novelty_score) pour la boucle agent V5 V1.5 (S4.1).

**Consumers** :
- `src/knowbase/runtime_v5/agent/workspace.py` (V5 internal)
- `src/knowbase/runtime_v5/reasoning_agent_v51.py` (V5 prod)
- `tests/runtime_v5/test_loop_signature.py`
- `tests/runtime_v5/test_workspace.py`

**Verdict** : **DEPRECATE** (V5 internal — sort lié à V5).
- V6 n'a pas de boucle agentique (Plan déterministe).
- Si V5 retiré post-A3.8, ce module disparaît avec lui.

### 2.6 `runtime_v5/agent/execution_plan.py` (~120 lignes)

**Rôle** : Pydantic schema plan-then-execute pour shapes complexes V5 (S4.3).

**Consumers** :
- `src/knowbase/runtime_v5/agent/workspace.py`
- `src/knowbase/runtime_v5/reasoning_agent_v51.py`
- `tests/runtime_v5/test_execution_plan.py`
- `tests/runtime_v5/test_workspace.py`

**Verdict** : **DEPRECATE** (V5 internal — sort lié à V5).
- V6 a son propre `PlanOutput` (déterministe, pas LLM).
- Suppression post-A3.8 si V5 retiré.

---

## 3. Matrice verdict

| Module | Consumers | Verdict | Action |
|---|---|---|---|
| `query_reformulator.py` | 1 (V5 prod) | DEPRECATE | banner + warning import |
| `domain_pack_loader.py` | 11 (ingestion+UI+packs) | **KEEP** | rien (charte) |
| `doc_topics_loader.py` | 1 (V5 prod) | DEPRECATE | banner + warning import |
| `anthropic_llm_caller.py` | 1 (V5 endpoint) | DEPRECATE | banner + warning import |
| `agent/loop_signature.py` | 4 (V5 internal+tests) | DEPRECATE | banner + warning import |
| `agent/execution_plan.py` | 4 (V5 internal+tests) | DEPRECATE | banner + warning import |

---

## 4. Mécanisme DEPRECATED appliqué

Pour chacun des 5 modules en DEPRECATE :

1. **Banner docstring** en tête de fichier :
   ```python
   """
   ⚠️ DEPRECATED (A3.6, 2026-05-21) — Réf ADR_PARSE_EVALUATE_RUNTIME §10.2.

   Ce module sera supprimé une fois :
   - Bench A3.8 validé (gates GA3-5/6/7 atteints)
   - Phase B cross-domain validée
   - V5.1 retiré comme endpoint de référence

   Remplacé par : <module V6 équivalent ou "logique intégrée dans Orchestrator">.

   ⚠️ NE PAS étendre. Pour nouveaux développements, voir runtime_a3/.
   """
   ```

2. **Warning import** : log warning unique (deduped via `_warned` flag de module)
   au moment du premier `import`.

3. **Tests** : inchangés (continuent de valider le module tant qu'il existe).

---

## 5. Suppressions effectives planifiées (post-A3.8)

Une fois bench A3.8 validé + Phase B validée :

1. Supprimer V5 endpoint `/api/runtime_v5/answer` (et router).
2. Supprimer `src/knowbase/runtime_v5/` complet (cascade les 5 DEPRECATED).
3. Supprimer tests `tests/runtime_v5/`.
4. Conserver `runtime_v5/api/{admission,idempotency,job_store,models,router,sse}`
   uniquement si ré-utilisé par V6 (cf ADR §10.3 : à valider en A3.7+ si on
   en a besoin pour V6 async — pas le cas actuellement).
5. **Conserver** `domain_packs/` + `domain_pack_loader.py` + ingestion consumers.

---

## 6. Amendement ADR §10.2

Retirer `domain_pack_loader.py` de la liste des suppressions. Ajouter référence
explicite à la charte mémoire `feedback_domain_agnostic_pipeline_components` qui
le protège.

---

## 7. Tests post-A3.6

Aucune régression attendue :
- Les warnings d'import sont émis en log (pas exception)
- Les modules fonctionnent identiquement
- Les tests V5 continuent de passer
- Le runtime_v6 (livré A3.7) n'utilise aucun de ces modules
