# Spécification Écran "Answer + Proof" - OSMOSE

## Contexte et Objectif

### Problème actuel
L'interface actuelle affiche :
- Une réponse textuelle (bien structurée ✅)
- Un score de confiance (94%) → **peu parlant, artefact data science**
- Un graphe KG → **illisible pour l'utilisateur métier**
- Des sources → ✅
- Des questions suggérées → ✅ (refactorisé avec ResearchAxesEngine v2)

### Objectif
Transformer l'écran de réponse pour montrer **pourquoi la réponse est fiable**, pas juste **ce qu'elle dit**.

> "Cette réponse n'est pas seulement plausible, elle est **contrôlée par la connaissance disponible**."

### Les 4 Blocs proposés

| Bloc | Nom | Fonction | Différenciation vs RAG |
|------|-----|----------|------------------------|
| A | Réponse | Texte synthétisé | Identique au RAG |
| B | Knowledge Proof Summary | État de la connaissance | **Le RAG ne peut pas faire** |
| C | Trace de Raisonnement | Chemin de preuve narratif | **Le RAG ne peut pas faire** |
| D | Knowledge Coverage Map | Ce qui est couvert vs non couvert | **Le RAG ne peut pas faire** |

---

## Knowledge Confidence Model (Cœur Algorithmique)

> **"Osmose n'optimise pas pour répondre. Osmose optimise pour savoir ce qu'il sait."**

### Principe Fondamental

Le Knowledge Confidence Model est le **contrat algorithmique** qui garantit que tout ce qu'OSMOSE montre est honnête, stable et défendable. Ce n'est pas un score ML, c'est un **évaluateur épistémique déterministe**.

### Deux Axes Orthogonaux (Séparation Cruciale)

```
┌─────────────────────────────────────────────────────────────────┐
│               KNOWLEDGE CONFIDENCE MODEL                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  AXE A — État Épistémique        AXE B — État Contractuel       │
│  (ce que le KG sait)             (ce que vous attendez)         │
│                                                                  │
│  🟢 ESTABLISHED                  ✅ COVERED                      │
│  🟡 PARTIAL                      ⚪ OUT_OF_SCOPE                 │
│  🟠 DEBATE                                                       │
│  🔴 INCOMPLETE                                                   │
│                                                                  │
│  → Calculé depuis KG             → Défini par DomainContext     │
│  → Déterministe                  → Contractuel                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Important :** "Hors périmètre" n'est PAS un état de connaissance. C'est un état du *contrat DomainContext*. Ne jamais mélanger les deux axes.

### Définition des États Épistémiques

| État | Définition (KG-based) | Indicateurs |
|------|----------------------|-------------|
| **ESTABLISHED** 🟢 | Relations cohérentes, pas de conflit, maturité ≥ VALIDATED, multi-sources | `validated_ratio ≥ 0.70`, `avg_conf ≥ 0.80`, `sources ≥ 2` |
| **PARTIAL** 🟡 | Relations présentes mais peu connectées ou maturity = EMERGING | Relations OK mais critères ESTABLISHED non atteints |
| **DEBATE** 🟠 | Relations CONFLICTS_WITH détectées entre sources | `conflicts_count > 0` |
| **INCOMPLETE** 🔴 | Concepts orphelins ou relations attendues absentes | `typed_edges = 0` ou `orphans > 0` ou `missing_expected > 0` |

### Définition des États Contractuels

| État | Définition | Source |
|------|------------|--------|
| **COVERED** ✅ | Question dans le périmètre DomainContext | `matched_domains` non vide |
| **OUT_OF_SCOPE** ⚪ | Question hors périmètre défini | `matched_domains` vide |

---

## Confidence Engine v2 (Pseudo-code)

### Enums

```python
from enum import Enum

class EpistemicState(str, Enum):
    ESTABLISHED = "established"   # 🟢
    PARTIAL     = "partial"       # 🟡
    DEBATE      = "debate"        # 🟠
    INCOMPLETE  = "incomplete"    # 🔴

class ContractState(str, Enum):
    COVERED      = "covered"       # ✅
    OUT_OF_SCOPE = "out_of_scope"  # ⚪
```

### Signaux KG (à collecter sur le sous-graphe de la réponse)

> **Définition contractuelle du "sous-graphe de la réponse" (Answer Subgraph) :**
> Le sous-graphe utilisé par le Confidence Engine est **strictement** :
> - L'ensemble des `typed_edges` qui apparaissent dans `reasoning_trace.steps[].supports`
> - Pas de traversée arbitraire depuis les `query_concepts`
> - Le frontend et le backend utilisent **le même périmètre**
>
> Cette définition garantit que le Confidence Engine évalue **uniquement** les relations qui soutiennent effectivement la réponse.

```python
@dataclass
class KGSignals:
    typed_edges_count: int              # Nombre de relations typées utilisées
    avg_conf: float                     # Moyenne confidence des relations
    validated_ratio: float              # ratio maturity VALIDATED / total
    conflicts_count: int                # CONFLICTS_WITH détectés
    orphan_concepts_count: int          # Concepts avec degree typed = 0
    independent_sources_count: int      # Documents distincts supportant les relations
    expected_edges_missing_count: int   # Relations attendues mais absentes (optionnel)
```

### Signaux Domain (depuis DomainContextStore)

```python
@dataclass
class DomainSignals:
    in_scope_domains: List[str]         # sub_domains du tenant
    matched_domains: List[str]          # Domaines matchés par la question
    contract_state: ContractState       # COVERED si match non vide
```

### Fonction Principale

```python
def compute_epistemic_state(s: KGSignals) -> EpistemicState:
    # 0) Cas extrêmes : pas de relations typées
    if s.typed_edges_count == 0:
        return EpistemicState.INCOMPLETE

    # 1) Conflits = DEBATE prioritaire (le conflit l'emporte toujours)
    if s.conflicts_count > 0:
        return EpistemicState.DEBATE

    # 2) Incomplétude structurelle
    if s.orphan_concepts_count > 0:
        return EpistemicState.INCOMPLETE
    if s.expected_edges_missing_count and s.expected_edges_missing_count > 0:
        return EpistemicState.INCOMPLETE

    # 3) Établie vs Partielle
    strong_maturity = s.validated_ratio >= 0.70
    strong_conf = s.avg_conf >= 0.80
    multi_sources = s.independent_sources_count >= 2

    if strong_maturity and strong_conf and multi_sources:
        return EpistemicState.ESTABLISHED

    # 4) Sinon : relations cohérentes mais fragiles
    return EpistemicState.PARTIAL

def compute_contract_state(d: DomainSignals) -> ContractState:
    # Aucune intelligence ici : c'est un contrat explicite
    return ContractState.COVERED if d.matched_domains else ContractState.OUT_OF_SCOPE
