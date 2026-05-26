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

---

# VOLET 2 — Correctif : réduire le volume/redondance SANS perdre le signal (post-mortem sur-extraction)

> Date : 2026-05-25 (soir)
> Déclencheur : l'implémentation P1.3.5 (Volet 1 ci-dessus : décontextualisation + question-guided + open-predicate + « extract EVERY genuine claim ») a produit une **sur-extraction massive** mesurée sur 4 docs ré-ingérés (cf `CLAIM_ANALYSIS_P1_4.md`) : 8530 claims / 4 docs ≈ 73% de l'ancien corpus entier ; Feature Scope = 6934 claims (×23). Sur-décomposition de listes/catalogues + ~6% quasi-doublons.
> But : 2e recherche littéraire — challenger Volet 1 dans l'autre sens. Volet 1 visait le **rappel** (sous-extraction Qwen) ; on a basculé dans l'excès inverse. Ce volet cherche le **point d'équilibre**.

## Renversement de diagnostic

Volet 1 nous a fait optimiser le **rappel** (« extract EVERY genuine claim » + question-guided agressif). Résultat empirique : on a viré dans l'excès opposé. La littérature 2025-2026 est sans ambiguïté sur ce point :

> **Plus de claims atomiques ≠ meilleur retrieval. La sur-atomisation dilue le signal et le bruit dégrade KG-RAG.**

- **DEG-RAG (« Less is More: Denoising KGs for RAG », arXiv:2510.14271, oct 2025)** : supprimer **40% des entités / 30-60% des relations améliore SYSTÉMATIQUEMENT** la perf RAG (winning rates 42-61%). Phrase-clé : *« knowledge graph quality matters more than size »*. **Validation empirique directe de notre intuition.**
- **Proposition-based chunking parmi les PIRES performers** (langcopilot 10/2025, ragaboutit « 2026 RAG Performance Paradox ») : *« when your system retrieves 20 tiny propositions instead of 5 coherent chunks, you're not improving context quality »*. → notre ×23 risque d'**activement dégrader** le retrieval, pas juste de coûter cher.
- **Gleaning GraphRAG = anti-pattern pour nous** : le gleaning re-demande N fois au LLM les claims manqués → conçu pour LLM qui *sous-extraient*. Notre prompt « extract every genuine claim » **reproduit l'esprit du gleaning** — c'est la cause du ×23. LazyGraphRAG (2025) a réduit ce coût à 0.1% en différant l'extraction exhaustive. → **max_gleanings = 0, un seul passage, pencher rappel→précision.**

## Concepts-clés à injecter

