@echo off
REM Script de nettoyage complet de toutes les bases de donnees
REM Usage: scripts\clean_all_databases.cmd

setlocal enabledelayedexpansion

echo.
echo ================================================================
echo   Nettoyage complet des bases de donnees SAP KB
echo ================================================================
echo.
echo Ce script va supprimer TOUTES les donnees de :
echo   - Qdrant (collections knowbase et rfp_qa)
echo   - Redis (DB 0 et DB 1)
echo   - Neo4j (tous les nodes et relations)
echo   - Postgres/Graphiti (cache episodes)
echo   - Historique imports (data\status\)
echo.

if "%1" neq "--confirm" (
    set /p confirmation="Etes-vous sur de vouloir continuer ? (tapez 'oui' pour confirmer) : "
    if /i not "!confirmation!"=="oui" (
        echo Annulation du nettoyage.
        exit /b 1
    )
)

echo.
echo Demarrage du nettoyage...
echo.

REM ================================================================
REM 1. QDRANT - Supprimer toutes les collections
REM ================================================================
echo [1/5] Nettoyage Qdrant...

for /f "tokens=*" %%i in ('curl -s http://localhost:6333/collections ^| findstr "name"') do (
    set line=%%i
    set line=!line:"name": "=!
    set line=!line:",=!
    set line=!line:"=!
    set collection=!line: =!
    if not "!collection!"=="" (
        echo   Suppression collection: !collection!
        curl -s -X DELETE "http://localhost:6333/collections/!collection!" >nul 2>&1
        echo   Collection !collection! supprimee
    )
)

REM ================================================================
REM 2. REDIS - Purger toutes les bases
REM ================================================================
echo [2/5] Nettoyage Redis...

docker exec knowbase-redis redis-cli -n 0 DBSIZE >nul 2>&1
if %errorlevel% equ 0 (
    echo   Purge Redis DB 0
    docker exec knowbase-redis redis-cli -n 0 FLUSHDB >nul 2>&1
    echo   Redis DB 0 purgee
)

docker exec knowbase-redis redis-cli -n 1 DBSIZE >nul 2>&1
if %errorlevel% equ 0 (
    echo   Purge Redis DB 1
    docker exec knowbase-redis redis-cli -n 1 FLUSHDB >nul 2>&1
    echo   Redis DB 1 purgee
)

REM ================================================================
REM 3. NEO4J - Supprimer tous les nodes et relations
REM ================================================================
echo [3/5] Nettoyage Neo4j...

docker ps --format "{{.Names}}" | findstr "graphiti-neo4j" >nul 2>&1
if %errorlevel% equ 0 (
    echo   Suppression des nodes Neo4j
    docker exec graphiti-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass "MATCH (n) DETACH DELETE n" >nul 2>&1
    if %errorlevel% equ 0 (
        echo   Neo4j purge
    ) else (
        echo   Attention: erreur Neo4j (credentials incorrects?)
    )
) else (
    echo   Conteneur Neo4j non trouve (OK si non utilise)
)

REM ================================================================
REM 4. POSTGRES/GRAPHITI - Skip (non utilise, Graphiti deprecated)
REM ================================================================
echo [4/5] Postgres/Graphiti (skip - non utilise)...
echo   Graphiti n'est plus utilise, conteneurs ignores

REM ================================================================
REM 5. HISTORIQUE IMPORTS - Supprimer fichiers status
REM ================================================================
echo [5/5] Nettoyage historique imports...

if exist "data\status\*.json" (
    del /q "data\status\*.json" >nul 2>&1
    echo   Historique imports nettoye
) else (
    echo   Aucun fichier status trouve
)

REM ================================================================
REM RESUME FINAL
REM ================================================================
echo.
echo ================================================================
echo   NETTOYAGE TERMINE AVEC SUCCES
echo ================================================================
echo.
echo Resume des operations :
echo   - Qdrant : toutes les collections supprimees
echo   - Redis : DB 0 et DB 1 purgees
echo   - Neo4j : tous les nodes supprimes
echo   - Postgres/Graphiti : ignore (non utilise)
echo   - Historique : fichiers status supprimes
echo.
echo Vous pouvez maintenant importer un nouveau PPTX avec une base propre.
echo.

endlocal
