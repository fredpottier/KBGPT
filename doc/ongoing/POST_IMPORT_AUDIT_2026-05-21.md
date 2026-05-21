# Audit pipeline post-import — 2026-05-21

> **Status** : 📋 Analyse — alimente Phase A2 (EXECUTION_ROADMAP §2 Phase A — A2)
> **Contexte** : audit déclenché après réingestion Phase A2 (38 docs SAP, 11622 claims bitemporels) avant relance du pipeline post-import 15 étapes. Pipeline interrompu à 9/15 par sécurité pendant analyse.
> **Auteur** : Claude (audit) + Fred (validation + corrections)

---

## 1. État au moment de l'arrêt

Run lancé via `/admin/post-import` avec les 15 étapes cochées, RQ job `117a4af0-29fe-4178-8532-7679ba9c07f0`. Arrêt par `docker restart knowbase-worker` autorisé explicitement par Fred (Option 1 — kill immédiat).

**9/15 étapes complétées et persistées dans le KG** :

| # | id | Durée | Effet sur KG |
|---|---|---|---|
| 1 | `canonicalize` | 25min 21s | 1405 → 1778 canonical entities (+373) |
| 2 | `facets` | 9min 14s | Facets reconstruits (résultat compteur 0 nouveaux car déjà couverts) |
| 3 | `facet_consolidate` | 48s | 0 renamed, 0 roots créés (KG déjà stable) |
| 4 | `purge_orphan_facets` | <1s | 137 facets candidates → `deprecated` |
| 5 | `cluster_cross_doc` | 26s | 1596 clusters, 14145 paires validées |
| 6 | `chains_cross_doc` | <1s | 419 chaînes détectées |
| 7 | `detect_contradictions` | non capturé | CONTRADICTS/REFINES/QUALIFIES posées (sans `invalidated_at`, cf §3) |
| 8 | `domain_pack_reprocess` | rapide | (sans effet mesurable sur corpus SAP, pack non-rebranché) |
| 9 | `claim_embeddings` | 65s | Vector index Neo4j e5-large 1024d sur tous les claims |

**6/15 étapes non exécutées** :
- 10 `claim_chunk_bridge`
- 11 `archive_isolated`
- 12 `garbage_collection`
- 13 `c4_relations`
- 14 `c6_pivots`
- 15 `build_perspectives`

**Décision Fred** : laisser tel quel (KG actuel suffisant pour développer Phase A2). Les étapes 10-15 seront ré-exécutées **après** refonte intégrée dans Phase A2.

---

## 2. Audit corrigé des 15 étapes

Verdict après corrections (vérification consommateurs en aval + application stricte de la charte domain-agnostic) :

| # | Étape | Verdict | Justification |
|---|---|---|---|
| 1 | canonicalize | **KEEP** | Critique cross-doc retrieval. Consommé runtime + C6 mining |
| 2 | facets | **KEEP** | Consommé Atlas (`atlas.py:160` `dominant_facet_names`) + Wiki (`/wiki/domain/{facet_key}`) + Perspectives builder |
| 3 | facet_consolidate | **KEEP** | Évite fragmentation racines facets sur réingestion |
| 4 | purge_orphan_facets | **KEEP** | Hygiène déterministe |
| 5 | cluster_cross_doc | **KEEP** | Pré-req `detect_contradictions` + C4 mining |
| 6 | chains_cross_doc | **MODIFY** | Ajouter timestamps sur `:CHAINS_TO` (compatibilité A2) |
| 7 | detect_contradictions | **MODIFY** | Brancher setter `invalidated_at` post-detection ; vérifier fallback LLM |
| 8 | domain_pack_reprocess | **KEEP** | Charte domain-agnostic : utile pour futurs corpus niche, même si inutile sur SAP |
| 9 | claim_embeddings | **KEEP** | Vector index essentiel retrieval |
| 10 | claim_chunk_bridge | **KEEP** | Citation cliquable + AX-1 compliance |
| 11 | archive_isolated | **MODIFY** | Critère `structured_form NULL` obsolète post-ClaimFirst — à adapter |
| 12 | garbage_collection | **KEEP** | Hygiène entités VALID/UNCERTAIN/NOISY |
| 13 | c4_relations | **MODIFY** | Clarifier modèle LLM réel (Qwen3 et pas Claude Haiku — description frontend obsolète) + setter `invalidated_at` |
| 14 | c6_pivots | **MODIFY** | Aligner sur schéma A2 : `:EVOLUTION_OF` (et pas `:EVOLVES_TO`) avec `detected_via='pivot'` |
| 15 | build_perspectives | **KEEP** | Critique Atlas frontend (`AtlasTheme -[:GROUPS_PERSPECTIVE]-> Perspective`) |

