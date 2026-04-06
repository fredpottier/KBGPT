# ADR — KG Quality Pipeline V3 : Canonicalisation, Relations Evidence-First, Cross-Doc Reasoning

**Statut :** Draft
**Date :** 2026-03-27
**Auteurs :** Consensus Claude Opus + ChatGPT + Fred
**Contexte :** Audit qualite KG post-import 6 documents — Note D-/F

---

## Contexte

Apres import de 6 documents SAP (3 PDF + 3 PPTX) avec le pipeline ClaimFirst, le KG Neo4j presente des deficiences structurelles majeures :

- **42% entites orphelines** (sans aucun claim lie)
- **67% entites singletons** (1 seul claim)
- **Duplications massives** : SAP Fiori = 13 entites, ABAP = 16 variantes
- **82% typees "concept"** (fourre-tout LLM)
- **35 relations / 3550 claims = 1%** (graphe plat)
- **13 clusters multi-doc / 561 = 2.3%** (cross-doc quasi inexistant)
- **8 facettes toutes NULL**

Le RAG (Qdrant) est en bonne sante (note B+). Le KG est le goulot.

## Probleme

Le KG dans son etat actuel n'apporte pas de valeur ajoutee significative par rapport a un simple index vectoriel. Les fonctions avancees (cross-doc, contradictions, evolutions, facettes) sont essentiellement vides. Comment rehausser la qualite epistemique du KG sans casser le contrat de verite documentaire d'OSMOSIS ?

## Principes directeurs

### P1 — Proposer localement, promouvoir sous gouvernance
Le LLM peut observer et proposer (claims, entites, relations candidates). Mais aucune sortie ne devient connaissance OSMOSIS sans validation evidence-first, ancrage documentaire et tracage explicite.

### P2 — Separation scope vs assertion
Co-presence dans un document ≠ relation semantique. Deux entites mentionnees dans le meme document ne sont pas necessairement liees. Seules les relations explicitement affirmees dans le texte sont structurantes.

### P3 — Suggested vs Promoted knowledge
Toute connaissance extraite a un statut de promotion :
- `CANDIDATE` : proposee par le LLM, non validee
- `VALIDATED` : passee les gates deterministes, consultable
- `PROMOTED` : structurante dans le KG, exploitee par la synthese

### P4 — Domain-agnostic core, domain-specific optional
Le noyau epistemique (types, relations, validation) reste universel. La specialisation metier est additive via Domain Context / Packs, jamais structurante.

### P5 — Tracabilite de la methode d'extraction
Chaque artefact porte sa provenance :
```
extraction_method: PATTERN | LLM | HYBRID | DETERMINISTIC
assertion_kind: EXPLICIT | DISCURSIVE | INFERRED
evidence_bundle: {spans, quotes, doc_item_ids}
support_strength: float [0-1]
```

---

## Chantier 1 — Canonicalisation renforcee

**Objectif :** Fusionner les variantes d'entites (13 Fiori → 1, 16 ABAP → 2-3)
**Risque :** Bas
**Impact :** Tres fort

### Phase 1.1 — Exact dedup deterministe (cout zero)
```
1. Normaliser : lower, strip, NFKD, remove punctuation
2. Fusionner les entites avec le meme nom normalise
3. Table acronyme → expansion (extraite du corpus)
Reduction estimee : 30-40% des doublons
```

### Phase 1.2 — Token-based blocking (remplace prefix blocking)
```
1. Tokeniser chaque entite : {"sap", "fiori", "launchpad"}
2. Index inverse token → [entity_ids]
3. Filtrer les tokens trop frequents (> 50 occurrences : "sap", "system")
4. Les entites partageant >= 1 token significatif = candidates
```
Capture les 13 variantes "SAP Fiori" en une passe via le token "fiori".

### Phase 1.3 — Embedding clustering + LLM par cluster
```
1. Encoder toutes les entites (embedding e5-large)
2. Agglomerative clustering (cosine >= 0.85) ou HDBSCAN
3. Pour chaque cluster > 1 entite :
   - 1 appel LLM avec TOUS les noms + contexte (claims, voisins)
   - Le LLM retourne les sous-groupes + nom canonique
4. Union-Find pour propager les decisions transitives
```
Cout : ~100-200 appels LLM (vs milliers en pairwise).

### Invariants canonicalisation
- **Conserver TOUTES les formes originales** comme aliases
- **Versionner les decisions** de merge (tracabilite)
- **Jamais de destruction irreversible** : merge logique, pas physique
- **Score de canonicalisation** : `canonical_confidence: float`
- **Statut** : `canonical_candidate` vs `canonical_validated`

---

## Chantier 2 — Epistemic Type Guidance

**Objectif :** Passer de 82% "concept" a une distribution discriminante
**Risque :** Bas
**Impact :** Fort

### Couche 1 — Types universels (agnostiques)

