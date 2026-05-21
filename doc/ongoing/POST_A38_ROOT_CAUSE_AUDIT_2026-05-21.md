# Audit cause racine A3.8 — Mismatch schéma KG vs ADR A3 (2026-05-21)

**Status** : Audit historique terminé. Cause racine identifiée. Fix planifié
(option dénormalisation pipeline + backfill).

---

## 1. Problème observé

Bench A3.8 (Phase A3 final) initié → audit KG révèle :

| Propriété attendue par runtime_a3.execute Cypher | Couverture KG (11622 claims) |
|---|---|
| `subject_canonical` | **0%** (0/11622) |
| `predicate` | 0% |
| `value` | 0% |
| `marker_type` | 0% |
| `valid_until` | 0% |
| `invalidated_at` | 0% |
| `valid_from` | 84.9% (peut être NULL) |
| `ingested_at` | 100% |

Conséquence si bench A3.8 lancé : 100% des `kg_claims` retourneraient 0 result,
tous verdicts → INSUFFICIENT_EVIDENCE, résultats inutilisables.

---

## 2. Audit historique (chronologie git)

| Date | Commit | Événement |
|---|---|---|
| 2025-12-22 | 8c42ab9 | Architecture Relations V3 + Claims MVP spec |
| 2025-12-25 | bd7805c | Création `CanonicalClaimWriter` (Phase 2.11-2.12) |
| 2026-01-06 | 71fa69f / afa2346 | Pass 2a (Structural Topics) / Pass 3 (Semantic Consolidation) |
| 2026-01-09 | 5ee26ca | "Intégrer Pass 2.0 (Promotion) dans le workflow" |
| 2026-01-22 | 90cfb04 / 6b2b6b3 / 6909895 | Fixes pass2 (process_document_topics_v2, contracts, PHASE_REGISTRY) |
| 2026-02-01 | e9bcae2 | Pipeline V2 stabilisé (feature flags) |
| 2026-03-17 | 14b2be1 | "Nettoyage pages obsolètes + ... claimfirst" — **dernière trace pass2 dans commits** |
| 2026-05-20 | e50405f | Phase A2 cleanup schéma |

**Trou** entre mars 2026 et mai 2026 : aucune mention pass2 / CanonicalClaim
dans les commits. La couche a été silencieusement abandonnée.

---

## 3. Doc officielle : décision documentée