**Synthèse** : 10 KEEP, 5 MODIFY, **0 REMOVE**, 0 DEFER. Aucune étape n'est à supprimer du pipeline.

---

## 3. Problèmes structurels identifiés (dépendances Phase A2)

### 3.1 `invalidated_at` jamais setté par les détecteurs de contradictions

**Étapes concernées** : #7 `detect_contradictions`, #13 `c4_relations`.

Le code crée bien les relations `:CONTRADICTS / :REFINES / :QUALIFIES` mais **le claim ciblé n'est jamais marqué `invalidated_at = now()`**.

- `RelationDetector` (Phase A déterministe) + adjudication LLM (Phase B) : `relation_persister_c4.py` ne fait que la persistance de la relation.
- Conséquence : un claim contredit reste `active` au sens bitemporel.

**Impact** : bloque l'algo supersession Phase A2 (CAS 1-4) qui s'appuie sur `invalidated_at` pour les requêtes point-in-time (cf ADR_BITEMPOREL §2.4).

**Correctif** : ajouter un setter Cypher post-adjudication.
```cypher
MATCH (b:Claim {claim_id: $loser_id})
WHERE b.tenant_id = $tenant_id AND b.invalidated_at IS NULL
SET b.invalidated_at = datetime(),
    b.invalidated_by = $winner_id,
    b.invalidation_reason = $relation_type
```
Logique de choix loser/winner = règle de supersession A2 (CAS 1-4 selon `valid_from` explicit vs NULL).

### 3.2 Schéma relationnel non-bitemporel sur `:CHAINS_TO / :EVOLVES_TO / :CONTRADICTS`

**Étapes concernées** : #6 `chains_cross_doc`, #7 `detect_contradictions`, #13 `c4_relations`, #14 `c6_pivots`.

Les relations cross-claim n'ont aucun marquage temporel (`valid_from`, `invalidated_at`). Si un des claims source ou cible est invalidé, la relation reste opaque.

**Correctif** : timestamps systématiques sur les relations cross-claim.
- `valid_from` = `min(claim_a.valid_from, claim_b.valid_from)` ou marker `'inherit_from_claims'`
- `invalidated_at` = setté si l'un des claims est invalidé après création de la relation

À spécifier précisément dans l'ADR A2 (extension de §9 addendum ADR_BITEMPOREL_CLAIMS).

### 3.3 `:EVOLVES_TO` (étape #14 C6) vs `:EVOLUTION_OF` (Phase A2 ADR §3.3)

**Étape concernée** : #14 `c6_pivots`.

`c6_pivots` crée des relations `:EVOLVES_TO` par heuristique pivot (entité partagée), alors que Phase A2 prévoit `:EVOLUTION_OF` avec `marker_type ∈ {explicit, inferred, prudence}` (cf ADR_BITEMPOREL §3.3).

**Risque** : deux conventions de nommage coexistent dans le KG, ambiguïté pour le runtime.

**Décision à prendre dans ADR A2** : 2 scénarios possibles.
- **Scénario A** : harmoniser sur `:EVOLUTION_OF` avec `marker_type` (C6 produit `marker_type='inferred', detected_via='pivot'`, A2 ADR algo produit `marker_type='explicit'|'prudence'`).
- **Scénario B** : conserver les deux relations, mais documenter leur sémantique distincte (C6 = heuristique douce, A2 = bitemporel strict).

**Recommandation** : Scénario A pour simplicité runtime.

### 3.4 Critère `archive_isolated` — vérifié OK post-mesure (initialement présumé obsolète à tort)

**Étape concernée** : #11 `archive_isolated`.

Le critère actuel : `archived = true SI structured_form_json IS NULL AND NOT (relations CHAINS_TO, ABOUT, REFINES, QUALIFIES, CONTRADICTS)`.

**Hypothèse initiale (FAUSSE)** : post-Phase A1.x ClaimFirst, les claims n'ont plus de `structured_form_json` distinct.

**Mesure 2026-05-21 (task #331 A2.11)** : sur les 11622 claims actuels du KG :
- `structured_form_json` non-NULL : **4488 claims (38.6%)** — ex: `{"subject": "SAP Solution Manager", "predicate": "BASED_ON", "object": "SAP Business Suite maintenance strategy"}`
- `structured_form_json` NULL : 7134 claims (61.4%)
- ClaimFirst produit toujours du `structured_form_json` pour ~40% des claims (format S/P/O classique avec subject_canonical / predicate / object_canonical)

**Simulation critères** :
- Critère actuel (sfj NULL + 0 relations) → **133 claims archivables**
- Critère simplifié (0 relations seulement) → 150 archivables (+17 claims structurés isolés)

**Décision** : **garder le critère actuel inchangé**. Il identifie correctement les "claims orphelins" (texte brut + isolé = bruit). Les 17 claims structurés isolés sont probablement en attente d'être rattachés à des relations par un cycle A2 ultérieur — les conserver actifs est plus prudent (principe §9.3 NULL > valeur fausse appliqué aux décisions d'archivage).