```

### Table de Vérité (Truth Table)

Variables booléennes :
- **E** = `typed_edges_count > 0`
- **C** = `conflicts_count > 0`
- **O** = `orphan_concepts_count > 0`
- **M** = `expected_edges_missing_count > 0`
- **S** = `(validated_ratio ≥ 0.70 AND avg_conf ≥ 0.80 AND sources ≥ 2)`

| E | C | O | M | S | EpistemicState |
|---|---|---|---|---|----------------|
| 0 | * | * | * | * | **INCOMPLETE** 🔴 |
| 1 | 1 | * | * | * | **DEBATE** 🟠 |
| 1 | 0 | 1 | * | * | **INCOMPLETE** 🔴 |
| 1 | 0 | 0 | 1 | * | **INCOMPLETE** 🔴 |
| 1 | 0 | 0 | 0 | 1 | **ESTABLISHED** 🟢 |
| 1 | 0 | 0 | 0 | 0 | **PARTIAL** 🟡 |

> Cette table est courte, donc **défendable**. Elle force l'alignement produit : "on ne confond pas *ne pas savoir* avec *hors périmètre*".

### Règle Critique : Quand OSMOSE Doit Refuser de Conclure

OSMOSE **ne doit PAS** produire une conclusion ferme dans ces cas :

| Cas | État | Message Obligatoire |
|-----|------|---------------------|
| Conflit détecté | DEBATE | "La connaissance est actuellement en débat entre sources." |
| Connaissance insuffisante | INCOMPLETE | "Les informations disponibles sont insuffisantes pour soutenir la réponse." |
| Domaine critique hors périmètre | OUT_OF_SCOPE | "Ce domaine n'est pas couvert par le périmètre de connaissance défini." |

---

## Lien avec TaxonomyBuilder et DomainContext

### Chaîne de Confiance

```
DomainContext (ce qui compte pour vous)
        ↓
Coverage Map (ce que cette réponse couvre vraiment)
        ↓
TaxonomyBuilder (comment la connaissance est organisée en profondeur)
```

### Sources de Taxonomie Actuelles

| Composant | Source | Status | Usage |
|-----------|--------|--------|-------|
| **DomainContext.sub_domains** | Manuelle (admin) | ✅ Existe | Coverage Map v0 |
| **LivingOntology** | Types de concepts auto-découverts | ✅ Existe | Enrichissement |
| **TaxonomyBuilder** | Hiérarchies PART_OF automatiques | ❌ Non implémenté | Coverage Map v2 |

### Stratégie d'Implémentation

1. **Court terme (Coverage Map v0)** : Utiliser `DomainContext.sub_domains` comme taxonomie de référence
2. **Moyen terme** : Enrichir avec types découverts par LivingOntology
3. **Long terme** : TaxonomyBuilder pour hiérarchies automatiques

> **Le Coverage Map est une *interface stable*. La Taxonomy est une *implémentation évolutive*.**

---

## État Actuel du Système

### Données disponibles dans le KG (Neo4j)

#### 1. CanonicalConcept
```cypher
(:CanonicalConcept {
  canonical_id: "uuid",
  canonical_name: "Article 22 RGPD",
  concept_type: "REGULATION",  // TECHNOLOGY, PROCESS, ORGANIZATION, REGULATION, STANDARD
  tenant_id: "default",
  quality_score: 0.85,         // Score de qualité du concept
  popularity: 12,              // Nombre de mentions
  summary: "...",
  unified_definition: "..."
})
```

#### 2. CanonicalRelation (Relations typées)
```cypher
[:REQUIRES|CAUSES|ENABLES|PART_OF|SUBTYPE_OF|CONFLICTS_WITH {
  canonical_relation_id: "uuid",
  confidence: 0.85,            // Confiance de la relation
  source_count: 3,             // Nombre de sources indépendantes
  maturity: "VALIDATED",       // CANDIDATE, VALIDATED, CONTESTED
  tenant_id: "default"
}]
```

> **⚠️ Note importante (MVP) :**
> Dans le KG actuel, `maturity` est sur `CanonicalConcept`, pas sur `CanonicalRelation`.
> Pour le MVP Answer+Proof, **CanonicalRelation DOIT porter `maturity`** (CANDIDATE | VALIDATED | CONTESTED).
> Cela permet au Confidence Engine de calculer `validated_ratio` sur les *edges* du sous-graphe de la réponse.

**Types de relations existants :**
- ASSOCIATED_WITH: 3200 (générique)
- REQUIRES: 262 (actionnable)
- PART_OF: 208 (structure)
- CAUSES: 142 (risque/impact)
- ENABLES: 68 (actionnable)
- USES: 42
- APPLIES_TO: 34
- INTEGRATES_WITH: 30
- EXTENDS: 16
- SUBTYPE_OF: 10 (structure)
- CONFLICTS_WITH: 10 (contradiction)
- PREVENTS: 8

#### 3. Données de réponse actuelle (API /search)
```json
{
  "synthesis": {
    "synthesized_answer": "...",
    "sources_used": ["doc1.pptx", "doc2.pdf"],
    "confidence": 0.94
  },
  "graph_context": {
    "query_concepts": ["Article 22 RGPD", "Décision automatisée"],
    "related_concepts": [
      {"source": "Article 22", "concept": "Intervention humaine", "relation": "REQUIRES", "confidence": 0.85}
    ],
    "transitive_relations": [...],
    "visibility_profile": "balanced"
  },
  "exploration_intelligence": {
    "research_axes": [...],
    "concept_explanations": {...}
  }
}
```

### Ce qui manque actuellement

| Donnée | Usage | État |
|--------|-------|------|
| Comptage d'assertions distinctes | Bloc B | ❌ À calculer |
| Détection de contradictions | Bloc B | ⚠️ CONFLICTS_WITH existe mais pas exploité |
| Mapping concept → domaine | Bloc D | ❌ À créer |
| Chemin de preuve narratif | Bloc C | ⚠️ Partiellement via explainer_trace |

---

## BLOC A - La Réponse (avec Badge Global)

### Objectif

Afficher un **badge combiné** `EpistemicState + ContractState` au lieu d'un score pourcentage.

> **Le waouh** : "je réponds" → "je sais ce que je sais"

### Changements requis

| Élément | Avant | Après |
|---------|-------|-------|
| Score de confiance | "94% de confiance" affiché | **Badge État** (ESTABLISHED/PARTIAL/DEBATE/INCOMPLETE) |
| Position | Seul élément principal | Premier bloc, suivi des preuves |
| Apparence | Auto-suffisant | Introduit comme "synthèse contrôlée" |

### Badges par État

| État | Badge Affiché | Micro-texte |
|------|---------------|-------------|
| **ESTABLISHED + COVERED** | 🟢 "Réponse contrôlée" | "Soutenue par X relations validées / Y sources" |
| **PARTIAL + COVERED** | 🟡 "Réponse partiellement contrôlée" | "Certaines parties restent peu étayées — voir Couverture" |
| **DEBATE + COVERED** | 🟠 "Réponse controversée" | "Sources en désaccord — arbitrage requis" |
| **INCOMPLETE + COVERED** | 🔴 "Réponse non garantie" | "Le graphe ne permet pas de soutenir la réponse de bout en bout" |
| **\* + OUT_OF_SCOPE** | ⚪ "Hors périmètre" | "Domaine non couvert par votre DomainContext" |

### CTA Contextuels (Call-To-Action)

| État | CTA |
|------|-----|
| PARTIAL / INCOMPLETE | "Compléter la base : ce qu'il manque" |
| DEBATE | "Voir les points de divergence" |
| OUT_OF_SCOPE | "Ajouter ce domaine au périmètre" |

### Implémentation

**Frontend** - Modification de `SearchResultDisplay.tsx` :
- Retirer l'affichage du score de confiance
- Ajouter le badge État avec couleur
- Ajouter le micro-texte contextuel
- Ajouter le CTA si applicable

**Backend** - Le champ `confidence` dans la réponse API contient :
```json
{
  "epistemic_state": "PARTIAL",
  "contract_state": "COVERED",
  "badge": "Réponse partiellement contrôlée",
  "warnings": ["Certaines parties restent peu étayées"],
  "cta": {"label": "Voir couverture", "action": "scroll_to_coverage"}
}
```

### Complexité : 🟢 Faible (2-4h)

---

## BLOC B - Knowledge Proof Summary

### Objectif
Remplacer le score "94%" par un **résumé structuré de l'état de la connaissance**.

> **Le waouh** : afficher 3 lignes de "preuves" au lieu d'un pourcentage abstrait.

### Rendu cible

```
┌─────────────────────────────────────────────────────────────┐
│ 🧾 ÉTAT DE LA CONNAISSANCE                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  📊 Fondements                                              │
│  ├─ 6 concepts identifiés                                   │
│  ├─ 4 relations typées (REQUIRES, CAUSES, PART_OF)          │
│  ├─ 3 sources documentaires indépendantes                   │
│  └─ 8 assertions distinctes                                 │
│                                                             │
│  ✅ Cohérence                                               │
│  ├─ Aucune contradiction détectée                           │
│  └─ 2 relations d'exception formalisées                     │
│                                                             │
│  📋 Nature                                                  │
│  ├─ Types dominants: ["REGULATION", "PROCESS"]              │
│  ├─ Solidité: Établie                                       │
│  └─ Maturité: 85% des relations validées                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Données nécessaires

