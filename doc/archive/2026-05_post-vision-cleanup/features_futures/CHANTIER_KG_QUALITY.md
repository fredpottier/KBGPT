# Chantier Qualite KG OSMOSIS

**Statut** : C1 + C3 TERMINES. Benchmark RAGAS valide (faith +1pp, stable). Phase 3 en cours.
**Derniere mise a jour** : 31 mars 2026 (PM)

### Resultats Phase 2 (31 mars 2026)

| Metrique | Avant | Apres C1+C3 | Delta |
|---|---|---|---|
| Orphelines | 78% | 56% | -22pp |
| Entites VALID | ~25% | 59% (4343) | +34pp |
| NOISY marquees | 0 | 1053 (14%) | — |
| UNCERTAIN | 0 | 1934 (26%) | — |
| CanonicalEntity | 1783 | 2265 | +482 |

Scripts executes :
- `canonicalize_entities_cross_doc.py --execute` (C1.1 alias identity)
- `canonicalize_token_blocking.py --execute --min-jaccard 0.70` (C1.2)
- `canonicalize_embedding_clusters.py --execute --threshold 0.95` (C1.3)
- `cleanup_garbage_entities.py --execute` (C3)
**Sources archivees** : `doc/archive/pre-rationalization-2026-03/ongoing/ADR_KG_QUALITY_PIPELINE_V3.md`, `ACRONYM_CONCEPT_DEDUP_PLAN.md`, `doc/archive/pre-rationalization-2026-03/specs/graph/SPEC-PHASE2.12_ENTITY_RELATION_DISCOVERY_SPEC.md`, `doc/archive/pre-rationalization-2026-03/specs/ingestion/SPEC-CORPUS_CONSOLIDATION.md`

---

## 1. Diagnostic actuel

Apres import de 6 documents SAP (3 PDF + 3 PPTX) avec le pipeline ClaimFirst, le KG Neo4j presente des deficiences structurelles majeures :

| Indicateur | Valeur | Note |
|-----------|--------|------|
| Entites orphelines (sans aucun claim) | **42%** | D |
| Entites singletons (1 seul claim) | **67%** | D |
| Duplications massives | SAP Fiori = 13 entites, ABAP = 16 variantes | F |
| Typees "concept" (fourre-tout) | **82%** | D |
| Relations / claims | 35 / 3550 = **1%** | F |
| Clusters multi-doc / total | 13 / 561 = **2.3%** | F |
| Facettes | 8 facettes, toutes NULL | F |

**Conclusion** : le RAG (Qdrant) est en bonne sante (note B+). Le KG est le goulot.

### Cause racine

Le KG dans son etat actuel n'apporte pas de valeur ajoutee significative par rapport a un simple index vectoriel. Les fonctions avancees (cross-doc, contradictions, evolutions, facettes) sont essentiellement vides. Le pipeline d'extraction est document-centric alors que l'ambition est corpus-centric.

### Ce qui fonctionne (a preserver)

- Extraction segment-level avec evidence (`evidence_text` = 100%)
- Hard budgets ADR (8/segment, 150/doc)
- Fusion intra-document (26% de reduction Proto → Canonical)
- Module ER existant (CandidateFinder, PairScorer, DecisionRouter)
- 820 clusters cross-doc sur le corpus complet (31.3% des clusters)
- 20 relations CONTRADICTS cross-doc identifiees

---

## 2. Les 6 chantiers qualite V3

### C1 — Canonicalisation renforcee

**Objectif** : Fusionner les variantes d'entites (13 Fiori → 1, 16 ABAP → 2-3)
**Risque** : Bas | **Impact** : Tres fort

**Phase 1.1 — Exact dedup deterministe (cout zero)**
1. Normaliser : lower, strip, NFKD, remove punctuation
2. Fusionner les entites avec le meme nom normalise
3. Table acronyme → expansion (extraite du corpus)
- Reduction estimee : 30-40% des doublons

**Phase 1.2 — Token-based blocking**
1. Tokeniser chaque entite : {"sap", "fiori", "launchpad"}
2. Index inverse token → [entity_ids]
3. Filtrer les tokens trop frequents (> 50 occurrences)
4. Entites partageant >= 1 token significatif = candidates
- Capture les 13 variantes "SAP Fiori" en une passe via le token "fiori"

