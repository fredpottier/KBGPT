# ADR — Relations claim-vs-claim (Phase A2)

> **Status** : 🟢 Draft v1.2 (rédigé 2026-05-21, amendé v1.1 + v1.2 même jour suite 2 passes review Claude Web) — globalement validé par Fred, prêt à exécution A2.8-A2.12
> **Phase** : A2 (Refondation runtime KG-first — Relations claim-vs-claim explicites)
> **Rattaché à** : `doc/VISION.md` §4.3 étape 8 + `doc/EXECUTION_ROADMAP.md` §2 Phase A — A2 (incluant sous-chantier A2-PostImport)
> **Étend** : `doc/ongoing/adr/ADR_BITEMPOREL_CLAIMS.md` §9 addendum (règle supersession CAS 1-4)
> **Auteur** : Claude (rédaction sur base décisions Fred 2026-05-19) + Fred (validation)
> **Référence externe** : Zep/Graphiti (arxiv 2501.13956) §4 (relations temporelles entre faits)

**Changelog** :
- **v1.0** (2026-05-21 matin) — Draft initial. 4 questions structurelles tranchées (Q1-Q4) + §2.5 ConflictPending + 5 alternatives écartées.
- **v1.1** (2026-05-21 après 1ère review Claude Web) — Amendements de fond :
  - §2.1 + §2.2 : exclusion mutuelle physique `:SUPERSEDES` vs `:EVOLUTION_OF` (1 seule arête par paire, pattern Cypher `[:EVOLUTION_OF|SUPERSEDES]` standardisé)
  - §2.3 : règle défaut `valid_from_relation` distinguée symétrique vs directionnelle (corrige bug du `max(NULL, date)` qui produirait NULL au lieu de `B.valid_from`)
  - §2.5 (nouveau) : détection `marker_type='explicit'` — table de 12 marqueurs linguistiques universels (replaces, supersedes, abrogates, version N of, applies if, etc.) intégrée au prompt LLM d'adjudication
  - §2.6 (renuméroté) : schéma `:ConflictPending` explicité comme NODE séparé (pas property/relation directe) + justification design
  - §2.7 (nouveau) : 8 Gate criteria mesurables (G1-G8) avec requête Cypher et seuil par critère
  - §2.4 Phase A : Source 3 (pivot entity) et Source 4 (SPO join) détaillées avec seuils, filtres hub, et caps
