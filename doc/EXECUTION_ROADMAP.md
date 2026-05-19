# OSMOSIS — Execution Roadmap

> **Version :** 1.0 (18 mai 2026)
> **Statut :** Vivant — révisé à chaque fin de phase
> **Relation à VISION.md** : VISION = "où on va et pourquoi", ROADMAP = "comment et quand". Ce doc est **subordonné** à VISION.md ; il s'y conforme et est mis à jour quand la vision évolue.

---

## 0. Pourquoi ce document existe

VISION.md décrit l'architecture cible (modèle bitemporel, hiérarchie 2-niveaux, Probability Isolation, multi-domaines). Mais cette vision est **largement aspirationnelle** au 18/05/2026 : la majorité des composants ne sont pas implémentés conformément, et les briques existantes (V5.1, ClaimFirst, UI) ont des niveaux de maturité hétérogènes.

Ce document :

1. **Mappe** chaque capacité C1-C5 et chaque composant architectural à un statut concret (implémenté / partiel / planifié / à invalider)
2. **Phase** la refondation en étapes mesurables avec dates cibles et critères de passage
3. **Définit les kill switches** : quel résultat empirique invalide quelle hypothèse, et donc déclenche un pivot
4. **Identifie les briques critiques** dans l'ordre de priorité justifié par la valeur produit

Principe directeur (validé 18/05/2026) :

> **La fiabilité de la réponse précède toujours sa traçabilité visuelle. Tant que la réponse n'est pas fiable, le click-to-source enrichi est inutile.**

Donc on travaille **d'abord** sur la qualité (KG-first runtime, bitemporel, agnosticité prouvée), **ensuite** sur l'UX (click-to-source enrichi).

---

## 1. Matrice de maturité au 18/05/2026

### 1.1 Capacités produit (C1-C5)

| Capacité | Définition (VISION §5.1) | Cible | État réel 18/05 | Source | Gap | Bloqueur principal |
|---|---|---|---|---|---|---|
| **C1** Réponse directe | Q/A factuel | ≥80% | 0.61 | `benchmark/runs/v51_bench_50q_v6j2_ds31_20260518T071051Z_scored_20260518T100157Z.json` (V5.1+DS-V3.1, 50q stratifiées) | -19pp | Architecture textuelle V5.1 sans KG sémantique runtime |
| **C2** Synthèse multi-doc | Réponse cross-doc | ≥80% | +19pp vs RAG (proxy) | Bench T4 mars 2026, pas re-mesuré | Inconnu post-V5.1 | Bench récent à faire |
| **C3** Raisonnement différentiel | Lifecycle, évolution | ≥80% | 0.25 | Même bench que C1 (`v6j2_ds31_*_scored`, ligne `lifecycle n=2 mean=0.250`) | -55pp 🔴 | Aucune représentation temporelle structurée |
| **C4** Détection tensions | Contradictions | 100% surface | 100% vs RAG 0% | Bench Sprint 0 mars 2026, pas re-mesuré | À re-confirmer | Bench récent à faire |
| **C5** Validation /verify | AI Act, abstention | ≥95% sur unanswerable | Non benché récemment | — | Inconnu | Bench dédié à concevoir |

### 1.2 Composants architecturaux

> **Note méthodologique** : Cette matrice est partiellement basée sur un **audit code réalisé le 18/05/2026** par sub-agent Explore sur `src/knowbase/runtime_v5/` (48 fichiers, 12.6k LOC). Verdict global : **65% du code V5.1 réutilisable** comme infrastructure pour runtime_v6, **13% à supprimer** (orchestration agentic contraire à Probability Isolation + injections corpus contraires à AX-11), **22% à adapter**.