**Phase 1.3 — Embedding clustering + LLM par cluster**
1. Encoder toutes les entites (embedding e5-large)
2. Agglomerative clustering (cosine >= 0.85) ou HDBSCAN
3. Pour chaque cluster > 1 entite : 1 appel LLM avec tous les noms + contexte
4. Union-Find pour propager les decisions transitives
- Cout : ~100-200 appels LLM (vs milliers en pairwise)

**Validation par la litterature** : Cette structure en 3 phases (exact dedup → blocking → matching+clustering) est le pattern industriel standard pour l'entity resolution. References cles :
- **Splink** : record linkage probabiliste scalable (blocking + scoring), utilise en production pour deduplication sans identifiants uniques
- **Ditto** (2020/2021) : entity matching via Transformers — cast le probleme comme classification de paires, haute qualite sur cas ambigus
- **SC-Block** (ESWC 2024) : blocking contrastif supervise pour candidate sets compacts — pertinent si on a des pseudo-labels (les merges manuels de Phase 1.1 en fournissent)

Notre `compute_lex_key()` existant est le premier etage de blocking (Phase 1.1). Les Phases 1.2-1.3 ajoutent le matching fin.

**Invariants canonicalisation** :
- Conserver TOUTES les formes originales comme aliases
- Versionner les decisions de merge (tracabilite)
- Jamais de destruction irreversible : merge logique, pas physique
- Score : `canonical_confidence: float`, statut : `canonical_candidate` vs `canonical_validated`

### C2 — Epistemic Type Guidance

**Objectif** : Passer de 82% "concept" a une distribution discriminante
**Risque** : Bas | **Impact** : Fort

Types universels (agnostiques, pas ontologie metier) :

| Type | Definition | Signaux |
|------|-----------|---------|
| artifact | Produit logiciel, composant, module identifiable | Nom propre, majuscules, prefixe vendor |
| protocol | Standard technique de communication ou securite | Acronyme technique, version, RFC/ISO |
| role | Acteur humain ou systemique | administrator, user, service, agent |
| capability | Fonction ou fonctionnalite offerte par un systeme | Verbe d'action nominalise, feature |
| metric | Mesure quantifiable, seuil, SLA | Nombre, unite, threshold |
| regulation | Norme legale, standard de conformite | GDPR, ISO, compliance |
| configuration | Parametre, reglage, mode operationnel | enable/disable, parameter, setting |
| unknown | Type non determinable avec confiance suffisante | — |

Metadata de typage : `type_confidence: float`, `type_source: LLM | RULE | INFERRED`, `type_override: null | admin_assigned`.

**Quand typer** : apres la canonicalisation — le LLM voit le nom canonique + aliases + claims, beaucoup plus de contexte.

### C3 — Garbage collection + Entity status

**Objectif** : Eliminer le bruit (42% orphelins, generiques) sans perte irreversible
**Risque** : Bas | **Impact** : Moyen

**Statuts** : `VALID | NOISY | UNCERTAIN | ARCHIVED`

| Regle | Condition | Action |
|-------|-----------|--------|
| Entites generiques | Mono-token + nom commun generique ("access", "logging") | `NOISY` |
| Orphelins | Sans claims apres 30 jours | `ARCHIVED` |
| Sans relations | Claims mais sans relations | `UNCERTAIN` (pas de suppression) |
| Retroactive linking | Parcourir claims existants, re-linker mentions vers entites canoniques | `VALID` |
| Salience scoring | TF-IDF < seuil → `NOISY`, TF-IDF > seuil + multi-doc → candidat `PROMOTED` | Score |

### C4 — Relations evidence-first

**Objectif** : Passer de 35 a 500+ relations defensibles
**Risque** : Moyen (necessite gouvernance stricte) | **Impact** : Tres fort

**Taxonomie de relations (universelle)** :

Intra-document (evidence locale) :
- `ELABORATES`, `EXEMPLIFIES`, `REQUIRES`, `CONFIGURES`, `SECURES`

Cross-document (via pivot canonique) :
- `COMPLEMENTS`, `SPECIALIZES`, `CONFLICTS`, `EVOLVES_TO`