| Métrique | Source | Calcul |
|----------|--------|--------|
| Nombre de concepts | `graph_context.query_concepts` + `related_concepts` | `count(distinct concepts)` |
| Nombre de relations typées | Neo4j | Requête sur CanonicalRelation |
| Types de relations | Neo4j | `GROUP BY type(r)` |
| Nombre de sources | `synthesis.sources_used` | `count(distinct sources)` |
| Nombre d'assertions | RawAssertion (si existe) ou estimation | À implémenter |
| Contradictions | Neo4j `CONFLICTS_WITH` | `count([:CONFLICTS_WITH])` |
| Relations d'exception | Neo4j | Relations avec `is_exception: true` |
| Types dominants | Analyse des concept_type | Liste extensible via LivingOntology |
| Solidité | Moyenne des `confidence` | Seuils : <0.5 Fragile, 0.5-0.8 Partielle, >0.8 Établie |
| Maturité | % de relations VALIDATED | `count(VALIDATED) / count(*)` |

### Implémentation Backend

#### 1. Nouveau service `knowledge_proof_service.py`

```python
@dataclass
class KnowledgeProofSummary:
    # Fondements
    concepts_count: int
    relations_count: int
    relation_types: List[str]  # ["REQUIRES", "CAUSES", "PART_OF"]
    sources_count: int
    assertions_count: int

    # Cohérence
    contradictions_count: int
    exceptions_count: int

    # Nature (extensible)
    dominant_concept_types: List[str]  # Types découverts par LivingOntology, extensibles
    solidity: str        # "Fragile", "Partielle", "Établie"
    maturity_percent: float

    def to_dict(self) -> Dict[str, Any]: ...
```

#### 2. Requête Cypher pour collecter les métriques

```cypher
// Pour les concepts de la réponse
UNWIND $concept_names AS name
MATCH (c:CanonicalConcept {tenant_id: $tid, canonical_name: name})
OPTIONAL MATCH (c)-[r]-(other:CanonicalConcept {tenant_id: $tid})

WITH
  count(DISTINCT c) AS concepts_count,
  count(DISTINCT r) AS relations_count,
  collect(DISTINCT type(r)) AS relation_types,
  avg(r.confidence) AS avg_confidence,
  sum(CASE WHEN r.maturity = 'VALIDATED' THEN 1 ELSE 0 END) AS validated_count,
  sum(CASE WHEN type(r) = 'CONFLICTS_WITH' THEN 1 ELSE 0 END) AS conflicts_count,
  collect(DISTINCT c.concept_type) AS concept_types

RETURN
  concepts_count,
  relations_count,
  relation_types,
  avg_confidence,
  toFloat(validated_count) / CASE WHEN relations_count > 0 THEN relations_count ELSE 1 END AS maturity_ratio,
  conflicts_count,
  concept_types
```

#### 3. Logique de classification

```python
def get_dominant_concept_types(concept_types: List[str], top_n: int = 3) -> List[str]:
    """
    Retourne les types de concepts les plus fréquents.

    Note: Les types proviennent de LivingOntology et sont extensibles.
    Aucun mapping hardcodé - on retourne les types tels quels.
    """
    from collections import Counter
    counts = Counter(concept_types)
    return [t for t, _ in counts.most_common(top_n)]

def determine_solidity(avg_confidence: float, sources_count: int) -> str:
    """Détermine la solidité de la réponse."""
    if avg_confidence >= 0.8 and sources_count >= 2:
        return "Établie"
    elif avg_confidence >= 0.5:
        return "Partielle"
    else:
        return "Fragile"
```

### Implémentation Frontend

#### Nouveau composant `KnowledgeProofPanel.tsx`

```tsx
interface KnowledgeProofPanelProps {
  proof: KnowledgeProofSummary
}

export function KnowledgeProofPanel({ proof }: KnowledgeProofPanelProps) {
  return (
    <Box bg="bg.secondary" rounded="xl" p={4}>
      <HStack mb={4}>
        <Icon as={FiShield} color="brand.400" />
        <Text fontWeight="bold">État de la connaissance</Text>
      </HStack>

      {/* Section Fondements */}
      <VStack align="start" spacing={2}>
        <ProofMetric
          icon={FiDatabase}
          label="concepts identifiés"
          value={proof.concepts_count}
        />
        <ProofMetric
          icon={FiLink}
          label="relations typées"
          value={proof.relations_count}
          detail={proof.relation_types.join(", ")}
        />
        ...
      </VStack>

      {/* Section Cohérence */}
      <CoherenceSection
        contradictions={proof.contradictions_count}
        exceptions={proof.exceptions_count}
      />

      {/* Section Nature */}
      <NatureSection
        dominantTypes={proof.dominant_concept_types}
        solidity={proof.solidity}
        maturity={proof.maturity_percent}
      />
    </Box>
  )
}
```

### Signaux UI - Cas Limites

| État | Affichage dans Bloc B |
|------|----------------------|
| **DEBATE** 🟠 | Encart orange "⚠️ Contradictions détectées : X" + bouton "Voir détails" listant 2-3 conflits max |
| **INCOMPLETE** 🔴 | Encart rouge "⚠️ Trou de connaissance" : "N concepts non reliés", "0 relation typée sur ce point" |
| **OUT_OF_SCOPE** ⚪ | Proof affiché mais **grisé** + mention "Hors contrat - information indicative" |
| **ESTABLISHED** 🟢 | Affichage normal avec indicateurs verts |

### Structure de Données Backend

