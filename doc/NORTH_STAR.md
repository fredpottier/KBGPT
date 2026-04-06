# NORTH STAR OSMOSIS -- Principes Fondateurs & Invariants

> **Niveau de fiabilite** : Principes fondateurs (stables). Les invariants sont verifies contre le code avec un badge par ligne (✅ code-verified / ⚠️ partiellement / ⏳ design-only).

*Document consolide -- Rationalisation documentation Mars 2026*
*Sources archivees : `doc/archive/pre-rationalization-2026-03/`*

**Documents source :**
- `foundations/GRAPH_FIRST_PRINCIPLE.md`
- `foundations/KG_AGNOSTIC_ARCHITECTURE.md`
- `ongoing/ADR_DECISION_DEFENSE_ARCHITECTURE.md`
- `adr/ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md`
- `adr/ADR_SCOPE_VS_ASSERTION_SEPARATION.md`
- `adr/ADR_COVERAGE_PROPERTY_NOT_NODE.md`
- `adr/ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md`
- `ongoing/ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md`

---

## 1. Mission epistemique

### Ce qu'OSMOSIS est

> **OSMOSIS est le Knowledge Graph documentaire de l'entreprise et l'arbitre de sa verite documentaire : il capture, structure et expose la connaissance telle qu'elle est exprimee dans le corpus documentaire, sans jamais extrapoler au-dela de ce corpus.**

Version operationnelle :

> **Dans le perimetre du corpus documentaire, OSMOSIS est la source de verite. En dehors de ce perimetre, il n'a pas d'opinion.**

OSMOSIS est un **Knowledge Graph documentaire, attributif, arbitral dans son perimetre** :

| Caracteristique | Signification |
|-----------------|---------------|
| **Documentaire** | Toute connaissance est attribuee a un document |
| **Attributif** | La verite est toujours "selon document X" |
| **Arbitral (borne)** | Arbitre souverain de la verite documentaire, muet au-dela |

Le grain primaire n'est pas le concept mais l'enonce factuel attribue (ClaimKey). Le graphe est construit bottom-up. Le coeur de la valeur produit : **ClaimKey + Value + Context + Contradictions**.

> **Vocabulaire interne vs externe** : Les termes "verite documentaire", "arbitre", "source de verite" sont du vocabulaire **interne** (design, architecture). En communication **externe** (clients, demos, marketing), OSMOSIS est positionne comme une **Documentation Verification Platform** — jamais comme un "Truth Engine" (voir `VISION_PRODUIT.md` §1). Cette distinction existe car le terme "verite" est explosif commercialement alors qu'il est precis techniquement.

### Matrice des pivots par couche

Chaque couche du systeme a son propre objet pivot. **Le pivot principal du systeme est la `Claim`** — c'est l'unite atomique de fait attribue qui alimente toutes les autres couches. Les autres objets sont des **projections** de la Claim vers des usages specifiques (retrieval, navigation, comparaison). Aucun de ces objets n'est "transitoire" ou "abandonne" — ils coexistent a des couches differentes :

| Couche | Objet pivot | Role | Fichier |
|--------|-------------|------|---------|
| **Verite (KG)** | `Claim` | Unite atomique de fait attribue a un document | `claimfirst/models/claim.py` |
| **Comparaison cross-doc** | `ClaimKey` (canonical_id + markers + polarity + scope) | Grain minimal comparable entre documents | Design — implementation partielle |
| **Retrieval structurel** | `QuestionDimension` (QD) | Question stable cross-doc (ex: "Quel est le SLA ?"), registre indexe dans Neo4j | `claimfirst/models/question_dimension.py` |
| **Retrieval runtime** | `QuestionSignature` (QS) | Pairage QD + valeur extraite d'une claim specifique | `claimfirst/models/question_signature.py` |
| **Navigation (Atlas/Wiki)** | `Entity` (2198 noeuds) | Pivot d'article Wikipedia OSMOSIS | `claimfirst/models/entity.py` |
| **Canonicalisation** | `CanonicalEntity` | Entite dedupliquee cross-doc (fusion via MERGED_INTO) | Design — implementation future |
| **Lecture (Qdrant)** | `SubChunk` / TypeAwareChunk | Unite de lecture enrichie pour retrieval | `retrieval/rechunker.py` |

**QD n'est pas le successeur de ClaimKey** — c'est une projection retrieval. ClaimKey est le grain de verite (comparabilite epistemique), QD est le grain de question (requetabilite). Les deux coexistent a des couches differentes.

### Ce qu'OSMOSIS n'est PAS

| Type de systeme | Pourquoi non |
|-----------------|--------------|
| Un RAG ameliore | La valeur n'est pas dans la reponse textuelle |
| Un chatbot plus precis | L'objectif n'est pas de "mieux repondre" |
| Un KG ontologique encyclopedique | Pas de pretention universelle |
| Un KG infere / deductif | Pas de raisonnement au-dela du texte |
| Un systeme qui "comprend" les documents | Il verifie des assertions explicites |
| Un oracle omniscient | Muet hors corpus |

### Le principe d'abstention qualifiee

> **La valeur centrale d'OSMOSIS est l'abstention qualifiee.**

