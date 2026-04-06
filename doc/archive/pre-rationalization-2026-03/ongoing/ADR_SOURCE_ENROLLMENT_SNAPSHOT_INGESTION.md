# ADR — Source Enrollment, Snapshot Provenance & Event-Driven Ingestion

**Statut :** Draft
**Date :** 2026-03-27
**Auteurs :** Consensus Claude Opus + ChatGPT + Fred
**Contexte :** Phase 3 — Multi-Source Architecture

---

## Contexte

OSMOSIS est un graphe documentaire attributif : toute connaissance est rattachee a un document source, sans extrapolation au-dela du corpus. Aujourd'hui, l'ingestion repose sur un depot manuel de fichiers dans un repertoire local (`burst/pending`) suivi d'un declenchement explicite du pipeline. Ce modele est acceptable en phase de developpement mais incompatible avec un deploiement production pour trois raisons :

1. **Les documents vivent ailleurs** — SharePoint, OneDrive, Teams, Google Drive, S3, filesystems reseau. On ne peut pas demander aux utilisateurs de copier des fichiers dans un repertoire.
2. **OSMOSIS ne doit pas devenir un stockage** — dupliquer les documents source cree des desynchronisations et pose des problemes de confidentialite (donnees sensibles sur une plateforme SaaS).
3. **La tracabilite exige un lien vivant** — les resultats de recherche doivent pointer vers le document source exact, dans la version exacte qui a ete lue, avec detection des modifications ulterieures.

## Probleme

Comment permettre a OSMOSIS d'ingerer des documents depuis des sources heterogenes sans devenir le systeme de stockage, tout en maintenant une tracabilite complete entre chaque information extraite et la version precise du document source ?

## Decision

Adopter une architecture **"Source Enrollment & Push-to-Osmosis"** basee sur trois piliers :

1. **Enrollment** — un admin declare des perimetres documentaires a surveiller
2. **Snapshot Provenance** — chaque ingestion capture l'etat exact du document a l'instant de lecture
3. **Event-Driven Ingestion** — tous les modes d'entree convergent vers un evenement unique

OSMOSIS ne stocke jamais durablement le binaire source. Il stocke des **references** (ou vit le document) et des **snapshots** (ce qui a ete lu, quand, dans quel etat).

---

## Invariants

### I-SRC-1 : Zero-retention du binaire source
OSMOSIS ne conserve jamais durablement le fichier document original. L'acquisition est temporaire (streaming ou fichier ephemere), le cache d'extraction peut etre supprime apres traitement. Seuls les artefacts extraits (chunks, claims, entities) persistent.

### I-SRC-2 : Attribution au snapshot, pas au document
Toute information produite (Claim, Entity, TypeAwareChunk, DocItem) est rattachee a un **DocumentSnapshot** precis, pas seulement a un DocumentSource. Si le document evolue et qu'on re-ingere, les anciennes claims restent liees a l'ancien snapshot, les nouvelles au nouveau.

### I-SRC-3 : Lien d'acces vers la source d'origine
L'acces utilisateur renvoie d'abord vers la source d'origine ("Ouvrir dans SharePoint"). OSMOSIS ne sert pas de proxy de telechargement sauf si la source ne fournit aucun mecanisme de lien direct.

### I-SRC-4 : Non-contamination du pipeline semantique
La couche source est une couche d'acquisition et de navigation. Les connecteurs ne doivent jamais influencer le raisonnement semantique (extraction de claims, detection de relations, synthese). Le pipeline d'ingestion recoit un flux de bytes + des metadonnees, rien de plus.

### I-SRC-5 : Evenement d'ingestion comme interface unique
Scan automatique, webhook, push utilisateur, upload manuel — tous produisent le meme `IngestionEvent`. Le pipeline en aval ne sait pas et n'a pas besoin de savoir d'ou vient le signal.

### I-SRC-6 : Tracabilite des disparitions
Un document supprime, deplace ou rendu inaccessible a la source est **marque**, pas efface du KG. Les claims extraites restent valides en tant que "ce document affirmait X au moment ou il existait".

---

## Modele de donnees

### SourceConnection
La tuyauterie technique vers un systeme source.

