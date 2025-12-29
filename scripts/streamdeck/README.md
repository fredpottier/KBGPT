# Stream Deck XL - Profile KnowWhere/OSMOSE

Configuration complete pour developper avec Stream Deck XL (32 boutons).

## Layout Visuel (8x4)

```
┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│  START  │  START  │  START  │  START  │  STOP   │  STOP   │  STOP   │  STOP   │
│   ALL   │   APP   │  INFRA  │ MONITOR │   ALL   │   APP   │  INFRA  │ MONITOR │
│   🟢    │   🟢    │   🟢    │   🟢    │   🔴    │   🔴    │   🔴    │   🔴    │
├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ RESTART │ RESTART │ RESTART │         │  BUILD  │  BUILD  │  BUILD  │ REBUILD │
│   ALL   │   APP   │  INFRA  │ STATUS  │   ALL   │   APP   │  INFRA  │   ALL   │
│   🔄    │   🔄    │   🔄    │   📊    │   🔨    │   🔨    │   🔨    │   🔨    │
├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│  OPEN   │FRONTEND │   API   │  QDRANT │  NEO4J  │ GRAFANA │  LOKI   │  REDIS  │
│  ALL    │  :3000  │  :8000  │  :6333  │  :7474  │  :3001  │  :3101  │COMMANDER│
│   🌐    │   🖥️    │   📡    │   💾    │   🕸️    │   📈    │   📋    │   🔑    │
├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ CLAUDE  │ VS CODE │  LOGS   │  LOGS   │  LOGS   │  CLEAN  │  PURGE  │  INFO   │
│  CODE   │ PROJECT │   APP   │ WORKER  │  NEO4J  │  ALL    │   KG    │  URLs   │
│   🤖    │   💻    │   📄    │   📄    │   📄    │   ⚠️    │   🗑️    │   ℹ️    │
└─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
```

## Configuration Stream Deck

### Etape 1: Ouvrir Stream Deck App
1. Lancer l'application Stream Deck
2. Creer un nouveau profil: "KnowWhere Dev"

### Etape 2: Configurer chaque bouton

Pour chaque bouton, utiliser l'action **"System > Open"** avec:

| Position | Titre | Script |
|----------|-------|--------|
| R1-C1 | START ALL | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\start-all.ps1"` |
| R1-C2 | START APP | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\start-app.ps1"` |
| R1-C3 | START INFRA | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\start-infra.ps1"` |
| R1-C4 | START MON | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\start-monitoring.ps1"` |
| R1-C5 | STOP ALL | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\stop-all.ps1"` |
| R1-C6 | STOP APP | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\stop-app.ps1"` |
| R1-C7 | STOP INFRA | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\stop-infra.ps1"` |
| R1-C8 | STOP MON | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\stop-monitoring.ps1"` |
| R2-C1 | RESTART ALL | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\restart-all.ps1"` |
| R2-C2 | RESTART APP | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\restart-app.ps1"` |
| R2-C3 | RESTART INFRA | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\restart-infra.ps1"` |
| R2-C4 | STATUS | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\status.ps1"` |
| R2-C5 | BUILD ALL | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\build-all.ps1"` |
| R2-C6 | BUILD APP | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\build-app.ps1"` |
| R2-C7 | BUILD INFRA | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\build-infra.ps1"` |
| R2-C8 | REBUILD | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\rebuild-all.ps1"` |
| R3-C1 | OPEN ALL | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-all-dashboards.ps1"` |
| R3-C2 | FRONTEND | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-frontend.ps1"` |
| R3-C3 | API | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-api.ps1"` |
| R3-C4 | QDRANT | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-qdrant.ps1"` |
| R3-C5 | NEO4J | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-neo4j.ps1"` |
| R3-C6 | GRAFANA | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-grafana.ps1"` |
| R3-C7 | LOKI | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-loki.ps1"` |
| R3-C8 | REDIS | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-redis-commander.ps1"` |
| R4-C1 | CLAUDE | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\launch-claude.ps1"` |
| R4-C2 | VS CODE | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\open-vscode.ps1"` |
| R4-C3 | LOGS APP | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\logs-app.ps1"` |
| R4-C4 | LOGS WORKER | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\logs-worker.ps1"` |
| R4-C5 | LOGS NEO4J | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\logs-neo4j.ps1"` |
| R4-C6 | CLEAN | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\clean-all.ps1"` |
| R4-C7 | PURGE KG | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\purge-kg.ps1"` |
| R4-C8 | INFO | `powershell -ExecutionPolicy Bypass -File "C:\Projects\SAP_KB\scripts\streamdeck\show-info.ps1"` |