1. **Molecular Facts (EMNLP 2024)** [déjà cité Volet 1, mais mal appliqué] : deux critères opposés — **décontextualité** (tient seul) ET **minimalité** (le minimum d'info). *« Les faits totalement atomiques ne sont PAS la bonne représentation. »* Variance énorme entre méthodes (20.2 vs 32.9 sous-claims/bio) → la granularité est un **hyperparamètre, pas une vérité**. On a gardé la décontextualité (bien : 96%) mais **violé la minimalité** (énumération `X available in A,B,C` → 11 claims).
2. **Granularité adaptative par densité (Optimizing Decomposition, ACL 2025, arXiv:2503.15354)** : les politiques fixes (FactScore, SAFE) gèrent mal les **densités factuelles variables** — exactement notre cas (Feature Scope catalogue dense vs doc narratif). Une politique uniforme est inadaptée. → granularité plus **grossière** pour les docs catalogue.
3. **CORE (arXiv:2403.11903)** : décorateur post-décomposition en 3 temps — (a) filtrage par entailment (vire hallucinations), (b) scoring d'informativité (∆Info), (c) **dé-dup par maximum-weight independent set** (si claim A ⊨ B, redondants). Conçu pile pour retenir un **set minimal unique informatif**.
4. **Hybrid verification regex + LLM-judge (arXiv:2602.11886, 2026)** : hallucination de sujet **65.2% → 1.6%**. Le **regex-match** est l'outil pour préserver/valider nos identifiants exacts (transactions SAP, codes WWI, ALL_CAPS / `\w+_\w+`) — là où le cross-encoder sémantique régressait (cf factual -0.233pp Config C).

## CLASSEMENT — Top 5 leviers ROI (réduire volume sans perdre valeur)

| # | Levier | Type | Source | Effort | Pourquoi |
|---|---|---|---|---|---|
| **1** | **Granularité MOLÉCULAIRE + anti-énumération explicite** : remplacer « extract EVERY genuine claim » par critères molecular fact ; règle dure « an enumeration (X available in A,B,C) is ONE claim with a list value or qualifiers, NOT N claims » | PROMPT | Molecular Facts | Faible | Attaque la cause racine du ×23 (sur-décompo listes). Exploite l'infra **ClaimQualifier (P1.1) déjà livrée** pour porter les énumérations. |
| **2** | **Dédup sémantique en cascade tiered** : (1) exact/MinHash → (2) embedding cosine ~0.93 (SemHash, on a déjà `claim_embeddings`) → (3) entailment NLI sur paires candidates (logique CORE) | POST | DEG-RAG, CORE, SemHash | Faible-Moyen | Déterministe, mesurable, vire les ~6% doublons + résidu sur-décompo. Réutilise HHEM-2.1 / bge-reranker en place. **Filet de sécurité indépendant de la variance LLM.** |
| **3** | **Filtre d'utilité / check-worthiness** : gate LLM-judge « worth storing? » + seuil fiabilité (triple reflection DEG-RAG). **Garde-fou : ne JAMAIS filtrer un claim contenant un identifiant ALL_CAPS** (regex protect) | POST | DEG-RAG, CheckThat! 2024, Noise-or-Nuance | Faible | Vire le trivial (« the document describes… »). On a déjà l'infra LLM-judge. |
| **4** | **Granularité adaptative par type de doc** : détecter docs catalogue/spec denses (« Feature Scope ») → granularité grossière + extraction structure-aware (1 claim/entrée de liste) | PROMPT+ROUTING | Optimizing Decomposition ACL 2025, Mix-of-Granularity | Moyen | C'est LE doc qui explose à 6934. |
| **5** | **Summarization-guided / salience** : « extract only propositions that would appear in an extractive summary » | PROMPT | Salient Proposition Annotation 2026 | Faible | Filtre le « not worth mentioning » en amont. Complément de #1. |
| transverse | **Désactiver tout gleaning / exhaustivité** : un seul passage, max_gleanings=0 | PROMPT | GraphRAG, LazyGraphRAG | Faible | Notre prompt = esprit gleaning. |

## Séquencement recommandé (critique)

1. **D'ABORD #2 (dédup post) + #3 (filtre utilité)** : déterministes, mesurables isolément, **pas de variance LLM**. Mesurer la réduction de volume + l'effet retrieval AVANT de toucher au prompt (cohérent avec « recall audit avant optim » + « smoke-first »).
2. **PUIS #1 + #4 (prompt)** : valider par smoke 2-5 docs que Qwen/DeepSeek respectent la granularité moléculaire — **risque de variance open-source réel** (notre historique le montre : les petits LLM ratent les consignes fines de granularité sous pression).
3. **#5** en affinage.

**Point critique (vs erreur Volet 1)** : ne PAS régler le volume par le prompt seul. Le post-traitement déterministe (#2/#3) est le filet de sécurité — c'est aussi ce que la littérature 2025-2026 recommande (DEG-RAG, CORE = couches post-extraction, pas confiance aveugle à l'extracteur). Volet 1 a fait l'erreur inverse : tout miser sur le prompt.

## GraphRAG / LightRAG / HippoRAG — ne résolvent PAS notre cas

- GraphRAG : pas d'anti-redondance natif (au contraire, gleaning). Merge d'entités demandé mais pas natif (issue #401).
- LightRAG : dédup limitée au **string-matching exact** (issues #1323/#2528) → rate les paraphrases.
- nano-graphrag : exact-match aussi.
- HippoRAG : PageRank au retrieval, rien à l'extraction.
- → notre problème (claims-phrases redondants, pas entités) **exige une couche sémantique ajoutée** (CORE/SemHash/DEG-RAG-like). Aucun framework ne nous l'offre gratuitement.

## Sources Volet 2 (≥12 datées)
- Less is More / DEG-RAG (oct 2025) https://arxiv.org/abs/2510.14271
- CORE: A Closer Look at Claim Decomposition (2024) https://arxiv.org/abs/2403.11903 — repo https://github.com/zipJiang/Core
- Optimizing Decomposition for Optimal Claim Verification (ACL 2025) https://arxiv.org/html/2503.15354
- Not Worth Mentioning? Salient Proposition Annotation (2026) https://arxiv.org/abs/2603.27358
- Noise or Nuance: Filtering for LLM-Driven AKBC (2025) https://arxiv.org/pdf/2509.08903
- Document Chunking for RAG, 9 strategies tested (10/2025) https://langcopilot.com/posts/2025-10-11-document-chunking-for-rag-practical-guide
- The 2026 RAG Performance Paradox https://ragaboutit.com/the-2026-rag-performance-paradox-why-simpler-chunking-strategies-are-outperforming-complex-ai-driven-methods/
- SemHash semantic dedup (2024-2025) https://minishlab.github.io/semhash-blogpost/
- MinHash LSH in Milvus (2025) https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md
- CheckThat! 2024 check-worthiness https://arxiv.org/pdf/2406.18297
- LLM Triplet Extraction regex+judge 65%→1.6% (2026) https://arxiv.org/abs/2602.11886
- GraphRAG gleaning issues https://github.com/microsoft/graphrag/issues/613
- LightRAG dedup string-exact issues https://github.com/HKUDS/LightRAG/issues/1323
- Mix-of-Granularity for RAG (2024) https://arxiv.org/html/2406.00456v1

---

## Sources Volet 1 (25, datées) — voir transcript agent. Principales :
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

---

# VOLET 3 — Fiabilité de la granularité avec LLM open-source (Qwen) : conception du #1/#4

> Déclencheur (26/05/2026) : avant de coder #1/#4 (prompt), se référer à la littérature car les LLM open-source suivent mal les consignes fines de granularité, **notamment Qwen** (ré-ingestion Qwen2.5-14B, extraction prod Qwen3-235B). But : maximiser la fiabilité.

## Le problème, nommé par la littérature
- **IFEval & dérivés** : les LLM échouent surtout sur les contraintes de **COMPTAGE / LONGUEUR / multi-contraintes** simultanées (« at most 600 »→« at most 610 » fait échouer des cas). **Implication directe : une cible « ~300 claims/doc » est le MAUVAIS levier** — Qwen ne tiendra pas un nombre.
- **Open-source + multi-contraintes simultanées = dégradation marquée.** Le prompt P1.3.5 actuel entasse **5 consignes dans 1 appel** (décontextualisation + question-guided + open-predicate + qualifiers + « extract EVERY claim ») → exactement le profil d'échec décrit. C'est la cause mécanique de la sur-extraction, pas un réglage à ajuster.

## Le remède SOTA : restructurer la TÂCHE, pas empiler les consignes
Principe transversal (**Claimify, DPPM, DeCRIM, ACONIC**) : **décomposer la tâche d'extraction en sous-tâches focalisées** réduit la charge sur le LLM faible et fait bondir la fiabilité (+10-40 pp selon ACONIC/DPPM).

1. **Pipeline multi-étapes séquentiel (Claimify), 1 prompt focalisé/étape — PAS un méga-prompt** :
   - **A. Sélection / check-worthiness** : par phrase/passage, « contenu vérifiable substantiel ? sinon DROP (opinion/boilerplate/méta) ». = notre **#3 déplacé À l'extraction** (validé par le smoke utilité Volet 4 de CLAIM_ANALYSIS).
   - **B. Décomposition à minimalité** : contenu retenu → claims autonomes, **PRINCIPE explicite** « garder le contexte critique ensemble ; ne PAS éclater une énumération en N claims ; une liste = UN claim » (Claimify : « inflation caused hardship » reste 1 claim). = **#1**.
   - **C. Décontextualisation** : résoudre anaphores via contexte passage ; si irrésoluble, **flaguer plutôt que deviner** (cohérent « NULL > faux »). `passage_context` déjà en place → garder.
   - (Fusion possible B+C ; mais la **Sélection en GATE séparée** = le plus gros gain de fiabilité.)

2. **Contrôler la granularité par RÈGLE + STRUCTURE de sortie, jamais par un nombre** :
   - Règle déterministe : 1 claim = 1 assertion (sujet, prédicat, objet) ; **énumération d'items partageant le même prédicat → 1 claim dont l'objet est la LISTE**.
   - **Structured/guided decoding (XGrammar via vLLM**, défaut vLLM/SGLang 2026, garantit le schéma à 100%). **CLÉ** : concevoir le schéma pour que l'énumération soit un **CHAMP** (`{"subject","predicate","objects":[...]}`) → « 1 claim avec liste » devient le **chemin de moindre résistance**, pas N claims. Le schéma **façonne** le comportement, plus fiable qu'une consigne en prose.

3. **Few-shot démonstratif** (2-3 exemples cross-domaines, domain-agnostic) : montrer une énumération gardée en 1 claim + une opinion DROP. Les démonstrations battent les consignes abstraites pour les modèles faibles (Molecular Facts = prompting 2 étapes ; AFEV = démonstrations dynamiques).

4. **Granularité adaptative par type de doc (#4)** — forme **fiable** = **ROUTAGE déterministe en amont** (catalogue/feature-scope vs guide procédural vs narratif) → instruction/schéma spécifique au type. Catalogue → biais coarse (1 feature = 1 claim, listes restent listes). **NE PAS** demander au LLM de s'auto-adapter en cours de route (peu fiable). (AFEV montre l'auto-adaptation possible mais dépend d'un reranker fine-tuné + demos dynamiques — trop lourd ; le routage déterministe est l'équivalent robuste.)

5. **Auto-correction (DeCRIM) = filet optionnel** (« as-tu sur-éclaté une liste ? fusionne »). Coûte un appel LLM ; notre **dédup déterministe (#2) attrape déjà beaucoup**. Préférer le post-traitement déterministe (moins cher, zéro variance) à l'auto-critique LLM.

## Spécificités Qwen (fiabilité)
- **Qwen2.5-14B** (ré-ingestion) : `guided_json` via vLLM propre, pas de toggle thinking → **utiliser XGrammar**.
- **Qwen3-235B** (extraction prod) : **BUG vLLM connu** — `guided_json` + `enable_thinking=False` → JSON malformé. Garder `enable_thinking=True` OU valider/réparer (vLLM issue #18819).
- Température basse (0.0-0.2) ; prompts **COURTS et mono-focus** par étape.

## Conséquence pour la refonte extraction (P1.4-bis)
Remplacer le méga-prompt P1.3.5 par : **routeur type-doc → [Sélection] → [Décomposition-minimalité + Décontextualisation] sous guided decoding à schéma « liste-comme-champ »**. Garder décontextualisation (96%) + qualifiers (peu coûteux quand présents). **Valider smoke 2-3 docs avec les 2 probes** (volume + dédup + utilité) AVANT ré-ingestion complète. Le post-traitement #2/#3 reste le filet de sécurité.

## Sources Volet 3 (datées)
- Claimify / « Towards Effective Extraction and Evaluation of Factual Claims » (Microsoft, ACL 2025) — pipeline Selection/Disambiguation/Decomposition, multi-prompts séquentiels https://www.microsoft.com/en-us/research/blog/claimify-extracting-high-quality-claims-from-language-model-outputs/ — papier https://aclanthology.org/2025.acl-long.348.pdf
- AFEV « Fact in Fragments » (juin 2025) — granularité adaptative itérative + STOP + claim original comme ancrage https://arxiv.org/html/2506.07446v1
- DeCRIM (Decompose-Critique-Refine, EMNLP 2024) — auto-correction multi-contraintes, gains même avec feedback faible https://arxiv.org/pdf/2410.06458
- DPPM Decompose-Plan-Merge multi-contraintes (2025) https://arxiv.org/html/2506.02683
- ACONIC systematic decomposition by complexity, +10-40pp (oct 2025) https://arxiv.org/html/2510.07772v1
- IFEval (Google) — multi-contraintes, échecs comptage/longueur https://www.envisioning.com/vocab/ifeval-instruction-following-eval
- AGENTIF instruction-following benchmark (2025) https://arxiv.org/pdf/2505.16944
- « The Instruction Gap: LLMs get lost in following instruction » (2026) https://arxiv.org/html/2601.03269
- vLLM Structured Outputs / XGrammar (défaut vLLM 2026) https://docs.vllm.ai/en/latest/features/structured_outputs/
- JSONSchemaBench (jan 2025) — XGrammar > Outlines en compliance/latence https://arxiv.org/html/2501.10868v1
- vLLM bug Qwen3 `guided_json` + `enable_thinking=False` (issue #18819) https://github.com/vllm-project/vllm/issues/18819
- Document-level Claim Extraction = extractive summarization (salience) + décontextualisation (2024) https://arxiv.org/html/2406.03239v1
