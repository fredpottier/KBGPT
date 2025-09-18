# 🐛 Guide de Debug Sélectif

## Configuration des Variables d'Environnement

### Mode Normal (Production)
```bash
# Dans .env
DEBUG_APP=false
DEBUG_WORKER=false
```
**Résultat** : Les deux services démarrent normalement, aucun debug.

### Debug FastAPI App seulement
```bash
# Dans .env
DEBUG_APP=true
DEBUG_WORKER=false
```
**Résultat** :
- ✅ Worker démarre normalement
- 🐛 App attend connexion debug sur port 5678

### Debug Worker seulement
```bash
# Dans .env
DEBUG_APP=false
DEBUG_WORKER=true
```
**Résultat** :
- ✅ App démarre normalement
- 🐛 Worker attend connexion debug sur port 5679

### Debug des deux (Non recommandé)
```bash
# Dans .env
DEBUG_APP=true
DEBUG_WORKER=true
```
**Résultat** : Les deux services attendent une connexion debug.

## Scripts PowerShell pour basculer rapidement

### Créer `scripts/debug-app.ps1`
```powershell
# Active debug pour FastAPI seulement
(Get-Content .env) -replace 'DEBUG_APP=.*', 'DEBUG_APP=true' -replace 'DEBUG_WORKER=.*', 'DEBUG_WORKER=false' | Set-Content .env
Write-Host "🐛 Debug activé pour FastAPI App (port 5678)" -ForegroundColor Green
docker-compose up app
```

### Créer `scripts/debug-worker.ps1`
```powershell
# Active debug pour Worker seulement
(Get-Content .env) -replace 'DEBUG_APP=.*', 'DEBUG_APP=false' -replace 'DEBUG_WORKER=.*', 'DEBUG_WORKER=true' | Set-Content .env
Write-Host "🐛 Debug activé pour Worker (port 5679)" -ForegroundColor Green
docker-compose up ingestion-worker
```

### Créer `scripts/debug-off.ps1`
```powershell
# Désactive tout debug
(Get-Content .env) -replace 'DEBUG_APP=.*', 'DEBUG_APP=false' -replace 'DEBUG_WORKER=.*', 'DEBUG_WORKER=false' | Set-Content .env
Write-Host "✅ Debug désactivé" -ForegroundColor Yellow
docker-compose up app ingestion-worker
```

## Configuration VS Code launch.json

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "🚀 Attach to FastAPI App",
            "type": "python",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5678
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}/src",
                    "remoteRoot": "/app/src"
                },
                {
                    "localRoot": "${workspaceFolder}/app",
                    "remoteRoot": "/app"
                }
            ],
            "justMyCode": false
        },
        {
            "name": "🔧 Attach to Worker",
            "type": "python",
            "request": "attach",
            "connect": {
                "host": "localhost",
                "port": 5679
            },
            "pathMappings": [
                {
                    "localRoot": "${workspaceFolder}/src",
                    "remoteRoot": "/app/src"
                },
                {
                    "localRoot": "${workspaceFolder}/app",
                    "remoteRoot": "/app"
                }
            ],
            "justMyCode": false
        }
    ]
}
```

## Workflow de Debug Recommandé

### 1. Debug d'un endpoint API
1. Modifier `.env` : `DEBUG_APP=true`, `DEBUG_WORKER=false`
2. `docker-compose up app`
3. VS Code → "🚀 Attach to FastAPI App"
4. Mettre breakpoint dans `src/knowbase/api/`
5. Tester l'endpoint

### 2. Debug d'un pipeline d'ingestion
1. Modifier `.env` : `DEBUG_APP=false`, `DEBUG_WORKER=true`
2. `docker-compose up ingestion-worker`
3. VS Code → "🔧 Attach to Worker"
4. Mettre breakpoint dans `src/knowbase/ingestion/`
5. Déclencher un job via API ou interface

### 3. Debug d'un flow complet
1. Débugger l'API d'abord (étapes 1)
2. Stopper debug, modifier `.env` pour worker
3. Redémarrer avec worker debug (étapes 2)
4. Suivre le traitement complet