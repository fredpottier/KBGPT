# OSMOSE — Travaux Restants et Plan d'Implémentation

**Date** : 2026-03-07
**Statut** : Document de cadrage pour validation avant implémentation
**Référence architecture** : `doc/ongoing/ARCH_CROSS_DOC_KNOWLEDGE_LAYERS.md` (v3)

---

## 1. État des Lieux — Ce qui est FAIT

### 1.1 Pipeline Claimfirst (Couche 0) — COMPLET

Le pipeline d'extraction document-par-document est opérationnel et stabilisé :
- Extraction de Claims, Entities, Passages, Facets depuis les documents SAP
- SubjectResolver v2 avec reclassification par règles (`axis_reclassification_rules`)
- ApplicabilityFrame evidence-locked (53 tests, module `applicability/`)
- Quality KG v1.4 (LLM Merge Arbiter, PASS marking, Champion/Redundant)
- Phase 2.8 : SubjectAnchors dérivés des entités canonicalisées
- Filtres `archived` sur claims (Chantier 2.2)
- Fix version/release SLA (3 couches : regex + prompt + MetricContextValidator)

### 1.2 Couche 1 — Identité Structurelle Cross-Doc (C1.1) — COMPLET

**Pass C1.1** déployé et validé en production :
- **267 CanonicalEntity** créés dans Neo4j
- **565 relations SAME_CANON_AS** entre Entity et CanonicalEntity
- **229 CanonicalEntity cross-doc** (≥2 documents) — objectif initial de 150-200 dépassé
- **0 Entity** rattachée à 2+ CanonicalEntity (invariant respecté)
- **0 hub** >50 entités (pas de mega-hub fourre-tout)
- **71 paires de documents** liées via 1-hop, **56 paires supplémentaires** via 2-hops uniquement

**Méthodes utilisées** :
- Alias Identity Match (confiance 0.95) — match des aliases qualifiés contre les noms normalisés
- Prefix Dedup data-driven (confiance 0.90, seuil fréquence prefix = 50)

**Fichiers** :
- Modèle : `src/knowbase/claimfirst/models/canonical_entity.py`
- Script : `app/scripts/canonicalize_entities_cross_doc.py`
- Tests : `tests/claimfirst/test_canonical_entity.py` (13 tests), `tests/claimfirst/test_canonicalize_cross_doc.py` (34 tests)

### 1.3 Infrastructure Burst / vLLM — OPÉRATIONNEL

- Qwen2.5-14B-Instruct-AWQ sur vLLM v0.6.6.post1 (EC2 Spot g6.2xlarge)
- AWQ Marlin : 26.8 t/s (8.5x vs standard)
- Golden AMI v8 (`ami-05ec81177dc825d56`)

---

## 2. Problèmes Connus à Corriger

### 2.1 Contradiction Detector — Faux Positifs — ✅ RÉSOLU (2026-03-08)

Gate de non-exclusivité ajoutée dans `value_contradicts.py` (Gate 2.5). Prédicats classifiés exclusive ("requires", "replaces") vs non-exclusive ("supports", "uses"). 13 tests dans `TestNonExclusivityGate`. Prompt LLM renforcé dans `relation_detector.py`.

---

### 2.2 ApplicabilityFrame — Release IDs Multiples — ✅ RÉSOLU (2026-03-08)

Rule 14 ajoutée au prompt LLM (extraire UNIQUEMENT la release primaire du titre). Dedup titre-first dans `frame_builder.py` avec `_has_title_signal()`. 2 tests ajoutés.

---

### 2.3 Authority Contract — Propagation Incomplète — ✅ DÉJÀ FAIT

Vérifié : le câblage `resolver_axis_values` est complet dans `orchestrator.py`. Le flow SubjectResolver→FrameBuilder→build()→_resolve_priors() fonctionne correctement.

---

### 2.4 Search sans Filtre Version — ✅ RÉSOLU (2026-03-08)