Un systeme qui repond toujours est un systeme qui ment parfois. OSMOSIS choisit de ne jamais mentir, quitte a ne pas conclure.

> **OSMOSIS ne promet pas la connaissance. Il promet la defendabilite.**

Ce qu'OSMOSIS arbitre :

| Ce qu'OSMOSIS arbitre | Exemple |
|-----------------------|---------|
| Ce qui est **affirme** | "TLS 1.2 est obligatoire" (doc A) -- **vrai dans le corpus** |
| Ce qui est **contredit** | Doc A dit X, Doc B dit Y -- **la contradiction est vraie** |
| Ce qui est **absent** | Aucun doc ne parle de Z -- **l'absence est vraie** |

Ce qu'OSMOSIS n'arbitre PAS : verite universelle, verite scientifique, verite du "monde reel", "bon sens metier" non documente.

### Distinction critique : Systeme vs Documents

| Le systeme ne dit PAS | Le systeme dit |
|------------------------|----------------|
| "Je ne sais pas" | "Les documents n'affirment pas X" |
| "Je n'ai pas trouve" | "Aucun document ne contient d'assertion explicite sur X" |
| "Information manquante" | "Le corpus decrit Y mais pas X" |

OSMOSIS ne declare pas son ignorance. Il declare l'absence d'assertion documentaire.

---

## 2. Invariants inviolables

Les 19 invariants sont organises par domaine. Le statut d'implementation est verifie contre le code source actuel.

### Legendes
- ✅ Implemente et verifie dans le code
- ⚠️ Partiellement implemente
- ⏳ Pas encore implemente

### 2.1 Invariants epistemiques (Verite documentaire)

| ID | Invariant | Rationale | Statut |
|----|-----------|-----------|--------|
| **INV-EPIST-01** | Pas d'assertion sans preuve localisable | Axiome fondateur. Toute Information doit etre ANCHORED_IN un DocItem avec charspan | ✅ `structural/models.py` : DocItem avec `charspan_start/end` et `charspan_start_docwide/end_docwide` |
| **INV-EPIST-02** | Perimetre corpus strict -- jamais d'inference externe | Interdiction de toute inference, "bon sens metier" non documente, resolution automatique de conflits hors documents | ✅ `synthesis.py` : prompt "Partial information rule" interdit de refuser de repondre mais interdit d'inventer |
| **INV-EPIST-03** | LLM = extracteur evidence-locked, jamais arbitre | Le LLM extrait ce qui est ecrit, pas ce qu'il "comprend". Pas de synthese cross-source a l'extraction | ⚠️ Applique au prompt de synthese, mais le pipeline d'extraction utilise encore le LLM pour classification |
| **INV-EPIST-04** | Un gap sans justification documentaire = defaillance systeme | Tout resultat non-conclusif DOIT etre adosse a au moins un extrait documentaire observable | ⏳ Decision Defense non encore implemente en production |
| **INV-EPIST-05** | Contradictions exposees, jamais resolues arbitrairement | Le systeme ne tranche pas entre documents contradictoires, il informe | ✅ `synthesis.py` : prompt regle 8 "Si information contradictoire, presenter BOTH versions" |

### 2.2 Invariants architecturaux (Graphe et stockage)

| ID | Invariant | Rationale | Statut |
|----|-----------|-----------|--------|
| **INV-ARCH-01** | Graph-First au sens orchestration logique, RAG-invariant au sens base de chunks | Le graphe structure et delimite (signaux, traversees, contexte), Qdrant fournit les preuves textuelles. Pour les questions simples (silence KG), le pipeline est un RAG pur — les chunks Qdrant sont identiques. **Runtime actuel** : Qdrant retrieval + KG claims search en parallele, puis enrichissement conditionnel par signaux. **Cible** : pathfinding GDS avant Qdrant (non implemente). | ⚠️ Partiellement : `search.py` fait Qdrant+KG en parallele, pas KG→Qdrant sequentiel. `graph_first_search.py` existe mais est **desactive** en mode ClaimFirst. |
| **INV-ARCH-02** | Neo4j = verite, Qdrant = projection | Neo4j stocke les claims et relations. Qdrant stocke les chunks de lecture (projection optimisee retrieval) | ✅ `qdrant_layer_r.py` : collection separee `knowbase_chunks_v2` |
| **INV-ARCH-03** | Toute relation stockee est navigable independamment de la maturite | Le KG ne bloque jamais la creation d'arete selon la maturite (CANDIDATE, VALIDATED, etc.) | ⚠️ Contrat defini dans KG_AGNOSTIC_ARCHITECTURE, implementation via TierFilter |
| **INV-ARCH-04** | Coverage = propriete, pas type de noeud | L'invariant coverage (preuve localisable) est garanti via DocItem, pas via CoverageChunk | ✅ `structural/models.py` : DocItem avec charspan natif, pas de CoverageChunk |
| **INV-ARCH-05** | ANCHORED_IN pointe uniquement vers DocItem, jamais vers des chunks retrieval | Separation proof surface / retrieval projection | ✅ Contrat respecte dans le pipeline ClaimFirst |

