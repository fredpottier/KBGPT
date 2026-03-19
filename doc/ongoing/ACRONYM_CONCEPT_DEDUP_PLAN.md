# Plan — Dedup Acronyme ↔ Nom Complet (Concept Consolidation)

**Statut** : En attente de validation

## Contexte

Apres ingestion, le KG contient des entites fragmentees qui representent le meme concept :

```
PCT (32 claims) + Procalcitonin (14 claims) + Procalcitonin (PCT) (3 claims)
   + PCT level (21) + PCT levels (8) + PCT testing (6) + ...
= 51 entites pour UN concept, 114+ claims eparpillees
```

Ce pattern est **universel** (pas domain-specific) :
- Biomedical : PCT/Procalcitonin, CRP/C-Reactive Protein, FMT/Fecal Microbiota Transplantation
- SAP : BPC/Business Planning & Consolidation, BTP/Business Technology Platform
- Reglementaire : GDPR/General Data Protection Regulation, DPIA/Data Protection Impact Assessment
- Retail : SKU/Stock Keeping Unit, POS/Point of Sale

## Probleme observe (donnees reelles)

| Acronyme | Variantes | Claims totales | Impact |
|----------|-----------|----------------|--------|
| PCT | 51 entites | 114+ claims | Procalcitonin invisible en navigation |
| ICI | 10 entites | 151 claims | Immune Checkpoint Inhibitor fragmente |
| CRISPR | 22 entites | 63 claims | Concept cle completement eclate |
| CAR | 11 entites | 50 claims | Chimeric Antigen Receptor non consolide |
| FMT | 11 entites | 38 claims | Fecal Microbiota Transplantation eclate |

## 3 types de fragmentation

### Type 1 : Acronyme ↔ Nom complet
Le plus structurant. Pattern deja present dans le texte :
- `"Procalcitonin (PCT)"` → le document definit explicitement le lien
- `"Major Depressive Disorder (MDD)"` → idem

**Source de verite** : le corpus lui-meme (patterns `"Nom (ACRONYME)"` dans les claims)

### Type 2 : Variantes morphologiques
L'acronyme ou le nom complet est utilise avec des suffixes :
- `PCT level` / `PCT levels` / `PCT testing` / `PCT guidance`
- `CRISPR screens` / `CRISPR editing` / `CRISPR activation`

Le concept racine est le meme, les suffixes qualifient un usage.

### Type 3 : Phrases descriptives contenant le concept
Pas des concepts a part entiere, mais des fragments :
- `"Cancer patients with higher PCT levels"` → phrase, pas concept
- `"PCT <0.25 ng/ml"` → seuil clinique, pas le concept PCT

Deja couvert par L1 (InvalidEntityName) et L2 (WeakEntity).

## Architecture proposee

### Phase 1 — Extraction de la table acronyme ↔ expansion (deterministe)

**Source 1 : Mining du corpus (patterns dans les claims)**

Scanner toutes les entites et claims pour extraire les patterns :
- `"FullName (ACRONYME)"` → ex: `Procalcitonin (PCT)` → PCT = Procalcitonin
- `"ACRONYME (FullName)"` → ex: `GDPR (General Data Protection Regulation)`
- Variante avec tiret : `"CAR-T (Chimeric Antigen Receptor T-cell)"`

Regex domain-agnostic :
```python
# Pattern 1: Nom complet suivi de (ACRONYME)
EXPANSION_PATTERN = re.compile(
    r"^(.{5,80}?)\s*\(([A-Z][A-Za-z0-9\-/]{1,10})\)\s*$"
)
# Pattern 2: ACRONYME suivi de (Nom complet)
ACRONYM_FIRST_PATTERN = re.compile(
    r"^([A-Z]{2,8})\s*\((.{5,80}?)\)\s*$"
)
```

**Source 2 : Domain Context `common_acronyms`**

