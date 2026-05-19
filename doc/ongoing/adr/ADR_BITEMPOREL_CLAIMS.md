# ADR — Modèle bitemporel sur Claims (Phase A1)

> **Status** : 📝 Proposed (rédigé 2026-05-19, à valider par utilisateur produit)
> **Phase** : A1 (Refondation runtime KG-first — Modèle bitemporel)
> **Rattaché à** : `doc/VISION.md` §3.2 (Bitemporel sur les claims) + `doc/EXECUTION_ROADMAP.md` §2 Phase A1
> **Kill switch** : Gate-B (cf §7.2 ROADMAP) — 100% des claims persistés doivent porter les 4 timestamps après cette phase
> **Auteur** : Fred (utilisateur produit)
> **Référence externe** : Zep/Graphiti (paper arxiv 2501.13956) — modèle bitemporal industriel ; VersionRAG (arxiv 2510.08109)

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
| `valid_from` | `DateTime` | **Non** (default = `ingested_at` si non détectable du doc) | Date à partir de laquelle le claim est vrai dans le monde réel. Si non explicite dans le doc, vaut par défaut la date d'ingestion (le claim est vrai depuis qu'on l'a appris) |
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
MATCH (c:Claim)
WHERE c.valid_from IS NULL
SET c.valid_from = c.ingested_at,
    c.valid_until = NULL,
    c.invalidated_at = NULL
RETURN count(c) AS migrated;

// Création indexes
CREATE INDEX claim_active IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.invalidated_at);

CREATE INDEX claim_event_time IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.valid_from, c.valid_until);

