# ADR — Cockpit Operationnel OSMOSIS

**Date** : 2026-03-28
**Statut** : Approuve (design), En attente d'implementation
**Branche** : `feat/cockpit-operationnel` (a creer)

---

## Contexte

OSMOSIS a besoin d'un centre de pilotage compact, pensable pour un petit ecran secondaire (Corsair Edge, tactile, ~480x800px). L'objectif n'est pas un dashboard analytique type Kibana mais une **supervision operationnelle** lisible en < 1 seconde, avec push temps reel.

## Decision

Construire un service Python independant (FastAPI) qui observe les memes sources de donnees que l'app OSMOSIS (Redis, Docker, Qdrant, Neo4j, AWS EC2) sans en dependre. Si l'app crash, le cockpit le detecte et l'affiche.

---

## Architecture 4 couches

```
COUCHE 4 — Renderer (HTML/SVG/CSS/JS vanilla, WebSocket client)
    |  WebSocket push (JSON)
COUCHE 3 — Cockpit API (FastAPI, port 9090)
    |  GET /cockpit/state, WS /cockpit/ws
    |  Moteur ETA + moteur Smart Events
    |  polling interne 5-15s
COUCHE 2 — Collecteurs (1 par source)
    |  DockerCollector, PipelineCollector, BurstCollector,
    |  KnowledgeCollector, LLMBudgetCollector
    |
COUCHE 1 — Sources de verite
    Docker socket | Redis | Qdrant | Neo4j | AWS EC2 API | SQLite local
```

### Principe cle
Le cockpit est un **processus separe**, pas integre dans l'app OSMOSIS.

---

## 6 Widgets

### 1. EC2 Burst
- **Source de verite = AWS EC2 API** (boto3 `describe_instances`, tag `Project=KnowWhere`)
- **JAMAIS Redis** pour l'etat EC2 (desynchronisation connue lors des recalls Spot)
- Redis utilise UNIQUEMENT pour le contexte job (batch_id, docs done/total)
- Health check vLLM + TEI via HTTP direct sur l'IP decouverte
- Cache 15s pour eviter spam API AWS
- Etats deduits : off | starting | booting | ready | stopping

### 2. Pipeline actif (visualisation graphique)
- **Rendu en noeuds SVG** relies par des lignes, pas une liste texte
- Cercles : vert (done), jaune/orange pulsant (en cours), gris (pending), rouge (echec)
- **Ligne progressive** : linearGradient SVG dont l'offset avance avec le % de l'etape
- Noms d'etapes tronques (5-6 chars), tooltip au tap
- Horizontal si <= 9 etapes, vertical si plus
- Definitions de pipelines en YAML (generique, pas code en dur)
- 3 pipelines V1 : claim-first, post-import, burst-extract

### 3. Conteneurs (groupes avec activite temps reel)
- **3 groupes** :
  - INFRA (4) : qdrant, redis, neo4j, postgres
  - APP (4) : app, ingestion-worker, folder-watcher, frontend
  - MONITORING (3) : loki, promtail, grafana
- Indicateur d'activite CPU par conteneur (mini bar-graph SVG)
  - idle (gris, <2%), active (vert, 2-50%), busy (orange, >50%)
- Le worker qui "travaille" est immediatement visible visuellement
- Source : Docker API `container.stats(stream=False)`

### 4. Knowledge state (Qdrant + Neo4j)
- Qdrant : chunks count, connectivite
- Neo4j : nodes, claims, entities, facets, relations, contradictions
- Endpoints existants : `/api/admin/health`, `/api/claimfirst/status`

### 5. LLM Session + Soldes
- **Compteur de session avec RESET tactile** (bouton 48px+ pour Edge)
  - Cout depuis dernier reset, breakdown par modele, rate $/min
  - Reset via message WebSocket `{"type": "reset_llm_session"}`
- Soldes API (si cles billing fournies) :
  - OpenAI : `GET /v1/organization/costs` (cle API standard)
  - Anthropic : pas d'API billing publique → saisie manuelle + decompte
- Seuils visuels : OK (vert) / LOW (jaune) / CRITICAL (rouge)

### 6. Smart Events
- Moteur a regles evaluees a chaque cycle (10s)
- Regles V1 :
  - Pipeline bloque (0 progression depuis 5min)
  - Etape anormalement lente (>2.5x mediane historique)
  - Container down ou unhealthy
  - Burst active mais idle >10min
  - Credits LLM sous seuil critique
  - Neo4j +claims mais Qdrant inchange (bridge manquant)
  - Rendement faible (<5 claims/doc)