Cadre de lecture documentaire, pas ontologie metier :

```yaml
universal_types:
  artifact:
    definition: "Produit logiciel, composant, module identifiable par un nom"
    signals: ["nom propre", "majuscules", "prefixe vendor"]
  protocol:
    definition: "Standard technique de communication ou securite"
    signals: ["acronyme technique", "version numerotee", "RFC/ISO"]
  role:
    definition: "Acteur humain ou systemique identifie par une fonction"
    signals: ["administrator", "user", "service", "agent"]
  capability:
    definition: "Fonction ou fonctionnalite offerte par un systeme"
    signals: ["verbe d'action nominalise", "feature", "support for"]
  metric:
    definition: "Mesure quantifiable, seuil, SLA"
    signals: ["nombre", "unite", "threshold", "limit"]
  regulation:
    definition: "Norme legale, standard de conformite"
    signals: ["GDPR", "ISO", "compliance", "regulation"]
  configuration:
    definition: "Parametre, reglage, mode operationnel"
    signals: ["enable/disable", "parameter", "setting"]
  unknown:
    definition: "Type non determinable avec confiance suffisante"
```

### Couche 2 — Hints domaine optionnels (via Domain Context)
Actives par pack, jamais obligatoires, jamais structurants pour la verite primaire.

### Metadata de typage
```
type_confidence: float [0-1]
type_source: LLM | RULE | INFERRED
type_override: null | admin_assigned
```

### Quand typer
**Apres la canonicalisation** — le LLM voit le nom canonique + tous les aliases + les claims associes, ce qui donne beaucoup plus de contexte.

---

## Chantier 3 — Garbage collection + Entity status

**Objectif :** Eliminer le bruit (42% orphelins, generiques) sans perte irreversible
**Risque :** Bas
**Impact :** Moyen

### Regle 1 — Entites generiques
Si un nom d'entite est mono-token ET nom commun generique → marquer, pas supprimer :
```
entity_status: VALID | NOISY | UNCERTAIN | ARCHIVED
```
Exemples NOISY : "access", "logging", "validation", "check"

### Regle 2 — Orphelins
Entites sans claims apres 30 jours → `ARCHIVED`
Entites avec claims mais sans relations → `UNCERTAIN` (pas de suppression)

### Regle 3 — Retroactive linking
Parcourir les claims existants et re-linker les mentions vers les entites canoniques (regex + fuzzy matching sur entity names + aliases).

### Regle 4 — Salience scoring
```
salience = TF-IDF(entity_name, corpus)
Si salience < seuil → candidat NOISY
Si salience > seuil ET multi-doc → candidat PROMOTED
```

---

## Chantier 4 — Relations evidence-first

**Objectif :** Passer de 35 a 500+ relations defensibles
**Risque :** Moyen (necessite gouvernance stricte)
**Impact :** Tres fort

### Taxonomie de relations (universelle)

```yaml
# Intra-document (co-located, evidence locale)
ELABORATES:     "Claim A detaille Claim B"
EXEMPLIFIES:    "Claim A est un exemple concret de Claim B"
REQUIRES:       "A necessite B (prerequis explicite dans le texte)"
CONFIGURES:     "Procedure A configure composant B"
SECURES:        "Mesure A protege composant B"

# Cross-document (semantic, via pivot canonique)
COMPLEMENTS:    "Information complementaire sur le meme sujet"
SPECIALIZES:    "Version plus specifique d'un fait general"
CONFLICTS:      "Contradiction factuelle entre deux assertions"
EVOLVES_TO:     "Version ulterieure qui remplace/modifie"

# Existants (garder)
REFINES:        "Precise / affine"
QUALIFIES:      "Ajoute une condition / nuance"
CONTRADICTS:    "Contradiction (LLM-arbitered, evidence-locked)"
```

### Classification obligatoire de chaque relation

```
relation_scope:
  ASSERTION_LEVEL    # Explicite dans le texte, citable
  LOCAL_CONTEXT      # Meme phrase / meme bloc, inferable
  DOCUMENT_SCOPE     # Co-presence uniquement

promotion_level:
  NONE               # Candidate rejetee
  WEAK               # Consultable mais non structurante
  STRONG             # Structurante dans le KG

extraction_method: PATTERN | LLM | HYBRID
assertion_kind: EXPLICIT | DISCURSIVE
evidence_bundle: {spans, quotes, doc_item_ids}
support_strength: float [0-1]
```

### Regle structurante
**Seules les relations `relation_scope = ASSERTION_LEVEL` et `promotion_level = STRONG` sont structurantes dans le KG.** Les autres servent a la navigation et a l'audit, mais pas a la synthese.

### Pipeline d'extraction