| **INV-ARCH-06** | Le KG diagnostique, il ne raconte pas | Le KG ne doit jamais injecter du contenu semantique concurrent des chunks dans le prompt LLM. Il fournit des **instructions de lecture** (tensions a surfacer, docs a comparer, limites a mentionner). Les chunks restent la seule source de preuve. Le KG est un controleur de lecture, pas un narrateur. | ⚠️ Violation actuelle : `_build_kg_context_block()` injecte du texte narratif → -7pp faithfulness vs RAG. Cible Phase 3 : `kg_findings[]` procedural. |

### 2.3 Invariants de separation (Scope vs Assertion)

| ID | Invariant | Rationale | Statut |
|----|-----------|-----------|--------|
| **INV-SEP-01** | Pas de promotion Scope vers Assertion sans preuve textuelle locale | Le contexte documentaire (titre, section, topic) n'est pas une preuve suffisante | ⚠️ Principe respecte dans le design, pas de garde-fou automatique |
| **INV-SEP-02** | Toute assertion doit avoir un EvidenceBundle avec au moins un span | "Implicite du contexte" n'est pas une evidence valide | ✅ Pipeline ClaimFirst exige verbatim |
| **INV-SEP-03** | La Scope Layer sert a filtrer/naviguer, jamais a inferer/traverser | Un consommateur ne peut pas faire : "A est dans le scope de X, donc A est lie a X" | ✅ `graph_first_search.py` : EXCLUDED_RELATION_TYPES separe navigation de semantique |
| **INV-SEP-04** | Frontiere explicite entre Scope et Assertion dans code et donnees | Pas de champ ambigu qui pourrait etre interprete des deux facons | ⚠️ Design respecte, materialisation en cours |

### 2.4 Invariants de preuve (Unite de preuve vs Unite de lecture)

| ID | Invariant | Rationale | Statut |
|----|-----------|-----------|--------|
| **INV-PROOF-01** | Unite de preuve (Claim/DocItem) reste atomique et verbatim | Precision d'extraction, ancrage deterministe | ✅ Claims dans Neo4j restent atomiques |
| **INV-PROOF-02** | Unite de lecture (chunk Qdrant) peut etre enrichie par reconstruction contextuelle sans appel LLM | Prefixe contextuel deterministe (doc_title + section_title + page) autorise | ✅ `rechunker.py` : prefixe contextuel deterministe |
| **INV-PROOF-03** | Evidence Bundles = artefacts de justification, pas de connaissance navigable | On ne navigue pas sur les bundles comme sur des relations | ⏳ Evidence Bundle Resolver non encore implemente |
| **INV-PROOF-04** | Confidence d'un bundle = minimum des fragments (jamais de moyenne) | Le maillon faible gouverne la confiance totale | ⏳ Design specifie, implementation future |

### 2.5 Invariants produit (Decision Defense)

| ID | Invariant | Rationale | Statut |
|----|-----------|-----------|--------|
| **INV-PROD-01** | Le statut (SUPPORTED/PARTIAL/NOT_SUPPORTED) est derive, jamais decide par LLM | Regle deterministe : `all(SUPPORTED) → SUPPORTED`, `any(SUPPORTED) → PARTIAL`, sinon `NOT_SUPPORTED` | ⏳ Decision Package non encore en production |
| **INV-PROD-02** | Navigation suggere, Evidence prouve -- CO_OCCURS != preuve | Les relations de navigation peuvent influencer ou chercher, mais jamais ce qui peut etre conclu | ✅ `graph_guided_search.py` : DENYLIST explicite, CO_OCCURS dans EXCLUDED_RELATION_TYPES |

---

## 3. Le graphe est le routeur

### Principe

> **Le graphe est le routeur, les preuves sont textuelles.**

> **Clarification runtime (Mars 2026)** : "Graph-First" est un principe d'**orchestration logique**, pas un ordre d'execution strict. En production actuelle, Qdrant et le KG sont interroges en parallele. Le KG enrichit le contexte via des signaux (tensions, evolutions), mais ne bloque ni ne filtre le retrieval Qdrant. Pour les questions simples ou le KG est silencieux, le pipeline est un **RAG pur identique** — c'est le hard constraint "Type A" (INV-PROD-03). La cible architecturale (pathfinding GDS avant Qdrant, mode REASONED) n'est pas encore implementee.

### Etat actuel vs cible

| Aspect | Runtime actuel (`search.py`) | Cible (`graph_first_search.py`, desactive) |
|--------|-------|-------|
| Ordre execution | Qdrant + KG claims en **parallele** | KG d'abord → Qdrant filtre ensuite |
| Role du KG | Enrichissement conditionnel (signal-driven) | Routage principal (pathfinding GDS) |
| Si KG silencieux | RAG pur (passthrough) | Mode TEXT_ONLY (fallback) |
| Chunks Qdrant | **Identiques au RAG** (INV Type A) | Filtres par le plan du graphe |
| Mode REASONED | Non actif | Chemin semantique + preuves |

### Cible : 3 modes de degradation gracieuse

Le design cible (`graph_first_search.py`, **desactive en production**) prevoit :