- Evenements avec TTL (disparaissent apres resolution ou expiration)

---

## Modele de donnees canonique

```python
@dataclass
class CockpitState:
    timestamp: datetime
    burst: BurstStatus
    pipeline: PipelineStatus | None
    container_groups: list[ContainerGroupStatus]
    knowledge: KnowledgeStatus
    llm_session: LLMSessionStatus
    llm_balances: LLMBalanceStatus
    events: list[SmartEvent]

@dataclass
class BurstStatus:
    active: bool
    status: str          # "off"|"starting"|"booting"|"ready"|"stopping"
    instance_ip: str | None
    instance_id: str | None
    instance_type: str | None
    instance_state: str | None    # etat AWS brut
    uptime_s: int | None
    vllm_healthy: bool
    tei_healthy: bool
    job_name: str | None
    docs_done: int | None
    docs_total: int | None

@dataclass
class PipelineStatus:
    name: str                      # "claim-first"|"post-import"|"burst-extract"
    run_id: str
    started_at: datetime
    elapsed_s: int
    stages: list[StageStatus]
    current_stage_index: int
    eta_remaining_s: int | None
    eta_finish: datetime | None
    eta_confidence: str            # "high"|"medium"|"low"|"unknown"

@dataclass
class StageStatus:
    name: str
    short_name: str                # 5-6 chars pour rendu SVG
    status: str                    # "done"|"running"|"pending"|"failed"|"skipped"
    duration_s: float | None
    progress: float | None         # 0.0-1.0
    detail: str | None

@dataclass
class ContainerGroupStatus:
    name: str                      # "infra"|"app"|"monitoring"
    containers: list[ContainerStatus]

@dataclass
class ContainerStatus:
    name: str
    status: str                    # "up"|"down"|"starting"
    health: str | None             # "healthy"|"unhealthy"
    uptime_s: int | None
    cpu_percent: float
    activity: str                  # "idle"|"active"|"busy"

@dataclass
class KnowledgeStatus:
    qdrant_ok: bool
    qdrant_chunks: int
    neo4j_ok: bool
    neo4j_nodes: int
    neo4j_claims: int
    neo4j_entities: int
    neo4j_facets: int
    neo4j_relations: int
    neo4j_contradictions: int
    last_refresh: datetime

@dataclass
class LLMSessionStatus:
    session_cost_usd: float
    session_started_at: datetime
    session_calls: int
    session_breakdown: dict         # {model: cost}
    cost_per_minute: float

@dataclass
class LLMBalanceStatus:
    openai_balance: float | None
    openai_status: str             # "ok"|"low"|"critical"|"unknown"
    anthropic_balance: float | None
    anthropic_status: str
    low_threshold: float           # defaut 10.0
    critical_threshold: float      # defaut 3.0

@dataclass
class SmartEvent:
    timestamp: datetime
    severity: str                  # "info"|"warning"|"critical"
    category: str                  # "pipeline"|"container"|"knowledge"|"budget"|"burst"
    message: str
    ttl_s: int                     # defaut 3600
```

---

## Modelisation generique des pipelines (YAML)

```yaml
pipelines:
  claim-first:
    redis_key: "osmose:claimfirst:state"
    redis_type: hash
    stages:
      - name: "Chargement corpus"
        short: "Load"
        phase_match: "LOADING"
      - name: "Extraction (par doc)"
        short: "Extr"
        phase_match: "EXTRACTING"
        iterable: true
        progress_fields: { done: "phase_items_done", total: "phase_items_total" }
      - name: "Chaines cross-doc"
        short: "Chain"
        phase_match: "CROSS_DOC_CHAINS"
      - name: "Canonicalisation entites"
        short: "Canon"
        phase_match: "CANONICALIZE_ENTITIES"
      - name: "Clustering cross-doc"
        short: "Clust"
        phase_match: "CROSS_DOC_CLUSTERING"
      - name: "QuestionSig cross-doc"
        short: "QSig"
        phase_match: "QS_CROSS_DOC_COMPARISON"
      - name: "Hygiene KG L1"
        short: "Hyg"
        phase_match: "KG_HYGIENE_L1"
    started_field: "started_at"
    status_field: "status"
    active_when: ["PROCESSING", "STARTING"]

  post-import:
    redis_key: "osmose:post_import:state:default"
    redis_type: json
    stages:
      dynamic: true
      completed_field: "completed_steps"
      current_field: "current_step_name"
      total_field: "total_steps"
      progress_field: "step_progress"
      detail_field: "step_detail"
    status_field: "running"
    active_when: [true]

  burst-extract:
    redis_key: "osmose:burst:state"
    redis_type: json
    stages:
      - name: "Preparation batch"
        short: "Prep"
        phase_match: "preparing"
      - name: "Demarrage Spot"
        short: "Spot"
        phase_match: ["requesting_spot", "waiting_capacity", "instance_starting"]
      - name: "Pret"
        short: "Ready"
        phase_match: "ready"
      - name: "Traitement"
        short: "Proc"
        phase_match: "processing"
        iterable: true
        progress_fields: { done: "documents_done", total: "total_documents" }
    started_field: "started_at"
    status_field: "status"
    active_when: ["preparing", "requesting_spot", "waiting_capacity",
                   "instance_starting", "ready", "processing"]
```

