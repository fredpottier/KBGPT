# OSMOSIS — Vision

> **Version :** 1.0 (18 mai 2026)
> **Statut :** Référence active. Toute décision produit/technique doit être confrontée à ce document.
> **Sources absorbées** : NORTH_STAR.md, VISION_PRODUIT.md, HISTORIQUE_PIVOTS.md (mars 2026) — archivés dans `archive/2026-05_pre-vision-cleanup/` après cette refondation.

---

## 0. Comment lire ce document

Ce document est l'**unique source de vérité produit + architecturale** pour OSMOSIS. Il remplace les 3 docs fondateurs précédents qui s'étaient désynchronisés de la vision réelle (modèle bitemporel, hiérarchie 2-niveaux, Probability Isolation, multi-domaines — tous absents des docs antérieurs).

Si une décision (chantier, refactoring, choix techno) ne se rattache pas à un principe de ce document, **elle doit être justifiée explicitement ou rejetée**. C'est aussi le document que l'agent `vision-guardian` utilise quotidiennement pour détecter les dérives.

---

## 1. Pourquoi on existe

### 1.1 Le vrai problème

De nombreuses entreprises constatent que leur documentation contient des inconsistances, des versions superposées et des contradictions difficiles à tracer manuellement.

- Une spec produit dit X, une doc marketing dit Y, une doc support dit Z — **contradictions permanentes**.
- Une norme réglementaire 2022 et sa version 2024 coexistent dans le corpus — **impossible de savoir ce qui est encore valide**.
- Une fusion d'entreprises hérite des docs des 3 entités — **chaos documentaire**.

Le problème **n'est pas la simple récupération d'information** (les RAG sont matures sur ce point pour les questions factuelles directes). Le problème est de savoir **si l'information est fiable, courante, contredite, évoluée**.

### 1.2 Mission

OSMOSIS est un système qui ingère une documentation hétérogène et inconsistante, et qui fournit aux utilisateurs des réponses **fiables, traçables et conscientes du temps** — en détectant automatiquement les évolutions, incohérences et contradictions entre documents, sans jamais affirmer ce qui n'est pas dans les sources.

Formulation opérationnelle :

> **Dans le périmètre du corpus documentaire, OSMOSIS est la source de vérité. En dehors de ce périmètre, il n'a pas d'opinion.**

### 1.3 Cible utilisateur (multi-domaines, par construction)

OSMOSIS est **agnostique au domaine métier**. Les 4 cas types à garder en tête à chaque décision :

- **Juridique** : suivre l'évolution d'un contrat ou règlement sur plusieurs versions
- **Médical** : synthétiser des études sur un protocole de traitement, identifier les contradictions
- **Presales / Produit** : retrouver une info produit dans des docs hétérogènes (specs, support, marketing)
- **Scientifique** : comparer les résultats publiés sur un sujet, identifier les évolutions

Si une fonctionnalité ne fonctionne que sur **un seul** de ces domaines, elle est un **anti-pattern** (voir §8).

### 1.4 Positionnement (interne vs externe)

| Audience | Terme à utiliser | Pourquoi |
|---|---|---|
| **Interne** (design, architecture, code) | "KG documentaire arbitral", "vérité documentaire" | Précision technique : nous arbitrons CE QUI EST AFFIRMÉ dans les docs, pas la vérité universelle |
| **Externe** (clients, démos, marketing) | **"Documentation Verification Platform"** | "Verification" décrit ce que le produit fait (vérifier cohérence + traçabilité). "Truth" décrirait ce qu'il ne fait PAS (donner LA vérité absolue) — voir §1.5 |

Tagline externe : *"De la recherche documentaire à l'intelligence documentaire."*

Positionnement en une phrase : *"OSMOSIS répond à vos questions, mais surtout il vous dit quand vos documents ne sont pas d'accord entre eux."*

### 1.5 Ce qu'OSMOSIS n'est PAS

| Catégorie | Pourquoi non |
|---|---|
| Un RAG amélioré | La valeur n'est pas dans la réponse textuelle, mais dans la qualification (sources, confiance, contradictions, évolutions) |
| Un "chat with docs" | Marché saturé (Glean, Copilot, Notion AI) — pas de différenciation possible sur ce terrain |
| Un "Truth Engine" | Promesse non tenable au regard de l'architecture (AX-5 : contradictions exposées, JAMAIS résolues — donc OSMOSIS ne donne pas "la" vérité, il qualifie ce que les docs affirment). Risque politique en entreprise : "qui a raison, le VP Produit ou le VP Marketing ?" — OSMOSIS expose, ne tranche pas. |
| Un KG ontologique encyclopédique | Pas de prétention universelle — le périmètre est strictement celui du corpus ingéré |
| Un système qui "comprend" les documents | Il vérifie des assertions explicites, il ne fait pas d'inférence sémantique au-delà |
| Un oracle | Muet hors corpus (AX-2) |

---

## 2. Axiomes inviolables

Ces principes ne sont pas négociables. Toute proposition qui en viole un doit être rejetée ou écrire d'abord une refondation explicite de l'axiome.

### 2.1 Vérité documentaire