```
Question → extract_concepts_from_query_v2() → seed_concepts[]
                                                    |
                            ┌───────────────────────┼───────────────────────┐
                            v                       v                       v
                      REASONED                 ANCHORED                TEXT_ONLY
                  (paths semantiques       (routing structural       (fallback Qdrant
                   trouves via GDS)        via HAS_TOPIC/COVERS)      classique)
```

| Mode | Declencheur | Ce qui se passe | Qualite |
|------|-------------|-----------------|---------|
| **REASONED** | Paths semantiques trouves entre concepts seeds (GDS Yen k-shortest) | Evidence via aretes du chemin, Qdrant filtre par context_id | Maximale -- preuves tracables via le graphe |
| **ANCHORED** | Pas de paths mais routing structural (HAS_TOPIC, COVERS) | Qdrant filtre par sections identifiees structurellement | Bonne -- contexte delimite sans traversee |
| **TEXT_ONLY** | Ni paths ni routing structural | Recherche vectorielle Qdrant classique sans guidage graphe | Degradee -- RAG standard, pas de tracabilite graphe |

### Approche DENYLIST pour les relations

Le code utilise une approche DENYLIST (et non ALLOWLIST) pour determiner quelles relations sont semantiques :

```python
# Relations EXCLUES du pathfinding (techniques, navigation, faibles)
EXCLUDED_RELATION_TYPES = frozenset({
    "INSTANCE_OF", "MERGED_INTO", "COVERS", "HAS_TOPIC",
    "MENTIONED_IN", "HAS_SECTION", "CONTAINED_IN",
    "CO_OCCURS", "APPEARS_WITH", "CO_OCCURS_IN_DOCUMENT", "CO_OCCURS_IN_CORPUS",
})
```

Raison : evite le bug ou de nouvelles relations semantiques (INTEGRATES_WITH, USES...) seraient silencieusement ignorees.

---

## 4. Verite documentaire contextualisee

### Paradigme : Applicability over Truth

OSMOSE adopte le paradigme de **Verite Documentaire Contextualisee** :

> Une **Information** est une assertion explicite, extraite d'un document source, qui est vraie **dans le contexte** de ce document, sans pretention a l'universalite.

Implications :
- Tout fait technique **explicitement affirme** dans un document est une verite exploitable
- Cette verite est **toujours contextualisee** (document, version, edition, region, date)
- Les contradictions entre documents sont **exposees, jamais resolues arbitrairement**

> **Taxonomie "tension" — regle definitive** :
>
> **Tension = super-categorie metier** englobant tout desaccord inter-document.
> Les sous-types techniques dans Neo4j sont :
>
> | Relation Neo4j | Nature | Conflictuel ? | Exemple |
> |---|---|---|---|
> | `CONTRADICTS` | Affirmation directement opposee | **Oui** | "TLS 1.2 requis" vs "TLS 1.3 minimum" |
> | `REFINES` | Precision/restriction du perimetre | Non | "TLS 1.2" generalise → "TLS 1.3 pour SAP BTP" |
> | `QUALIFIES` | Ajout de condition/nuance | Non | "supporte" → "supporte avec patch X" |
>
> **Cible future** (voir `CHANTIER_KG_QUALITY.md`) : `COMPLEMENTS`, `SPECIALIZES`, `CONFLICTS`, `EVOLVES_TO`
>
> **Regle produit** : Quand on dit "252 tensions cross-doc", c'est la **somme** de CONTRADICTS + REFINES + QUALIFIES. Les contradictions dures (CONTRADICTS) sont rares (2 dans le corpus actuel). La majorite des tensions sont des REFINES/QUALIFIES (non conflictuelles mais informatives).
>
> **Regle code** : Ne jamais utiliser "contradiction" quand on veut dire "tension". Utiliser "tension" comme terme generique, "contradiction" uniquement pour CONTRADICTS.

### ClaimKey : Pivot de comparaison cross-document

Un **ClaimKey** est un identifiant stable representant une question factuelle, independant du vocabulaire utilise dans les documents.

```
KG classique : Concept → Informations → Recherche par concept
OSMOSIS      : ClaimKey → Informations → Recherche par question factuelle
               (les Concepts organisent et naviguent, ils ne decident pas)
```

Structure :
- `canonical_question` : question factuelle ("Quelle est la version TLS minimum requise ?")
- `key` : identifiant machine (`tls_min_version`)
- `linked_informations` : de differents documents, avec valeurs normalisees et contexte
- `has_contradiction` : boolean + type + tension_level

Sans ClaimKey :
- Usage B (challenge de texte utilisateur) infaisable
- Usage A (question-reponse) devient un RAG deguise
- Usage C (comparaison) devient narratif mais non defendable

### Value Contract : Comparabilite des valeurs

Les informations quantifiees portent une valeur normalisee pour permettre la detection de contradictions :

| Champ | Description | Exemple |
|-------|-------------|---------|
| `value.kind` | Type | `percent`, `number`, `version` |
| `value.raw` | Valeur brute | "99.7%", "TLS 1.2", "6 TiB" |
| `value.normalized` | Valeur normalisee | `0.997`, `1.2`, `6` |
| `value.comparable` | Statut comparabilite | `strict`, `loose`, `non_comparable` |

Regle : Contradiction `hard` uniquement si `comparable: strict`.