---

## Logique ETA

### Etape en cours (iterative)
```
rate = elapsed_stage / items_done
eta_stage = (items_total - items_done) * rate
confidence = "high" si done > 10, "medium" si > 3, "low" sinon
```

### Pipeline total
```
eta_total = eta_stage_courante + SUM(duree_mediane_historique[stages_restantes])
```

### Historique (SQLite local)
```sql
CREATE TABLE run_history (
    id INTEGER PRIMARY KEY,
    pipeline_type TEXT,
    run_id TEXT,
    stage_name TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_s REAL,
    items_processed INTEGER,
    metadata TEXT  -- JSON
);
```

### Niveaux de confiance
- high : stage iterative + done > 10 + historique >= 3 runs
- medium : stage iterative + done > 3 OU historique >= 1 run
- low : premiere execution, peu de donnees
- unknown : aucune donnee de progression

---

## Instrumentation necessaire des pipelines existants

### P0 — ClaimFirst (orchestrator.py, ~20 lignes)
Ajouter `_emit_phase_state()` aux transitions de phase :
- Redis HSET sur `osmose:claimfirst:state` avec :
  `phase`, `phase_status`, `phase_started_at`, `phase_elapsed_s`,
  `phase_items_done`, `phase_items_total`, `updated_at`
- Appeler : au debut, pendant (iterations), et a la fin de chaque phase

### P1 — Post-Import (post_import.py, ~1 ligne)
Ajouter `step_started_at` dans le state Redis avant chaque step.

### P1 — Burst (orchestrator.py, ~10 lignes)
Ajouter SETEX Redis (`osmose:burst:state:live`, TTL 3600) dans `_update_state()`.

### P2 — Extraction V2 (pas necessaire en V1)
Tourne a l'interieur des autres pipelines, progression du parent suffit.

---

## Strategie de rendu

### Approche en 2 temps
1. **Dev & iteration** : UI web avancee servie par FastAPI (port 9090), ouverte dans Chrome `--app`
2. **Production** : empaquetage Tauri v2 — meme code frontend, fenetre native (frameless, always-on-top, ~50 MB RAM)

Le code frontend (HTML/SVG/CSS/JS) est **identique** dans les deux cas. Tauri emballe le web dans un binaire natif avec controle fenetre. La migration est un copier-coller.

### Pourquoi Tauri v2 (et pas Electron, Qt, ImGui, etc.)
- **vs Electron** : meme rendu (WebView2 = Chromium) mais 3x moins de RAM (~50 MB vs ~150-300 MB)
- **vs Qt/QML** : rendu equivalent mais courbe d'apprentissage QML, theming CSS inexistant, packaging lourd (~200 MB)
- **vs Dear ImGui** : look utilitaire, pas premium, tactile quasi inexistant sur Windows
- **vs iCUE SDK** : documentation pauvre, lock-in Corsair, rendu tres contraint
- **vs Flutter** : integration Python penible (Dart = langage supplementaire)
- **vs Godot** : paradigme jeu video, friction d'integration disproportionnee

### Capacites Tauri specifiques au Edge
- `decorations: false` → fenetre frameless (pas de barre de titre)
- `always_on_top: true` → reste visible
- `resizable: false` + `width: 480, height: 800` → taille fixe
- Demarrage au boot possible nativement
- Empreinte memoire ~30-50 MB (reutilise WebView2 systeme)

### Lancement phase dev (Chrome kiosk)
```bash
chrome --app=http://localhost:9090/cockpit --window-size=2560,720 --window-position=0,1080
```
(position Y=1080 suppose ecran principal 1080p au-dessus du Edge)