### Etape 3: Codes couleur recommandes

| Couleur | Usage |
|---------|-------|
| Vert (#00FF00) | START (demarrer) |
| Rouge (#FF0000) | STOP (arreter) |
| Orange (#FFA500) | RESTART, BUILD |
| Bleu (#0088FF) | Dashboards/URLs |
| Violet (#9900FF) | Outils dev (Claude, VS Code) |
| Jaune (#FFFF00) | Logs |
| Rouge fonce (#880000) | CLEAN/PURGE (danger) |
| Gris (#888888) | INFO/STATUS |

## Icones recommandees

Tu peux utiliser des icones PNG 72x72 ou 144x144 pour chaque bouton.
Sites recommandes pour icones:
- https://icons8.com
- https://www.flaticon.com
- https://simpleicons.org (logos tech)

Icones suggerees:
- Docker logo pour START/STOP/BUILD
- Chrome logo pour OPEN ALL
- Neo4j/Qdrant/Grafana logos officiels
- VS Code logo officiel
- Robot/AI icon pour Claude

## Scripts inclus

| Script | Description |
|--------|-------------|
| `start-*.ps1` | Demarre les services (all/app/infra/monitoring) |
| `stop-*.ps1` | Arrete les services |
| `restart-*.ps1` | Redemarre les services |
| `build-*.ps1` | Build les images Docker |
| `rebuild-all.ps1` | Rebuild complet sans cache + demarrage |
| `status.ps1` | Affiche le statut de tous les services |
| `open-*.ps1` | Ouvre les dashboards dans le navigateur |
| `launch-claude.ps1` | Lance Claude Code dans un nouveau terminal |
| `open-vscode.ps1` | Ouvre VS Code avec le projet |
| `logs-*.ps1` | Affiche les logs des services |
| `clean-all.ps1` | Nettoyage complet (avec confirmation) |
| `purge-kg.ps1` | Purge le Knowledge Graph (preserve cache) |
| `show-info.ps1` | Affiche toutes les URLs et credentials |

## Personnalisation

Tu peux modifier les scripts selon tes besoins:
- Ajouter d'autres services
- Modifier les URLs
- Ajouter des raccourcis supplementaires

## Multi-actions Stream Deck

Tu peux creer des multi-actions pour enchainer:

### Exemple: "Morning Startup"
1. start-all.ps1
2. Delay 30s
3. open-all-dashboards.ps1
4. launch-claude.ps1

### Exemple: "Quick Reset Dev"
1. restart-app.ps1
2. Delay 10s
3. open-frontend.ps1

## Troubleshooting

### Le script ne s'execute pas
- Verifier que PowerShell est autorise a executer des scripts
- Tester manuellement: `powershell -ExecutionPolicy Bypass -File "chemin\script.ps1"`

### La fenetre se ferme trop vite
- Les scripts ont `Read-Host` pour rester ouverts
- Si tu veux qu'ils se ferment automatiquement, retire les `Read-Host`

### Chrome n'ouvre pas tous les onglets
- Verifier que Chrome est dans le PATH
- Ou modifier le script avec le chemin complet:
  `Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe"`