`doc/ARCH_CLAIMFIRST.md` (doc d'architecture ClaimFirst actuelle) :

- §5 "Corpus Promotion (Pass 2.0)" — décrit Pass 2 pour les CanonicalConcept
- §7 "CanonicalClaim (unaires)" — décrit le design de la couche L2
- **§Future Work (ligne 412)** : `| CanonicalClaim (Layer 2 consolidation) | Spec draft, non implémenté |`

**Décision documentée explicite** : CanonicalClaim **n'est PAS implémenté**.
Le code `canonical_claim_writer.py` existe mais n'est invoqué que via
`/api/admin/pass2/*` endpoints (admin manuel, hors pipeline d'ingestion auto).

Le pipeline d'ingestion ClaimFirst produit uniquement `:Claim` raw avec
`structured_form_json` (sérialisé) — c'est le format autoritatif.

---

## 4. Le format réel des claims

Sample observé sur le KG :
```json
{"subject": "SAP Solution Manager", "predicate": "BASED_ON",
 "object": "SAP Business Suite maintenance strategy"}
```

L'info structurée **EXISTE** sur 4488/11622 claims (38.6%), sérialisée dans
`structured_form_json`. Les 7134 autres claims n'ont pas de `structured_form` —
ils sont des claims textuels non décomposés en triplets.

---

## 5. Cause racine

**L'ADR Phase A3 (mon design) a divergé de `doc/ARCH_CLAIMFIRST.md` (doc
officielle pipeline)** :

- ADR A3 §4 Cypher templates : `WHERE c.subject_canonical = $subject AND c.predicate = $predicate`
- Réalité KG : ces propriétés n'existent pas en colonnes directes, l'info est
  dans `structured_form_json` sérialisé

J'ai conçu l'ADR A3 sans vérifier le schéma réel des `:Claim` actuels. Le
mapping correct est :
- `subject_canonical` (A3) = `structured_form.subject` (ClaimFirst)
- `predicate` (A3) = `structured_form.predicate` (ClaimFirst)
- `value` (A3) = `structured_form.object` (ClaimFirst — pas "value" !)

`marker_type` n'existe ni en propriété ni en JSON — c'est un concept exclusif
des relations (cf ADR_RELATIONS_CLAIM_CLAIM §3.3 sur les markers `explicit/
inferred/prudence` des CONTRADICTS/SUPERSEDES).

`valid_until` et `invalidated_at` sont initialisés à `None` à l'ingestion par
`_persist_claims_batch` (cf `claim_persister.py:1124-1129`) — comportement
attendu, ils sont set ultérieurement par la détection contradictions (jamais
déclenché récemment d'où 0%).

---

## 6. Décision corrective (validée user)

**Option 1 — Dénormalisation pipeline + backfill** :

1. Modifier `src/knowbase/claimfirst/models/claim.py` `to_neo4j_properties()` :
   quand `self.structured_form` est présent, ajouter en props directes :
   - `subject_canonical = self.structured_form.get("subject")`
   - `predicate = self.structured_form.get("predicate")`
   - `object_canonical = self.structured_form.get("object")`
2. **`structured_form_json` reste écrit intact** (rétro-compat 100%, source
   autoritative).
3. **Backfill script idempotent** pour les 4488 claims existants ayant
   `structured_form_json` → ajouter les 3 props.
4. **Adapter `runtime_a3/execute.py` Cypher** : utiliser `object_canonical` au
   lieu de `value` (le nom `value` est ambigu en SQL/Cypher ; `object_canonical`
   reflète clairement que c'est le `object` du structured_form dénormalisé).
5. **Adapter `ClaimSummary` Pydantic** : `_claim_from_node()` mappe
   `object_canonical` → champ `value` (output).
6. **Amender ADR A3 §4** pour clarifier le mapping vs `ARCH_CLAIMFIRST.md`.

**Conséquence pratique** :
- Sur les 4488 claims structured : Cypher fonctionne avec indexes (perf).
- Sur les 7134 claims non-structured : ils n'ont pas de triplet, pas trouvables
  via `kg_claims` (fact_lookup). C'est attendu — claims textuels sans
  décomposition relationnelle. Le runtime A3 les ignore via les requêtes par
  subject/predicate.
- `marker_type` retiré de `ClaimSummary` Pydantic A3 (concept exclusif relations).
- `valid_until` et `invalidated_at` restent dans le schéma mais resteront NULL
  tant que la détection contradiction n'est pas déclenchée.

---

## 7. Tâches dérivées

| Tâche | Type | Estimation |
|---|---|---|
| A3.8-prep.1 | Modifier `Claim.to_neo4j_properties()` + tests | 30min |
| A3.8-prep.2 | Backfill script + dry-run sur sample | 1h |
| A3.8-prep.3 | Run backfill 4488 claims + verify | 15min |
| A3.8-prep.4 | Adapter `runtime_a3/execute.py` Cypher (object_canonical) | 15min |
| A3.8-prep.5 | Adapter `_claim_from_node()` + tests | 15min |
| A3.8-prep.6 | Amender ADR A3 §4 + ADR_BITEMPOREL si nécessaire | 30min |
| A3.8-prep.7 | Tests non-régression V5 + A3 + Smoke runtime_v6 sur 3 claims réels | 30min |
| **Total prep** | | **~3h30** |
| A3.8 (bench complet) | reporté après prep | 4-8h selon LLM live |

---

## 8. Leçon apprise (mémoire)

**Avant tout ADR runtime, AUDITER le schéma KG réel ne pas se contenter des
docs ADR antérieures**. La spec `ARCH_CLAIMFIRST.md` est l'autorité sur le
format des Claims — l'ADR A3 aurait dû la lire en P0.

L'ADR_BITEMPOREL_CLAIMS a ajouté correctement les timestamps (les 0% sur
`valid_until`/`invalidated_at` sont attendus à ingestion, pas un bug). C'est
**uniquement** mon ADR A3 qui a halluciné `subject_canonical`/`predicate`/`value`
en props directes.

À mémoriser : `feedback_adr_must_audit_real_kg_schema`.