### Scope vs Assertion : Separation fondamentale (INV-SEP-01 a 04)

| Couche | Ce qu'elle exprime | Densite | Traversable |
|--------|-------------------|---------|-------------|
| **Scope Layer** | Ce que le document **couvre** | Dense (~90% du contenu) | Non (navigation uniquement) |
| **Assertion Layer** | Ce que le document **affirme** | Sparse (~5-15%) | Oui (raisonnement) |

**Metaphore :**
> Le graphe semantique est une **carte routiere** : peu de routes, mais fiables.
> La scope layer est un **GPS satellite** : dense, mais guide sans affirmer.
> On utilise le GPS pour trouver ou aller, la carte pour savoir quelles routes existent vraiment.

**Metriques cibles :**

| Metrique | Cible |
|----------|-------|
| Taux d'assertions | 5-15% des relations potentielles |
| Couverture scope | 90%+ des concepts mentionnes |
| Faux positifs Type 2 (assertions inventees) | 0% -- invariant absolu |

---

## 5. Decision Defense Architecture

### Paradigme

> **"OSMOSIS is not a system that tries to answer better. It is a system that refuses to answer beyond what can be proven -- and explains why."**

OSMOSIS ne vise plus a raisonner par traversee semantique, mais a **raisonner par obligations de preuve**.

### Pipeline

```
Question → Claim Generator → Evidence Searcher → Gap Qualifier → Decision Package
              |                    |                  |               |
         Claims a prouver    Preuves trouvees    Gaps qualifies   Statut derive
```

### Regles fondamentales (R1-R5)

| Regle | Enonce | Implication |
|-------|--------|-------------|
| **R1** | Pas de preuve = Pas de support | Jamais d'inference. Le silence documentaire est un resultat valide |
| **R2** | Navigation suggere, Evidence prouve | CO_OCCURS peut guider vers des documents, mais ne compte jamais comme Evidence |
| **R3** | PARTIALLY_SUPPORTED est un statut valide | Pas un echec. Certains claims prouves, d'autres non |
| **R4** | Le statut est derive, jamais decide par LLM | Regle deterministe : `all(SUPPORTED)→SUPPORTED`, `any(SUPPORTED)→PARTIAL`, sinon `NOT_SUPPORTED` |
| **R5** | PARTIALLY_SUPPORTED != securite partielle | Ne signifie PAS "presque oui". Signifie : zone a examiner attentivement |

### Decision Package : L'artefact central

> **"The Decision Package is the product."**

Structure :
- `claims[]` : chaque claim avec `status`, `evidence[]`, `gap_reason`
- `coverage` : {supported, partial, unsupported}
- `corpus_scope` : documents consultes

Tout gap_reason DOIT etre associe a au moins un element Evidence qui demontre l'absence :
- Un gap n'est pas une meta-explication generee par le systeme
- C'est une **preuve d'absence**, via substitution observable
- Le systeme montre ce qu'il a trouve **a la place** de l'assertion attendue

### Role du LLM (strictement borne)

| Autorise | Interdit |
|----------|----------|
| Detecter le type de question | Conclure en absence de preuve |
| Instancier des claim templates | Combler un gap par inference |
| Classifier des preuves | Transformer PARTIAL en affirmation |
| Produire un resume non engageant, derive du Decision Package | Generer des "peut-etre" ou "probablement" |

> Le LLM est un **assistant de structuration**, pas un **decideur**.

### Validation empirique

| POC | Questions | Types | Claim Coverage | Gaps qualifies | Gaps generiques | Verdict |
|-----|-----------|-------|----------------|----------------|-----------------|---------|
| v1 | 9 | upgrade | 92.9% | 7 | 0 | ✅ VALIDE |
| v2 | 13 | 7 types | 93.8% | 9 | 0 | ✅ VALIDE |

A comparer avec l'approche KG semantique precedente ou Pass 3 (extraction relations) montrait **97% d'abstention**.

---

## 6. Agnosticisme domaine & langue

### Principe fondamental

> **OSMOSE raisonne sur la FORME des assertions (structure linguistique, position documentaire), jamais sur le CONTENU metier.**

### Agnosticisme domaine

Aucune regle du systeme ne presuppose de vocabulaire metier :

| Element | Approche adoptee | Approche rejetee |
|---------|-----------------|------------------|
| Detection de predicats valides | Morpho-syntaxique (POS tags) | Whitelist lexicale metier |
| Types de relations | Types generiques + mapping tenant optionnel | Types hardcodes par domaine |
| Exclusions de predicats | Structurelle (auxiliaires, copules, modaux) | Liste de mots specifiques |
| Profils de visibilite | 4 comportements universels | Politiques par domaine (healthcare, legal...) |

Toute regle doit etre :
- Linguistique (POS, syntaxe, morphologie)
- OU structurelle (position, scope, proximite)
- JAMAIS lexicale-metier

### Agnosticisme langue

Le systeme utilise Universal Dependencies (POS tags universels) pour fonctionner sur toute langue supportee par spaCy :

