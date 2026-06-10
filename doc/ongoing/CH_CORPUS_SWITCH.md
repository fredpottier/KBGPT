# Chantier — Bascule de corpus actif (multi-corpus live)

> **Statut** : **implémenté** (10/06/2026). Reste : déployer (restart app+workers) +
>   créer l'index Qdrant `tenant_id` sur la collection vivante (sinon effectif à la
>   prochaine ingestion).
> **Date** : 2026-06-10 — Branche : feat/phase-b-augmentee.
> **Origine** : préparer l'ajout d'un corpus médical (études cliniques → tensions +
>   lifecycle par dates). Prérequis : pouvoir basculer **tout le système** (chat +
>   ingestion) d'un corpus à l'autre, sans refonte, et faciliter les démos.

---

## 1. Principe & décision

Un **corpus actif global** (un seul `tenant_id` pour toute l'instance, modèle
mono-opérateur / démo), stocké en Redis. Choisi par décision produit (vs per-user JWT,
inutilement lourd ici). Voir la session du 10/06.

**Constat clé de la cartographie** : `tenant_id` est **déjà câblé de bout en bout** —
chat (`RuntimeV6Request.tenant_id` → orchestrateur), retrieval (filtre payload Qdrant),
ingestion (job → `claimfirst_process_job`). Et **tous les corpus partagent UNE collection
Qdrant** (`knowbase_chunks_v2`) + **un graphe Neo4j**, isolés par `tenant_id`
(filtre/propriété + contrainte composite). Donc « changer de corpus » = **changer un seul
`tenant_id`**. Aucune refonte ; la séparation physique par collection reste possible plus
tard pour UN corpus si besoin (compliance/volume).

---

## 2. Implémentation (points de greffe)

### Backend
| Brique | Fichier | Détail |
|---|---|---|
| Store Redis | `common/active_corpus.py` (NEW) | clé `osmosis:active_corpus`, get (fail-soft→`default`) / set (strict) |
| Index Qdrant | `retrieval/qdrant_layer_r.py` | ajout de `tenant_id` à l'index payload KEYWORD (filtrage efficace à l'échelle) |
| Endpoints admin | `api/routers/admin.py` | `GET/PUT /admin/active-corpus` (require_admin) |
| Substitution chat | `api/routers/runtime_v6.py` | `/answer` : si `tenant_id == "default"` (sentinelle frontend) → corpus actif. Tenant explicite (bench) respecté. |
| Estampille ingestion | `ingestion/queue/dispatcher.py` + `ingestion/folder_watcher.py` | `enqueue_pdf/pptx` propagent `tenant_id` ; le watcher lit le corpus actif à l'enqueue → **jobs en vol gardent leur tenant** (switch-safe) |

### Frontend
| Brique | Fichier | Détail |
|---|---|---|
| API client | `lib/api.ts` | `api.activeCorpus.get()/set()` |
| Sélecteur admin | `components/admin/CorpusSwitcher.tsx` (NEW) | monté en tête de `app/admin/settings/page.tsx` |
| Bannière chat | `components/chat/ActiveCorpusBadge.tsx` (NEW) | « Corpus : … » dans l'en-tête `app/chat/page.tsx` (fail-soft) |

### Tests
`tests/common/test_active_corpus.py` — 7 tests (défaut, get/set, fail-soft, Redis indispo, bytes).

---

## 3. Déploiement

1. **Restart app + workers + watcher** pour recharger le code (src monté → pas de rebuild) :
   `app` (substitution chat + endpoints), `ingestion-worker(s)` + `folder-watcher` (estampille).
2. **Index Qdrant `tenant_id`** : créé automatiquement à la prochaine `ensure_layer_r_collection`
   (ingestion). Pour l'appliquer **maintenant** sur la collection vivante :
   ```python
   from qdrant_client.models import PayloadSchemaType
   from knowbase.common.clients import get_qdrant_client
   get_qdrant_client().create_payload_index("knowbase_chunks_v2", "tenant_id", PayloadSchemaType.KEYWORD)
   ```
3. **Choisir le corpus actif** dans Admin → Configuration → « Corpus actif » (défaut `default`
   = aéro-legacy ; mettre `aero` pour le corpus à 17 455 claims, ou le futur `medical`).

---

## 4. Ajout du corpus médical (suite)

- Déposer les docs dans `docs_in` **après** avoir activé le corpus cible (ex. créer/activer
  `medical`) → le watcher les estampille `tenant_id=medical`.
- **Prérequis qualité** : installer un **contexte de domaine médical** avant ingestion
  (oriente l'extraction ; cf. pattern `set_domain_context_*`). Sans lui, extraction générique.
- Études cliniques : axe **lifecycle par dates** (peu de SUPERSEDES, mais antériorité/date de
  publication pondèrent) + **tensions** natives (cohortes/méthodo/interprétations).

---

## 5. Limites connues / évolutions

- Modèle **global** (un corpus actif pour toute l'instance) : adapté mono-opérateur/démo.
  Le mécanisme cockpit per-tenant (`get_cockpit_tenant`, JWT) reste pour les opérations admin.
- Isolation **logique** (filtre `tenant_id`), pas physique. Séparation par collection =
  chantier ultérieur ciblé si un corpus l'exige.
- Tenant `default` = aéro-legacy (non renommé, décision 10/06). Nommer proprement plus tard.

---

*Lié à : `CATALOGUE_FONCTIONNEL.md`, protocole non-régression bi-corpus, #468 hygiène méta.*