```python
@dataclass
class KnowledgeProofSummary:
    # Fondements
    concepts_count: int
    relations_count: int
    relation_types: List[str]      # ["REQUIRES", "CAUSES", "PART_OF"]
    sources_count: int

    # Cohérence (basée sur Confidence Engine)
    contradictions_count: int      # CONFLICTS_WITH détectés
    coherence_status: str          # "coherent", "debate", "incomplete"

    # Solidité (métriques KG)
    maturity_percent: float        # % relations VALIDATED
    avg_confidence: float          # Moyenne confidence

    # État global (calculé par Confidence Engine)
    epistemic_state: EpistemicState
    contract_state: ContractState
```

### Complexité : 🟡 Moyenne (1-2 jours)

---

## BLOC C - Trace de Raisonnement Vérifiée

### Objectif
Montrer le **chemin de preuve** sous forme narrative, pas sous forme de graphe technique.

### Rendu cible

```
┌─────────────────────────────────────────────────────────────┐
│ 🔍 POURQUOI CETTE RÉPONSE TIENT                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Article 22 RGPD pose une interdiction générale          │
│     └─ [REQUIRES] → Intervention humaine                    │
│                                                             │
│  2. Cette interdiction est modulée par 3 exceptions         │
│     └─ [PART_OF] → Exceptions contractuelles                │
│     └─ [PART_OF] → Consentement explicite                   │
│     └─ [PART_OF] → Base légale                              │
│                                                             │
│  3. Les exceptions déclenchent des garanties                │
│     └─ [ENABLES] → Droit de contestation                    │
│                                                             │
│  4. Pour les données sensibles (Art. 9), règle stricte      │
│     └─ [SUBTYPE_OF] → Données de santé                      │
│     └─ [CONFLICTS_WITH] → Traitement automatisé standard    │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│  ✅ Ces règles sont cohérentes entre elles                  │
│  ✅ Aucune source analysée ne les contredit                 │
│                                                             │
│  📎 Cliquez sur une étape pour voir la source               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Données nécessaires

| Donnée | Source | État |
|--------|--------|------|
| Chemin de concepts | ResearchAxesEngine.explainer_trace | ✅ Existe |
| Relations entre concepts | Neo4j CanonicalRelation | ✅ Existe |
| Groupement logique | LLM ou règles métier | ❌ À créer |
| Sources par relation | CanonicalRelation → RawAssertion → chunks | ⚠️ Partiellement |

### Implémentation Backend

#### 1. Nouveau service `reasoning_trace_service.py`

```python
@dataclass
class ReasoningStep:
    step_number: int
    statement: str                    # "Article 22 RGPD pose une interdiction générale"
    relations: List[ReasoningRelation]
    source_refs: List[str]            # ["doc1.pptx:slide12", "doc2.pdf:page5"]

@dataclass
class ReasoningRelation:
    relation_type: str      # "REQUIRES"
    target_concept: str     # "Intervention humaine"
    confidence: float
    source_ref: Optional[str]

@dataclass
class ReasoningTrace:
    steps: List[ReasoningStep]
    coherence_status: str   # "coherent", "partial_conflict", "conflict"
    coherence_message: str  # "Ces règles sont cohérentes entre elles"
```

#### 2. Approche de génération du chemin

**Option A : Extraction depuis le KG (déterministe)**
```python
async def build_reasoning_trace(
    focus_concepts: List[str],
    tenant_id: str
) -> ReasoningTrace:
    """
    Construit le chemin de raisonnement depuis le KG.

    1. Part des concepts de la question
    2. Suit les relations sortantes (REQUIRES, CAUSES, ENABLES)
    3. Suit les relations structurelles (PART_OF, SUBTYPE_OF)
    4. Détecte les conflits (CONFLICTS_WITH)
    5. Groupe par thème logique
    """

    # Requête pour obtenir les chemins
    cypher = """
    UNWIND $concepts AS concept_name
    MATCH path = (c:CanonicalConcept {canonical_name: concept_name, tenant_id: $tid})
                 -[r:REQUIRES|CAUSES|ENABLES|PART_OF|SUBTYPE_OF*1..2]->
                 (target:CanonicalConcept)
    RETURN
        c.canonical_name AS source,
        [rel IN relationships(path) | {type: type(rel), conf: rel.confidence}] AS rels,
        [n IN nodes(path) | n.canonical_name] AS path_nodes
    ORDER BY length(path)
    LIMIT 20
    """
    ...
```

**Option B : Génération LLM (plus naturel)**
```python
async def generate_narrative_trace(
    query: str,
    answer: str,
    kg_relations: List[Dict]
) -> ReasoningTrace:
    """
    Utilise un LLM pour transformer les relations KG en récit structuré.
    """
    prompt = f"""
    Transforme ces relations du Knowledge Graph en étapes de raisonnement narratif.

    Question: {query}
    Réponse: {answer[:500]}

    Relations KG:
    {format_relations(kg_relations)}

    Génère 3-5 étapes de raisonnement, chacune avec:
    - Un énoncé en langage naturel
    - Les relations KG qui le soutiennent

    Format JSON attendu:
    {{
      "steps": [
        {{
          "statement": "L'article 22 RGPD pose une interdiction générale",
          "relations": [
            {{"type": "REQUIRES", "target": "Intervention humaine"}}
          ]
        }}
      ]
    }}
    """
    ...
```

**Recommandation : Hybride**
- Extraire les relations depuis le KG (fiable, auditable)
- Utiliser le LLM uniquement pour le "statement" narratif de chaque étape
- Garder les relations KG comme preuve

### Implémentation Frontend

#### Nouveau composant `ReasoningTracePanel.tsx`

```tsx
interface ReasoningTracePanelProps {
  trace: ReasoningTrace
  onSourceClick: (sourceRef: string) => void
}

export function ReasoningTracePanel({ trace, onSourceClick }: ReasoningTracePanelProps) {
  return (
    <Box bg="bg.secondary" rounded="xl" p={4}>
      <HStack mb={4}>
        <Icon as={FiSearch} color="brand.400" />
        <Text fontWeight="bold">Pourquoi cette réponse tient</Text>
      </HStack>

      <VStack align="stretch" spacing={4}>
        {trace.steps.map((step, idx) => (
          <ReasoningStepCard
            key={idx}
            step={step}
            onSourceClick={onSourceClick}
          />
        ))}
      </VStack>

      {/* Footer cohérence */}
      <CoherenceFooter
        status={trace.coherence_status}
        message={trace.coherence_message}
      />
    </Box>
  )
}