```
SourceConnection:
  connection_id: UUID
  tenant_id: str
  source_type: "microsoft_graph" | "google_workspace" | "filesystem" | "s3"
  auth_method: "oauth2" | "service_account" | "api_key" | "local"
  credentials_ref: str           # reference vers un vault ou env_var
  display_name: str              # "SharePoint Contoso - Site SAP"
  status: "connected" | "expired" | "revoked" | "error"
  created_at: timestamp
  last_verified_at: timestamp
```

### SourceScope
Le perimetre administratif surveille. C'est l'objet central de l'enrollment.

```
SourceScope:
  scope_id: UUID
  connection_id: -> SourceConnection
  container_id: str              # site_id+library_id (SharePoint) ou folder_id (Drive)
  path: str                      # "/Documents SAP/Guides"
  display_name: str              # "Guides SAP - Security & Operations"
  mode: "WATCHED" | "MANUAL_ONLY"
  sync_policy: SyncPolicy
  include_patterns: ["*.pdf", "*.pptx", "*.docx"]
  exclude_patterns: ["*DRAFT*", "~$*", "*.tmp"]
  auto_ingest: bool
  status: "active" | "paused" | "error"
  created_by: user_id
  created_at: timestamp
  last_scan_at: timestamp
```

### SyncPolicy
Politique de synchronisation par scope.

```
SyncPolicy:
  scan_mode: "INITIAL_FULL_SCAN" | "NEW_ONLY" | "NEW_AND_UPDATED"
  scan_interval: "1h" | "6h" | "daily" | "webhook_only" | "manual"
  on_update: "AUTO_REINGEST" | "MANUAL_REVIEW" | "NOTIFY_ONLY"
  on_deletion: "MARK_STATUS" | "IGNORE" | "ARCHIVE_CLAIMS"
  on_access_revoked: "MARK_STATUS" | "QUARANTINE"
  max_file_size_mb: int          # limite par fichier
  max_files_per_scan: int        # limite par scan (evite les explosions)
```

### DocumentSource
L'identite logique d'un document dans son systeme source.

```
DocumentSource:
  source_id: UUID
  tenant_id: str
  scope_id: -> SourceScope       # null si push isole
  source_locator: str            # "driveItem:abc123" | "/path/to/file.pdf"
  display_name: str              # "SAP S/4HANA 2023 Security Guide"
  source_type: "pdf" | "pptx" | "docx" | "xlsx"
  open_uri: str                  # URL pour ouvrir dans la source
  download_capability: "DIRECT_LINK" | "BROKERED" | "STREAM_ONLY" | "NONE"
  source_metadata: dict          # auteur, taille, created_at cote source
  lifecycle_status: "discovered" | "eligible" | "ingested" | "failed"
                    | "suppressed" | "moved" | "deleted_at_source" | "access_revoked"
  discovered_at: timestamp
  discovered_by: "scope_scan" | "user_push" | "manual_upload"
  last_checked_at: timestamp
```

### DocumentSnapshot
L'etat exact du document au moment de l'ingestion. C'est la **racine de provenance** de tout ce qui est produit par le pipeline.

```
DocumentSnapshot:
  snapshot_id: UUID
  source_id: -> DocumentSource

  # Hierarchie de detection de changement (par ordre de priorite)
  observed_etag: str             # priorite 1 — fourni par SharePoint/Graph
  observed_version_id: str       # priorite 1b — revision Drive/S3
  observed_modified_at: timestamp # priorite 2 — last modified cote source
  observed_hash: str             # priorite 3 — sha256 du contenu (fallback couteux)

  # Version metier (extraite du contenu, pas du systeme source)
  # Distinction critique : la version fichier != la version de ce qui est affirme
  # Ex: "FPS03" est une version metier, "etag:W/abc" est une revision fichier
  semantic_version: str          # extrait par le pipeline (ex: "2023 FPS03")

  # Pipeline
  pipeline_version: str          # "v2_docling_parsev4" | "v2_pptx_native"
  extraction_duration_s: float
  ingested_at: timestamp
  ingestion_status: "completed" | "failed" | "superseded"

  # Lien vers le KG
  doc_version_id: str            # cle de jointure avec Claims, Entities, Chunks
  chunks_count: int
  claims_count: int
```

### IngestionEvent
Le signal d'entree unifie. Tous les modes d'entree produisent cet objet.