Existants (garder) : `REFINES`, `QUALIFIES`, `CONTRADICTS`

**Classification obligatoire de chaque relation** :

```
relation_scope:    ASSERTION_LEVEL | LOCAL_CONTEXT | DOCUMENT_SCOPE
promotion_level:   NONE | WEAK | STRONG
extraction_method: PATTERN | LLM | HYBRID
assertion_kind:    EXPLICIT | DISCURSIVE
evidence_bundle:   {spans, quotes, doc_item_ids}
support_strength:  float [0-1]
```

**Regle structurante** : seules les relations `ASSERTION_LEVEL` + `STRONG` sont structurantes dans le KG. Les autres servent a la navigation et a l'audit.

**Pipeline d'extraction en 3 phases** :
1. Pass d'observation local (pendant ingestion) : LLM retourne des candidats (PAS des verites)
2. Validation deterministe (post-LLM) : verbatim exact obligatoire, ancrage DocItem, classification scope
3. Pilot avant deploiement : sous-ensemble corpus, mesure taux faux positifs, go/no-go

### C5 — Facettes (navigation layer)

**Objectif** : Reconstruire les facettes comme couche de navigation (pas de verite)
**Risque** : Bas | **Impact** : Moyen

Diagnostic : les 8 facettes existantes ont `name = NULL`. Le script `rebuild_facets.py` echantillonne 10 claims par doc — insuffisant.

Actions : diagnostiquer les NULL, augmenter l'echantillon (50-100 claims/doc), traiter les facettes comme des projections de navigation.

Note : le FacetEngine V2 (voir CHANTIER_ATLAS.md) remplacera cette approche par des prototypes semantiques.

### C6 — Cross-doc reasoning par pivot canonique

**Objectif** : Exploiter les entites partagees cross-doc pour decouvrir les liens inter-documents
**Risque** : Moyen | **Impact** : Tres fort (differenciateur OSMOSIS)

**Principe** : on ne cherche pas des relations globales directement. On passe par les entites canoniques comme pivots.

**Pipeline** :
1. Pivot = entite canonique (ex: SAP S/4HANA, SAP Fiori)
2. Regrouper les claims lies a ce pivot, par document
3. Pour chaque pivot multi-documents : analyser variations, complements, tensions
4. Generer des relations cross-doc typees : COMPLEMENTS, SPECIALIZES, CONFLICTS, EVOLVES_TO
5. Memes regles de promotion que C4 (evidence_bundle obligatoire, promotion_level)

**Alignement** : coherent avec l'architecture ClaimKey-centric, la roadmap contradiction intelligence, et l'idee que les documents se "parlent" via des pivots partages.

---

## 3. Entity Resolution corpus-level (Phase 2.12)

### Architecture 3-patch

```
PATCH-ER (BLOQUANT)     PATCH-LINK (BLOQUANT)     PATCH-BUDGET (STRUCTURANT)
Entity Resolution        Corpus Linker              Allocation Ranked
Inter-Document           (Liens faibles)            + Coverage Floor
- Lexical (lex_key)      - CO_OCCURS_IN_CORPUS
- Semantic (embed)       - MENTIONED_IN_DOCUMENT
- Compat (type)
→ MERGED_INTO edges
```

### PATCH-ER — Entity Resolution Inter-Document

Un `CanonicalConcept` represente un concept unique dans le corpus. "GDPR" doit converger vers un seul noeud, sans whitelist metier.

**Algorithme a 3 etages** :

| Etage | Signal | Seuil auto | Seuil defer |
|-------|--------|-----------|-------------|
| Lexical | `lex_key` normalise (lower, strip, NFKD) | 0.98 | 0.85 |
| Semantique | Embedding similarity (e5-large) | 0.95 | 0.80 |
| Compatibilite | Type match | — | — |

**Merge reversible** : on ne supprime jamais de noeuds. On cree des relations `MERGED_INTO` avec score, raison, et flag `reversible: true`.

### PATCH-LINK — Liens faibles deterministes

- `CO_OCCURS_IN_CORPUS` : co-presence dans le meme document
- `MENTIONED_IN_DOCUMENT` : mention d'un concept dans un document

### PATCH-BUDGET — Allocation intelligente

Allocation ranked + coverage floor sans changer les hard budgets existants.