Implémenté dans Phase B :
- Chunks Qdrant enrichis avec `axis_release_id` et `axis_version` (payload + indexes)
- `SearchRequest` : paramètres `release_id` et `use_latest`
- Expansion SAME_CANON_AS dans le search path
- LatestSelector boost (×1.3) pour les chunks du document le plus récent
- Script migration `backfill_chunk_axis_values.py`
- 15 tests dans `test_search_c1_pivots.py` (chantier structurant)

---

### 2.5 Qwen3 Migration — ROLLBACK (PAS PRIORITAIRE)

**Situation** : La migration Qwen2.5 → Qwen3-14B-AWQ a été planifiée (21 fichiers, plan validé) puis rollbackée (commit `dc0d530`) car Qwen3 produisait 77.7% de réponses vides sous charge.

**Cause racine** : vLLM v0.9.2 + Qwen3 sous charge concurrente avec les paramètres de production (temperature, structured output) causait des timeouts et réponses vides.

**Décision** : Rester sur Qwen2.5 pour l'instant. La migration sera retentée quand :
- vLLM aura un release stable avec support Qwen3 confirmé sous charge
- Ou quand un benchmark montrera un gain qualitatif justifiant l'effort

**Aucune action immédiate requise.**

---

## 3. Travaux d'Implémentation Restants — Architecture Cross-Doc

Ces travaux suivent l'architecture définie dans `ARCH_CROSS_DOC_KNOWLEDGE_LAYERS.md` et l'ordre d'implémentation validé.

### 3.1 Étape C1.2 — Élargir C1 avec Version Strip (OPTIONNEL)

**Prérequis** : C1.1 audité et validé (FAIT)

**Description** : Ajouter la méthode `version_strip` (confiance 0.90) pour merger des entités comme "S/4HANA 2021" et "S/4HANA" vers le même CanonicalEntity.

**Points d'attention** :
- Risque : "SAP BW 7.4" et "SAP BW 7.5" sont des versions distinctes avec des fonctionnalités différentes. Le version_strip doit respecter la granularité sémantique.
- Approche recommandée : version_strip uniquement si le nom sans version existe déjà comme Entity indépendante dans le corpus. Sinon, conserver les versions comme entités distinctes.
- Audit obligatoire en dry-run avant exécution.

**Effort estimé** : 1 jour

**Priorité** : BASSE — C1.1 couvre déjà 229 entités cross-doc, le gain marginal est limité.

---

### 3.2 Étape 2 — Brancher Search sur C1 Pivots (PRIORITÉ HAUTE)

**Prérequis** : C1.1 déployé (FAIT)

**C'est le chantier le plus important.** Sans lui, les 267 CanonicalEntity n'apportent aucune valeur visible à l'utilisateur.

**Description** : Connecter le chemin de recherche `/api/search` aux pivots C1 pour :
1. **Cross-doc retrieval** : quand l'utilisateur cherche "SAP Fiori", trouver aussi les claims des docs qui parlent de "Fiori" ou "SAP Fiori apps" via les CanonicalEntity
2. **Filtre version** : ajouter un paramètre optionnel `version` ou `release` à `SearchRequest`, utiliser les axis_values pour filtrer
3. **Comportement "latest"** : si aucune version spécifiée, privilégier les documents les plus récents via `LatestSelector`

**Sous-tâches** :
- **3.2.a** Enrichir les chunks Qdrant avec `axis_values` (version, release) au moment de l'indexation
- **3.2.b** Ajouter `version` / `release` comme paramètres optionnels dans `SearchRequest`
- **3.2.c** Modifier le retrieval pour traverser `SAME_CANON_AS` lors de l'expansion de la requête entity
- **3.2.d** Intégrer `LatestSelector` comme filtre par défaut quand aucune version n'est spécifiée
- **3.2.e** Tests d'intégration avec des scénarios multi-version

**Fichiers impactés** :
- `src/knowbase/api/routers/search.py` ou équivalent
- `src/knowbase/api/schemas/search.py` (SearchRequest)
- Pipeline d'indexation Qdrant (ajout axis_values aux metadata)
- Module de retrieval (expansion via C1)

**Effort estimé** : 2-3 jours

---

### 3.3 Étape C1.3 — LLM Arbiter (FUTUR)

**Prérequis** : C1.2 audité, Search sur C1 validé

