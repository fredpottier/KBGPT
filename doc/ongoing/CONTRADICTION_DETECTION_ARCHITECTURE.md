# OSMOSIS — Moteur d'analyse logique de règles documentaires

*Document de synthèse — 28 avril 2026 (V3.3 — séparation 3 axes orthogonaux Scope/Temporalité/Lifecycle + provenance vs inférence + REAFFIRMS)*

> 🔒 **VERSION FIGÉE V3.3 — 28 avril 2026 — Architecture cible "Modèle du monde"**
> Ce document décrit la **couche modèle** d'OSMOSIS (extraction, persistence, schéma KG, typologie de relations). Il a atteint sa stabilité conceptuelle après 4 cycles de challenge croisé Fred / Claude / ChatGPT.
>
> **La couche runtime exploitation** (query resolver, priorisation des relations, kg_trust score, fallback strategies, synthesis) est traitée dans un document séparé : [`RUNTIME_EXPLOITATION_ARCHITECTURE.md`](./RUNTIME_EXPLOITATION_ARCHITECTURE.md).
>
> Toute évolution future du modèle (nouveau type de relation, nouvel axe orthogonal) fera l'objet d'une version V3.4+ explicite. Le runtime évolue indépendamment.

> Document destiné à expliciter l'architecture cible d'OSMOSIS pour passer d'un détecteur de contradictions LLM-judge vers un moteur d'analyse logique de relations entre claims documentaires. Synthèse de :
> - Constat empirique sur le corpus aerospace + dual-use (10 471 pages PDF, 40 196 claims, 10 289 relations détectées par le post-import)
> - Revue de la littérature académique 2024-2025
> - Analyse de l'infrastructure OSMOSIS actuelle (DocumentContext, ApplicabilityFrame, Domain Packs)
> - 2 cycles de challenge / contre-challenge avec ChatGPT (28 avril 2026)
> - Validation des cas d'usage historiques OSMOSIS (versioning produit, contradiction sur dosage, etc.) — **garantie de non-régression V3.1**
>
> **Pivot V2 (acquis)** : on ne cherche plus *"ces 2 claims se contredisent-elles ?"* (problème NLP de classification binaire) mais *"quelle est la relation logique entre ces 2 claims ?"* (problème de classification multi-classe avec décision déterministe). La contradiction devient un **cas particulier** d'une typologie plus large.
>
> **Affinements V3 (acquis)** :
> - Relation **strength** (STRONG / WEAK / UNCERTAIN) en plus du type
> - **Confidence threshold différencié par type** de relation (CONFLICT plus strict que SUBSET)
> - **Skip persistence UNRELATED** (ne pas polluer le KG avec des arêtes vides)
> - **Composabilité / transitivité** promue de "optionnel" à feature de premier plan (passage de *graph de faits* à *graph de raisonnement*)
>
> **Extension V3.1 (acquise)** :
> - **Ajout des relations temporelles** `SUPERSEDES` et `EVOLVES_FROM` — pour traiter explicitement les cas de versioning produit ("X utilise B depuis version Z") et de mise à jour réglementaire ("dosage Y remplace dosage X depuis le RCP révisé").
> - Garantie de **non-régression** par rapport aux cas d'usage historiques OSMOSIS : la typologie 11-types préserve TOUTES les capacités V1 tout en distinguant proprement les cas mal classés auparavant (ex: faux CONTRADICTS sur évolutions temporelles).
>
> **Upgrade V3.2 (ce document) — Temporalité comme dimension intrinsèque du fait** :
> - Dans un RAG classique, la date d'un document est une **métadonnée** (filtrage occasionnel, jamais dans la génération). L'embedding est a-temporel : 2 docs qui se contredisent à 2 dates différentes ont des embeddings proches et sont retrouvés ensemble.
> - Dans un système qui vise le **jugement** (compliance, regulatory, medical), la temporalité n'est PAS une métadonnée : c'est une **dimension du fait lui-même**. *"La procédure X valide les commandes > 10K€"* n'est pas une affirmation universelle — c'est une affirmation **vraie dans une fenêtre temporelle**, remplaçable, abrogeable, modifiable.
> - V3.2 traite cette différence en first-class :
>   1. **3 timestamps par fait** (`publication_date`, `validity_start/end`, `ingestion_date`)
>   2. **Relations temporelles bidirectionnelles** (déjà V3.1 : SUPERSEDES, EVOLVES_FROM)
>   3. **Retrieval temporellement aware** (filtrage / pondération par date contextuelle de la question)
> - **C'est un différenciateur produit majeur** : aucun framework RAG grand public (LangChain, LlamaIndex, Microsoft GraphRAG) ne traite la temporalité comme une dimension intrinsèque. Elle reste métadonnée bricolable dans tous les outils dominants.

---

## 1. Le problème, factuel

OSMOSIS est positionné comme un système RAG+KG dont la **valeur principale** est la détection automatique de contradictions cross-document, pour environnements régulés (aerospace, dual-use, medical, legal, tech specs).

Sur le corpus en production (avril 2026) :
- 17 documents PDF (CS-25 amendments + EU dual-use regulations) = **10 471 pages**
- 40 196 claims atomiques extraites
- Le post-import `detect_contradictions` a généré **10 289 relations** (CONTRADICTS / REFINES / QUALIFIES) en Phase B LLM, sur 29 525 paires cross-doc analysées.

**Le problème observé empiriquement** : un échantillon de relations CONTRADICTS contient un fort taux de faux positifs typiques. Exemple concret :

```
Source A (Del 2023/66, p.192, Annex Control List) :
"Output energy > 0.002 J per pulse + pulse duration ∈ [1ps, 1ns] + ..."

Source B (Reg 2021/821, p.47, Definitions) :
"Pulsed laser means a laser having a pulse duration ≤ 0.25 seconds."

→ Détecté comme CONTRADICTS par le LLM
→ En réalité : Source A définit un sous-ensemble étroit (1ps–1ns) de la 
   catégorie générale "Pulsed laser" (≤ 0.25s) définie par Source B.
   Les scopes sont emboîtés, pas opposés. Devrait être REFINES.
```

**Coût opérationnel actuel** : aucun humain ne peut valider 800+ contradictions candidate. La valeur business du système s'effondre si le bruit n'est pas adressé architecturalement.

---

## 2. État de l'art académique (oct 2024 → oct 2025)

### Constat partagé

> **NLI naïf sur paires cross-document = 16 % precision** (mesure LegalWiz, oct 2025).
> Même un LLM seul stagne à ~70.9 % F1 en pairwise. Ce n'est pas un problème de prompt, c'est un problème **architectural**.

### Approches publiées qui marchent

#### 2.1 Cascading filters — LegalWiz (oct 2025)

```
Sentence pair candidates
  ↓ Semantic filtering (top-5 par embedding distance)
  ↓ NLI classifier (confidence weighted)
  ↓ LLM judgment (confidence weighted)
  ↓ Hybrid score : w_NLI · p_NLI + w_LLM · p_LLM
```

Gain mesuré : NLI seul 16 % → ensemble **71 % F1**. Validation humaine : Cohen's κ = 0.83–0.91 (annotateurs).

Source : *LegalWiz — A Multi-Agent Generation Framework for Contradiction Detection in Legal Documents* (arXiv 2510.03418).

#### 2.2 Defeasible Deontic Logic (DDL) — juin 2025

Transformer chaque énoncé réglementaire en :

```
RuleID: 1A006-pulse → [F] export(laser, EU→TIERS) ON pulse_duration ∈ [1ps, 1ns]
RuleID: def-pulsed-laser → [DEF] pulsed_laser ⇔ pulse_duration ≤ 0.25s
```

Plus une **superiority relation** : `1A006-pulse ⊃ def-pulsed-laser` (la règle spécifique l'emporte sur la générale).

Détecteur de contradictions = parcours d'un **graph DDL** avec moteur d'inférence défaisable. Pas de LLM dans la boucle critique, déterministe, auditable.

Performance : **80 % precision** sur Australian Telecom Code après fine-tuning GPT-4o pour la transformation NL → DDL.

Source : *From Legal Texts to Defeasible Deontic Logic via LLMs* (arXiv 2506.08899).

#### 2.3 RST + Graph Fusion — EMNLP 2025

Cross-Document Cross-Lingual NLI utilisant des **arbres RST** (Rhetorical Structure Theory) pour aligner les structures discursives entre documents avant le NLI. Améliore significativement par rapport au NLI vanilla mais alourdit la pipeline.

Source : *Cross-Document Cross-Lingual NLI via RST-Enhanced Graph Fusion* (ACL EMNLP 2025).

#### 2.4 Cross-document relation extraction via entity graph (juin 2024)

Décompose les entités en :
- **Bridge entities** : partagées entre les 2 docs (rares — 2.6 par chemin en moyenne)
- **Non-bridge entities** : co-occurrence asymétrique (16.2 par chemin)

L'enseignement : la **pair selection** ne doit PAS reposer sur le seul cosine. Les non-bridge entities apportent un signal puissant.

Source : *Towards Better Graph-based Cross-document Relation Extraction* (arXiv 2406.16529).

---

## 3. Anatomie du problème — pourquoi le détecteur actuel se trompe

Le pipeline `detect_contradictions` actuel d'OSMOSIS fait :

```
Phase A (formelle) : regex/déterministe → 825 relations (REFINES, QUALIFIES)
Phase B (LLM) : 29 525 paires cross-doc → 10 289 relations
   pair selection = clusters cross-doc partageant des entités/embeddings proches
   décision = LLM "ces 2 phrases sont-elles contradictoires ?"
```

**Trois failles structurelles** :

### 3.1 Pair selection insuffisamment riche

La sélection de paires repose principalement sur **similarité sémantique (cosine sur embeddings)**. Conséquences :
- Manque les paires lexicalement éloignées mais sémantiquement liées (ex : "Pulse duration < 1 ns" vs "Pulsed laser ≤ 0.25 s" — partagent le concept "Pulsed laser" mais cosine moyen)
- Génère des paires entre claims partageant juste un mot fréquent du domaine
- N'exploite pas la riche structure du KG (CanonicalEntity, Facets, Clusters)

### 3.2 Pas de scope alignment avant le LLM

Le LLM voit deux phrases sans savoir si elles **s'appliquent au même scope**. Une définition générale et une restriction spécifique ont une intersection dans l'espace lexical mais pas dans le scope d'applicabilité.

Le pipeline OSMOSIS extrait pourtant un `ApplicabilityFrame` par document (release_id, region, edition, conditions) — mais **cette information n'est PAS passée au détecteur de contradictions**.

### 3.3 Pas de modélisation rhétorique

Une DEFINITION (Source B "Pulsed laser means...") joue un rôle **différent** d'une RESTRICTION (Source A "Output energy > X + pulse ∈ [1ps, 1ns] is controlled"). Ces 2 énoncés ne **peuvent structurellement pas** se contredire — le premier établit un terme, le second impose une condition à un sous-ensemble nommé.

Le détecteur actuel n'a aucune notion de **rôle rhétorique du passage**.

### 3.4 Faille fondamentale (V2) — paradigme classification binaire

Au-delà des trois failles structurelles ci-dessus, il existe **une faille de fond** que ChatGPT a permis d'expliciter : le pipeline traite un **problème logique** comme un **problème de similarité + classification binaire**.

Le pattern actuel :
```
pair → LLM → "is contradiction ?" → boolean
```

Or la réalité d'un corpus réglementaire est :
```
rule A + rule B → relation logique (subset/superset/exception/conflict/...) 
                → puis décision déterministe : contradiction = (relation == CONFLICT) ∧ scope_overlap
```

Conséquences du paradigme actuel :
- **Non déterministe** : le même couple (A, B) peut donner CONTRADICTS aujourd'hui et REFINES demain selon la version du modèle ou la température.
- **Non auditable** : pour un audit AI Act, on ne peut pas justifier *pourquoi* le LLM a tranché contradiction. Pas de chaîne de raisonnement formelle.
- **Non composable** : impossible de chaîner des inférences ("si A REFINES B et B REFINES C, alors A REFINES C") car les relations sont émises ad-hoc.

**Correction V2** : sortir du paradigme *LLM-as-judge* vers *LLM-as-extractor* d'une typologie de relations logiques, avec décision finale déterministe.

---

## 3 bis. Pivot V2 — De la détection de contradictions au moteur d'analyse logique

### Reframing produit

Ce que tu construis n'est pas :
- ❌ un RAG amélioré
- ❌ un détecteur de contradictions

Mais :
- ✅ **un moteur d'analyse logique de règles documentaires**

La contradiction devient un **cas particulier** d'une typologie plus large de relations logiques. Et ce reframing est plus puissant produit + plus correct techniquement.

### Typologie des relations logiques (la vraie sortie du système — V3.3)

```python
class LogicalRelation(Enum):
    # Relations ensemblistes
    SUBSET        = "subset"          # A ⊂ B (A est un cas particulier de B)
    SUPERSET      = "superset"        # A ⊃ B
    EQUIVALENT    = "equivalent"      # A ≡ B
    OVERLAP       = "overlap"         # A ∩ B ≠ ∅, mais ni SUBSET ni SUPERSET
    DISJOINT      = "disjoint"        # A ∩ B = ∅
    
    # Relations sémantiques
    CONFLICT      = "conflict"        # A et B affirment l'opposé sur même scope
    EXCEPTION     = "exception"       # A déroge à B sous conditions (population, contexte)
    DEFINITION_OF = "definition_of"   # A définit un terme utilisé dans B
    
    # Relations temporelles (V3.1 + V3.3)
    SUPERSEDES    = "supersedes"      # A remplace B (B obsolète depuis une date/version)
    EVOLVES_FROM  = "evolves_from"    # A est une évolution naturelle de B (continuité)
    REAFFIRMS     = "reaffirms"       # A confirme la validité de B sans la modifier (V3.3)
    
    UNRELATED     = "unrelated"       # pas de relation logique pertinente
```

#### Distinction CONFLICT vs SUPERSEDES vs EXCEPTION (cas dosage médical)

| Situation | Type | Exemple |
|---|---|---|
| Même indication, même population, valeurs incompatibles | `CONFLICT` (true contradiction) | Doc A "200 mg/j" vs Doc B "300 mg/j" même contexte → erreur à arbitrer |
| Population spécifique différente | `EXCEPTION` | Standard "200 mg/j" + "150 mg/j si insuffisance rénale" → règle + exception légitime |
| Mise à jour temporelle | `SUPERSEDES` | RCP v2 "300 mg/j (depuis 2026-03)" remplace RCP v1 "200 mg/j" → évolution officielle |
| Pas de scope partagé | `DISJOINT` | "Médicament A 200 mg" et "Médicament B 300 mg" → claims sur sujets différents |

#### Distinction SUPERSEDES vs EVOLVES_FROM

- `SUPERSEDES` : la nouvelle assertion **invalide** l'ancienne (l'ancienne ne s'applique plus)
  - Ex : "Reg 2021/821 supersedes Reg 428/2009" — l'ancien règlement est abrogé
- `EVOLVES_FROM` : la nouvelle assertion **prolonge ou affine** l'ancienne (l'ancienne reste utile pour comprendre le contexte)
  - Ex : "CS-25 amdt 28 evolves_from amdt 27" — l'ancien amendement reste référence historique

