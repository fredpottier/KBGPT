# Chantier Cockpit Operationnel OSMOSIS

**Statut** : Design approuve, implementation non demarree
**Derniere mise a jour** : 29 mars 2026
**Source archivee** : `doc/archive/pre-rationalization-2026-03/ongoing/ADR_COCKPIT_OPERATIONNEL.md`

---

## 1. Vision

Centre de pilotage compact pour supervision temps reel d'OSMOSIS, concu pour un ecran secondaire **Corsair Xeneon Edge** (2560x720 pixels, 14.5 pouces, 5-point multi-touch, 60Hz). L'objectif n'est pas un dashboard analytique type Kibana mais une **supervision operationnelle** lisible en < 1 seconde, avec push temps reel via WebSocket.

### Hierarchie visuelle (ordre de lecture en < 1s)

1. **0-300ms** : Pipeline (bande centrale, la plus large, noeud pulsant visible immediatement)
2. **300-700ms** : EC2 pill (extreme gauche) + LLM cout (grand chiffre a droite)
3. **700ms+** : Conteneurs + Knowledge + Events (seulement si non-vide, flash couleur)

---

## 2. Architecture 4 couches

```
COUCHE 4 — Renderer (HTML/SVG/CSS/JS vanilla, WebSocket client)
    |  WebSocket push (JSON)
COUCHE 3 — Cockpit API (FastAPI, port 9090)
    |  GET /cockpit/state, WS /cockpit/ws
    |  Moteur ETA + moteur Smart Events
    |  Polling interne 5-15s
COUCHE 2 — Collecteurs (1 par source)
    |  DockerCollector, PipelineCollector, BurstCollector,
    |  KnowledgeCollector, LLMBudgetCollector
COUCHE 1 — Sources de verite
    Docker socket | Redis | Qdrant | Neo4j | AWS EC2 API | SQLite local
```

### Principe cle

Le cockpit est un **processus separe**, pas integre dans l'app OSMOSIS. Si l'app crash, le cockpit le detecte et l'affiche. Le service FastAPI tourne sur le port 9090 independamment.

### Modele de donnees canonique

```python
@dataclass
class CockpitState:
    timestamp: datetime
    burst: BurstStatus           # EC2 Spot + vLLM/TEI health
    pipeline: PipelineStatus     # Etapes en cours
    container_groups: list[ContainerGroupStatus]  # 3 groupes
    knowledge: KnowledgeStatus   # Qdrant + Neo4j stats
    llm_session: LLMSessionStatus  # Cout session + reset
    llm_balances: LLMBalanceStatus  # Soldes API
    events: list[SmartEvent]     # Alertes actives
```

---

## 3. Les 6 widgets

### Widget 1 — EC2 Burst (200px)

- **Source de verite = AWS EC2 API** (boto3 `describe_instances`, tag `Project=KnowWhere`)
- **JAMAIS Redis** pour l'etat EC2 (desynchronisation connue lors des recalls Spot)
- Redis utilise uniquement pour le contexte job (batch_id, docs done/total)
- Health check vLLM + TEI via HTTP direct sur l'IP decouverte
- Cache 15s pour eviter spam API AWS
- Etats deduits : off | starting | booting | ready | stopping

### Widget 2 — Pipeline actif (920px, zone principale)

- **Rendu en noeuds SVG** en ligne horizontale (le format ultrawide le permet)
- Cercles 28px : vert (done, checkmark), ambre pulsant (running, 1.8s ease-in-out), gris pointilles (pending), rouge croix (failed)
- **Ligne progressive** : linearGradient SVG dont l'offset avance avec le % de l'etape
- Labels 9-10px sous chaque noeud, tronques ~10 chars, tooltip au tap
- Definitions de pipelines en YAML (generique, pas code en dur)
- 3 pipelines V1 : claim-first (7 etapes), post-import (dynamique), burst-extract (4 etapes)

```
●━━━━●━━━━●━━━━●━━━━◉════○╌╌╌╌○╌╌╌╌○╌╌╌╌○
Load  Extr  Dedup Canon  Fac   Contr  Pers  Final
0:01  0:40  0:03  0:18  >0:12
                        ~0:09
```

### Widget 3 — Conteneurs (320px)

3 groupes empiles :
- **INFRA** (4) : qdrant, redis, neo4j, postgres
- **APP** (4) : app, ingestion-worker, folder-watcher, frontend
- **MONITORING** (3) : loki, promtail, grafana

Mini bar-graph CPU par conteneur (hauteur 4px) :
- < 40% : bleu, 40-70% : ambre, > 70% : rouge
- Le worker qui "travaille" est immediatement visible visuellement
- Source : Docker API `container.stats(stream=False)`