**Phase 4a — Pass d'observation local (pendant ingestion)**
```
Pour chaque chunk :
  LLM retourne un objet de travail (PAS des verites promues) :
    - candidate_assertions[]
    - candidate_entities[]
    - candidate_local_relations[]
    - rhetorical_role
    - exact_quotes[]
    - ambiguity_score
```

**Phase 4b — Validation deterministe (post-LLM)**
```
Pour chaque relation candidate :
  1. Verbatim exact obligatoire (evidence_bundle non vide)
  2. Ancrage DocItem/SectionContext obligatoire
  3. Classification relation_scope
  4. Rejet si relation_scope = DOCUMENT_SCOPE uniquement
  5. Attribution promotion_level selon criteres
  6. Tracage extraction_method + assertion_kind
```

**Phase 4c — Pilot avant deploiement**
```
1. Sous-ensemble du corpus (1 doc PDF + 1 PPTX)
2. Comparaison avec pipeline actuel
3. Mesure taux faux positifs relationnels
4. Mesure taux relations sans evidence locale
5. Decision go/no-go avant generalisation
```

---

## Chantier 5 — Facettes (navigation layer)

**Objectif :** Reconstruire les facettes comme couche de navigation, pas de verite
**Risque :** Bas
**Impact :** Moyen

### Diagnostic
Les 8 facettes existantes ont `name = NULL`. Le script `rebuild_facets.py` echantillonne 10 claims par doc — insuffisant pour couvrir les themes.

### Actions
1. Diagnostiquer pourquoi les facettes sont NULL
2. Augmenter l'echantillon (50-100 claims par doc)
3. Traiter les facettes comme des **projections** (navigation) pas des verites
4. Separer explicitement la couche facettes de la couche relations semantiques

---

## Chantier 6 — Cross-doc reasoning par pivot canonique

**Objectif :** Exploiter les entites partagees cross-doc pour decouvrir les liens inter-documents
**Risque :** Moyen
**Impact :** Tres fort (differenciateur OSMOSIS)

### Principe
On ne cherche PAS des relations globales directement. On passe par les **entites canoniques** comme pivots.

### Pipeline

```
1. Pivot = entite canonique (ex: SAP S/4HANA, SAP Fiori, ABAP)
2. Regrouper les claims lies a ce pivot, par document
3. Pour chaque pivot avec claims multi-documents :
   a. Analyser les variations (valeurs differentes)
   b. Analyser les complements (informations additionnelles)
   c. Analyser les tensions (contradictions potentielles)
4. Generer des relations cross-doc typees :
   - COMPLEMENTS (doc A et doc B apportent des infos complementaires)
   - SPECIALIZES (doc A donne un detail que doc B generalise)
   - CONFLICTS (doc A et doc B affirment des choses contradictoires)
   - EVOLVES_TO (doc A est une version anterieure de doc B)
5. Memes regles de promotion que Chantier 4 :
   - evidence_bundle obligatoire
   - relation_scope classification
   - promotion_level
```

### Alignement OSMOSIS
Coherent avec :
- L'architecture ClaimKey-centric existante
- La roadmap contradiction intelligence
- Le North Star "verite documentaire contextualisee"
- L'idee que les documents se "parlent" via des pivots partages

---

## Ordre d'implementation

| Phase | Chantier | Effort | Prerequis |
|-------|----------|--------|-----------|
| Sprint A | C1 Canonicalisation | 4h | Aucun |
| Sprint A | C3 Garbage + status | 2h | C1 |
| Sprint A | C2 Epistemic typing | 2h | C1 |
| Sprint B | C5 Facettes | 2h | Aucun |
| Sprint B | C4 Relations (pilot) | 8h | C1+C2 |
| Sprint C | C6 Cross-doc reasoning | 8h | C1+C4 |
| Sprint C | C4 Relations (generalisation) | 4h | C4 pilot OK |

Sprint A = quick wins, risque bas, impact immediat
Sprint B = fondations relations + navigation
Sprint C = differenciateur OSMOSIS

---

## Non-goals

1. **Pas d'ontologie metier hardcodee** — le noyau reste agnostique
2. **Pas de densification brute** — plus de relations ≠ meilleur KG
3. **Pas de co-localisation de decision de verite** — le LLM propose, le systeme dispose
4. **Pas de suppression irreversible** — statuts, pas destructions
5. **Pas de link prediction** sur un graphe sparse — enrichir d'abord, predire ensuite

---

## References

- Audit qualite KG 2026-03-27 (3550 claims, 3615 entities, 35 relations)
- ADR Unite de Preuve vs Unite de Lecture
- Invariants OSMOSIS (INV-4, INV-5, INV-6, INV-25)
- Consensus Claude Opus + ChatGPT (2026-03-27)
- Microsoft GraphRAG (Edge et al., 2024)
- KAG (Ant Group, Liang et al., 2024)
- LightRAG (Zhuang et al., 2024)
- MatchGPT (Peeters & Bizer, VLDB 2024)
