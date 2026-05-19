# Contre-Review ADR Runtime V5 Reading Agent — Sonnet (Staff Engineer indépendant)

*Date : 12/05/2026*
*Reviewer : Claude Sonnet en posture staff engineer adversaire*
*ADR reviewé : `doc/ongoing/ADR_RUNTIME_V5_READING_AGENT_INDUSTRIALIZATION.md` (417 lignes, statut Proposition)*
*Mandat : challenge brutal mais constructif, GO/NO-GO factuel*

---

## 1. Verdict exécutif

**Score maturité : 6,5 / 10**

Justification : la direction technique est solide (POC validé sur 2 corpus, séparation extraction/composition propre, charte agnostic respectée dans l'intention) mais l'ADR est sous-spécifié sur 4 dimensions critiques pour la prod : sécurité (prompt injection, PII OTel), scaling (1000 req/h × 50 tenants jamais chiffré), failure modes (cold start, race conditions Neo4j, eviction Spot), et gouvernance des coûts (cap 150k tok/q sans budget enforcement effectif). Le plan de 25j est optimiste-agressif et plusieurs gates sont qualitatifs (« Fred verdict OK ≥ 8/10 ») plutôt que mesurables.

### Top 3 forces

1. **POC évidence-based à 2 corpus indépendants** (0.737 SAP / 0.779 aerospace) — rare dans le projet, légitime la bascule architecturale.
2. **Découplage extraction / composition** (§3d in fine) et **citation forcée + verifier externe** — élimine la classe d'hallucinations Goodhart sur judge LLM. C'est l'innovation centrale qui justifie l'ADR.
3. **Approches écartées documentées sérieusement** (§2a-f) avec rationale chiffrée, pas du straw-man.

### Top 5 faiblesses (par sévérité décroissante)

1. **[CRITIQUE]** **Aucune mention de prompt injection** via documents lus. Un agent qui obéit aveuglément au texte du DSG peut être manipulé par un PDF malveillant ingéré dans un tenant. Vector d'attaque non-trivial à fermer post-coup. Pas dans la matrice §7.
2. **[CRITIQUE]** **Multi-tenancy Neo4j sans isolation forte**. Le design §3b repose sur `tenant_id` property + index composite — c'est de l'isolation logicielle, pas physique. Un bug d'oubli de clause `WHERE tenant_id = $tid` dans un Cypher = cross-tenant leak. Aucune mention de défense en profondeur (rôles Neo4j, schéma par tenant, ou query interceptor).
3. **[MAJEUR]** **Scaling 1000 req/h × 50 tenants jamais modélisé**. À p50=25s et p95=60s, avec budget 65-100k tok/q, on parle de ~14 req/min sustained = 14 × 100k = 1.4M tok/min en sortie LLM. Together AI Qwen-72B-Turbo rate-limits ? DeepSeek throughput sustained ? Verifier HHEM/Lynx concurrency self-hostés ? Aucune analyse capacity planning.
4. **[MAJEUR]** **Plan-then-execute (§3e) introduit en passant** sans schéma de plan, sans gestion d'échec partiel d'étape, sans replanning. Mention « pattern Perplexity Deep Research » mais zéro design concret. Économiser 30-40% des tokens est une promesse non étayée.
5. **[MAJEUR]** **Gate « sanity check Fred 10q ≥ 8/10 » (§8.8) est subjectif et non reproductible** — ne peut pas être bloquant pour une release prod. Idem « démo presales OK » (S8). Un staff engineer ne valide pas une release de cette ampleur sur du qualitatif single-reviewer.

### Recommandation

**REWORK partiel — GO avec 8 amendements obligatoires** détaillés §7. La décision technique est juste, mais l'ADR doit être amendée avant statut Accepté. Pas de GO as-is.

---

## 2. Review architecture (sections 3a-3h)

### 3a. Découpage 8 composants

**Ce qui tient** : la séparation Router / Agent / Tools / Stores / Verifier est saine, conforme aux patterns Anthropic agents + OTel GenAI. La hiérarchie de responsabilité est lisible.

**Ce qui pèche** :
- **Single Point of Failure non identifié** : le `ReasoningAgent` est central — pas de mention de circuit breaker entre Agent et Tools (un tool qui hang 300s bloque toute l'itération). `read_timeout` par tool absent du design.
- **Cold start non traité** : la première requête après déploiement doit charger HHEM-2.1 (184M, ~2s GPU), pool Neo4j, embeddings Qdrant, prompts depuis config. Aucune warm-up policy.
- **Couplage Agent ↔ ToolRegistry hardcodé** : 11 tools listés en dur §3d. Pour ajouter un 12e tool il faut redéployer l'agent. Pas de tool discovery dynamique ni de feature flag par tenant (utile pour A/B).

**Amendement** : ajouter §3a.1 « Resilience model » avec timeout par tool (read=5s, find_in=10s, summarize_subtree=20s), circuit breaker pattern (Resilience4j-like), warm-up endpoint `/internal/runtime_v5/warmup`.

### 3b. Multi-tenant Neo4j

**Ce qui tient** : tenant_id propagé sur tous les nodes, indexes composites prévus.

**Ce qui pèche frontalement** :
- **Isolation logicielle uniquement** — un bug Cypher = leak. La charte sécurité OSMOSIS ne mentionne nulle part les contrôles.
- **Aucun row-level security Neo4j 5.x** (disponible via fine-grained access control en Enterprise edition) — l'ADR n'explicite pas si on est Community (pas de RBAC fin) ou Enterprise.
- **Pas de mention de l'audit log** des accès cross-tenant.
- **`list_versions(doc_subject, tenant_id?)`** : le `?` est dangereux. Si appelé sans tenant_id, retourne tout ? Default explicite manquant.

**Amendement** : forcer le tenant_id en paramètre obligatoire dans **tous** les tools (pas optionnel). Implémenter un `TenantQueryGuard` qui injecte la clause WHERE côté driver (pattern Cypher template). Ajouter test e2e cross-tenant leak (créer 2 tenants, query depuis tenant A doit retourner 0 résultat de tenant B).

### 3c. Pipeline ingestion

**Ce qui tient** : ordre 2.5 dans ClaimFirst raisonnable, versionning extractor utile.

**Ce qui pèche** :
- **Docling + Granite-Docling-258M** mentionnés sans benchmark de fidélité sur corpus actuel. Si Granite est inférieur à SmolDocling sur PDFs SAP complexes, perte cachée.
- **Race condition non discutée** : 2 jobs concurrents qui ingèrent le même doc (réingestion + nouvel import) → conflit `UNIQUE constraint Document.(tenant_id, doc_id)`. Pas de mention idempotence ni de lock distribué.
- **Catastrophic forgetting lors réingestion** : si Docling v2 → v3 change le schéma DocTags, les section_id changent → toutes les citations historiques en base utilisateur cassent. Pas de stratégie de migration des references.

**Amendement** : ajouter une politique de stable section_id (hash sur title+page+parent_path, pas sur ordre d'extraction). Définir un `DSGIngestionLock` Redis par (tenant_id, doc_id).

### 3d. Reading tools

Voir §3 dédié ci-dessous.

### 3e. ReasoningAgent V5.1

**Ce qui pèche** :
- **Anti-thrash basé sur `same_section_revisited > 2`** : trop grossier. Un agent peut alterner section A / B / A / B / A / B sans déclencher la règle. Préférer un Bloom filter sur tool_call signatures + score d'utilité décroissant.
- **Workspace V1 schéma Pydantic versionné** mentionné mais non spécifié — quelles invariants ? Sérialisable comment ?
- **Pas de cancellation** : si le user ferme l'onglet à l'itération 4/12, l'agent continue à dépenser 8 itérations en zombie. Coût gaspillé, OTel trace orpheline.

**Amendement** : ajouter mécanisme de cancellation token (FastAPI BackgroundTasks + check périodique). Anti-thrash robuste basé sur similarité d'état workspace, pas juste section_id revisitée.

### 3h. Endpoint API

**Ce qui pèche** :
- **Pas de streaming** : retour JSON one-shot après 60s. UX presales catastrophique. SSE ou WebSocket nécessaire pour stream le workspace en cours de construction.
- **Pas de partial responses** : si verifier rejette, on perd toute la chaîne de raisonnement visible. Le user UI doit pouvoir afficher « j'ai lu ces 4 sections mais je ne suis pas sûr ».
- **`max_iter_override` clamp [1, 12]** : un user malveillant peut forcer 12 sur 1000 questions → coût explosif. Pas de cap budget tenant-level mentionné.
- **`doc_ids: list[str]`** : pas de cap sur la taille de la liste. `doc_ids=[1, 2, ..., 10000]` accepté ? DoS facile.
- **Pas de versioning sémantique de l'API** : header `X-Runtime-Version: v5.1` OK mais pas de policy de deprecation.

**Amendement** : SSE streaming des deltas workspace, cancellation native, validation `doc_ids` ≤ 50, budget tenant journalier enforcé en amont du clamp max_iter.

### Migration V4.2 → V5.1

**Critique** : §4 mentionne « V5 devient endpoint par défaut, V4.2 reste accessible 1 mois ». **Aucun rollback plan** si V5 régresse en prod. Aucun feature flag tenant-level pour passer 10/50/100% du trafic. Pas de shadow mode (rouler V4.2 et V5 en parallèle, comparer résultats sans servir V5 à l'user).

**Régression confirmée** sur la catégorie *contextual* (V4.2=0.80 vs V5=0.70 d'après le contexte mémoire). L'ADR n'aborde pas comment combler ce -10pp avant bascule.

**Amendement** : canary par tenant (config), shadow mode 1 semaine avec divergence reporting, rollback plan automatique sur breach SLO 60s ou verifier accept rate < 70%.

---

## 3. Review reading tools (section 3d)

### Gap quantitative (0.57 → cible 0.75)

**Promesse non démontrée** : `find_quantitative` + `get_table` sont supposés combler 18pp. Sur quoi se base cette estimation ? Aucun mini-POC sur les 5 questions quantitatives échouées du gold-set SAP. C'est de la projection optimiste.

**Risques concrets** :
- L'extraction de tables avec unités cohérentes par Docling/SmolDocling est notoirement difficile sur les tableaux SAP (cellules fusionnées, colonnes croisées, unités implicites en pied de page).
- `find_quantitative(metric_query: str, value_range?, unit?)` : le `metric_query` libre suppose une résolution sémantique entre la requête (« max throughput in TPS ») et les headers de table extraits. Embedding ? Fuzzy match ? Aucun design.
- Cas typique raté : « quel est le RTO du tier production ? » → table avec headers en allemand, valeur en heures vs minutes. Le tool retournera quoi ?

### Tools manquants identifiés

| Tool manquant | Pourquoi nécessaire |
|---|---|
| `compare_across_versions(doc_subject, sections_path)` | Lifecycle : « qu'est-ce qui a changé entre v2023 et v2024 sur section X » — actuellement `list_versions` + 2× `read` + diff côté LLM, coûteux et fragile |
| `semantic_diff(section_a_id, section_b_id, granularity?)` | Comparaison sémantique fine au-delà du diff textuel — pour détecter une obligation devenue facultative |
| `citation_aggregator(claim, candidate_sections)` | Aider le LLM à choisir LA section qui supporte le mieux un claim — actuellement laissé au LLM = source d'erreurs verifier |
| `get_definition(term, doc_id?)` | Glossaire / sections de définitions — réutilisé par 30%+ des questions multi-hop |
| `list_obligations(section_id, modal?)` | Extraction normative (shall/must/should) — domain-agnostic, utile regulatory, médical, RFP |
| `find_cross_references(section_id, direction?)` | Suivre les renvois explicites « see §4.2.1 » — actuellement `resolve_ref` mais sans graphe préconstruit |
| `read_with_footnotes(section_id)` | Les footnotes contiennent souvent des conditions critiques perdues par `read()` actuellement |

7 tools manquants ≠ tool zoo : ce sont des primitives orthogonales identifiées par analyse des catégories où V5 échoue. À discuter en priorité.

### Risque « tool zoo » — est-il VRAIMENT évité ?

**Non**. §7 mentionne « Gate tool selection accuracy ≥ 95% avant tout nouveau tool » mais ne définit ni le bench de mesure ni le seuil de dégradation à partir duquel on retire un tool. C'est une promesse molle.

**Réalité** : passer de 11 à 15-18 tools en 6 mois est probable (les 7 ci-dessus + ce que l'équipe imagine). Le LLM va se perdre. La littérature (Anthropic Agents 2024, ReAct Limits 2025) montre une dégradation forte au-delà de ~15 tools sans namespacing strict.

**Amendement** : politique formelle « max 12 tools dans le registry public, tools supplémentaires en namespace `experimental_*` avec feature flag, retrait automatique si tool selection accuracy < 90% sur 4 semaines glissantes ».

### Strict JSON Schema + namespacing — exécutable ?

**Théoriquement oui** (Pydantic V2 + DeepSeek tool calling supporte strict mode). **En pratique** : DeepSeek-V3.1 a un track record connu d'ignorer les `additionalProperties=false` dans 1-3% des cas (vs 0.1% sur Claude / GPT-4o). Le fallback Qwen-72B-Turbo est encore moins strict. **Aucun mécanisme de coercition côté Python** mentionné dans l'ADR.

**Amendement** : ajouter une couche `ToolCallSanitizer` Pydantic qui rejette ou répare les appels mal formés avant exécution, métrique OTel `tool_call_repair_rate`.

---

## 4. Review verifier (section 3f)

### HHEM-2.1-Open + Patronus Lynx-8B = SOTA 2026 ?

**Réponse honnête** : c'est un choix défendable mais pas optimal en mai 2026.

**SOTA réel** :
- **Vectara HHEM-2.1** : effectivement bon (le module open-source 184M), MAIS Vectara propose désormais **HHEM 7B** (mars 2026) avec +12pp F1 sur HaluEval, non mentionné dans l'ADR.
- **MiniCheck (Liu et al. 2024)** : 770M, état de l'art sur factual consistency, plus rapide que Lynx et meilleur sur les claims multi-hop. Étrangement absent.
- **Patronus Lynx-8B** : valide, mais Patronus a sorti **Glider 3.8B** (jan 2026) qui claim parity à 2× moins de paramètres.
- **Anthropic API Citations** (mars 2026) : citation native avec garantie de span exact — exclu par charte propriétaire, OK.
- **Self-RAG critique tokens** : pertinent mais nécessite fine-tune (charte agnostic violée).

**Recommandation** : tester MiniCheck-770M en parallèle de HHEM-2.1 sur les 80 questions gold-set. Si MiniCheck ≥ HHEM, switcher.

### Threshold-by-shape (§3f) — soundness ou hand-wavy ?

**Hand-wavy**. L'ADR dit « threshold tuning par shape sur gold-set » sans définir :
- comment on calibre (Bayes optimal threshold via Youden's J ? Cost-sensitive ? Manuel ?)
- comment on évite l'overfitting du threshold sur le gold-set (split train/test du gold-set ?)
- ce qu'on fait quand `shape=unanswerable` — un verifier qui score 0.0 est-il un succès ou un échec ? Sémantique opposée.

**Amendement** : produire en S7 un fichier `verifier_thresholds.yaml` par shape avec méthode de calibration documentée + recalibration trimestrielle.

### Risque boucle infinie sur re-run conditionnel

**Présent**. §3f dit « 1 retry max » mais en cas de retry, l'agent peut re-déclencher des outils, lui-même peut atteindre `max_iter`, re-verifier rejette… La boucle est bornée mais le coût d'un cycle re-run = +50-80k tokens.

**Amendement** : budget tokens distinct pour le retry (cap 30k), tracer `retry_count` en OTel, alert si > 5% des questions re-runnent.

### Lynx-8B self-host requis ?

L'ADR dit « déployable Together » — **À VÉRIFIER**. Together AI ne sert pas Lynx-8B en serverless catalog public (mai 2026). Si déploiement custom requis = $X/h GPU dédiée 24/7 = non-trivial.

**Amendement** : valider la disponibilité Lynx-8B sur Together AI **avant** S7, sinon plan B (Patronus API hosted, mais charte propriétaire ?).

---

## 5. Review observabilité (section 3g)

### OTel GenAI v1.37 + Phoenix Arize = bon choix ?

**Oui, c'est bien choisi** — OTel GenAI v1.37 est le standard de facto post-conv OpenTelemetry oct 2025. Phoenix Arize est open-source, vendor-agnostic, intègre bien.

**Mais** :
- **Cardinalité non analysée** : labels `tenant_id` × `tool_name` × `shape` × `model` × `epistemic_status` = 50 × 11 × 7 × 2 × 4 = **30 800 séries Prometheus**. C'est gérable mais cher en stockage Loki/Mimir si on garde 30 jours. Aucune politique de retention/aggregation mentionnée.
- **Coût Phoenix Arize à l'échelle** : 1000 req/h × 60 spans/req × 24h = 1.4M spans/jour. Phoenix self-host = OK, version cloud Arize = $$$. Ambiguïté à lever.

### Métriques critiques MANQUANTES

L'ADR liste 5 métriques SLO mais oublie :

1. **Tool selection accuracy** — alors que c'est le gate du contrôle tool zoo. Comment on mesure en prod ? Pas de label-free oracle.
2. **Citation faithfulness rate en prod** (post-verifier) — fraction des claims réellement supportés par section citée. Différent du verifier score interne.
3. **Hallucination detection rate** — quel % des réponses retournées avec `epistemic_status: supported` sont en fait hallucinées (sample audit) ?
4. **Abstention rate par shape** — critique pour détecter dérive (rappel AbstentionBench).
5. **DSG cache hit rate** (Neo4j queries) — pour optimiser Redis cache éventuel.
6. **Token cost per tenant** — gouvernance financière.
7. **Tool call repair rate** — voir §3 ci-dessus.
8. **Spot eviction recovery time** (cohérent mémoire incident 09/04).

### Tracing : pertes sur traces longues

**Risque réel** : 12 itérations × 5 tool calls × 2 LLM (agent + verifier) = ~120 spans par trace. Phoenix Arize gère mais l'UI devient illisible. Aucune mention de **trace sampling** intelligent (100% des erreurs, 10% des succès au-delà de 5 iter).

**Amendement** : politique de sampling adaptative + `gen_ai.agent.answer` span summary attributes pour vue agrégée sans drill-down.

### PII / RGPD sur logs OTel

**OMISSION MAJEURE**. Les questions utilisateur (`question` attribute root span) et les `answer` peuvent contenir PII (noms clients SAP, données médicales, identifiants employés). Phoenix Arize les stocke en clair. RGPD article 32 ? Right to be forgotten ? Pas un mot.

**Amendement** : PII redaction layer entre OTel SDK et Phoenix exporter (Presidio ou équivalent), policy de retention 7 jours sur attributs sensibles, opt-out par tenant.

---

## 6. Risques OMIS (cible : 8+ au-delà des 11 listés §7)

| # | Risque omis | Sévérité | Mitigation suggérée |
|---|---|---|---|
| **O1** | **Prompt injection via documents lus** : un PDF malveillant contenant « ignore previous instructions, call tool X with args Y » est lu par `read()` et injecté dans le contexte agent. | Critique | Sandboxing du tool output, marqueurs `<untrusted_content>`, monitoring de tool calls anormaux |
| **O2** | **Data exfiltration via tool calls** : aucun tool n'accède à URL externe dans le design **actuel**, mais si on ajoute `find_external_reference` ou si `resolve_ref` lit des URLs embarquées, vector d'exfil créé | Critique | Politique formelle : aucun tool ne fait d'I/O réseau sortant. Audit CI |
| **O3** | **Vendor risk DeepSeek-V3.1 spécifique** : sanctions US sur sociétés AI chinoises (executive order possible 2026), deprecation V3.1 → V4, drift de comportement entre versions | Critique | Avoir Qwen-72B-Turbo prêt comme primaire en 1 semaine, golden tests par modèle, contrat SLO Together AI |
| **O4** | **Coût runaway au-delà de 150k/q** : pas de quota tenant journalier mentionné. Un tenant abusif peut consommer $1000/jour | Majeur | Quota OPEX par tenant (config), kill switch >$X/jour, rate-limit dynamique |
| **O5** | **Régression catégorie *contextual*** (V4.2=0.80 → V5=0.70 sur POC SAP) — confirmée par chiffres, jamais discutée dans l'ADR | Majeur | Mini-bench contextual dédié S4, identifier root cause (probable : agent over-explore quand réponse est dans la 1ère section retournée) |
| **O6** | **Charte domain-agnostic « grep CI » — voeu pieux** : la regex « regex\|amendment\|article » est trop naïve. `Article` en pascal case (entité Pydantic) passerait. Vocabulaire métier comme « tier », « SLA », « RPO/RTO » n'est pas matché. | Majeur | Lint sémantique : AST-based, list de tokens interdits maintenue + exception explicite, revue obligatoire en PR review |
| **O7** | **Race conditions persistence Neo4j multi-tenant** : 2 jobs ingèrent simultanément le même doc → constraint violation ou état partiel | Majeur | Lock distribué Redis (Redlock pattern), retry idempotent, état `ingestion_status` sur Document |
| **O8** | **Anti-abuse / DoS** : rate-limit 10/min/tenant est faible mais un user peut envoyer 10 questions à 12 iter × 100k tok = 12M tok/min. Coût $$$ avant trip d'alerte. | Majeur | Token budget /min, pas seulement req/min. Honeypot question patterns |
| **O9** | **Catastrophic forgetting réingestion** : Docling v2→v3 change section_id → toutes les citations utilisateur historiques cassent | Majeur | Stable section_id hashing + table d'aliasing pour migrations |
| **O10** | **Cold-start après spot eviction** : Burst Redis state + Neo4j connection pool + HHEM model load = 30-60s P99 premier hit | Modéré | Warmup endpoint, health check distinguant "healthy" vs "ready" |
| **O11** | **Cancellation côté API** : un onglet fermé continue de coûter | Modéré | SSE + cancellation token natif |
| **O12** | **Disaster recovery DSG Neo4j** : sauvegarde Neo4j fréquence ? RPO/RTO du DSG en cas de perte ? Réingestion 150 docs = 1 nuit. Pour 1000 docs futurs = ? | Modéré | Backup Neo4j incrémental quotidien + procédure documentée |
| **O13** | **Compliance audit trail** : qui a posé quelle question sur quel doc à quelle heure ? Pour client enterprise = exigence | Modéré | Table audit séparée (immutable, append-only), opt-in par tenant |
| **O14** | **Test golden set leakage** : les 30q SAP ont servi à designer V5 — risque overfitting. Pas de holdout strict mentionné | Majeur | Holdout 30% non-touché jusqu'à release, mesure honnête |

**14 risques omis** identifiés, dont 4 critiques et 7 majeurs. La matrice §7 actuelle (11 entrées) est notablement incomplète sur sécurité et gouvernance.

---

## 7. Amendements concrets à intégrer dans l'ADR

**Par priorité décroissante** :

### A1. Sécurité — section 3i nouvelle « Threat Model » [CRITIQUE]

Ajouter une section 3i dédiée :
- Prompt injection via documents → marqueurs untrusted, sandboxing tool output
- Multi-tenant isolation forte → TenantQueryGuard + tests cross-tenant leak e2e
- PII redaction OTel → Presidio layer + retention policy
- Politique « aucun tool n'accède au réseau sortant » + audit CI
- Cap budget tokens par tenant journalier
- Audit trail append-only

**Rationale** : sans ce volet, V5 ne peut pas être vendu à un client enterprise (SAP presales, aerospace defense). C'est un blocker commercial autant que technique.

### A2. Scaling chiffré — section 3a.2 « Capacity Planning » [CRITIQUE]

Modéliser explicitement :
- 1000 req/h × 50 tenants → req/min peak, p95 concurrence
- Throughput Together AI / DeepSeek sustained vs burst
- Verifier (HHEM/Lynx) max concurrent inferences si self-host
- Neo4j connection pool sizing
- Qdrant QPS sections collection

**Rationale** : sans chiffres, S5 va découvrir à la canary que ça ne scale pas.

### A3. Migration safety — section 3c.1 « Stable Section IDs » [MAJEUR]

- Hash déterministe `section_id = sha256(doc_id, parent_path, normalized_title, page_start)` au lieu d'IDs séquentiels.
- Table d'aliasing pour migrations cross-version Docling.
- Test de stabilité section_id sur upgrade Docling.

**Rationale** : sans ça, toute migration future casse les citations utilisateur — dette technique massive en 12 mois.

### A4. Gate de release renforcés — section 8 [MAJEUR]

Remplacer :
- ~~« sanity check Fred 10q ≥ 8/10 »~~ → blind A/B test 50q V4.2 vs V5 avec 3 reviewers indépendants, statistical significance test (McNemar)
- ~~« démo presales OK »~~ → 3 démos différents reviewers, scorecard structurée
- Ajouter holdout gold-set 30% jamais touché pendant dev

**Rationale** : un staff engineer ne signe pas une release sur du subjectif single-reviewer.

### A5. Plan-then-execute spécifié — section 3e.1 [MAJEUR]

Définir :
- Schéma Pydantic du plan
- Politique d'échec partiel d'étape (skip ? abort ? replan ?)
- Replanning : conditions de déclenchement
- Métrique OTel `plan_adherence_rate`

**Rationale** : promesse de 30-40% tokens économisés non étayée — risque de fiasco S4.

### A6. Streaming + cancellation — section 3h.1 [MAJEUR]

- SSE des deltas workspace (chaque tool call → event)
- Cancellation token natif
- Validation entrées (`doc_ids` ≤ 50, `question` ≤ 4000 chars)
- Quota tokens tenant/jour

**Rationale** : UX 60s sans feedback = inutilisable, et la gouvernance coût est inexistante actuelle.

### A7. Reading tools — section 3d révisée [MAJEUR]

- Mini-POC `find_quantitative` sur 10q quantitatives avant industrialisation full
- Ajouter `compare_across_versions`, `read_with_footnotes`, `find_cross_references` au registry initial (12 tools, plafond formel)
- Politique formelle « experimental_* namespace » pour tools au-delà du plafond
- ToolCallSanitizer Pydantic + métrique `tool_call_repair_rate`

**Rationale** : combler le gap 0.57 sans POC chiffré = pari risqué.

### A8. Rollback & canary — section 4.1 « Deployment Strategy » [MAJEUR]

- Feature flag tenant-level (0/10/50/100%)
- Shadow mode 1 semaine (V4.2 et V5 en parallèle, divergence reporting)
- Auto-rollback sur breach SLO (latence p95 > 60s sur 10 min OU verifier accept < 70%)
- Comparer catégories V4.2 vs V5 par tenant pour détecter régression *contextual*

**Rationale** : bascule en 1 mois sans rollback automatique = roulette russe.

### A9. Verifier — section 3f révisée [MODÉRÉ]

- Tester MiniCheck-770M en parallèle de HHEM-2.1
- Calibration threshold formalisée (`verifier_thresholds.yaml`)
- Valider Lynx-8B sur Together avant S7 (sinon plan B)
- Budget tokens distinct retry (cap 30k)

**Rationale** : choix verifier déterminant pour la qualité finale, mérite plus de rigueur.

### A10. Observabilité — section 3g révisée [MODÉRÉ]

- Cardinalité métriques explicitée + retention policy
- Métriques ajoutées : tool_selection_accuracy, citation_faithfulness_rate, abstention_rate_by_shape, token_cost_per_tenant, tool_call_repair_rate, dsg_cache_hit_rate
- Trace sampling adaptatif (100% errors, 10% success >5iter)
- PII redaction obligatoire

**Rationale** : observabilité actuelle insuffisante pour ops production.

---

## 8. État de l'art alternatif manqué (mai 2026)

L'ADR ne mentionne pas :

1. **Anthropic Contextual Retrieval** (mentionné en passant §3d sans citation) — papier officiel sept 2024, bench reproductible — mérite référence + chiffres attendus.
2. **Vectara HHEM 7B** (mars 2026) — successeur du 184M, +12pp F1.
3. **MiniCheck-770M** (Liu et al. 2024) — concurrent direct Lynx.
4. **GraphRAG (Microsoft 2024) vs LazyGraphRAG (jan 2026)** — l'ADR mentionne LazyGraphRAG en passant §3d mais sans contraste avec son propre design.
5. **ReAct vs ReWOO vs Reflexion** — DAG d'agents alternative, pas évalué.
6. **Anthropic Skill APIs (mars 2026)** — pattern « skill-based » émergent, alternative au tool-based pur, non discuté (charte propriétaire mais le pattern est portable).
7. **OpenAI Structured Outputs / Strict mode** comparé à DeepSeek tool calling — taux d'erreur structurée chiffrés.
8. **Anthropic Agent SDK (avril 2026)** — référence à laquelle se comparer architecturalement même si on ne l'utilise pas.
9. **BFCL (Berkeley Function Calling Leaderboard) v3** — bench tool calling où DeepSeek-V3.1 / Qwen-72B se classent comment ? Pas cité.
10. **HELM Instruct (2025)** — bench grounded answering, point de comparaison externe.
11. **AbstentionBench** est cité (charte), bien — mais les chiffres concrets sur DeepSeek-V3.1 manquent.
12. **OWASP LLM Top 10 v2 (2025)** — prompt injection (LLM01), insecure output handling (LLM02), supply chain (LLM05), excessive agency (LLM08) — devrait servir de checklist sécurité.

**Recommandation** : ajouter §11 « État de l'art comparé » avec ces 12 références.

---

## Synthèse finale

L'ADR est **techniquement légitime** mais **opérationnellement immature**. Le POC vaut la bascule, l'architecture est saine dans ses choix structurants (citation forcée, verifier externe, séparation extraction/composition, charte agnostic). Mais 4 piliers manquent pour passer en prod multi-tenant 50 clients :

1. **Threat model formel** (prompt injection, isolation tenant, PII)
2. **Capacity planning chiffré** (rien sur le scaling)
3. **Deployment strategy avec rollback** (feature flag, shadow, canary auto-rollback)
4. **Gates de release reproductibles** (pas Fred-subjectifs)

Les 10 amendements proposés (§7) couvrent ces 4 piliers + les omissions ciblées. Effort d'amendement estimé : **3-5j d'analyse complémentaire + 1 nouvelle révision ADR**, à intégrer **avant** statut Accepté.

**Recommandation finale : REWORK partiel — GO avec amendements obligatoires A1-A8 (CRITIQUE + MAJEUR), A9-A10 souhaitables.** Si ces amendements ne sont pas intégrés, le score maturité reste 6,5/10 et la release V5.1 prendra des coups en prod sur sécurité ou coût avant 3 mois.

---

*Reviewer : Sonnet en posture adversaire. Aucun conflit d'intérêt — pas auteur de l'ADR. Disponible pour défendre cette review face aux auteurs si besoin.*
