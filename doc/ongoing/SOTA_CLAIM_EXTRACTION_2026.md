# État de l'art — Extraction de claims/propositions pour KG-RAG (2024-2026)

> Date : 2026-05-25
> Contexte : challenge littéraire de la génération de claims OSMOSE (Phase B), demandé par Fred
> But : identifier les approches complémentaires pour améliorer SIGNIFICATIVEMENT la génération de claims, et décider ce qui doit être fait AVANT vs APRÈS la ré-ingestion 38 docs.
> Branche : `feat/phase-b-augmentee`

## Synthèse exécutive

Le diagnostic OSMOSE (~44% des échecs = claims absents ou trop atomiques/incomplets) **est** le problème central nommé par la littérature 2024-2026. Trois constats qui challengent l'implémentation actuelle :

1. **La granularité « atomique pure » est une erreur de conception**, pas une vertu (Molecular Facts, EMNLP 2024). Les claims trop atomiques perdent le contexte → erreurs de retrieval/vérification. OSMOSE souffre d'un **déficit de décontextualisation**. Le bug `c.text` HUM_0028 (CGSADM→CG5Z) était un symptôme du même mal de fond : **le `text` du claim est sous-spécifié**.
2. **La whitelist fermée de prédicats limite le rappel** (trade-off coverage↔consistency documenté). Suspect direct du plafond C1.
3. **Le multi-passe est sous-optimal seul (~+1.2pp)** → à prioriser APRÈS les deux points ci-dessus.

**Point clé** : les qualifiers (Phase B) et les procedures sont **validés par la SOTA** (RDF-star hyper-relational, GraphRAG covariates, event-centric KG) — à GARDER. Mais ils sont une couche par-dessus des claims trop atomiques. Il faut **corriger la granularité du `text` AVANT** que les qualifiers ne servent pleinement.

## Classement ROI (top 5)

| # | Amélioration | Source | Gain | Effort | vs OSMOSE |
|---|---|---|---|---|---|
| **1** | **Décontextualisation** des claims (anaphores résolues, entité spécifiée, portée minimale dans le `text`) — passer d'atomique à « moléculaire » | Molecular Facts EMNLP 2024 | **+6pp** accuracy ; attaque les 44% incomplets | Modéré (prompt) | **CONTREDIT** atomique pur |
| **2** | **Extraction question-guided** : templates multi_hop/conditional/lifecycle injectés dans le prompt | CQ-driven, Kommineni 2024 | cible directe du trou multi-saut/conditionnel/cycle | Faible-Modéré | COMPLÈTE |
| **3** | **Open-then-canonicalize** : extraire prédicat libre, mapper post-hoc vers whitelist, tagger `open_predicate` | EDC 2024 | lève le plafond de rappel | Modéré | **CONTREDIT** whitelist fermée |
| **4** | **Multi-stage type Claimify** (Selection→Disambiguation→Decomposition) + **ensembling 2-3 passes** pour compenser Qwen2.5-14B | Claimify MSR 2025 ; CheckThat! 2025 | 99% entailment ; compense sous-extraction 14B | Modéré (coût ×3) | COMPLÈTE |
| **5** | **PropRAG beam search** sur chemins de claims (runtime, LLM-free) + nœuds passage HippoRAG | PropRAG EMNLP 2025 ; HippoRAG 2 | multi_hop +0.30pp démontré ailleurs | Modéré-Élevé | COMPLÈTE |

## AVANT vs APRÈS la ré-ingestion (décision critique)

**AVANT** (modifient le contenu stocké → irréversibles sans re-ré-ingérer) : **#1, #2, #3, #4**. À intégrer **ensemble** dans un pipeline d'extraction révisé, puis ré-ingérer **une seule fois**. Pré-validation smoke 2-5 docs obligatoire (mesurer nb claims, décontextualisation, rappel gold-set).

**APRÈS** (runtime, indépendants du stockage, itérables) : **#5 PropRAG beam search** + nœuds passage ; MIGRES (Phase C).

⚠️ **Ne PAS ré-ingérer avant d'intégrer #1+#2+#3 (+#4).** Une ré-ingestion qui ne corrige que les qualifiers (Phase B actuelle) consommerait le budget EC2 sans corriger la cause racine (atomicité + whitelist). C'est l'enjeu majeur révélé par cette recherche.

## Validation empirique de l'urgence (mesure 25/05)