Le champ existant `common_acronyms` dans le DomainContextProfile :
```json
{"PCT": "Procalcitonin", "CRP": "C-Reactive Protein", ...}
```

**Source 3 : Entites existantes**

Les entites elles-memes contiennent parfois le pattern :
```
Entity name = "Procalcitonin (PCT)" → extrait PCT = Procalcitonin
Entity name = "C-reactive Protein (CRP)" → extrait CRP = C-reactive Protein
```

**Resultat** : une `AcronymMap` — dictionnaire `{acronyme: [expansions]}`

### Phase 2 — Clustering des variantes (deterministe)

Pour chaque entree de l'AcronymMap, regrouper toutes les entites qui :
1. Sont exactement l'acronyme : `PCT`
2. Sont exactement l'expansion : `Procalcitonin`
3. Sont le pattern complet : `Procalcitonin (PCT)`
4. Commencent par l'acronyme + espace : `PCT level`, `PCT testing`
5. Commencent par l'expansion + espace : `Procalcitonin-guided`, `Procalcitonin levels`

**Exclusions** :
- Ne PAS fusionner les entites qui contiennent l'acronyme comme sous-chaine d'un mot plus long (ex: `IMPACT` ne doit pas matcher `PCT`)
- Ne PAS fusionner si l'entite contient un verbe conjugue (c'est une phrase, pas un concept)
- Ne PAS fusionner les entites produit/tool specifiques (`AFIAS PCT measurement` = un produit, pas le concept PCT)

### Phase 3 — Proposition de consolidation (PROPOSED)

Pour chaque cluster, proposer :

**Action 1 : Creer/enrichir un CanonicalEntity**

Si aucun CanonicalEntity n'existe pour le cluster :
- Creer un CanonicalEntity avec `name = expansion` (nom complet), `aliases = [acronyme, pattern complet]`

Si un CanonicalEntity existe deja :
- Enrichir ses aliases avec l'acronyme et le nom complet

**Action 2 : MERGE_CANONICAL pour les entites du core**

Les entites "core" (acronyme pur + expansion pure + pattern complet) sont fusionnees vers le CanonicalEntity.

**Action 3 : Laisser les variantes morphologiques en l'etat (follow-up)**

`PCT level`, `PCT testing`, `CRISPR screens` restent des entites separees.
Elles seront liees au CanonicalEntity via SAME_CANON_AS mais pas fusionnees.
La fusion morphologique est un chantier plus complexe (Type 2) a traiter separement.

## Toutes les actions sont PROPOSED

Comme pour L3 axes, aucune auto-application :
- L'admin voit le cluster propose dans le tableau
- Il approuve, rejette, ou rollback

## Integration dans le systeme d'hygiene existant

### Option A : Nouvelle regle L2 `AcronymDedupRule`

Avantage : reutilise le framework existant (engine, persistence, UI, rollback).
L'action type est `MERGE_CANONICAL` (deja supporte).

### Option B : Module separe `src/knowbase/hygiene/acronym_resolver.py`

Avantage : separation de responsabilite, la logique est complexe.
Inconvenient : necessite de dupliquer le framework.

**Recommandation** : Option A — une regle L2 qui produit des `MERGE_CANONICAL` PROPOSED.

## Fichiers

### A creer

| Fichier | Description |
|---------|-------------|
| `src/knowbase/hygiene/acronym_map.py` | Extraction AcronymMap depuis corpus + Domain Context |
| `src/knowbase/hygiene/rules/acronym_dedup.py` | Regle L2 AcronymDedupRule |
| `tests/hygiene/test_acronym_dedup.py` | Tests |

### A modifier

| Fichier | Modification |
|---------|-------------|
| `src/knowbase/hygiene/engine.py` | Ajouter AcronymDedupRule dans _get_layer2_rules() |

## Schema de la AcronymMap