function ReasoningStepCard({ step, onSourceClick }) {
  return (
    <Box pl={4} borderLeft="2px solid" borderColor="brand.500">
      <Text fontWeight="medium" color="text.primary">
        {step.step_number}. {step.statement}
      </Text>

      <VStack align="start" pl={4} mt={2} spacing={1}>
        {step.relations.map((rel, idx) => (
          <HStack key={idx} fontSize="sm" color="text.secondary">
            <Badge colorScheme={getRelationColor(rel.relation_type)}>
              {rel.relation_type}
            </Badge>
            <Text>→ {rel.target_concept}</Text>
            {rel.source_ref && (
              <Link onClick={() => onSourceClick(rel.source_ref)}>
                📎
              </Link>
            )}
          </HStack>
        ))}
      </VStack>
    </Box>
  )
}
```

### Signaux UI - Cas Limites (Ruptures de Confiance)

Le Bloc C doit gérer les **ruptures de confiance** visuellement :

| Cas | Affichage |
|-----|-----------|
| **Étape sans support KG** | Ligne pointillée + tag "Hypothèse (non supportée par le KG)" |
| **DEBATE** 🟠 | Étape avec **2 branches** visuelles : "Version A (doc1)" vs "Version B (doc2)" |
| **INCOMPLETE** 🔴 | Étape "trou" explicite : "Pour conclure sur X, il manque une relation typée entre A et B" |
| **OUT_OF_SCOPE** ⚪ | Trace affichable mais avec avertissement "Raisonnement non contractualisé" |

### Règle Importante

> **Bloc C = visualisation narrative, PAS calcul.**
> Le calcul des états est fait par le Confidence Engine en amont.
> Bloc C expose les transitions, il ne les invente jamais.

### Structure de Données Backend

```python
@dataclass
class ReasoningStep:
    step_number: int
    statement: str                    # LLM génère la phrase narrative
    supports: List[ReasoningSupport]  # Relations KG qui soutiennent
    has_kg_support: bool              # True si au moins 1 support KG
    is_conflict: bool                 # True si CONFLICTS_WITH détecté
    source_refs: List[str]            # ["doc1.pptx:slide12"]

@dataclass
class ReasoningSupport:
    relation_type: str                # "REQUIRES"
    source_concept_id: str
    target_concept_id: str
    edge_confidence: float
    canonical_relation_id: str        # Pour traçabilité
    source_refs: List[str]

@dataclass
class ReasoningTrace:
    steps: List[ReasoningStep]
    coherence_status: str             # "coherent", "partial_conflict", "conflict"
    unsupported_steps_count: int      # Nombre d'étapes sans support KG
```

### Complexité : 🟡 Moyenne-Haute (2-3 jours)

---

## BLOC D - Knowledge Coverage Map

### Objectif
Montrer **ce qui est couvert ET ce qui ne l'est pas** - la vraie différenciation vs RAG.

### Rendu cible

```
┌─────────────────────────────────────────────────────────────┐
│ 🗺️ COUVERTURE DE LA QUESTION                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Domaine                        État                        │
│  ─────────────────────────────────────────────────────────  │
│  Décisions automatisées         🟢 Couvert (8 relations)    │
│  Exceptions contractuelles      🟢 Couvert (3 relations)    │
│  Garanties procédurales         🟢 Couvert (4 relations)    │
│  Droit à l'explication          🟡 Débat doctrinal          │
│  Jurisprudence nationale        🔴 Non couvert              │
│  Sanctions CNIL                 🔴 Non couvert              │
│                                                             │
│  ─────────────────────────────────────────────────────────  │
│  📊 Cette réponse couvre 67% des domaines pertinents        │
│                                                             │
│  ⚠️ Pour une analyse complète, considérez:                  │
│     • La jurisprudence nationale                            │
│     • Les décisions de la CNIL                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Données nécessaires

| Donnée | Source | État |
|--------|--------|------|
| Liste des domaines pertinents | Domain Context + Analyse question | ❌ À créer |
| Mapping concept → domaine | Taxonomie ou LLM | ❌ À créer |
| Couverture par domaine | Comptage relations par domaine | ❌ À créer |
| Domaines manquants | Domain Context - domaines couverts | ❌ À créer |

### Prérequis : Taxonomie de domaines

#### 1. Source de taxonomie (règle absolue)

> **⚠️ Règle fondamentale :**
> La taxonomie utilisée par le Coverage Map provient **exclusivement** de `DomainContextStore`.
> **Aucun domaine hardcodé dans le code.**
>
> Si le tenant n'a pas de DomainContext configuré, Coverage Map retourne :
> ```json
> { "domains": [], "coverage_percent": null, "message": "DomainContext non configuré" }
> ```

Le modèle `KnowledgeDomain` dans `domain_context_store.py` :

```python
@dataclass
class KnowledgeDomain:
    domain_id: str
    name: str                      # Ex: "Décisions automatisées"
    description: str
    parent_domain: Optional[str]   # Pour hiérarchie
    keywords: List[str]            # Pour matching
    required_for_completeness: bool  # Ce domaine est-il essentiel?

# Les domaines sont chargés depuis DomainContextStore.get_domains(tenant_id)
# PAS de constante hardcodée ici
```

#### 2. Mapping automatique question → domaines pertinents

```python
async def identify_relevant_domains(
    query: str,
    query_concepts: List[str],
    all_domains: List[KnowledgeDomain]
) -> List[KnowledgeDomain]:
    """
    Identifie les domaines pertinents pour une question.

    Approche hybride:
    1. Matching par keywords
    2. Matching par concepts KG
    3. (Optionnel) Enrichissement LLM
    """
    relevant = []

    query_lower = query.lower()
    concepts_lower = [c.lower() for c in query_concepts]

    for domain in all_domains:
        # Score de pertinence
        score = 0

        # Matching keywords dans la question
        for kw in domain.keywords:
            if kw.lower() in query_lower:
                score += 2

        # Matching keywords dans les concepts
        for kw in domain.keywords:
            for concept in concepts_lower:
                if kw.lower() in concept:
                    score += 1

        if score > 0 or domain.required_for_completeness:
            relevant.append((domain, score))

    # Trier par score et retourner
    return [d for d, s in sorted(relevant, key=lambda x: -x[1])]
```

### Implémentation Backend

#### 1. Nouveau service `coverage_map_service.py`

```python
@dataclass
class DomainCoverage:
    domain_id: str
    domain_name: str
    status: str           # "covered", "partial", "debated", "not_covered"
    relations_count: int
    concepts_found: List[str]
    confidence: float
    note: Optional[str]   # "Débat doctrinal", etc.

@dataclass
class CoverageMap:
    domains: List[DomainCoverage]
    coverage_percent: float
    covered_count: int
    total_relevant: int
    recommendations: List[str]  # Domaines à explorer

class CoverageMapService:
    async def build_coverage_map(
        self,
        query: str,
        query_concepts: List[str],
        kg_relations: List[Dict],
        tenant_id: str
    ) -> CoverageMap:
        """
        Construit la carte de couverture.

        1. Identifier les domaines pertinents
        2. Pour chaque domaine, chercher les concepts/relations correspondants
        3. Calculer le statut de couverture
        4. Générer les recommandations
        """

        # 1. Domaines pertinents
        relevant_domains = await self.identify_relevant_domains(
            query, query_concepts
        )

        # 2. Analyser la couverture pour chaque domaine
        coverages = []
        for domain in relevant_domains:
            coverage = await self.analyze_domain_coverage(
                domain, query_concepts, kg_relations, tenant_id
            )
            coverages.append(coverage)

        # 3. Calculer les stats
        covered = [c for c in coverages if c.status in ["covered", "partial"]]
        coverage_percent = len(covered) / len(coverages) * 100 if coverages else 0

        # 4. Recommandations
        recommendations = [
            c.domain_name for c in coverages
            if c.status == "not_covered" and c.domain_id in REQUIRED_DOMAINS
        ]

        return CoverageMap(
            domains=coverages,
            coverage_percent=coverage_percent,
            covered_count=len(covered),
            total_relevant=len(coverages),
            recommendations=recommendations
        )

    async def analyze_domain_coverage(
        self,
        domain: KnowledgeDomain,
        query_concepts: List[str],
        kg_relations: List[Dict],
        tenant_id: str
    ) -> DomainCoverage:
        """
        Analyse la couverture d'un domaine spécifique.
        """
        # Chercher les concepts du KG qui matchent ce domaine
        cypher = """
        MATCH (c:CanonicalConcept {tenant_id: $tid})
        WHERE any(kw IN $keywords WHERE toLower(c.canonical_name) CONTAINS toLower(kw))
        OPTIONAL MATCH (c)-[r]-(other:CanonicalConcept)
        RETURN
            c.canonical_name AS concept,
            count(r) AS relations_count,
            avg(r.confidence) AS avg_confidence
        """

        results = self.neo4j.execute_query(cypher, {
            "tid": tenant_id,
            "keywords": domain.keywords
        })

        if not results:
            return DomainCoverage(
                domain_id=domain.domain_id,
                domain_name=domain.name,
                status="not_covered",
                relations_count=0,
                concepts_found=[],
                confidence=0,
                note=None
            )

        # Calculer le statut
        total_relations = sum(r["relations_count"] for r in results)
        avg_conf = sum(r["avg_confidence"] or 0 for r in results) / len(results)
        concepts = [r["concept"] for r in results]

        # Déterminer le statut
        if total_relations >= 3 and avg_conf >= 0.7:
            status = "covered"
        elif total_relations >= 1:
            status = "partial"
        else:
            status = "not_covered"

        # Cas spéciaux (débat doctrinal, etc.)
        if domain.domain_id == "rgpd_art22_explanation":
            status = "debated"
            note = "Débat doctrinal en cours"

        return DomainCoverage(
            domain_id=domain.domain_id,
            domain_name=domain.name,
            status=status,
            relations_count=total_relations,
            concepts_found=concepts[:5],
            confidence=avg_conf,
            note=note
        )
```