- **v1.2** (2026-05-21 après 2ème review Claude Web) — 2 corrections :
  - §2.4 Phase C 4.2 : **incohérence critique** corrigée — supprimé le "Créer (B)-[:EVOLUTION_OF]->(A) ET (B)-[:SUPERSEDES]->(A)" qui contredisait l'exclusion mutuelle §2.1+§2.2. Désormais : SI CAS 1/2 §9.4 → `:SUPERSEDES` uniquement (l'arête `:EVOLUTION_OF` est implicite). SI ambigu (CAS 3/4) → `:EVOLUTION_OF` uniquement avec marker_type='prudence' + `:ConflictPending`.
  - §2.4 Phase A : clarification numérotation des sources. 3 sources A2 explicites (A2-1 cluster, A2-2 embedding, A2-3 pivot) + 1 source orthogonale (SPO-join, génère `:CHAINS_TO` séparément, n'alimente pas A2 mainline).

---

## 1. Contexte

### 1.1 Acquis Phase A1

Phase A1 a livré le **modèle bitemporel sur les Claims** (4 timestamps `valid_from / valid_until / ingested_at / invalidated_at` + `valid_from_marker ∈ {explicit, document_inherited, ingestion_fallback}`). KG actuel post-réingestion : **11 622 claims bitemporels** sur 38 DocumentContext, 100% de couverture `ingested_at` (Gate-B PASS, audit 2026-05-20).

ADR_BITEMPOREL §9 a tranché :
- **§9.1** Sémantique `valid_from = NULL` = "date inconnue, à traiter comme toujours valide jusqu'à preuve du contraire"
- **§9.3** Principe transverse "NULL > valeur probablement fausse"
- **§9.4** **Règle supersession CAS 1-4** sous incertitude (cf §3.2 ci-dessous)
- **§9.5** Cypher écriture invalidation avec `:SUPERSEDES`
- **§9.6** Dénormalisation `valid_from_marker` sur Claim (commit 8299b58)

### 1.2 Problème ouvert pour Phase A2

ADR_BITEMPOREL §9 n'a tranché que le cas **`:SUPERSEDES`**. Quatre questions structurelles restent ouvertes pour Phase A2 :

| Q | Question | Pourquoi maintenant |
|---|---|---|
| **Q1** | Sémantique précise des 5 relations cibles (`SAME_AS`, `EVOLUTION_OF`, `CONTRADICTS`, `REFINES`, `QUALIFIES`) — avec `marker_type` | Étape 8 du pipeline ingestion (VISION §4.3) doit classifier explicitement |
| **Q2** | Ambiguïté de nommage : `:SUPERSEDES` (§9.5) vs `:EVOLUTION_OF` (§3.3, mentions prospectives) vs `:EVOLVES_TO` (c6_pivots existant). Trois noms pour des concepts proches | Le KG actuel contient déjà des `:EVOLVES_TO` (c6_pivots step #14) sans timestamps. Faut harmoniser |
| **Q3** | Détection : qui produit quoi ? Le pipeline post-import a déjà 3 étapes qui font partiellement A2 : `detect_contradictions` (#7), `c4_relations` (#13), `c6_pivots` (#14). L'algo A2 mainline doit-il les remplacer ou les compléter ? | Cf audit `POST_IMPORT_AUDIT_2026-05-21.md` §3 (4 problèmes structurels identifiés) |
| **Q4** | Schéma timestamps sur les 5 relations claim-vs-claim. §9.5 traite uniquement `:SUPERSEDES`. À étendre | Sans timestamps relationnels, les queries point-in-time sur les relations sont ambigues quand un claim source est invalidé |

### 1.3 Contraintes héritées

- **Charte domain-agnostic stricte** : noms de relations universels (pas SAP-spécifiques). `:SUPERSEDES` ✅, `:DEPRECATES_BY_OPS_GUIDE` ❌
- **Charte open-source only** : LLM d'adjudication = Qwen3-235B (DeepInfra) / Llama-3.3-70B-Turbo (Together). Pas de Claude Haiku / GPT-4o-mini en runtime A2.
- **AX-1 (preuve localisable)** : toute relation créée par A2 doit porter `evidence_a` + `evidence_b` (verbatim spans des deux claims) ou un `:DETECTED_FROM_CLUSTER` vers le cluster source.
- **AX-3 (LLM evidence-locked)** : l'adjudication LLM doit voir les deux verbatim, pas inférer hors-texte.
- **Principe §9.3 NULL > valeur fausse** : si la classification n'est pas confiante, créer `:ConflictPending` plutôt que choisir au hasard entre 2 types.

---

## 2. Décisions

### 2.1 Décision Q1 — Vocabulaire des 5 relations claim-vs-claim

**5 relations canoniques** entre deux claims, sémantique stricte :

| Relation | Direction | Sémantique | Effet sur `invalidated_at` |
|---|---|---|---|
| **`:SAME_AS`** | A ↔ B (symétrique) | A et B affirment **la même chose** (même subject + même predicate + même object, paraphrase ou traduction) | Aucun (les deux restent actifs ; sert au déduplica retrieval) |
| **`:EVOLUTION_OF`** | B → A | B est une **version postérieure** de A (même subject + même predicate, object évolué). Cas où l'évolution ne se traduit PAS par une invalidation (les deux versions co-existent pour des contextes différents, ou `marker_type='prudence'` faute de signal temporel) | Aucun (B et A restent actifs) |
| **`:SUPERSEDES`** | B → A | B **invalide** A (règle §9.4 CAS 1 ou CAS 2 satisfaite, contradiction sémantique mesurée). **Sémantiquement** : sous-cas fort de l'évolution avec invalidation | **Setter `A.invalidated_at = datetime()`** et `A.valid_until = B.valid_from` |
| **`:CONTRADICTS`** | A ↔ B (symétrique) | A et B affirment des choses **incompatibles** sans qu'on puisse trancher temporellement (CAS 3, 4, ou contradiction intra-date) | Aucun direct — la relation `:CONTRADICTS` est créée ET en parallèle un nœud `:ConflictPending` (cf §2.6) pour exposition runtime |
| **`:REFINES`** | B → A | B **précise / restreint** A (même subject + même predicate, B ajoute des qualificateurs ou conditions) | Aucun (A reste valide en général, B précise un cas particulier) |
| **`:QUALIFIES`** | B → A | B **conditionne** A (ajoute un contexte d'applicabilité : "A est vrai SI condition X") | Aucun |

**Cardinalités** :
- `:SAME_AS` + `:CONTRADICTS` sont symétriques (1 seule relation entre A et B, peu importe la direction)
- `:EVOLUTION_OF` + `:SUPERSEDES` + `:REFINES` + `:QUALIFIES` sont directionnelles (B → A)
- Convention de direction : la relation pointe **de nouveau vers ancien** (B est la source, A est la cible)
- **Cardinalité physique entre `:EVOLUTION_OF` et `:SUPERSEDES`** : **exclusion mutuelle stricte par paire (A, B)**. Si CAS 1/2 §9.4 est satisfait → créer **uniquement** `:SUPERSEDES`. Sinon (CAS 3/4, ou pas de contradiction sémantique mesurée) → créer **uniquement** `:EVOLUTION_OF`. Pas de double arête (cf §2.2 ci-dessous + pattern Cypher runtime).

**Marker_type sur chaque relation** :

```cypher
{
  marker_type: 'explicit' | 'inferred' | 'prudence',
  detected_at: datetime(),
  detection_method: 'cluster_jaccard' | 'embedding_nli' | 'pivot_entity' | 'llm_arbitration',
  detection_source: 'detect_contradictions' | 'c4_relations' | 'c6_pivots' | 'a2_mainline',
  confidence: 0.0..1.0,
  evidence_a: '<verbatim span claim A>',
  evidence_b: '<verbatim span claim B>',
  reasoning: '<short LLM rationale, optional>'
}
```

| `marker_type` | Quand | Action runtime |
|---|---|---|
| `explicit` | Texte de B nomme A explicitement ("remplace X", "abroge Y", "voir aussi A", "version 2 de A") | Confiance haute → utiliser dans réponses sans flag |
| `inferred` | Pas de mention explicite, mais classification LLM avec confidence ≥ 0.85 et evidence solides | Confiance moyenne → utiliser avec mention "version inferred" |
| `prudence` | Confidence < 0.85, ou désaccord cluster vs LLM, ou CAS 3/4 ambigu | Confiance basse → créer `:ConflictPending`, ne pas appliquer `invalidated_at` |

### 2.2 Décision Q2 — Harmonisation nommage : `:SUPERSEDES` vs `:EVOLUTION_OF` vs `:EVOLVES_TO`

**Décision** :
1. **Garder `:SUPERSEDES`** comme nom canonique du cas fort (B invalide A, règle §9.4 CAS 1/2 satisfaite). Cohérent avec §9.5.
2. **Garder `:EVOLUTION_OF`** comme umbrella concept (B est une évolution de A, peut ou non superseder). Mentionné prospectivement dans §3.3 + §4.1.
3. **Renommer `:EVOLVES_TO` → `:EVOLUTION_OF`** dans tout le code et le KG. Migration documentée §3.2 ci-dessous.

**Hiérarchie sémantique (PAS physique)** : `:SUPERSEDES` est un sous-cas conceptuel de `:EVOLUTION_OF` (B est postérieur à A ET B invalide A). **Mais physiquement les deux relations sont mutuellement exclusives** sur une paire (A, B) donnée :
- si l'algo A2 conclut CAS 1 ou CAS 2 §9.4 → crée **uniquement** `:SUPERSEDES` (et `:EVOLUTION_OF` est implicite, jamais matérialisée)
- si l'algo A2 conclut "B est postérieur mais sans invalidation" (co-existence, ou `marker_type='prudence'`) → crée **uniquement** `:EVOLUTION_OF`
- si CAS 3/4 §9.4 ambigu → ne crée ni l'une ni l'autre, crée `:ConflictPending` (cf §2.6)

**Direction canonique** :
```
// Cas fort (invalidation) — UNE seule arête
(B {valid_from: '2026-10-12'}) -[:SUPERSEDES]-> (A {valid_from: '2023-03-15', invalidated_at: '2026-10-15'})

// Cas faible (évolution sans invalidation) — UNE seule arête
(B {valid_from: '2026-10-12'}) -[:EVOLUTION_OF {marker_type: 'inferred'}]-> (A {valid_from: '2023-03-15'})
// A.invalidated_at reste NULL, A et B co-existent
```

**Pattern Cypher runtime obligatoire** : pour récupérer "toute évolution de A vers B" (cas faible ET cas fort), utiliser l'union de types :
```cypher
// Récupérer tous les claims qui évoluent A (qu'ils invalident A ou non)
MATCH (b:Claim)-[r:EVOLUTION_OF|SUPERSEDES]->(a:Claim {claim_id: $a_id})
WHERE b.tenant_id = $tenant_id
RETURN b, r, type(r) AS evolution_type
```

À documenter dans le code runtime V5+ comme convention standard.

**Pourquoi pas `:EVOLVES_TO`** : le verbe `evolves_to` exprime A → B (présent vers futur), incohérent avec la direction "nouveau vers ancien" décidée pour les autres relations (§2.1). Le code `c6_pivots` actuel utilisera `:EVOLUTION_OF` après migration A2.10.

### 2.3 Décision Q4 — Schéma timestamps sur les relations claim-vs-claim

Toutes les relations claim-vs-claim portent **3 timestamps** systématiques (et 2 optionnels) :

| Property | Type | Quand | Sémantique |
|---|---|---|---|
| `detected_at` | DateTime | toujours | Timestamp pipeline qui a détecté la relation (équivalent `ingested_at` côté Claim) |
| `valid_from_relation` | DateTime nullable | toujours | Date à partir de laquelle la relation est vraie dans le monde réel. Règle de défaut **distincte selon symétrie** (cf tableau ci-dessous) |
| `invalidated_relation_at` | DateTime nullable | si l'un des claims est invalidé | Timestamp de la première invalidation d'un des claims source. Setté par hook claim-invalidate cascade |
| `confidence` | Float (0..1) | optionnel | Score LLM ou score combiné cluster + NLI |
| `marker_type` | Enum | toujours | Cf §2.1 ('explicit', 'inferred', 'prudence') |

**Règle de défaut `valid_from_relation`** — distincte symétrique vs directionnelle :

| Type relation | Direction | Défaut `valid_from_relation` | Justification |
|---|---|---|---|
| `:SAME_AS` | symétrique | `max(A.valid_from, B.valid_from)` (NULL si l'un est NULL) | La relation "A et B disent la même chose" devient comparable seulement quand les deux existent — donc à partir de la plus récente des deux |
| `:CONTRADICTS` | symétrique | `max(A.valid_from, B.valid_from)` (NULL si l'un est NULL) | Idem `:SAME_AS` |
| `:EVOLUTION_OF` | B → A | `B.valid_from` (date où l'évolution prend effet) | La relation matérialise "B est l'évolution de A" — prend effet au moment où B est valide. Si B.valid_from = NULL, alors `valid_from_relation = NULL` |
| `:SUPERSEDES` | B → A | `B.valid_from` (date où B remplace A) | Idem `:EVOLUTION_OF` — la supersession prend effet à la date de validité de B. Coïncide avec `A.valid_until = B.valid_from` setté par §9.5 |
| `:REFINES` | B → A | `B.valid_from` (date où la précision prend effet) | B précise A à partir du moment où B existe |
| `:QUALIFIES` | B → A | `B.valid_from` (date où le conditionnement prend effet) | B conditionne A à partir du moment où B existe |

**Important** : pour les relations directionnelles, le `valid_from_relation` est **strictement** `B.valid_from` (la source de la relation), **PAS** `max(A.valid_from, B.valid_from)`. Sinon dans l'exemple :
- A (valid_from=NULL) : "Produit X existe" — claim ancien, date inconnue
- B (valid_from=2025-01-01) : "Produit X est obsolète" — supersède A à partir de 2025-01-01
- `max(NULL, 2025-01-01) = NULL` ✗ (faux : la supersession DOIT être datée 2025-01-01)
- `B.valid_from = 2025-01-01` ✓ (correct)

L'algorithme A2 doit appliquer cette règle au moment de la création de la relation (cf §2.4 Phase D).

**Hook cascade `invalidated_relation_at`** : quand `claim.invalidated_at` est setté (par `:SUPERSEDES` ou autre cause), toutes les relations attachées au claim reçoivent `invalidated_relation_at = claim.invalidated_at` via Cypher cascade :

```cypher
MATCH (a:Claim {claim_id: $invalidated_id})
WITH a, a.invalidated_at AS inv_at
MATCH (a)-[r:SAME_AS|EVOLUTION_OF|CONTRADICTS|REFINES|QUALIFIES]-(b:Claim)
WHERE r.invalidated_relation_at IS NULL
SET r.invalidated_relation_at = inv_at
```

À exécuter en post-trigger de chaque invalidation.

### 2.4 Décision Q3 — Détection : ordre et déduplication

**Étapes existantes du pipeline post-import** :

| Étape | Produit | Conserver ? | Mapping vers A2 |
|---|---|---|---|
| #5 `cluster_cross_doc` (Jaccard, déterministe) | `(c:Claim)-[:IN_CLUSTER]->(cl:ClaimCluster)` | ✅ **Pré-requis A2** | Phase A : génère les paires candidates pour adjudication |
| #6 `chains_cross_doc` (SPO join, déterministe) | `(a)-[:CHAINS_TO]->(b)` | ✅ Garder mais ajouter timestamps (A2.9) | Capacité orthogonale à A2 — détecte des inférences logiques cross-doc, pas des relations claim-vs-claim au sens A2 |
| #7 `detect_contradictions` (LLM NLI Qwen3) | `:CONTRADICTS / :REFINES / :QUALIFIES` | ⚠️ **À refactorer en A2 mainline** | Devient le cœur de l'algo A2 (cf §2.4 ordre ci-dessous) |
| #13 `c4_relations` (embedding similarity + NLI adjudication) | `:CONTRADICTS / :REFINES / :QUALIFIES` + `:C4_SCANNED` markers | ⚠️ **Doublon partiel avec #7** | Fusionner avec #7 dans A2 mainline (cf §2.4 ordre) |
| #14 `c6_pivots` (entité pivot partagée) | `:COMPLEMENTS / :EVOLVES_TO / :SPECIALIZES` | ⚠️ **Renommer + intégrer A2** | `:EVOLVES_TO` → `:EVOLUTION_OF` (§2.2). `:COMPLEMENTS` / `:SPECIALIZES` deviennent des sous-cas de `:REFINES` ou `:QUALIFIES` (à mapper précisément lors de A2.10) |

**Ordre canonique de l'algo A2 mainline** :

```
1. PRÉ-REQUIS (déjà fait par post-import étapes 1, 2, 3, 4, 5, 9, 10) :
   - Canonical entities résolues (étape 1)
   - Facets attachées (étapes 2-4)
   - Clusters cross-doc Jaccard (étape 5)
   - Vector embeddings Neo4j (étape 9)
   - Claim-chunk bridge (étape 10)

2. A2 PHASE A — GÉNÉRATION DES PAIRES CANDIDATES (déterministe, no LLM)
   2.1 Charger tous les claims actifs (invalidated_at IS NULL)
   2.2 Pour chaque pair (A, B) candidat, **3 sources A2 alimentent l'adjudication LLM** :
        - **Source A2-1** : même cluster cross-doc (réutilise étape 5 cluster_cross_doc)
          → Jaccard sur tokens normalisés ≥ 0.70, mêmes filtres modalité/négation
        - **Source A2-2** : embedding cosine ≥ 0.85 (top-5 voisins via vector index étape 9)
          → utilise e5-large 1024d sur claim.text
        - **Source A2-3** : entité pivot canonical partagée (réutilise logique c6_pivots étape 14)
          → A et B ont ≥ 1 CanonicalEntity en commun mentionnée dans leur subject_canonical OU object_canonical
          → Filtre hub : exclure les CanonicalEntity avec degree > 200 claims (entités trop génériques, ex: "SAP", "system")
          → Cap : ≤ 3000 paires totales générées par cette source (hérité de c6_pivots)

   **Source orthogonale** (non-A2, gérée séparément) :
        - **SPO-join** déterministe (réutilise étape 6 chains_cross_doc)
          → A.subject_canonical == B.subject_canonical ET A.predicate == B.predicate
          → Produit la relation `:CHAINS_TO` (inférence logique cross-doc), **pas une relation claim-vs-claim au sens A2**.
          → Reste dans le pipeline post-import étape #6 indépendamment de l'algo A2 mainline (timestamps ajoutés en A2.9 par cohérence schéma §2.3, mais détection inchangée)

   2.3 Déduplication des paires issues des 3 sources A2 : 1 paire (A, B) unique avec tag `candidate_sources: ['cluster', 'embedding', 'pivot']` (liste des sources A2-1/2/3 qui ont remonté la paire). Permet pondération downstream (paire remontée par 3 sources = haute confiance pré-LLM).
   2.4 Cap MAX_PAIRS_PER_CLUSTER = 50 (anti-explosion combinatoire, hérité de #7)
   2.5 Skip via :C4_SCANNED markers : paire déjà adjudiquée dans un run précédent → ne pas re-soumettre LLM (idempotent, runs incrémentaux supportés)

3. A2 PHASE B — ADJUDICATION LLM (Qwen3-235B via FAST_CLASSIFICATION)
   3.1 Pour chaque paire : prompt NLI evidence-locked
   3.2 Output JSON : {relation_type ∈ {SAME_AS, EVOLUTION_OF, CONTRADICTS, REFINES, QUALIFIES, NONE},
                      confidence, evidence_a, evidence_b, reasoning}
   3.3 Filtre threshold (cf §2.1 marker_type) :
        - confidence ≥ 0.85 → marker_type = 'inferred' (ou 'explicit' si LLM détecte mention texte)
        - confidence < 0.85 → marker_type = 'prudence' (→ :ConflictPending au lieu de relation directe)

4. A2 PHASE C — APPLICATION RÈGLE SUPERSESSION (déterministe, basée §9.4)
   4.1 Pour chaque relation_type = CONTRADICTS classifiée :
        - Appliquer règle §9.4 CAS 1-4 sur (A, B) selon leurs (valid_from, valid_from_marker, ingested_at)
        - CAS 1 (B.valid_from > A.valid_from) ou CAS 2 (B.valid_from > A.ingested_at, A.valid_from=NULL) :
            → Créer (B)-[:SUPERSEDES]->(A) avec marker_type herité
            → Setter A.invalidated_at = datetime() + A.valid_until = B.valid_from
            → Cascade invalidated_relation_at sur les relations attachées à A (§2.3)
        - CAS 1 (égalité), CAS 3, CAS 4 :
            → Garder (A)-[:CONTRADICTS]-(B) symétrique
            → Créer :ConflictPending (cf §2.5)

   4.2 Pour relation_type = EVOLUTION_OF classifiée (avec contradiction sémantique sous-jacente détectée par LLM dans le claim B) :
        - SI règle §9.4 CAS 1 ou 2 satisfaite (B est forcément postérieur) :
            → Créer (B)-[:SUPERSEDES]->(A) **uniquement** (cas fort, l'arête :EVOLUTION_OF est implicite et n'est pas matérialisée — cf §2.1 + §2.2 exclusion mutuelle)
            → Setter A.invalidated_at = datetime() et A.valid_until = B.valid_from
            → Cascade `invalidated_relation_at` sur les autres relations attachées à A (§2.3)
        - SI ambigu (CAS 3, 4, ou égalité §9.4) :
            → Créer (B)-[:EVOLUTION_OF]->(A) **uniquement** avec marker_type='prudence'
            → NE PAS setter A.invalidated_at (B et A co-existent)
            → Créer aussi un (:ConflictPending {conflict_type: 'evolution_ambiguous'}) reliant A et B (§2.6)

       **Une seule arête entre A et B**, jamais les deux — l'invariant §2.1 + §2.2 est strict.

   4.3 Pour relation_type = SAME_AS / REFINES / QUALIFIES :
        - Créer la relation, aucune invalidation (les deux claims restent actifs)

5. A2 PHASE D — PERSISTANCE + MARQUEURS DE TRAÇAGE
   5.1 Pour chaque paire scannée (même rejetée NONE) : créer :C4_SCANNED marker (réutiliser convention #13)
        Permet runs incrémentaux : on ne re-scanne pas les paires déjà adjudiquées au prochain post-import
   5.2 Métriques : count par relation_type, latence p50/p95, taux d'invalidation A par tenant
```

**Fusion #7 + #13** : `detect_contradictions` (phase A formelle SPO + phase B LLM) et `c4_relations` (mining embedding + NLI) deviennent **un seul module `a2_relations`** dans le pipeline post-import. L'étape #7 absorbe les capacités de #13. L'étape #13 est dépréciée (REMOVE de STEPS[]) après migration. Étape #14 c6_pivots devient source d'inputs de l'algo A2 mainline plutôt qu'un détecteur indépendant.

**Décision sur les étapes orthogonales** :
- `cluster_cross_doc` (#5) : KEEP — pré-requis A2
- `chains_cross_doc` (#6) : KEEP avec timestamps (A2.9) — détecte des chaînes logiques cross-doc, orthogonal à A2 claim-vs-claim
- `detect_contradictions` (#7) : MODIFY → devient `a2_relations` (cœur algo A2)
- `c4_relations` (#13) : REMOVE après migration (absorbé par #7 refactoré)
- `c6_pivots` (#14) : MODIFY → devient `a2_relations_pivot_source` (Phase A2 source 3) + harmonise vocabulaire (`:EVOLVES_TO` → `:EVOLUTION_OF`)

### 2.5 Détection `marker_type = 'explicit'` — marqueurs linguistiques universels

L'algo A2 Phase B (adjudication LLM Qwen3-235B) inclut dans son prompt système la liste des **marqueurs linguistiques universels** suivants à détecter dans `evidence_b` (verbatim du claim B). Si l'un est trouvé ET pointe vers le sujet de A → `marker_type = 'explicit'`.

**Liste des marqueurs** (domain-agnostic, multilingue) :

| Verbe / pattern | Anglais | Français | Type relation impliqué |
|---|---|---|---|
| replaces / replaced by | replaces, is replaced by, replacement of | remplace, est remplacé par | `:SUPERSEDES` ou `:EVOLUTION_OF` |
| supersedes | supersedes, supersession of | supplante, supersède | `:SUPERSEDES` |
| abrogates / repeals | abrogates, repeals, revokes | abroge, révoque | `:SUPERSEDES` |
| deprecates | deprecates, is deprecated by, deprecated in favor of | déprécie, est obsolétisé par | `:SUPERSEDES` |
| obsoletes | obsoletes, makes obsolete | rend obsolète | `:SUPERSEDES` |
| version reference | version N of X, X v2, X (revised) | version N de X, X v2, X (révisé) | `:EVOLUTION_OF` |
| succeeds / follows | succeeds, follows from, builds upon | succède à, fait suite à, prolonge | `:EVOLUTION_OF` |
| amends | amends, amendment to, modifies | amende, modifie | `:REFINES` |
| extends / refines | extends, refines, narrows, specializes | étend, précise, restreint, spécialise | `:REFINES` |
| applies if / conditional | applies if, valid when, subject to, conditional on | s'applique si, valide quand, sous réserve de | `:QUALIFIES` |
| same / identical | same as, identical to, equivalent to | identique à, équivalent à | `:SAME_AS` |
| contradicts / conflicts | contradicts, conflicts with, inconsistent with | contredit, en conflit avec, incohérent avec | `:CONTRADICTS` |

**Prompt LLM** (à intégrer dans `a2_relations_adjudicator.py:_PROMPT_SYSTEM`) :

```
Detect explicit linguistic markers in claim B that reference claim A.
If found AND the marker points to A's subject:
  - set marker_type = 'explicit'
  - set detection_method = 'llm_explicit_marker'
  - cite the marker in 'reasoning'
Otherwise:
  - set marker_type = 'inferred' if confidence >= 0.85
  - set marker_type = 'prudence' if confidence < 0.85
```

**Cas universel** : applicable légal (abroge), médical (déprécie), technique (supersedes), aerospace (revised version), etc. Pas de liste corpus-spécifique.

### 2.6 Schéma `:ConflictPending` (extension §9.5)

§9.5 a introduit `:ConflictPending` pour les CAS 3-4 du `:SUPERSEDES`. On l'étend à tous les cas où la classification A2 est en `marker_type = 'prudence'` :

**Forme : NODE séparé**, relié par 2 arêtes `:INVOLVES` (PAS une relation directe entre claims, PAS une property booléenne sur une autre relation).

```cypher
CREATE (cp:ConflictPending {
    tenant_id: $tenant,
    conflict_id: randomUUID(),
    created_at: datetime(),
    resolution_status: 'unresolved',
    conflict_type: 'contradiction' | 'evolution_ambiguous' | 'low_confidence_classification',
    relation_classified: 'CONTRADICTS' | 'EVOLUTION_OF' | 'REFINES' | 'QUALIFIES',
    confidence: $score,
    detection_method: 'llm_arbitration',
    detected_at: datetime()
})
CREATE (cp)-[:INVOLVES {role: 'A'}]->(a:Claim {claim_id: $a_id})
CREATE (cp)-[:INVOLVES {role: 'B'}]->(b:Claim {claim_id: $b_id})
```

**Runtime exploitation** : le module `evaluate/` Phase A3 (cf ADR_PARSE_EVALUATE_RUNTIME à venir) consulte les `:ConflictPending` adjacents aux claims retournés et :
- Si conflict_type = `contradiction` → émet un signal UI "claims contradictoires non résolus" (transparence AX-5)
- Si conflict_type = `evolution_ambiguous` → propose les deux versions sans superseder (AX-1 traçabilité)
- Si conflict_type = `low_confidence_classification` → abstention motivée si critique pour la réponse (AX-14)

**Pas d'auto-résolution** : les `:ConflictPending` restent dans le KG indéfiniment. Un futur cycle A2 (avec nouveau corpus enrichi) peut les **résoudre** en mettant `resolution_status = 'resolved_by_<event>'` et `resolved_at`, mais ne supprime jamais le node.

**Pourquoi un node et pas une relation directe** :
- Permet d'attacher des metadata (`conflict_type`, `confidence`, `resolution_status`, `resolved_at`) sans alourdir les Claim ni multiplier les types de relations
- Permet de relier > 2 claims à un même conflit futur (ex: 3 claims contradictoires sur le même sujet)
- Permet à `evaluate/` Phase A3 de lister les `:ConflictPending` pendants par tenant pour exposition UI

### 2.7 Gate criteria Phase A2

Critères de validation post-implémentation A2, mesurés sur le KG après réingestion complète (A2.12) :

| # | Critère | Mesure Cypher | Cible |
|---|---|---|---|
| **G1** | Toutes les relations claim-vs-claim portent `detected_at` + `marker_type` | `MATCH ()-[r:SAME_AS\|EVOLUTION_OF\|SUPERSEDES\|CONTRADICTS\|REFINES\|QUALIFIES]-() WHERE r.detected_at IS NULL OR r.marker_type IS NULL RETURN count(r)` | **= 0** |
| **G2** | Cohérence `:SUPERSEDES` : 100% satisfont CAS 1 ou CAS 2 §9.4 (B est forcément postérieur) | `MATCH (b)-[r:SUPERSEDES]->(a) WHERE NOT ( (a.valid_from IS NOT NULL AND b.valid_from > a.valid_from) OR (a.valid_from IS NULL AND b.valid_from > a.ingested_at) ) RETURN count(r)` | **= 0** |
| **G3** | Pas de `:SUPERSEDES` avec `marker_type='prudence'` (par définition prudence → `:ConflictPending`, pas `:SUPERSEDES`) | `MATCH ()-[r:SUPERSEDES]->() WHERE r.marker_type = 'prudence' RETURN count(r)` | **= 0** |
| **G4** | Cascade `invalidated_relation_at` cohérente : 0 relation orpheline (claim source invalidé mais relation non timestampée) | `MATCH (a:Claim)-[r]-(b:Claim) WHERE a.invalidated_at IS NOT NULL AND r.invalidated_relation_at IS NULL AND type(r) IN ['SAME_AS','EVOLUTION_OF','SUPERSEDES','CONTRADICTS','REFINES','QUALIFIES'] RETURN count(r)` | **= 0** |
| **G5** | Couverture qualitative : sur 50 paires `(A, B)` partageant le même `subject_canonical`, ≥80% ont une relation explicite OU un `:ConflictPending` (vs paires "non-classifiées" qui resteraient sans signal) | Sample manuel + Cypher random 50 paires | **≥ 80%** |
| **G6** | Pas de `:EVOLVES_TO` résiduel post-migration A2.10 | `MATCH ()-[r:EVOLVES_TO]-() RETURN count(r)` | **= 0** |
| **G7** | Tous les `:ConflictPending` ont exactement 2 `:INVOLVES` (ou plus pour conflits multi-claims futurs, jamais 0 ou 1) | `MATCH (cp:ConflictPending) WITH cp, count{(cp)-[:INVOLVES]->()} AS n WHERE n < 2 RETURN count(cp)` | **= 0** |
| **G8** | Évidences présentes : 100% des relations directionnelles (`:EVOLUTION_OF / :SUPERSEDES / :REFINES / :QUALIFIES`) portent `evidence_a` ET `evidence_b` non-vides (sauf cas backfill historique pré-A2) | `MATCH ()-[r:EVOLUTION_OF\|SUPERSEDES\|REFINES\|QUALIFIES]-() WHERE r.detection_source <> 'backfill_pre_a2' AND (r.evidence_a IS NULL OR r.evidence_b IS NULL OR size(r.evidence_a) = 0 OR size(r.evidence_b) = 0) RETURN count(r)` | **= 0** |

**Action en cas d'échec gate** :
- G1, G3, G6, G7 : bug d'implémentation → diagnostiquer + fixer avant validation
- G2 : bug dans application règle §9.4 → re-vérifier algo Phase C 4.1
- G4 : bug dans cascade post-invalidation → vérifier trigger Cypher §2.3
- G5 : couverture insuffisante de l'adjudication → augmenter cap MAX_PAIRS_PER_CLUSTER ou élargir sources candidates §2.4
- G8 : prompt LLM ne ramène pas les verbatim → renforcer instruction + valider sur 10 échantillons

---

## 3. Plan de mise en œuvre

### 3.1 Mapping vers tasks backlog

| Task # | Title | Réf décision | Bloque |
|---|---|---|---|
| #333 | A2.0 — Rédiger ADR_PHASE_A2_RELATIONS_CLAIMS (= ce document) | — | A2.6-A2.12 |
| #326 | A2.6 — Cancel-flag dans run_pipeline_job | §2.4 quick win | — |
| #327 | A2.7 — Fix description c4_relations frontend STEPS[] | §2.4 quick win | ✅ Done |
| #328 | A2.8 — Setter invalidated_at post-detection | §2.4 Phase C 4.1 + 4.2 | A2.12 |
| #329 | A2.9 — Timestamps sur relations cross-claim | §2.3 schéma timestamps | A2.12 |
| #330 | A2.10 — Harmoniser :EVOLUTION_OF / :EVOLVES_TO | §2.2 + migration | A2.12 |
| #331 | A2.11 — Adapter critère archive_isolated post-ClaimFirst | indép. A2 (audit post-import §3.4) | — |
| #332 | A2.12 — Réingestion full + post-import propre | finalisation | — |

### 3.2 Plan de migration des relations existantes dans le KG

Le KG actuel contient (mesure à faire post-validation ADR) :
- `:CONTRADICTS / :REFINES / :QUALIFIES` créées par étape #7 (sans timestamps cf audit §3.2)
- `:EVOLVES_TO` créées par étape #14 (KG actuel : 9 étapes complétées, donc PAS encore créées sur ce corpus — pas de migration `:EVOLVES_TO` requise sur les 11622 claims)
- `:CHAINS_TO` créées par étape #6 (419 chaînes, sans timestamps cf audit §3.2)

**Script migration** (à inclure dans A2.9 + A2.10) :
```cypher
// Backfill timestamps sur relations cross-claim existantes
MATCH (a:Claim)-[r:CONTRADICTS|REFINES|QUALIFIES|CHAINS_TO]-(b:Claim)
WHERE a.tenant_id = 'default' AND b.tenant_id = 'default'
  AND r.detected_at IS NULL
SET r.detected_at = coalesce(r.created_at, a.ingested_at),
    r.valid_from_relation = CASE
        WHEN a.valid_from IS NOT NULL AND b.valid_from IS NOT NULL
        THEN apoc.coll.max([a.valid_from, b.valid_from])
        ELSE NULL
    END,
    r.marker_type = coalesce(r.marker_type, 'inferred')

// Cascade invalidated_relation_at sur relations attachées à claims déjà invalidés
MATCH (a:Claim)-[r]-(b:Claim)
WHERE a.invalidated_at IS NOT NULL AND r.invalidated_relation_at IS NULL
SET r.invalidated_relation_at = a.invalidated_at
```

### 3.3 Estimation effort

| Phase | Tasks | Durée |
|---|---|---|
| ADR (ce doc) + review Claude Web | #333 (A2.0) | 1-1.5j |
| Quick wins | #326 + #327 | 0.5j (#327 déjà done) |
| Refactor algo A2 mainline | #328 (invalidated_at setter) | 1.5j |
| Schéma timestamps + migration | #329 | 1j |
| Harmonisation EVOLUTION_OF | #330 | 1j |
| Adapter archive_isolated | #331 | 0.5j |
| Réingestion + validation | #332 | 1j |
| **Total Phase A2** | | **~6-7j effectifs** (cohérent avec 1 semaine annoncée roadmap §2 Phase A — A2) |

---

## 4. Conséquences

### 4.1 Conséquences positives

- ✅ **Vocabulaire unique** : 5 relations canoniques, plus de doublons (`:EVOLVES_TO` supprimé). Runtime simplifié.
- ✅ **Timestamps relationnels** : queries point-in-time sur les relations possibles ("quelles relations existaient au 2024-01-15 ?")
- ✅ **Règle invalidation déterministe** : §9.4 CAS 1-4 appliquée systématiquement, traçable, auditable
- ✅ **`:ConflictPending` typé** : runtime peut distinguer 3 niveaux de doute et adapter sa réponse (abstention motivée vs exposition transparente)
- ✅ **Pipeline post-import simplifié** : 15 étapes → 13 (fusion #7 + #13, intégration #14 dans a2_relations)
- ✅ **Marker_type explicite** : permet aux LLM downstream de pondérer confiance

### 4.2 Conséquences négatives (assumées)

- ⚠️ **Charge schéma Neo4j** : 5 propriétés par relation cross-claim × ~10K relations attendues = ~500 KB stockage. Négligeable.
- ⚠️ **Migration des relations existantes** : backfill Cypher sur ~5K relations actuelles (CONTRADICTS + CHAINS_TO + REFINES + QUALIFIES). 1 script idempotent (cf §3.2).
- ⚠️ **`:ConflictPending` accumulation** : sans mécanisme de résolution explicite, peut croître linéairement avec le corpus. Mitigation : politique de "review batch" trimestrielle.
- ⚠️ **Coût LLM A2 mainline** : Qwen3-235B sur ~5000 paires candidates × ~1500 tokens = ~$5-8 par réingestion full. Acceptable.

### 4.3 Risques mitigés

| Risque | Mitigation |
|---|---|
| LLM se trompe sur classification (false positive `:SUPERSEDES`) | `marker_type = 'prudence'` si confidence < 0.85 → pas d'invalidation, juste `:ConflictPending` |
| Faux positifs adjudication LLM (paire non liée classifiée CONTRADICTS) | Phase A déterministe (cluster + embedding cosine 0.85) filtre les paires hors-sujet **avant** LLM |
| Cascade `invalidated_relation_at` rate quand un claim est ré-invalidé | Idempotent : `SET r.invalidated_relation_at = inv_at` n'écrit que si NULL |
| `c4_relations` REMOVE casse les consumers existants | Aucun consumer trouvé (audit POST_IMPORT §3) hors UI admin step listing. Pas de retro-compat à gérer |

---

## 5. Alternatives écartées

### 5.1 Garder `:EVOLVES_TO` ET `:EVOLUTION_OF` comme synonymes

**Idée** : éviter migration en gardant les deux relations.
**Rejet** : viole le principe vocabulaire unique. Doublons → ambiguïté queries Cypher du runtime. Coût migration est faible (~500 EVOLVES_TO max à renommer post-A2.12).

### 5.2 Détecter SUPERSEDES indépendamment d'EVOLUTION_OF

**Idée** : `:SUPERSEDES` détecté par règle bitemporelle pure (§9.4), `:EVOLUTION_OF` détecté par LLM sur sémantique. Pas de hiérarchie entre les deux.
**Rejet** : crée des cas absurdes (B est EVOLUTION_OF mais pas SUPERSEDES ET B est plus récent que A) → ambiguïté pour le runtime. Hiérarchie `SUPERSEDES ⊆ EVOLUTION_OF` est plus claire.

### 5.3 Stocker `marker_type` au niveau relation type (créer 3 labels par relation)

**Idée** : `:SUPERSEDES_EXPLICIT`, `:SUPERSEDES_INFERRED`, `:SUPERSEDES_PRUDENCE` comme labels distincts au lieu de property.
**Rejet** : 15+ labels supplémentaires (5 relations × 3 marker_type), complexifie les queries (WHERE clauses par UNION de types). Property `marker_type` plus simple à filtrer.

### 5.4 Pas de `:ConflictPending` — choisir une relation par défaut en cas d'ambigu

**Idée** : si CAS 3-4, prendre l'arbitrage `ingested_at` (B.ingested_at > A.ingested_at → B supersede A).
**Rejet** : viole §9.4 ("`ingested_at` ne doit pas être arbitrage par défaut") et viole §9.3 (NULL > valeur fausse — ici on devine quand on ne sait pas).

### 5.5 Algo A2 entièrement déterministe (pas de LLM adjudication)

**Idée** : règles SPO + matching subject_canonical strict pour classifier les 5 relations sans LLM.
**Rejet** : impraticable pour CONTRADICTS subtiles (paraphrase, négation implicite), REFINES (qualificateurs contextuels), SAME_AS (paraphrase). Test antérieur (V3.3 `candidate_miner_v33`) avait montré ~30% precision. LLM NLI est nécessaire (cf c4_relations actuel ~85% precision).

---

## 6. Reviewers à solliciter

| Reviewer | Quoi | Priorité |
|---|---|---|
| **Fred (utilisateur)** | Validation décisions Q1-Q4 + alignement avec vision produit | **P0** — bloquant |
| **Claude Web** | Audit cohérence avec ADR_BITEMPOREL §9 + détection trous logiques | **P1** — recommandé |
| **ChatGPT (revue externe)** | Sanity check sur sémantique des 5 relations vs littérature KG temporels (Zep, VersionRAG) | **P2** — optionnel |

---

## 7. Liens

- `doc/VISION.md` §4.3 étape 8 (relations claim-vs-claim au pipeline ingestion)
- `doc/EXECUTION_ROADMAP.md` §2 Phase A — A2 (sous-chantier A2-PostImport ajouté 2026-05-21)
- `doc/ongoing/adr/ADR_BITEMPOREL_CLAIMS.md` §9 (addendum supersession)
- `doc/ongoing/POST_IMPORT_AUDIT_2026-05-21.md` (audit 15 étapes + 4 problèmes structurels)
- Code actuel : `src/knowbase/api/routers/post_import.py` (étapes #5, #6, #7, #13, #14)
- Code actuel : `src/knowbase/relations/{candidate_miner_c4,nli_adjudicator,relation_persister_c4}.py`
- Code actuel : `src/knowbase/claimfirst/clustering/relation_detector.py`

---

## 8. Status

| Acteur | Date | Verdict |
|---|---|---|
| Claude (rédaction) | 2026-05-21 | Draft v1.0 livré |
| Fred (validation produit) | TBD | À solliciter |
| Claude Web (review) | TBD | À solliciter post-validation Fred |

*Cet ADR est le pré-requis bloquant pour les tasks A2.8-A2.12. Toute modification au schéma cible (vocabulaire, timestamps, marker_type) doit passer par une nouvelle version de ce document.*
