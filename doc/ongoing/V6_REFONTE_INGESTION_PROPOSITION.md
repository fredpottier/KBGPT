# OSMOSIS V6 — Refonte ingestion structurée universelle

> **Document de partage pour challenge externe (autre LLM, expert humain)**
> *Date : 2026-05-14 | Branche : `feat/runtime-v5` | État actuel V5.1 = 0.620 sur panel SAP 50q*

Ce document expose :
1. L'ambition produit et l'écart actuel avec les attentes
2. L'état mesuré de V5.1 et le journey des tentatives
3. Pourquoi le paradigme actuel atteint son plafond
4. Une proposition d'architecture V6 (refonte ingestion + retrieval)
5. Les hypothèses de gain et les risques
6. Les décisions ouvertes à valider

L'objectif est qu'un autre LLM ou un expert humain puisse **challenger l'analyse et la proposition** avec un contexte complet.

---

## 1. Ambition produit

### 1.1 Promesse OSMOSIS / KnowWhere

> *« Le Cortex Documentaire des Organisations »*

L'utilisateur (presales technique, juriste, médecin, ingénieur conformité…) pose une question sur un corpus documentaire et reçoit une réponse **précise**, **traçable** (citations), **fidèle** (pas d'hallucination), et **honnête sur ses limites** (abstention quand l'info n'est pas dans le corpus).

### 1.2 Contrainte fondamentale (validée par le user)