| Detection | Mecanisme | Langues couvertes |
|-----------|-----------|-------------------|
| Modaux | `POS = AUX` (universel) | EN, FR, DE, ES, IT, PT, NL, RU, ZH, JA... |
| Conditionnels | `Mood=Cnd` (morphologie universelle) | Toutes langues avec morphologie |
| Intentionnels | Pattern `xcomp` (dependance universelle) | Toutes langues avec parser UD |
| Copules | `dep=cop` (dependance universelle) | Toutes langues avec parser UD |
| Structures predicatives | Pattern SVO (syntaxe universelle) | Toutes langues avec parser UD |

### Assertions normatives

Les assertions normatives ("shall", "must", "doit") sont grammaticalement modales mais epistemiquement factuelles dans un cadre reglementaire :
- `FACTUAL` → eligible pour promotion en relation
- `MODAL` → rejete (non factuel)
- `NORMATIVE` → non promu en relation, mais stocke avec `assertion_type=NORMATIVE` pour tracabilite

---

## 7. Separations architecturales

### 7.1 Neo4j = verite, Qdrant = projection

| Systeme | Role | Contenu | Invariant |
|---------|------|---------|-----------|
| **Neo4j** | Source de verite | Claims, relations, DocItems, SectionContexts | Toute assertion est persistee avec metadata complete |
| **Qdrant** | Projection retrieval | Chunks de lecture optimises pour la recherche vectorielle | Projection derivee, reconstructible depuis Neo4j |

Implementation : collection `knowbase_chunks_v2` dans Qdrant (Layer R), schema `v2_layer_r_1`.

### 7.2 Scope != Assertion (INV-SEP-01 a 04)

Voir Section 4. La scope layer (ce que le document couvre) est strictement separee de l'assertion layer (ce que le document affirme). Aucune promotion automatique.

### 7.3 Unite de preuve != Unite de lecture (INV-PROOF-01 et 02)

| Concept | Unite | Usage | Taille typique | Invariant |
|---------|-------|-------|----------------|-----------|
| **Unite de preuve** | DocItem / Claim | KG (Neo4j) | Atomique, verbatim | Pas d'assertion sans preuve localisable |
| **Unite de lecture** | Chunk Qdrant | Retrieval | 1500 chars cible, overlap 200 | Un expert doit pouvoir repondre a une question factuelle avec ce chunk seul |

Diagnostic Sprint 2 : 70% des chunks Qdrant faisaient < 100 chars quand on utilisait les DocItems comme unite de lecture. Cause : ClaimFirst envoie des DocItems atomiques 1:1 a Qdrant (MIN_CHARS=20). La separation formelle a resolu le probleme.

Architecture cible :
```
Document brut
    |
[Extraction] Docling + Speaker Notes
    |
    +--- DocItems atomiques → ClaimFirst → Claims → KG (unite de preuve)
    |    (verbatim, inchange)
    |
    +--- TypeAwareChunks → Prefixe contextuel deterministe → Qdrant (unite de lecture)
         (enrichie, autonome)
```

Ce qui est autorise dans les chunks de lecture :
- Prefixe contextuel deterministe (doc_title + section_title + page)
- Fusion des notes orateur PPTX avec le contenu visible (contenu auteur verbatim)
- Relations structurelles Docling (`contains`, `grouping`) comme verbatim

Ce qui reste interdit :
- Descriptions interpretatives Vision dans le chemin de connaissance
- Prefixe contextuel genere par LLM (inference, non-deterministe)
- Inference de flux directionnels dans les schemas

### 7.4 Evidence Bundles != Relations KG (INV-PROOF-03)

> **Un EvidenceBundle n'est PAS de la connaissance. C'est un artefact de justification structure.**

Implications :
- On ne "navigue" pas sur les bundles comme sur des relations
- L'UI ne doit pas presenter les bundles comme des faits
- Seules les `SemanticRelation` promues font partie du KG navigable
- Le champ `relation_type_candidate` rappelle que le type est une proposition jusqu'a promotion

### 7.5 Coverage = propriete, pas noeud (INV-ARCH-04)

L'invariant coverage ("tout anchor SPAN doit pouvoir pointer vers une unite persistee qui couvre sa position") est garanti via DocItem, pas via un type de noeud dedie.

**Avant :** Dual chunking (CoverageChunks + RetrievalChunks) -- deux pipelines a maintenir.
**Apres :** DocItem comme proof surface (charspan natif) + TypeAwareChunk comme retrieval projection.

KPIs de remplacement :

| Metrique | Formule | Cible |
|----------|---------|-------|
| **Anchor Bind Rate (ABR)** | ProtoConcepts(SPAN) avec ANCHORED_IN valide / Total(SPAN) | 100% |
| **Orphan Ratio (OR)** | ProtoConcepts sans ANCHORED_IN / Total | 0% |
| **Section Alignment Rate (SAR)** | ProtoConcepts dont section_id matche SectionContext / Total | 100% |

---

## 8. Pistes ecartees fondamentales

Cette section documente les decisions "WHY NOT" avec les preuves empiriques qui les justifient. Toute tentative de recycler ces approches doit d'abord refuter les donnees ci-dessous.

### 8.1 Concept-focused chunks

**Quoi :** Organiser les chunks autour de concepts (reformulations LLM pour chaque concept) au lieu de la structure du document.

**Donnees empiriques :**