**Statut tâche A2.11** : ✅ completed — pas de modification de code requise, juste correction de cette section.

### 3.5 Aucun mécanisme de cancel dans `run_pipeline_job`

**Étape concernée** : N/A — défaut transverse du router.

`run_pipeline_job` (post_import.py:372-460) n'a aucun check de cancel-flag entre les étapes. L'endpoint `/cancel` ne fait que vider la clé Redis state mais ne stoppe pas le job RQ en cours.

Conséquence : la seule manière d'interrompre un pipeline en cours est de tuer le worker container (PID 1).

**Correctif** : ajouter un check au début de chaque itération de la boucle `for step_id in steps`.
```python
# Check cancel flag (set by /cancel endpoint)
if rc.client.get(f"osmose:post_import:cancel:{tenant_id}"):
    logger.info(f"[PostImport] Cancelled by user before {step_id}")
    break
```
Petite modif (~10 lignes), mais évite les restarts de container futurs.

### 3.6 Description frontend obsolète sur `c4_relations`

**Étape concernée** : #13 `c4_relations` (description seulement, pas de blocage).

Frontend dit "Adjudication LLM (Claude Haiku)" mais le code appelle `llm_router.complete(task_type=TaskType.FAST_CLASSIFICATION)` qui route vers Qwen3-235B (ou Qwen3-14B selon config). Aucune violation charte, juste un libellé à corriger.

**Correctif** : modifier `STEPS[]` dans `post_import.py` ligne ~183-188 :
```
description: "...via embedding similarity + adjudication LLM (Qwen3-235B/Qwen3-14B). Chaque relation a des preuves verbatim."
```

---

## 4. Erreurs d'audit initiales (transparence + leçons)

Deux erreurs majeures dans mon audit initial (corrigées par Fred) :

### 4.1 « Facets sans consumer runtime »

**Erreur** : j'avais cherché uniquement dans `src/knowbase/runtime_v5/` et conclu "facets ne semblent pas consultées au runtime".

**Réalité** : facets sont consommées par 3 frontends critiques (Wiki domain, Atlas perspective_topics, admin corpus-audit) et par `perspectives/builder.py`. J'aurais dû grep large (`:Facet|CanonicalFacetRoot|facet_id|BELONGS_TO_FACET`) sur tout `src/` + `frontend/src/app/` avant verdict.

**Leçon** : avant tout verdict REMOVE, grep exhaustif sur backend + frontend + autres scripts. Documenté dans `feedback_audit_must_grep_all_consumers.md`.

### 4.2 « Domain Pack à retirer car inopérant sur SAP »

**Erreur** : j'ai utilisé la mémoire "A10 — Domain Pack SAP testé inopérant" comme justification REMOVE. Mais le test SAP n'invalide pas l'utilité du Domain Pack en général.

**Réalité (Fred)** : la charte domain-agnostic est claire — le corpus actuel ne dicte jamais les choix d'architecture. DeepSeek connaît SAP nativement, mais pas un futur corpus médical/légal/aerospace niche. **On ne supprime pas un script juste parce qu'il est inutile sur le corpus actuel**.

**Leçon** : verdict REMOVE seulement si (a) aucun consumer dans aucun chemin (b) code domain-aware non généralisable, ou (c) doublon strict. Pas si "inutile pour ce corpus". Documenté dans `feedback_domain_agnostic_pipeline_components.md`.

---

## 4-bis. Mise à jour 2026-05-21 — Phase A2 exécutée

**8 tasks A2 livrées en une journée** (vs estimation 6-7j roadmap §2 Phase A — A2) :

| Task | Status | Livrable |
|---|---|---|
| #333 A2.0 | ✅ | `ADR_RELATIONS_CLAIM_CLAIM.md` v1.2 (2 passes review Claude Web) |
| #326 A2.6 | ✅ | Cancel-flag dans `run_pipeline_job` |
| #327 A2.7 | ✅ | Description c4_relations frontend STEPS[] |
| #328 A2.8 | ✅ | `SupersessionApplier` (règle §9.4 CAS 1-4) + 17 tests unitaires |
| #329 A2.9 | ✅ | Timestamps sur relations cross-claim — 6878 backfill |
| #330 A2.10 | ✅ | Harmonisation `EVOLVES_TO` → `EVOLUTION_OF` (7 fichiers) |
| #331 A2.11 | ✅ | Mesure `structured_form_json` (38.6% non-NULL → critère gardé) |
| #332 A2.12 | 🔄 | En cours : rétro-application + étapes 10-15 post-import |