Le distinguo se fait via le **document_role** + **modal_operator** :
- Si le doc nouveau dit explicitement "repeals", "abrogates", "replaces" → `SUPERSEDES`
- Si le doc nouveau dit "amends", "updates", "revises" sans abroger → `EVOLVES_FROM`

#### Sortie produit V3.1

Ce qu'OSMOSIS produit en sortie n'est plus *"voici 800 contradictions à valider"* mais :
- *"Voici 47 EXCEPTIONS détectées sur le règlement EU 2021/821"* (population/contexte spécifique)
- *"Voici 213 SUBSETS — règles spécifiques affinant des règles générales"*
- *"Voici 8 CONFLICTS véritables — incompatibilités sémantiques sur scope identique, à arbitrer"*
- *"Voici 156 SUPERSEDES — règles obsolètes remplacées par des versions plus récentes"* (V3.1)
- *"Voici 89 EVOLVES_FROM — chaînes d'évolution de spécifications dans le temps"* (V3.1)
- *"Voici 1 247 DEFINITION_OF — définitions de termes réutilisés"*

Cette **vue exhaustive** est plus précieuse pour un compliance officer / regulatory specialist / product manager qu'une simple liste de contradictions : elle expose la **structure logique ET temporelle du corpus**.

### LLM = extracteur, pas juge

Avant (V1) :
```
Question LLM:  "Are these 2 claims contradictory ? Y/N"
Décision:      LLM-as-judge (boolean)
Stabilité:     Faible (dépend du modèle, prompt, température)
Auditabilité:  Faible (pas de raisonnement formalisé)
```

Après (V2) :
```
Question LLM:  "Classify the logical relation between A and B
                ∈ {SUBSET, SUPERSET, EQUIVALENT, OVERLAP, DISJOINT,
                   CONFLICT, EXCEPTION, DEFINITION_OF, UNRELATED}.
                Return: {relation, confidence, reasoning}"
Décision:      Déterministe (function (relation, scope, role) → contradiction Y/N)
Stabilité:     Plus élevée (la règle finale est déterministe)
Auditabilité:  Bonne (relation typée + reasoning + règle finale formalisée)
```

### Ce qui change dans le KG

Aujourd'hui, on a 3 types de relations ad-hoc (`CONTRADICTS`, `REFINES`, `QUALIFIES`). V2 :

```cypher
MERGE (a:Claim)-[r:LOGICAL_RELATION {
    type: 'subset' | 'conflict' | 'exception' | 'definition_of' | ...,
    confidence: 0.92,
    reasoning: "Claim A's pulse_duration range [1ps, 1ns] is a strict 
                subset of Claim B's general definition pulse_duration ≤ 0.25s.",
    extracted_by: "qwen2.5-14b-awq",
    extracted_at: timestamp(),
    scope_alignment: "subset",
    document_role_pair: ("RESTRICTION", "DEFINITION")
}]->(b:Claim)
```

**Une seule relation typée riche** plutôt que plusieurs relations ad-hoc. La contradiction est dérivée :
```cypher
MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'conflict'}]->(b:Claim)
WHERE r.confidence > 0.85
  AND r.scope_alignment = 'overlap'   // scope identique = vraie contradiction
RETURN a, b, r
```

---

## 4. Architecture cible — proposition en 4 phases (+ pré-requis)

### Phase 0 (PRÉ-REQUIS) — Fiabiliser l'ApplicabilityFrame + TemporalFrame (V3.2.1)