**Description** : Utiliser un LLM pour détecter des synonymes non-triviaux (ex: "Cloud Connector" ↔ "SAP Cloud Connector Service"). Le LLM reçoit les claims des deux entités comme evidence et juge s'ils réfèrent au même concept.

**Points d'attention** :
- Relation `POSSIBLE_SAME_AS` (confiance 0.60-0.84) pour les cas incertains — non traversée automatiquement
- Relation `SAME_CANON_AS` (confiance 0.85) pour les cas confirmés par le LLM
- Coût : 1 appel LLM par paire candidate (pré-filtrer avec embedding similarity > 0.8 pour limiter)

**Effort estimé** : 3-5 jours

**Priorité** : BASSE — à planifier après validation que les étapes précédentes apportent une valeur mesurable.

---

### 3.4 Étape 3 — C2a QuestionSignatures (PRIORITÉ MOYENNE-HAUTE)

**Prérequis** : C1.1 audité (FAIT), Search sur C1 fonctionnel (idéalement)

**Description** : Extraire de chaque Claim une "question factuelle implicite" (QuestionSignature) qui permet de comparer les réponses entre documents.

**Exemple** :
- Claim : "TLS 1.2 is the minimum version required for all connections"
- QuestionSignature : `{ question: "What is the minimum TLS version?", dimension_key: "tls_min_version", value_type: "version" }`

**Deux niveaux d'extraction** :
1. **Level A** (patterns regex déterministes) — ~12 patterns IT/infra déjà identifiés. Précision ~100%. Exemples : "minimum version X", "maximum Y connections", "requires Z protocol".
2. **Level B** (LLM evidence-locked) — Le LLM reformule la claim en question factuelle. Plus large mais ~85-90% de précision. Le LLM ne voit qu'un seul document à la fois (pas de cross-doc synthesis).

**Points d'attention** :
- Le `dimension_key` (snake_case, ≤5 mots) est l'identifiant de regroupement, PAS la question en langue naturelle (trop variable)
- Seuil de récurrence : ≥3 claims pour les types string/enum/boolean, ≥1 pour number/version/percent
- Cap : max 50 QS par document
- Commencer sur un sous-ensemble (2-3 docs sécurité) avant d'étendre

**Approche recommandée** : Commencer par Level A seul sur tout le corpus (rapide, zéro coût LLM, 100% de précision) puis ajouter Level B sur le sous-ensemble de test.

**Fichiers à créer** :
- `app/scripts/extract_question_signatures.py` (script post-import)
- Modèle QuestionSignature (Pydantic, pattern standard)
- Tests unitaires pour les patterns Level A

**Effort estimé** : 3-5 jours (Level A: 1-2j, Level B: 2-3j)

---

### 3.5 Étape 4 — C2b ClaimKey Confirmation (PRIORITÉ MOYENNE)

**Prérequis** : C2a stable et auditée

**Description** : Quand la même `dimension_key` apparaît dans ≥2 documents **indépendants**, une ClaimKey est créée. La ClaimKey est le pivot factuel cross-doc qui permet la comparaison de valeurs.

**Exemple** :
- Doc A (Security Guide 2022) : `tls_min_version` → "1.2"
- Doc B (Security Guide 2023) : `tls_min_version` → "1.3"
- ClaimKey `ck_tls_min_version` créée → permet de détecter l'évolution (pas une contradiction)

**Points d'attention** :
- **Documents indépendants** : même sujet + même version = pas indépendant (éviter les faux récurrents issus de templates)
- Utiliser `ComparableSubject` et `ApplicabilityAxis` pour vérifier l'indépendance
- Status : EMERGENT → COMPARABLE → DEPRECATED (lifecycle)
- Le champ `scope_canonical_entity_ids` (optionnel) scope la ClaimKey à un produit/composant spécifique via C1

**Fichiers à créer** :
- `app/scripts/confirm_claimkeys.py` (script corpus-level)
- Modèle ClaimKey (réutiliser le modèle existant dans `claimkey/` si compatible)

**Effort estimé** : 2-3 jours

---

### 3.6 Étape 5 — C3 Ponts Conceptuels (PRIORITÉ BASSE)