### Implémentation Frontend

#### Nouveau composant `CoverageMapPanel.tsx`

```tsx
interface CoverageMapPanelProps {
  coverage: CoverageMap
}

const STATUS_CONFIG = {
  covered: { icon: "🟢", color: "green.400", label: "Couvert" },
  partial: { icon: "🟡", color: "yellow.400", label: "Partiel" },
  debated: { icon: "🟡", color: "orange.400", label: "Débat" },
  not_covered: { icon: "🔴", color: "red.400", label: "Non couvert" }
}

export function CoverageMapPanel({ coverage }: CoverageMapPanelProps) {
  return (
    <Box bg="bg.secondary" rounded="xl" p={4}>
      <HStack mb={4}>
        <Icon as={FiMap} color="brand.400" />
        <Text fontWeight="bold">Couverture de la question</Text>
      </HStack>

      {/* Table des domaines */}
      <Table variant="simple" size="sm">
        <Thead>
          <Tr>
            <Th>Domaine</Th>
            <Th>État</Th>
          </Tr>
        </Thead>
        <Tbody>
          {coverage.domains.map(domain => (
            <Tr key={domain.domain_id}>
              <Td>{domain.domain_name}</Td>
              <Td>
                <HStack>
                  <Text>{STATUS_CONFIG[domain.status].icon}</Text>
                  <Text color={STATUS_CONFIG[domain.status].color}>
                    {STATUS_CONFIG[domain.status].label}
                    {domain.relations_count > 0 && ` (${domain.relations_count} relations)`}
                  </Text>
                </HStack>
                {domain.note && (
                  <Text fontSize="xs" color="text.muted">{domain.note}</Text>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>

      {/* Résumé */}
      <Box mt={4} p={3} bg="bg.tertiary" rounded="lg">
        <Text fontSize="sm">
          📊 Cette réponse couvre <strong>{coverage.coverage_percent.toFixed(0)}%</strong> des domaines pertinents
        </Text>
      </Box>

      {/* Recommandations */}
      {coverage.recommendations.length > 0 && (
        <Box mt={3}>
          <Text fontSize="sm" color="text.secondary">
            ⚠️ Pour une analyse complète, considérez :
          </Text>
          <UnorderedList fontSize="sm" color="text.muted" pl={4}>
            {coverage.recommendations.map((rec, idx) => (
              <ListItem key={idx}>{rec}</ListItem>
            ))}
          </UnorderedList>
        </Box>
      )}
    </Box>
  )
}
```

### Signaux UI - Cas Limites

| État du Domaine | Affichage | Icône |
|-----------------|-----------|-------|
| **covered** | "Couvert (X relations)" | 🟢 |
| **partial** | "Partiel" - présent mais faible | 🟡 |
| **debate** | "Débat" - contradictions détectées | 🟠 |
| **not_covered** | "Non couvert" - rien dans le KG | 🔴 |
| **out_of_scope** | "Hors périmètre" - non attendu par DomainContext | ⚪ |

### Mapping États Épistémiques → Domaines

Le Coverage Map hérite des états du Confidence Engine :

```python
def get_domain_epistemic_state(domain_concepts: List[CanonicalConcept]) -> EpistemicState:
    """Agrège l'état épistémique d'un domaine depuis ses concepts."""
    states = [compute_concept_state(c) for c in domain_concepts]

    # Le conflit l'emporte
    if any(s == EpistemicState.DEBATE for s in states):
        return EpistemicState.DEBATE

    # Tous établis = domaine établi
    if all(s == EpistemicState.ESTABLISHED for s in states):
        return EpistemicState.ESTABLISHED

    # Un incomplet = domaine incomplet
    if any(s == EpistemicState.INCOMPLETE for s in states):
        return EpistemicState.INCOMPLETE

    return EpistemicState.PARTIAL
```

### La vraie différenciation vs RAG

> **Le Coverage Map montre la "carte des angles morts"** — ce qu'un RAG standard ne peut jamais faire.

C'est le bloc qui démontre le plus clairement la valeur d'OSMOSE :
- Un RAG dit "voici ma réponse"
- OSMOSE dit "voici ma réponse, ET voici ce que je ne couvre pas"

### Complexité : 🔴 Haute (3-5 jours)

**Pourquoi c'est complexe :**
1. Nécessite de définir une taxonomie de domaines (utiliser `DomainContext.sub_domains` en v0)
2. Le mapping concept → domaine n'est pas trivial
3. La détection de "débat doctrinal" vs "non couvert" nécessite des règles métier
4. Doit être maintenu à mesure que le corpus évolue

---

## Intégration dans l'API

### Modification de `/search` endpoint

