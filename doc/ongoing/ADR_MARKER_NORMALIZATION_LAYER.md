# ADR: Marker Normalization Layer

**Status**: ✅ IMPLÉMENTÉ (~85%) - Janvier 2026
**Date**: 2025-01-05
**Authors**: Claude + ChatGPT (collaborative design)
**Reviewers**: Fred

---

## Implementation Status (Janvier 2026)

| Composant | Fichier | Status |
|-----------|---------|--------|
| **Phase 1: Cleanup** | | ✅ **COMPLET** |
| CandidateGate (filtrage faux positifs) | `extraction_v2/context/candidate_mining.py` | ✅ |
| **Phase 2: Schema Neo4j** | | ✅ **COMPLET** |
| MarkerStore basique | `consolidation/marker_store.py` | ✅ |
| MarkerKind enum | `consolidation/marker_store.py` | ✅ |
| DiffResult | `consolidation/marker_store.py` | ✅ |
| MarkerMention model | `consolidation/normalization/models.py` | ✅ |
| CanonicalMarker model | `consolidation/normalization/models.py` | ✅ |
| NormalizationStore | `consolidation/normalization/normalization_store.py` | ✅ |
| **Phase 3: Normalization Engine** | | ✅ **COMPLET** |
| Parser config YAML | `consolidation/normalization/normalization_engine.py` | ✅ |
| Moteur de règles (aliases + regex) | `consolidation/normalization/normalization_engine.py` | ✅ |
| Entity Anchor detection | `NormalizationEngine.find_entity_anchors()` | ✅ |
| Config YAML par défaut | `config/normalization/default.yaml` | ✅ |
| **Phase 4: UI/UX** | | ❌ **NON FAIT** |
| Endpoint `/markers/suggestions` | - | ❌ Non fait |
| Interface chat normalization | - | ❌ Non fait |
| Dashboard admin aliases | - | ❌ Non fait |
| **Phase 5: Feedback Loop** | | ❌ **NON FAIT** |
| Clustering automatique | - | ❌ Non fait |
| Métriques | - | ❌ Non fait |

**Ce qui est implémenté (Janvier 2026):**
```
consolidation/normalization/
├── __init__.py
├── models.py                    # MarkerMention, CanonicalMarker, NormalizationRule
├── normalization_store.py       # Gestion Neo4j (CRUD mentions/canoniques)
└── normalization_engine.py      # Moteur de règles + Entity Anchor detection

config/normalization/
└── default.yaml                 # Config par défaut (aliases, rules, blacklist)
```

- Architecture MarkerMention → CanonicalMarker complète
- NormalizationStore avec schema Neo4j (indexes, constraints)
- NormalizationEngine avec:
  - Parser config YAML
  - Moteur de règles regex avec templates
  - Entity Anchor detection depuis concepts du document
  - Blacklist pour faux positifs
  - Safe-by-default (UNRESOLVED si doute)

**Ce qui reste (UI/UX + Feedback Loop):**
- Endpoints API pour suggestions et administration
- Interface chat pour normaliser des markers
- Dashboard admin pour gérer les aliases
- Clustering automatique pour suggestions
- Métriques de couverture

---

## 1. Contexte

### 1.1 Probleme identifie

Le systeme de detection de markers (Document Structural Awareness Layer) extrait ce qui est **ecrit** dans les documents, pas ce qui est **semantiquement voulu**.

Exemples concrets du corpus actuel:

| Marker detecte | Probleme |
|----------------|----------|
| `Edition 2508` | Quel produit? (incomplet sans Entity Anchor) |
| `2508` | Annee ou version? De quel produit? (ambigu) |
| `PUBLIC 2025` | Melange deployment type + version (structure non-standard) |
| `1809` | Pourrait etre N produits differents (ambigu sans contexte) |
| `FPS03` | Patch de quelle version de base? (manque contexte) |

**Point cle** : On ne peut PAS deviner la "signification reelle" - seul le document
(via Entity Anchor) ou l'utilisateur (via config tenant) peut lever l'ambiguite.

### 1.2 Analyse des donnees Neo4j actuelles

**Markers existants** (UNWIND global_markers):
```
"Content 2": 5 docs     <- FAUX POSITIF (artefact)
"PUBLIC 3": 5 docs      <- FAUX POSITIF (artefact)
"2023": 2 docs          <- VALIDE mais incomplet
"Edition 2508": 2 docs  <- VALIDE mais incomplet
"PUBLIC 2025": 2 docs   <- PARTIELLEMENT valide
"based": 1 doc          <- FAUX POSITIF
"any": 1 doc            <- FAUX POSITIF
```