CREATE INDEX claim_ingested IF NOT EXISTS
FOR (c:Claim) ON (c.tenant_id, c.ingested_at);
```

Localisation script migration : `migrations/v6_bitemporal_claims.cypher` (à créer en Phase A1.2).

### 3.2 Phase A1.3 — Pipeline d'ingestion ClaimFirst

Deux étapes du pipeline 9-phases (cf VISION.md §4.3) sont impactées :

#### Étape 1 — Document Profile (extension)

Ajouter à la détection de profil documentaire l'extraction de :
- **`document_valid_from`** : date d'effet ou de publication du document, si présente
  - Sources prioritaires : metadata PDF (`/CreationDate`, `/ModDate`), première page (date publication), nom de fichier (`*_2023*`, `*_v2.1*`)
  - Si introuvable : `valid_from` du document = `ingested_at`
- **`document_version`** : version explicite (string libre)
- **`document_source_authority`** : hiérarchie de fiabilité (officielle, draft, archive...)

Ces 3 champs sont posés sur le nœud `:Document` créé à l'ingestion. Ils alimenteront `:Claim.valid_from` par défaut (héritage du document) lors de l'étape 9.

#### Étape 9 — Persistance (extension)

À la création d'un `:Claim` en Neo4j, peupler les 4 timestamps :

```python
# Pseudo-code pipeline ClaimFirst Phase 9 (persistance)
claim_data = {
    # ... champs existants ...
    "valid_from": (
        extracted_valid_from               # Si extrait du claim lui-même (rare, ex: "applicable from 2023-01-01")
        or document.valid_from              # Héritage du document source (cf étape 1)
        or datetime.utcnow()                # Fallback (jamais utilisé en pratique car étape 1 garantit valid_from)
    ),
    "valid_until": extracted_valid_until,  # Si explicite (ex: "expires 2025-12-31"), sinon NULL
    "ingested_at": datetime.utcnow(),
    "invalidated_at": None,                # Toujours NULL à la création (sera mis en Phase A2 lors de classification claim-vs-claim)
    # ... autres champs (subject_canonical, predicate, value, evidence_id, etc.) ...
}
```

### 3.3 Phase A1.4 — Validation Gate-B

Tests d'intégration **obligatoires** avant de marquer Phase A1 comme complétée :

1. **Test post-migration** : audit Cypher sur le KG SAP existant
   ```cypher
   MATCH (c:Claim)
   WHERE c.tenant_id = 'default'
     AND (c.valid_from IS NULL OR c.ingested_at IS NULL)
   RETURN count(c) AS missing_timestamps;
   // Attendu : 0
   ```

2. **Test post-ré-ingestion d'un doc de référence** : ingestion d'un PDF SAP (ex: Operations Guide), vérifier que tous les claims nouveaux ont les 4 timestamps :
   ```cypher
   MATCH (c:Claim {doc_id: <new_doc_id>})
   WITH c, [c.valid_from, c.ingested_at] AS required, [c.valid_until, c.invalidated_at] AS optional
   WHERE any(t IN required WHERE t IS NULL)
   RETURN count(c) AS bad_claims;
   // Attendu : 0
   ```

3. **Test queries point-in-time** : sur un échantillon de 10 claims du corpus SAP, vérifier que les 3 queries types (cf §2.4) retournent des résultats cohérents.

4. **Test cross-tenant** : vérifier que les index `claim_active`, `claim_event_time`, `claim_ingested` sont utilisés (via `EXPLAIN`) et que les queries restent isolées par tenant.

**Critère de succès Gate-B** : 100% des claims persistés portent les 4 timestamps. Si <100%, **Phase A1 échouée**, investiguer avant Phase A2.

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
- **Complexité query runtime** : tous les Cypher du runtime devront inclure le filtre `WHERE c.invalidated_at IS NULL` par défaut, sauf modes "audit historique"
- **Migration Neo4j non-trivial** : impossible à rollback en cas de bug — la migration A1.2 doit être validée sur un dump avant d'être appliquée à la prod
- **Pipeline ingestion légèrement plus complexe** : extraction de `document_valid_from` ajoute du LLM/regex à l'étape 1 (impact latence minimal, ~0.5s/doc)

### 4.3 Risques mitigés

| Risque | Mitigation |
|---|---|
| `valid_from` mal extrait par LLM | Fallback à `ingested_at` ; `marker_type` à venir en Phase A2 trace si extraction explicite ou inférée |
| Queries point-in-time lentes sur gros corpus | Indexes composites sur `tenant_id` (cf §2.5) ; bench performance dans Gate-B test 4 |
| Migration bug perdant des claims existants | Migration idempotente + dump Neo4j avant migration + test post-migration count |
| Confusion sémantique `valid_from` vs `ingested_at` | ADR explicite (ce doc) + commentaires Cypher + tests qui exercent les 3 queries types §2.4 |

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
| #319 | PHASE A1.1 — Rédiger cet ADR | 0.5j | 🟡 in_progress |
| #320 | PHASE A1.2 — Migration schéma Neo4j (`migrations/v6_bitemporal_claims.cypher`) + tests idempotence | 1j | pending (blocked by #319) |
| #321 | PHASE A1.3 — Pipeline ingestion : extraction `document_valid_from` + peuplement claim timestamps | 1.5-2j | pending (blocked by #320) |
| #322 | PHASE A1.4 — Tests Gate-B (4 tests) — validation 100% claims OK | 0.5j | pending (blocked by #321) |
| **Total Phase A1** | | **~4-5j** | |

Conforme à l'estimation EXECUTION_ROADMAP §2 Phase A1 (1 semaine).

### 6.2 Critères de réussite Phase A1 (Gate-B)

- ✅ Migration `v6_bitemporal_claims.cypher` exécutée avec succès
- ✅ Tests d'audit : 0 claim sans `valid_from` OU `ingested_at` (champs obligatoires)
- ✅ Tests cross-tenant : indexes utilisés, isolation préservée
- ✅ Tests queries point-in-time : 3 patterns §2.4 fonctionnent sur échantillon
- ✅ Pipeline ré-ingestion : sample doc créé avec 100% de claims aux 4 timestamps

Si tous OK → Phase A1 fermée, démarrage Phase A2 (relations claim-vs-claim).

### 6.3 Dépendances et ordre

```
A1.1 ADR (#319) — VALIDATED →  A1.2 Migration (#320) →  A1.3 Pipeline (#321) →  A1.4 Tests (#322) →  Phase A2
```

Strict séquentiel (chaque tâche débloque la suivante).

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
| Fred (utilisateur produit) | _à valider_ | 📝 Proposed |
| Vision-guardian | _audit auto à la première invocation post-publication_ | _pending_ |

*ADR rédigé le 2026-05-19 dans le cadre de la Phase A1 (refondation runtime KG-first).*