```python
# Dans search.py

def search_documents(...) -> dict[str, Any]:
    ...

    # Après la synthèse et le graph_context

    # 🆕 Bloc B: Knowledge Proof Summary
    if graph_context_data:
        try:
            from .knowledge_proof_service import get_knowledge_proof_service

            proof_service = get_knowledge_proof_service()
            knowledge_proof = proof_service.build_proof_summary(
                query_concepts=graph_context_data.get("query_concepts", []),
                related_concepts=graph_context_data.get("related_concepts", []),
                sources=synthesis_result.get("sources_used", []),
                tenant_id=tenant_id
            )
            response["knowledge_proof"] = knowledge_proof.to_dict()

        except Exception as e:
            logger.warning(f"Knowledge proof failed: {e}")

    # 🆕 Bloc C: Reasoning Trace
    if graph_context_data:
        try:
            from .reasoning_trace_service import get_reasoning_trace_service

            trace_service = get_reasoning_trace_service()
            reasoning_trace = await trace_service.build_reasoning_trace(
                query=query,
                answer=synthesis_result.get("synthesized_answer", ""),
                focus_concepts=graph_context_data.get("query_concepts", []),
                tenant_id=tenant_id
            )
            response["reasoning_trace"] = reasoning_trace.to_dict()

        except Exception as e:
            logger.warning(f"Reasoning trace failed: {e}")

    # 🆕 Bloc D: Coverage Map
    if graph_context_data:
        try:
            from .coverage_map_service import get_coverage_map_service

            coverage_service = get_coverage_map_service()
            coverage_map = await coverage_service.build_coverage_map(
                query=query,
                query_concepts=graph_context_data.get("query_concepts", []),
                kg_relations=graph_context_data.get("related_concepts", []),
                tenant_id=tenant_id
            )
            response["coverage_map"] = coverage_map.to_dict()

        except Exception as e:
            logger.warning(f"Coverage map failed: {e}")

    return response
```

### Schéma JSON Unifié pour `/search` (Contrat API)

**Objectif :** Un seul objet qui alimente l'écran Answer+Proof + l'exploration.

```json
{
  "status": "success",
  "request_id": "uuid",
  "tenant_id": "default",

  "question": {
    "text": "string",
    "language": "fr"
  },

  "answer": {
    "text": "string",
    "sources_used": [
      { "doc_id": "fra_bias_discrimination_ai", "kind": "pdf", "locator": "slides 12-15" }
    ]
  },

  "focus_concepts": [
    { "canonical_id": "uuid", "name": "Article 22 RGPD", "weight": 4, "origin": "question" }
  ],

  "graph_context": {
    "subgraph": {
      "concept_ids": ["uuid", "uuid2"],
      "typed_edges": [
        {
          "source_id": "uuid",
          "target_id": "uuid2",
          "type": "REQUIRES",
          "confidence": 0.85,
          "maturity": "VALIDATED",
          "canonical_relation_id": "cr_123",
          "source_docs": ["fra_bias_discrimination_ai"]
        }
      ]
    }
  },

  "confidence": {
    "epistemic_state": "PARTIAL",
    "contract_state": "COVERED",
    "badge": "Réponse partiellement contrôlée",
    "rules_fired": ["NO_CONFLICT", "NOT_ENOUGH_SOURCES"],
    "warnings": ["Certaines parties restent peu étayées"],
    "blockers": [],
    "kg_signals": {
      "typed_edges_count": 4,
      "avg_conf": 0.81,
      "validated_ratio": 0.50,
      "conflicts_count": 0,
      "orphan_concepts_count": 0,
      "independent_sources_count": 1,
      "expected_edges_missing_count": 1
    },
    "domain_signals": {
      "matched_domains": ["RGPD"],
      "out_of_scope_domains": []
    }
  },

  "proof_summary": {
    "concepts_count": 6,
    "relations_count": 4,
    "relation_types": ["REQUIRES", "PART_OF", "ENABLES"],
    "sources_count": 1,
    "contradictions_count": 0,
    "maturity_percent": 50
  },

  "reasoning_trace": {
    "coherence_status": "coherent",
    "unsupported_steps_count": 0,
    "steps": [
      {
        "step": 1,
        "statement": "L'article 22 encadre les décisions automatisées.",
        "has_kg_support": true,
        "is_conflict": false,
        "supports": [
          {
            "relation_type": "PART_OF",
            "source_concept_id": "uuid",
            "target_concept_id": "uuid2",
            "edge_confidence": 0.82,
            "canonical_relation_id": "cr_123",
            "source_refs": ["fra_bias_discrimination_ai:slides12-15"]
          }
        ]
      }
    ]
  },

  "coverage_map": {
    "domains": [
      { "domain": "RGPD", "status": "covered", "epistemic_state": "ESTABLISHED", "relations_count": 8 },
      { "domain": "Jurisprudence", "status": "not_covered", "epistemic_state": "INCOMPLETE", "relations_count": 0 }
    ],
    "coverage_percent": 67,
    "recommendations": ["Jurisprudence", "Sanctions CNIL"]
  },

  "exploration_intelligence": {
    "research_axes": [
      {
        "axis_id": "ax_001",
        "role": "actionnable",
        "short_label": "Prérequis DPO",
        "full_question": "Pour mettre en œuvre Article 22 RGPD, quels prérequis faut-il prévoir, notamment DPO ?",
        "source_concept": "Article 22 RGPD",
        "target_concept": "DPO",
        "relation_type": "REQUIRES",
        "relevance_score": 0.87,
        "confidence": 0.87,
        "explainer_trace": "Article 22 RGPD —REQUIRES→ DPO (conf 0.87)",
        "search_query": "DPO Article 22 RGPD prérequis"
      }
    ],
    "concept_explanations": {},
    "suggested_questions": []
  }
}
```

### Champs Obligatoires vs Optionnels

| Champ | Obligatoire | Description |
|-------|-------------|-------------|
| `confidence.epistemic_state` | ✅ | État épistémique calculé par Confidence Engine |
| `confidence.contract_state` | ✅ | État contractuel depuis DomainContext |
| `confidence.kg_signals` | ✅ | Métriques KG pour audit |
| `proof_summary` | ✅ | Résumé pour Bloc B |
| `reasoning_trace` | ⚠️ | Optionnel si pas de relations typées |
| `coverage_map` | ⚠️ | Optionnel si DomainContext non configuré |
| `exploration_intelligence` | ⚠️ | Optionnel, enrichissement UX |

---

## Résumé des travaux

| Bloc | Complexité | Durée estimée | Prérequis |
|------|------------|---------------|-----------|
| A - Réponse | 🟢 Faible | 1-2h | Aucun |
| B - Knowledge Proof | 🟡 Moyenne | 1-2 jours | Aucun |
| C - Reasoning Trace | 🟡 Moyenne-Haute | 2-3 jours | Bloc B |
| D - Coverage Map | 🔴 Haute | 3-5 jours | Taxonomie domaines |

### Ordre d'implémentation recommandé

1. **Phase 1** : Bloc A + Bloc B (impact immédiat, données disponibles)
2. **Phase 2** : Bloc C (trace de raisonnement)
3. **Phase 3** : Bloc D (nécessite taxonomie domaines)

### Dépendances techniques

```
Bloc A (Réponse)
    └── Frontend uniquement

Bloc B (Knowledge Proof)
    ├── Backend: knowledge_proof_service.py
    ├── Requêtes Cypher sur CanonicalRelation
    └── Frontend: KnowledgeProofPanel.tsx

Bloc C (Reasoning Trace)
    ├── Backend: reasoning_trace_service.py
    ├── Dépend de Bloc B (concepts, relations)
    ├── Optionnel: LLM pour narrativisation
    └── Frontend: ReasoningTracePanel.tsx

Bloc D (Coverage Map)
    ├── Prérequis: Taxonomie de domaines
    ├── Backend: coverage_map_service.py
    ├── Backend: Extension domain_context_store.py
    └── Frontend: CoverageMapPanel.tsx
```

---

## Tests Unitaires - Truth Cases

### Objectif