**Observation critique**: ~40% des markers actuels sont des faux positifs de l'ancien systeme (avant CandidateGate).

**Concepts "produit" disponibles** (potentiels Entity Anchors):
```
"SAP S/4HANA" (32 mentions)
"SAP S/4HANA Cloud Public Edition"
"SAP S/4HANA Cloud Private Edition"
"Connection to S/4HANA 2023"  <- Contient deja la version!
```

---

## 2. Decision

Implementer une **Marker Normalization Layer** separee avec:

1. **Stockage brut preserve** (MarkerMention)
2. **Normalisation configurable par tenant** (CanonicalMarker)
3. **Suggestions automatiques non-bloquantes**
4. **Interface via chat pour administration**

### 2.1 Architecture en couches

```
[Extraction agnostique]
         |
         v
  MarkerMention (raw)
         |
         v
[Normalization Layer]  <-- Config Tenant (aliases, rules)
         |
         v
  CanonicalMarker
```

### 2.2 Modele de donnees Neo4j

#### MarkerMention (nouveau noeud)
```cypher
(:MarkerMention {
  id: "mm_xxx",
  raw_text: "Edition 2508",           // Ce qui est ecrit
  lexical_shape: "entity_numeral",    // Type detecte
  source: "cover",                    // Ou dans le doc
  evidence: "...Feature Scope...",    // Contexte
  doc_id: "doc_xxx",
  confidence_extraction: 0.85,
  tenant_id: "default",
  created_at: datetime()
})
```

#### CanonicalMarker (nouveau noeud)
```cypher
(:CanonicalMarker {
  id: "cm_xxx",
  canonical_form: "ProductX 2023 Rev B",  // Forme normalisee (string)

  // DIMENSIONS (optionnel mais recommande pour markers complexes)
  // Permet de gerer "Clio 3 Phase 2", "iPhone 15 Pro Max", etc.
  dimensions: {
    generation: "2023",
    revision: "B"
  },

  marker_type: "product_version",         // OUVERT: version | edition | generation |
                                          //         standard_revision | model_year | etc.
  entity_anchor: "ProductX",              // Entite parente (du document)
  tenant_id: "default",
  created_by: "rule:regex_edition",       // Tracabilite
  created_at: datetime()
})
```

#### Relations
```cypher
// Lien mention -> canonique
(:MarkerMention)-[:CANONICALIZES_TO {
  rule_id: "rule_001",
  confidence: 0.9,
  applied_at: datetime()
}]->(:CanonicalMarker)

// Lien document -> mentions
(:Document)-[:HAS_MARKER_MENTION]->(:MarkerMention)

// Alias entre canoniques
(:CanonicalMarker)-[:HAS_ALIAS]->(:CanonicalMarker)
```

---

## 3. Regles de normalisation (ordre d'application)

### 3.1 Exact Alias (tenant mapping)
```yaml
aliases:
  "Edition 2508": "S/4HANA Cloud 2508"
  "PCE 2023": "S/4HANA Cloud Private Edition 2023"
  "1809": "S/4HANA 1809"
```

### 3.2 Regex Canonicalization (tenant rules)
```yaml
rules:
  - id: "rule_edition_year"
    pattern: "Edition\\s+(20\\d{2}|25\\d{2})"
    requires_entity: "S/4HANA"
    output: "{entity} {$1}"

  - id: "rule_fps"
    pattern: "FPS(\\d{2})"
    requires_entity: "S/4HANA"
    requires_base_version: true
    output: "{entity} {base_version} FPS{$1}"
```

### 3.3 Cluster Suggestion (offline, non-bloquant)
```
Suggestion: "Edition 2508" (2 docs) co-occurs with entity "SAP S/4HANA Cloud"
            -> Proposer normalisation vers "S/4HANA Cloud 2508"?
            [Approuver] [Ignorer] [Creer alias custom]
```

### 3.4 LLM Suggester (optionnel, jamais automatique)
Uniquement pour proposer des normalisations complexes, jamais pour appliquer.

---

## 4. Challenge de la proposition (analyse critique)

### 4.1 Points valides

| Aspect | Validation |
|--------|------------|
| Separation brut/canonique | ✅ Essentiel pour tracabilite |
| Entity Anchor | ✅ Les concepts "SAP S/4HANA" existent deja dans le KG |
| Config tenant (pas code) | ✅ Maintient l'agnosticisme du moteur |
| Suggest → Approve | ✅ Evite les faux positifs automatiques |

### 4.2 Risques identifies