```
IngestionEvent:
  event_id: UUID
  event_type: "DISCOVERED_IN_SCOPE" | "UPDATED_IN_SCOPE" | "DELETED_IN_SCOPE"
             | "PUSH_REQUESTED" | "MANUAL_UPLOAD" | "REINGEST_REQUESTED"
  source_locator: str
  scope_id: str                  # null si push isole ou upload
  connection_id: str             # null si filesystem local
  requested_by: str              # user_id ou "system"
  priority: "normal" | "high"
  metadata: dict                 # tags, projet cible, workspace, commentaire
  created_at: timestamp
  processing_status: "pending" | "processing" | "completed" | "failed"
```

---

## Flux nominaux

### Flux 1 — Enrollment & Scan initial (admin)

```
1. Admin configure SourceConnection (OAuth Microsoft Graph)
2. Admin cree SourceScope (bibliotheque "Guides SAP", mode WATCHED, sync NEW_AND_UPDATED)
3. OSMOSIS lance un scan initial du scope
4. Pour chaque document decouvert :
   a. Creation DocumentSource (status = discovered)
   b. Evaluation eligibilite (patterns include/exclude, taille, format)
   c. Si eligible : status -> eligible, creation IngestionEvent(DISCOVERED_IN_SCOPE)
   d. Si non eligible : status -> suppressed
5. IngestionEvent entre dans la queue d'ingestion
6. Worker acquiert temporairement le binaire via l'adapter
7. Pipeline V2 (extraction -> structural graph -> cache ephemere)
8. Creation DocumentSnapshot avec etag + hash + pipeline_version
9. ClaimFirst produit claims/entities lies au snapshot
10. Binaire temporaire supprime (I-SRC-1)
11. DocumentSource.lifecycle_status -> ingested
```

### Flux 2 — Push from Source (utilisateur)

```
1. Utilisateur dans Teams/SharePoint clique "Add to OSMOSIS"
2. Le plugin envoie POST /api/sources/ingest :
   {event_type: "PUSH_REQUESTED", source_locator: "driveItem:abc123",
    connection_id: "conn_graph_contoso", requested_by: "user@contoso.com"}
3. OSMOSIS cree ou retrouve le DocumentSource
4. Acquisition temporaire -> Pipeline V2 -> DocumentSnapshot
5. Confirmation envoyee a l'utilisateur
```

### Flux 3 — Detection de changement (automatique)

```
1. Watcher poll le SourceScope (ou webhook Graph recu)
2. Pour chaque document modifie (etag different du dernier snapshot) :
   a. IngestionEvent(UPDATED_IN_SCOPE)
   b. Nouvelle acquisition -> Pipeline V2 -> Nouveau DocumentSnapshot
   c. Ancien snapshot marque "superseded"
   d. Claims ancien snapshot : intactes, liees a l'ancien snapshot
   e. Claims nouveau snapshot : liees au nouveau snapshot
   f. Detection d'evolution cross-snapshot possible (QuestionSignatures)
3. Pour chaque document supprime :
   a. DocumentSource.lifecycle_status -> deleted_at_source
   b. Claims existantes : intactes mais marquees comme provenant d'un doc supprime
   c. Warning dans les resultats de recherche
```

### Flux 4 — Acces source dans les resultats

```
1. Utilisateur recoit un resultat de recherche
2. Le chunk porte un source_id -> DocumentSource -> open_uri
3. Bouton "Ouvrir dans SharePoint" : utilise open_uri
4. Bouton "Telecharger" : adapter.resolve_download_url(source_locator)
5. Si le document a change depuis le snapshot :
   badge "Document modifie depuis l'ingestion (27 mars -> 2 avril)"
6. Si le document a ete supprime :
   badge "Document supprime a la source — informations potentiellement obsoletes"
```

---

## Interface SourceAdapter

Chaque systeme source implemente cette interface. L'adapter est une couche d'acquisition, pas de raisonnement.