### Widget 4 — Knowledge state (272px)

- Qdrant : chunks count, connectivite
- Neo4j : nodes, claims, entities, facets, relations, contradictions
- Endpoints existants : `/api/admin/health`, `/api/claimfirst/status`

### Widget 5 — LLM Session + Soldes (272px)

- **Compteur de session avec RESET tactile** (bouton 96x56px pour fiabilite tactile)
  - Cout depuis dernier reset, breakdown par modele, rate $/min
  - Reset via message WebSocket `{"type": "reset_llm_session"}`
  - Feedback : fill radial 200ms avant action (evite activation accidentelle)
- Soldes API :
  - OpenAI : `GET /v1/organization/costs`
  - Anthropic : pas d'API billing publique → saisie manuelle + decompte
- Seuils visuels : OK (vert) / LOW (jaune, < 10$) / CRITICAL (rouge, < 3$)

### Widget 6 — Smart Events (520px)

Moteur a regles evaluees toutes les 10s :
- Pipeline bloque (0 progression depuis 5min)
- Etape anormalement lente (>2.5x mediane historique)
- Container down ou unhealthy
- Burst active mais idle >10min
- Credits LLM sous seuil critique
- Neo4j +claims mais Qdrant inchange (bridge manquant)
- Rendement faible (<5 claims/doc)
- Evenements avec TTL (disparaissent apres resolution ou expiration)

---

## 4. Design system

### Palette dark theme anti-fatigue

```css
--bg-base:       #080C14;   /* canvas */
--bg-surface:    #0D1320;   /* widget cards */
--bg-elevated:   #131A2B;   /* header bars */
--success:       #10B981;   /* done, healthy */
--warning:       #F59E0B;   /* in-progress, degraded */
--error:         #EF4444;   /* failed, critical */
--active:        #3B82F6;   /* selected, processing */
--text-primary:  #E2E8F0;   /* contenu principal */
--text-secondary:#94A3B8;   /* labels, metadata */
--text-accent:   #7DD3FC;   /* highlights, liens */
```

Tous les couples texte/fond valides WCAG AA minimum (ratio >= 5.4:1).

### Typographie

- **Donnees** : Fira Code 400/500/600 (monospace, tabular nums)
- **Labels** : Fira Sans 300/400/500/600 (sans-serif)
- Meme famille = x-height identique, alignement parfait nombres/labels
- Tailles : XL (28px) KPI principal, LG (20px) compteurs, MD (14px) secondaires, SM (11px) timestamps, minimum lisible a 60cm = 10px

### Regles d'animation (anti-fatigue)

- **Un seul element pulse a la fois** (le noeud pipeline actif)
- Container dots pulsent seulement si unhealthy
- Event dots pulsent seulement si severity=ERROR
- Cout LLM anime seulement a l'arrivee d'un nouveau cout
- `@media (prefers-reduced-motion: reduce)` → animations statiques

### Layout 2560x720 — bandeau horizontal "cockpit strip"