**Le pipeline doit être universellement applicable** — domaine-agnostic ET document-agnostic. Un même core doit traiter :
- Documentation technique (SAP S/4HANA Operations Guide, manuel d'OS)
- Réglementaire (RGPD, normes ISO, règlement aérospatial CS-25)
- Médical (protocoles cliniques, monographies ICD-10)
- Juridique (jurisprudence, contrats)
- Procédural (manuel qualité, runbooks SRE)

**La spécialisation domaine doit passer par des extensions externes** (Domain Pack par tenant), pas par du code hardcodé dans le core.

### 1.3 Cible mesurée

Le bench actuel évalue le score sur un panel de questions stratifiées avec un juge LLM (Llama-3.3-70B-Instruct) qui compare la réponse candidate au ground truth.

| Cible | Score |
|---|---:|
| Phase 1 ADR (acceptable) | 0.65-0.70 |
| Phase 2 ADR (cible long terme) | 0.80+ |
| EKX (référence concurrente SAP-native, non-universelle) | 0.858 |
| Plafond Oracle (Claude Sonnet 4.6 + lecture libre PDFs, CH-50) | 0.94 |

---

## 2. État mesuré V5.1 (au 14/05/2026)

### 2.1 Score actuel

**V5.1 production-ready = 0.620** sur panel SAP 50q stratifié (gold_set_sap_v2, judge Llama-3.3-70B).

```
Distribution : 50% perfect (1.0) / 24% partial (0.5) / 26% zero (0.0)
Pipeline    : 100% citation rate, 0% phantom tool_call
Latence avg : 29.5s / question (DeepSeek-V3.1 via Together AI)
Iter avg    : 7.0 (max=8)
```

### 2.2 Architecture livrée

V5.1 est un **Reading Agent** basé sur :
- LLM agent (DeepSeek-V3.1, charte open-source serverless via Together AI)
- 10 reading tools : `outline`, `read`, `find_in`, `resolve_ref`, `expand_context`, `compare_sections`, `list_versions`, `navigate_by_toc`, `read_with_footnotes`, `find_cross_references`
- Workspace cognitif Pydantic (S4.7) + budgets par shape + anti-thrash novelty detection
- API SSE/async + admission control + idempotency
- Verifier shell HHEM-2.1 (Mode A passive, inopérant en pratique — voir §3.5)
- Document Context enrichi par doc (A6) : `doc_title`, `doc_summary`, `key_topics`, `key_terms` extraits par LLM offline

Code organisé sous `src/knowbase/runtime_v5/` avec 35+ tests.

### 2.3 Comparaisons mesurées (apples-to-apples, même panel)

| Système | Score | Δ vs V5.1 | LLM | Note |
|---|---:|---:|---|---|
| V4.2 (RAG ancien, cassé) | 0.333 | -0.287 | DeepSeek-V3.1 | retrieval LLM-centric défaillant |
| POC initial reading_agent.py | 0.440 | -0.180 | DeepSeek-V3.1 | base avant industrialisation |
| **V5.1 (état actuel A7)** | **0.620** | — | **DeepSeek-V3.1** | **architecture production-ready** |
| V5.1 + Sonnet 4.6 (A_SONNET) | 0.710 | +0.090 | Claude Sonnet 4.6 | LLM premium, même architecture |
| EKX (SAP-natif KG, externe) | 0.858 | +0.238 | inconnu | KG SAP propriétaire |

---

## 3. Le journey — 10 itérations, ce qui a marché et ce qui n'a pas

### 3.1 Tweaks ayant produit un gain réel mesurable

| Itération | Idée | Gain | Statut |
|---|---|---:|---|
| **A2** | Injecter `available_docs` listing dans le user prompt (l'agent ne connaissait pas le corpus) | +0.017 | ✅ keep |
| **A3** | Aligner budgets shape (factual `max_iter` 3→8) sur POC | +0.010 | ✅ keep |
| **A6** | Enrichir DocumentContext Neo4j avec `doc_title`/`doc_summary`/`key_topics`/`key_terms` extraits par LLM offline, injectés dans le prompt | **+0.090** | ✅ keep — gros gain réel |
| **A7** | `find_in` TF-IDF cosine ranking (n-grams 1-2) au lieu de regex substring | **+0.080** | ✅ keep — confirme gain retrieval intra-doc |

**Gain cumulé runtime : +0.170pp** (0.450 → 0.620).

### 3.2 Tentatives abandonnées et leurs leçons

| Itération | Idée | Résultat | Pourquoi abandonné |
|---|---|---|---|
| **A5** | Brancher verifier HHEM-2.1 Mode A passif | +0.07 (variance) | Verifier inopérant : 49/50 questions ont `support_rate=0` (matching `[doc=X]` claim segmenter cassé) — gain attribué à la variance |
| **A8** | Hybrid retrieval RRF (TF-IDF + e5-large embeddings) dans `find_in` | -0.060pp | RRF mélange 2 rankers complémentaires mais dégrade sur multi-hop/causal (embeddings ramènent des sections sémantiquement proches mais pas exactement bonnes pour raisonnement multi-section) |
| **A10** | Brancher Domain Pack SAP existant (200+ acronymes, 70+ aliases) dans le user prompt | -0.020pp | DeepSeek-V3.1 **connaît déjà nativement** EHS, HANA, RISE, SAP — Domain Pack n'apporte pas de "nouveau savoir". Effet de dilution : 12 entries supplémentaires déplacent le focus |
| **A_SONNET** | Switch LLM agent vers Claude Sonnet 4.6 (calibration plafond) | +0.090 → 0.710 | Gap LLM premium = seulement +0.090pp. **Le LLM n'est pas le bottleneck principal.** Sonnet régresse paradoxalement sur false_premise (trop confiant, abstient mal) |
| **A9** | Bench 143q complet pour mesure agrégée | annulé | Budget Together AI insuffisant ; A7 0.620 sur 50q reste la mesure de référence |

### 3.3 Diagnostic des 17 zero-scores restants en A7

**Stop reasons des fails** :
- 10 budget_cap (agent atteint `max_iter=8` sans trouver l'info)
- 3 thrash (agent boucle sur sections similaires)
- 2 concluded avec FAUSSE info (agent croit avoir trouvé, mais hallucine ou interprète mal)
- 2 abstention quand info était trouvable

**Pattern des fails factual (7/15)** : l'agent ne trouve pas l'**identifiant exact rare** (transaction code `CGSADM`, role `SAP_HR_PYC_TM_MNG`, auth object `P_RCF_POOL`). La query française descriptive ("Quelle transaction initialise le cache Expert") n'a aucun token overlap avec le contenu doc qui contient juste le code. TF-IDF rate.

### 3.4 Constat clé apprenti

**Le LLM n'est pas le bottleneck.** Avec Sonnet 4.6 (modèle ~30× plus cher que DeepSeek), on monte de 0.620 à 0.710 seulement. EKX (0.858) reste +0.148 au-dessus de Sonnet **sur le même panel**. **Donc l'avantage d'EKX n'est pas le modèle, c'est l'architecture/data.**

### 3.5 Honnêteté sur ce qui est livré mais inopérant

- **Verifier HHEM-2.1** : modèle chargé, branchement OK, mais 49/50 questions ont `support_rate=0` à cause d'un bug de matching `[doc=X]` dans le claim segmenter. Le verifier ne discrimine pas → n'aide pas à détecter les hallucinations. Effort de fix ~1-2j, pas fait par manque de temps.

- **Plan-then-execute (S4.3)** : Pydantic `ExecutionPlan` codé, mais pas branché dans le flow agent → l'agent ne fait pas de plan explicite avant d'agir.

- **Cheap path (S4.5)** : prep seulement, pas implémenté.

- **Bake-off verifier complet (S7.7)** : MiniCheck/Lynx/Glider non testés.

---

## 4. Pourquoi il faut aborder autrement

### 4.1 Le paradigme actuel : "agent qui lit comme un humain qui découvre"

V5.1 est conceptuellement un humain à qui on donne un corpus et qui doit le **découvrir à chaque question**. Il a des outils de lecture (outline, find_in, read), un workspace pour prendre des notes, des budgets pour ne pas boucler. Mais il **reconstruit le sens à zéro à chaque query**.

### 4.2 Limite fondamentale de ce paradigme

**Ce que fait V5.1 quand on lui pose une question** :
1. Lit la liste des docs (`available_docs`)
2. Devine quel doc consulter (heuristique LLM + topics A6)
3. Fait `outline()` pour voir la structure
4. Fait `find_in()` pour chercher des mots
5. Fait `read()` sur les sections candidates
6. Synthétise une réponse
7. **Recommence intégralement à la question suivante** (pas de mémoire)

**Conséquences** :
- Coût : ~50k tokens input + 5k output par question
- Latence : ~30s par question
- **Aucune capitalisation** : l'agent re-découvre les mêmes patterns à chaque fois
- Bottleneck irréductible : trouver `CGSADM` sans connaître à l'avance la structure du doc nécessite beaucoup de lecture séquentielle

### 4.3 Comment procède un humain qui **maîtrise** le domaine (vs découvre)

Un consultant SAP qui répond à "Quelle transaction initialise le cache Expert ?" **ne lit pas** les guides. Il :
1. Sait que "Expert cache" est une fonctionnalité du module SAP EHS
2. Sait que les transactions admin EHS ont un préfixe (CG*, CB*)
3. Récupère de sa mémoire (ou d'une table de référence) la transaction `CGSADM`
4. Optionnellement vérifie dans le doc Operations Guide §10.7.4

Le consultant a un **modèle mental préalablement construit** (entités + relations + structure du domaine) qu'il interroge **à la demande**.

### 4.4 Ce qu'EKX fait probablement (système concurrent à 0.858)

EKX est un système RAG+KG SAP-natif. Inférence basée sur :
- Un Knowledge Graph SAP-natif construit à l'ingestion (transactions, modules, rôles, dépendances explicitement typés)
- Des requêtes structurées (probablement Cypher ou SPARQL) générées dynamiquement par le LLM à partir de la query
- Du retrieval textuel complémentaire pour les détails

**Quand EKX reçoit "Quelle transaction initialise le cache Expert ?"** :
1. Identifie l'intent : `LOOKUP_TRANSACTION` avec contexte `Expert cache initialization`
2. Query KG : `MATCH (t:Transaction)-[:INITIALIZES]->(f:Function {name:'Expert cache'}) RETURN t`
3. Si trouvé : retourne `CGSADM` + référence section
4. Synthétise réponse courte

**Pas de boucle d'exploration. Pas de thrash. Réponse en ~3-5s.**

### 4.5 Le shift paradigmatique nécessaire

Passer de :

```
[Léger ingestion]  →  [Lourd runtime "agent qui découvre"]
   (juste l'OCR             (agent loop, lectures séquentielles,
    et la TOC)                 retrieval ad-hoc)
```

À :

```
[Lourd ingestion structurée]  →  [Léger runtime "agent qui consulte"]
  (entities + relations +           (query KG + retrieval + synthèse rapide)
   facts + procedures +
   indexed by type)
```

**C'est exactement le pattern qu'utilise un humain expert vs un humain qui découvre.**

---

## 5. Proposition V6 — Pipeline atomique universel

### 5.1 Principes directeurs

1. **Schémas Pydantic universels** dans le core (pas de mention SAP, légal, médical)
2. **Extensibilité par Domain Pack** (chaque tenant peut sub-classer)
3. **Extraction "humanoid"** : le LLM extrait comme un humain comprendrait
4. **Pas de hardcoding** : aucune liste fermée d'entity types ou de predicates dans le core
5. **Validation par schema** : si le LLM produit quelque chose de mal formé → rejet et re-extract
6. **Backward compat V5.1** : V6 vit en parallèle, on peut basculer

### 5.2 Couche 1 — Modèle d'extraction universel

Les **5 archétypes universels** présents dans tout document structuré (académique, technique, légal, médical, procédural) :

#### 5.2.1 `NamedEntity` (entité nommée)
Tout objet ayant un identifiant propre.

```python
class NamedEntity(BaseModel):
    entity_id: str  # UUID interne
    canonical_name: str  # nom principal
    aliases: list[str] = []  # variantes orthographiques
    entity_kind: str  # "code", "person", "place", "concept", "tool", ...
    domain_type: Optional[str] = None  # extensible par Domain Pack
    description: Optional[str] = None
```

Exemples extraits **par le même schema** :
- SAP : `canonical_name="CGSADM"`, `entity_kind="code"`, `domain_type="SAP_TRANSACTION"`
- Légal : `canonical_name="Article 32"`, `entity_kind="reference"`, `domain_type="GDPR_ARTICLE"`
- Médical : `canonical_name="ICD-10 J45"`, `entity_kind="code"`, `domain_type="ICD_CODE"`

#### 5.2.2 `AtomicFact` (assertion factuelle)
Une affirmation testable, sujet-prédicat-objet.

```python
class AtomicFact(BaseModel):
    fact_id: str
    subject: str  # peut référencer un NamedEntity
    predicate: str  # verbe d'action ou de relation
    object: str
    evidence_section_id: str
    evidence_text: str  # verbatim minimal
    modality: Literal["asserted", "conditional", "negated", "example"] = "asserted"
    confidence: float = 1.0
```

Exemples :
- SAP : "CGSADM initializes Expert cache" → subject=`CGSADM`, predicate=`initializes`, object=`Expert cache`
- Légal : "Article 32 requires data encryption" → subject=`Article 32`, predicate=`requires`, object=`data encryption`
- Médical : "Salbutamol relieves bronchospasm" → subject=`Salbutamol`, predicate=`relieves`, object=`bronchospasm`

#### 5.2.3 `Procedure` (action séquencée)
Une séquence d'étapes à exécuter pour atteindre un objectif.

```python
class Procedure(BaseModel):
    procedure_id: str
    name: str  # nom court ("Initialize Expert cache")
    goal: str  # objectif ("Make Expert cache available")
    steps: list[ProcedureStep]
    prerequisites: list[str] = []  # autres procédures, conditions
    evidence_section_id: str
```

Exemples :
- SAP : steps=["Open transaction CGSADM", "Click Initialize button", "Wait for confirmation"]
- Médical : steps=["Administer salbutamol via nebulizer", "Monitor SpO2 every 5min"]
- Légal : steps=["Notify supervisory authority within 72h", "Document the breach"]

#### 5.2.4 `Constraint` (contrainte / règle)
Une obligation, condition, exception, exclusion.

```python
class Constraint(BaseModel):
    constraint_id: str
    constraint_type: Literal["requirement", "prohibition", "exception", "condition"]
    statement: str  # texte de la contrainte
    applies_to: list[str] = []  # entities ou procedures concernés
    evidence_section_id: str
```

Exemples :
- SAP : "Requires authorization object P_RCF_POOL"
- Légal : "Personal data must be encrypted in transit"
- Médical : "Contraindicated if patient < 12 years old"

#### 5.2.5 `Reference` (pointeur)
Lien vers une autre information (interne au doc ou externe).

```python
class Reference(BaseModel):
    reference_id: str
    reference_text: str  # texte tel qu'écrit ("see Article 17", "cf SAP Note 12345")
    target_kind: Literal["internal_section", "external_document", "standard", "regulation"]
    resolved_target: Optional[str] = None  # section_id ou doc_id si résolu
    evidence_section_id: str
```

Exemples :
- SAP : "see SAP Note 1061242" → target_kind=`external_document`
- Légal : "see Article 17" → target_kind=`internal_section`
- Médical : "ATS Guidelines 2024" → target_kind=`standard`

### 5.3 Couche 2 — Pipeline d'extraction

```
Document (PDF/PPTX/HTML)
        │
        ▼
[V5.1 existant — DSG section parsing]
        │
        ▼
[NOUVEAU V6 — Pour chaque section :]
   LLM (DeepSeek-V3.1) avec prompt universel + schema Pydantic
   → produit { entities, facts, procedures, constraints, references }
        │
        ▼
[Validation Pydantic stricte]
   → si mal formé : re-extract avec correction prompt
        │
        ▼
[Indexation Neo4j V5.2]
   → (V5Section)-[:CONTAINS_FACT]->(:AtomicFact)
   → (V5Section)-[:MENTIONS]->(:NamedEntity)
   → (V5Section)-[:DESCRIBES]->(:Procedure)
   → (V5Section)-[:STATES]->(:Constraint)
   → (V5Section)-[:HAS_REFERENCE]->(:Reference)
   → (NamedEntity)-[:HAS_FACT]->(:AtomicFact)
   → (Reference)-[:POINTS_TO]->(:V5Section) (si résolu)
```

**Prompt LLM universel (extrait, pas SAP-spécifique)** :
```
You are analyzing a document section to extract structured information that
would help someone search and reason about this content later.

Extract:
1. Named entities: any proper nouns, codes, identifiers, references to specific
   things (people, places, codes, named concepts, tools, standards, etc.)
2. Atomic facts: simple assertions of the form "subject + verb + object" that
   are verifiable in the text.
3. Procedures: any sequence of steps describing how to do something.
4. Constraints: requirements, prohibitions, conditions, exceptions stated in
   the text.
5. References: pointers to other parts of the document or external sources.

For each entity, classify its kind (code, person, place, concept, tool, ...).
Do NOT invent. Stay strictly grounded in the text.
```

**Test ex-post agnostique** : ce prompt est identique pour SAP, légal, médical, etc. Le LLM extrait selon le contenu, sans guidance domaine.

### 5.4 Couche 3 — Domain Pack (extension par tenant)

Le Domain Pack ajoute des **sous-types** à `NamedEntity.domain_type` :

```yaml
# enterprise_sap pack
domain_types:
  NamedEntity:
    - SAP_TRANSACTION: "Code de transaction SAP (4-5 char alphanumériques)"
    - SAP_ROLE: "Rôle SAP avec préfixe SAP_*"
    - SAP_AUTH_OBJECT: "Objet d'autorisation (P_*, S_*)"
    - SAP_MODULE: "Module fonctionnel (FI, MM, SD, ...)"
  Procedure:
    - SAP_CONFIGURATION: "Procédure de configuration"
  Constraint:
    - SAP_PREREQUISITE: "Prérequis technique SAP"
```

**Le core ne sait rien de ces sous-types**. Le runtime tool peut les utiliser comme filtre optionnel.

### 5.5 Couche 4 — Retrieval intelligent au runtime

Nouveaux tools (s'ajoutent aux 10 existants V5.1) :

```python
def lookup_entity(name: str, entity_kind: Optional[str] = None) -> dict:
    """Find a named entity by name (with aliases). Returns entity + facts + sections."""

def find_facts_about(subject: str, predicate: Optional[str] = None) -> list[AtomicFact]:
    """Find all facts where subject matches."""

def find_procedure(goal_keywords: str) -> list[Procedure]:
    """Find procedures by goal description."""

def find_constraints_on(entity_or_procedure: str) -> list[Constraint]:
    """Find constraints applying to an entity or procedure."""

def resolve_reference(ref_text: str, current_doc_id: str) -> dict:
    """Resolve a reference to its target section/document."""
```

**Routing intent** dans `_build_user_prompt` (ou via classifier S2 existant) :
- Question "Quelle transaction X ?" → bias vers `lookup_entity("X", entity_kind="code")`
- Question "Comment faire Y ?" → bias vers `find_procedure(goal=Y)`
- Question "Quelles règles pour Z ?" → bias vers `find_constraints_on(Z)`

**L'agent garde aussi les tools de lecture libre** (read, outline, find_in) pour les questions qui ne tombent pas dans un pattern structuré (multi-hop, comparison, causal).

---

## 6. Hypothèses de gain et pourquoi

### H1 — Facteurs rares : retrieval direct par entity index (+0.10-0.15pp sur factual)

**Problème actuel** : "Quelle transaction initialise le cache Expert ?" → V5.1 fait 8 itérations de `outline` + `read` sans trouver `CGSADM` car la query française n'a pas de mot-clé matching le doc.

**Solution V6** : à l'ingestion, `CGSADM` est extrait comme `NamedEntity(kind=code)` avec un `AtomicFact(subject=CGSADM, predicate=initializes, object=Expert_cache)`. Au runtime, `find_facts_about("Expert cache")` retourne directement le fact + section evidence en 1 call.

**Pourquoi ça marche** : l'agent n'a plus besoin de **reconnecter** la query française au code anglais. La connexion a déjà été faite à l'ingestion par un LLM qui avait le contexte de la section entière.

### H2 — Multi-hop : cross-document linking actif (+0.05-0.10pp sur multi_hop)

**Problème actuel** : multi-hop nécessite de relier des infos dispersées. V5.1 doit chercher dans plusieurs docs séquentiellement.

**Solution V6** : les `Reference` extraits à l'ingestion sont **résolus** : "SAP Note 1061242" mentionné dans doc A pointe vers la section X de doc B. Au runtime, `resolve_reference` retourne le lien direct. L'agent suit le chemin.

**Pourquoi ça marche** : la résolution se fait UNE FOIS à l'ingestion (coûteux mais one-shot). Au runtime, juste un lookup.

### H3 — Comparison : retrieval typé par section (+0.05-0.10pp sur comparison)

**Problème actuel** : "Les deux guides 2021 et 2023 couvrent-ils X de la même façon ?" → l'agent doit lire les deux et comparer. Souvent il rate des nuances.

**Solution V6** : `find_facts_about(subject="X")` retourne TOUS les facts mentionnant X dans le corpus, groupés par doc. L'agent voit côte-à-côte les versions, peut compare structurellement.

**Pourquoi ça marche** : pas de risque de manquer une mention si elle est dans une section non lue.

### H4 — False premise : KG nullability (+0.05pp sur false_premise)

**Problème actuel** : "Quelle procédure pour migrer Business One → S/4HANA Cloud PCE ?" → V5.1 cherche, ne trouve pas, abstient parfois bien parfois mal.

**Solution V6** : `find_procedure(goal="migrate Business One to S/4HANA Cloud PCE")` retourne `null` rapidement et de manière **structurelle**. L'agent peut abstenir avec certitude : "Cette procédure n'est pas documentée dans le corpus".

**Pourquoi ça marche** : la requête KG nullable est une preuve d'absence, pas juste "je n'ai pas trouvé en N itérations".

### H5 — Coût/latence (réduction ~50% des tokens runtime)

**Problème actuel** : V5.1 consomme ~50k tokens input/q en lectures redondantes. Coût agrégé = ~$0.02/q DeepSeek, ~$0.30/q Sonnet.

**Solution V6** : la majorité des questions factuelles sont résolues en 1-2 tool calls (lookup + 1 read pour evidence). ~10-20k tokens.

**Pourquoi ça marche** : pas d'exploration aveugle, l'agent va direct.

### Total gain estimé

Avec uniquement DeepSeek-V3.1 (charte open-source) :
- V5.1 actuel : **0.620**
- V6 estimé : **0.72-0.78** (+0.10-0.16pp)
- Coût/q : ~$0.01 (vs $0.02 V5.1)
- Latence : ~10-15s (vs 30s V5.1)

Pas garanti d'atteindre EKX (0.858) qui bénéficie probablement de :
- Extraction SAP-spécialisée (pas universelle)
- KG SAP propriétaire (relations métier nuancées)
- Possibles annotations humaines

Mais **rester universel** est notre différenciation.

---

## 7. Risques et garde-fous

| # | Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Extraction LLM rate sur certaines structures (tableaux complexes, formules) | Élevée | Moyen | Validation Pydantic permissive + fallback `read()` |
| R2 | Coût LLM ingestion dépasse estimation | Moyenne | Faible | POC 3 docs avant batch, budget cap explicite |
| R3 | Schémas trop rigides → mauvaise extraction sur certains domaines | Moyenne | Élevé | Champs `description`/`statement` libres + LLM mode "best effort" |
| R4 | KG explose (latency queries) | Faible | Élevé | Indexation typed + limit per query + caching |
| R5 | Domain Pack viole charte | Moyenne | Critique | Code review charte explicite avant merge, separation core/pack |
| R6 | Refonte casse V5.1 actif | Faible | Critique | V6 en parallèle, endpoint `/api/runtime_v6/answer` distinct |
| R7 | Le LLM extrait incorrectement (hallucine entities) | Moyenne | Moyen | Verbatim evidence obligatoire par fact, validation regex pour les codes |
| R8 | Time-to-market dépasse 2-3 semaines | Moyenne | Moyen | Phasing strict, gates objectives à chaque phase |
| R9 | Régression sur shapes où V5.1 marche bien (multi_hop 0.75) | Faible | Moyen | Bench A/B systématique avant cutover |
| R10 | Charte agnostique violée par accident (terme SAP dans le core) | Moyenne | Critique | Test linter qui grep "SAP\|article\|patient" dans `src/knowbase/runtime_v6/` (excluding domain_packs) |

---

## 8. Comparatif systèmes

| Système | Score panel SAP | Latence/q | Coût/q | Universalité | Différenciation |
|---|---:|---:|---:|---|---|
| V4.2 RAG | 0.333 | 15s | low | ✅ universel | abandonné |
| POC reading_agent | 0.440 | 35s | medium | ✅ universel | baseline |
| **V5.1 actuel** | **0.620** | **30s** | **$0.02** | **✅ universel** | **production-ready** |
| V5.1 + Sonnet | 0.710 | 36s | $0.14 | ✅ universel | trop cher prod |
| EKX | 0.858 | ? | ? | ❌ **SAP-locked** | concurrent |
| **V6 proposé** | **0.72-0.78** | **~12s** | **$0.01** | **✅ universel** | **différenciation forte** |

**Argument commercial V6** : performance EKX-like SANS lock domaine. Pour un client multi-corpus (juridique + technique + médical par exemple), V6 est utilisable sur tous les corpus avec le même produit.

---

## 9. Décisions ouvertes à valider

### D1 — Stratégie d'incrémentalité

- **A** : V6 sur 3 docs POC → validation manuelle → batch 38 (recommandé)
- **B** : V6 sur 38 docs direct
- **C** : V6 en parallèle V5.1 (deux ingestions), comparaison A/B au runtime

### D2 — Budget LLM ingestion offline

- **DeepSeek-V3.1** (Together AI) : ~$3 pour 38 docs (charte open-source)
- **Claude Sonnet 4.6** : ~$30-50 pour 38 docs (extraction qualité +)
- **Hybride** : Sonnet sur 3 docs POC pour valider qualité, DeepSeek pour batch 38

### D3 — Granularité Pydantic

- **A** : 5 archétypes universels stricts (recommandé pour rester agnostique)
- **B** : 10+ types incluant `Definition`, `Example`, `Caveat`, `Metric`, ... (plus riche mais risque d'over-engineering)

### D4 — Approche `domain_type`

- **A** : champ string libre `domain_type: str` (le LLM peut mettre n'importe quoi)
- **B** : enum dynamique chargé du Domain Pack tenant
- **C** : pas de domain_type dans le core, le tenant applique post-process

### D5 — Migration V5.1 → V6

- Garder V5.1 actif en parallèle (rollback safety)
- V6 = endpoint `/api/runtime_v6/answer` distinct
- Bench A/B sur même panel
- Cutover si V6 ≥ V5.1 + 0.05pp sur ≥4 shapes

### D6 — Cible Phase 1 V6

- **Gate** : V6 ≥ 0.70 sur panel SAP 50q stratifié (+ 0.08pp vs V5.1)
- **Gate ambitieux** : V6 ≥ 0.75 (- 0.10pp vs EKX)
- **Gate audacieux** : V6 ≥ 0.80 (cible long terme)

---

## 10. Phasing proposé (3 semaines)

| Phase | Durée | Livrables | Gate de sortie |
|---|---:|---|---|
| **P1 — ADR + schémas** | 2j | ADR_V6_INGESTION_STRUCTUREE.md, modèles Pydantic, prompt LLM testé | Validation user + autre LLM sur ce doc |
| **P2 — POC extraction (3 docs)** | 3j | Pipeline extract sur Operations 014, Security 027, Upgrade 003 + audit qualité manuel | ≥80% des facts validés humainement |
| **P3 — Persistence Neo4j V5.2** | 2j | Schéma KG enrichi, scripts migration, indexes | Tous nodes/relations queryables avec perf <500ms |
| **P4 — Tools runtime + agent** | 3j | 5 nouveaux tools, intégration ReasoningAgentV6, prompt update | Smoke 8q toutes shapes OK |
| **P5 — Batch ingestion 38 docs** | 1j | Ingestion complete corpus SAP | Tous docs ingérés sans erreur |
| **P6 — Bench + tuning** | 3j | Bench 50q stratifié + diagnostic + tuning prompt | Score V6 ≥ 0.70 |
| **P7 — Validation multi-corpus** | 2j | Test sur 1 doc légal + 1 médical (ex: RGPD + ICD-10 protocol) | Extraction fonctionnelle même schéma |

**Total : ~16 jours de dev** + budget LLM ~$5-50 selon décisions.

---

## 11. Questions pour challenge

Pour qu'un autre LLM (ou expert humain) puisse challenger cette proposition, voici les questions clés :

1. **Le diagnostic est-il juste ?** Le bottleneck est-il vraiment l'absence de modèle mental préalable, ou y a-t-il un autre angle (ex: prompt engineering du Reading Agent V5.1 actuel pourrait combler le gap) ?

2. **Les 5 archétypes universels (NamedEntity, AtomicFact, Procedure, Constraint, Reference) sont-ils suffisants** pour couvrir technique + légal + médical + procédural ? Manque-t-il `Definition`, `Example`, `Hypothesis`, `Metric`, … ?

3. **L'extraction LLM peut-elle vraiment être universelle** sans dégrader sur certains domaines ? Faudrait-il un prompt par grande famille (procédural vs déclaratif vs analytique) ?

4. **Le coût d'ingestion est-il prohibitif à grande échelle** (10 000 docs au lieu de 38) ? Quelles optimisations (extraction incrémentale, parallélisation, modèle distillé) ?

5. **Le KG va-t-il "exploser"** ? 38 docs × ~180 sections × 10 facts/section = 68k facts. À 10k docs, on a 18M facts. Latence Cypher reste-t-elle <500ms ?

6. **L'approche V6 est-elle vraiment universelle** ou cache-t-elle des biais ? Test ex-post : prendre 1 doc d'un domaine inconnu (ex: doc législatif coréen sur la pêche) et vérifier que l'extraction donne du sens.

7. **L'estimation +0.10-0.16pp est-elle réaliste ou optimiste** ? Quelles autres voies ?

8. **Le verifier (Mode B actif) doit-il être branché AVANT ou APRÈS V6** ? V6 produit du contenu plus structuré → potentiellement plus facile à vérifier.

9. **Plan-then-execute (S4.3 inactif) doit-il être réactivé dans V6** ? Avec des tools structurés, le plan a plus de sens.

10. **Quelle est la stratégie de fallback** si V6 ne dépasse pas V5.1 ? Garder V5.1 en prod, V6 en R&D ?

---

## 12. Conclusion

L'analyse montre que **V5.1 a atteint le plafond de son paradigme** ("agent qui lit comme un humain qui découvre") à 0.620. Pour viser EKX-like (0.85+) sans sacrifier l'universalité du produit, il faut passer à un paradigme **"agent qui consulte comme un humain expert"** — ce qui requiert un travail lourd à l'**ingestion** (extraction structurée universelle) plutôt qu'au runtime.

La proposition V6 garde toute l'architecture V5.1 actuelle (Reading Agent + tools + workspace + verifier) et ajoute :
- Une couche d'extraction structurée à l'ingestion (5 archétypes universels)
- 5 nouveaux tools de lookup au runtime
- Un KG enrichi (V5.2)

Le tout reste **strictement domain-agnostic et document-agnostic** : prompt LLM neutre, schémas universels, Domain Pack pour la spécialisation par tenant.

Estimation : 3 semaines de dev, +0.10-0.16pp de gain attendu, latence/coût divisés par ~2-3.

**Cette proposition mérite d'être challengée avant d'être lancée.**

---

*Fin du document. Pour challenge externe, focus sur §4 (diagnostic), §5 (proposition architecture), §6 (hypothèses), §11 (questions).*
