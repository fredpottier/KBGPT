# ADR — Modèle bitemporel sur Claims (Phase A1)

> **Status** : ✅ Accepted (rédigé 2026-05-19, validé post-review Claude Web 2026-05-19 + amendements §2.2 / §3 / §4 / §6)
> **Phase** : A1 (Refondation runtime KG-first — Modèle bitemporel)
> **Rattaché à** : `doc/VISION.md` §3.2 (Bitemporel sur les claims) + `doc/EXECUTION_ROADMAP.md` §2 Phase A1
> **Kill switch** : Gate-B (cf §7.2 ROADMAP) — 100% des claims persistés doivent porter les 4 timestamps après cette phase
> **Auteur** : Fred (utilisateur produit)
> **Référence externe** : Zep/Graphiti (paper arxiv 2501.13956) — modèle bitemporal industriel ; VersionRAG (arxiv 2510.08109)
> **Reviewers** : Claude Web (2026-05-19) — verdict "production-ready" + 5 améliorations mineures + 1 spike de mitigation, tous intégrés dans cette version

---

## 1. Contexte et problème

### 1.1 Contexte

OSMOSIS ingère une documentation **hétérogène, multi-versions, parfois contradictoire** (cf VISION.md §1.1). La capacité **C3 (Raisonnement différentiel — évolution, lifecycle)** est mesurée actuellement à **0.25 sur SAP** (cf ROADMAP §1.1, bench 18/05/2026), très loin de la cible **≥80%**.

Le diagnostic structurel (cf VISION.md §6.4) identifie la cause racine :
- Le runtime V5.1 lit du texte via TF-IDF section-level sans aucune représentation **temporelle structurée** des claims
- Aucun moyen actuel de répondre à la question : *"Qu'était vrai au 15 janvier 2024 ?"* vs *"Qu'est vrai maintenant ?"*
- Aucun moyen actuel de tracer **quand un claim a été invalidé par un claim ultérieur**

### 1.2 Problème à résoudre

Comment représenter dans le KG (Neo4j) la **dimension temporelle des claims** de manière à :

1. **Distinguer la validité dans le monde réel** (event time) **vs la connaissance par le système** (transaction time)
2. **Préserver l'historique** : ne jamais supprimer un claim contredit, marquer son invalidation
3. **Répondre aux requêtes point-in-time** : "qu'était vrai à T ?" et "qu'est vrai maintenant ?"
4. **Offrir une base solide** aux relations claim-vs-claim de Phase A2 (`EVOLUTION_OF`, `CONTRADICTS`, `SAME_AS`)
5. **Rester conforme** à `AX-1` (preuve localisable), `AX-3` (LLM evidence-locked), `AX-7` (Neo4j = vérité)

### 1.3 État de l'art (référence)

Le **modèle bitemporel** est le standard industriel 2026 (Zep/Graphiti, papier arxiv 2501.13956 §3 ; VersionRAG arxiv 2510.08109) pour les KG temporels :

| Dimension | Sémantique |
|---|---|
| **Event Time** (`valid_from` / `valid_until`) | Quand le fait est vrai dans le monde réel |
| **Transaction Time** (`ingested_at` / `invalidated_at`) | Quand le système a appris ou invalidé le fait |

C'est le modèle prescrit par VISION.md §3.2.

---

## 2. Décision

### 2.1 Décision principale

**Tous les nœuds `:Claim` du KG porteront 4 timestamps obligatoires** :

```cypher
(:Claim {
   // ... champs existants (subject_canonical, predicate, value, claim_id, tenant_id, ...) ...
   valid_from:      DateTime,     // Event time start — quand le fait est vrai (obligatoire à l'ingestion)
   valid_until:     DateTime,     // Event time end — quand le fait n'est plus vrai (NULL si encore valide)
   ingested_at:     DateTime,     // Transaction time start — quand le système a appris le fait (obligatoire)
   invalidated_at:  DateTime      // Transaction time end — quand le système a invalidé le fait (NULL si actif)
})
```

### 2.2 Sémantique précise