```
2560px
┌──────────┬─────────────────────────────────┬────────┬────────┬────────┬────────┐
│ W1: EC2  │ W2: PIPELINE (noeuds SVG)       │ W3:    │ W4:    │ W5:    │ W6:    │
│ BURST    │ zone principale 920px           │ CONT.  │ KNOWL. │ LLM    │ EVENTS │
│ 200px    │                                  │ 320px  │ 272px  │ 272px  │ 520px  │
├──────────┴─────────────────────────────────┴────────┴────────┴────────┴────────┤
│ TOPBAR 28px — "OSMOSIS COCKPIT" + horloge + dot WebSocket + pipeline ETA      │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Stack technique

### Structure du projet

```
cockpit/
├── main.py                    # FastAPI, uvicorn, port 9090
├── config.py                  # Seuils, intervalles, pipeline defs
├── models.py                  # Dataclasses CockpitState & co
├── collectors/
│   ├── docker_collector.py    # Docker API → ContainerGroupStatus (CPU stats)
│   ├── pipeline_collector.py  # Redis state keys → PipelineStatus
│   ├── burst_collector.py     # AWS EC2 API (boto3) → BurstStatus
│   ├── knowledge_collector.py # Qdrant HTTP + Neo4j bolt → KnowledgeStatus
│   └── llm_budget_collector.py # Token stats + billing → LLM*Status
├── engine/
│   ├── aggregator.py          # Orchestre collecteurs, assemble CockpitState
│   ├── eta.py                 # Calcul ETA + historique SQLite
│   └── events.py              # Moteur Smart Events a regles
├── db/
│   └── history.db             # SQLite local pour historique runs
├── static/
│   ├── index.html             # UI mono-page
│   ├── style.css              # Design system complet
│   └── cockpit.js             # WebSocket client, SVG pipeline, DOM updates
├── pipeline_defs.yaml         # Definitions pipelines (generique)
└── launch.bat                 # Chrome --app pour dev
```

### Dependances Python (backend)

fastapi + uvicorn, redis, docker (SDK Python), httpx (Qdrant, health checks), neo4j (bolt), boto3 (AWS), pyyaml, sqlite3 (stdlib)

### Dependances frontend

Zero framework — vanilla JS + SVG + CSS. Pas de build chain, pas de npm.

### Strategie de rendu en 2 temps

1. **Dev & iteration** : UI web servie par FastAPI (port 9090), ouverte dans Chrome `--app`
   ```bash
   chrome --app=http://localhost:9090/cockpit --window-size=2560,720 --window-position=0,1080
   ```
2. **Production** : empaquetage Tauri v2 — meme code frontend, fenetre native (frameless, always-on-top, ~50 MB RAM)

### Pourquoi Tauri v2

| Alternative | Ecarte car |
|-------------|------------|
| Electron | Meme rendu (WebView2) mais 3x plus de RAM (~150-300 MB) |
| Qt/QML | Courbe d'apprentissage QML, theming CSS inexistant, packaging lourd |
| Dear ImGui | Look utilitaire, pas premium, tactile quasi inexistant |
| iCUE SDK | Documentation pauvre, lock-in Corsair |
| Flutter | Integration Python penible (Dart = langage supplementaire) |

---

## 6. Invariants

| Invariant | Justification |
|-----------|--------------|
| Service independant (pas dans l'app) | Doit observer meme si l'app crash |
| AWS EC2 API, jamais Redis pour l'etat EC2 | Desynchronisation connue (recall Spot) |
| Compteur LLM session avec reset tactile | Voir cout d'un traitement specifique |
| Pipeline en noeuds SVG (pas liste texte) | Lisibilite immediate, progression visuelle |
| Conteneurs groupes avec activite CPU | Detecter visuellement un worker qui ne travaille pas |
| YAML pour definitions pipelines | Generique, pas code en dur, extensible |
| Polling 5-15s collecteurs | Simple, suffisant pour supervision humaine |
| SQLite pour historique ETA | Zero config, local, independant |
| Vanilla JS (pas de framework) | Legeret, pas de build chain, maintenance simple |
| Une seule pulsation a la fois | Anti-fatigue, evite bruit visuel |

---

## 7. Travaux non termines

### V1 — Cockpit Minimum Viable

1. Instrumenter ClaimFirst (`_emit_phase_state()` ~20 lignes, Redis HSET `osmose:claimfirst:state`)
2. Structure cockpit : models, config, pipeline_defs.yaml
3. Collecteurs : Docker (CPU stats), EC2 (AWS direct), Pipeline (Redis), Knowledge
4. Agregateur + WebSocket (boucle 5s, push state)
5. UI premium : design system complet (palette, typo, layout, SVG pipeline, barres CPU)
6. Instrumenter Burst + Post-Import (~11 lignes)
7. LLM session avec compteur reset tactile

### V2 — Intelligence + Tauri

- ETA engine + historique SQLite + niveaux de confiance
  - Confiance high : stage iterative + done > 10 + historique >= 3 runs
  - Confiance medium : done > 3 OU historique >= 1 run
  - Confiance low : premiere execution, peu de donnees
- Smart Events (regles de base)
- Empaquetage Tauri v2 (fenetre native, frameless, always-on-top)
- Son/notification sur evenement critique

### V3 — Polish

- Animations avancees (transitions fluides entre etats)
- Support multi-pipelines concurrents
- Demarrage automatique au boot Windows
- Enrichissement regles smart events

### Instrumentation necessaire des pipelines existants

| Pipeline | Fichier | Effort |
|----------|---------|--------|
| ClaimFirst (P0) | `orchestrator.py` | ~20 lignes (HSET phase transitions) |
| Post-Import (P1) | `post_import.py` | ~1 ligne (`step_started_at` dans Redis) |
| Burst (P1) | `orchestrator.py` | ~10 lignes (SETEX Redis TTL 3600) |

### Logique ETA

```
# Etape en cours (iterative)
rate = elapsed_stage / items_done
eta_stage = (items_total - items_done) * rate

# Pipeline total
eta_total = eta_stage_courante + SUM(duree_mediane_historique[stages_restantes])
```