| Composant | Spec VISION | État réel 18/05 | Maturité |
|---|---|---|---|
| **Pipeline ingestion ClaimFirst** | 9 phases (§4.3) | Implémenté, validé | 🟢 Production |
| **Schéma Neo4j Document + Claim** | Hiérarchie 2-niveaux (§3.1) | Claim existe, Document partiel, hierarchy partielle | 🟡 70% — manque structuration explicite Document/Section |
| **Bitemporel sur Claim** | 4 timestamps (§3.2) | `valid_from` partiel ; `ingested_at` existe ; `valid_until`, `invalidated_at` **manquants** | 🔴 30% |
| **Supersession doc-level** | `SUPERSEDES` (§3.3) | REAFFIRMS existe (CH-02.3), SUPERSEDES partiel | 🟡 50% |
| **Relations claim-vs-claim** | SAME_AS / EVOLUTION_OF / CONTRADICTS (§3.3) | LIFECYCLE_RELATION + LOGICAL_RELATION existent mais sémantique différente | 🟡 40% — refacto à faire |
| **Schéma Qdrant projection** | `knowbase_chunks_v2` (§4.2) | Existant et fonctionnel | 🟢 Production |
| **Runtime KG-first (intent-first)** | Pipeline §4.4, 2 LLM calls | V5.1 = ~12-15 LLM calls/q (boucle 6-8 iter + multiform×5 + verifier) | 🔴 0% — à construire (cf §2 Phase A3, audit estime 8-10j) |
| **3 modes dégradation** (REASONED/ANCHORED/TEXT_ONLY) | §4.5 | `graph_first_search.py` existe mais désactivé en runtime | 🟡 30% — code base existant mais inactif |
| **Probability Isolation** | LLM uniquement intent+format (§3.5) | V5.1 contraire — agent multi-itérations + multiform LLM | 🔴 0% |
| **Domain Pack mécanisme** | Pluggable JSON (§2.3 AX-11) | Concept défini ; `domain_pack_loader.py` actuel injecte context_defaults dans prompt V5.1 → contraire à agnosticité stricte, à supprimer puis re-concevoir | 🔴 10% — design + impl à reprendre |
| **Frontend click-to-source page exacte** | (§5.3) | Implémenté (CH-05.3, CH-05.5) | 🟢 Production |
| **Frontend claim verbatim affiché** | (§5.3) | Partiel — à vérifier dans SourcesFootnotes | 🟡 50% |
| **Frontend confidence + dates** | (§5.3 #3) | Pas affiché | 🔴 0% — dépend du bitemporel |
| **Verifier HHEM-2.1** | Mode A passive (CH-52.8) | Branché V5.1 mais inopérant (corrélation outcome↔score nulle) | 🟡 50% — code OK, sémantique cassée |
| **Multi-tenant isolation** | (§9.x via OPS) | Tests cross-tenant leak passent | 🟢 Production |
| **Observabilité OTel** | (CH-52.7) | Branchée pipeline V5.1 | 🟢 Production |
| **Infrastructure API (Admission, Idempotency, JobStore, SSE)** | (§4.4 endpoint async) | Implémentée et production-ready via CH-52.6 | 🟢 Production — réutilisable telle quelle pour runtime_v6 |
| **ToolRegistry + ToolSpec Pydantic** | (CH-52.4.1) | Implémenté, validé | 🟢 Production — réutilisable telle quelle |
| **ClaimSegmenter + Verifier backends + Answer-level checks** | (CH-52.8) | Implémentés, déterministes, domain-agnostic | 🟢 Production — réutilisable telle quelle |

### 1.3 Légende maturité

| Niveau | Définition |
|---|---|
| 🟢 Production | Implémenté, validé par bench/test, en service |
| 🟡 Partiel | Implémenté partiellement OU implémenté mais non aligné spec VISION |
| 🔴 Manquant | Non implémenté, à concevoir et construire |

---

## 2. Phasage de la refondation

### Principe : ordre par valeur produit

1. **D'abord** : Phase A (qualité de réponse C1+C3) — sans ça, tout le reste est inutile
2. **Ensuite** : Phase B (validation agnosticité par kill switch) — qu'on échoue tôt si l'hypothèse est fausse
3. **Puis** : Phase C (UX enrichie click-to-source) — quand on a quelque chose qui mérite d'être affiché
4. **Enfin** : Phase D (industrialisation, Domain Packs) — production-ready

### Phase A — Refondation runtime KG-first (3-4 semaines effective)

**Objectif** : passer de 0.61 → ≥0.75 sur C1 et 0.25 → ≥0.50 sur C3 sur le panel SAP existant.

> **Note importante post-audit 18/05** : `CH-52` n'est PAS jeté. L'audit code montre que **65% de V5.1 est de l'infrastructure réutilisable** (API Pydantic, AdmissionController, IdempotencyStore, JobStore, SSE, OTel, MetricsRegistry, PIIRedactor, Neo4j DSG, TenantQueryGuard, ToolRegistry, ClaimSegmenter, Verifier backends, BudgetTracker, CancellationToken). Seule l'**orchestration agentique** (`reasoning_agent_v51.py` 828 LOC, `query_reformulator.py`, `loop_signature.py`, `execution_plan.py`) est à **réécrire** car contraire à Probability Isolation. Plus quelques composants à **supprimer** car contraires à AX-11 agnosticité (`domain_pack_loader.py` injection prompt, `doc_topics_loader.py`).

#### A1. Modèle bitemporel sur Claim (1 sem)
- ADR `ADR_BITEMPOREL_CLAIMS.md` validé
- Migration schéma Neo4j : ajouter `valid_from`, `valid_until`, `invalidated_at` (`ingested_at` existe déjà) sur tous les Claim existants (valeurs par défaut)
- Mise à jour pipeline ingestion (étape 1 Document Profile : extraire `version` + `valid_from` du doc ; étape 9 persistance : peupler timestamps claim)
- Tests : 100% des claims persistés ont les 4 timestamps après cette phase (Gate-B de VISION)

#### A2. Relations claim-vs-claim explicites (1 sem)
- Étape 8 du pipeline ingestion (cf VISION §4.3) : classifier `SAME_AS` / `EVOLUTION_OF` / `CONTRADICTS` / `REFINES` / `QUALIFIES`
- Logique : matching par `(subject_canonical, predicate)`, puis classification selon marker_type (explicit / inferred / prudence)
- Migration : exécuter cette classification sur le corpus SAP existant
- Test : sur le bench T2 contradictions, atteindre ≥90% de surface correcte (vs 100% mars 2026 à recalibrer)

#### A3. Runtime intent-first (2 sem)

*Estimation post-audit : 8-10 jours full-stack (1 personne soutenue) + buffer ≈ 2 semaines.*

- ADR `ADR_PROBABILITY_ISOLATION.md` validé
- Nouveau module `runtime_v6/` avec : `IntentResolver` (1 LLM call) → `Cypher templates` (déterministe, génération de plan basée sur intent type) → `Format response` (1 LLM call, formatage humain zéro création de fait)
- **Réutilisation infrastructure V5.1** (estimation 0j d'effort net) : API Pydantic models, AdmissionController, IdempotencyStore, JobStore, SSE, OTel/metrics, ToolRegistry, Verifier (post-synthèse, mode active désormais), BudgetTracker, CancellationToken
- **Suppressions ciblées (1-2j)** : `query_reformulator.py`, `loop_signature.py`, `execution_plan.py`, `domain_pack_loader.py`, `doc_topics_loader.py`, `anthropic_llm_caller.py` (hors charte open-source)
- **Adaptations (2-3j)** : HTTPLLMCaller (2 callsites seulement en V6), Workspace schema (champs evidence_from_kg au lieu de tool_calls), thresholds verifier (recalibration potentielle), Reading tools (déplacer en module séparé `fallback_text_only/`, accessible uniquement quand KG silencieux)
- Migration **shadow mode au niveau API** (confirmé faisable par audit) : `/api/runtime_v5/answer` (V5.1 boucle agent) et `/api/runtime_v6/answer` (KG-first) coexistent. Le bench tape les deux endpoints en parallèle sur le panel. Ramp progressive du trafic (0 → 10 → 50 → 100%) sur 2-3 semaines post-A3
- Bench latence : cible p50 <30s, p95 <60s
- Bench qualité : cible C1 ≥0.75, C3 ≥0.50 sur 50q SAP stratifiées
- Kill switch K-3 (cf §3) si non atteint

### Phase B — Validation cross-domain (2 semaines)

**Objectif** : prouver empiriquement l'agnosticité du **core** (sans Domain Pack) ou pivoter.

> **Limite assumée** : cette phase teste l'agnosticité du **core seul**, sans Domain Pack actif (les Domain Packs arrivent en Phase D). Donc si <70% sur un corpus non-SAP :
> - **Interprétation A** : agnosticité fondamentalement impossible → invalidation de AX-11/12/13 → pivot architectural obligatoire (Kill switch K-1)
> - **Interprétation B** : Domain Pack vraiment indispensable (le core seul ne suffit pas) → re-prioriser Phase D avant Phase C
> Pour distinguer A vs B, ajouter un test de contrôle : run sur corpus SAP via le core nu (sans context_defaults.json). Si SAP aussi chute, c'est l'option A. Si SAP reste OK, c'est l'option B.

#### B1. Construction corpus de validation (5 jours)
- **Corpus juridique** : 10-15 documents libres de droits (ex: extraits CRR/Bâle III, GDPR, AI Act — déjà partiellement présents dans les anciens corpus)
- **Corpus médical** : 10-15 publications open access (PubMed Central) sur un protocole versionné (cf doc/ongoing/etudes/CORPUS_PREECLAMPSIA_PLAN.md déjà ébauché)
- Ingestion via pipeline ClaimFirst existant (non-régression pipeline)

#### B2. Construction gold-set de fumée (4 jours)
- **10 questions par corpus** (mini-gold-set, pour ne pas y passer 2 semaines à seul). Acceptable car Phase B est un test go/no-go, pas une mesure de précision fine.
- Mix : 4 factual + 3 lifecycle/evolution + 2 contradictions + 1 unanswerable
- Questions humaines (pas LLM-bootstrapped) pour éviter biais — rédaction par Fred (utilisateur produit) qui a une compréhension métier des deux corpus
- Annotation des `expected_identifiers` et `supporting_doc_ids` par lecture humaine du corpus

#### B3. Bench cross-domain + verdict Gate-F (3 jours)
- Lancer runtime_v6 (issu Phase A) sur les 2 corpus + leurs gold-sets + un run de contrôle sur SAP sans Domain Pack
- Mesure : factual + lifecycle + abstention sur chaque corpus
- **Kill switch K-1 (Gate-F)** : si <70% factual sur un des 2 corpus non-SAP, déclencher l'analyse interprétation A vs B (cf encadré ci-dessus), puis appliquer le scénario de pivot correspondant (cf §3.2)
- Si OK : valider AX-11/12/13 empiriquement, mettre à jour §6.3 de VISION.md

### Phase C — Enrichissement UX traçabilité (1-2 semaines, conditionnée à Phase A+B OK)

**Objectif** : passer du click-to-source minimal (page exacte) à la traçabilité complète promise (§5.3).

#### C1. ADR + composant SourcesFootnotes enrichi (3 jours)
- `ADR_CLICK_TO_SOURCE_FRONTEND.md` validé
- Affichage systématique du **claim verbatim** dans la footnote (déjà partiel, à compléter)
- Affichage **confidence** + **source_authority**
- Tooltip claim verbatim au survol des pills inline

#### C2. Affichage dates bitemporelles (2 jours, dépend Phase A1)
- Badge "valid from" / "valid until" / "current" / "obsolete" sur chaque citation
- Filtre temporal-aware dans l'UI : "tel jour" / "actuel"

#### C3. (Optionnel, plus tard) Highlight span précis dans PDF (3-5 jours)
- Viewer PDF.js custom remplaçant le PDF viewer natif browser
- Support highlight via `?highlight=span_id` dans l'URL
- Coût élevé pour bénéfice marginal — décision après C1+C2

### Phase D — Production hardening (2-3 semaines, conditionnée à Phase A+B+C OK)

**Objectif** : transformer en produit utilisable par un client zéro.

#### D1. Domain Pack mécanisme (1 sem)
- ADR domain pack lifecycle déjà existant (à ressortir des archives ou réécrire)
- Plugin JSON minimal : entité métier supplémentaires, vocabulaire (synonymes), patterns d'évolution
- Test sur **2 packs** : SAP enterprise + un autre (juridique ou médical selon Phase B)

#### D2. CI/CD + tests automatisés (3 jours)
- Pipeline GitHub Actions
- Tests bench automatique sur PR (smoke 10q)
- Gate-A automatique (audit `grep` corpus-specific)

#### D3. Sécurité enterprise minimale (3 jours)
- SSO/SAML stub (au moins un connecteur OAuth)
- Secrets management via Vault ou équivalent
- Audit log multi-tenant

#### D4. Documentation utilisateur (2 jours)
- Guide utilisateur EN (80% du marché)
- Quickstart admin
- API docs Swagger publiques

### Estimation globale (révisée post-audit 18/05)

| Phase | Durée nominale | Durée réaliste (×1.5 historique projet) |
|---|---|---|
| A — Refondation runtime | 3-4 sem (audit code 8-10j + buffer) | 4-6 sem |
| B — Validation cross-domain | 2 sem (corpus + gold-sets humains réalistes) | 2-3 sem |
| C — UX enrichie | 1-2 sem | 2-3 sem |
| D — Production hardening | 2-3 sem | 3-4 sem |
| **Total cumulé** | **8-11 sem** | **11-16 sem** (≈ 2.5-4 mois) |

> Le coefficient 1.5 vient de l'observation historique : tous les pivots architecturaux passés ont dépassé l'estimation initiale (HISTORIQUE_PIVOTS archivé). À reconfirmer ou affiner après Phase A.

> **Risque assumé** : Pendant ces 2.5-4 mois, **aucun signal marché externe** ne sera obtenu (utilisateur produit travaille en solo en chambre, sans accès prospect direct). La validation produit reposera sur le jugement personnel de l'utilisateur (presales SAP expert) sur la qualité des réponses produites + verdict empirique sur les benchs internes (SAP + 2 corpus de validation Phase B). C'est un trade-off acceptable mais explicite.

---

## 3. Kill switches (conditions de pivot)

Ces conditions sont **non-négociables**. Si une est atteinte, on **arrête** la trajectoire actuelle et on remet en cause l'hypothèse.

### 3.1 Conditions de kill switch

| ID | Condition | Hypothèse invalidée | Action déclenchée |
|---|---|---|---|
| **K-1** (Gate-F) | Test fumée cross-domain : <70% factual sur au moins un des 2 corpus non-SAP | AX-11/12/13 agnosticité empirique | Voir scénarios détaillés §3.2 |
| **K-2** | Après Phase A2 (relations claim-vs-claim), bench T2 contradictions <80% surface | Hypothèse : les claims structurés permettent la détection contradictions | **Investiguer** : problème d'extraction (étape 8 pipeline) ou de représentation (schéma claim) avant de poursuivre |
| **K-3** | Après Phase A3 (runtime intent-first), C1 <0.65 OU C3 <0.40 OU latence p50 >90s | Hypothèse : runtime KG-first apporte une amélioration substantielle | **Investiguer** : revoir l'IntentResolver, ou réintégrer plus de retrieval Qdrant, ou décider que V5.1 reste runtime principal et la cible 0.85 est inatteignable |
| **K-4** | Verifier HHEM-2.1 reste inopérant (corrélation outcome↔score <0.2) après refactoring | Hypothèse : verifier passif Mode A est utile en production | **Décision** : soit refactor profond, soit abandon verifier (acceptation que validation passe par autres mécanismes) |
| **K-5** | Coût LLM mensuel >€500 sur usage interne dev | Hypothèse : DeepInfra serverless est tenable économiquement | **Investiguer** : caching plus agressif, self-hosting vLLM EC2, ou bascule modèle plus petit |
| **K-6** *(nouveau, 19/05)* | Auto-évaluation utilisateur produit (Fred) sur 20 questions presales SAP type **après Phase A** : qualité subjective <"acceptable" sur la majorité | Hypothèse : un produit à 0.75 C1 a une valeur perçue par un utilisateur expert | **Pause** : pas de Phase B/C avant clarification de ce qui manque réellement à la perception de valeur (peut-être pas seulement le score factual, mais aussi la latence, la traçabilité, l'expression, etc.) |

Si un kill switch déclenche, **mise à jour de VISION.md** : soit assouplir l'axiome concerné (et justifier par ADR), soit re-prioriser les capacités.

### 3.2 Scénarios de pivot si K-1 déclenche

Détails opérationnels des actions de pivot, à pré-écrire avant Phase B pour éviter improvisation sous stress :

#### Scénario A — Un seul domaine non-SAP passe (l'autre <70%)
**Exemple** : juridique 75%, médical 55%.
**Interprétation** : l'agnosticité fonctionne pour certains domaines mais pas tous. Probablement question de **structure documentaire** (juridique très structuré vs médical narratif).
**Action** :
1. Re-prioriser Phase D (Domain Pack) avant Phase C — construire un Domain Pack médical minimal et re-bencher
2. Mettre à jour AX-13 : "agnosticité conditionnée à structure documentaire compatible" (ADR)
3. Repositionner commercialement : produit "juridique-first" avec roadmap d'extension

#### Scénario B — Aucun corpus non-SAP ne passe (<70% sur les deux)
**Exemple** : juridique 55%, médical 50%.
**Interprétation** : le core seul ne suffit pas, l'agnosticité est plus profonde que prévu. **Test de contrôle** : run SAP sans Domain Pack.
- Si SAP aussi chute → Interprétation A (cf §B intro) : agnosticité **architecturalement impossible** dans le design actuel. Pivot lourd nécessaire.
- Si SAP reste OK → Interprétation B : Domain Pack **indispensable** sur tous les domaines, pas un "enrichissement". Re-architecturer : Domain Pack devient un composant first-class.

**Action** :
1. Documenter la cause précise via analyse manuelle de 5 fails par corpus
2. Si Interprétation B : re-prioriser Phase D AVANT Phase C, construire Domain Pack minimal sur les 2 corpus, re-bencher
3. Si Interprétation A : pivot architectural lourd (1-2 mois additionnels, à décider avec l'utilisateur)

#### Scénario C — Pivot produit (si Scénarios A et B échouent ou ne sont pas viables)
**Si** ni l'agnosticité ni la spécialisation par Domain Pack ne donne ≥70% : il faut accepter que l'ambition multi-domaine n'est pas tenable dans le design actuel.
**Options** :
1. **Spécialiser SAP uniquement** : malgré EKX (0.86) qui est concurrent. Trouver un angle différenciant (UX click-to-source ? expression de contradictions ? lifecycle ?) que EKX ne fait pas.
2. **Repenser le produit en outil d'audit/comparaison documentaire** : sortir du Q/A interactif, devenir un outil d'analyse batch (génère des rapports : "voici les contradictions dans votre corpus", "voici l'évolution de la règle X entre versions"). Moins ambitieux mais peut-être plus défendable.
3. **Pause produit** : conserver le code comme R&D, sans push commercial. Reprendre quand le marché ou les modèles évoluent.

Cette décision n'est pas technique, elle est stratégique (utilisateur produit doit choisir).

### 3.3 Note sur le risque commercial assumé (post-18/05)

L'utilisateur produit (Fred, presales SAP, solo en chambre) n'a **pas accès direct à des prospects** pendant la refondation. Pas de test commercial avant Phase A+B. Conséquences :
- **Pas de signal de valeur perçue externe** pendant 2.5-4 mois
- La validation produit reposera sur **l'auto-évaluation experte** de l'utilisateur (Kill switch K-6) sur les 20 questions presales SAP type
- Le risque "construire un produit que personne ne veut" est **explicitement accepté**
- Mitigation : K-6 introduit une checkpoint d'auto-évaluation après Phase A pour détecter une éventuelle absence de valeur perçue avant de continuer en Phase B/C

C'est un trade-off conscient. Le re-questionnement viendra naturellement à la sortie de Phase A ou Phase B selon les résultats.

---

## 4. Backlog ADR à créer (priorité)

| Priorité | ADR | Pour quelle Phase | Statut |
|---|---|---|---|
| **P0** | `ADR_BITEMPOREL_CLAIMS.md` | Phase A1 | À créer |
| **P0** | `ADR_PROBABILITY_ISOLATION.md` | Phase A3 | À créer |
| **P0** | `ADR_DEPRECATIONS_V51.md` *(nouveau post-audit)* — Décommission de query_reformulator, loop_signature, execution_plan, domain_pack_loader, doc_topics_loader, anthropic_llm_caller. Justification par AX-11 (agnosticité) + Probability Isolation. | Phase A3 | À créer |
| **P1** | `ADR_VALIDATION_CROSS_DOMAIN.md` | Phase B | À créer |
| **P1** | `ADR_RELATIONS_CLAIM_CLAIM.md` (SAME_AS / EVOLUTION_OF / CONTRADICTS / REFINES / QUALIFIES) | Phase A2 | À créer |
| **P2** | `ADR_CLICK_TO_SOURCE_FRONTEND.md` | Phase C | À créer |
| **P3** | `ADR_DOMAIN_PACK_LIFECYCLE.md` | Phase D1 | Existe déjà en ongoing/ (mars 2026) — à dépoussiérer/réviser après suppression `domain_pack_loader.py` |

---

## 5. Backlog stratégique commercial (HORS scope refondation)

> Ces sujets sortent du périmètre technique de VISION.md. À traiter avec l'utilisateur produit dans un document `STRATEGIE_COMMERCIALE.md` séparé, **après que les Phases A+B soient OK**.

- Identification de **3 prospects concrets hors SAP** (juridique / médical / scientifique ou autre)
- Construction de **corpus de démo non-SAP** pour pitches commerciaux
- Plan de pricing & business model
- Cas client zéro : qui, quand, quoi montrer

---

## 6. Convergence vision → réalité : indicateurs

Chaque sprint, le tableau §1 (Matrice de maturité) doit progresser. Indicateur de convergence :

```
Convergence = (composants 🟢) / (composants total)

État 18/05/2026 = 6 🟢 / 16 = 37.5%
Cible fin Phase A (3-4 sem) = 9 🟢 / 16 = 56%
Cible fin Phase B (1-1.5 sem) = 10 🟢 / 16 = 62%
Cible fin Phase C (2-3 sem) = 13 🟢 / 16 = 81%
Cible fin Phase D (3-4 sem) = 16 🟢 / 16 = 100%
```

L'agent `vision-guardian` (P4) doit calculer cet indicateur chaque jour à partir du tableau §1 + état du code.

---

## 7. Gouvernance de ce document

- **Owner** : Fred (utilisateur produit)
- **Mise à jour** : à chaque fin de phase, le tableau §1 est mis à jour avec mesures actualisées
- **Relation à VISION.md** : si une décision de phase contredit un axiome VISION, **VISION.md doit être amendé en premier** (avec ADR justifiant la rupture) avant que l'EXECUTION_ROADMAP ne devienne contradictoire
- **Relation au harness de tâches** : chaque phase Ai/Bi/Ci/Di doit avoir une tâche dans le tracker
- **Revue** : revue obligatoire par `vision-guardian` (P4 quand il sera implémenté) en fin de chaque phase, pour vérifier que l'exécution est restée alignée VISION

---

*Document rédigé le 18 mai 2026 dans le cadre de la refondation post-audit doc + retour challengeant de Claude Web. Subordonné à VISION.md.*