| Metrique | Valeur mesuree |
|----------|---------------|
| Temps par document | 35+ minutes |
| Concept-focused chunks generes | 11 713 / document |
| Chunks generiques | 84 / document |
| Ratio | **140:1** (explosion combinatoire) |

**Pourquoi ecarte :** Duplication semantique massive, temps de traitement inacceptable, reformulations LLM non verifiables indexees dans Qdrant.

*Source : ADR-20241229-hybrid-anchor-model.md*

### 8.2 Vision dans le chemin de connaissance (KG path)

**Quoi :** Utiliser GPT-4o Vision pour extraire des informations des pages visuelles et les injecter dans le flux InformationMVP → Information.

**Donnees empiriques :**

| Test | Configuration | InformationMVP | Ancrees | Anchor Rate |
|------|---------------|----------------|---------|-------------|
| Run 1 | Vision ON (prompt FR) | 831 | 149 | 17.9% |
| Run 2 | Vision ON (prompt EN) | 1040 | 125 | 12.0% |
| Run 3 | Vision "Extractive Only" v3.0 | 1066 | 151 | 14.2% |
| **Run 4** | **TEXT-ONLY (Vision OFF)** | **316** | **179** | **56.6%** |

**Pourquoi ecarte :** Taux d'ancrage 12-17% malgre 4 tentatives d'optimisation. Vision genere des paraphrases non ancrables sur les DocItems (texte auteur). TEXT-ONLY produit moins de candidats mais 3x plus de resultats ancrables. Vision est relegue au rle de navigation (VisionObservation) uniquement.

*Source : ADR-20260126-vision-out-of-knowledge-path.md*

### 8.3 Bloc KG dans le prompt de synthese

**Quoi :** Injecter un bloc de contexte KG directement dans le prompt de synthese LLM.

**Donnees empiriques :**

| Metrique | Impact mesure |
|----------|--------------|
| factual_correctness | **-8pp** (degradation) |
| false_idk rate | **+6.9pp** (augmentation) |

**Pourquoi ecarte :** Le bloc KG polluait les reponses au lieu de les enrichir. Le LLM interpretait les signaux KG comme des contraintes au lieu de les utiliser comme contexte additionnel.

*Source : SPRINT0_RAPPORT_EXHAUSTIF.md, MATRICE_TRACABILITE_RATIONALIZATION.md*

### 8.4 Extraction bottom-up exhaustive (V1)

**Quoi :** Extraire des concepts chunk par chunk puis tenter de valider des relations entre eux.

**Donnees empiriques :**

| Metrique | Valeur |
|----------|--------|
| Nodes generes | **90k+** pour 19 documents |
| Relations validees | Tres peu |
| Graphe resultant | "Pur" mais **fonctionnellement inutile** |

Diagnostic : OSMOSIS scannait au lieu de lire. Concepts fragmentes, non navigables. La validation inter-chunks etait trop stricte (a juste titre -- pas de preuve locale).

*Source : ADR_STRATIFIED_READING_MODEL.md*

### 8.5 Retrieval-first RAG

**Quoi :** Architecture ou Qdrant est interroge en premier et le KG n'enrichit qu'ensuite.

**Pourquoi ecarte :** Biais "Semantic Anchoring Bug" -- le contexte retrieve domine le raisonnement du LLM, le KG ne sert que de decoration post-hoc. Le pivot vers Graph-First (ADR-20260106) a resolu ce probleme en inversant l'ordre : le graphe structure d'abord, Qdrant prouve ensuite.

*Source : ADR-20260106-graph-first-architecture.md*

### 8.6 Texte genere par LLM indexe comme evidence

**Quoi :** Indexer dans Qdrant des reformulations ou descriptions generees par le LLM.

**Pourquoi ecarte :** Risque d'hallucination indexee. Si le LLM reformule incorrectement et que cette reformulation est stockee dans Qdrant, elle devient une "verite" que le systeme retourne ensuite comme evidence. Viole INV-EPIST-01 (pas d'assertion sans preuve localisable).

> Le LLM selectionne, qualifie et consolide. Il ne materialise JAMAIS de texte indexe.

*Source : ADR-20241229-hybrid-anchor-model.md*

### 8.7 Regles hardcodees par domaine metier

**Quoi :** Definir des politiques de visibilite, des whitelist de predicats, ou des regles de promotion specifiques a un domaine (healthcare, legal, finance...).

**Pourquoi ecarte :**
- Impossible de prevoir tous les domaines d'utilisation
- Non maintenable a long terme
- Presuppose une connaissance du contexte metier
- Une ancienne whitelist `GENERIC_VERBS_EXCLUDED = {"be", "have",...}` etait anglais-only et violait l'agnosticite linguistique

Solution adoptee : 4 profils comportementaux universels (voir Section 9) + detection POS-based pour la linguistique.

*Source : KG_AGNOSTIC_ARCHITECTURE.md, ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md*

### 8.8 KG semantique riche avec raisonnement par traversee

**Quoi :** Faire emerger un KG semantique riche sans ontologie upfront et permettre un raisonnement par propagation semantique.

**Donnees empiriques :**