| ID | Axiome | Implication |
|---|---|---|
| **AX-1** | **Pas d'assertion sans preuve localisable** | Toute affirmation doit être ancrée à un span de texte (`charspan_start`, `charspan_end`) d'un document source. |
| **AX-2** | **Périmètre corpus strict** | Jamais d'inférence "bon sens", jamais de résolution automatique de conflits hors documents. |
| **AX-3** | **LLM = extracteur evidence-locked à l'ingestion, ET confiné aux 3 points contrôlés au runtime (Parse + Evaluate + Format)** | À l'**ingestion** : le LLM extrait ce qui est écrit, pas ce qu'il "comprend". Au **runtime** : le LLM intervient à 3 points clairement bornés — (1) Parse de la question en sub-goals, (2) Evaluate lightweight des résultats déterministes, (3) Format de la réponse finale. Tout entre ces 3 points est déterministe (Cypher, Qdrant, mapping tools). Jamais d'arbitrage LLM entre claims contradictoires (AX-5). |
| **AX-4** | **Un gap sans justification = défaillance système** | Tout résultat non-conclusif DOIT être adossé à au moins un extrait observable (preuve d'absence). |
| **AX-5** | **Contradictions exposées, jamais résolues arbitrairement** | Le système ne tranche pas entre documents — il informe et qualifie la nature de la tension. |
| **AX-6** | **Le statut (SUPPORTED/PARTIAL/NOT_SUPPORTED) est dérivé, jamais décidé par LLM** | Règle déterministe : `all(SUPPORTED) → SUPPORTED`, `any(SUPPORTED) → PARTIAL`, sinon `NOT_SUPPORTED`. |

### 2.2 Séparations architecturales

| ID | Axiome | Détails |
|---|---|---|
| **AX-7** | **Neo4j = vérité, Qdrant = projection** | Toutes les claims et relations dans Neo4j. Qdrant ne contient que des projections de lecture reconstructibles. |
| **AX-8** | **Scope ≠ Assertion** | La couche "ce que le document couvre" (~90% du contenu) est strictement séparée de "ce que le document affirme" (~5-15%). Pas de promotion automatique de l'une à l'autre. |
| **AX-9** | **Unité de preuve ≠ Unité de lecture** | DocItem/Claim atomique verbatim pour le KG. TypeAwareChunk ~1500 chars avec préfixe contextuel déterministe pour Qdrant. Aucune génération LLM dans la projection retrieval. |
| **AX-10** | **ANCHORED_IN pointe uniquement vers DocItem** | Jamais vers un chunk retrieval. Sépare strictement la surface de preuve de la projection. |

### 2.3 Agnosticité totale

| ID | Axiome | Implication |
|---|---|---|
| **AX-11** | **Agnostique au domaine métier** | Aucun regex, whitelist, liste hardcodée spécifique à un domaine dans le code core. Tout enrichissement métier passe par un **Domain Pack pluggable** (configuration JSON, non-code). |
| **AX-12** | **Agnostique à la langue** | Détection morpho-syntaxique (POS tags Universal Dependencies), jamais lexicale. *Théoriquement compatible avec toutes les langues supportées par spaCy ; validé en production sur FR/EN, à valider sur les autres (cf §9.3).* |
| **AX-13** | **Agnostique au corpus (normatif)** | Le pipeline core **DOIT** être testé sur ≥2 domaines distincts. Toute régression cross-domain = blocking. *Aspiration normative — réalité au 18/05/2026 : validé uniquement sur SAP, validation cross-domain reste à faire (cf §6.3).* |

### 2.4 Abstention qualifiée

| ID | Axiome | Implication |
|---|---|---|
| **AX-14** | **OSMOSIS ne promet pas la connaissance. Il promet la défendabilité.** | Un système qui répond toujours est un système qui ment parfois. Mieux vaut "le corpus n'affirme pas X" qu'une réponse inventée. |
| **AX-15** | **Le système ne dit pas "je ne sais pas"** | Il dit "aucun document du corpus ne contient d'assertion explicite sur X". Distinction critique : il ne déclare pas son ignorance, il déclare l'absence d'assertion documentaire. |

---

## 3. Modèle épistémique (l'élément le plus stratégique)

C'est la section qui contient les **nouveautés validées le 18 mai 2026** et qui marquent une rupture vs les docs antérieurs. Aligné avec l'état de l'art 2026 (Zep/Graphiti, VersionRAG, Deterministic Legal Agents).

### 3.1 Hiérarchie 2-niveaux : Document + Claim

OSMOSIS organise sa connaissance en **deux couches strictement hiérarchiques** :

```
Niveau 1 — DOCUMENT (épisode)
   ├── identifiant, version, source_authority
   ├── ingested_at, valid_from
   ├── relations doc-level : SUPERSEDES, REPLACES_PARTIALLY
   │
   └── contient Niveau 2 ↓

Niveau 2 — CLAIM (fait atomique attribué)
   ├── subject_canonical, predicate, value
   ├── 4 timestamps (cf §3.2)
   ├── confidence, source_authority (hérité du doc)
   ├── relations claim-level : SAME_AS, EVOLUTION_OF, CONTRADICTS
   └── EVIDENCED_BY → Section (avec charspan, page PDF)
```

**Pourquoi deux niveaux et pas un seul ?**

Un doc `v1.3` qui remplace `v1.2` est une information **utile au niveau document** (le lecteur sait "prends d'abord la dernière version"). Mais cela **ne suffit pas** : si v1.2 contient 60 claims et v1.3 en contient 50, les 10 claims de v1.2 sans équivalent dans v1.3 méritent un traitement explicite (héritage implicite ? omission volontaire ? ambiguïté à signaler).

Le doc-level capture **la gouvernance documentaire**. Le claim-level capture **la sémantique fine**. Les deux coexistent et se renforcent.

Cette architecture est cohérente avec l'état de l'art 2026 : **Zep / Graphiti** (paper arxiv 2501.13956, intégration native Neo4j) implémente exactement ce pattern Episode + Semantic Entity. **VersionRAG** (arxiv 2510.08109) confirme l'approche hiérarchique. Ces deux références indépendantes valident le choix.

### 3.2 Bitemporel sur les claims (4 timestamps)

Chaque claim porte explicitement **4 timestamps** suivant le modèle bitemporel standard :

| Champ | Sémantique | Exemple |
|---|---|---|
| `valid_from` | Date à partir de laquelle le fait est vrai dans le monde | "2023-01-01" (date d'effet de la règle) |
| `valid_until` | Date après laquelle le fait n'est plus vrai (ou `null` si encore actif) | "2024-12-31" |
| `ingested_at` | Date à laquelle le système a appris ce fait | "2026-05-18T09:00Z" |
| `invalidated_at` | Date à laquelle le système a invalidé ce fait (suite à contradiction/évolution) | "2026-05-20T14:30Z" |

**Règle d'or** : un claim contredit ou superseded **n'est jamais supprimé**. On positionne `invalidated_at`. Cela permet de répondre aux deux questions :

- "Qu'est-ce qui est vrai aujourd'hui ?" → `WHERE invalidated_at IS NULL AND (valid_until IS NULL OR valid_until > now())`
- "Qu'était vrai au 15 janvier 2024 ?" → `WHERE valid_from <= '2024-01-15' AND (valid_until IS NULL OR valid_until > '2024-01-15') AND ingested_at <= '2024-01-15'`

### 3.3 Supersession à 2 niveaux

**Au niveau document** :

```cypher
(:Document {version:"1.3"}) -[:SUPERSEDES {explicit: true, declared_at: "2026-05-18"}]-> (:Document {version:"1.2"})
```

Déclenche par défaut : "pour les questions ouvertes, ignorer v1.2 et utiliser v1.3 sauf demande explicite d'historique".

**Au niveau claim** :

```cypher
(:Claim {value:"Y", source:"v1.3"}) -[:EVOLUTION_OF {marker_type:"explicit"|"inferred"|"prudence"}]-> (:Claim {value:"X", source:"v1.2", invalidated_at:T})

(:Claim {value:"Y"}) -[:CONTRADICTS {resolution:"unresolved"|"by_authority"|"by_recency"}]-> (:Claim {value:"X"})

(:Claim) -[:SAME_AS {confirming_source:doc_id}]-> (:Claim)
```

### 3.4 Détection automatique évolution vs contradiction

**Trois niveaux de confiance** dans la classification (correspondance claim-vs-claim sur même `subject_canonical` + `predicate`) :

| Cas | Mécanisme | Classification |
|---|---|---|
| Marqueur textuel explicite ("a été remplacé par", "depuis v1.3", "supersedes") | Détection LLM à l'extraction | **EVOLUTION_OF** (`marker_type: "explicit"`) — haute confiance |
| Valeurs différentes, doc plus récent, autorité supérieure, pas de marqueur | Inférence à l'ingestion | **EVOLUTION_OF** (`marker_type: "inferred"`) — confiance moyenne |
| Valeurs différentes, autorité égale ou ambiguë | Défaut prudent | **CONTRADICTS** (`resolution: "unresolved"`) — à signaler à l'utilisateur |

**Règle d'or AX-16** : *si on ne sait pas distinguer évolution vs contradiction → c'est une contradiction par prudence*. L'utilisateur doit voir le doute. Cette règle est cohérente avec l'esprit du paper *Deterministic Legal Agents* : préférer abstenir + signaler le doute plutôt qu'inférer un statut incertain (le paper ne formule pas cette règle exactement, mais le principe Probability Isolation va dans le même sens — confiner les inférences incertaines).

État de l'art : VersionRAG atteint **90% de précision sur changements explicites** et **60% sur changements implicites** sur 100 questions / 34 documents versionnés. C'est notre référence chiffrée pour cette détection.

### 3.5 Probability Isolation + récupération d'erreur (Parse → Evaluate → Re-plan)

> **"L'incertitude LLM est confinée à TROIS points contrôlés : Parse (décomposition en sub-goals), Evaluate (jugement qualité), Format (rédaction humaine). Tout le reste — sélection tools, traversée graphe, agrégation claims — est déterministe. Et l'incertitude initiale de Parse n'est jamais irréversible : un évaluateur léger permet de re-planifier si le résultat ne répond pas aux sub-goals."**

#### 3.5.1 Pourquoi 3 points et pas 1 ?

L'état de l'art 2026 (Corrective RAG / CRAG, Iterative Routing, QAgent — cf §10.4) montre qu'une architecture **single-shot classifier** (1 LLM décide irréversiblement du routing) est **fragile par construction** : si la classification initiale se trompe, tout l'aval tombe. C'est précisément le diagnostic V5.1 (plafond 0.61, anti-pattern §8.1).

La solution prescrite est l'**architecture en 5 modules avec feedback loop** :

```
Question utilisateur
        │
        ▼ [LLM 1 — Parse] (incertitude #1, bornée à la décomposition)
sub_goals[], entities, time_filter, hints
        │
        ▼ [DÉTERMINISTE — Plan]
Pour chaque sub_goal → tool sélectionné (Cypher | Qdrant | Contradiction | Lifecycle)
        │
        ▼ [DÉTERMINISTE — Execute]
Résultats structurés (claims + relations + timestamps)
        │
        ▼ [LLM 2 — Evaluate, ~200-500 tokens, lightweight] (incertitude #2)
Verdict ∈ {CORRECT, AMBIGUOUS, INCORRECT}
        │
        ├─ CORRECT    → suite (Synthesize)
        ├─ AMBIGUOUS  → BOUCLE retour à Plan (re-decompose, +tools, max 2 iter)
        └─ INCORRECT  → fallback TEXT_ONLY (Qdrant brut) OU abstention motivée
        │
        ▼ [LLM 3 — Synthesize/Format, optionnel] (incertitude #3)
Réponse rédigée pour l'utilisateur (zéro nouveau fait)
```

#### 3.5.2 Trois principes architecturaux non-négociables

1. **Decomposition > Classification** : Parse produit des **sub-goals** (objectifs concrets : "trouver claim X sur sujet Y à date Z") au lieu de classer la question dans un bucket figé. Les tools émergent du besoin, pas d'une typologie a priori.

2. **Lightweight Evaluator obligatoire** : un LLM léger (~200-500 tokens) juge la qualité avant synthèse. C'est le **chaînon manquant** de V5.1. Sans lui, pas de récupération d'erreur de routing.

3. **Hard cap anti-thrash** : maximum 2 boucles `Plan → Execute → Evaluate`. Au-delà : fallback ou abstention forcée. Évite la boucle infinie de re-planning.

#### 3.5.3 Comptage LLM calls par requête

| Cas | Calls LLM |
|---|---|
| Heureux (CORRECT au 1er essai, sans Synthesize séparé) | **2** (Parse + Evaluate) |
| Heureux + Synthesize | **3** (Parse + Evaluate + Format) |
| AMBIGUOUS 1 fois → re-plan → OK | **4** (Parse + Eval + Eval + Format) |
| AMBIGUOUS 2 fois max → fallback | **5** + fallback Qdrant déterministe |

vs V5.1 actuel : **12-15 LLM calls/q**. Réduction massive avec **gain de robustesse**, pas perte.

#### 3.5.4 Conséquence sur les axiomes

Cette section enrichit (sans contredire) :
- **AX-3** (LLM evidence-locked) : reste valide. Le LLM n'invente pas, il décompose ou évalue.
- **AX-6** (statut dérivé déterministe) : reste valide. Le verdict de l'évaluateur n'est pas "le statut" — c'est seulement la décision de re-planifier ou non.
- **AX-14** (abstention qualifiée) : renforcée. Le verdict INCORRECT → fallback ou abstention motivée. On ne force jamais une réponse douteuse.

C'est la rupture majeure avec V5.1 (Reading Agent agentique, 6-8 itérations multiform×5, verifier LLM passif inopérant) — cf §6.4 + §8.1 anti-pattern "single-shot classification routing".

---

## 4. Architecture cible

### 4.1 Schéma Neo4j (canonique)

```cypher
// ─── Niveau 1 : Document ───────────────────────────────────────
(:Document {
   doc_id, title, version, mime_type,
   source_authority,           // hiérarchie de fiabilité de la source
   ingested_at, valid_from,
   tenant_id, page_count
})
   -[:SUPERSEDES {explicit: bool, declared_at}]-> (:Document)
   -[:CONTAINS]-> (:Section)

// ─── Niveau 2 : Section (unité de localisation pour click-to-source) ──
(:Section {
   section_id,        // sha256 stable (cf S2.1 du runtime V5)
   title, page,
   charspan_start, charspan_end,
   tenant_id
})

// ─── Niveau 3 : Claim (unité atomique de vérité) ───────────────
(:Claim {
   claim_id, subject_canonical, predicate, value,
   value_kind,                 // "percent" | "version" | "number" | "string"
   value_normalized,           // pour comparabilité
   value_comparable,           // "strict" | "loose" | "non_comparable"
   valid_from, valid_until,    // event time
   ingested_at, invalidated_at, // transaction time
   confidence, source_authority,
   tenant_id
})
   -[:EVIDENCED_BY {charspan_start, charspan_end}]-> (:Section)
   -[:IN_DOCUMENT]-> (:Document)
   -[:SAME_AS {confirming_source:doc_id}]-> (:Claim)
   -[:EVOLUTION_OF {marker_type, evidence_text}]-> (:Claim)
   -[:CONTRADICTS {resolution, severity}]-> (:Claim)
   -[:REFINES]-> (:Claim)      // précision/restriction (non conflictuel)
   -[:QUALIFIES]-> (:Claim)    // ajout de condition (non conflictuel)
```

### 4.2 Schéma Qdrant (projection)

Collection unique `knowbase_chunks_v2`, payload minimal :

```json
{
   "chunk_id": "...",
   "doc_id": "...",
   "section_id": "...",         // pour rejoindre Neo4j et obtenir traçabilité fine
   "tenant_id": "...",
   "type": "text" | "table" | "code",
   "contextual_prefix": "...",  // déterministe, jamais LLM-généré
   "embedding": [...]
}
```

Aucune information sémantique enrichie n'est stockée dans Qdrant — c'est une projection retrieval reconstructible depuis Neo4j.

### 4.3 Pipeline d'ingestion (9 phases ClaimFirst)

Le pipeline actuel `ARCH_CLAIMFIRST.md` reste valide, à enrichir des éléments §3 :

1. **Document Profile** — détection langue, type, version (extraction du `version`, `valid_from`, `source_authority`)
2. **Decoupage** — Docling → DocItem natifs avec charspans
3. **Claim Extraction** — verbatim, evidence-locked
4. **Entity Identification**
5. **Linking ABOUT / SUPPORTED_BY**
6. **Domain Pack enrichment** (pluggable, hors core)
7. **Cluster (déduplication sémantique)**
8. **Cross-claim detection** — comparaison `subject_canonical + predicate` → classifier **SAME_AS / EVOLUTION_OF / CONTRADICTS / REFINES / QUALIFIES** selon §3.4
9. **Persistance Neo4j + Qdrant**

**Ajout vs pipeline mars 2026** : étape 8 doit produire les **relations claim-vs-claim bitemporelles** (avec marker_type + invalidated_at), pas seulement détecter des tensions à la requête.

### 4.4 Pipeline runtime (5 modules + feedback loop, conforme §3.5)

```
1. PARSE [LLM #1] — Question → décomposition structurée
   Output: {sub_goals: [{predicate, subject_hint, time_filter, expected_value_kind}, ...],
            entities[], language, raw_question}
   Pas de classification figée, pas de "type" — sub-goals concrets directement actionnables.

2. PLAN [DÉTERMINISTE] — Pour chaque sub_goal :
   - Mapping sub_goal → tool ∈ {kg_claims, qdrant_sections, contradiction_surface, lifecycle_query, ...}
   - Construction Cypher query OU Qdrant params selon tool
   - Ordonnancement (séquentiel si dépendances, parallèle sinon)

3. EXECUTE [DÉTERMINISTE] — Lance les tools, agrège les résultats par sub_goal :
   - kg_claims : Cypher Neo4j → claims actives (filter invalidated_at IS NULL + valid_from/until)
   - qdrant_sections : recherche vectorielle (mode fallback ou enrichissement)
   - contradiction_surface : claims liés par CONTRADICTS → expose les deux versions
   - lifecycle_query : suit EVOLUTION_OF / SAME_AS / SUPERSEDES

4. EVALUATE [LLM #2, lightweight ~200-500 tokens]
   Input: {sub_goals, résultats agrégés par sub_goal, confidence scores}
   Output: verdict ∈ {CORRECT, AMBIGUOUS, INCORRECT, INSUFFICIENT_EVIDENCE}
   - CORRECT : tous sub_goals couverts par evidence → goto 5
   - AMBIGUOUS : couverture partielle ou ambiguïté détectée → BOUCLE goto 2
     (re-plan : élargir scope, ajouter tools, décomposer plus finement)
     Hard cap : max 2 retours (anti-thrash)
   - INCORRECT : evidence contradictoire avec sub_goal OU rien de pertinent → fallback Qdrant TEXT_ONLY
   - INSUFFICIENT_EVIDENCE : tools ont retourné peu/rien → abstention motivée (AX-14)

5. SYNTHESIZE [LLM #3, optionnel selon mode] — Rédaction réponse humaine
   - Input: evidence agrégée + verdict + sub_goals couverts/non couverts
   - Contraintes: zéro création de fait, citation cliquable obligatoire (§5.3),
     mention explicite des sub_goals non couverts (transparence)
   - Output: réponse structurée pour UI (texte + claims_verbatim[] + citations[])
```

#### Comptage LLM calls par requête

| Scénario | Calls LLM | Latence cible |
|---|---|---|
| Heureux (CORRECT 1er essai, format inline) | 2 (Parse + Eval) | < 15s |
| Heureux + Synthesize séparé | 3 | < 25s |
| AMBIGUOUS → re-plan → OK | 4 (Parse + 2×Eval + Format) | < 45s |
| AMBIGUOUS 2× → fallback | 5 + Qdrant TEXT_ONLY | < 60s |
| INCORRECT / INSUFFICIENT | 3 (Parse + Eval + Format abstention) | < 20s |

vs V5.1 : 12-15 LLM calls, 135-173s. **Gain de robustesse ET latence simultanés.**

Cibles latence VISION §5.2 : **p50 <30s, p95 <60s** → atteignables si Parse et Evaluate sont efficacement implémentés.

### 4.5 Trois modes de dégradation gracieuse

| Mode | Déclencheur | Fiabilité attendue |
|---|---|---|
| **REASONED** | Paths sémantiques entre entités trouvés via Cypher | Maximale — preuves tracées via le graphe |
| **ANCHORED** | Pas de paths mais routing structural (HAS_TOPIC, COVERS) | Bonne — contexte délimité |
| **TEXT_ONLY** | Ni paths ni routing → Qdrant standard | Dégradée — fallback RAG |

C'est un héritage stable du design `graph_first_search.py` (à réactiver). En mode TEXT_ONLY, OSMOSIS doit signaler `mode=fallback` à l'utilisateur — il sait alors que la traçabilité graphe n'est pas garantie.

---

## 5. Capacités produit & cibles de fiabilité

### 5.1 Les 5 capacités fondamentales

Chaque feature implémentée doit servir au moins une de ces capacités. Sinon → anti-feature.

| # | Capacité | Cible fiabilité | Différenciation |
|---|---|---|---|
| **C1** | **Réponse directe** (Q/A factuel) | **≥80%** | Non — baseline (égaler RAG) |
| **C2** | **Synthèse multi-document** | **≥80%** | Forte (vs RAG top-k naïf) |
| **C3** | **Raisonnement différentiel** (évolution/lifecycle) | **≥80%** | **Forte** — à notre connaissance non offert dans les RAG d'entreprise commerciaux usuels (Copilot, Glean) au regard de leur documentation publique mai 2026, à confirmer par bench |
| **C4** | **Détection de tensions** (contradictions) | **100% surface** (déjà atteint vs 0% RAG) | **Absolue** — game-changer |
| **C5** | **Validation /verify** (AI Act) | **≥95% abstention** sur input non couvert | **Absolue** — différenciation réglementaire |

### 5.2 Cibles transversales (non-négociables)

| Métrique | Cible | Pourquoi |
|---|---|---|
| **Fiabilité Q/A factuel basique (C1)** | ≥ 80% | "Si je ne sais pas faire ça, je suis un mauvais produit" |
| **Fiabilité évolution/contradiction (C3+C4)** | ≥ 80% | C'est le différenciant vs Copilot |
| **Abstention sur unanswerable** | ≥ 95% | Hallucination = perte totale de confiance utilisateur |
| **Latence utilisateur** | < 30s p50, < 60s p95 | Au-delà, aucun usage interactif |
| **Traçabilité visible UI** | 100% des réponses | Pas de confiance sans preuve cliquable |

### 5.3 Traçabilité click-to-source PDF (requirement MVP)

**Critère final attendu** : chaque affirmation dans la réponse utilisateur doit être :

1. **Cliquable** → ouvre directement le PDF source à la bonne page, surligne le span exact
2. **Accompagnée du claim verbatim** → l'utilisateur peut valider sans cliquer
3. **Avec métadonnées affichées** : `confidence`, `source_authority`, `valid_from` / `valid_until` (bitemporel)

**État actuel** (vérifié dans `frontend/src/lib/openSourceFile.ts` + `SourcePill.tsx` + `SourcesFootnotes.tsx`, CH-05.3 / CH-05.5) :

| Élément | État |
|---|---|
| Pill inline cliquable (format Wikipedia footnotes `[N]`) | ✅ implémenté |
| Fragment `#page=N` (RFC 3778) → PDF s'ouvre à la bonne page | ✅ implémenté |
| Gestion blob authentifié pour doc_id internes + URL absolues | ✅ implémenté |
| Tooltip survol : nom doc humanisé + numéro de page | ✅ implémenté |
| Liste détaillée des sources en bas de réponse | ✅ implémenté |
| Highlight du span exact dans la page | ❌ pas encore (le browser PDF viewer ne supporte pas `#highlight=`) |
| Claim verbatim affiché AVANT clic | 🟡 à vérifier dans `SourcesFootnotes` |
| Métadonnées confidence / source_authority | 🟡 partiellement affichées |
| Dates de validité bitemporelles (`valid_from`, `valid_until`) | ❌ pas encore (dépend du modèle bitemporel §3.2 à implémenter) |

**Ce qui reste à faire pour le MVP UX** :
- (a) Vérifier et compléter l'affichage du claim verbatim dans `SourcesFootnotes`
- (b) Afficher confidence + source_authority systématiquement
- (c) Une fois le modèle bitemporel §3.2 implémenté, afficher `valid_from`/`valid_until` sur chaque citation
- (d) (Optionnel, plus tard) viewer PDF custom (PDF.js) pour highlight du span précis

La fondation existe (pill cliquable → bonne page). L'enrichissement est incremental.

### 5.4 Les 3 usages d'exploitation

| Usage | Intention | Quand |
|---|---|---|
| **A — Composition** | Produire un document autonome à partir du corpus | Reporting, livrables |
| **B — Writing Companion** | Assister la rédaction en challengeant le texte | Sécurisation communications |
| **C — Navigator** | Construire un texte par navigation conceptuelle | Exploration d'un sujet |

Ces 3 usages ne doivent **pas être fusionnés**. Ils ont des prompts, des UI et des contrats différents.

---

## 6. Où on en est aujourd'hui (état brut au 18/05/2026)

### 6.1 Ce qui fonctionne

| Capacité | Métrique | Valeur | Date / source |
|---|---|---|---|
| Détection contradictions (C4) | both_sides_surfaced | **100%** vs RAG **0%** ✅ | mars 2026 — bench Sprint 0 25q KG contradictions |
| Synthèse multi-doc (C2) | T4 completude | OSMOSIS +19pp vs RAG ✅ | mars 2026 — bench T4 |
| Traçabilité backend | Citations présentes | 94-100% ✅ | mars 2026 ET re-confirmé partiellement 18/05 (100% cité sur bench V6-J2 50q) |
| ClaimClusters | Volume cross-doc | 820 sur corpus SAP | mars 2026 — corpus SAP de 22 documents (snapshot, peut avoir évolué depuis V6 extraction) |
| Pipeline ingestion | Formats supportés | PDF, PPTX, DOCX, XLSX, MD, HTML ✅ | factuel, vérifiable dans code (ingestion pipelines) |
| Multi-tenant isolation | Tests cross-tenant leak | Passent ✅ | tests property-based CH-52.2.4, dernière exécution à dater |
| Agnosticité (zéro regex métier) | Audit charte | 80% conforme | mars 2026 — audit `AUDIT_HARDCODED_WORD_LISTS.md` |

> ⚠️ **Note dating** : la majorité de ces métriques datent de mars 2026 et n'ont pas été re-mesurées depuis. Un re-bench complet est prévu après refondation (cf §7.1 Phase 1) pour confirmer ou actualiser ces valeurs.

### 6.2 Ce qui ne fonctionne pas (gaps mesurés)

| Problème | Mesure | Cause identifiée |
|---|---|---|
| **C1 Q/A factuel** | 0.61 (target 0.85) | LLM textuel sans recours KG sémantique en runtime |
| **Latence** | 135-173s/q (target 30s) | Pipeline V5.1 fait 12-15 LLM calls par question |
| **C3 lifecycle** | 0.25 (target 0.80) | Aucune représentation temporelle structurée en runtime |
| **C1 comparison** | 0.375 (target 0.80) | Pas de structure cross-version exploitable |
| **Outils KG V6** | find_procedures, find_references = 0 invocations sur 70 questions | Workflow Reading Agent profond préfère find_in TF-IDF |
| **Frontend traçabilité enrichie** | Pill cliquable + ouverture page exacte ✅, mais claim verbatim/confidence/dates pas systématiques | Fondation OK (CH-05.3/5), reste enrichissement métadonnées |

### 6.3 Tableau de bord vision vs réalité

| Axe | Cible vision | Réalité 18/05 | Gap |
|---|---|---|---|
| C1 Q/A factuel | ≥80% | 61% | **-19pp** 🔴 |
| C2 Multi-doc | ≥80% | Non mesuré récemment ; T4 mars 2026 montrait +19pp vs RAG (proxy positif) | À re-bencher 🟡 |
| C3 Lifecycle | ≥80% | 25% | **-55pp** 🔴 CRITIQUE |
| C4 Contradictions | 100% surface | 100% (RAG = 0%) | 0pp ✅ |
| C5 Validation | ≥95% abstention | Non benché récemment | 🟡 inconnu |
| Latence p50 | <30s | 135s | **+105s** 🔴 |
| Click-to-PDF (page exacte) | 100% | ✅ implémenté (CH-05.3/5) | 0pp ✅ |
| Affichage claim verbatim + métadonnées | systématique | partiel | 🟡 enrichissement |
| Bitemporel claim | Modèle complet | Non implémenté | 🔴 manquant |
| Probability Isolation | LLM seulement intent+format | 6-8 LLM calls/question | 🔴 anti-pattern |
| Agnosticité multi-domaine | Validée ≥2 domaines | Validée 1 domaine (SAP) | 🟠 cross-domain à valider |

### 6.4 Le diagnostic structurel

**Le plafond à 0.61-0.71 (avec Sonnet) n'est PAS un problème de LLM ni de tweaks.** Les benchs récents le démontrent :

- Sonnet 4.6 (frontier, proprietary, hors charte) plafonne à 0.71 *(mesuré 14/05/2026 sur 50q stratifiées gold_set_sap_v2)*
- DS-V3.1 (open-source utilisé en runtime) plafonne à 0.61 *(mesuré 18/05/2026 sur 50q stratifiées gold_set_sap_v2, V5.1 + V6-J2)*
- Gap LLM seul = +0.10pp seulement

**Le plafond vient de l'architecture** : V5.1 est un Reading Agent qui interroge **du texte** via TF-IDF section-level. Il ne dispose d'aucune représentation sémantique structurée (claims typés, relations bitemporelles, supersession). C'est comme demander à un humain très brillant de répondre à des questions SAP en lisant les PDF page par page, sans aucun index ni connaissance préalable du domaine.

**Pour franchir 0.85 (cible), il faut le KG sémantique RUNTIME**, pas une couche additionnelle dormante (cf V6-J1, V6-J2 = 0 invocations).

C'est la rupture stratégique de cette refondation : **abandonner l'illusion qu'un Reading Agent textuel peut atteindre 0.85** et investir dans le KG sémantique runtime conforme §3+§4.

---

## 7. Stratégie pour franchir le plafond

### 7.1 Voie choisie : KG-first runtime (refondation profonde)

Ordre de grandeur **4-6 semaines** (estimation sous réserve de disponibilité et de découvertes en cours de route — l'historique du projet montre que les phases dérapent souvent de 50% sur les premiers chantiers d'un nouveau paradigme) :

**Phase 1 — Modèle bitemporel + supersession (2 sem)**
- Enrichir le schéma Neo4j actuel : ajouter `valid_from`, `valid_until`, `invalidated_at` sur Claim
- Ajouter relations `SUPERSEDES` doc-level + `EVOLUTION_OF/CONTRADICTS/SAME_AS` claim-level
- Étape 8 du pipeline ingestion : classifier les relations claim-vs-claim
- Bench T2/T5 spécifique évolution/contradiction → cible C3+C4

**Phase 2 — Runtime intent-first (1-2 sem)**

*Chemin de migration explicite V5.1 → KG-first* :

1. Le module V5.1 `reasoning_agent_v51` reste vivant mais devient le **mode TEXT_ONLY** (fallback) — pas de suppression de code.
2. Nouveau module `runtime_v6` (ou similaire) implémente le pipeline `IntentResolver → Cypher templates → Format réponse`.
3. Le router runtime décide à chaque question : si claims structurés trouvés en Neo4j → mode REASONED (V6). Sinon → ANCHORED (Cypher partiel + Qdrant) ou TEXT_ONLY (fallback V5.1).
4. Pendant 2-4 semaines, double-écriture : les 2 runtimes répondent en parallèle (mode shadow) pour comparer scores et latence sur même panel.
5. Une fois V6 prouvé sur ≥80% des questions du gold-set, on déprécie V5.1 en runtime principal (kill switch).

Cibles : 2 LLM calls max par question (intent + format), latence p50 <30s.

**Phase 3 — Frontend click-to-source (1-2 sem)**
- Composant React : citation cliquable → viewer PDF.js avec highlight span
- Affichage claim verbatim + confidence + source_authority + dates de validité
- Bench UX : 5 utilisateurs externes, mesure temps de validation par claim

**Phase 4 — Validation cross-domain (1 sem)**
- Construire mini-corpus juridique (~10 docs) + mini-corpus médical (~10 docs)
- Bench les 5 capacités sur les 3 domaines (SAP + juridique + médical)
- Toute régression cross-domain = blocking

### 7.2 Gates explicites (anti-dérive)

Pendant la refondation, ces conditions doivent rester vérifiées sinon **stop et remise en cause** :

- **Gate-A** : Aucun regex/liste/exemple corpus-spécifique commit dans le core (audit grep automatique pré-commit)
- **Gate-B** : Tout claim persisté doit avoir les 4 timestamps + `subject_canonical + predicate + value`
- **Gate-C** : Si après 2 sprints de bench le score C3 (lifecycle) n'est pas > 0.50, on remet la voie KG-first en question
- **Gate-D** : Le runtime ne doit jamais faire >3 LLM calls par question (intent + retrieve-orchestrator + format max)
- **Gate-E** : Toute nouvelle feature doit être démontrée sur ≥2 domaines (SAP + 1 autre) avant merge
- **Gate-F (kill switch agnosticité)** : un **test de fumée cross-domain** (10-20 questions représentatives sur 2 corpus non-SAP — juridique + médical ou similaires) doit atteindre **≥70% factual** sur chaque corpus. Si ce seuil n'est pas atteint après Phase 1 OK, l'hypothèse d'agnosticité (AX-11/12/13) est **empiriquement invalidée** et un pivot architectural est obligatoire (re-spécialisation par domaine ou abandon de l'ambition multi-domaine).

### 7.3 Ce qu'on **arrête immédiatement**

- ❌ **V5.1 Reading Agent en runtime principal** (devient fallback TEXT_ONLY uniquement)
- ❌ **V6-J1 Procedure / V6-J2 Reference / V6-J3 ConceptCard comme outils dormants** (à réintégrer comme nodes typés du KG runtime au lieu d'outils LLM optionnels)
- ❌ **Tweaks score sur gold_set_sap_v2** (overfit au bench, ne franchit pas le plafond)
- ❌ **Multiform×5, max_iter=8, verifier passive** (latence killers, qualité marginale)

### 7.4 Ce qu'on conserve absolument

- ✅ Pipeline ClaimFirst d'ingestion (9 phases) — reste valide, à enrichir
- ✅ ClaimClusters cross-doc (820 sur corpus SAP) — base pour les relations claim-vs-claim
- ✅ Charte agnosticité (zéro regex métier) — c'est le DNA différenciant
- ✅ Detection contradictions (capacité C4 déjà à 100%)
- ✅ Multi-tenant isolation + observabilité OTel
- ✅ Frontend admin/benchmarks (à compléter avec C3+C5)

---

## 8. Anti-vision (ce qu'on REFUSE)

### 8.1 Pistes techniques écartées (avec preuves empiriques)

> Toutes les données ci-dessous sont issues des archives mars 2026 (ADR pivots, `HISTORIQUE_PIVOTS.md` archivé). Elles ne sont pas re-mesurées récemment mais leur conclusion architecturale reste valide tant qu'aucune nouvelle preuve empirique n'inverse la décision.

| Piste | Pourquoi écartée | Données | Source/date |
|---|---|---|---|
| Concept-focused chunks | Explosion combinatoire ratio 140:1 | 11713 chunks/doc, 35min/doc | ADR hybrid anchor model — 12/2024 |
| Vision (OCR) dans le KG path | Anchor rate 12-17% sur 4 tentatives | TEXT-ONLY = 56.6% anchor rate | ADR vision-out-of-kg — 01/2026 |
| Bloc KG injecté dans prompt synthèse | -8pp factual, +6.9pp false_idk | Bench Sprint 0 | 03/2026 |
| Extraction bottom-up exhaustive V1 | 90k nodes, fonctionnellement inutile | 19 docs | ADR stratified reading — 10/2025 |
| Retrieval-first RAG (Qdrant avant KG) | Biais "semantic anchoring" mots vs sens | "transformation" → mauvais concept | ADR graph-first — 01/2026 |
| Texte LLM-généré indexé dans Qdrant | Hallucination indexée = vérité fausse | Violation AX-1 | ADR hybrid anchor — 12/2024 |
| Règles hardcodées par domaine métier | Non-maintenable, anti-agnosticité | Whitelist `GENERIC_VERBS = {"be"…}` was EN-only | KG_AGNOSTIC_ARCHITECTURE — 02/2026 |
| KG sémantique riche + raisonnement traversée | Pass3 = 97% abstention sur procéduraux | Bench corpus SAP | ADR decision defense — 03/2026 |
| **Single-shot classification routing rigide** (1 classifier décide irréversiblement `answer_shape` → template tool) | **Si classification fausse, toute la réponse tombe**. Pas de mécanisme de récupération | V5.1 avec DeBERTa S2 cascade : plafond C1=0.61 (mai 2026) malgré tweaks A1-A10. Diagnostic confirmé par état de l'art 2026 (CRAG, Iterative Routing, QAgent) | Analyse 19/05/2026 + état de l'art externe — remplacé par §3.5 Parse → Plan → Execute → Evaluate avec feedback loop |

### 8.2 Anti-patterns produit (verboten en présence du PO)

- ❌ "Chat with your docs" (positionnement — bataille perdue vs Copilot)
- ❌ "Truth Engine" / "Truth Layer" (politiquement explosif)
- ❌ "Enterprise RAG" (mort en arrivant)
- ❌ "AI Governance Layer" en messaging avant clients payants
- ❌ Focus SAP en commercial (SAP a son propre outil interne EKX, mesuré à 0.86 sur **30 questions hard** où V3+V4.2 OSMOSIS échouent en mai 2026 — score non strictement comparable à nos benchs 50q stratifiées, mais indique qu'un plafond bien supérieur est techniquement accessible sur le domaine SAP, donc concurrence frontale risquée)

### 8.3 Anti-patterns commerciaux

- ❌ Démos avec données SAP uniquement (aucun prospect non-SAP ne se projettera)
- ❌ Mention "AI Governance" sans client payant
- ❌ Promesse "100% sans erreur" — incompatible avec AX-14 (abstention qualifiée)

### 8.4 Anti-patterns d'organisation (apprentissage 18/05)

- ❌ **Boucle de tweaks sans step-back vision** : si après 3 sprints le score plafonne, on **arrête** et on remet en cause l'archi (pas un 4ème tweak)
- ❌ **Construire des outils KG dormants** : un outil non sollicité par le runtime n'a aucune valeur — soit on l'active par router, soit on ne le construit pas
- ❌ **Mesurer pour mesurer** : un score ne vaut que s'il est lié à un mouvement vers la vision. Sinon c'est de la dopamine de progression sans avancement.

---

## 9. Frontière système

### 9.1 Périmètre corpus strict

OSMOSIS répond uniquement sur ce qui est **affirmé dans le corpus ingéré**. Il n'a pas d'opinion sur :

- Vérité universelle ("la Terre est ronde")
- Vérité scientifique non documentée dans le corpus
- "Bon sens métier" non écrit
- Connaissance générale du LLM (qui est explicitement bridée par le prompt)

### 9.2 Ce qu'OSMOSIS arbitre

| Type | Exemple |
|---|---|
| Ce qui est affirmé | "TLS 1.2 est obligatoire" (doc A, section 3, p. 12) |
| Ce qui est contredit | "Doc A dit X, doc B dit Y — voici les preuves, je ne tranche pas" |
| Ce qui a évolué | "Doc v1.2 disait X, doc v1.3 dit Y, marqueur explicite à p. 5" |
| Ce qui est absent | "Aucun document n'affirme Z dans le corpus actuel" |

### 9.3 Limites techniques acceptées (à dater)

- **Schémas visuels / diagrammes** : non extraits dans le KG (cf pivot Vision UX-only). Limitation acceptée pour MVP.
- **OCR de PDF scannés** : pipeline support OCR mais qualité dépend de la source. À surveiller.
- **Langues exotiques** (hors EN/FR/DE/ES/IT/PT/NL/RU/ZH/JA) : support universal POS mais qualité non garantie hors langues principales spaCy.
- **Documents avec ambiguïtés de version implicites** : si v1.3 ne déclare pas explicitement remplacer v1.2, OSMOSIS classifie par défaut en CONTRADICTS (par prudence — AX-16). À expliquer à l'utilisateur dans la doc.

---

## 10. Références

### 10.1 Docs sœurs (architecture détaillée)

- `doc/ARCH_CLAIMFIRST.md` — Pipeline ClaimFirst 9 phases, détails extraction
- `doc/ARCH_PIPELINE.md` — Pipeline stratifié Pass 0→3, Docling, vision gating
- `doc/ARCH_RETRIEVAL.md` — Graph-Guided RAG, Signal-Driven, 3 modes dégradation
- `doc/ARCH_STOCKAGE.md` — Neo4j + Qdrant + PostgreSQL + Redis schémas
- `doc/OPS.md` — Docker, déploiement, monitoring
- `doc/DEV_GUIDE.md` — Structure code, conventions, endpoints

### 10.2 Docs absorbées par VISION.md (à archiver après publication)

- `doc/NORTH_STAR.md` — 19 invariants → réduits à 16 axiomes ici
- `doc/VISION_PRODUIT.md` — 5 capacités, 3 usages, positionnement
- `doc/HISTORIQUE_PIVOTS.md` — 7 pivots, anti-patterns

Ces docs sont à déplacer dans `doc/archive/2026-05_pre-vision-cleanup/` après validation de ce VISION.md.

### 10.3 ADR à créer (gaps critiques identifiés par l'audit)

Dans `doc/ongoing/adr/` :

- `ADR_BITEMPOREL_CLAIMS.md` — Modèle 4 timestamps + Cypher + migrations
- `ADR_CLICK_TO_SOURCE_FRONTEND.md` — Composant React + viewer PDF.js + protocole API
- `ADR_PROBABILITY_ISOLATION.md` — IntentResolver + Cypher templates + abandon V5.1 Reading Agent
- `ADR_VALIDATION_CROSS_DOMAIN.md` — Test matrix multi-domaines + corpus samples

### 10.4 État de l'art externe (références scientifiques)

- **VersionRAG** : Version-Aware RAG for Evolving Documents — [arxiv 2510.08109](https://arxiv.org/abs/2510.08109). 90% précision sur changements explicites, 60% sur implicites. Validation industrielle de l'approche hiérarchique.
- **Zep / Graphiti** : Temporal Knowledge Graph Architecture — [arxiv 2501.13956](https://arxiv.org/html/2501.13956v1). Modèle bitemporel sur edges, hierarchy Episode + Semantic Entity. Référence industrie 2026.
- **Deterministic Legal Agents** : SAT-Graph API + Probability Isolation — [arxiv 2510.06002](https://arxiv.org/abs/2510.06002). Confine LLM uncertainty à l'intent translation. Modèle domain-portable.

---

## 11. Gouvernance du document

### 11.1 Cycle de vie

- **Version courante** : 1.0 (18 mai 2026)
- **Prochaine révision attendue** : après Phase 1 (bitemporel) — fin juin 2026
- **Owner** : Fred (utilisateur produit)
- **Reviewers obligatoires** : agent `vision-guardian` (quotidien) + revue humaine à chaque rev majeure

### 11.2 Règles de modification

- Toute modification d'un axiome (§2) nécessite un **ADR explicite** justifiant la rupture
- Toute modification de cible de fiabilité (§5) nécessite une justification chiffrée (bench + analyse)
- L'ajout de nouvelles capacités passe par une révision de §5 — pas de feature qui sort de C1-C5

### 11.3 Anti-érosion

Ce document est le seul rempart contre la dérive constatée 08-18 mai 2026 (10 jours de tweaks bench sans franchir le plafond). Si **un nouveau chantier est proposé** sans pouvoir être rattaché à un principe de ce document, **il doit être tracé dans le log des déviations** pour arbitrage explicite (intégrer / différer / abandonner / faire évoluer la VISION). **Pas de rejet automatique** : une bonne idée non rattachée à la roadmap actuelle peut mériter d'enrichir le plan.

**Principe directeur** : *"L'agent trace, l'utilisateur décide."* Une déviation tracée et oubliée vaut mieux qu'une bonne idée perdue. Une déviation tracée et débattue vaut mieux qu'une mauvaise idée poursuivie en silence.

#### Mécanisme opérationnel : agent `vision-guardian` ✅ implémenté (19/05/2026)

- **Définition** : `.claude/commands/vision-guardian.md` (slash command `/vision-guardian`)
- **Backlog des déviations** : `doc/ongoing/etudes/deviations_log.md`
- **Sources de référence** : VISION.md + EXECUTION_ROADMAP.md
- **Invocation** :
  - **Manuelle** : taper `/vision-guardian` dans une session Claude Code (recommandé chaque matin avant de coder)
  - **Cron automatique** : configurer via tool `CronCreate` de Claude Code (à activer par l'utilisateur produit ; pas encore en place)
- **Comportement** : compare l'activité observée (git log 7j, tasks, benchs récents) aux principes/phases du plan. Trace chaque déviation détectée dans le log avec format structuré (type, description, bénéfice potentiel, coût opportunité, recommandation). Ne bloque rien, signale tout.
- **Workflow utilisateur** : lecture du log en début de session → arbitrage statut (`reviewed` / `integrated` / `deferred` / `dropped`) pour chaque entrée `new` → si `integrated`, créer la tâche correspondante ou ouvrir un ADR pour amender VISION/ROADMAP

> En complément de l'agent, le rôle de garde-fou repose sur :
> - **Revue humaine systématique** de chaque nouveau chantier vs principes VISION.md avant démarrage
> - **Lecture de ce document** par le tech lead à chaque début de session
> - **Tableau de bord §6.3** confronté aux cibles §5 lors de chaque démarrage de sprint

---

*Document rédigé le 18 mai 2026 dans le cadre de la refondation post-audit doc. Absorbe NORTH_STAR.md (mars 2026) + VISION_PRODUIT.md (mars 2026) + HISTORIQUE_PIVOTS.md (mars 2026) + conclusions session 18 mai 2026 (modèle bitemporel + hiérarchie 2-niveaux + Probability Isolation + multi-domaines + traçabilité click-PDF).*
