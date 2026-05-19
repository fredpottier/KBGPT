# Audit code OSMOSIS vs carte cible — préparation test Armand

**Date** : 2026-04-26
**Statut** : Document de travail (étape 2 — audit code, suit ARMAND_TEST_READINESS_TARGET)
**Auteur** : Fred + Claude Code
**Portée** : Pour chaque M/S/N de la carte cible, statut réel dans le code OSMOSIS

---

## Légende

- **✅ Implémenté** : capacité construite et fonctionnelle, à valider sur le corpus de test
- **🟡 Partiel** : capacité construite mais qualité à améliorer ou couverture incomplète
- **🔴 Absent / non vérifié** : capacité non implémentée ou impossible de confirmer sans exploration supplémentaire

---

## 1. MUST-HAVE

### M1 — Détection fiable de tensions ✅

**Composants** :
- `src/knowbase/api/services/kg_signal_detector.py` — détecteur de signaux KG (tension, temporal_evolution, coverage_gap, exactness, question_context_gap)
- `src/knowbase/claimfirst/clustering/relation_detector.py` — détection de relations entre claims
- `src/knowbase/claimfirst/clustering/value_contradicts.py` — détection de contradictions de valeurs
- Stockage : relations `CONTRADICTS` dans Neo4j sur les claims