| Metrique | Valeur |
|----------|--------|
| Pass 3 (extraction relations) | **97% d'abstention** |
| Cause | Les documents SAP decrivent des procedures, pas des assertions relationnelles |
| CO_OCCURS et MENTIONED_IN | Ne constituent pas des preuves |

**Pourquoi ecarte :** Structurellement deceptif sur des corpus proceduraux et normatifs. Les relations CO_OCCURS sont des correlations, pas des causalites. Le pivot vers Decision Defense (raisonnement par obligations de preuve) a remplace cette approche.

*Source : ADR_DECISION_DEFENSE_ARCHITECTURE.md*

---

## 9. Profils de visibilite

### Modele 5 couches

```
Couche 5 : DECISION        — Puis-je m'y fier ? → Humain / Metier
Couche 4 : UI / API        — Comment presenter ? → Produit
Couche 3 : PROFIL          — Montrable ?         → Admin Tenant
Couche 2 : TOPOLOGIE       — Navigable ?         → Knowledge Graph
Couche 1 : STOCKAGE        — Existe ?            → Knowledge Graph
```

Invariants par couche :

| Couche | Le KG ne doit JAMAIS... |
|--------|-------------------------|
| 1 - Stockage | ...supprimer une relation car elle est "peu fiable" |
| 2 - Topologie | ...bloquer la creation d'arete selon la maturite |
| 3 - Profil | ...hardcoder des regles par domaine metier |
| 4 - UI/API | ...afficher sans distinction de maturite |
| 5 - Decision | ...remplacer le jugement humain |

### 4 profils comportementaux universels

| Profil | Description | min_confidence | min_source_count | Cas d'usage |
|--------|-------------|----------------|------------------|-------------|
| **VERIFIE** | Uniquement les faits confirmes par plusieurs sources | 0.90 | 2 | Decisions importantes, fiabilite maximale |
| **EQUILIBRE** (defaut) | Faits verifies + informations fiables avec indication | 0.70 | 1 | Usage quotidien, bon equilibre quantite/qualite |
| **EXPLORATOIRE** | Maximum de connexions, conflits et ambiguites visibles | 0.40 | - | Exploration d'un nouveau sujet, brainstorming |
| **COMPLET** | Acces a toutes les donnees sans filtre | 0.00 | - | Administration, audit, debug technique |

Regles :
- Le changement de profil est immediat et ne modifie jamais les donnees sous-jacentes
- Le meme profil s'applique au graphe, a la recherche semantique, et aux reponses chat
- Pas de profils personnalises en v2.0 (les 4 couvrent 95% des besoins)
- `full_access` reserve aux admins

---

## 10. References archive

Pour le raisonnement detaille et l'historique complet des decisions, consulter les documents originaux dans `doc/archive/pre-rationalization-2026-03/` :

### Principes fondateurs
| Document | Contenu |
|----------|---------|
| `foundations/GRAPH_FIRST_PRINCIPLE.md` | Principe Graph-First original |
| `foundations/KG_AGNOSTIC_ARCHITECTURE.md` | Modele 5 couches, 4 profils, contrats KG/Visibility |

### ADR structurants
| Document | Contenu |
|----------|---------|
| `adr/ADR_NORTH_STAR_VERITE_DOCUMENTAIRE.md` | Information-First, ClaimKey, Value Contract, Addressability |
| `adr/ADR_SCOPE_VS_ASSERTION_SEPARATION.md` | Separation Scope/Assertion, INV-SEP-01 a 04 |
| `adr/ADR_COVERAGE_PROPERTY_NOT_NODE.md` | Coverage via DocItem, KPIs ABR/OR/SAR |
| `adr/ADR_MULTI_SPAN_EVIDENCE_BUNDLES.md` | Evidence Bundle Resolver, agnosticisme domaine/langue |
| `adr/ADR-20260106-graph-first-architecture.md` | Pivot Graph-First, 3 modes degradation |
| `adr/ADR-20241229-hybrid-anchor-model.md` | Suppression concept-focused chunks |
| `adr/ADR_STRATIFIED_READING_MODEL.md` | Diagnostic echec V1 bottom-up |

### ADR Decision Defense
| Document | Contenu |
|----------|---------|
| `ongoing/ADR_DECISION_DEFENSE_ARCHITECTURE.md` | Paradigme complet, R1-R5, Decision Package, POC v1/v2 |

### ADR preuve et lecture
| Document | Contenu |
|----------|---------|
| `ongoing/ADR_UNITE_PREUVE_VS_UNITE_LECTURE.md` | Separation formelle unite de preuve / unite de lecture |
| `ongoing/ADR-20260126-vision-out-of-knowledge-path.md` | Vision hors du chemin de connaissance |

### Historique des pivots
| Document | Contenu |
|----------|---------|
| `OSMOSIS_PROJECT_HISTORY.md` | 6 pivots architecturaux, anti-patterns documentes |
| `ongoing/ANALYSE_POC_COMPOSER_CROSS_DOC.md` | 5 approches echouees, patterns a ne pas recycler |

---

*Document genere le 29 mars 2026 -- Rationalisation documentation OSMOSIS.*
*Tout ajout d'invariant doit etre accompagne d'un ADR dans `doc/ongoing/` et d'une mise a jour de ce document.*