| Risque | Impact | Mitigation |
|--------|--------|------------|
| **Over-normalization** | Fusionner des choses differentes (S/4HANA Cloud vs On-Premise) | Policy: `requires_entity` obligatoire pour patterns ambigus |
| **Entity Anchor manquant** | Certains docs n'ont pas de concept produit clair | Fallback: marker reste "unresolved" (acceptable) |
| **Explosion des aliases** | Maintenance difficile si trop de mappings | Limite: max 50 aliases par tenant, review obligatoire |
| **Performance** | Join supplementaire sur chaque requete | Index sur `canonical_form` + cache |

### 4.3 Cas problematiques du corpus actuel

**Cas 1: Marker ambigu sans Entity Anchor**
- Exemple: "2508" seul
- Probleme: Impossible de savoir a quel produit/variante ca correspond
- Solution: **Reste "unresolved"** - on ne devine pas, on attend l'Entity Anchor du document

**Cas 2: Marker partiel (FPS, SP, patch level)**
- Exemple: "FPS03" sans version de base
- Probleme: Un patch/feature pack sans sa version parente est ambigu
- Solution: `requires_base_version: true` → reste unresolved si contexte insuffisant

**Cas 3: Faux positifs historiques**
- Exemple: "Content 2", "PUBLIC 3", "Phase 1"
- Probleme: Artefacts d'extraction, polluent le KG
- Solution: Blacklist tenant-level + migration script

### 4.4 Principe fondamental : PAS DE DOMAIN-SPECIFIC DANS LE MOTEUR

**ATTENTION**: Les exemples de normalisation (SAP, versions, etc.) sont purement illustratifs.

Le moteur de normalisation :
- Ne contient AUCUNE regle metier hardcodee
- Ne connait PAS la semantique "S/4HANA Cloud = Private ou Public"
- S'appuie UNIQUEMENT sur :
  1. La config tenant (aliases, regles)
  2. L'Entity Anchor detecte DANS le document

**Safe-by-default** : Si l'Entity Anchor est ambigu ou absent → marker reste "unresolved".
Un marker non-normalise est acceptable. Un marker mal-normalise est toxique.

### 4.5 Principe directeur (ajoute suite review ChatGPT)

> **La normalisation n'a pas pour objectif d'augmenter le recall.**
> **Elle a pour objectif d'augmenter la coherence.**

Cela signifie :
- On ne normalise PAS pour "trouver plus de resultats"
- On normalise pour que les resultats trouves soient FIABLES
- L'abstention (unresolved) est une information valide

### 4.6 Regle d'hygiene sur les aliases

Une normalisation ne doit **jamais corriger une ambiguite documentaire structurelle**.

| Scenario | Alias OK? | Raison |
|----------|-----------|--------|
| "Edition 2023" → "ProductX 2023" (entity unique dans doc) | ✅ Oui | Entity Anchor present |
| "Version 3" → "ProductX v3" (plusieurs entities possibles) | ❌ Non | Ambiguite non resolvable |
| "Rev B" → "ProductX Rev B" (entity unique) | ✅ Oui | Context suffisant |
| "2023" seul → "ProductX 2023" (guess) | ❌ Non | Pas d'entity, pure speculation |

Si un tenant accumule des aliases pour "compenser" des auteurs negligents,
la config devient une **dette cognitive deguisee**.

### 4.7 Validation multi-domaines (review ChatGPT)

L'ADR a ete teste conceptuellement sur des domaines NON-SAP :

| Domaine | Exemple | Entity Anchor | Resultat |
|---------|---------|---------------|----------|
| **Automobile** | "Clio 3 Phase 2" | Renault Clio | ✅ → "Renault Clio 3 Phase 2" |
| **Medical** | "ICD-10 Revision 2023" | ICD-10 | ✅ → "ICD-10 Revision 2023" |
| **Hardware** | "iPhone 15 Pro Max" | iPhone | ✅ → dimensions: {gen:15, tier:Pro, size:Max} |
| **Industrie** | "Pump Series X Gen II Rev B" | Pump Series X | ✅ → multi-dimensions |
| **Juridique** | "GDPR Article 5" | GDPR | ❌ Hors scope (reference, pas variante) |

**Conclusion** : L'ADR tient **sans connaissance domaine** - seule la structure compte.

### 4.8 Estimation d'impact sur le corpus actuel

```
Markers actuels:           21 uniques
- Faux positifs evidents:  ~8 (38%) -> A supprimer (blacklist)
- Potentiellement normalisables: ~8 (38%) -> Via config tenant SI entity anchor present
- Ambigus sans contexte:   ~5 (24%) -> Restent "unresolved" (acceptable)
```

---

## 5. Format de configuration tenant