**Architecture** :
- Détection sur claims déjà en mémoire (pas d'appel Neo4j supplémentaire au runtime de la requête)
- 4 types de signaux indépendants, additifs
- Le silence (zéro signal) est un résultat normal, pas un échec → fallback RAG pur

**Statut sur CS-25 + 2021/821** : à valider par bench, pas de raison structurelle d'échec
**Gap vs cible** : aucun gap de fond ; bench requis pour vérifier que la détection fonctionne aussi bien sur PDF juridique anglais que sur SAP/biomédical

---

### M2 — Classification des tensions 🟡 **CHANTIER PRINCIPAL**

**Composants** :
- `src/knowbase/claimfirst/clustering/contradiction_classifier.py` — classificateur LLM-based
- `src/knowbase/claimfirst/clustering/contradiction_rules.py` — règles structurelles pré-LLM
- `src/knowbase/claimfirst/clustering/tension_enums.py` — énumérations TensionLevel / TensionNature
- `src/knowbase/wiki/diffusion_flags.py` — dérivation des flags d'affichage

**Architecture actuelle** :
- **6 classes de nature** : `value_conflict`, `scope_conflict`, `temporal_conflict`, `methodological`, `complementary`, `unknown`
- **4 niveaux d'intensité** : `hard`, `soft`, `none`, `unknown`
- Pipeline 2-passes :
  1. Règles structurelles (deterministic) sur structured_form + valueframe
  2. LLM Qwen2.5-72B (via DeepInfra) sur paires non résolues
- Prompt evidence-locked : "classify, NOT decide"
- Persiste sur la relation CONTRADICTS avec flags d'affichage (show_in_article, show_in_chat, show_in_homepage, requires_review)

**Statut** : 🟡 Architecture sophistiquée et bien construite, mais qualité de la classification reconnue comme imparfaite par Fred. Cas typique d'erreur : tension marquée `value_conflict` alors qu'elle est `scope_conflict` (différence d'aire d'application).

**Gap vs cible** :
- **M2 cible** : 70% justes au confort + < 10% erreurs aberrantes
- **Statut estimé** : taux exact à mesurer sur CS-25/2021/821, mais Fred indique que le modèle confond `value_conflict` et `scope_conflict`
- **Causes probables à investiguer** :
  - Prompt LLM trop générique (exemples pas assez discriminants pour aéronautique vs juridique vs SAP)
  - ValueFrame insuffisant pour capter la dimension "scope" (qui est sémantique, pas valeur)
  - Règles structurelles couvrent mal la distinction scope (les règles existent mais lesquelles ?)

**Articulation avec ADRs existants** :
- Aucun ADR dédié à la classification de tensions à ce jour
- → **Candidat n°1 pour ADR formel** : `ADR_TENSION_CLASSIFICATION` (étape 3)

---

### M3 — Traçabilité claim-to-source ✅

**Composants** :
- `src/knowbase/api/services/synthesis.py` — prompt synthesis avec règles 4-5 ("Mandatory citations" + "Never use Block #X / Unknown source")
- `src/knowbase/claimfirst/persistence/claim_persister.py` — persistance des claims avec `EXTRACTED_FROM` vers `DocumentContext`
- `src/knowbase/api/services/proof_subgraph_builder.py` — construction du sous-graphe de preuves
- `src/knowbase/api/services/knowledge_proof_service.py` — service de preuve

**Architecture** :
- Chaque claim Neo4j a une relation `EXTRACTED_FROM` vers son DocumentContext
- Format de citation imposé dans prompt : `*(Source: Document ABC, slide 12)*`
- Règle anti-hallucination dans prompt : "Never use Block #X / Unknown source"
- Logprobs entropy calculée sur réponse pour signal de confiance (HALT/EPR refs)

**Statut sur CS-25 + 2021/821** : à valider par bench, mais structure traçable garantie par construction (chaque claim → DocumentContext via EXTRACTED_FROM)

**Gap vs cible** :
- **M3 cible** : 100% des phrases ont source valide
- **Risque résiduel** : LLM peut malgré le prompt halluciner une source. Le mécanisme de garde existe (règle 5) mais l'efficacité doit être benchmarkée sur PDF juridique long
- Pas de validation post-génération automatique que les sources citées existent réellement dans le contexte

---

### M4 — Abstention calibrée hors-corpus ✅

**Composants** :
- `src/knowbase/api/services/synthesis.py` — prompts response_modes (DIRECT/AUGMENTED/TENSION/STRUCTURED_FACT) chargés depuis `config/synthesis_prompts.yaml`
- `src/knowbase/claimfirst/query/intent_resolver.py` — IntentResolver avec C3 garde-fou lexical, INV-24 ≥2 candidats sauf exact match
- INV-EPIST-01 (evidence-locking) dans architecture

**Architecture** :
- Prompts response_modes configurés en YAML (provider-aware avec rule_7_override par provider)
- IntentResolver retourne au moins 2 candidats sauf exact match lexical → force la disambiguation plutôt que l'invention
- Classification de mode via embeddings (mode_classifier.py)

**Statut** :
- Sprint 0 a corrigé le taux de refus à tort de 33% → ~10% sur SAP
- À valider sur corpus juridique anglais

**Gap vs cible** :
- **M4 cible** : zéro hallucination + ≥ 90% abstentions claires sur 15 questions hors-corpus
- Risque : prompts response_modes calibrés sur SAP/biomédical peuvent moins bien gérer l'aéronautique (vocabulaire technique différent, phrases plus longues)

---

### M5 — Baseline factual sur questions simples ✅

**Composants** :
- `src/knowbase/api/services/mode_classifier.py` — classifie question DIRECT/TENSION/STRUCTURED_FACT par cosine similarity multilingue (e5-large)
- `src/knowbase/api/services/synthesis.py` — DIRECT mode = délégation au RAG sans enrichissement KG
- `src/knowbase/api/services/retriever.py` — retriever
- `src/knowbase/api/services/search.py` — orchestration search

**Architecture** :
- Mode DIRECT activé pour questions simples → délégation au RAG → -4 pts vs RAG pur sur SAP
- Mode TENSION/STRUCTURED_FACT activé sur questions complexes → enrichissement KG
- Mode AUGMENTED = en cours d'introduction (cf. memory project_v3_response_modes)

**Statut** :
- Sur SAP : -4 pts vs RAG pur (acceptable, dans la cible confort à -5 pts)
- Sur CS-25/2021/821 : à valider

**Gap vs cible** :
- Risque sur le corpus juridique : DIRECT mode peut être moins discriminant si embeddings e5-large performent moins bien sur l'anglais juridique technique
- Mode classifier trained sur exemples SAP/biomed → peut nécessiter ajout d'exemples aerospace/dual-use

---

### M6 — Présentation lisible du raisonnement 🟡 **À VÉRIFIER**

**Composants présumés** (à explorer plus en détail) :
- `frontend/src/app/` — interface chat avec OSMOSIS
- `src/knowbase/api/services/reasoning_trace_service.py` — trace de raisonnement
- Endpoint `/why` éventuel

**Statut** : à confirmer par exploration frontend. Le `reasoning_trace_service` existe (cf. listing services) mais l'exposition utilisateur (vue lisible des textes retenus / écartés / tensions / silences) n'est pas confirmée.

**Gap vs cible** :
- **M6 cible** : 5/5 requêtes représentatives compréhensibles sans manipulation technique
- Risque le plus élevé du panier MUST : si l'UI ne montre pas le raisonnement, le test Armand demandera explication verbale → démo-dépendance → niveau 2/3 du RDV moins atteignable

**Action recommandée** : explorer `frontend/src/app/chat` + `reasoning_trace_service.py` pour évaluer le statut UI du raisonnement.

---

## 2. SHOULD-HAVE

### S1 — Décomposition différentielle ✅

**Composants** :
- `src/knowbase/api/services/query_decomposer.py` — Query Decomposer V2

**Architecture** :
- Deux modes : Comparison/Cross-version + Multi-facettes
- Détecte questions de comparaison, énumération, chronologie
- Construit QueryPlan avec sub_queries + scope_filter (release_id, edition, etc.)
- Récupère axes connus via :
  1. Neo4j ApplicabilityAxis (axis_key + known_values)
  2. Qdrant échantillon des champs axis_*
- Principe d'intégrité : si sub-query a 0 chunks → propose clarification interactive (pas de synthèse partielle)

**Statut** : capacité confirmée fonctionnelle par Fred. ApplicabilityAxis non vide après import (3 ComparableSubjects, 22 AxisValues sur SAP).

**Gap vs cible** :
- **S1 cible** : 4/5 questions différentielles produisent un diff structurant
- À valider sur CS-25 amendments 26/27/28 successifs (cas archétypal différentiel)

---

### S2 — Classification fine des tensions (2 classes additionnelles) 🟡

**Composants** : mêmes que M2 — cf. `contradiction_classifier.py`

**Statut** :
- 6 classes existent déjà mais leur fiabilité est inégale (cf. M2)
- Les 2 classes "additionnelles" demandées par la carte cible (`précision-complément`, `équivalence reformulée`) correspondent partiellement aux classes existantes :
  - `complementary` (complément) ≈ précision-complément
  - `methodological` (méthodologique) couvre une partie d'équivalence reformulée

**Gap vs cible** : modèle existe, qualité à améliorer (couplée avec M2)

---

### S3 — Reconstitution état du droit à date donnée 🟡

**Composants** :
- `src/knowbase/claimfirst/applicability/frame_builder.py` — ApplicabilityFrame
- `src/knowbase/claimfirst/applicability/candidate_miner.py`
- `src/knowbase/claimfirst/query/temporal_query_engine.py` — moteur de requête temporelle
- `src/knowbase/claimfirst/query/latest_selector.py` — sélection de la version la plus récente
- Relations Neo4j : `SUPERSEDES`, `IS_SUPERSEDED_BY` (à confirmer dans schéma)

**Architecture** :
- ApplicabilityFrame capture année/version comme qualifiers du DocumentContext
- ContextExtractor extrait les éléments temporels du document
- ApplicabilityAxis stocke les valeurs connues (release_id, edition, date)

**Statut** :
- Capacité partiellement implémentée (memory project_sprint1_progress mentionne ApplicabilityAxis = 0 résolu pour SAP corpus)
- Reconstitution **à date** par mention dans le prompt fonctionne (un RAG le ferait aussi)
- Reconstitution **automatique** (sans précision manuelle de version) reste à mûrir

**Gap vs cible** : confirme le diagnostic de la carte cible (S3, pas M) — repositionnée en arrière-plan dans le pitch oral

---

### S4 — Classification confident sur statuts /verify ✅

**Composants** :
- `src/knowbase/api/services/verification_service.py` — VerificationService V2
- `src/knowbase/verification/assertion_splitter.py` — split text → assertions
- 4 statuts : `confirmed`, `contradicted`, `incomplete`, `unknown`

**Architecture** :
- Pipeline : split text → search_documents par assertion → compare LLM (corpus_answer vs assertion) → status + confidence + explanation
- Endpoint /verify et /correct (avec corrections proposées)

**Statut** : implémenté, qualité distinction `incomplete` vs `unknown` à benchmarker

**Gap vs cible** :
- **S4 cible** : 16/20 assertions correctement classées, distinction CONFLICTING / NOT_ENOUGH fiable
- À benchmarker spécifiquement sur cas piège (assertion avec scope différent → incomplete vs contradicted)

---

### S5 — Détection de tensions cross-corpus 🔴

**Composants** : aucun composant dédié identifié pour le linking entre **deux corpus distincts** (CS-25 ↔ 2021/821)

**Statut** :
- Le détecteur de signaux fonctionne **intra-corpus** (claims du même tenant)
- L'enrichissement KG via tension docs traverse les documents mais reste dans un même tenant/domain
- Linking d'entités cross-corpus = pas trivial sans un nom canonique partagé

**Gap vs cible** : conforme à la carte cible (S5 = bonus, pas pilier). Si un siège conforme CS-25 contient un composant Annex I, le linking exige une entité partagée canonique entre les deux corpus.

**Note** : le pack `aerospace_compliance` créé à l'étape 4b vise précisément à fournir un domaine sémantique commun pour faciliter ce cross-linking. À tester pendant l'ingestion.

---

## 3. NICE-TO-HAVE

| Capacité | Statut | Composants/Notes |
|----------|--------|------------------|
| **N1 Export PDF de la trace** | 🔴 | À construire si voulu, pas de service identifié |
| **N2 Visualisation grappes de tensions** | 🟡 | KG Health cockpit existe (cf. commit `1db6485 feat: KG Health cockpit — 4 familles de métriques`) — vérifier exposition tensions |
| **N3 Résumé exécutif d'un document long** | 🟡 | Atlas narratif existe (cf. commits `966fec6` `10daedc`) — peut servir |
| **N4 Cross-lingual FR/EN** | ✅ | multilingual-e5-large déjà en place, mode_classifier multilingue confirmé |
| **N5 Side-by-side claims en tension** | 🟡 | À explorer dans frontend KG admin |

---

## 4. Synthèse — gros sujets méritant un ADR

L'audit confirme la cible identifiée à l'étape 1 :

### ADR n°1 (priorité absolue) — `ADR_TENSION_CLASSIFICATION`
**Cible** : remonter le M2 du plancher vers le seuil de confort (70% justes + < 10% aberrantes).
**Sujets à traiter** :
- Décomposition fine du concept "scope_conflict" — distinguer scope géographique / scope temporel / scope catégoriel / scope d'application
- Enrichir les règles structurelles pré-LLM (`contradiction_rules.py`) pour mieux couvrir les cas de scope
- Calibrer le prompt LLM avec exemples spécifiques aerospace + dual-use (chaque domaine a ses pièges typiques)
- Évaluer si un classifier ML léger (en complément du LLM) sur features structurelles pourrait améliorer la précision sur `scope_conflict` vs `value_conflict`
- Mettre en place un benchmark dédié à la classification (corpus annoté CS-25 amendments + 428→821 recast)

### ADR n°2 (méthodologique, indispensable) — `ADR_BENCH_PROTOCOL_ARMAND`
**Cible** : formaliser le protocole de bench préalable que la carte cible exige (cf. §9 de TARGET).
**Sujets à traiter** :
- Construction du jeu de test annoté à partir des Change Notes EASA (vérité terrain) + analyses cabinets pour 428→821
- Formats de questions par M/S (factuelles, tensions, hors-corpus, différentielles, /verify)
- Méthodologie de scoring (juge automatisé vs Fred manuel, sur quels critères)
- Reproductibilité (versions du code, seed, seuils)
- Articulation avec le benchmark RAGAS existant (cf. memory)

### ADR n°3 (à confirmer après exploration frontend) — `ADR_RAISONNEMENT_UI`
**Cible** : si l'audit M6 révèle un manque substantiel, formaliser la conception d'une UI lisible du raisonnement.
**Sujets à traiter** :
- Quelle vue par mode de réponse ? (DIRECT, TENSION, STRUCTURED_FACT)
- Comment exposer textes retenus / textes écartés / tensions / silences sans surcharger
- Lien avec `reasoning_trace_service.py` existant
- Potentiellement aligné avec ADR_PERSPECTIVE_LAYER existant

**Décision sur l'ADR n°3** : à prendre après exploration explicite du frontend chat. Cette exploration est l'**action manquante** principale de l'audit (M6 reste 🟡 jusqu'à confirmation).