```python
class SourceAdapter(Protocol):
    source_type: str

    async def authenticate(self, credentials: dict) -> ConnectionStatus
    async def browse(self, scope: SourceScope, path: str) -> list[DocumentRef]
    async def get_revision_info(self, locator: str) -> RevisionInfo
        # RevisionInfo: etag, version_id, modified_at, size
    async def stream_content(self, locator: str) -> AsyncIterator[bytes]
    async def resolve_open_uri(self, locator: str) -> str
    async def resolve_download_url(self, locator: str) -> Optional[str]
    async def list_changes(self, scope: SourceScope, since: timestamp) -> list[ChangeEvent]
```

### Adapters prevus

| Adapter | Systemes couverts | Auth | Priorite |
|---------|-------------------|------|----------|
| `FilesystemAdapter` | Local, reseau, NFS | Aucune | Existe (burst/pending) |
| `MicrosoftGraphAdapter` | SharePoint, OneDrive, Teams files | OAuth2 | Phase 3.2 |
| `GoogleWorkspaceAdapter` | Google Drive, Shared Drives | OAuth2 | Phase 3.3 |
| `S3Adapter` | AWS S3, MinIO, tout S3-compatible | Access Key / IAM | Phase 3.4 |

Note : Teams, OneDrive et SharePoint utilisent la meme API Microsoft Graph. Un seul adapter les couvre tous.

---

## Non-goals

1. **OSMOSIS n'est pas un systeme de gestion documentaire (GED).** Pas de versioning, pas de workflow d'approbation, pas d'edition collaborative.
2. **OSMOSIS ne gere pas les permissions d'acces aux documents sources.** Si un utilisateur n'a pas acces au document dans SharePoint, OSMOSIS ne lui donnera pas acces non plus.
3. **Les plugins UX (SharePoint add-in, extension navigateur) ne sont pas des composants architecturaux.** Ce sont des facades optionnelles vers l'API d'IngestionEvent. L'architecture ne doit pas en dependre.
4. **La re-ingestion n'est pas un diff.** Quand un document change, on re-ingere entierement et on cree un nouveau snapshot. Pas de diff incremental au niveau du contenu.

---

## Impact sur l'existant

### Ce qui change

| Composant | Avant | Apres |
|-----------|-------|-------|
| `doc_id` dans le KG | Identifiant unique du document | Pointe vers un `DocumentSource.source_id` |
| `doc_version_id` dans le KG | Hash du contenu | Pointe vers un `DocumentSnapshot.snapshot_id` |
| `burst/pending` | Seul point d'entree | Devient le `FilesystemAdapter`, un adapter parmi d'autres |
| Cache d'extraction | Conserve indefiniment | Peut etre ephemere (zero-retention en production) |
| Resultats de recherche | Pas de lien source | Lien "Ouvrir dans [source]" + warning si modifie |

### Ce qui ne change pas

- Le pipeline V2 (extraction, structural graph, vision)
- ClaimFirst (claims, entities, relations)
- Le rechunker et Qdrant Layer R
- Le modele de synthese et de recherche
- Les scripts post-import

---

## Plan de mise en oeuvre

### Phase immediate — Formalisation du filesystem adapter
- Modeliser `DocumentSource` + `DocumentSnapshot` dans Postgres
- Migrer les `doc_id` / `doc_version_id` existants
- Formaliser le burst/pending comme `FilesystemAdapter`
- API `POST /api/sources/ingest` — endpoint unique

### Phase 3.2 — Microsoft Graph
- OAuth2 flow pour SharePoint/OneDrive
- Browse depuis l'UI OSMOSIS
- Selection de scopes par l'admin (watched folders)
- Scan initial + polling periodique
- "Ouvrir dans SharePoint" dans les resultats

### Phase 3.3 — Sync & Detection
- Webhooks Microsoft Graph
- Detection etag/version -> re-ingestion automatique
- Warning "source modifiee" dans les resultats
- Gestion des statuts (deleted, moved, access_revoked)
- Google Workspace adapter

### Phase 3.4 — Push from Source
- API push stabilisee
- SharePoint add-in "Add to OSMOSIS"
- Extension navigateur Chrome/Edge
- Google Drive action contextuelle
- S3 adapter

---

## References

- North Star OSMOSIS : "Verite documentaire contextualisee"
- ADR Unite de Preuve vs Unite de Lecture
- ADR Structural Graph from Docling
- Phase 3 Roadmap : Multi-Source Simplifie
- Consensus architectural Claude Opus + ChatGPT (2026-03-27)