**Prérequis** : C1 et C2 stables et éprouvés

**Description** : Détecter des relations sémantiques entre CanonicalEntity (SPECIALIZES, REQUIRES, ENABLES, ALTERNATIVE_TO, ASPECT_OF) basées sur la co-occurrence dans les claims.

**Contrainte critique** : C3 ne sert QU'À la navigation ("voir aussi", exploration). **JAMAIS** pour le raisonnement, la preuve, ou la détection de contradiction. Cette contrainte est architecturale et doit être enforcée dans le code (pas juste documentée).

**Effort estimé** : 1-2 semaines

**Priorité** : BASSE — à planifier uniquement après que C1 et C2 soient en production et validés.

---

## 4. Phases d'Implémentation — Ordre Recommandé

### Phase A — Corrections Structurelles — ✅ COMPLÈTE (2026-03-08)

| # | Tâche | Statut | Section |
|---|-------|--------|---------|
| A.1 | Contradiction Detector — gate de non-exclusivité | ✅ FAIT | §2.1 |
| A.2 | ApplicabilityFrame — primary vs mentioned release | ✅ FAIT | §2.2 |
| A.3 | Authority Contract — câblage orchestrator.py | ✅ DÉJÀ FAIT | §2.3 |

### Phase B — Search sur C1 Pivots — ✅ COMPLÈTE (2026-03-08)

| # | Tâche | Statut | Section |
|---|-------|--------|---------|
| B.1 | Enrichir chunks Qdrant avec axis_values | ✅ FAIT | §3.2.a |
| B.2 | Paramètre version/release dans SearchRequest | ✅ FAIT | §3.2.b |
| B.3 | Expansion requête via SAME_CANON_AS | ✅ FAIT | §3.2.c |
| B.4 | LatestSelector comme filtre par défaut | ✅ FAIT | §3.2.d |
| B.5 | Tests d'intégration multi-version | ✅ FAIT (15 tests) | §3.2.e |

**Note** : Script migration `backfill_chunk_axis_values.py` créé pour les chunks existants.

### Phase C — QuestionSignatures Level A — ✅ COMPLÈTE (2026-03-08)

| # | Tâche | Statut | Section |
|---|-------|--------|---------|
| C.1 | Modèle QuestionSignature (Pydantic) | ✅ FAIT | §3.4 |
| C.2 | Patterns Level A (regex, 15 patterns) | ✅ FAIT (23 tests) | §3.4 |
| C.3 | Script extract_question_signatures.py | ✅ FAIT | §3.4 |
| C.4 | Dry-run + audit sur tout le corpus | ⏳ À FAIRE (nécessite infra Docker) | §3.4 |

**Fichiers créés** :
- `src/knowbase/claimfirst/models/question_signature.py`
- `src/knowbase/claimfirst/extractors/question_signature_extractor.py`
- `tests/claimfirst/test_question_signature.py`
- `app/scripts/extract_question_signatures.py`

### Phase D — QuestionSignatures Level B + ClaimKey (1-2 semaines)

Extension LLM de C2 sur un sous-ensemble, puis confirmation ClaimKey.

| # | Tâche | Priorité | Effort | Section |
|---|-------|----------|--------|---------|
| D.1 | Prompt LLM Level B (QS extraction) | MOYENNE | 1-2j | §3.4 |
| D.2 | Test sur sous-ensemble (2-3 docs sécurité) | MOYENNE | 1j | §3.4 |
| D.3 | Audit précision Level B (≥90% sur 50 cas) | MOYENNE | 0.5j | §3.4 |
| D.4 | Script confirm_claimkeys.py | MOYENNE | 2-3j | §3.5 |
| D.5 | Audit ClaimKey (ratio stable/one-off >30%) | MOYENNE | 0.5j | §3.5 |

**Livrable** : ClaimKeys confirmées cross-doc. Premier challenge factuel possible ("TLS 1.2 est-il suffisant ?").

### Phase E — C3 Ponts Conceptuels (2 semaines, FUTUR)

Uniquement quand C1+C2 sont stables et éprouvés en production.