---

## 4. Deduplication acronymes

### Probleme observe (donnees reelles)

| Acronyme | Variantes | Claims totales |
|----------|-----------|----------------|
| PCT | 51 entites | 114+ claims |
| ICI | 10 entites | 151 claims |
| CRISPR | 22 entites | 63 claims |
| CAR | 11 entites | 50 claims |
| FMT | 11 entites | 38 claims |

Pattern universel (pas domain-specific) : SAP (BPC/Business Planning, BTP/Business Technology Platform), reglementaire (GDPR, DPIA), retail (SKU, POS).

### 3 types de fragmentation

| Type | Exemple | Traitement |
|------|---------|------------|
| Acronyme <-> Nom complet | `Procalcitonin (PCT)` | MERGE_CANONICAL (fusionnable) |
| Variantes morphologiques | `PCT level`, `PCT testing` | SAME_CANON_AS (liees, pas fusionnees) |
| Phrases descriptives | `Cancer patients with higher PCT levels` | L1/L2 entity rules (deja couvert) |

### Pipeline AcronymMap

**Phase 1 — Extraction table acronyme (deterministe)**

3 sources :
1. Mining du corpus : regex `"FullName (ACRONYME)"` et `"ACRONYME (FullName)"`
2. Domain Context `common_acronyms`
3. Entites existantes contenant le pattern

Resultat : `AcronymMap` — dictionnaire `{acronyme: [expansions, sources, confidence]}`

**Phase 2 — Clustering des variantes (deterministe)**

Pour chaque entree, regrouper : acronyme exact + expansion exacte + pattern complet + variantes commencant par l'acronyme/expansion + espace.

Exclusions : sous-chaine d'un mot plus long, verbe conjugue, entite produit/tool specifique.

**Phase 3 — Proposition de consolidation (PROPOSED)**

- Creer/enrichir CanonicalEntity (nom complet + aliases)
- MERGE_CANONICAL pour les entites core
- Variantes morphologiques liees via SAME_CANON_AS (pas fusionnees)
- **Toutes les actions sont PROPOSED** — l'admin approuve, rejette, ou rollback

### Integration

Nouvelle regle L2 `AcronymDedupRule` dans le framework d'hygiene existant, produisant des `MERGE_CANONICAL` PROPOSED.

---

## 5. Principes directeurs

### P1 — Proposer localement, promouvoir sous gouvernance

Le LLM peut observer et proposer (claims, entites, relations candidates). Aucune sortie ne devient connaissance OSMOSIS sans validation evidence-first, ancrage documentaire et tracage explicite.

### P2 — Separation scope vs assertion

Co-presence dans un document ≠ relation semantique. Deux entites mentionnees dans le meme document ne sont pas necessairement liees. Seules les relations explicitement affirmees dans le texte sont structurantes.

### P3 — Suggested vs Promoted knowledge

| Statut | Definition |
|--------|-----------|
| CANDIDATE | Proposee par le LLM, non validee |
| VALIDATED | Passee les gates deterministes, consultable |
| PROMOTED | Structurante dans le KG, exploitee par la synthese |

### P4 — Domain-agnostic core, domain-specific optional

Le noyau epistemique (types, relations, validation) reste universel. La specialisation metier est additive via Domain Context / Packs, jamais structurante.

### P5 — Tracabilite de la methode d'extraction

Chaque artefact porte :
- `extraction_method`: PATTERN | LLM | HYBRID | DETERMINISTIC
- `assertion_kind`: EXPLICIT | DISCURSIVE | INFERRED
- `evidence_bundle`: {spans, quotes, doc_item_ids}
- `support_strength`: float [0-1]

---

## 6. Plan d'execution

| Sprint | Chantier | Effort | Prerequis | Impact |
|--------|----------|--------|-----------|--------|
| **A** | C1 Canonicalisation | 4h | Aucun | Tres fort |
| **A** | C3 Garbage + status | 2h | C1 | Moyen |
| **A** | C2 Epistemic typing | 2h | C1 | Fort |
| **B** | C5 Facettes | 2h | Aucun | Moyen |
| **B** | C4 Relations (pilot) | 8h | C1+C2 | Tres fort |
| **C** | C6 Cross-doc reasoning | 8h | C1+C4 | Tres fort |
| **C** | C4 Relations (generalisation) | 4h | C4 pilot OK | Fort |