---

## 5. Actions immédiates suggérées

1. **Compléter M6** : explorer `frontend/src/app/chat` + `reasoning_trace_service.py` pour confirmer ou infirmer le 🟡
2. **Démarrer ADR n°1** : `ADR_TENSION_CLASSIFICATION` est le chantier produit principal des prochaines semaines selon la carte cible — l'ADR cadrera l'approche avant tout code
3. **Démarrer ADR n°2** : `ADR_BENCH_PROTOCOL_ARMAND` peut être rédigé en parallèle de n°1 — ne dépend pas du code à modifier
4. **Bench préalable sur corpus aerospace_compliance** : une fois le pack créé et l'ingestion validée, mesurer où OSMOSIS se situe **aujourd'hui** sur les seuils chiffrés. Sans ce baseline, on ne pourra pas mesurer l'impact des chantiers ADR n°1.

---

## 6. Articulation avec les ADRs existants

| ADR existant | Pertinence pour le test Armand |
|--------------|--------------------------------|
| `ADR_KG_QUALITY_PIPELINE_V3.md` | M1, M2, M3 — qualité KG = base de la détection et traçabilité |
| `ADR_KG_INJECTION_ARCHITECTURE_V3.md` | M5 — Response modes V3 = baseline factual |
| `ADR_PERSPECTIVE_LAYER_ARCHITECTURE.md` | M6 — couche Perspective = compréhension structurée pour restitution |
| `ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md` | M3, M5 — séparation unit-of-proof vs unit-of-reading = pilier de la traçabilité |
| `ADR_ENTITY_EXTRACTION_DOMAIN_AGNOSTIC.md` | M1, S5 — extraction d'entités = fondation pour le linking et la détection cross-doc |
| `ADR_CORPUS_VIVANT_PHILOSOPHIE.md` | S3 — temporalité, évolution corpus |
| `ADR_LOCAL_LLM_STRATEGY.md` | M2, M5 — choix du LLM (Qwen vs Claude vs Haiku selon usage) |
| `ADR_LLM_CONFIGURATION_PAGE_V2.md` | M5 — config LLM par usage (récent) |

Aucun ADR existant n'adresse spécifiquement la **classification fine des tensions** → confirme la nécessité d'ADR n°1.