Valider que le Confidence Engine est :
- **Déterministe** : mêmes entrées = mêmes sorties
- **Stable** : pas de flapping entre états
- **Non "gadget métrique"** : les seuils ont un sens produit

### Tests Épistémiques (6 cas essentiels)

```python
import pytest
from confidence_engine import compute_epistemic_state, KGSignals, EpistemicState

class TestEpistemicState:

    def test_no_edges_returns_incomplete(self):
        """Pas de relations typées → INCOMPLETE"""
        signals = KGSignals(
            typed_edges_count=0,
            avg_conf=0.0,
            validated_ratio=0.0,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=0,
            expected_edges_missing_count=0
        )
        assert compute_epistemic_state(signals) == EpistemicState.INCOMPLETE

    def test_conflict_dominates_everything(self):
        """Le conflit l'emporte même si toutes les autres métriques sont parfaites"""
        signals = KGSignals(
            typed_edges_count=10,
            avg_conf=0.95,
            validated_ratio=1.0,
            conflicts_count=1,  # UN SEUL conflit
            orphan_concepts_count=0,
            independent_sources_count=5,
            expected_edges_missing_count=0
        )
        assert compute_epistemic_state(signals) == EpistemicState.DEBATE

    def test_orphans_return_incomplete(self):
        """Concepts orphelins → INCOMPLETE"""
        signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=2,  # Orphelins
            independent_sources_count=3,
            expected_edges_missing_count=0
        )
        assert compute_epistemic_state(signals) == EpistemicState.INCOMPLETE

    def test_established_happy_path(self):
        """Toutes conditions réunies → ESTABLISHED"""
        signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0
        )
        assert compute_epistemic_state(signals) == EpistemicState.ESTABLISHED

    def test_partial_by_lack_of_sources(self):
        """Métriques OK mais une seule source → PARTIAL"""
        signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=1,  # Une seule source
            expected_edges_missing_count=0
        )
        assert compute_epistemic_state(signals) == EpistemicState.PARTIAL

    def test_incomplete_by_missing_expected(self):
        """Relations attendues manquantes → INCOMPLETE"""
        signals = KGSignals(
            typed_edges_count=5,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=3,
            expected_edges_missing_count=2  # Manques
        )
        assert compute_epistemic_state(signals) == EpistemicState.INCOMPLETE
```

### Tests Contractuels

```python
from confidence_engine import compute_contract_state, DomainSignals, ContractState

class TestContractState:

    def test_out_of_scope_does_not_change_epistemic(self):
        """OUT_OF_SCOPE ne modifie pas l'état épistémique"""
        # Un état ESTABLISHED reste ESTABLISHED même hors scope
        kg_signals = KGSignals(
            typed_edges_count=8,
            avg_conf=0.85,
            validated_ratio=0.80,
            conflicts_count=0,
            orphan_concepts_count=0,
            independent_sources_count=2,
            expected_edges_missing_count=0
        )
        domain_signals = DomainSignals(
            in_scope_domains=["Finance", "RH"],
            matched_domains=[],  # Pas de match
            contract_state=ContractState.OUT_OF_SCOPE
        )

        epistemic = compute_epistemic_state(kg_signals)
        contract = compute_contract_state(domain_signals)

        # Les deux états sont indépendants
        assert epistemic == EpistemicState.ESTABLISHED
        assert contract == ContractState.OUT_OF_SCOPE
```

### Tests UI Obligations

```python
class TestUIObligations:

    def test_debate_must_expose_conflict_list(self):
        """Si DEBATE, le Bloc B DOIT contenir au moins 1 conflit"""
        result = build_full_response(...)  # Mock avec DEBATE

        if result.confidence.epistemic_state == EpistemicState.DEBATE:
            assert result.proof_summary.contradictions_count >= 1
            # Le frontend DOIT afficher l'encart orange

    def test_incomplete_must_mark_trace_breaks(self):
        """Si INCOMPLETE, le Bloc C DOIT contenir au moins 1 étape non supportée"""
        result = build_full_response(...)  # Mock avec INCOMPLETE

        if result.confidence.epistemic_state == EpistemicState.INCOMPLETE:
            assert result.reasoning_trace.unsupported_steps_count >= 1
            # Le frontend DOIT afficher les étapes en pointillés
```

### Fichier de Tests

```
tests/
└── api/
    └── services/
        └── test_confidence_engine.py   # ← Ces tests
```

---

## Questions pour ChatGPT (Résolues)

Les questions ci-dessous ont été discutées et résolues lors de la session de design :

1. ✅ **Sur la taxonomie de domaines (Bloc D)** : Utiliser `DomainContext.sub_domains` en v0, enrichir avec LivingOntology plus tard, TaxonomyBuilder en v2.

2. ✅ **Sur le Reasoning Trace (Bloc C)** : Approche hybride - KG pour les supports (relations), LLM uniquement pour la phrase narrative.

3. ✅ **Sur le statut "Débat doctrinal"** : Détection via `CONFLICTS_WITH` dans le KG. Si conflit détecté → état DEBATE.

4. ✅ **Sur l'UX** : Bloc A toujours visible, Blocs B/C/D en accordéon avec indicateurs d'état visibles même fermés.

5. ✅ **Sur la performance** : Les requêtes Cypher sont batchées via UNWIND. Impact estimé < 50ms supplémentaires.

---

## Prochaines Étapes d'Implémentation

### Ordre Recommandé (Hyper Pragmatique)

1. **Phase 1** : Confidence Engine + Badge (A) + Proof Summary (B)
   - Impact immédiat, données disponibles
   - Fichiers : `confidence_engine.py`, `KnowledgeProofPanel.tsx`

2. **Phase 2** : Reasoning Trace (C)
   - Version hybride : KG pour supports, LLM pour phrases
   - Fichiers : `reasoning_trace_service.py`, `ReasoningTracePanel.tsx`

3. **Phase 3** : Coverage Map v0 (D)
   - Basé sur `DomainContext.sub_domains`
   - Fichiers : `coverage_map_service.py`, `CoverageMapPanel.tsx`

4. **Phase 4** : TaxonomyBuilder enrichit D sans casser l'UI

### Ce que ChatGPT a validé

> "Tu es en train de transformer un KG 'impressionnant' en un **outil de décision assumé et auditable**."

> "Le Coverage Map **ne concurrence pas** le TaxonomyBuilder. Il le **précède logiquement** et lui donne un **sens produit clair**."

> "Ce n'est pas juste de l'architecture. C'est une **chaîne de confiance explicite**."

---

## Design Principle (Conclusion)

> **"Osmos does not optimize for producing answers. Osmos optimizes for determining what it knows, why it knows it, and where its knowledge boundaries lie."**

Cette spécification implémente ce principe à travers :

| Principe | Implémentation |
|----------|----------------|
| **Déterminisme** | Confidence Engine basé sur règles KG, pas de ML |
| **Transparence** | 4 Blocs exposent chaque aspect de la connaissance |
| **Séparation des préoccupations** | Axe épistémique vs axe contractuel |
| **Auditabilité** | Trace de raisonnement avec supports KG |
| **Honnêteté** | INCOMPLETE/DEBATE/OUT_OF_SCOPE sont des états, pas des échecs |

**Ce document est le contrat entre le frontend et le backend pour l'écran Answer+Proof.**