**Sprint A** = quick wins, risque bas, impact immediat
**Sprint B** = fondations relations + navigation
**Sprint C** = differenciateur OSMOSIS

### Dedup acronymes (transversal)

S'integre dans Sprint A apres C1 : la regle L2 AcronymDedupRule fonctionne sur les entites canonisees.

---

## 7. Travaux non termines

### Chantiers non demarres

Aucun des 6 chantiers n'est implemente. L'ADR est ecrit et le consensus est obtenu (Claude Opus + ChatGPT + Fred), mais l'implementation est bloquee par la priorite au re-chunking (voir CHANTIER_CHUNKING.md).

### Prerequis

1. **Re-ingestion complete** du corpus avec nouvelle strategie de chunking — les claims actuels sont extraits de DocItems atomiques, la re-extraction produira des claims plus riches
2. **Benchmark post re-chunking** pour mesurer l'impact avant d'investir dans le KG
3. La canonicalisation (C1) peut demarrer independamment du chunking

### Dependances entre chantiers

```
C1 Canonicalisation ──→ C2 Epistemic Types
         │                      │
         ├──→ C3 Garbage        │
         │                      ▼
         └──────────────→ C4 Relations (pilot)
                                │
                                ▼
                          C6 Cross-doc reasoning
                                │
                                ▼
                          C4 Relations (generalisation)

C5 Facettes ← independant (peut demarrer en parallele de C1)
```

### Non-goals

1. Pas d'ontologie metier hardcodee — le noyau reste agnostique
2. Pas de densification brute — plus de relations ≠ meilleur KG
3. Pas de co-localisation de decision de verite — le LLM propose, le systeme dispose
4. Pas de suppression irreversible — statuts, pas destructions
5. Pas de link prediction sur un graphe sparse — enrichir d'abord, predire ensuite

### Pistes a terme (horizon 3-6 mois)

Ces pistes deviennent pertinentes **apres** que C1-C3 ont densifie le KG :

| Piste | Prerequis | Quand | Impact attendu |
|-------|-----------|-------|----------------|
| **Leiden community clustering** | KG dense (singletons < 30%) | Apres Phase 2 complete | Clustering hierarchique des communautes thematiques. Permet un mode "global query" (a la GraphRAG) : router vers un sous-graphe pertinent au lieu de tout traverser. Base pour resumes par communaute au runtime. |
| **REBEL / InstructIE extraction** | Relations evidence-first (C4) actives | Apres Phase 3 | Extraction seq2seq structuree (triplets) en complement du pipeline ClaimFirst. Pertinent si le volume de relations extraites par LLM+regles est insuffisant. Necessite evidence-binding (REBEL ne fournit pas de preuves par defaut). |
| **NLI document-level (DocNLI)** | Relations CONTRADICTS fiables | Apres Phase 3 | Classificateur support/refute/unknown a granularite document. Calibre la detection de contradictions au-dela du matching lexical. Utile en complement de SciFact pour le benchmark contradiction. |
| **SciFact/SCIVER evaluation** | Benchmark contradictions mature | Apres Phase 3 benchmark | Cadre reproductible pour evaluer "support/refute with rationales" — alignement direct avec la promesse Decision Defense. Datasets publics pour calibration. |

### References academiques

- Microsoft GraphRAG (Edge et al., 2024) — KG, clustering Leiden, modes global/local, fallback baseline
- KAG (Ant Group, Liang et al., 2024)
- LightRAG (Zhuang et al., 2024)
- MatchGPT (Peeters & Bizer, VLDB 2024)
- Ditto (2020/2021) — entity matching Transformers
- SC-Block (ESWC 2024) — blocking contrastif supervise
- Splink — record linkage probabiliste scalable
- REBEL (Findings EMNLP 2021) — extraction relations seq2seq
- InstructIE/ODIE (EMNLP 2023) — extraction guidee par instruction
- SciFact (EMNLP 2020) + SCIVER — verification avec rationales
- DocNLI — NLI document-level pour contradiction detection
- Google KG, Microsoft Turing, Neo4j Research — pattern standard Entity Resolution → Relation Discovery