### Lancement phase production (Tauri)
```json
// tauri.conf.json
{
  "windows": [{
    "width": 2560, "height": 720,
    "resizable": false, "decorations": false,
    "alwaysOnTop": false, "title": "OSMOSIS Cockpit"
  }]
}
```

---

## Design System

### Palette de couleurs (dark theme anti-fatigue)
```css
/* Fondation — warm-dark, pas de bleu froid */
--bg-base:          #080C14;    /* canvas background */
--bg-surface:       #0D1320;    /* widget cards */
--bg-elevated:      #131A2B;    /* header bars dans cards */
--border-subtle:    #1E2A3E;    /* contours cards */
--border-default:   #253247;    /* separateurs visibles */

/* Etats semantiques */
--success:          #10B981;    /* vert : done, healthy, ready */
--warning:          #F59E0B;    /* ambre : in-progress, degraded */
--error:            #EF4444;    /* rouge : failed, critical */
--active:           #3B82F6;    /* bleu : selected, processing */
--neutral:          #475569;    /* gris : pending, disabled */

/* Glows (pour cercles pipeline) */
--success-glow:     #10B98126;
--warning-glow:     #F59E0B26;
--error-glow:       #EF444426;

/* Texte */
--text-primary:     #E2E8F0;    /* contenu principal */
--text-secondary:   #94A3B8;    /* labels, metadata */
--text-tertiary:    #4A5568;    /* placeholder, desactive */
--text-accent:      #7DD3FC;    /* bleu ciel : highlights, liens */
--text-mono:        #CBD5E1;    /* valeurs monospace */
```

Tous les couples texte/fond valides WCAG AA minimum (ratio >= 5.4:1).

### Typographie
- **Donnees** : Fira Code 400/500/600 (monospace, tabular nums)
- **Labels** : Fira Sans 300/400/500/600 (sans-serif)
- Meme famille = x-height identique, alignement parfait nombres/labels
- Tailles :
  - XL (28px) : cout total LLM, KPI principal
  - LG (20px) : compteurs, IP
  - MD (14px) : valeurs secondaires
  - SM (11px) : timestamps, rates
  - Labels : 12px (principal), 10px (section headers, uppercase)
  - Minimum lisible a 60cm : 10px (labels non-critiques uniquement)

### Ecran cible : Corsair Xeneon Edge
- **2560 x 720 pixels** — ratio 32:9 ultrawide (bandeau horizontal)
- **14.5 pouces** — 372 x 120 mm physique
- **~183 PPI** — haute densite
- **5-point multi-touch**, 60Hz, AHVA
- Montage magnetique, HDMI + USB-C

### Layout 2560x720 — bandeau horizontal "cockpit strip"

Le format ultrawide impose un layout **en colonnes cote a cote**, pas empile.
Chaque widget est une **colonne verticale** occupant toute la hauteur disponible.

```
2560px
├────────────┬─────────────────────────────────────────┬───────────┬───────────┬────────────┬───────────┤
│            │                                         │           │           │            │           │
│  W1: EC2   │  W2: PIPELINE (zone principale)        │ W3: CONT  │ W4: KNOW  │ W5: LLM    │ W6: EVTS  │
│  BURST     │  noeuds SVG en ligne horizontale       │ AINERS    │ LEDGE     │ SESSION    │ SMART     │
│            │                                         │ groupes   │ Qdrant    │ cout+reset │ EVENTS    │
│  200px     │  960px — LE PLUS LARGE                 │ +CPU bars │ +Neo4j    │            │           │
│            │                                         │ 320px     │ 280px     │ 280px      │ 280px     │
│            │                                         │           │           │            │           │
├────────────┴─────────────────────────────────────────┴───────────┴───────────┴────────────┴───────────┤
│  TOPBAR 28px — "OSMOSIS COCKPIT" + horloge HH:MM:SS + dot WebSocket + pipeline name/ETA si actif     │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Dimensions exactes (safe area 8px, gap 8px) :

```
Usable: 2544 x 704 px (8px inset all sides)
Topbar: bas de l'ecran, full width, 28px height → y=684 to y=712

Zone widgets: 2544 x 676 px (au dessus du topbar)

  W1 EC2:      x=0,     w=200px   (colonne etroite — status compact)
  W2 PIPELINE: x=208,   w=920px   (colonne dominante — noeuds en ligne)
  W3 CONTAIN:  x=1136,  w=320px   (3 groupes empiles)
  W4 KNOWL:    x=1464,  w=272px   (metriques empilees)
  W5 LLM:      x=1744,  w=272px   (cout + bouton RESET)
  W6 EVENTS:   x=2024,  w=520px   (alertes, plus large pour messages)