| # | Tâche | Priorité | Effort | Section |
|---|-------|----------|--------|---------|
| E.1 | Détection co-occurrence structurelle | BASSE | 3j | §3.6 |
| E.2 | LLM arbiter pour type de relation | BASSE | 3-5j | §3.6 |
| E.3 | Contrat de non-promotion (tests) | BASSE | 1j | §3.6 |
| E.4 | UX : badge visuel distinct pour liens C3 | BASSE | 1-2j | §3.6 |

**Livrable** : ~50 bridges conceptuels navigables. Aucun bridge utilisé dans une réponse "preuve".

---

## 5. Résumé Visuel — Timeline

```
Semaine 1          Semaine 2          Semaine 3          Semaine 4+
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Phase A     │   │  Phase B     │   │  Phase C     │   │  Phase D     │
│  Corrections │──>│  Search + C1 │──>│  QS Level A  │──>│  QS LLM +    │
│  structurelles│   │  Pivots      │   │  (patterns)  │   │  ClaimKey    │
│  (§2.1-2.3)  │   │  (§3.2)      │   │  (§3.4)      │   │  (§3.4-3.5)  │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
                                                              │
                                                              v
                                                         Phase E (futur)
                                                         C3 Ponts
                                                         (§3.6)
```

---

## 6. Risques et Points de Vigilance

### 6.1 Risque — Search expansion trop large via C1

Si un CanonicalEntity relie trop d'entités, l'expansion de requête via `SAME_CANON_AS` peut ramener du bruit.

**Mitigation** : limiter l'expansion aux CanonicalEntity de confiance ≥0.90 (exclure les `soft_candidate`). Cap le nombre de résultats expandés. Actuellement non-risqué car 0 hub >50 entités.

### 6.2 Risque — Dimension Key drift en Level B

Le LLM peut produire des `dimension_key` incohérentes entre documents ("tls_min_version" vs "minimum_tls" vs "tls_requirement").

**Mitigation** : post-traitement de normalisation des dimension_keys (lemmatization + canonical form). Alternativement, fournir au LLM une liste de dimension_keys déjà connues (Level A) comme ancrage.

### 6.3 Risque — Performance du filtre version Qdrant

Ajouter des metadata axis_values aux chunks Qdrant peut impacter les performances de filtrage.

**Mitigation** : utiliser les payload indexes de Qdrant sur les champs de filtre. Benchmark avant déploiement.

### 6.4 Risque — source_doc_ids vide sur les Entity

Les Entity en Neo4j ont `source_doc_ids` vide (non peuplé par le pipeline d'ingestion). C1.1 a contourné le problème en utilisant les Claims pour l'audit cross-doc. Les phases suivantes qui nécessitent `doc_count` par Entity devront utiliser la même approche (compter via ABOUT→Claim→doc_id).

---

## 7. Métriques de Succès Globales

| Métrique | Avant | Objectif | Mesure |
|----------|-------|----------|--------|
| Entités partagées cross-doc | 11 | >200 | Requête Neo4j sur CanonicalEntity |
| Paires de documents liées | ~5 | >100 | Traversée 1-hop + 2-hop |
| Précision C1 (audit 50 cas) | — | ≥95% | Audit manuel |
| Search cross-doc | 0 | Actif | Requête "Fiori" retourne résultats multi-doc |
| QuestionSignatures récurrentes | 0 | ≥20 | Script C2a |
| ClaimKeys confirmées | 0 | ≥10 | Script C2b |
| Faux positifs contradiction | 10/10 | <1/10 | Audit RelationDetector |

---

## 8. Décisions Reportées (hors scope de ce plan)

1. **Qwen3 migration** — en attente de maturité vLLM. Pas de blocage fonctionnel.
2. **C1.3 LLM Arbiter** — après validation que C1.1+C1.2 suffisent pour le MVP.
3. **Enrichissement rétroactif claims restantes** — 1720 claims sans structured_form (LLM null ou rejeté). Nécessiterait un prompt amélioré ou un modèle plus capable. Non bloquant.
4. **source_doc_ids sur Entity** — idéalement, le pipeline d'ingestion devrait peupler ce champ. Mais le workaround via Claims fonctionne. À corriger éventuellement pour la cohérence du KG.