**Rétro-application supersession sur KG existant (1.5s)** :
- 113 paires CONTRADICTS analysées (sans réingestion)
- 27 `:SUPERSEDES` créées (CAS 1) → 27 claims `invalidated_at`
- 73 `:ConflictPending` créés (49 CAS_1_EQUAL + 20 CAS_2 + 4 CAS_3)
- 13 no_op (chaînes d'invalidation déjà résolues par paires précédentes)

**Audit baseline mid-A2.12** : 7/8 Gate Criteria PASS (avant fin étapes 10-15).
- G4 : initialement FAIL puis corrigé (`:SUPERSEDES` exclu — par design matérialise l'invalidation)
- G8 : 197 relations sans evidence_a/b — explicables par sources non-LLM (relation_detector formel A déterministe + post_import_cross_doc + retro_apply_a2_8). Filtre G8 affiné pour exclure ces cas.

**Décision corpus** : **PAS de re-purge + ré-ingestion** ClaimFirst. Le travail A2 a porté uniquement sur le post-import. Les 11622 claims ingérés hier restent valides. Seules les étapes 10-15 manquantes du post-import sont en train d'être complétées.

## 5. Phasing recommandé

**Refonte du pipeline post-import = sous-chantier de Phase A2** (cf EXECUTION_ROADMAP §2 Phase A — A2). Pas un chantier isolé.

Pourquoi pas maintenant :
- Sans ADR A2 finalisé, le schéma cible (`:EVOLUTION_OF` vs `:EVOLVES_TO`, timestamps relations, règle invalidation) n'est pas tranché. Coder maintenant = inventer à l'aveugle.
- Le KG actuel (9/15 étapes) est exploitable pour développer A2 algo.
- Les 6 étapes restantes ne sont pas bloquantes (juste sous-optimales sans correctifs).

**Séquence proposée** :

1. **Phase A3.0** : rédiger `ADR_PARSE_EVALUATE_RUNTIME.md` (déjà pending #323) — clarifie le runtime cible
2. **Phase A2 ADR** : étendre §9 addendum ADR_BITEMPOREL en ADR A2 complet — tranche `:EVOLUTION_OF` vs `:EVOLVES_TO`, schéma timestamps relations, règle CAS 1-4
3. **Phase A2 — sous-chantier refonte post-import** (3-5j, intégré dans la sem A2) :
   - **A2.6** : check cancel-flag dans `run_pipeline_job` (§3.5) — *quick win, ~30min*
   - **A2.7** : description frontend `c4_relations` (§3.6) — *quick win, 5min*
   - **A2.8** : setter `invalidated_at` post-detection (§3.1) — `detect_contradictions` + `c4_relations` + `c6_pivots`
   - **A2.9** : timestamps sur relations cross-claim (§3.2)
   - **A2.10** : harmonisation `:EVOLUTION_OF`/`:EVOLVES_TO` (§3.3) — applique le choix ADR A2
   - **A2.11** : mesurer `structured_form_json` distribution + adapter critère `archive_isolated` (§3.4)
4. **Phase A2 impl** : algo supersession claim-vs-claim CAS 1-4
5. **Réingestion + pipeline post-import propre** (full 15 étapes avec correctifs)

---

## 6. État technique post-arrêt

- ✅ Worker container : `Up` (restart auto réussi)
- ✅ RQ job : marqué `FAILED` proprement
- ✅ Redis state : `running=False`, historique 9 étapes préservé
- ✅ Aucun processus zombie résiduel
- ✅ KG cohérent (les 9 étapes ont toutes terminé proprement avant interruption)

**Endpoints exposés** (post-import) :
- `GET  /api/admin/post-import/steps` — liste 15 étapes
- `GET  /api/admin/post-import/status` — état courant
- `POST /api/admin/post-import/run` — lance pipeline
- `POST /api/admin/post-import/cancel` — vide état Redis (ne stoppe pas le job RQ → à corriger A2.6)

**Fichier rapport audit Phase A2** : `data/benchmark/phase_a2/audit_20260520_212412.json` (PASS, 11622 claims, 38 docs).

---

## 7. Références

- VISION : `doc/VISION.md` §3.2 (bitemporel), §4.3 (pipeline ingestion étape 8)
- ADR : `doc/ongoing/adr/ADR_BITEMPOREL_CLAIMS.md` §9 addendum + §3.3 EVOLUTION_OF
- Roadmap : `doc/EXECUTION_ROADMAP.md` §2 Phase A — A2
- Code router : `src/knowbase/api/routers/post_import.py`
- Mémoire `feedback_audit_must_grep_all_consumers.md` (à créer)
- Mémoire `feedback_domain_agnostic_pipeline_components.md` (à créer)