**Constat de l'audit Neo4j** (28/04/2026) :
- 17/17 DocumentContext ont `applicability_frame_json` rempli ✅
- **0/17 ont `axis_values` populé** ❌
- **6/17 docs sans aucune relation HAS_AXIS_VALUE** ❌
- **1 seul node ApplicabilityAxis dans le KG global** ❌ (au lieu d'un par axis détecté)
- **Aucune fenêtre de validité explicite sur les Claims** ❌

L'infrastructure existe en code mais le résultat persisté est **fragile**, et la dimension temporelle manque totalement. V3.2.1 fusionne les 2 chantiers en un seul.

**Phase 0.A — ApplicabilityFrame (scope)** :
1. Investiguer pourquoi 6 docs n'ont pas d'axis détecté (cs25_change_amdt_*, dual-use small)
2. Persister proprement les `axis_values` (en propriété OU en relations vers ApplicabilityAxis)
3. Garantir qu'au minimum chaque DocumentContext a un `release_id` ou équivalent
4. Backfill rétroactif

**Phase 0.B — TemporalFrame (3 timestamps)** :
1. Implémenter la cascade 5-tiers d'extraction temporelle (cf. §4 bis.B)
2. Persister sur chaque Claim : `publication_date`, `validity_start`, `validity_end`, `ingestion_date`, `temporal_axis_source`, `temporal_confidence`
3. Persister sur chaque DocumentContext les mêmes timestamps (héritables par les Claims si non extraits localement)
4. Backfill rétroactif sur les 17 docs / 40 196 claims existants

**Effort estimé V3.2.1 : 7-10 jours** (au lieu de 5-7j en V3 — surcoût de 2-3j pour TemporalFrame, justifié par l'élimination de la Phase 4 bis tardive).

### Phase 1 — Pair selection multi-signal

Remplacer "cosine > seuil" par un score multi-canal :

```python
def candidate_pair_score(claim_a, claim_b) -> float:
    # 1. Embedding similarity (current)
    s_cos = cosine(emb_a, emb_b)
    
    # 2. Shared CanonicalEntity (already in KG, 2 320 canonical entities)
    shared_ce = canonical_entities(claim_a) & canonical_entities(claim_b)
    s_ent = min(1.0, len(shared_ce) / 2.0)
    
    # 3. Shared facet (theme overlap, 68 facets in KG)
    s_facet = 1.0 if facet(claim_a) == facet(claim_b) else 0.0
    
    # 4. Shared cluster (already computed in cluster_cross_doc)
    s_cluster = 1.0 if cluster(claim_a) == cluster(claim_b) else 0.0
    
    # 5. Graph proximity (multi-hop via ABOUT/MENTIONS)
    s_graph = max(0, 1.0 - graph_distance(claim_a, claim_b) / 4.0)
    
    return 0.3*s_cos + 0.25*s_ent + 0.15*s_facet + 0.2*s_cluster + 0.1*s_graph
```

**Avantage** : 4 signaux sur 5 sont déjà calculés en post-import. C'est 80 % gratuit.

**Effort estimé : 3-5 jours** (refonte de la requête de génération de paires cross-doc).

### Phase 2 — Scope & Temporal Gate (V3.2.1 — filter avant LLM)

Avant chaque appel LLM, vérifier la compatibilité **scope ET temporelle**. Le second axe permet de détecter des relations temporelles déterministiquement (sans LLM) quand 2 claims sont sur même scope mais à des dates incompatibles.

```python
def gate_compatibility(claim_a, claim_b) -> GateDecision:
    frame_a = applicability_frame(claim_a.doc_id)
    frame_b = applicability_frame(claim_b.doc_id)
    
    # 2.A — Scope alignment (V2/V3)
    scope_relation = compute_scope_relation(frame_a, frame_b)
    
    if scope_relation == DISJOINT:
        return DECISION_SKIP_DISJOINT_SCOPE  # SKIP, no LLM call
    
    if scope_relation in (SUBSET, SUPERSET):
        # → candidat REFINES, mais on regarde aussi la temporalité avant de trancher
        ...
    
    # 2.B — Temporal alignment (V3.2.1)
    temporal_relation = compute_temporal_relation(claim_a, claim_b)
    
    if temporal_relation == TEMPORAL_DISJOINT:
        # Scopes identiques mais fenêtres de validité non-chevauchantes
        # → candidat fort SUPERSEDES, à confirmer par le LLM
        return DECISION_LIKELY_SUPERSEDES_OR_EVOLVES
    
    if temporal_relation == TEMPORAL_OVERLAP:
        # Fenêtres chevauchantes → vraie compatibilité, possibilité de CONFLICT
        return DECISION_FULL_LLM_CLASSIFY
    
    return DECISION_FULL_LLM_CLASSIFY


def compute_temporal_relation(claim_a, claim_b) -> TemporalRelation:
    """
    Compare les fenêtres de validité [validity_start, validity_end] de 2 claims.
    """
    a_start = claim_a.validity_start or claim_a.publication_date
    a_end = claim_a.validity_end  # None = encore valide
    b_start = claim_b.validity_start or claim_b.publication_date
    b_end = claim_b.validity_end
    
    if (a_end is not None and b_start is not None and a_end < b_start):
        return TEMPORAL_DISJOINT  # A se termine avant que B commence
    
    if (b_end is not None and a_start is not None and b_end < a_start):
        return TEMPORAL_DISJOINT  # B se termine avant que A commence
    
    return TEMPORAL_OVERLAP
```

**Sur le faux positif laser** (cas V2) : `pulse_duration ∈ [1ps, 1ns]` ⊂ `pulse_duration ≤ 0.25s` → scope SUBSET. Si en plus les 2 sont contemporaines (validity_window_overlap), on tranche REFINES sans LLM. Si l'une est superseded, on tranche SUPERSEDES sans LLM.

**Sur le cas dosage médical** (V3.1) :
- Doc 1 : "Médicament A 200mg/j" valid 2018-2023
- Doc 2 : "Médicament A 300mg/j" valid 2024-NOW
- → scope identique + temporal disjoint → **DECISION_LIKELY_SUPERSEDES_OR_EVOLVES**, confirmé par LLM avec input enrichi

**Effort estimé V3.2.1 : 5-7 jours** (au lieu de 3-5j en V3 — surcoût de 2j pour le temporal alignment).

### Phase 3 V2 — Logical Relation Classifier (LLM-as-extractor)

> Cœur du pivot V2. Remplace la "matrice d'incompatibilité binaire" par un classifieur multi-classe LLM + décision déterministe en aval.

#### 3.A — Document Role (input du classifier)

Le rôle rhétorique reste extrait via la cascade 4-tiers ci-dessous, mais il devient un **input** du classifier (pas une matrice de filtrage standalone) :

```
TIER 1 — Structure documentaire explicite (déterministe, gratuit)
   Lecture du heading parent + page_type Docling, mappé via Domain Pack.
   Confidence: 0.9
   
TIER 2 — Heuristiques lexicales locales
   Regex sur le passage : "Note:", "Exception:", "Sauf", "Must", ...
   Confidence: 0.6

TIER 3 — LLM role tagging (1 call par chunk, pas par claim)
   Pour les docs faiblement structurés (wiki, mémos, blog).
   Coût : ~$0.01 / doc
   Confidence: 0.7-0.8
   
TIER 4 — Default UNKNOWN
   Le classifier reçoit role=UNKNOWN ; il décidera sans ce signal.
```

#### 3.B — Domain-aware role mapping via Domain Packs

```yaml
# domain_packs/aerospace_compliance/role_mapping.yaml
roles:
  DEFINITION:
    section_titles_regex: ["^definitions?$", "^terms?$", "^terminology"]
  RESTRICTION:
    section_titles_regex: ["^annex (i|ii|iii)", "^control list", "^restrictions?"]
    page_types: ["annex"]
  EXCEPTION:
    section_titles_regex: ["exemptions?", "exceptions?", "derogations?"]
  GUIDANCE:
    section_titles_regex: ["^guidance material", "^amc", "acceptable means"]

# domain_packs/medical/role_mapping.yaml
roles:
  INDICATION:
    section_titles_regex: ["^therapeutic indications?$"]
  CONTRA_INDICATION:
    section_titles_regex: ["^contra-?indications?$"]
  ADVERSE_EFFECT:
    section_titles_regex: ["^undesirable effects?", "^adverse reactions?"]
```

#### 3.C — Logical Relation Classifier (le coeur V2)

Au lieu de demander au LLM "are these contradictory ?", on lui demande de **classifier la relation logique** sur une typologie fermée :

```python
def classify_logical_relation(claim_a: Claim, claim_b: Claim,
                              scope_relation: ScopeRelation,
                              ) -> LogicalRelationOutput:
    """
    LLM-as-extractor : classifie la relation logique entre 2 claims.
    Retourne (relation_type, confidence, reasoning).
    """
    prompt = f"""
    Classify the logical relation between two regulatory claims.
    
    Claim A:
      role: {claim_a.document_role}      # DEFINITION / RESTRICTION / EXCEPTION / ...
      scope: {claim_a.scope_dict}        # release_id, region, conditions, ...
      modal_operator: {claim_a.modal}    # OBLIGATION / PERMISSION / PROHIBITION / DEFINITION
      predicate: {claim_a.predicate}
      object: {claim_a.object}
    
    Claim B: {{...}}
    
    Pre-computed scope alignment: {scope_relation}
    
    Choose ONE relation from:
    - SUBSET: A is a strict particular case of B (e.g., A's range is inside B's range)
    - SUPERSET: B is a strict particular case of A
    - EQUIVALENT: A and B express the same rule
    - OVERLAP: A and B share scope partially but neither is subset of the other
    - DISJOINT: A and B don't apply to the same things
    - CONFLICT: A and B make incompatible assertions on identical scope (TRUE contradiction)
    - EXCEPTION: A derogates B under specific conditions
    - DEFINITION_OF: A defines a term used in B (or vice versa)
    - UNRELATED: no meaningful logical relation
    
    Return JSON:
    {{
      "relation": "...",
      "confidence": 0.0-1.0,
      "reasoning": "structured explanation of the choice"
    }}
    """
    return llm.classify_structured(prompt, schema=LogicalRelationOutput)
```

#### 3.D — Décision déterministe (la contradiction = règle, pas LLM)

```python
def is_true_contradiction(rel_output: LogicalRelationOutput,
                          scope: ScopeRelation,
                          ) -> tuple[bool, str]:
    """
    Décision déterministe basée sur la typologie + scope.
    Le LLM ne tranche PAS — la fonction tranche.
    """
    # Vraie contradiction : conflit + scope identique + haute confidence
    if (rel_output.relation == LogicalRelation.CONFLICT
        and scope == ScopeRelation.OVERLAPPING
        and rel_output.confidence >= 0.85):
        return True, "true_conflict_high_confidence"
    
    # Faux positif typique : SUBSET/SUPERSET = REFINES, pas contradiction
    if rel_output.relation in (LogicalRelation.SUBSET, LogicalRelation.SUPERSET):
        return False, "subset_relation_not_contradiction"
    
    # EXCEPTION = relation valide mais pas contradiction au sens strict
    if rel_output.relation == LogicalRelation.EXCEPTION:
        return False, "exception_relation_not_contradiction"
    
    # DEFINITION = catégorie différente (DEF vs RESTRICTION)
    if rel_output.relation == LogicalRelation.DEFINITION_OF:
        return False, "definition_relation_not_contradiction"
    
    # CONFLICT mais sur scope partiellement disjoint = contradiction faible
    if rel_output.relation == LogicalRelation.CONFLICT:
        return False, "conflict_but_partial_scope"
    
    # Tout le reste = pas une contradiction
    return False, f"relation_{rel_output.relation.value}"
```

#### 3.E — Persistance dans le KG (relation typée riche)

```cypher
MERGE (a:Claim {claim_id: $a_id})-[r:LOGICAL_RELATION {
    type: $relation_type,
    confidence: $confidence,
    reasoning: $reasoning,
    extracted_by: $model_id,
    extracted_at: $timestamp,
    scope_alignment: $scope_relation,
    document_role_pair: $role_pair,
    is_contradiction: $is_contradiction,
    contradiction_reason: $contradiction_reason
}]->(b:Claim {claim_id: $b_id})
```

→ Une relation typée par paire (au lieu de N relations ad-hoc CONTRADICTS / REFINES / QUALIFIES). La requête de "vraies contradictions" devient déterministe :

```cypher
MATCH (a:Claim)-[r:LOGICAL_RELATION]->(b:Claim)
WHERE r.is_contradiction = true
  AND r.confidence >= 0.85
RETURN a, b, r
```

#### 3.F — Avantages V2 vs V1

| Critère | V1 (matrice incompat.) | V2 (LLM-as-extractor) |
|---|---|---|
| LLM rôle | Juge boolean | Extracteur multi-classe |
| Décision contradiction | LLM | Déterministe |
| Stabilité dans le temps | Faible | Élevée |
| Auditabilité | Reasoning LLM seulement | Reasoning + règle formalisée |
| Composabilité | Non | Oui (chaînage de relations) |
| Sortie produit | "X contradictions candidate" | "X EXCEPTIONS, Y SUBSETS, Z CONFLICTS, ..." |
| Coût LLM | 1 call par paire | 1 call par paire (idem) |

**Effort estimé Phase 3 V2 : 5-7 jours** (sur Domain Pack aerospace_compliance, avec Tier 1+2 du document role).

#### 3.G — Affinements V3 (post 2nd cycle ChatGPT)

##### 3.G.1 — Relation strength en plus du type

Pour chaque relation classifiée, capturer une **force** en plus du type :

```python
class RelationStrength(Enum):
    STRONG    = "strong"      # logique claire, peu d'ambiguïté
    WEAK      = "weak"         # interprétatif, dépend du contexte
    UNCERTAIN = "uncertain"    # borderline, abstention possible
```

Exemple : `SUBSET strict` (intervalle [1ps, 1ns] dans [0, 0.25s]) = `STRONG`. `SUBSET interprétatif` ("validation > 50M€" vs "validation grandes contreparties") = `WEAK`.

**Bénéfice** : permet UI/filtrage différencié (afficher strong par défaut, weak en option, uncertain en review).

##### 3.G.2 — Confidence threshold différencié par type

Une seule barrière de confidence pour tous les types est sous-optimale. Les types ne sont pas équivalents en difficulté d'extraction :

```python
CONFIDENCE_THRESHOLDS = {
    LogicalRelation.CONFLICT:      0.90,  # le plus risqué — faux conflict = pire cas produit
    LogicalRelation.EXCEPTION:     0.80,
    LogicalRelation.SUBSET:        0.70,
    LogicalRelation.SUPERSET:      0.70,
    LogicalRelation.EQUIVALENT:    0.75,
    LogicalRelation.OVERLAP:       0.65,
    LogicalRelation.DISJOINT:      0.60,  # facile : scopes orthogonaux
    LogicalRelation.DEFINITION_OF: 0.60,  # facile : signal lexical fort
    LogicalRelation.UNRELATED:     0.50,  # absorption, pas confiance
}
```

Une relation extraite avec confidence en-dessous du seuil de son type est rétrogradée en `strength=UNCERTAIN`, pas rejetée totalement.

##### 3.G.3 — Skip persistence sur UNRELATED

**Règle critique** : si la relation classifiée est `UNRELATED`, **ne PAS persister l'arête** dans le KG.

```python
def persist_relation(rel_output, claim_a, claim_b):
    if rel_output.relation == LogicalRelation.UNRELATED:
        return  # SKIP — pollue le KG sans valeur
    
    if rel_output.confidence < CONFIDENCE_THRESHOLDS[rel_output.relation]:
        rel_output.strength = RelationStrength.UNCERTAIN  # downgraded, pas skipped
    
    persist_to_neo4j(rel_output)
```

Sinon, sur 29 525 paires analysées dont ~80 % UNRELATED, le KG accumule 23 000 arêtes inutiles. Bruit pur.

##### 3.G.4 — Composabilité / transitivité (game changer)

> Promu de "optionnel" (V2) à **feature de premier plan** (V3) suite au challenge ChatGPT.

Une fois les relations typées persistées, certaines sont **transitives**. On peut dériver des relations implicites par parcours du graph :

| Règle | Inférence | Confidence |
|---|---|---|
| `A SUBSET B` ∧ `B SUBSET C` | `A SUBSET C` | min(c_AB, c_BC) × 0.9 (discount) |
| `A EXCEPTION B` ∧ `B SUBSET C` | `A EXCEPTION C` (l'exception remonte) | min × 0.85 |
| `A DEFINITION_OF B` ∧ `B DEFINITION_OF C` | `A DEFINITION_OF C` | min × 0.95 |
| `A CONFLICT B` ∧ `A EQUIVALENT A'` | `A' CONFLICT B` (conflit hérite) | min × 0.9 |
| `A DISJOINT B` ∧ `B SUBSET C` | (rien — A peut être SUBSET, OVERLAP, ou DISJOINT vs C) | — |

**Implémentation** : tâche batch périodique (post-classifier) qui matérialise les relations transitives **bornées à 3 hops** (au-delà, le discount cumulatif rend la confidence inutilisable).

**Garde-fous critiques** :
- Borne le nombre de hops (≤ 3) sinon explosion combinatoire
- Marquer les relations dérivées avec `derived: true` et `derivation_path: [edge_id_1, edge_id_2]` pour traçabilité
- Recalculer après chaque batch d'imports nouveaux (incrémental, pas full)

**Pourquoi c'est un game changer** :
- Le KG passe de **graph de faits** (ce que le LLM a vu) à **graph de raisonnement** (ce qui en découle)
- Permet la navigation : *"toutes les claims qui sont des cas particuliers de la définition X"*
- Permet la compression : si 100 EXCEPTIONs convergent vers la même règle générale via SUBSET chains, on les regroupe
- Permet l'explication : *"cette claim est en conflit avec celle-ci PARCE QUE [path: ...]"*

##### 3.G.5 — Stratégie face à l'ambiguïté typologique

**Risque identifié V3** : certains cas réels sont intrinsèquement ambigus entre EXCEPTION / OVERLAP / UNRELATED. Le classifier sera instable sur ces cas.

Stratégies cumulatives :

1. **Multi-label avec primary** : retourner top-2 types avec scores. Le primary (max confidence) est persisté, le secondary est en metadata pour audit.

```python
{
  "relation": "exception",      # primary
  "confidence": 0.62,
  "strength": "weak",
  "alternatives": [{"type": "overlap", "confidence": 0.31}],
  "reasoning": "Could be exception if AAA constraint is exemption from validation rule, or overlap if both rules apply concurrently"
}
```

2. **Confidence floor de l'abstention** : si max < 0.55, downgrader à UNRELATED + skip.

3. **Validation humaine ciblée** : router les `strength=UNCERTAIN` + `top-2 within 0.15` vers un workflow d'annotation (UI dédiée).

**Effort additionnel V3 : +2-3 jours** sur Phase 3 V2 (donc **Phase 3 V3 = 7-10 jours total**).

### Phase 4 — Defeasible Logic Graph (R&D, optionnel mais structurant)

Le pivot V2 (Phase 3) résout 80 % du problème en passant à *LLM-as-extractor + décision déterministe*. Mais le LLM reste impliqué dans la classification. Pour atteindre une auditabilité **strictement formelle** (compliance AI Act art. 12 dans son interprétation la plus stricte, où le raisonnement doit être reproductible sans ML), il faut formaliser la sortie en **Defeasible Deontic Logic** (DDL).

Persistance de la structure DDL dans le KG : pour chaque Claim, ajouter `ddl_form` avec opérateur ([O]/[P]/[F]/[DEF]), scope, conditions, exceptions. Construire `SUPERSEDES` relations entre règles spécifiques et règles générales.

Détection des relations = parcours du graph DDL avec moteur d'inférence défaisable. **Aucun LLM dans la boucle critique**. Déterministe. Auditable. Reproductible.

**Effort estimé : 30-60 jours**. Justifié uniquement pour cas d'usage où l'auditabilité formelle est une exigence absolue (régulateurs, juridictions critiques).

**Note V2** : la Phase 3 V2 produit déjà un graph de relations logiques typées qui constitue **80 % du chemin vers DDL**. La Phase 4 est principalement la formalisation des opérateurs déontiques + le moteur d'inférence défaisable. C'est moins une refonte qu'une **maturation**.

---

## 4 bis. Temporalité comme dimension intrinsèque du fait (V3.2 / V3.2.1)

> **Note V3.2.1** : suite au feedback ChatGPT, la temporalité est désormais traitée comme **dimension fondatrice** intégrée dès Phase 0 (extraction) et Phase 2 (gate), pas comme phase tardive. Cette section décrit la **vision conceptuelle** ; les modifications concrètes sont distribuées sur Phase 0, Phase 2, Phase 3 et la nouvelle Phase 4 (Retrieval Layer).

### Le constat différenciateur

Dans la **majorité des frameworks RAG** (LangChain, LlamaIndex, Microsoft GraphRAG, LightRAG, etc.) :
- La date d'un document est une **métadonnée**
- Elle apparaît parfois dans le filtrage (où ?, quand ?), rarement dans la génération
- L'**embedding est a-temporel** : 2 documents qui se contredisent à 2 dates différentes ont des embeddings très proches et sont retrouvés ensemble, sans distinction temporelle

Dans un **système qui vise le jugement** (compliance officer, regulatory specialist, product manager, medical reviewer) :
- *"La procédure X valide les commandes > 10K€"* n'est pas une affirmation universelle
- C'est une affirmation **vraie dans une fenêtre temporelle**, qui peut être remplacée, contredite, ou nuancée par une autre affirmation dans une fenêtre ultérieure
- La question *"que dit la réglementation sur X ?"* n'a pas de sens sans le **at-time** : *"que disait la réglementation sur X au 1er janvier 2024 ?"* vs *"que dit-elle aujourd'hui ?"*

V3.2 traite la temporalité comme **dimension de premier rang** du Claim, pas comme métadonnée annexe.

### 4 bis.A — Les 3 timestamps par fait

Chaque `Claim` extrait porte **trois timestamps distincts** :

| Timestamp | Sémantique | Source |
|---|---|---|
| **`publication_date`** | Date de publication du document source | Métadonnée document (Docling, parsing PDF) |
| **`validity_start`** | Date d'entrée en vigueur du fait | Extrait du texte ou inféré par le `ApplicabilityFrame` |
| **`validity_end`** | Date de fin de validité (NULL = encore valide) | Auto-set par les relations `SUPERSEDES` |
| **`ingestion_date`** | Date d'ingestion dans OSMOSIS | Pipeline OSMOSIS (déjà existant : `created_at`) |

**Exemple concret** :
```
Document : "Annex to ED Decision 2023/021/R" (publié 2023-09-21)
Texte extrait : "This Amendment 28 of CS-25 enters into force on 1 January 2024
                 and supersedes Amendment 27 from that date."

Claim extrait :
{
  text: "Pulse duration ≤ 0.25 seconds for pulsed laser definition",
  publication_date: 2023-09-21,
  validity_start: 2024-01-01,
  validity_end: null,          // encore valide à ce jour
  ingestion_date: 2026-04-28,
  temporal_axis_source: "document_metadata + extracted_from_text"
}
```

**Quand SUPERSEDES est créé**, le moteur **met automatiquement à jour le `validity_end`** de la claim ancienne :
```cypher
MATCH (newer:Claim)-[r:LOGICAL_RELATION {type: 'supersedes'}]->(older:Claim)
WHERE r.confidence >= 0.85 AND r.effective_date_a IS NOT NULL
SET older.validity_end = r.effective_date_a,
    older.superseded_by = newer.claim_id
```

→ Le KG **encode la durée de validité** de chaque fait, pas seulement la relation entre faits.

### 4 bis.B — Sources d'extraction temporelle

Pour chaque timestamp, OSMOSIS dispose de plusieurs sources cascadées (`temporal_axis_source` traçable) :

```
TIER 1 — Métadonnée du document (Docling)
   PDF metadata, header "Effective Date: ...", "Date of Issue: ..."
   Confidence: 0.95
   
TIER 2 — Extraction depuis le texte (regex + LLM)
   "This Amendment enters into force on 1 January 2024"
   "Effective from YYYY-MM-DD"
   "Applicable until ..."
   Confidence: 0.80-0.90
   
TIER 3 — Inférence depuis le filename / titre / structure
   "amdt_28" → Amendment 28 → release_id mapping → 2024
   "RCP_v3.2" → version 3.2
   Confidence: 0.70

TIER 4 — Inférence depuis ApplicabilityFrame déjà extrait (Phase 0)
   release_id, edition, version captured during ContextExtraction
   Confidence: 0.85
   
TIER 5 — Default = ingestion_date seul
   Si toutes les sources échouent, on a au moins l'ingestion_date.
   Le claim est marqué validity_start=ingestion_date, à valider humainement.
   Confidence: 0.30 (low — flag pour review)
```

### 4 bis.C — Retrieval temporellement aware

C'est l'upgrade le plus visible côté produit. Aujourd'hui le retrieval OSMOSIS fait :
```
query → embedding → Qdrant top-K → re-rank → context for LLM
```

V3.2 ajoute un **paramètre `as_of_date`** dans la requête :
```python
def retrieve(query: str, as_of_date: datetime|None = None, ...) -> list[Claim]:
    """
    Retrieve claims relevant to the query, filtered/weighted by temporal context.
    
    as_of_date=None : pas de filtre temporel (comportement legacy)
    as_of_date=2024-06-15 : ne ramène que les claims valides à cette date
                            + boost les claims les plus "à jour" pour cette date
    """
```

3 modes au choix :

#### Mode 1 — Snapshot temporel strict
```python
filters = {
    "validity_start__lte": as_of_date,
    "validity_end__gte_or_null": as_of_date
}
```
*"Voici ce qui était en vigueur exactement au 15 juin 2024"*. Pour audit historique.

#### Mode 2 — Pondération temporelle
Score augmenté pour les claims les plus proches dans le temps de `as_of_date`, sans exclure les autres.
```python
temporal_score = 1.0 if validity_window_contains(as_of_date) else 0.5
final_score = 0.7 * cosine_similarity + 0.3 * temporal_score
```
*"Voici ce qui était pertinent vers juin 2024, en privilégiant les règles en vigueur"*. Pour Q&A généraliste.

#### Mode 3 — Diff temporel
Compare l'état du corpus à 2 dates et retourne les changements.
```python
def diff(query: str, date_before: datetime, date_after: datetime) -> DiffResult:
    """
    Retourne ce qui a changé entre date_before et date_after sur le sujet query.
    Exploite les relations SUPERSEDES + EVOLVES_FROM.
    """
```
*"Qu'est-ce qui a changé entre l'amdt 27 (2022) et l'amdt 28 (2024) sur la définition de Pulsed Laser ?"*. Pour delta-analysis réglementaire.

### 4 bis.D — Génération temporellement consciente

Le LLM de synthèse reçoit les claims avec leur fenêtre de validité explicite dans le contexte :

```
Context for LLM:
- Claim 1 [valid 2024-01-01 to NOW] : "Pulsed laser ≤ 0.25 seconds"  
- Claim 2 [valid 2018-01-01 to 2023-12-31] : "Pulsed laser ≤ 0.5 seconds (superseded)"

User question: "Quelle est la définition de pulsed laser ?"
LLM response: "Selon la définition actuellement en vigueur (depuis le 1er janvier 2024 
              avec l'Amendment 28 de CS-25), un 'pulsed laser' est défini comme ayant 
              une pulse duration ≤ 0.25 seconds. Cette définition a remplacé celle de 
              l'Amendment 27 (en vigueur 2018-2023) qui spécifiait ≤ 0.5 seconds."
```

→ Le LLM **ne peut plus halluciner** une réponse atemporelle si les sources ont des fenêtres de validité explicites dans son contexte.

### 4 bis.E — Implémentation : modifications structurantes (réparties V3.2.1)

| Composant | Modification | Phase qui la porte |
|---|---|---|
| **Schéma Claim Neo4j** | Ajout `publication_date`, `validity_start`, `validity_end`, `ingestion_date`, `temporal_axis_source`, `superseded_by` | Phase 0.B |
| **Schéma Qdrant payload** | Ajout `validity_start`, `validity_end`, `temporal_axis_source` (filtrage natif Qdrant) | Phase 0.B |
| **Pipeline ClaimFirst Phase 0** | Extraction des 3 timestamps (cascade 5-tiers) | Phase 0.B |
| **Pipeline pre-LLM Phase 2** | Gate temporel + alignment fenêtre validité avant classifier | Phase 2 |
| **Classifier Phase 3** | Inputs temporels structurés dans prompt LLM (fenêtres validité, scope) | Phase 3 |
| **Pipeline post-classifier** | Auto-set `validity_end` quand SUPERSEDES créé (déterministe) | Phase 3 |
| **API `/search`** | Paramètre `as_of_date`, modes `snapshot`/`weighted`/`diff` | Phase 4 |
| **Synthesis LLM** | Prompt enrichi avec fenêtres de validité dans le context | Phase 4 |

**Effort total temporalité** : **15-20 jours** distribués sur Phase 0 (3-4j), Phase 2 (2-3j), Phase 3 (1-2j), Phase 4 (5-7j) — au lieu de 8-12j concentré en Phase 4 bis tardive (V3.2).

L'effort total est légèrement supérieur (+5-8j) mais la **dette architecturale est éliminée** : Phase 2/3 ne fonctionnent plus dans une logique a-temporelle qu'on viendrait corriger plus tard.

### 4 bis.F — Avantage compétitif

Ce qui rend OSMOSIS différenciant à partir de V3.2 :

| Capacité | LangChain | LlamaIndex | Microsoft GraphRAG | OSMOSIS V3.2 |
|---|---|---|---|---|
| Embedding sémantique | ✅ | ✅ | ✅ | ✅ |
| Knowledge Graph | ⚠️ via plugin | ⚠️ via plugin | ✅ | ✅ |
| Détection de contradictions | ❌ | ❌ | ❌ | ✅ |
| Typologie de relations logiques | ❌ | ❌ | ❌ | ✅ (11 types) |
| **Temporal validity layer** (fenêtre de validité par fait) | ❌ | ❌ | ❌ | ✅ |
| **Temporal-aware retrieval / scoring** | ❌ | ❌ | ❌ | ✅ |
| **3 timestamps par fait** | ❌ | ❌ | ❌ | ✅ |
| **Retrieval `as_of_date`** | ❌ via metadata filter | ❌ via metadata filter | ❌ | ✅ first-class |
| **Diff temporel cross-doc** | ❌ | ❌ | ❌ | ✅ |
| **Auto-update validity_end via SUPERSEDES** | ❌ | ❌ | ❌ | ✅ |
| **Auditabilité fenêtre de validité** | ❌ | ❌ | ❌ | ✅ |

**Note de précision** : ce n'est pas l'embedding qui devient temporel (un embedding reste un vecteur dans un espace sémantique). C'est la **couche de retrieval et de scoring** qui devient temporally-aware grâce au `temporal validity layer` posé sur chaque Claim. La distinction matters : sur-vendre une "temporalité dans l'embedding" serait techniquement faux et fragiliserait le positionnement.

→ Aucun framework RAG mainstream ne traite la temporalité comme dimension de premier rang. **C'est un positionnement produit unique pour OSMOSIS**, particulièrement pour les domaines où la valeur business dépend de la fenêtre temporelle (compliance, regulatory, medical, legal).

---

## 4 ter. Trois axes orthogonaux : Scope, Temporalité, Lifecycle (V3.3)

> **Précision V3.3 issue d'une question architecturale clé** : la temporalité d'un fait n'est pas la même chose que le statut opérationnel d'un produit, ni que son scope d'applicabilité. V3.2 confondait ces 3 notions dans certains exemples (notamment SAP S/4HANA). V3.3 sépare proprement.

### Les 3 axes orthogonaux

Chaque Claim porte trois informations distinctes, qui répondent à 3 questions différentes :

| Axe | Question | Variabilité | Source |
|---|---|---|---|
| **Scope** (`ApplicabilityFrame`) | *"À quoi/qui le fait s'applique ?"* | **invariant** dans le temps | extraction Phase 0.A |
| **Temporalité** (`factual_validity`) | *"Quand le fait est-il vrai ?"* | **évolutive** (peut être ajustée par relations) | extraction Phase 0.B + post-classifier |
| **Lifecycle status** | *"Quel est l'état opérationnel du sujet ?"* | métadonnée informative | extraction Phase 0.C |

Ces 3 axes ne se substituent pas mutuellement. Un claim peut avoir :
- Un scope précis (S/4HANA version 1809)
- Une temporalité large (le fait est vrai depuis la release et le restera) 
- Un lifecycle EOL (le produit n'est plus supporté commercialement)

→ Les 3 informations coexistent et permettent des filtrages indépendants côté retrieval.

### Cas pédagogique : pourquoi version SAP ≠ temporalité (correction d'un contre-exemple V3.2)

Mon exemple S/4HANA initial confondait 2 notions :
- *"S/4HANA 1809 a une date de release et une date d'EOL → donc validity_window"*

C'était **incorrect**. Les claims sur S/4HANA 1809 restent **vrais et applicables** indéfiniment dans leur scope de version, même après EOL :

> Si un utilisateur demande en 2026 *"comment configurer X dans S/4HANA 1809 ?"*, la doc 1809 doit être ramenée. Le claim *"dans 1809, configurer Y de telle manière"* est **vrai en 2026** comme il l'était en 2018. L'EOL produit n'invalide pas la véracité descriptive du claim.

→ **La version 1809 est un axe de scope** (`ApplicabilityFrame.version="1809"`), pas un axe temporel. La temporalité de validité reste `[release_date, NULL]` (toujours vrai dans le scope 1809). Le lifecycle EOL est metadata séparée.

### Tableau de mapping cross-domain

| Domaine | Axe Scope (ApplicabilityFrame) | Axe Temporalité (factual_validity) | Axe Lifecycle |
|---|---|---|---|
| **IT / Tech / SaaS** | version produit, env, région cloud, OS | release date, breaking change | ACTIVE / BETA / DEPRECATED / EOL |
| **Lifescience / Biotech** | organisme, concentration, espèce, équipement | publication study date, période validité protocole | validated / preliminary / withdrawn |
| **Médical / Pharma** | indication, population (âge, comorbidité), dosage, voie | RCP version, AMM date, sunset | commercialized / discontinued / **recalled** / suspended |
| **Legal** | juridiction, domaine droit, type d'acte | entrée en vigueur, abrogation | in_force / partially_amended / repealed |
| **Réglementaire** (CS-25, Reg EU) | aircraft_type, ECCN code, region | effective date, sunset clause | in_force / superseded |
| **Académique** | discipline, méthodologie, dataset | publication date, correction | published / **retracted** / superseded |
| **Business / SOPs** | BU, géographie, segment | effective date, sunset | active / superseded / rescinded |
| **Manufacturing** | gamme produit, ligne fab, certification | date homologation, retrait | qualified / under_review / decommissioned |

→ **Les 3 axes s'appliquent universellement.** Aucun domaine ne nécessite un 4e axe.

### Domain-agnostic vs domain-specific values

Les **axes sont universels**, leurs **valeurs varient par domaine**. La typologie canonique LifecycleStatus permet de mapper toutes les valeurs natives vers une logique cross-domain :

```python
class LifecycleStatus(Enum):
    ACTIVE       = "active"        # opérationnel, en vigueur, citable
    PROVISIONAL  = "provisional"   # beta, draft, clinical_trial, preliminary
    DEPRECATED   = "deprecated"    # encore valide mais migration recommandée
    RETIRED      = "retired"       # retiré normalement (EOL, abrogated, discontinued)
    WITHDRAWN    = "withdrawn"     # retiré pour cause de problème (RECALLED, RETRACTED) ⚠️
    UNKNOWN      = "unknown"       # non déterminé
```

Mapping des valeurs natives via Domain Packs (extrait, voir `domain_packs/<pack>/lifecycle_mapping.yaml`) :

```yaml
# medical
ACTIVE:      ["commercialized", "available", "approved"]
WITHDRAWN:   ["recalled", "safety_alert_class_1"]    # critique médical

# legal
ACTIVE:      ["in_force", "promulgated"]
RETIRED:     ["repealed", "abrogated", "expired"]

# api_documentation (IT)
ACTIVE:      ["stable", "ga"]
PROVISIONAL: ["beta", "alpha", "preview", "experimental"]
RETIRED:     ["end_of_life", "sunset"]

# academic
ACTIVE:      ["published", "peer_reviewed"]
WITHDRAWN:   ["retracted"]                           # critique scientifique
```

**Bénéfices** :
- Code OSMOSIS reste 100% domain-agnostic (manipule `LifecycleStatus.WITHDRAWN`)
- Sémantique préservée cross-domain (un médicament rappelé et un papier rétracté = même signal "ne pas utiliser")
- Filtres cross-domain fonctionnent (`WHERE lifecycle_status = 'withdrawn'` ramène recalls + retractions selon le corpus)
- Les Domain Packs encapsulent la traduction native ↔ canonique

### Provenance immutable vs inférence mutable (clé de cohérence)

Pour résoudre le paradoxe *"on s'interdit de modifier un claim, mais sa temporalité doit pouvoir évoluer avec les relations cross-doc"*, distinction **provenance vs inférence** :

| Aspect du Claim | Mutabilité | Origine |
|---|---|---|
| `text`, `verbatim_quote`, `passage_id`, `doc_id`, `page_no` | ❌ **immutable** | provenance documentaire |
| `document_validity_start/end` | ❌ **immutable** | provenance (hérité du DocumentContext parent) |
| `applicability_frame` (scope) | ❌ **immutable** | provenance (extrait à l'ingestion) |
| `lifecycle_status_at_publication` | ❌ **immutable** | snapshot au moment de la publication |
| `factual_validity_start/end` | ✅ **mutable** | inférence (ajustée par SUPERSEDES, REAFFIRMS, etc.) |
| `factual_validity_audit_log` | ✅ append-only | trace toutes les modifications de factual_validity |
| `lifecycle_status_current` | ✅ mutable | mis à jour par re-ingestion ou observation externe |

Le **claim source** n'est jamais modifié. C'est seulement la **vue inférée** que le KG maintient sur sa validité factuelle qui évolue. C'est un pattern Git-like : le commit ne change pas, ses relations (HEAD, branches) évoluent.

### Cascade 5-tiers révisée pour factual_validity

```
TIER 1 — Verbatim explicite dans le claim/passage
   "valid until 2025-12-31", "applicable from 2024-01-01"
   Confidence: 0.95

TIER 2 — Section / sous-section context
   "Annex IV applicable from 1 January 2024"
   Confidence: 0.85

TIER 3 — Inférence depuis le statut du fait dans le document
   Modal verbs + tense detection
   Confidence: 0.70

TIER 4 — DEFAULT : héritage de document_validity
   Si rien d'autre, factual_validity = document_validity du doc parent
   Confidence: 0.60

TIER 5 — POST-IMPORT : ajustement par relations cross-doc
   SUPERSEDES créé : auto-set factual_validity_end de l'ancien
   REAFFIRMS créé : auto-extend factual_validity_end (ou _start)
   EVOLVES_FROM : continuité — factual_validity inchangée
   Audit log : chaque modification trace la relation source
```

### Ajout typologie : REAFFIRMS (V3.3)

Cas non couvert par V3.1 : *"L'AMC 25.1419 reste applicable sans modification dans le présent amendement"*. Ce claim étend la validité d'un fait antérieur sans le modifier ni l'invalider.

```python
class LogicalRelation(Enum):
    # ... 11 existants V3.1 ...
    REAFFIRMS = "reaffirms"  # A confirme la validité de B sans la modifier
                              # → étend factual_validity_end de B
```

| Distinction | Effet |
|---|---|
| `EVOLVES_FROM` | A est une nouvelle version de B (B reste référence historique) |
| `REAFFIRMS` | A confirme la validité de B sans changer B (B reste pleinement vivant) |
| `SUPERSEDES` | A invalide B (B obsolète) |

Effet déterministe post-classifier :
```python
if relation.type == REAFFIRMS:
    target_claim.factual_validity_end = max(
        target_claim.factual_validity_end or DATE_INFINITY,
        source_claim.document_validity_end or DATE_INFINITY
    )
    target_claim.factual_validity_audit_log.append({
        "action": "extend_via_reaffirms",
        "source": source_claim.claim_id,
        "from": old_end, "to": new_end,
        "timestamp": now()
    })
```

### Cas spéciaux à signaler

#### Cas 1 — Versions multiniveau (S/4HANA SP, hotfix)

```yaml
applicability_frame:
  product: "S/4HANA"
  version: "1809"        # axe scope principal
  support_pack: "SP12"   # axe scope secondaire (sous-version)
```

Si SP12 corrige un bug de SP05 (même version 1809), c'est un **SUPERSEDES intra-scope** (même version, sub-version différente).

#### Cas 2 — Recall médical / Retraction académique

```python
claim.lifecycle_status_current = LifecycleStatus.WITHDRAWN
claim.lifecycle_status_change_date = "2025-03-15"
claim.lifecycle_status_reason = "FDA Class I recall — contamination"
```

Effet sur retrieval : par défaut, exclure les `WITHDRAWN` du contexte LLM (sauf si la query explicite *"include withdrawn"*). Synthesis LLM peut alerter contextuellement *"Note: cette information provient d'un médicament rappelé en mars 2025"*.

#### Cas 3 — Document immutable mais lifecycle mutable

Doc S/4HANA 1809 (publié 2018) → re-ingestion en 2026 :
- Verbatim, doc_id, scope (version=1809) : inchangés ✅
- `lifecycle_status_at_publication` : ACTIVE (en 2018) — inchangé
- `lifecycle_status_current` : RETIRED (EOL en 2027 prévu, donc en 2026 = DEPRECATED) — mis à jour

Le claim n'est pas modifié, juste enrichi d'une nouvelle info externe.

---

## 5. Généralisation hors aerospace : couverture par domaine

Tableau de **couverture Tier 1 (structure documentaire)** :

| Domaine | Tier 1 | Stratégie principale |
|---|---|---|
| Legal (contrats, jurisprudence) | 80-90 % | Structure documentaire (sections rituelles) |
| Medical (RCP, guidelines, articles IMRaD) | 85-95 % | Structure + lexical (excellent fit) |
| Réglementaire (GDPR, NIST, ISO) | 90-95 % | Structure documentaire — sweet spot |
| Tech — API specs (OpenAPI, RFC) | 70-85 % | Structure + lexical |
| Tech — wikis internes | 30-50 % | Tier 2 lexical + Tier 3 LLM |
| Business — politiques / SOP | 70-85 % | Structure + lexical |
| Business — mémos, slides | 30-50 % | Tier 3 LLM ou NEUTRAL |
| Académique (papers IMRaD) | 80-90 % | Structure documentaire |
| Narratif (roman, blog post) | < 10 % | Tier 4 NEUTRAL |
| Email / Slack / forums | < 10 % | Tier 4 NEUTRAL |

**Conclusion stratégique** : OSMOSIS reste fonctionnel sur tous les domaines, mais **le gain du filtrage rhétorique est maximal sur les domaines structurés** — qui sont précisément les cas d'usage à plus haute valeur business (legal, medical, regulatory, tech specs). Pour les domaines non-structurés (Slack, blogs), la détection de contradictions formelles est rarement le besoin principal.

---

## 6. Ordre de mise en œuvre recommandé (V3.2.1 — temporalité dimension fondatrice)

> **Refonte structurelle suggérée par ChatGPT (validée)** : la temporalité n'est PAS une phase tardive (V3.2 plaçait Phase 4 bis après composabilité). Elle doit être **dimension fondatrice** intégrée à Phase 0, Phase 2 et Phase 3 dès l'origine, car le scope gate et le classifier ont besoin des fenêtres de validité pour décider correctement.

| Phase | Effort | Apport principal | Risque |
|---|---|---|---|
| **Phase 0 — Fix ApplicabilityFrame + TemporalFrame** | 7-10 j | pré-requis (scope + 3 timestamps extraits ensemble lors du parsing) | faible |
| **Phase 1 — Pair selection multi-signal** | 3-5 j | -50 % paires bruyantes en amont (4 signaux KG déjà calculés) | faible |
| **Phase 2 — Scope & Temporal Gate** | 5-7 j | -60 à -70 % faux positifs via filtrage scope + temporel (DISJOINT temporel détecté avant LLM) | faible |
| **Phase 3 V3.2 — Logical Relation Classifier (avec inputs temporels)** | 8-11 j | LLM-as-extractor + typologie 11-types + strength + thresholds par type + skip UNRELATED + fenêtres validité dans le prompt ⭐ | moyen |
| **Phase 3 bis — Composabilité transitive** | 3-5 j | inférence relations dérivées (SUBSET / SUPERSEDES chains) — game changer navigation | moyen |
| **Phase 4 — Temporal Retrieval Layer** | 5-7 j | API `as_of_date` + 3 modes (snapshot/weighted/diff) + synthesis temporellement consciente | moyen |
| **Phase 5 — DDL graph (R&D)** | 30-60 j | auditabilité formelle stricte (regulators-grade) | élevé |

### Changement par rapport à V3.2

- **Phase 0 enrichie** (5-7j → 7-10j) : extraction des 3 timestamps EN MÊME TEMPS que le scope (cascade 5-tiers déjà décrite §4 bis.B)
- **Phase 2 enrichie** (3-5j → 5-7j) : "Scope Gate" → "Scope & Temporal Gate" — détection auto des cas où les claims sont sur même scope mais à des dates incompatibles (= SUPERSEDES candidats, pas envoyés au LLM comme CONFLICT)
- **Phase 3 enrichie** : le classifier reçoit les fenêtres de validité comme **inputs structurés** (pas juste comme metadata). Permet distinction déterministe SUPERSEDES vs CONFLICT vs EXCEPTION
- **Phase 4 simplifiée** (8-12j → 5-7j) : ne reste que le retrieval layer + API `as_of_date` + synthesis. L'extraction temporelle est désormais en Phase 0
- **Phase 4 anciennement = Phase 5** : DDL R&D, inchangé

### Effort total

| Cible | V3.2 | V3.2.1 | Δ |
|---|---|---|---|
| Total Phases 0-4 | 30-43 j | 31-45 j | +1-2 j (équivalent) |
| Cohérence architecturale | 6/10 | 9/10 | meilleure |
| Risque sur Phase 2/3 sans temporal | élevé | éliminé | gain net |

L'effort total est quasi inchangé mais la **distribution est plus saine** : on n'a plus de phase tardive qui devrait modifier rétroactivement les comportements de phases antérieures.

### Sprints actualisés V3.2.1

- **Sprint 1 (3-4 semaines)** : Phase 0 V3.2.1 (Applicability + Temporal) + Phase 1
- **Sprint 2 (3 semaines)** : Phase 2 (Scope & Temporal Gate) + Phase 3 V3.2 sur aerospace_compliance
- **Sprint 3 (2 semaines)** : Phase 3 bis composabilité + Phase 4 Retrieval Layer
- **Sprint 4 (1-2 semaines)** : validation, benchmarks, golden set, audit
- Phase 5 DDL : différée post-MVP

**Sprints estimés** :
- **Sprint 1 (2-3 semaines)** : Phase 0 + Phase 1
- **Sprint 2 (2-3 semaines)** : Phase 2 + Phase 3 V2 sur aerospace_compliance
- **Sprint 3 (1-2 semaines)** : validation — mesurer precision/recall sur un échantillon humain validé du corpus actuel + tests par domaine
- **Phase 4 différée** post-MVP, déclenchée seulement par exigence client réglementaire forte

**Cible mesurable post-Sprint 2** :
- Passer de ~16-30 % precision (mesure LegalWiz pairwise) à **70-80 % precision** sur les CONTRADICTS véritables (relation=CONFLICT + scope_overlapping + confidence ≥ 0.85), sans dégrader le recall des vraies contradictions.
- Produire en sortie une **vue typée** : N CONFLICTS, M EXCEPTIONS, K SUBSETS, J DEFINITION_OF — pas juste une liste plate.

**Indicateur produit** : le compliance officer doit pouvoir répondre, en se basant sur la sortie OSMOSIS :
- *"Combien d'exceptions couvre ce règlement ?"* → query SUBSET/EXCEPTION
- *"Quelles sont les vraies contradictions à arbitrer ?"* → query CONFLICT confirmé
- *"Quels termes sont définis dans ce corpus ?"* → query DEFINITION_OF
- *"Cette nouvelle clause crée-t-elle des conflits avec l'existant ?"* → diff incrémental sur les CONFLICTs

C'est ce passage de *"liste de contradictions à valider"* à *"carte de relations logiques navigable"* qui constitue le saut de valeur produit.

---

## 7. Ce que cette architecture **n'est pas**

- **Pas un patch** : c'est une refonte structurelle de la pipeline (LLM-as-extractor + décision déterministe)
- **Pas un ajout LLM-only** : la majorité du gain vient de signaux déterministes (structure documentaire, scope, KG existant) ; le LLM est juste mieux utilisé
- **Pas une dépendance à un nouveau parser ML lourd** : on exploite ce que Docling extrait déjà
- **Pas un changement du modèle d'extraction** : ClaimFirst (Qwen2.5-14B) reste tel quel
- **Pas une remise en cause du KG** : on ajoute des propriétés et une typologie de relations, pas de schéma fondamental
- **Pas une élimination du LLM** : V2 utilise toujours le LLM, mais comme **classifier multi-classe**, pas comme juge boolean

---

## 8. Risques identifiés (V3)

| Risque | Probabilité | Mitigation |
|---|---|---|
| ApplicabilityFrame trop fragile pour scope gate | Moyenne (déjà observé) | Phase 0 dédiée, monitoring per-doc |
| Domain Packs role_mapping incomplet pour un nouveau domaine | Élevée si nouveau domaine | Tier 3 LLM fallback |
| **Explosion UNRELATED (~80 % des paires post-Phase 1+2)** | Élevée | **Skip persistence (§3.G.3)** + Phase 1 réduit drastiquement les paires en amont |
| **Ambiguïté typologique (EXCEPTION vs OVERLAP vs UNRELATED selon interprétation)** | Élevée | **Multi-label + abstention + strength UNCERTAIN (§3.G.5)** |
| **Confidence threshold unique inadapté aux 9 types** | Élevée | **Thresholds différenciés par type (§3.G.2)** : CONFLICT 0.90, SUBSET 0.70, ... |
| **Faux CONFLICT non filtrés (pire cas produit)** | Moyenne | Threshold CONFLICT le plus strict (0.90) + scope_overlap obligatoire |
| Pair selection multi-signal trop générante | Moyenne | Tunable thresholds, A/B test |
| Coût LLM Phase 3 V3 (1 call par paire ~250 tokens output structuré) | Faible-Moyen | Filtrage Phase 1+2 réduit les paires de 60-70 %, skip UNRELATED en post |
| **Explosion combinatoire transitivité** | Moyenne | **Borne hops ≤ 3 + discount cumulatif + recompute incrémental** (§3.G.4) |
| Phase 4 DDL trop coûteuse en LLM | Élevée | Différer, considérer comme R&D |
| Migration des 10 289 relations existantes vers nouveau schéma | Moyenne | Stratégie graduelle : co-existence pendant transition, re-classifier à la demande |

---

## 8 ter. Validation de non-régression sur cas d'usage historiques (V3.1)

Préoccupation légitime : un changement de paradigme ne doit PAS dégrader les capacités de réponse aux questions concrètes que le système était conçu pour traiter. Vérification systématique :

### Cas d'usage 1 — Versioning produit / SaaS

> Question utilisateur : *"Le produit X utilise la solution B uniquement depuis la version Z"*

| Étape | V1 (legacy) | V3.1 (cible) |
|---|---|---|
| Détection 2 claims sur même produit X | OK (cosine + entity match) | OK (multi-signal pair selection) |
| Classification de la relation entre les 2 claims | `CONTRADICTS` (faux positif) | `SUPERSEDES` ou `EVOLVES_FROM` (typé) |
| Capture de la version où le changement intervient | Non (perdu dans le bruit) | Oui (`scope.version` + `effective_date` sur la relation) |
| Query produit | Difficile (filtre dans liste plate) | Direct via Cypher typé |

```cypher
// V3.1 — réponse directe à la question
MATCH (newer:Claim)-[r:LOGICAL_RELATION {type: 'supersedes'}]->(older:Claim)
WHERE newer.subject_canonical = "Produit X"
  AND newer.predicate IN ['uses', 'utilise', 'based_on']
RETURN newer.object AS new_solution,
       newer.scope.version AS since_version,
       newer.scope.effective_date AS since_date,
       older.object AS replaced_solution,
       older.scope.version AS until_version,
       r.confidence
ORDER BY newer.scope.version
```

→ ✅ **V3.1 conserve et améliore la capacité** : passe de "détection de contradiction floue" à "tracé d'évolution explicite avec versioning".

### Cas d'usage 2 — Contradiction de dosage médical

> Question utilisateur : *"Le médicament A est utilisable au dosage X mais le document RR dit que c'est le dosage Y"*

V3.1 distingue 4 sous-cas selon le scope alignment :

```cypher
// 2.A — Vraie contradiction (même indication, même population, valeurs incompatibles)
MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'conflict'}]->(b:Claim)
WHERE r.is_contradiction = true
  AND a.subject_canonical = "Medicament A"
  AND a.predicate = "dosage"
  AND r.confidence >= 0.90
RETURN a.object AS dosage_A_says,
       b.object AS dosage_B_says,
       a.doc_id, b.doc_id, r.reasoning;

// 2.B — Exception légitime (population spécifique)
MATCH (exception:Claim)-[r:LOGICAL_RELATION {type: 'exception'}]->(standard:Claim)
WHERE exception.subject_canonical = "Medicament A"
RETURN exception.object AS exception_dosage,
       exception.scope.population AS specific_population,
       standard.object AS standard_dosage;

// 2.C — Mise à jour temporelle (RCP révisé)
MATCH (newer:Claim)-[r:LOGICAL_RELATION {type: 'supersedes'}]->(older:Claim)
WHERE newer.subject_canonical = "Medicament A"
  AND newer.predicate = "dosage"
RETURN newer.object AS new_dosage,
       newer.scope.effective_date AS effective_since,
       older.object AS old_dosage,
       older.scope.effective_date AS was_effective_until;

// 2.D — Évolution sans invalidation (mise à jour incrémentale)
MATCH (current:Claim)-[r:LOGICAL_RELATION {type: 'evolves_from'}]->(previous:Claim)
WHERE current.subject_canonical = "Medicament A"
RETURN current.object, previous.object, r.reasoning;
```

→ ✅ **V3.1 distingue 4 sous-cas** au lieu de tout regrouper en CONTRADICTS, avec query Cypher dédiée pour chaque besoin produit.

### Tableau de couverture des cas d'usage historiques

| Capacité historique OSMOSIS | V1 (legacy) | V3.1 (cible) | Note |
|---|---|---|---|
| "X utilise B depuis version Z" | ❌ Perdu dans CONTRADICTS | ✅ `SUPERSEDES` typé | Versioning explicite |
| "Dosage X vs Y même contexte" | ⚠️ CONTRADICTS noyé dans le bruit | ✅ `CONFLICT is_contradiction=true` | Confidence haute |
| "Dosage X std + Y exception population" | ⚠️ CONTRADICTS faux positif | ✅ `EXCEPTION` non-contradiction | Faux positif éliminé |
| "Dosage X v1 → Y v2 (RCP révisé)" | ⚠️ CONTRADICTS temporel | ✅ `SUPERSEDES` avec dates | Évolution capturée |
| "Norme N1 abrogée par N2" | ⚠️ CONTRADICTS temporel | ✅ `SUPERSEDES` strict | Auditable |
| "Spec amendée incrémentalement" | ⚠️ CONTRADICTS chaîne | ✅ `EVOLVES_FROM` chaîne | Historique navigable |
| "Définition d'un terme dans le corpus" | ❌ Pas de détection | ✅ `DEFINITION_OF` | Nouveau |
| "Quelles sont les exceptions au règlement R ?" | ❌ Impossible (liste plate) | ✅ Query directe | Nouveau |
| "Quelles vraies contradictions ?" | ❌ Liste polluée | ✅ Filter `is_contradiction=true` + threshold | Nettoyage drastique |
| "Quelles évolutions du règlement R ?" | ❌ Impossible | ✅ Query SUPERSEDES + EVOLVES_FROM | Nouveau |

**Garantie V3.1** : aucune capacité V1 n'est perdue. Au contraire, les capacités auparavant noyées dans le bruit deviennent **explicites, queryables, et auditables**.

---

## 8 bis. Changelog V1 → V2 → V3 → V3.1 (avril 2026)

### V1 → V2 — Pivot conceptuel (1er challenge ChatGPT)
- **V1** : Détecteur de contradictions binaire avec matrice d'incompatibilité statique
- **V2** : Classifier multi-classe de relations logiques avec décision déterministe en aval

#### Modifications V2
- Phase 3 réécrite : "Document Role + matrice d'incompatibilité" → "Logical Relation Classifier (LLM-as-extractor)"
- Document Role passe de **filtre** à **input** du classifier
- Introduction d'une typologie fermée à 9 valeurs : `{SUBSET, SUPERSET, EQUIVALENT, OVERLAP, DISJOINT, CONFLICT, EXCEPTION, DEFINITION_OF, UNRELATED}`
- KG : suppression progressive des 3 relations ad-hoc (CONTRADICTS / REFINES / QUALIFIES) au profit d'une seule relation typée riche `LOGICAL_RELATION` avec attribut `type`
- Reframing produit : *"détecter contradictions"* → *"analyser la logique du corpus"*

### V2 → V3 — Affinements (2nd challenge ChatGPT)

ChatGPT V2 a accepté ses excès précédents (DDL non obligatoire, "instable" trop fort) et a poussé 2 points sous-estimés en V2 :

1. **Composabilité / transitivité** : V2 la mentionnait comme "optionnelle" — V3 la promeut à feature de premier plan (game changer : graph de faits → graph de raisonnement).
2. **Risques opérationnels du classifier** : explosion d'UNRELATED (~80 % des paires) et ambiguïté typologique sur cas réels.

#### Modifications V3 (additives à V2)
- **§3.G.1 Relation strength** : ajout de `STRONG / WEAK / UNCERTAIN` en plus du type
- **§3.G.2 Confidence threshold différencié par type** : CONFLICT 0.90, SUBSET 0.70, DEFINITION_OF 0.60, etc.
- **§3.G.3 Skip persistence sur UNRELATED** : règle critique — ne pas polluer le KG avec les ~80 % de paires sans relation pertinente
- **§3.G.4 Composabilité transitive** : nouvelle phase "Phase 3 bis" dédiée + règles d'inférence dérivées + garde-fous (≤ 3 hops, traçabilité `derived: true`)
- **§3.G.5 Stratégie ambiguïté** : multi-label avec primary + alternatives, abstention si max < 0.55, validation humaine ciblée pour UNCERTAIN

#### Effort impact V3
- Phase 3 V2 (5-7 j) → Phase 3 V3 (**7-10 j**)
- Nouvelle Phase 3 bis composabilité (**3-5 j**)
- Total Sprint 2 : passe de 2-3 semaines à **3 semaines**

### Conservé tel quel de V1/V2 (V3)
- Phase 0 (ApplicabilityFrame) inchangée
- Phase 1 (pair selection multi-signal) inchangée
- Phase 2 (scope gate) inchangée
- Cascade 4-tiers du Document Role inchangée
- État de l'art académique
- Généralisation par domaine

### V3 → V3.1 — Extension temporelle (validation cas d'usage historiques)

#### Préoccupation déclencheuse
Risque de régression sur les capacités OSMOSIS historiques : *"le produit X utilise la solution B uniquement depuis la version Z"* et *"le médicament A dosage X vs RR dosage Y"* — ces cas étaient mal traités en V1 (CONTRADICTS générique) et la V3 ne les distinguait pas explicitement (regroupés en EXCEPTION ou DISJOINT selon scope).

#### Extension V3.1
- **Typologie passe de 9 à 11 valeurs** : ajout de `SUPERSEDES` et `EVOLVES_FROM`
- Distinction systématique des 4 sous-cas dosage (CONFLICT vs EXCEPTION vs SUPERSEDES vs EVOLVES_FROM)
- Capture explicite de `effective_date` / `release_id` sur les relations temporelles
- Section **8 ter "Validation non-régression"** : tableau de couverture cas d'usage historiques avec query Cypher dédiée pour chaque

#### Effort impact V3.1
- Phase 3 V3 (7-10 j) → Phase 3 V3.1 (**8-11 j** : +1j pour les 2 types temporels)
- Pas de phase nouvelle, juste extension de la typologie + règles de classification temporelle
- Prompts du classifier mis à jour pour distinguer `CONFLICT` (logique) de `SUPERSEDES` (temporel)

### Position de convergence (V3.1)
> Claude a raison sur le pragmatisme (V2 = bon MVP).
> ChatGPT a raison sur le potentiel long terme (composabilité = différenciateur).
> Fred a raison de challenger la non-régression : **toute extension doit préserver les capacités existantes**.
>
> **V3.1 = synthèse intermédiaire** :
> - Logique relationnelle légère (MVP V2)
> - Strength + thresholds par type + skip UNRELATED (V3)
> - Composabilité transitive activée tôt (V3)
> - **Relations temporelles explicites pour versioning et mises à jour (V3.1)**
> - DDL optionnel pour cas R&D extrême (différé)

### V3.1 → V3.2 — Temporalité comme dimension intrinsèque

#### Préoccupation déclencheuse
La V3.1 a ajouté `SUPERSEDES`/`EVOLVES_FROM` comme types de relations, mais traite la temporalité **au niveau de la relation extraite**, pas du fait lui-même. Or :
- Dans un RAG classique, la date d'un document est une **métadonnée** (filtrage occasionnel, embedding a-temporel)
- Pour un système qui vise le jugement (compliance, regulatory, medical), la temporalité est une **dimension du fait** : *"X est valable au 15 juin 2024 mais a été remplacée le 1er janvier 2025"*
- **Aucun framework RAG mainstream** (LangChain, LlamaIndex, Microsoft GraphRAG) ne traite ça nativement

#### Modifications V3.2
- **3 timestamps par Claim** : `publication_date`, `validity_start`, `validity_end`, `ingestion_date` (déjà existant)
- **Cascade 5-tiers d'extraction temporelle** : metadata document → texte parsing → filename inférence → ApplicabilityFrame → default ingestion
- **Auto-update `validity_end`** déclenché par les relations `SUPERSEDES` post-classifier
- **Retrieval `as_of_date`** : nouveau paramètre dans l'API search
- **3 modes retrieval temporel** : snapshot strict / pondération / diff temporel
- **Synthesis LLM** reçoit fenêtres de validité explicites dans son contexte → ne peut plus halluciner une réponse atemporelle
- **Tableau comparatif** vs LangChain/LlamaIndex/GraphRAG → différenciateur produit unique

#### Effort impact V3.2
- Nouvelle Phase 4 bis dédiée : **8-12 jours**
- Pas de changement sur Phases 0-3 V3.1 (additif, pas modificatif)
- Total Sprint 4 ajouté : 2-3 semaines

### Position de convergence finale (V3.2)
> **Le différenciateur produit OSMOSIS n'est pas la détection de contradictions**.
> C'est l'intersection de 3 capacités qu'aucun framework mainstream ne combine :
> 1. Unit-of-proof / unit-of-reading (séparation atomique structurée)
> 2. Typologie de relations logiques (11 types + strength + composabilité)
> 3. **Temporalité comme dimension intrinsèque du fait** (3 timestamps + retrieval temporel + diff)
>
> Cette combinaison constitue un **moteur d'analyse logique de règles documentaires temporellement aware**, positionnement défendable en production-grade pour environnements régulés.

### V3.2 → V3.2.1 — Refonte architecturale temporal first-class

#### Préoccupation déclencheuse (ChatGPT 3e cycle)
- **Erreur formulation tableau** : "Temporalité dans embedding" était techniquement faux. Un embedding reste un vecteur dans un espace sémantique. C'est le **retrieval / scoring** qui devient temporally-aware grâce au **temporal validity layer** posé sur chaque Claim. Sur-vendre une "temporalité dans l'embedding" fragiliserait le positionnement technique.
- **Erreur architecturale** : V3.2 plaçait la Phase 4 bis (temporalité) APRÈS la composabilité, comme extension tardive. Or le scope gate (Phase 2) et le classifier (Phase 3) ont besoin des fenêtres de validité pour décider correctement. Sans temporalité dès Phase 0/2, ils tournent dans une logique a-temporelle qu'on viendrait corriger après — dette architecturale.

#### Modifications V3.2.1
- **Tableau comparatif corrigé** : "Temporalité dans embedding" → **"Temporal validity layer"** + **"Temporal-aware retrieval / scoring"** (2 lignes distinctes, plus précis techniquement)
- **Note technique ajoutée** : précision sur la nature de l'avantage (pas l'embedding, le layer de retrieval)
- **Phase 0 enrichie** (5-7j → **7-10j**) : "Fix ApplicabilityFrame + TemporalFrame" — extraction des 3 timestamps EN MÊME TEMPS que le scope (cascade 5-tiers)
- **Phase 2 renommée et enrichie** (3-5j → **5-7j**) : "Scope Gate" → "**Scope & Temporal Gate**" — détection auto SUPERSEDES candidats avant LLM
- **Phase 3 enrichie** : classifier reçoit fenêtres de validité comme inputs structurés
- **Phase 4 simplifiée** (8-12j → **5-7j**) : ne reste que **Temporal Retrieval Layer** (API `as_of_date` + 3 modes + synthesis temporellement consciente). L'extraction est en Phase 0
- **Renumération** : ancienne "Phase 4 bis" disparaît ; ancienne "Phase 4 DDL" devient "Phase 5 DDL"

#### Effort impact V3.2.1
- Effort total Phases 0-4 : 30-43j (V3.2) → **31-45j** (V3.2.1) — quasi-identique
- **Distribution plus saine** : pas de phase tardive qui doit modifier rétroactivement les phases antérieures
- Cohérence architecturale : 6/10 (V3.2) → **9/10** (V3.2.1)

### Position de convergence (V3.2.1)
> Claude a raison sur le pragmatisme.
> ChatGPT (1er cycle) a raison sur le pivot LLM-as-extractor.
> ChatGPT (2e cycle) a raison sur la composabilité.
> Fred a raison sur la non-régression et sur la centralité de la temporalité.
> ChatGPT (3e cycle) a raison sur la temporalité comme dimension fondatrice (pas tardive) et sur la précision technique du tableau comparatif.

### V3.2.1 → V3.3 — Séparation 3 axes orthogonaux + Provenance/Inférence + REAFFIRMS

#### Préoccupations déclencheuses (Fred, 4e cycle)

1. **Confusion conceptuelle dans l'exemple S/4HANA** : V3.2.1 traitait la version produit comme une dimension temporelle (date de release → date d'EOL = validity_window). C'était **incorrect** : un claim sur S/4HANA 1809 reste vrai en 2026, même après EOL produit. La version est un **scope**, pas une temporalité.

2. **Question architecturale** : *"Comment gérer le cas où un claim doc N+1 dit 'cette obligation reste valide en application de la précédente version' ? On modifie la temporalité du claim antérieur ? Mais on s'interdit de modifier un claim lié à un doc."*

3. **Exigence domain-agnostic** : tout nouvel axe doit s'appliquer cross-domain (IT, lifescience, medical, legal, regulatory, business, academic, manufacturing).

#### Modifications V3.3

**Séparation 3 axes orthogonaux** (§4 ter) :
- **Scope** (`ApplicabilityFrame`) : invariant temporellement, répond *"à quoi/qui le fait s'applique"*
- **Temporalité** (`factual_validity`) : évolutive, répond *"quand le fait est-il vrai"*
- **Lifecycle status** : métadonnée informative, répond *"quel état opérationnel du sujet"*

**Validation domain-agnostic** : tableau de mapping cross-domain validant que les 3 axes existent dans 8 domaines (IT, Lifescience, Medical, Legal, Regulatory, Academic, Business/SOPs, Manufacturing). Aucun domaine ne nécessite un 4e axe.

**Typologie canonique LifecycleStatus** (cross-domain) : `ACTIVE / PROVISIONAL / DEPRECATED / RETIRED / WITHDRAWN / UNKNOWN`. Chaque Domain Pack mappe ses valeurs natives ("recalled" / "retracted" / "EOL" / "abrogated") vers cette typologie canonique.

**Distinction Provenance immutable vs Inférence mutable** :
- Verbatim, doc_id, scope, document_validity = **immutable** (ne change jamais)
- factual_validity_start/end = **mutable** avec audit-trail append-only
- Le claim source n'est jamais modifié — seulement la vue inférée que le KG maintient

**Cascade 5-tiers révisée** pour `factual_validity` (verbatim → section → modal inference → document inheritance → post-import relations).

**Ajout typologie : REAFFIRMS** (12e type) pour le cas *"L'AMC 25.1419 reste applicable sans modification"*. Distinct de SUPERSEDES (invalidation) et EVOLVES_FROM (continuité avec nouvelle version).

**Cas spéciaux clarifiés** :
- Versions multi-niveau (S/4HANA SP, hotfix) → axe scope secondaire
- Recall médical / Retraction académique → `lifecycle_status_current = WITHDRAWN`
- Document immutable mais lifecycle mutable (re-ingestion enrichit le claim sans modifier sa provenance)

#### Effort impact V3.3
- Phase 0 : 7-10j → **9-12j** (extraction du 3e axe lifecycle + double validity_window)
- Phase 3 bis : ajout audit-trail factual_validity (~+2j)
- Effort total : 31-45j → **34-49j** (~+10%)
- Bénéfice : élimination des confusions entre versioning produit, temporalité réglementaire, et statut opérationnel

### Position de convergence définitive (V3.3)

> Claude a raison sur le pragmatisme.
> ChatGPT (1er–3e cycles) a raison sur le pivot LLM-as-extractor, la composabilité, la précision technique.
> Fred a raison sur la non-régression, la centralité de la temporalité, la séparation 3 axes orthogonaux, et l'exigence domain-agnostic.
>
> **V3.3 = synthèse stabilisée** :
> 1. **Unit-of-proof / unit-of-reading** (séparation atomique structurée)
> 2. **Typologie de relations logiques 12-types** + strength + thresholds + composabilité (V2/V3/V3.3)
> 3. **3 axes orthogonaux par Claim** : Scope (invariant) / Temporalité (évolutive avec audit) / Lifecycle (métadonnée)
> 4. **Provenance immutable + Inférence mutable** : pattern Git-like, claim source jamais modifié, KG maintient la vue inférée
> 5. **Domain-agnostic by design** : 3 axes universels, valeurs domain-specific via Domain Packs
>
> **Différenciateur produit unique** : aucun framework RAG mainstream (LangChain, LlamaIndex, Microsoft GraphRAG) ne combine ces 5 capacités. Positionnement défendable en production-grade pour environnements régulés.
>
> **Phase 5 DDL** différée post-MVP, justifiée uniquement par exigence client réglementaire stricte (audit formel sans ML in-the-loop).

---

## 9. Points ouverts pour discussion / 2nd opinion

1. **Domain Packs role_mapping standardisé ou libre** : standardiser le schéma `role_mapping.yaml` (rôles canoniques cross-domain : DEFINITION, RESTRICTION, OBLIGATION, EXCEPTION, GUIDANCE, EXAMPLE...) versus laisser chaque pack libre (legal vs medical vs tech ont des rôles spécifiques). Recommandation : noyau commun standardisé + extensions par domain pack.

2. **Validation humaine intermédiaire** : faut-il un workflow d'annotation manuelle (sample de 100 paires couvrant les 9 types de relations) avant de déployer Phase 3 V2 ? Coût ~1-2 jours-personne mais base de vérité solide pour calibrer les seuils de confidence et la matrice déterministe.

3. **Calibration confidence par type de relation** : les 9 types de la typologie n'ont pas tous la même fiabilité d'extraction (CONFLICT plus dur que DEFINITION_OF). Faut-il calibrer un seuil de confidence **par type** plutôt qu'un seuil unique ?

4. **Phase 4 DDL — go ou kill** : à conserver dans le roadmap (auditabilité formelle stricte AI Act, regulators-grade) ou à abandonner au profit d'une approche entièrement Phase 0+1+2+3 V2 (qui adresse 80-90 % du besoin) ? **Position V2** : conserver mais déclencher uniquement par exigence client (compliance régulateur strict), pas dans le MVP.

5. **Cross-doc vs intra-doc** : on parle ici de cross-document. Doit-on traiter les contradictions intra-document (un même doc qui se contredit) avec la même architecture ou un pipeline distinct ? La typologie V2 s'applique aux deux, mais la pair selection diffère.

6. **Performance benchmark** : sur quel échantillon mesurer le gain ? Faut-il préparer un golden-set human-annoté (50-100 paires) avant Sprint 2, multi-typé (couvrant les 9 LogicalRelations) ?

7. **Reframing produit "moteur d'analyse logique" vs "détecteur de contradictions"** : impact go-to-market. La narrative "nous détectons les contradictions" est compréhensible mais sous-vend. La narrative "moteur d'analyse logique de règles documentaires" est plus différenciante mais nécessite plus d'éducation marché. Quel reframing privilégier dans le pitch et la doc client ?

8. **Composabilité des relations** (V2 specific) : faut-il dériver des relations transitives au post-import ? *"A SUBSET B + B SUBSET C → A SUBSET C"*, *"A EXCEPTION B + B SUBSET C → A est une exception au cas particulier C de B"*. Coût computationnel mais valeur exploratoire forte (graph navigation).

9. **Backward compatibility** : on a 10 289 relations CONTRADICTS / REFINES / QUALIFIES en KG actuellement. Stratégie de migration : (a) re-classifier toutes les relations existantes via Phase 3 V2 ? (b) garder en parallèle les 2 systèmes pendant période de transition ? (c) effacer et re-générer ? Coût LLM × 10 289 ≈ ~$10-30 selon modèle.

---

## 10. Sources académiques

- *LegalWiz: A Multi-Agent Generation Framework for Contradiction Detection in Legal Documents* (oct 2025) — https://arxiv.org/abs/2510.03418
- *A Straightforward Pipeline for Targeted Entailment and Contradiction Detection* (août 2025) — https://arxiv.org/abs/2508.17127
- *From Legal Texts to Defeasible Deontic Logic via LLMs* (juin 2025) — https://arxiv.org/abs/2506.08899
- *Graph RAG for Legal Norms: A Hierarchical and Temporal Approach* (mai 2025) — https://arxiv.org/abs/2505.00039
- *Cross-Document Cross-Lingual NLI via RST-Enhanced Graph Fusion* (EMNLP 2025) — https://aclanthology.org/2025.emnlp-main.1611/
- *Towards Better Graph-based Cross-document Relation Extraction with Non-bridge Entities* (juin 2024) — https://arxiv.org/abs/2406.16529
- *Detecting contradictions from IoT protocol specification documents based on neural generated knowledge graph* (NRFCKG) — https://www.sciencedirect.com/science/article/abs/pii/S0019057823001945
- *Defeasible Reasoning* (Stanford Encyclopedia of Philosophy) — https://plato.stanford.edu/entries/reasoning-defeasible/
- *Defeasible Reasoning with Legal Rules* (Springer) — https://link.springer.com/chapter/10.1007/978-94-015-8851-5_11
- *Mann & Thompson, Rhetorical Structure Theory (1988)* — https://www.sfu.ca/rst/

---

## Annexe A — État actuel de l'infrastructure OSMOSIS pertinente

| Composant | État | Utilisation actuelle dans détection contradictions |
|---|---|---|
| `DocumentContext` | 17/17 ✅ | Non utilisé |
| `applicability_frame_json` | 17/17 ✅ | Non utilisé |
| `axis_values` (propriété) | 0/17 ❌ | Non utilisé (vide) |
| `ApplicabilityAxis` (nodes) | 1 seul global ❌ | Non utilisé |
| `CanonicalEntity` (nodes) | 2 320 ✅ | Non utilisé pour pair selection |
| `Facet` (nodes) | 68 ✅ | Non utilisé pour pair selection |
| `ClaimCluster` (nodes) | 9 622 ✅ | Utilisé partiellement (pair gen via clusters) |
| Embeddings claims | 40 196 ✅ | Utilisé (cosine pair selection) |
| `Claim.document_role` | n'existe pas ❌ | À créer (Phase 3 V2) |
| Domain Pack `role_mapping.yaml` | n'existe pas ❌ | À créer (Phase 3 V2) |
| Relations LOGICAL_RELATION typées | n'existent pas ❌ | À créer (Phase 3 V2) |
| Relations CONTRADICTS / REFINES / QUALIFIES (legacy) | 10 289 ✅ | À déprécier progressivement |
| `Claim.publication_date` / `validity_start` / `validity_end` (V3.2) | n'existent pas ❌ | À créer (Phase 4 bis) |
| Cascade extraction temporelle 5-tiers | n'existe pas ❌ | À créer (Phase 4 bis) |
| API `/search` paramètre `as_of_date` | n'existe pas ❌ | À créer (Phase 4 bis) |
| Auto-update `validity_end` via SUPERSEDES | n'existe pas ❌ | À créer (Phase 4 bis, déterministe post-classifier) |

---

## Annexe B — Glossaire

- **NLI** : Natural Language Inference. Tâche de classification entre deux phrases : entailment / neutral / contradiction.
- **RST** : Rhetorical Structure Theory. Théorie linguistique modélisant les relations rhétoriques entre unités de discours (1988).
- **EDU** : Elementary Discourse Unit. Unité de base de RST.
- **DDL** : Defeasible Deontic Logic. Logique formelle pour les obligations/permissions/prohibitions avec exceptions hiérarchiques.
- **Bridge entity** : entité partagée entre deux documents permettant de connecter des claims cross-doc.
- **Non-bridge entity** : entité co-occurrente avec un seul des deux documents mais sémantiquement liée.
- **Scope alignment** : compatibilité des contextes d'applicabilité (release, version, région, conditions) entre deux énoncés.
- **LLM-as-judge** (V1, déprécié) : pattern où le LLM tranche directement la décision finale (ex: "is contradiction Y/N").
- **LLM-as-extractor** (V2) : pattern où le LLM extrait une typologie structurée, et la décision finale est déterministe en aval.
- **Logical Relation** (V3.1) : typologie de 11 valeurs caractérisant la relation entre 2 claims (9 valeurs ensemblistes/sémantiques + 2 valeurs temporelles `SUPERSEDES`/`EVOLVES_FROM`).
- **SUPERSEDES** (V3.1) : relation temporelle où A invalide B (B obsolète). Ex : Reg 2021/821 supersedes Reg 428/2009.
- **EVOLVES_FROM** (V3.1) : relation temporelle où A prolonge/affine B sans l'invalider (B reste référence historique). Ex : CS-25 amdt 28 evolves_from amdt 27.
- **publication_date** (V3.2) : date de publication du document source du Claim (extraite de la métadonnée document).
- **validity_start** (V3.2) : date d'entrée en vigueur d'un fait (extraite du texte ou inférée).
- **validity_end** (V3.2) : date de fin de validité d'un fait (auto-set par les relations SUPERSEDES, NULL = encore valide).
- **ingestion_date** (V3.2) : date d'ingestion du fait dans OSMOSIS (audit trail).
- **as_of_date** (V3.2) : paramètre de requête API pour filtrer/pondérer le retrieval selon une date contextuelle.
- **Snapshot temporel** (V3.2) : mode retrieval qui ne retourne que les claims valides à une date donnée.
- **Diff temporel** (V3.2) : mode retrieval qui retourne les changements entre 2 dates sur un sujet.
- **REAFFIRMS** (V3.3) : relation où A confirme la validité de B sans la modifier. Étend `factual_validity_end` de B sans toucher à son verbatim. Distinct de SUPERSEDES (invalidation) et EVOLVES_FROM (continuité avec nouvelle version).
- **3 axes orthogonaux** (V3.3) : Scope (invariant) / Temporalité (évolutive) / Lifecycle status (métadonnée). Chacun répond à une question distincte sur le claim.
- **Provenance immutable** (V3.3) : aspects du Claim qui viennent du document (verbatim, doc_id, scope, document_validity) et qui ne changent JAMAIS.
- **Inférence mutable** (V3.3) : aspects du Claim qui sont inférés et peuvent évoluer (`factual_validity_start/end`, `lifecycle_status_current`), avec audit-trail append-only.
- **LifecycleStatus canonique** (V3.3) : typologie cross-domain `{ACTIVE, PROVISIONAL, DEPRECATED, RETIRED, WITHDRAWN, UNKNOWN}` mappable depuis valeurs natives Domain Pack-specific.
- **WITHDRAWN** (V3.3, état lifecycle) : retiré pour cause de problème. Médical = "recalled", académique = "retracted". Critique opérationnellement (filtre par défaut au retrieval).
- **Domain-agnostic by design** (V3.3) : les 3 axes (scope, temporalité, lifecycle) s'appliquent à tous les domaines OSMOSIS supporte. Les valeurs natives diffèrent ; les axes restent universels.
- **Document Role** : étiquette structurelle d'un passage (DEFINITION, RESTRICTION, OBLIGATION, EXCEPTION, GUIDANCE, etc.) dérivée de la structure documentaire (Tier 1) ou inférée (Tier 2/3).
- **AbandonedJobError** : statut RQ quand le heartbeat d'un worker est perdu mais le process continue.
- **REFINES / CONTRADICTS / QUALIFIES** : types de relations OSMOSIS legacy (V1) entre claims, à déprécier au profit de `LOGICAL_RELATION` typée (V2).

---

## Annexe C — Schéma cible Cypher V2

### Nodes V3.3 — Provenance immutable + Inférence mutable + 3 axes orthogonaux

```cypher
(:Claim {
    // === PROVENANCE IMMUTABLE ===
    claim_id: ...,
    text: ...,
    verbatim_quote: ...,
    doc_id: ...,
    passage_id: ...,
    page_no: ...,
    
    // V2/V3 — rôle documentaire et modal (immutable)
    document_role: 'DEFINITION'|'RESTRICTION'|'OBLIGATION'|'EXCEPTION'|...,
    document_role_source: 'tier1_structure'|'tier2_lexical'|'tier3_llm'|'tier4_unknown',
    document_role_confidence: 0.0-1.0,
    modal_operator: 'OBLIGATION'|'PERMISSION'|'PROHIBITION'|'DEFINITION'|'STATEMENT',
    
    // === AXE 1 : SCOPE (immutable) ===
    applicability_frame_json: {                    // V3.3
        // domain-specific keys (mappés via Domain Pack)
        version: "1809"|null,        // ex: SAP, IT
        product: "S/4HANA"|null,
        region: "EU"|null,            // legal/regulatory
        population: "..."|null,        // medical
        // ...
    },
    
    // === AXE 2 : TEMPORALITÉ ===
    // 2.A — Provenance (immutable, hérité du document)
    document_validity_start: '2018-09-15'|null,
    document_validity_end:   '2027-12-31'|null,    // NULL = encore en vigueur
    publication_date:        '2018-09-15'|null,
    ingestion_date:          '2026-04-28T19:51:00Z',
    
    // 2.B — Factual validity (mutable, ajusté par relations cross-doc)
    factual_validity_start:  '2018-09-15'|null,
    factual_validity_end:    null,                  // NULL = encore vrai (cas SAP) ou fini (cas reg superseded)
    factual_validity_source: 'verbatim_explicit'|'section_context'|'inferred_modal'
                           |'document_inheritance'|'cross_doc_relation',
    factual_validity_confidence: 0.0-1.0,
    factual_validity_audit_log: [                   // append-only
        {action, source_relation, from, to, timestamp}
    ],
    superseded_by: 'claim_id_xxx'|null,             // auto-set par SUPERSEDES post-classifier
    
    // === AXE 3 : LIFECYCLE STATUS ===
    lifecycle_status_at_publication: 'active'|'provisional'|'deprecated'|'retired'|'withdrawn'|'unknown',
    lifecycle_status_current:        'active'|'provisional'|'deprecated'|'retired'|'withdrawn'|'unknown',
    lifecycle_status_change_date:    '2025-03-15'|null,
    lifecycle_status_reason:         "..."|null,    // ex: "FDA Class I recall"
    lifecycle_status_native_value:   "recalled"|"retracted"|"end_of_life"|...,  // valeur native (Domain Pack)
    
    // === MAPPING DOMAIN PACK (référence) ===
    domain_pack_active: "medical"|"aerospace_compliance"|"api_documentation"|...
})
```

### Relation V3.1 unifiée

```cypher
(a:Claim)-[r:LOGICAL_RELATION {
    type: 'subset'|'superset'|'equivalent'|'overlap'|'disjoint'
        |'conflict'|'exception'|'definition_of'
        |'supersedes'|'evolves_from'                    // V3.1
        |'unrelated',
    strength: 'strong'|'weak'|'uncertain',              // V3
    confidence: 0.0-1.0,
    reasoning: "...",
    extracted_by: 'qwen2.5-14b-awq',
    extracted_at: timestamp(),
    scope_alignment: 'subset'|'superset'|'overlap'|'disjoint',
    document_role_pair: ['RESTRICTION', 'DEFINITION'],
    is_contradiction: true|false,
    contradiction_reason: 'true_conflict_high_confidence'|'subset_relation_not_contradiction'|...,
    
    // V3.1 — metadata temporelle pour SUPERSEDES / EVOLVES_FROM
    temporal_axis: 'release_id'|'effective_date'|'version'|null,
    effective_date_a: '2026-03-15'|null,
    effective_date_b: '2024-01-01'|null,
    
    // Phase 3 bis — composabilité
    derived: true|false,
    derivation_path: [edge_id_1, edge_id_2]|null
}]->(b:Claim)
```

### Requêtes types V3.1

```cypher
// 1. Toutes les vraies contradictions (CONFLICT confirmées)
MATCH (a:Claim)-[r:LOGICAL_RELATION]->(b:Claim)
WHERE r.is_contradiction = true 
  AND r.confidence >= 0.90
  AND r.strength IN ['strong', 'weak']
RETURN a, b, r;

// 2. Toutes les exceptions à un règlement spécifique (population/scope spécifique)
MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'exception'}]->(b:Claim {doc_id: 'reg_2021_821'})
RETURN a, b, r;

// 3. Hiérarchie des définitions/spécialisations
MATCH (a:Claim)-[r:LOGICAL_RELATION {type: 'subset'}]->(b:Claim)
WHERE r.confidence >= 0.70
RETURN b AS general, a AS specific, r;

// 4. (V3.1) Évolution temporelle d'un produit / règlement
MATCH (newer:Claim)-[r:LOGICAL_RELATION {type: 'supersedes'}]->(older:Claim)
WHERE newer.subject_canonical = $subject
RETURN newer.object AS new_value,
       newer.scope.version AS since_version,
       r.effective_date_a AS since_date,
       older.object AS old_value,
       older.scope.version AS until_version
ORDER BY newer.scope.version;

// 5. (V3.1) Chaînes d'évolution incrémentale (versioning produit)
MATCH path = (latest:Claim)-[:LOGICAL_RELATION {type: 'evolves_from'}*1..5]->(origin:Claim)
WHERE latest.subject_canonical = $subject
RETURN path;

// 6. Diff incrémental — nouveaux conflits introduits par un nouveau doc
MATCH (a:Claim {doc_id: $new_doc_id})-[r:LOGICAL_RELATION {type: 'conflict'}]->(b:Claim)
WHERE r.scope_alignment = 'overlap' AND r.confidence >= 0.85
RETURN a, b, r ORDER BY r.confidence DESC;

// 7. (V3.1) Inventaire complet par type sur un règlement
MATCH (a:Claim)-[r:LOGICAL_RELATION]->(b:Claim {doc_id: $doc_id})
RETURN r.type AS relation_type, count(*) AS n
ORDER BY n DESC;
// Retourne : conflict 8, exception 47, subset 213, supersedes 156, evolves_from 89, definition_of 1247, ...

// 8. (V3.2) Snapshot temporel strict — état du corpus au 15 juin 2024
MATCH (c:Claim)
WHERE c.validity_start <= datetime('2024-06-15')
  AND (c.validity_end IS NULL OR c.validity_end >= datetime('2024-06-15'))
  AND c.subject_canonical = $subject
RETURN c;

// 9. (V3.2) Diff temporel entre 2 dates — ce qui a changé sur un sujet
MATCH (newer:Claim)-[r:LOGICAL_RELATION {type: 'supersedes'}]->(older:Claim)
WHERE newer.subject_canonical = $subject
  AND newer.validity_start >= datetime('2024-01-01')
  AND older.validity_end <= datetime('2024-01-01')
RETURN newer.text AS new_state,
       newer.validity_start AS new_effective,
       older.text AS previous_state,
       older.validity_end AS previous_until,
       r.reasoning;

// 10. (V3.2) Claims actuellement en vigueur (validity_end IS NULL ou future)
MATCH (c:Claim)
WHERE c.validity_end IS NULL OR c.validity_end > datetime()
  AND c.doc_id = $doc_id
RETURN c
ORDER BY c.validity_start DESC;
```