```

**Note** : W6 Events est place a droite et assez large car les messages d'alerte
ont besoin de place horizontale. Alternative : W6 en barre fine sous le topbar
(full width, 1 ligne) si peu d'events.

### Avantage du format ultrawide pour le pipeline

Le pipeline peut maintenant etre affiche **en une seule ligne horizontale** !
Plus besoin de zigzag multi-rangees. Meme 13 etapes tiennent dans 920px :

```
920px / 13 etapes = ~70px par etape
Cercle 28px + gap 42px + ligne = largement suffisant
```

Rendu pipeline horizontal :
```
●━━━━●━━━━●━━━━●━━━━◉════○╌╌╌╌○╌╌╌╌○╌╌╌╌○
Load  Extr  Dedup Canon  Fac   Contr  Pers  Final
0:01  0:40  0:03  0:18  ▶0:12
                        ~0:09
```

C'est beaucoup plus lisible qu'un zigzag — la progression est un **rail horizontal**,
naturel a lire de gauche a droite, comme une timeline.

### Hierarchie visuelle (ordre de lecture en < 1s)
1. **0-300ms** : Pipeline W2 (bande centrale, la plus large, noeud pulsant visible immediatement)
2. **300-700ms** : EC2 pill (extreme gauche, couleur forte) + LLM cout (grand chiffre a droite)
3. **700ms+** : Conteneurs + Knowledge (metriques de fond) + Events (seulement si non-vide, flash couleur)

### Pipeline — rendu en noeuds SVG

Chaque etape = cercle 28px relies par des lignes. Disposition **horizontale en ligne droite**
(le format 2560x720 ultrawide le permet — 920px pour le pipeline, ~70px/etape) :
```
●━━━━●━━━━●━━━━●━━━━◉════○╌╌╌╌○╌╌╌╌○╌╌╌╌○
Load  Extr  Dedup Canon  Fac   Contr  Pers  Final
```
Progression lue naturellement de gauche a droite, comme un rail/timeline.

Etats des noeuds :
- **Done** : cercle vert plein (#10B981) + checkmark blanc
- **Running** : cercle ambre (#F59E0B) pulsant (1.8s ease-in-out) + anneau externe qui "respire" (2.2s)
- **Pending** : cercle gris (#253247) en pointilles
- **Failed** : cercle rouge (#EF4444) + croix
- **Skipped** : gris barre

Lignes de connexion :
- Done→Done : verte pleine
- →Running : **linearGradient SVG progressif** — offset avance avec le % de l'etape
- →Pending : grise en pointilles
- →Failed : rouge en pointilles

Labels d'etapes : Fira Sans 9-10px sous chaque noeud, tronques ~10 chars.

### Conteneurs — barres d'activite CPU

Mini bar-graph par conteneur (hauteur 4px, couleur par seuil CPU) :
- < 40% : bleu (#3B82F6)
- 40-70% : ambre (#F59E0B)
- > 70% : rouge (#EF4444)
- Transition douce : `width 800ms ease-out`

### LLM Session — bouton RESET tactile

- Taille : 96x56px (depasse largement le minimum 48px tactile)
- Style : fond sombre rouge subtil, bordure #EF4444
- Feedback : fill radial 200ms avant action (evite activation accidentelle)
- Confirmation : bordure flash vert 600ms puis retour
- Sous-texte : "SESSION" 8px

### Regles d'animation (anti-fatigue)
- **UN SEUL element pulse a la fois** (le noeud pipeline actif)
- Container dots pulsent SEULEMENT si unhealthy
- Event dots pulsent SEULEMENT si severity=ERROR
- Cout LLM anime seulement a l'arrivee d'un nouveau cout
- `@media (prefers-reduced-motion: reduce)` → animations statiques

### Interactions tactiles
- Bouton RESET LLM session : 96x56px, feedback radial
- Noeuds pipeline : zone tactile invisible 44px autour du cercle visible 28px
- Lignes conteneurs : toute la largeur = zone tap pour detail
- Events : tap pour expansion du message complet
- Tooltip au tap sur noms d'etapes tronques

---

## Stack technique

```
cockpit/
├── main.py                    # FastAPI, uvicorn, point d'entree (port 9090)
├── config.py                  # seuils, intervalles, pipeline defs
├── models.py                  # dataclasses CockpitState & co
├── collectors/
│   ├── docker_collector.py    # Docker API socket → ContainerGroupStatus (avec CPU stats)
│   ├── pipeline_collector.py  # Redis state keys → PipelineStatus
│   ├── burst_collector.py     # AWS EC2 API (boto3) → BurstStatus (JAMAIS Redis pour EC2)
│   ├── knowledge_collector.py # Qdrant HTTP + Neo4j bolt → KnowledgeStatus
│   └── llm_budget_collector.py # token stats API + billing → LLM*Status
├── engine/
│   ├── aggregator.py          # orchestre collecteurs, assemble CockpitState
│   ├── eta.py                 # calcul ETA + historique SQLite
│   └── events.py              # moteur Smart Events a regles
├── db/
│   └── history.db             # SQLite — historique runs, durees stages
├── static/
│   ├── index.html             # UI mono-page
│   ├── style.css              # design system complet (tokens CSS, animations)
│   └── cockpit.js             # WebSocket client, SVG pipeline, DOM updates
├── pipeline_defs.yaml         # definitions des pipelines (generique)
└── launch.bat                 # Chrome --app pour dev / ou tauri-cockpit/ pour prod
```

### Phase production : ajout Tauri
```
tauri-cockpit/
├── src-tauri/
│   └── main.rs                # Minimal — config fenetre + single-instance
├── src/                       # COPIE de cockpit/static/ (meme code)
│   ├── index.html
│   ├── style.css
│   └── cockpit.js
└── tauri.conf.json            # 480x800, frameless, always-on-top
```

### Dependances Python (backend)
- fastapi + uvicorn (HTTP + WebSocket)
- redis (lecture state keys)
- docker (SDK Python, Docker socket — CPU stats)
- httpx (Qdrant HTTP, health checks)
- neo4j (driver bolt)
- boto3 (AWS EC2 describe)
- pyyaml (config)
- sqlite3 (stdlib)

### Dependances Tauri (optionnel, phase prod)
- Rust toolchain + Tauri CLI
- WebView2 (inclus Windows 11)

---

## Roadmap implementation

### V1 — Cockpit Minimum Viable
1. Instrumenter ClaimFirst (P0, ~20 lignes)
2. Structure cockpit : models, config, pipeline_defs.yaml
3. Collecteurs : Docker (CPU stats), EC2 (AWS direct), Pipeline (Redis), Knowledge
4. Agregateur + WebSocket (boucle 5s, push state)
5. UI premium : design system complet (palette, typo, layout, SVG pipeline, barres CPU)
6. Instrumenter Burst + Post-Import (~11 lignes)
7. LLM session avec compteur reset tactile

### V2 — Intelligence + Tauri
- ETA engine + historique SQLite + niveaux de confiance
- Smart Events (regles de base)
- Empaquetage Tauri v2 (fenetre native, frameless, always-on-top, ~50 MB RAM)
- Son/notification sur evenement critique

### V3 — Polish
- Animations avancees (transitions fluides entre etats)
- Support multi-pipelines concurrents
- Demarrage automatique au boot Windows
- Enrichissement regles smart events

---

## Decisions cles

| Decision | Justification |
|----------|--------------|
| Service independant (pas dans l'app) | Doit observer meme si l'app crash |
| AWS EC2 API, jamais Redis pour l'etat EC2 | Desynchronisation connue (recall Spot) |
| Compteur LLM session avec reset tactile | Voir cout d'un traitement specifique |
| Pipeline en noeuds SVG (pas liste texte) | Lisibilite immediate, progression visuelle |
| Conteneurs groupes avec activite CPU | Detecter visuellement un worker qui ne travaille pas |
| YAML pour definitions pipelines | Generique, pas code en dur, extensible |
| Polling 5-15s collecteurs | Simple, suffisant pour supervision humaine |
| SQLite pour historique ETA | Zero config, local, independant |
| Vanilla JS (pas de framework) | Legeret, pas de build chain, maintient simple |
| Dev web → prod Tauri | Code frontend identique, migration = copier-coller |
| Tauri v2 (pas Electron) | Meme rendu Chromium, 3x moins de RAM, fenetre native |
| Fira Code + Fira Sans | Meme x-height, alignement parfait donnees/labels |
| Palette warm-dark #080C14 | Anti-fatigue visuelle pour ecran always-on |
| Une seule pulsation a la fois | Anti-fatigue, evite bruit visuel |
| Gradient SVG progressif | Retour visuel premium sur avancement etape |
| Bouton RESET 96x56px + fill radial | Tactile fiable, anti-activation accidentelle |