```python
@dataclass
class AcronymEntry:
    acronym: str              # "PCT"
    expansions: List[str]     # ["Procalcitonin", "procalcitonin"]
    sources: List[str]        # ["entity:Procalcitonin (PCT)", "domain_context"]
    confidence: float         # 1.0 si pattern explicite, 0.8 si domain_context seul

class AcronymMap:
    entries: Dict[str, AcronymEntry]  # clé = acronyme normalisé

    def build(neo4j_driver, tenant_id) -> "AcronymMap":
        # 1. Scanner les entités avec pattern "(ACRONYME)"
        # 2. Scanner les claims avec pattern "Expansion (ACRONYME)"
        # 3. Charger common_acronyms du Domain Context
        # 4. Deduplicer et merger les sources
```

## Logique de matching des variantes

```python
def find_cluster(acronym_entry, all_entities) -> List[Entity]:
    """Trouve toutes les entités liées à cet acronyme."""
    acr = acronym_entry.acronym      # "PCT"
    exp = acronym_entry.expansions   # ["Procalcitonin"]

    matches = []
    for entity in all_entities:
        name = entity.name

        # Core matches (fusionnables)
        if name == acr:                              # "PCT"
            matches.append((entity, "exact_acronym"))
        elif name.lower() in [e.lower() for e in exp]:  # "Procalcitonin"
            matches.append((entity, "exact_expansion"))
        elif EXPANSION_PATTERN.match(name):           # "Procalcitonin (PCT)"
            matches.append((entity, "pattern_match"))

        # Variant matches (liables mais pas fusionnables dans cette phase)
        elif name.startswith(acr + " "):              # "PCT level"
            matches.append((entity, "acronym_variant"))
        elif any(name.lower().startswith(e.lower() + " ") for e in exp):  # "Procalcitonin-guided"
            matches.append((entity, "expansion_variant"))

    return matches
```

## Points d'attention

1. **Domain-agnostic** : les regex ne referencent aucun domaine. Le mining de `"Nom (ACR)"` est universel.
2. **Pas de LLM** : Phase 1 et 2 sont 100% deterministes. Pas besoin de LLM pour etablir que `Procalcitonin (PCT)` definit PCT = Procalcitonin.
3. **Toujours PROPOSED** : MERGE_CANONICAL est structurant → jamais auto-apply.
4. **Multi-source** : l'AcronymMap combine corpus mining + Domain Context. Si le DomainContext dit PCT = Procalcitonin et que le corpus le confirme → confidence maximale.
5. **Ambiguite** : un acronyme peut avoir plusieurs expansions (ex: `CAR` = Chimeric Antigen Receptor OU Computer-Aided Research). L'AcronymMap stocke toutes les expansions. Le clustering ne fusionne que si une seule expansion est majoritaire.
6. **Variantes morphologiques hors scope** : `PCT level` / `PCT levels` restent des entites separees. Ils seront lies via SAME_CANON_AS mais la fusion morphologique est un follow-up.
7. **Phrases hors scope** : `"Cancer patients with higher PCT levels"` est une phrase, pas un concept. Deja couvert par L1/L2 entity rules.
8. **Rollback** : comme tout MERGE_CANONICAL, le rollback restaure l'entite absorbee depuis le before_state.

## Verification

1. Mining → AcronymMap contient au moins PCT→Procalcitonin, CRP→C-Reactive Protein, FMT→Fecal Microbiota Transplantation
2. Clustering → PCT cluster contient {PCT, Procalcitonin, Procalcitonin (PCT)} comme core
3. Dry run → MERGE_CANONICAL PROPOSED pour chaque cluster
4. Approve → CanonicalEntity "Procalcitonin" creee avec aliases ["PCT", "Procalcitonin (PCT)"]
5. Les variantes PCT level, PCT testing sont liees via SAME_CANON_AS (pas fusionnees)
6. Rollback → entites separees restaurees
7. Pas de faux positif : `IMPACT` ne matche pas `PCT`, `APC/T cell` ne matche pas `PCT`