Sur 7 unités multi-corpus, Qwen2.5-14B (modèle de ré-ingestion) extrait **6 claims vs 10 pour DeepSeek-V3.1**, et **0 claim PROCEDURAL** sur la section procédurale (vs 3). Confirme la sous-extraction des petits LLM (axe 7, papier « Propositioner helps weak extractors » 2026) → #1 (pré-segmentation/décontextualisation) + #4 (ensembling) sont d'autant plus nécessaires pour Qwen.

## Plan d'action OSMOSE proposé — « P1.3.5 : Extraction Quality Upgrade » (avant P1.4)

Tout dans `src/knowbase/claimfirst/extractors/claim_extractor.py` (prompt + post-traitement), validable via le harnais `p1_2_validate_qualifiers.py` étendu, sur DeepSeek + Qwen EC2.

1. **#1 Décontextualisation** — enrichir le prompt : « chaque claim_text doit être auto-contenu : résoudre les anaphores (il/elle/ce dernier → entité nommée), spécifier l'entité sujet, inclure la portée minimale nécessaire pour lever toute ambiguïté, sans sur-charger ». Critère smoke : 0 anaphore non résolue sur échantillon, claims compréhensibles hors contexte.
2. **#2 Question-guided** — ajouter au prompt une consigne d'extraction orientée par les types de questions cibles : pour chaque unité, extraire explicitement (si présents) : conditions/prérequis, séquences/ordres, versions/dates d'applicabilité, comparaisons. Mappé sur nos types de bench (multi_hop, conditional, lifecycle, comparison).
3. **#3 Open-then-canonicalize** — autoriser le LLM à produire un prédicat libre quand aucun de la whitelist ne convient (au lieu de `structured_form=null`), tagger `open_predicate=true`, puis canonicaliser en post-traitement (mapping vers whitelist si proche, sinon garder le prédicat libre indexé). Mesure : % de claims relationnels récupérés vs whitelist seule.
4. **#4 (optionnel, coût ×2-3)** — ensembling 2 passes Qwen (températures différentes) + dé-dup sémantique, OU split entités/relations (KGGEN). À activer seulement si #1-#3 ne suffisent pas à combler la sous-extraction Qwen au smoke.

Séquence : implémenter #1+#2+#3 → smoke 2-5 docs (DeepSeek + Qwen) → si rappel/décontextualisation OK → décider #4 → ré-ingestion unique (P1.4) avec le prompt révisé → bench P1.5.

## Garder (validé SOTA, ne pas remettre en cause)
- Qualifiers structurés Phase B (temporal/spatial/version/condition/scope) ↔ RDF-star hyper-relational.
- Procedures + STEP_OF/PREREQUISITE_OF/HAS_OUTCOME ↔ event-centric KG.
- Granularité fine (proposition) ↔ Dense X Retrieval — mais « moléculaire », pas « atomique pur ».
- Procedure_chain runtime (P1.5-tool) ↔ PropRAG (chemins de propositions).

## Sources (25, datées) — voir transcript agent. Principales :
- Molecular Facts (EMNLP 2024) https://arxiv.org/html/2406.20079v1
- Dense X Retrieval / Propositionizer (EMNLP 2024) https://arxiv.org/abs/2312.06648
- APS / Gemma-APS (EMNLP Findings 2024) https://arxiv.org/abs/2406.19803
- Claimify (Microsoft 2025) https://www.microsoft.com/en-us/research/blog/claimify-extracting-high-quality-claims-from-language-model-outputs/
- PropRAG (EMNLP 2025) https://arxiv.org/abs/2504.18070
- HippoRAG 2 (2025) https://arxiv.org/abs/2405.14831
- EDC Extract-Define-Canonicalize (2024) https://arxiv.org/pdf/2404.03868
- AutoSchemaKG (HKUST 2025) https://arxiv.org/abs/2505.23628
- OG-RAG (EMNLP 2025) https://aclanthology.org/2025.emnlp-main.1674.pdf
- CQ-driven extraction (2024) https://arxiv.org/pdf/2412.20942
- LLM-KG construction survey (oct 2025) https://arxiv.org/html/2510.20345v1
- CheckThat! 2025 ensembling https://ceur-ws.org/Vol-4038/paper_62.pdf
- Microsoft GraphRAG dataflow (2024) https://microsoft.github.io/graphrag/index/default_dataflow/
- Event KG for LLM generation (ACL 2025) https://aclanthology.org/2025.acl-long.830.pdf