```yaml
# config/marker_normalization.yaml
#
# IMPORTANT: Ce fichier est 100% tenant-specific.
# Les exemples ci-dessous sont ILLUSTRATIFS - chaque organisation
# definit ses propres regles selon son domaine metier.

version: "1.0"
tenant_id: "example_tenant"

# =============================================================
# ALIASES EXACTS (priorite haute)
# Mapping direct raw_marker → canonical_form
# Utiliser quand l'Entity Anchor est DEJA dans le marker
# =============================================================
aliases:
  # Format: "raw_marker": "canonical_form"
  # Exemples illustratifs (a adapter par tenant):
  "Edition 2023": "ProductName 2023"      # Si entity evidente
  "Model Year 24": "VehicleLine MY2024"   # Automotive example
  "Rev B": "ComponentX Revision B"        # Manufacturing example

# =============================================================
# REGLES REGEX (priorite moyenne)
# Patterns avec capture groups + Entity Anchor obligatoire
# =============================================================
rules:
  - id: "version_with_entity"
    description: "Annee/version seule + entity anchor du document"
    pattern: "^(\\d{4})$"                    # Capture une annee seule
    requires_entity: true                    # OBLIGATOIRE: entity doit exister dans le doc
    output_template: "{entity} {$1}"         # Ex: "ProductX" + "2023" → "ProductX 2023"
    confidence: 0.7

  - id: "edition_pattern"
    description: "Pattern 'Edition X' generique"
    pattern: "^Edition\\s+(.+)$"
    requires_entity: true
    output_template: "{entity} {$1}"
    confidence: 0.75

  - id: "patch_level"
    description: "Patch/SP/FPS avec version de base requise"
    pattern: "^(SP|FPS|Patch)(\\d+)$"
    requires_base_version: true              # Doit trouver une version parente dans le doc
    output_template: "{entity} {base_version} {$1}{$2}"
    confidence: 0.6

# =============================================================
# CONTRAINTES DE SECURITE
# =============================================================
constraints:
  # Si pas d'entity anchor → marker reste "unresolved"
  require_entity_for_ambiguous: true

  # Seuil de confiance pour application automatique
  # En dessous = suggestion seulement (humain decide)
  auto_apply_threshold: 0.95

  # Limite du nombre d'aliases (evite explosion)
  max_aliases: 100

  # Si plusieurs entities possibles → unresolved (pas de guess)
  single_entity_required: true

# =============================================================
# BLACKLIST (rejeter ces markers, jamais normaliser)
# Faux positifs connus du tenant
# =============================================================
blacklist:
  - "Content 2"     # Artefact extraction
  - "PUBLIC 3"      # Artefact extraction
  - "Level 2"       # Section document
  - "Phase 1"       # Etape projet, pas version
  - "Phase 2"
  - "Phase 3"
```

**Note critique** : Ce fichier YAML n'est PAS dans le code source.
Il est stocke/versionne par tenant et editable via l'UI admin ou le chat.

---

## 6. Implementation Plan

### Phase 1: Cleanup (pre-requis) ✅ DONE
- [x] CandidateGate avec filtres universels (dates, copyright, trimestres, etc.)
- [x] Validation que le CandidateGate fonctionne dans le pipeline

### Phase 2: Schema Neo4j ⚠️ PARTIEL
- [x] MarkerStore basique avec MarkerKind, DiffResult
- [x] API `/markers` pour consultation
- [ ] Creer les noeuds MarkerMention et CanonicalMarker (architecture à 2 niveaux)
- [ ] Migrer les `global_markers` existants vers MarkerMention
- [ ] Creer les indexes

### Phase 3: Normalization Engine ❌ NON FAIT
- [ ] Parser de config YAML (config/marker_normalization.yaml)
- [ ] Moteur de regles (aliases + regex)
- [ ] Detection d'Entity Anchor via concepts du document

### Phase 4: UI/UX ❌ NON FAIT
- [ ] Endpoint API `/markers/suggestions`
- [ ] Interface chat: "Normalise marker X en Y"
- [ ] Dashboard admin pour gerer les aliases

### Phase 5: Feedback Loop ❌ NON FAIT
- [ ] Clustering automatique pour suggestions
- [ ] Metriques: % markers resolus, % unresolved, % rejetes

---

## 7. Decision finale

**Adopter** l'architecture proposee avec les garde-fous suivants:

1. **Safe-by-default**: Si normalisation incertaine → reste "unresolved"
2. **Entity Anchor obligatoire** pour les markers ambigus (annees seules)
3. **Versioning + Audit** de toute modification de config
4. **Migration prealable** des faux positifs historiques

---

## 8. References

- ADR_DOCUMENT_STRUCTURAL_AWARENESS.md (Detection agnostique)
- ADR_ASSERTION_AWARE_KG.md (Architecture KG)
- Discussion Claude + ChatGPT (2025-01-05)