| Timestamp | Type Neo4j | Nullable | Sémantique opérationnelle |
|---|---|---|---|
| `valid_from` | `DateTime` | **Oui** (NULL = "date inconnue, à traiter comme toujours valide jusqu'à preuve du contraire", cf §9.1) | Date à partir de laquelle le claim est vrai dans le monde réel. Cascade : (1) extraction explicite dans le claim, (2) héritage `document.valid_from` (qui peut lui-même être NULL si aucune source fiable détectée — voir §9.2), (3) NULL final accepté. **NULL est intentionnel et préférable à une valeur fausse** (cf principe §9.3). Le champ **`valid_from_marker`** (sur DocumentContext aujourd'hui ; à propager au Claim en pré-A2 cf §9.6) trace l'origine du `valid_from` (`explicit | document_inherited | ingestion_fallback`) et permet à la classification claim-vs-claim (`EVOLUTION_OF` / `CONTRADICTS`) de distinguer les claims fiables des claims sans signal |
| `valid_until` | `DateTime` | **Oui** | Date après laquelle le claim n'est plus vrai. `NULL` = encore actif dans le monde réel. Renseigné explicitement (marqueur textuel "expires", "until", "until vX.Y") OU implicitement (claim contradictoire dans doc plus récent → Phase A2) |
| `ingested_at` | `DateTime` | **Non** | Timestamp système au moment de la persistance Neo4j. Sert d'audit trail. Déjà partiellement présent dans le pipeline actuel (champ existant à compléter pour systématisation) |
| `invalidated_at` | `DateTime` | **Oui** | Timestamp système au moment où ce claim a été invalidé (suite à contradiction, supersession, retrait du corpus). `NULL` = claim actif dans le KG. **Jamais de suppression** : on invalide, on ne supprime pas (AX-1 préserve la preuve) |

### 2.3 Règle d'or — invariant temporel

> **Un claim n'est JAMAIS supprimé du KG**. S'il est contredit, superseded ou retiré du corpus, on positionne `invalidated_at = <date système>`. La preuve textuelle initiale (`EVIDENCED_BY`) reste intacte.

Cette règle découle directement de `AX-1` (toute affirmation doit rester ancrée à un span de texte localisable, même si l'affirmation n'est plus considérée comme valide aujourd'hui).

### 2.4 Queries types supportées

```cypher
// "Qu'est-ce qui est vrai aujourd'hui ?"
MATCH (c:Claim)
WHERE c.tenant_id = $tenant_id
  AND c.invalidated_at IS NULL
  AND (c.valid_until IS NULL OR c.valid_until > datetime())
  AND c.valid_from <= datetime()
RETURN c

// "Qu'était vrai au 15 janvier 2024 ?"
MATCH (c:Claim)
WHERE c.tenant_id = $tenant_id
  AND c.valid_from <= datetime('2024-01-15')
  AND (c.valid_until IS NULL OR c.valid_until > datetime('2024-01-15'))
  AND c.ingested_at <= datetime('2024-01-15')
  AND (c.invalidated_at IS NULL OR c.invalidated_at > datetime('2024-01-15'))
RETURN c

// "Qu'est-ce qu'on savait à T mais qu'on a invalidé depuis ?"
MATCH (c:Claim)
WHERE c.tenant_id = $tenant_id
  AND c.ingested_at <= datetime('2024-01-15')
  AND c.invalidated_at IS NOT NULL
  AND c.invalidated_at > datetime('2024-01-15')
RETURN c
```

### 2.5 Indexation Neo4j

Pour performance des queries temporelles fréquentes en runtime :

```cypher
// Index principal sur invalidated_at (NULL pour claims actifs — index sparse efficient)
CREATE INDEX claim_active IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.invalidated_at);

// Index sur valid_from + valid_until pour point-in-time queries
CREATE INDEX claim_event_time IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.valid_from, c.valid_until);

// Index sur ingested_at pour audit trail
CREATE INDEX claim_ingested IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.ingested_at);
```

Les 3 indexes sont composés sur `tenant_id` en premier (multi-tenant isolation, cf `AX-7` + CH-52.2).

---

## 3. Stratégie d'implémentation

### 3.1 Phase A1.2 — Migration du schéma existant

Le KG actuel contient ~15 861 claims SAP (cf VISION.md §6.1). La migration doit :

1. **Ajouter les 3 nouveaux champs** (`valid_from`, `valid_until`, `invalidated_at`) sur tous les Claims existants
2. **Valeurs par défaut** :
   - `valid_from = ingested_at` (faute de mieux : on suppose qu'un claim est valide depuis qu'on l'a appris)
   - `valid_until = NULL` (par défaut, encore actif)
   - `invalidated_at = NULL` (par défaut, encore actif)
3. **Idempotence** : la migration peut être rejouée sans effet (script `CREATE/SET IF NOT EXISTS` patterns)
4. **Multi-tenant safe** : migration appliquée à tous les tenants, audit log par tenant

Script de migration cible :

```cypher
// Migration A1.2 — Bitemporel sur Claim
// Idempotent : peut être rejouée sans effet

// 1. Count avant migration (audit)
MATCH (c:Claim) RETURN count(c) AS total_claims_before;

// 2. Migration des claims sans valid_from
MATCH (c:Claim)
WHERE c.valid_from IS NULL
SET c.valid_from = c.ingested_at,
    c.valid_until = NULL,
    c.invalidated_at = NULL
WITH count(c) AS migrated_count

// 3. Log de migration (audit trail persistant — node :MigrationLog)
CREATE (:MigrationLog {
  migration_id: 'v6_bitemporal_claims',
  executed_at: datetime(),
  claims_migrated: migrated_count,
  script_version: '1.0',
  applied_by: 'A1.2'
})
RETURN migrated_count;

// 4. Count après migration (vérification)
MATCH (c:Claim) RETURN count(c) AS total_claims_after;

// 5. Création indexes
CREATE INDEX claim_active IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.invalidated_at);

CREATE INDEX claim_event_time IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.valid_from, c.valid_until);

CREATE INDEX claim_ingested IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.ingested_at);
```

Localisation script migration : `migrations/v6_bitemporal_claims.cypher` (à créer en Phase A1.2).

**Audit post-migration** :
```cypher
// Vérifier traçabilité migration
MATCH (m:MigrationLog {migration_id: 'v6_bitemporal_claims'})
RETURN m.executed_at, m.claims_migrated, m.script_version;
```

Le node `:MigrationLog` est conservé en permanence pour audit historique (ne sera jamais purgé).

### 3.2 Phase A1.3 — Pipeline d'ingestion ClaimFirst

Deux étapes du pipeline 9-phases (cf VISION.md §4.3) sont impactées :

#### Étape 1 — Document Profile (extension)

Ajouter à la détection de profil documentaire l'extraction de :
- **`document_valid_from`** : date d'effet ou de publication du document, si présente
- **`document_version`** : version explicite (string libre)
- **`document_source_authority`** : hiérarchie de fiabilité (officielle, draft, archive...)

Ces 3 champs sont posés sur le nœud `:Document` créé à l'ingestion. Ils alimenteront `:Claim.valid_from` par défaut (héritage du document) lors de l'étape 9.

**Cascade extraction `document_valid_from` (en vigueur depuis 2026-05-19 soir — cf §9.2)** :

> ⚠️ **Cette cascade a été révisée le 2026-05-19 soir** suite au test live RISE Bootcamp Cloud ALM. La version originale post-spike A1.0 plaçait S1 en 3e position ; elle est superseded par la version ci-dessous qui désactive S1 par défaut. Voir §9.2 pour le raisonnement complet et §9.3 pour le principe transverse "NULL > valeur probablement fausse".

Le spike A1.0 (cf `doc/ongoing/sessions/A1.0_SPIKE_DOCUMENT_VALID_FROM.md`) avait déjà montré que sur le corpus SAP, 9/15 PDFs ont une `/CreationDate` identique au jour (signal batch re-save local par l'utilisateur lors du téléchargement, **pas** la date de publication SAP réelle). Le test live a confirmé l'incompatibilité opérationnelle de S1 même hors batch (un seul PDF téléchargé a sa CreationDate réécrite par le portail). **S1 est donc désactivé par défaut** ; il reste opt-in (`enable_s1_metadata=True`) pour corpus maîtrisé où la CreationDate est fiable.

```python
def extract_document_valid_from(pdf_path) -> tuple[date | None, marker_type]:
    """
    Cascade en vigueur depuis 2026-05-19 soir : contenu sémantique uniquement,
    S1 metadata désactivé par défaut (opt-in last resort).
    Retourne (date, marker_type) où marker_type ∈ {explicit, document_inherited, ingestion_fallback}.
    """
    # S2 — Texte page 1 proche d'un keyword sémantique (Published, Effective, etc.)
    #      Le plus fiable car contenu *officiel* du document
    if (d := extract_from_page1_keyword(pdf_path)):
        return d, "explicit"

    # S3 — Nom de fichier enrichi (year + month_year FR/EN + YYYYMMDD compact + version)
    if (d := extract_from_filename_enriched(pdf_path)):
        return d, "explicit"

    # S4 — LLM evidence-locked sur texte page 1
    #      Prompt strict : retourne None si pas de date explicite (cf §9.2)
    if (d := extract_from_llm_evidence_locked(pdf_path)):
        return d, "explicit"

    # S1 — Metadata /CreationDate (DÉSACTIVÉ par défaut, opt-in via enable_s1_metadata=True)
    #      Si opt-in et succès : ajoute warning="s1_low_reliability_metadata"
    if S1_ENABLED_FOR_THIS_CORPUS and (d := extract_from_metadata_with_batch_check(pdf_path)):
        return d, "explicit"  # warning trace la faible fiabilité

    # Fallback ultime — pas de signal fiable. **valid_from = NULL est intentionnel** (§9.3).
    # Une date fausse propage le biais ; NULL signale honnêtement "à traiter comme indéterminé".
    return None, "ingestion_fallback"
```

**Détection batch re-save** (héritée du design initial, conservée pour opt-in S1) : pre-pass d'audit du corpus avant ingestion. Si ≥3 PDFs partagent la même `/CreationDate` au jour près, S1 est disqualifié pour ce batch — mais en pratique, S1 étant off par défaut, ce mécanisme n'est utile que sur les corpus opt-in.

**Choix S4 LLM : Qwen2.5-14B AWQ sur EC2 Burst** (motifs §6.1.1) :
- Déjà utilisé par ClaimFirst Phase 2 (extraction claims) sur ce corpus → battle-tested
- AWQ quantization perte <1pp sur extraction simple (litérature publique)
- Zéro coût marginal : instance déjà allumée pour ingestion
- Fallback gracieux si EC2 indisponible : passer à S1+warning (ne pas bloquer ingestion)
- Reste evidence-locked (AX-3) : prompt extrait ce qui est écrit page 1, n'infère pas

**`marker_type` (champ Phase A2)** : déjà prévu §2.2, sert à filtrer les claims dont `valid_from` est fiable (S2/S3/S4 = "explicit") vs incertain (fallback = "ingestion_fallback") lors de la classification claim-vs-claim (`EVOLUTION_OF` / `CONTRADICTS`).

#### Étape 9 — Persistance (extension)

À la création d'un `:Claim` en Neo4j, peupler les 4 timestamps :

```python
# Pseudo-code pipeline ClaimFirst Phase 9 (persistance) — révisé 2026-05-19 soir (§9.1)

# Précondition (assouplie) : `document.valid_from` PEUT être None si aucune source fiable n'a
# été détectée par la cascade S2→S3→S4 (S1 désactivé par défaut, cf §9.2). C'est intentionnel
# et préférable à une date fausse (§9.3). L'assert strict pré-2026-05-19 a été retiré.

claim_valid_from = (
    extracted_valid_from               # Si extrait du claim lui-même (rare, ex: "applicable from 2023-01-01")
    or document.valid_from              # Héritage du document source (peut être None — c'est OK)
)
# claim_valid_from peut donc être None : c'est le signal "date inconnue, à traiter comme
# toujours valide jusqu'à preuve du contraire" (§9.1). La supersession A2 gère ce cas
# explicitement (cf §9.4 CAS 2, 3, 4).

# Règle drift soft (inchangée pour les claims AVEC date explicite) :
# - claim.valid_from > document.valid_from : autorisé (entrée en vigueur future)
# - claim.valid_from < document.valid_from : warning log (suspect mais pas bloquant)
# - claim.valid_from is None OU document.valid_from is None : aucun drift à comparer
if claim_valid_from is not None and document.valid_from is not None and claim_valid_from < document.valid_from:
    logger.warning(
        f"Drift temporel claim<document : claim_valid_from={claim_valid_from} "
        f"< document.valid_from={document.valid_from} (doc_id={doc_id}, claim_id={claim_id})"
    )

claim_data = {
    # ... champs existants ...
    "valid_from": claim_valid_from,             # Peut être None (§9.1)
    "valid_until": extracted_valid_until,       # Si explicite (ex: "expires 2025-12-31"), sinon NULL
    "ingested_at": datetime.utcnow(),           # Toujours obligatoire — borne inférieure connue
    "invalidated_at": None,                     # NULL à la création (rempli par Phase A2)
    # ... autres champs (subject_canonical, predicate, value, evidence_id, etc.) ...
}
```

**Règle drift (décidée 2026-05-19)** :
- `claim.valid_from >= document.valid_from` : nominal (cas attendu)
- `claim.valid_from > document.valid_from` : **autorisé** (entrée en vigueur future décrite dans le doc)
- `claim.valid_from < document.valid_from` : **warning log** (suspect mais pas bloquant — Phase A2 statuera sur durcissement)

### 3.3 Phase A1.4 — Validation Gate-B

Tests d'intégration **obligatoires** avant de marquer Phase A1 comme complétée :

1. **Test post-migration** : audit Cypher sur le KG SAP existant — **révisé §9.8**, seul `ingested_at` est obligatoire (`valid_from = NULL` est légitime depuis §9.1).
   ```cypher
   MATCH (c:Claim)
   WHERE c.tenant_id = 'default'
     AND c.ingested_at IS NULL
   RETURN count(c) AS missing_ingested_at;
   // Attendu : 0
   ```

2. **Test post-ré-ingestion d'un doc de référence** : ingestion d'un PDF SAP (ex: Operations Guide), vérifier que tous les claims nouveaux ont au moins `ingested_at` (révisé §9.8 — `valid_from` peut être NULL légitimement quand S2/S3/S4 retournent NULL) :
   ```cypher
   MATCH (c:Claim {doc_id: <new_doc_id>})
   WHERE c.ingested_at IS NULL
   RETURN count(c) AS bad_claims;
   // Attendu : 0 (ingested_at est le seul timestamp obligatoire au peuplement)
   ```

3. **Test queries point-in-time** : sur un **échantillon stratifié de 10 claims du corpus SAP** (2 par doc_type : Operations Guide / Security Guide / Admin Guide / Release Notes / Integration Guide), vérifier que les 3 queries types (cf §2.4) retournent des résultats cohérents. La stratification garantit qu'on ne benchmarke pas sur un seul type de doc.

4. **Test cross-tenant** : vérifier que les index `claim_active`, `claim_event_time`, `claim_ingested` sont utilisés (via `EXPLAIN`) et que les queries restent isolées par tenant.

5. **Test performance query point-in-time** (nouveau, ajout post-review Claude Web) : sur le corpus SAP complet (~15 861 claims), mesurer la latence des 3 queries §2.4. **Seuils** :
   - p50 < 100 ms
   - **p95 < 500 ms** (critère bloquant)
   - p99 < 1 s
   - Si dépassement → analyse `EXPLAIN` + revue indexes avant Phase A2

**Critère de succès Gate-B** : 100% des claims persistés portent les 4 timestamps **ET** queries p95 < 500ms. Si <100% sur timestamps OU p95 ≥ 500ms, **Phase A1 échouée**, investiguer avant Phase A2.

---

## 4. Conséquences

### 4.1 Conséquences positives

- **Base solide pour Phase A2** : les relations `EVOLUTION_OF` / `CONTRADICTS` / `SAME_AS` (claim-vs-claim) deviennent triviales à classifier dès que les claims portent leur propre date de validité
- **Capacité C3 (raisonnement différentiel) débloquée** : queries point-in-time deviennent natives en Cypher (déterministes, pas de LLM, conforme Probability Isolation §3.5)
- **Conformité état de l'art** : aligné Zep/Graphiti + VersionRAG (référencé VISION.md §10.4)
- **Auditabilité totale** : on peut toujours expliquer "pourquoi ce claim n'est plus retourné" via `invalidated_at + sa raison` (à venir en Phase A2)
- **Pas de perte de mémoire** : un claim invalidé reste consultable par requête historique (`AX-1` respecté)

### 4.2 Conséquences négatives (assumées)

- **Coût stockage Neo4j** : +3 champs DateTime par Claim × ~15 861 claims SAP = ~200 KB extra (négligeable)
- **Complexité query runtime** : tous les Cypher du runtime devront inclure le filtre `WHERE c.invalidated_at IS NULL` par défaut, sauf modes "audit historique" — **pattern obligatoire** documenté en §4.4 ci-dessous
- **Migration Neo4j non-trivial** : impossible à rollback en cas de bug — la migration A1.2 doit être validée sur un dump avant d'être appliquée à la prod
- **Pipeline ingestion légèrement plus complexe** : extraction de `document_valid_from` ajoute du LLM/regex à l'étape 1 (impact latence minimal, ~0.5s/doc)

### 4.3 Risques mitigés

| Risque | Mitigation |
|---|---|
| `valid_from` mal extrait par LLM | **Révisé §9.8** : fallback est `NULL` (pas `ingested_at`), marker_type = `ingestion_fallback` trace l'origine. Une valeur fausse est strictement pire que NULL (cf §9.3). Le marker_type sera dénormalisé sur Claim avant impl A2 (cf §9.6). |
| Queries point-in-time lentes sur gros corpus | Indexes composites sur `tenant_id` (cf §2.5) ; bench performance Gate-B test 5 avec seuil p95 < 500ms |
| Migration bug perdant des claims existants | Migration idempotente + dump Neo4j avant migration + node `:MigrationLog` audit + plan rollback §6.4 |
| Confusion sémantique `valid_from` vs `ingested_at` | ADR explicite (ce doc) + commentaires Cypher + tests qui exercent les 3 queries types §2.4 |
| **Drift `claim.valid_from` vs `document.valid_from`** (ajout post-review Claude Web) | Règle soft : `>` autorisé (entrée vigueur future), `<` warning log (cf §3.2). Durcissement éventuel en assert tranché Phase A2 selon volume warnings observés |
| **Taux extraction `document_valid_from` faible** sur PDFs SAP hétérogènes | **Spike A1.0** (0.5j) avant A1.3 : tester extraction sur 20 PDFs SAP représentatifs, mesurer taux succès, ajuster stratégie si <80% |

### 4.4 Pattern runtime obligatoire — filtre `invalidated_at IS NULL`

Toute query Cypher du runtime qui interroge les `:Claim` **doit** inclure le filtre `WHERE c.invalidated_at IS NULL`, sauf modes "audit historique" explicitement opt-in. Sinon les claims invalidés sont retournés et polluent les réponses.

**Pattern à appliquer** :

```cypher
// ✅ CORRECT — claims actifs uniquement (cas nominal, révisé §9.8 pour NULL valid_from)
MATCH (c:Claim)
WHERE c.tenant_id = $tenant
  AND c.invalidated_at IS NULL                                         // OBLIGATOIRE filtre actif
  AND (c.valid_from IS NULL OR c.valid_from <= datetime())              // NULL accepté = "valide jusqu'à preuve du contraire" (§9.1)
  AND (c.valid_until IS NULL OR c.valid_until > datetime())
RETURN c

// ❌ INCORRECT — oubli filtre invalidated_at, retourne claims obsolètes
MATCH (c:Claim)
WHERE c.tenant_id = $tenant
RETURN c

// ❌ INCORRECT (post-§9.8) — exclut les claims avec valid_from=NULL alors qu'ils sont légitimes
MATCH (c:Claim)
WHERE c.tenant_id = $tenant
  AND c.valid_from <= datetime()  // ⚠️ NULL ne match jamais → claims légitimes perdus
RETURN c

// ✅ AUDIT HISTORIQUE — opt-in explicite, claims invalidés inclus
MATCH (c:Claim)
WHERE c.tenant_id = $tenant
  AND c.ingested_at <= datetime($point_in_time)
// PAS de filtre invalidated_at : on veut voir l'historique complet
RETURN c
```

Ce pattern sera codifié dans le DEV_GUIDE (à créer en Phase A1.3) et **enforced** par revue de code sur toute PR touchant un module Cypher.

---

## 5. Alternatives écartées

### 5.1 Modèle mono-temporel (transaction time seulement)

**Idée** : ne stocker que `ingested_at` et `invalidated_at`, considérer que `valid_from = ingested_at`, ignorer `valid_until`.

**Pourquoi écarté** : ne permet pas de répondre à la question critique *"Qu'était vrai à T dans le monde, indépendamment de quand on l'a appris ?"*. Or c'est précisément la valeur produit C3 (capacité différentielle / lifecycle). Économise ~50 KB de stockage pour un gain produit nul.

### 5.2 Modèle versioned tuples (immutable claims, nouveau Claim à chaque modif)

**Idée** : ne jamais modifier un Claim. Si invalidé, créer un nouveau Claim qui pointe vers l'ancien via `INVALIDATES`.

**Pourquoi écarté** : explose le nombre de nœuds (×N versions), complique les queries, alourdit Qdrant projection. Le modèle bitemporel sur le nœud lui-même est plus compact et plus simple à requêter.

### 5.3 Modèle externe (table relationnelle temporelle PostgreSQL)

**Idée** : stocker les timestamps dans PostgreSQL, garder Neo4j pour la structure relationnelle.

**Pourquoi écarté** : viole `AX-7` (Neo4j = vérité, pas projection partielle). Ajoute une dépendance cross-database à chaque query temporelle. La complexité opérationnelle dépasse le gain perf marginal.

### 5.4 Pas de modèle temporel structuré, déduction LLM au runtime

**Idée** : continuer comme V5.1, laisser le LLM Reading Agent inférer le temporel depuis le texte à chaque question.

**Pourquoi écarté** : c'est précisément l'approche V5.1 qui plafonne à C3=0.25 (anti-pattern §8.4). Viole Probability Isolation §3.5 (incertitude LLM dans le chemin déterministe). Insuffisant pour atteindre la cible ≥80%.

---

## 6. Plan de mise en œuvre

### 6.1 Découpage en tâches (cf tracker)

| # | Tâche | Estimation | Statut |
|---|---|---|---|
| #319 | PHASE A1.1 — Rédiger cet ADR | 0.5j | ✅ completed |
| #320 | PHASE A1.2 — Migration schéma Neo4j (`migrations/v6_bitemporal_claims.cypher`) + tests idempotence | 1j | pending (blocked by #319) |
| **#A1.0** | **PHASE A1.0 spike (post-review Claude Web)** — tester extraction `document_valid_from` sur 20 PDFs SAP représentatifs, mesurer taux succès, valider stratégie regex+LLM. **Bloquant A1.3 si taux <80%**, déclenche revue stratégie | **0.5j** | **pending (blocked by #320)** |
| #321 | PHASE A1.3 — Pipeline ingestion : extraction `document_valid_from` (cascade S2>S3>S1>S4 LLM Qwen2.5-14B AWQ) + peuplement claim timestamps + détection batch re-save | **2.5-3j** (révisé post-spike A1.0 : +1j pour cascade enrichie + S4 LLM + batch detection) | pending |
| #322 | PHASE A1.4 — Tests Gate-B (5 tests dont perf p95) — validation 100% claims OK + p95 < 500ms | 0.5j | pending (blocked by #321) |
| **Total Phase A1** | | **~5-6j** (révisé post-spike A1.0) | |

Légèrement au-dessus de l'estimation initiale EXECUTION_ROADMAP §2 Phase A1 (1 semaine). À noter : le surcoût A1.3 (+1j) est compensé par la valeur du spike A1.0 (a évité un rework potentiel de plusieurs jours en Phase A2).

### 6.1.1 Choix S4 LLM — Qwen2.5-14B AWQ sur EC2 Burst (validé 2026-05-19)

Le S4 du cascade A1.3 nécessite un LLM pour extraire la date depuis page 1 quand S2/S3/S1 ont échoué. Bake-off implicite documenté ci-dessous :

| Modèle | Aptitude S4 | Coût marginal ingestion | Motif rejet/sélection |
|---|---|---|---|
| **Qwen2.5-14B AWQ EC2 Burst** | ✅ Battle-tested ClaimFirst Phase 2 sur ce corpus | **$0** (instance déjà allumée) | **Sélectionné** — cohérence opérationnelle |
| Qwen2.5-14B Together AI serverless | ✅ | $0.20/M tokens | Rejeté : duplique le modèle, ajoute provider |
| Mistral-Small-3.2-24B DeepInfra | ✅ Bon ratio | $0.10/$0.30 | Alternative valable, mais ajoute un LLM externe |
| DeepSeek-V3.1 (runtime V5.1) | ⚠️ Surdimensionné | $0.40/$0.40 | Rejeté : overkill pour extraction simple |
| Llama-3.3-70B-Turbo | ❌ Levier 4 piège (129/132 abstentions sur structuré) | $0.88/$0.88 | Rejeté formellement |

**Précaution opérationnelle** : si EC2 Burst indisponible au moment de l'ingestion (vLLM down), S4 est **skip** gracieusement et la cascade retombe sur S1+warning. Pas de fallback sur LLM externe pour garder le principe "1 LLM = 1 lifecycle = 1 monitoring".

### 6.2 Critères de réussite Phase A1 (Gate-B)

- ✅ Migration `v6_bitemporal_claims.cypher` exécutée avec succès
- ✅ Tests d'audit : 0 claim sans `valid_from` OU `ingested_at` (champs obligatoires)
- ✅ Tests cross-tenant : indexes utilisés, isolation préservée
- ✅ Tests queries point-in-time : 3 patterns §2.4 fonctionnent sur échantillon
- ✅ Pipeline ré-ingestion : sample doc créé avec 100% de claims aux 4 timestamps

Si tous OK → Phase A1 fermée, démarrage Phase A2 (relations claim-vs-claim).

### 6.3 Dépendances et ordre

```
A1.1 ADR (#319) ✅ →  A1.2 Migration (#320) →  A1.0 Spike (#A1.0) →  A1.3 Pipeline (#321) →  A1.4 Tests Gate-B (#322) →  Phase A2
```

Strict séquentiel (chaque tâche débloque la suivante). Le spike A1.0 (0.5j) est inséré entre A1.2 et A1.3 pour dérisquer l'extraction `document_valid_from` qui est le point de fragilité identifié par Claude Web.

### 6.4 Plan de rollback (en cas d'échec migration A1.2)

Avant exécution de la migration A1.2, **dump complet Neo4j** est obligatoire :

```bash
# 1. Backup pré-migration
docker exec knowbase-neo4j neo4j-admin database dump neo4j \
  --to-path=/data/backups/pre_v6_bitemporal_$(date +%Y%m%d_%H%M%S).dump
```

En cas d'échec de la migration ou de découverte d'un bug bloquant :

```
1. STOP immédiat du pipeline d'ingestion (kw.ps1 stop app — pas infra pour préserver le state du dump)
2. Validation diagnostic : MATCH (m:MigrationLog {migration_id: 'v6_bitemporal_claims'}) RETURN m
   → si présent : migration a tourné partiellement, rollback nécessaire
   → si absent : migration n'a pas démarré, fix script et re-run
3. Restore dump pré-migration :
   docker exec knowbase-neo4j neo4j-admin database load neo4j \
     --from-path=/data/backups/pre_v6_bitemporal_<timestamp>.dump --overwrite-destination=true
4. Investigation cause racine (script Cypher → erreur sémantique ? volume ? lock ?)
5. Fix script `migrations/v6_bitemporal_claims.cypher`
6. Re-run migration sur dump test isolé avant prod
7. Documenter post-mortem dans `doc/ongoing/sessions/POST_MORTEM_A1.2_<date>.md`
```

Le dump pré-migration est conservé **minimum 30 jours** après validation Gate-B (parachute en cas de découverte tardive de bug).

---

## 7. Liens

- VISION.md §3.2 — Bitemporel sur les claims (4 timestamps)
- VISION.md §3.3 — Supersession à 2 niveaux (utilise `invalidated_at`)
- EXECUTION_ROADMAP.md §2 Phase A1 — Plan
- EXECUTION_ROADMAP.md §3.1 Kill switch K-2 — si Phase A1 OK mais A2 (relations) ne détecte pas les contradictions, problème probable à A1 (schéma)
- État de l'art externe :
  - Zep/Graphiti — [arxiv 2501.13956](https://arxiv.org/html/2501.13956v1)
  - VersionRAG — [arxiv 2510.08109](https://arxiv.org/abs/2510.08109)
- ADR connexes (à créer en Phase A2) : `ADR_RELATIONS_CLAIM_CLAIM.md` (SAME_AS / EVOLUTION_OF / CONTRADICTS / REFINES / QUALIFIES)

---

## 8. Validation

| Acteur | Date | Statut |
|---|---|---|
| Fred (utilisateur produit) | 2026-05-19 | ✅ Accepted |
| Claude Web (review externe) | 2026-05-19 | ✅ "Production-ready" — 5 améliorations mineures + 1 spike de mitigation, tous intégrés |
| Vision-guardian | _audit auto à la prochaine invocation_ | _pending_ |

**Amendements appliqués post-review Claude Web (2026-05-19)** :
1. §2.2 — Clarification ambiguïté `valid_from = ingested_at` + référence `marker_type` Phase A2
2. §3.1 — Log de migration (node `:MigrationLog` avec audit count avant/après)
3. §3.2 — Règle drift soft `claim.valid_from` vs `document.valid_from` (warning, pas assert)
4. §3.3 — Échantillon Gate-B #4 stratifié par doc_type + test #5 perf p95 < 500ms
5. §4.4 — Pattern runtime obligatoire `WHERE invalidated_at IS NULL` documenté
6. §6.1 — Tâche **A1.0 spike** (0.5j) ajoutée avant A1.3 (extraction `document_valid_from` sur 20 PDFs)
7. §6.4 — Plan de rollback explicite (procédure 7 étapes)

*ADR rédigé le 2026-05-19 dans le cadre de la Phase A1 (refondation runtime KG-first). Amendé et validé le même jour post-review.*

---

## 9. Addendum (2026-05-20) — Supersession sous incertitude + S1 metadata désactivé

> **Status** : ✅ Accepted (Fred 2026-05-19 soir — décisions tranchées post-validation A1.3)
> **Scope** : amende §2.2, §3.2, §3.3, §4.4. Préfigure le squelette de la règle de supersession pour Phase A2.
> **Déclencheur** : test live RISE Bootcamp Cloud ALM (2026-05-19 23:23 UTC) — DocumentValidFromExtractor a tranché S1 sur une `/CreationDate` = `2026-05-19` (= jour du download), produisant une fausse date de publication. Deux corrections en ont découlé : (1) S1 désactivé par défaut, (2) formalisation explicite du traitement de `valid_from = NULL` dans la chaîne d'invalidation A2.

### 9.1 Sémantique de `valid_from = NULL` (clarification §2.2)

`valid_from = NULL` n'est PAS une valeur sentinelle "ancien", "inexistant" ni "à filtrer". C'est un signal honnête :

> **`valid_from = NULL` signifie : « date d'effet inconnue, à traiter comme toujours valide jusqu'à preuve du contraire »**

Trois conséquences runtime :

1. **Sur les queries point-in-time**, un claim `valid_from = NULL` non-invalidé doit remonter. Le filtre §2.4 devient :
   ```cypher
   AND (c.valid_from IS NULL OR c.valid_from <= datetime())
   ```
   (au lieu de `AND c.valid_from <= datetime()` qui exclurait les NULLs)

2. **À l'ingestion**, NULL est **préférable** à une date inférée avec faible confiance. Une valeur fausse propage le biais dans toutes les opérations downstream (supersession, classification, filtres de fraîcheur). NULL ne propage rien.

3. **À la supersession A2** (cf §9.4), l'algorithme distingue les 4 combinaisons NULL/non-NULL explicitement.

### 9.2 S1 metadata désactivé par défaut (amende §3.2)

La cascade par défaut devient **S2 → S3 → S4 → fallback NULL**. S1 reste dans le code mais **opt-in uniquement** via `enable_s1_metadata=True`.

| Source | Fiabilité | Décision |
|---|---|---|
| **S2** — Page 1 keyword sémantique | ✅ Fiable (contenu officiel du document) | Conservée — priorité 1 |
| **S3** — Filename enrichi | ✅ Fiable si présent | Conservée — priorité 2 |
| **S4** — LLM evidence-locked page 1 | ✅ Fiable si signal explicite, retourne NULL sinon | Conservée — priorité 3 |
| **S1** — Metadata `/CreationDate` PDF | ❌ **Volatile** (copie, re-save batch, re-pack portail) | **Désactivée par défaut** (opt-in last-resort si activée) |

**Justification S1 désactivée** : un PDF téléchargé d'un portail (SAP, ECHA, Eur-Lex, etc.) voit sa `/CreationDate` réécrite au moment du téléchargement. Spike A1.0 : 9/15 PDFs SAP avec `/CreationDate` identique au jour (batch local). Mettre `valid_from = today` sur un doc publié en 2019 :
- Fausse le filtre temporel (runtime exclut le doc pour les queries "avant aujourd'hui")
- Fausse la supersession A2 (doc traité comme "tout récent" → invalide à tort les vrais récents)
- Fausse la fraîcheur perçue (doc apparaît neuf à l'utilisateur)

**Prompt S4 LLM renforcé** (cf code `document_valid_from_extractor.py:_S4_PROMPT_SYSTEM`) :
- Distinction explicite "date du document" vs "dates mentionnées DANS le document" (EOL/EOM produits, échéances contractuelles, validity windows d'items décrits, événements narratifs, etc.)
- Confirmation explicite : "Returning null is correct and expected — a false document date is far worse than no date at all."
- Domain-agnostic (médical/légal/technique/SAP — même règle).

**Opt-in S1** : pour un corpus maîtrisé où la `/CreationDate` est fiable (génération interne de PDFs sans portail intermédiaire), activer via `DocumentValidFromExtractor(enable_s1_metadata=True)`. Dans ce cas, S1 ne tranche qu'**après échec de S2/S3/S4**, et toujours avec un `warning = "s1_low_reliability_metadata"`.

### 9.3 Principe transverse : NULL > valeur probablement fausse

**Règle d'or pour tout extracteur cascade** : sur un champ qui influencera des décisions runtime (date, identifiant, statut, classification), préférer **systématiquement** `NULL` à une valeur extraite via un signal volatile ou avec confiance basse.

Justification : une valeur fausse propage le biais (filtres, classification, supersession, fraîcheur). Un NULL signale honnêtement "à traiter comme indéterminé" et permet aux mécanismes downstream (supersession A2, abstention runtime) de gérer l'incertitude proprement.

**Test mental** : *"si le pipeline downstream supposait que cette valeur est sûre, est-ce que ça ferait du dégât quand elle est fausse ?"* — si oui, NULL est plus sûr.

Ce principe s'applique aussi aux futurs extracteurs (identifiants produits, statuts lifecycle, classifications domain).

### 9.4 Règle de supersession Phase A2 sous incertitude

Phase A2 implémentera la chaîne d'invalidation `Doc_B supersede Doc_A` quand une contradiction sémantique est mesurée entre des claims des deux docs. La règle bitemporelle qui décide quel claim remplace l'autre est :

```
Précondition : contradiction sémantique mesurée entre claim_A et claim_B
             (NLI ou structured eval, méthode à définir dans ADR_RELATIONS_CLAIM_CLAIM)

Décision basée sur les 4 timestamps :

  CAS 1 — Les deux dates explicites
    A.valid_from IS NOT NULL ET B.valid_from IS NOT NULL

    → SI B.valid_from > A.valid_from  : B supersede A
    → SI A.valid_from > B.valid_from  : A supersede B
    → SI égales                       : pas de supersession (claims concurrents, marquer
                                        `conflict_concurrent`)

  CAS 2 — A inconnue, B explicite (cas test RISE Bootcamp, cf §9.7)
    A.valid_from IS NULL ET B.valid_from IS NOT NULL

    → SI B.valid_from > A.ingested_at : B supersede A
       Justification : B affirme une date d'effet POSTÉRIEURE au dernier instant où on
       a vu A dans le KG. Donc B est forcément postérieur à A dans le temps réel, même
       si on ne connait pas la date réelle de A.
    → SI B.valid_from ≤ A.ingested_at : ambigu, NE PAS superseder, marquer
                                         `conflict_pending` (B pourrait dater d'avant
                                         la connaissance de A — sans plus d'info,
                                         on garde A)

  CAS 3 — A explicite, B inconnue
    A.valid_from IS NOT NULL ET B.valid_from IS NULL

    → Ambigu : B peut être antérieur ou postérieur à A. NE PAS superseder.
       Marquer `conflict_pending`. Un futur doc avec date explicite tranchera.

  CAS 4 — Les deux inconnues
    A.valid_from IS NULL ET B.valid_from IS NULL

    → Ambigu : aucune date pour décider. NE PAS superseder. Marquer `conflict_pending`.
       Tie-breaker `ingested_at` possible (B.ingested_at > A.ingested_at → B vu plus
       récemment) mais NE PAS l'utiliser comme arbitrage par défaut : `ingested_at`
       reflète l'ordre d'ingestion opérateur, pas l'ordre intellectuel.
```

### 9.5 Écriture de l'invalidation (CAS 1 ou 2)

Quand A est superseded par B :

```cypher
MATCH (a:Claim {claim_id: $a_id}), (b:Claim {claim_id: $b_id})
SET a.valid_until    = b.valid_from,       // borne de validité de A = date d'effet de B
    a.invalidated_at = datetime()           // timestamp pipeline A2 qui détecte
CREATE (b)-[:SUPERSEDES {detected_at: datetime(), reason: $contradiction_metric}]->(a)
RETURN a, b
```

B reste actif (`valid_until = NULL`, `invalidated_at = NULL`).

Pour CAS 3, CAS 4 et CAS 1 égalité : créer un node `:ConflictPending` reliant les deux claims, à formaliser dans `ADR_RELATIONS_CLAIM_CLAIM.md` :

```cypher
CREATE (cp:ConflictPending {
   created_at: datetime(),
   resolution_status: 'unresolved',
   contradiction_metric: $score
})
CREATE (cp)-[:INVOLVES]->(a)
CREATE (cp)-[:INVOLVES]->(b)
```

### 9.6 Impact schéma : propager `valid_from_marker` aux Claims

Le DocumentContext porte actuellement `valid_from_marker` (`explicit | document_inherited | ingestion_fallback`) après PR `5c83879`. Les claims héritent du `valid_from` du DocumentContext mais **pas** du marker. Pour la classification A2 :

| Option | Coût stockage | Coût query | Décision |
|---|---|---|---|
| **A** — Jointure runtime (`MATCH (c:Claim)-[:HAS_CONTEXT]->(dc:DocumentContext) RETURN dc.valid_from_marker`) | 0 | +1 traversée par comparaison claim-vs-claim | À écarter |
| **B** — Dénormalisation sur Claim (`c.valid_from_marker`) | ~5 bytes × 15 861 = 80 KB | 0 (lecture directe) | **Sélectionné** |

**Décision** : Option B (dénormalisation). Justification : la query A2 est très fréquente (chaque comparaison claim-vs-claim potentielle), la jointure ralentirait inutilement. Le coût stockage est négligeable.

**Modification nécessaire** (à appliquer avant impl A2) :
- `claim_persister._persist_document_context` : étendre le cache `_doc_valid_from_by_id` de `dict[doc_id, Optional[str]]` à `dict[doc_id, tuple[Optional[str], str]]` (valid_from + marker).
- `claim_persister._persist_claims_batch` : ajouter `props["valid_from_marker"] = marker` à partir du cache.
- Migration backfill : pour les claims existants déjà persistés, peupler `valid_from_marker` par jointure puis dénormalisation (script idempotent type §3.1).

### 9.7 Cas pratique de référence (test live 2026-05-19)

**Doc A — "RISE Bootcamp Cloud ALM"** (test du 2026-05-19, voie ClaimFirst) :
- `valid_from = NULL`, `valid_from_marker = ingestion_fallback`, `ingested_at = 2026-05-19T21:23:27Z`
- 11 claims hérités : tous `valid_from = NULL`, tous `ingested_at = 2026-05-19T21:23:27Z`
- Claim hypothétique : "Module XYZ utilise architecture monolithique"

**Doc B — "SAP S/4HANA Architecture Update"** (futur, ingéré en octobre 2026) :
- Page 1 contient "Published: 12 October 2026"
- `valid_from = 2026-10-12`, `valid_from_marker = explicit`, `ingested_at = 2026-10-15T...`
- Claim : "Module XYZ utilise architecture microservices depuis octobre 2026"

**Pipeline A2** détecte contradiction entre claim_A et claim_B → applique règle §9.4 :
- A.valid_from = NULL, B.valid_from = 2026-10-12 → **CAS 2**
- B.valid_from (2026-10-12) > A.ingested_at (2026-05-19) → CAS 2 satisfait
- **B supersede A**
- `A.valid_until = 2026-10-12`, `A.invalidated_at = 2026-10-15T...`
- Création `(B)-[:SUPERSEDES]->(A)`

**Au runtime** :
- Query "Architecture du module XYZ le 2026-08-01" → A retourne (`valid_from IS NULL OR valid_from ≤ 2026-08-01` ✓, `valid_until = 2026-10-12 > 2026-08-01` ✓, `invalidated_at` ignoré en mode point-in-time as-of)
- Query "Architecture du module XYZ aujourd'hui (2026-11-01)" → B retourne (filtre `invalidated_at IS NULL` exclut A)
- Query as-of 2026-08-01 rétroactive après ingestion B → A retourne quand même (point-in-time historique fonctionne, cf §2.4)

C'est exactement la bitemporalité utile en presales : *"qu'est-ce que je savais à telle date ?"* ≠ *"qu'est-ce qui est vrai aujourd'hui ?"*

### 9.8 Impacts sur les sections existantes — ✅ TOUS APPLIQUÉS (commit suivant ad8ce3a)

| Section | Impact | Statut |
|---|---|---|
| §2.2 | Tableau `valid_from` : marquer Nullable=Oui + référencer §9.1 | ✅ Appliqué |
| §3.2 cascade | (S2→S3→S1→S4) obsolète sur S1, S1 désactivé par défaut | ✅ Appliqué — cascade documentée en vigueur : **S2→S3→S4→fallback NULL** (voir §9.2) |
| §3.3 Gate-B test 1 | "0 claim sans `valid_from`" invalide | ✅ Appliqué — révisé en "0 claim sans `ingested_at`" |
| §3.3 Gate-B test 2 | Cohérent avec NULL légitime | ✅ Appliqué — n'audite plus que `ingested_at` |
| §4.4 pattern runtime | Doit accepter NULL `valid_from` | ✅ Appliqué — `AND (c.valid_from IS NULL OR c.valid_from <= datetime())` + contre-exemple ajouté |
| Code `document_valid_from_extractor.py` | Docstring `class DocumentValidFromExtractor` obsolète | ✅ Appliqué — cascade par défaut documentée correctement |
| §3.2 pseudo-code Phase 9 | `assert document.valid_from is not None` à assouplir | ✅ Appliqué — assert retiré, le pseudo-code accepte NULL et gère drift comparison NULL-safe |
| §4.3 mitigation "valid_from mal extrait" | "fallback à ingested_at" est faux | ✅ Appliqué — fallback est NULL, marker_type=ingestion_fallback trace l'origine |

**§9 est le référentiel canonique** depuis 2026-05-20. Les sections §1-§8 ont été mises à jour ponctuellement pour ne plus contredire §9, avec pointeurs explicites (`révisé §9.x`) en attendant un éventuel re-numérotage si l'ADR devient v2.

### 9.9 Validation

| Acteur | Date | Décisions |
|---|---|---|
| Fred (utilisateur produit) | 2026-05-19 soir | (1) S1 désactivé par défaut, (2) NULL > valeur probablement fausse, (3) règle supersession sous incertitude (CAS 1-4) |
| Fred (utilisateur produit) | 2026-05-20 | ✅ Validation finale formalisation §9 |
| Claude (assistant) | 2026-05-20 | Rédaction §9 sur la base des décisions tranchées |

**Commits associés** :
- `5c83879` — fix(phase-a1.3): désactiver S1 metadata par défaut + renforcer S4 prompt
- `1c97041` — feat(phase-a1.3): brancher DocumentValidFromExtractor sur la voie ClaimFirst (test live qui a révélé le besoin du §9)

*Addendum §9 rédigé le 2026-05-20 par Claude sur la base des décisions Fred du 2026-05-19 soir, validées en session après test live RISE Bootcamp Cloud ALM. Statut produit-ready, à exécuter en Phase A2 selon §9.4 (algorithme supersession) et §9.6 (modif schéma `valid_from_marker` sur Claim).*
