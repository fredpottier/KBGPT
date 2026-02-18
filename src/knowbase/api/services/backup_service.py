"""
Service de backup & restore OSMOSE.

Implémentation Python native — tourne dans le container Docker.
Accès direct aux services via réseau interne (Neo4j bolt, Qdrant HTTP, Redis, PostgreSQL).
"""

import json
import os
import shutil
import tarfile
import threading
import time
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import requests

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

from knowbase.api.schemas.backup import (
    BackupManifest,
    BackupSummary,
    BackupListResponse,
    CurrentSystemStats,
    BackupJobStatus,
    DomainContextInfo,
    ImportedDocumentInfo,
)

settings = get_settings()
logger = setup_logging(settings.logs_dir, "backup_service.log")

# Répertoire des backups (sous /data = volume Docker monté)
BACKUPS_DIR = Path("/data/backups/snapshots")
JOBS_DIR = Path("/data/backups/jobs")

# Répertoire du cache d'extraction (volume Docker /data)
CACHE_DIR = Path("/data/extraction_cache")

# URL Qdrant interne au réseau Docker
QDRANT_URL = settings.qdrant_url  # http://qdrant:6333
QDRANT_COLLECTIONS = [settings.qdrant_collection, settings.qdrant_qa_collection]


def _format_size(size_bytes: int) -> str:
    """Formate une taille en bytes en format humain."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _dir_size(path: Path) -> int:
    """Calcule la taille totale d'un répertoire."""
    total = 0
    if path.exists():
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    return total


# ---------------------------------------------------------------------------
#  Helpers backup par composant
# ---------------------------------------------------------------------------

def _backup_neo4j(backup_dir: Path, log_lines: list) -> dict:
    """Export Neo4j via Cypher → JSON (tous les nodes et relations)."""
    try:
        from neo4j import GraphDatabase

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        nodes = []
        relationships = []
        node_counts: Dict[str, int] = {}
        rel_counts: Dict[str, int] = {}

        with driver.session() as session:
            # Export tous les nodes
            log_lines.append("[Neo4j] Export des nodes...")
            result = session.run(
                "MATCH (n) RETURN id(n) as id, labels(n) as labels, properties(n) as props"
            )
            for record in result:
                node = {
                    "id": record["id"],
                    "labels": record["labels"],
                    "properties": _sanitize_neo4j_props(record["props"]),
                }
                nodes.append(node)
                for lbl in record["labels"]:
                    node_counts[lbl] = node_counts.get(lbl, 0) + 1

            # Export toutes les relations
            log_lines.append("[Neo4j] Export des relations...")
            result = session.run(
                "MATCH (a)-[r]->(b) "
                "RETURN id(r) as id, type(r) as type, "
                "id(a) as start_id, id(b) as end_id, properties(r) as props"
            )
            for record in result:
                rel = {
                    "id": record["id"],
                    "type": record["type"],
                    "start_id": record["start_id"],
                    "end_id": record["end_id"],
                    "properties": _sanitize_neo4j_props(record["props"]),
                }
                relationships.append(rel)
                rtype = record["type"]
                rel_counts[rtype] = rel_counts.get(rtype, 0) + 1

        driver.close()

        # Écrire le fichier JSON
        export_data = {"nodes": nodes, "relationships": relationships}
        export_path = backup_dir / "neo4j_export.json"
        export_path.write_text(
            json.dumps(export_data, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        file_size = export_path.stat().st_size

        msg = f"[Neo4j] OK — {len(nodes)} nodes, {len(relationships)} relations ({_format_size(file_size)})"
        log_lines.append(msg)
        logger.info(msg)

        return {
            "status": "success",
            "size_bytes": file_size,
            "total_nodes": len(nodes),
            "total_relationships": len(relationships),
            "node_counts": node_counts,
            "relationship_counts": rel_counts,
        }

    except Exception as e:
        msg = f"[Neo4j] ERREUR — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "size_bytes": 0, "error": str(e)}


def _sanitize_neo4j_props(props: dict) -> dict:
    """Convertit les types Neo4j non-sérialisables (datetime, etc.)."""
    clean = {}
    for k, v in (props or {}).items():
        if hasattr(v, "isoformat"):
            clean[k] = v.isoformat()
        elif isinstance(v, (list, tuple)):
            clean[k] = [
                x.isoformat() if hasattr(x, "isoformat") else x for x in v
            ]
        else:
            clean[k] = v
    return clean


def _backup_qdrant(backup_dir: Path, log_lines: list) -> dict:
    """Backup Qdrant via API snapshots HTTP."""
    snap_dir = backup_dir / "qdrant_snapshots"
    snap_dir.mkdir(exist_ok=True)

    collections_info = {}
    total_size = 0
    all_ok = True

    for coll in QDRANT_COLLECTIONS:
        try:
            # Vérifier que la collection existe
            resp = requests.get(f"{QDRANT_URL}/collections/{coll}", timeout=10)
            if resp.status_code == 404:
                log_lines.append(f"[Qdrant] Collection {coll} inexistante, skip")
                continue

            coll_info = resp.json().get("result", {})
            point_count = coll_info.get("points_count", 0)

            # Créer snapshot
            log_lines.append(f"[Qdrant] Snapshot {coll} ({point_count} points)...")
            resp = requests.post(
                f"{QDRANT_URL}/collections/{coll}/snapshots",
                timeout=120,
            )
            resp.raise_for_status()
            snap_name = resp.json().get("result", {}).get("name")

            if not snap_name:
                raise ValueError("Snapshot name vide")

            # Télécharger snapshot
            snap_path = snap_dir / f"{coll}.snapshot"
            resp = requests.get(
                f"{QDRANT_URL}/collections/{coll}/snapshots/{snap_name}",
                stream=True,
                timeout=300,
            )
            resp.raise_for_status()
            with open(snap_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            snap_size = snap_path.stat().st_size
            total_size += snap_size

            collections_info[coll] = {
                "point_count": point_count,
                "vector_size": 0,
            }

            # Nettoyer snapshot côté serveur
            try:
                requests.delete(
                    f"{QDRANT_URL}/collections/{coll}/snapshots/{snap_name}",
                    timeout=10,
                )
            except Exception:
                pass

            msg = f"[Qdrant] {coll}: {point_count} points ({_format_size(snap_size)})"
            log_lines.append(msg)
            logger.info(msg)

        except Exception as e:
            msg = f"[Qdrant] {coll}: ERREUR — {e}"
            log_lines.append(msg)
            logger.error(msg)
            all_ok = False

    return {
        "status": "success" if all_ok else "error",
        "size_bytes": total_size,
        "collections": collections_info,
    }


def _backup_postgresql(backup_dir: Path, log_lines: list) -> dict:
    """Backup PostgreSQL via SQLAlchemy — export toutes les tables en JSON."""
    try:
        from sqlalchemy import create_engine, text, inspect

        db_url = os.getenv("DATABASE_URL", "postgresql://knowbase:knowbase@postgres:5432/knowbase")
        engine = create_engine(db_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        export = {}
        table_counts = {}

        with engine.connect() as conn:
            for table in tables:
                log_lines.append(f"[PostgreSQL] Export {table}...")
                result = conn.execute(text(f'SELECT * FROM "{table}"'))
                columns = list(result.keys())
                rows = []
                for row in result:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        val = row[i]
                        if hasattr(val, "isoformat"):
                            val = val.isoformat()
                        elif isinstance(val, bytes):
                            val = val.hex()
                        row_dict[col] = val
                    rows.append(row_dict)

                export[table] = {"columns": columns, "rows": rows}
                table_counts[table] = len(rows)

        engine.dispose()

        export_path = backup_dir / "postgres_export.json"
        export_path.write_text(
            json.dumps(export, ensure_ascii=False, default=str, indent=1),
            encoding="utf-8",
        )
        file_size = export_path.stat().st_size

        total_rows = sum(table_counts.values())
        msg = f"[PostgreSQL] OK — {len(tables)} tables, {total_rows} rows ({_format_size(file_size)})"
        log_lines.append(msg)
        logger.info(msg)

        return {
            "status": "success",
            "size_bytes": file_size,
            "table_counts": table_counts,
        }

    except Exception as e:
        msg = f"[PostgreSQL] ERREUR — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "size_bytes": 0, "error": str(e)}


def _backup_redis(backup_dir: Path, log_lines: list) -> dict:
    """Backup Redis — export toutes les clés en JSON."""
    try:
        import redis as redis_lib

        client = redis_lib.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=0,
        )

        keys = client.keys("*")
        export = {}

        for key in keys:
            key_str = key.decode("utf-8", errors="replace")
            key_type = client.type(key).decode("utf-8")

            try:
                if key_type == "string":
                    val = client.get(key)
                    export[key_str] = {
                        "type": "string",
                        "value": val.decode("utf-8", errors="replace") if val else None,
                    }
                elif key_type == "list":
                    vals = client.lrange(key, 0, -1)
                    export[key_str] = {
                        "type": "list",
                        "value": [v.decode("utf-8", errors="replace") for v in vals],
                    }
                elif key_type == "set":
                    vals = client.smembers(key)
                    export[key_str] = {
                        "type": "set",
                        "value": [v.decode("utf-8", errors="replace") for v in vals],
                    }
                elif key_type == "hash":
                    vals = client.hgetall(key)
                    export[key_str] = {
                        "type": "hash",
                        "value": {
                            k.decode("utf-8", errors="replace"): v.decode("utf-8", errors="replace")
                            for k, v in vals.items()
                        },
                    }
                elif key_type == "zset":
                    vals = client.zrange(key, 0, -1, withscores=True)
                    export[key_str] = {
                        "type": "zset",
                        "value": [
                            {"member": v.decode("utf-8", errors="replace"), "score": s}
                            for v, s in vals
                        ],
                    }
                else:
                    export[key_str] = {"type": key_type, "value": None}
            except Exception:
                export[key_str] = {"type": key_type, "value": None, "error": "unreadable"}

        client.close()

        export_path = backup_dir / "redis_export.json"
        export_path.write_text(
            json.dumps(export, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        file_size = export_path.stat().st_size

        msg = f"[Redis] OK — {len(keys)} clés ({_format_size(file_size)})"
        log_lines.append(msg)
        logger.info(msg)

        return {"status": "success", "size_bytes": file_size}

    except Exception as e:
        msg = f"[Redis] ERREUR — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "size_bytes": 0, "error": str(e)}


def _backup_extraction_cache(backup_dir: Path, include_cache: bool, log_lines: list) -> dict:
    """Backup extraction cache via tarfile."""
    if not include_cache:
        log_lines.append("[Cache] Ignoré (--no-cache)")
        return {"status": "skipped", "file_count": 0, "size_bytes": 0}

    if not CACHE_DIR.exists():
        log_lines.append("[Cache] Répertoire inexistant")
        return {"status": "skipped", "file_count": 0, "size_bytes": 0}

    cache_files = list(CACHE_DIR.glob("*.v5cache.json")) + list(CACHE_DIR.glob("*.npz"))
    if not cache_files:
        log_lines.append("[Cache] Aucun fichier")
        return {"status": "success", "file_count": 0, "size_bytes": 0}

    try:
        tar_path = backup_dir / "extraction_cache.tar.gz"
        log_lines.append(f"[Cache] Compression de {len(cache_files)} fichiers...")

        with tarfile.open(tar_path, "w:gz") as tar:
            for f in cache_files:
                tar.add(str(f), arcname=f.name)

        file_size = tar_path.stat().st_size
        msg = f"[Cache] OK — {len(cache_files)} fichiers ({_format_size(file_size)})"
        log_lines.append(msg)
        logger.info(msg)

        return {"status": "success", "file_count": len(cache_files), "size_bytes": file_size}

    except Exception as e:
        msg = f"[Cache] ERREUR — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "file_count": 0, "size_bytes": 0, "error": str(e)}


# ---------------------------------------------------------------------------
#  Helpers restore par composant
# ---------------------------------------------------------------------------

def _restore_neo4j(backup_dir: Path, log_lines: list) -> dict:
    """Restore Neo4j depuis JSON export."""
    export_path = backup_dir / "neo4j_export.json"
    if not export_path.exists():
        return {"status": "error", "error": "neo4j_export.json introuvable"}

    try:
        from neo4j import GraphDatabase

        neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        data = json.loads(export_path.read_text(encoding="utf-8"))
        nodes = data.get("nodes", [])
        relationships = data.get("relationships", [])

        with driver.session() as session:
            # Purger toutes les données existantes
            log_lines.append("[Neo4j] Purge des données existantes...")
            session.run("MATCH (n) DETACH DELETE n")

            # Recréer les nodes par batch
            log_lines.append(f"[Neo4j] Import de {len(nodes)} nodes...")
            id_map = {}  # old_id → new_id
            batch_size = 500

            for i in range(0, len(nodes), batch_size):
                batch = nodes[i:i + batch_size]
                for node in batch:
                    labels_str = ":".join(node["labels"]) if node["labels"] else "Node"
                    result = session.run(
                        f"CREATE (n:{labels_str} $props) RETURN id(n) as new_id",
                        props=node["properties"],
                    )
                    new_id = result.single()["new_id"]
                    id_map[node["id"]] = new_id

            # Recréer les relations par batch
            log_lines.append(f"[Neo4j] Import de {len(relationships)} relations...")
            for i in range(0, len(relationships), batch_size):
                batch = relationships[i:i + batch_size]
                for rel in batch:
                    start_new = id_map.get(rel["start_id"])
                    end_new = id_map.get(rel["end_id"])
                    if start_new is not None and end_new is not None:
                        session.run(
                            f"MATCH (a), (b) WHERE id(a) = $sid AND id(b) = $eid "
                            f"CREATE (a)-[r:{rel['type']}]->(b) SET r = $props",
                            sid=start_new,
                            eid=end_new,
                            props=rel.get("properties", {}),
                        )

        driver.close()

        msg = f"[Neo4j] Restauré — {len(nodes)} nodes, {len(relationships)} relations"
        log_lines.append(msg)
        logger.info(msg)
        return {"status": "success"}

    except Exception as e:
        msg = f"[Neo4j] ERREUR restore — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "error": str(e)}


def _restore_qdrant(backup_dir: Path, log_lines: list) -> dict:
    """Restore Qdrant depuis snapshots."""
    snap_dir = backup_dir / "qdrant_snapshots"
    if not snap_dir.exists():
        return {"status": "error", "error": "qdrant_snapshots/ introuvable"}

    all_ok = True
    for coll in QDRANT_COLLECTIONS:
        snap_path = snap_dir / f"{coll}.snapshot"
        if not snap_path.exists():
            log_lines.append(f"[Qdrant] Pas de snapshot pour {coll}, skip")
            continue

        try:
            # Supprimer la collection existante
            log_lines.append(f"[Qdrant] Suppression collection {coll}...")
            requests.delete(f"{QDRANT_URL}/collections/{coll}", timeout=30)
            time.sleep(1)

            # Restaurer depuis snapshot via upload
            log_lines.append(f"[Qdrant] Restauration {coll} depuis snapshot...")
            with open(snap_path, "rb") as f:
                resp = requests.post(
                    f"{QDRANT_URL}/collections/{coll}/snapshots/upload",
                    files={"snapshot": (f"{coll}.snapshot", f, "application/octet-stream")},
                    timeout=600,
                )
                resp.raise_for_status()

            # Vérifier
            resp = requests.get(f"{QDRANT_URL}/collections/{coll}", timeout=10)
            points = resp.json().get("result", {}).get("points_count", 0)

            msg = f"[Qdrant] {coll} restauré — {points} points"
            log_lines.append(msg)
            logger.info(msg)

        except Exception as e:
            msg = f"[Qdrant] {coll}: ERREUR restore — {e}"
            log_lines.append(msg)
            logger.error(msg)
            all_ok = False

    return {"status": "success" if all_ok else "error"}


def _restore_postgresql(backup_dir: Path, log_lines: list) -> dict:
    """Restore PostgreSQL depuis JSON export."""
    export_path = backup_dir / "postgres_export.json"
    if not export_path.exists():
        return {"status": "error", "error": "postgres_export.json introuvable"}

    try:
        from sqlalchemy import create_engine, text

        db_url = os.getenv("DATABASE_URL", "postgresql://knowbase:knowbase@postgres:5432/knowbase")
        engine = create_engine(db_url)

        data = json.loads(export_path.read_text(encoding="utf-8"))

        with engine.begin() as conn:
            # Désactiver les contraintes FK temporairement
            conn.execute(text("SET session_replication_role = 'replica'"))

            for table, table_data in data.items():
                rows = table_data.get("rows", [])
                columns = table_data.get("columns", [])

                log_lines.append(f"[PostgreSQL] Restore {table} ({len(rows)} rows)...")

                # Vider la table
                conn.execute(text(f'DELETE FROM "{table}"'))

                # Insérer les rows
                if rows and columns:
                    cols_str = ", ".join(f'"{c}"' for c in columns)
                    params_str = ", ".join(f":{c}" for c in columns)
                    insert_sql = f'INSERT INTO "{table}" ({cols_str}) VALUES ({params_str})'

                    for row in rows:
                        try:
                            conn.execute(text(insert_sql), row)
                        except Exception as row_err:
                            logger.warning(f"[PostgreSQL] Erreur insert {table}: {row_err}")

            # Réactiver les contraintes FK
            conn.execute(text("SET session_replication_role = 'origin'"))

        engine.dispose()

        total_rows = sum(len(t.get("rows", [])) for t in data.values())
        msg = f"[PostgreSQL] Restauré — {len(data)} tables, {total_rows} rows"
        log_lines.append(msg)
        logger.info(msg)
        return {"status": "success"}

    except Exception as e:
        msg = f"[PostgreSQL] ERREUR restore — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "error": str(e)}


def _restore_redis(backup_dir: Path, log_lines: list) -> dict:
    """Restore Redis depuis JSON export."""
    export_path = backup_dir / "redis_export.json"
    if not export_path.exists():
        return {"status": "error", "error": "redis_export.json introuvable"}

    try:
        import redis as redis_lib

        client = redis_lib.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=0,
        )

        # Purger Redis
        log_lines.append("[Redis] Purge des données existantes...")
        client.flushdb()

        data = json.loads(export_path.read_text(encoding="utf-8"))

        restored = 0
        for key_str, entry in data.items():
            key_type = entry.get("type", "string")
            value = entry.get("value")

            if value is None:
                continue

            try:
                if key_type == "string":
                    client.set(key_str, value)
                elif key_type == "list":
                    if value:
                        client.rpush(key_str, *value)
                elif key_type == "set":
                    if value:
                        client.sadd(key_str, *value)
                elif key_type == "hash":
                    if value:
                        client.hset(key_str, mapping=value)
                elif key_type == "zset":
                    if value:
                        for item in value:
                            client.zadd(key_str, {item["member"]: item["score"]})
                restored += 1
            except Exception as key_err:
                logger.warning(f"[Redis] Erreur restore clé {key_str}: {key_err}")

        client.close()

        msg = f"[Redis] Restauré — {restored}/{len(data)} clés"
        log_lines.append(msg)
        logger.info(msg)
        return {"status": "success"}

    except Exception as e:
        msg = f"[Redis] ERREUR restore — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "error": str(e)}


def _restore_extraction_cache(backup_dir: Path, log_lines: list) -> dict:
    """Restore extraction cache depuis tar.gz."""
    tar_path = backup_dir / "extraction_cache.tar.gz"
    if not tar_path.exists():
        log_lines.append("[Cache] Pas de fichier extraction_cache.tar.gz, skip")
        return {"status": "skipped"}

    try:
        log_lines.append("[Cache] Extraction du cache...")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=str(CACHE_DIR))

        count = len(list(CACHE_DIR.glob("*.v5cache.json"))) + len(list(CACHE_DIR.glob("*.npz")))

        msg = f"[Cache] Restauré — {count} fichiers"
        log_lines.append(msg)
        logger.info(msg)
        return {"status": "success", "file_count": count}

    except Exception as e:
        msg = f"[Cache] ERREUR restore — {e}"
        log_lines.append(msg)
        logger.error(msg)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
#  Service principal
# ---------------------------------------------------------------------------

class BackupService:
    """Service backup/restore — Python natif, tourne dans le container."""

    def __init__(self):
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        JOBS_DIR.mkdir(parents=True, exist_ok=True)

    def list_backups(self) -> BackupListResponse:
        """Scanne les backups existants."""
        backups: List[BackupSummary] = []

        if not BACKUPS_DIR.exists():
            return BackupListResponse(backups=[], total=0, backups_dir=str(BACKUPS_DIR))

        for backup_dir in sorted(BACKUPS_DIR.iterdir(), reverse=True):
            manifest_path = backup_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

                # Calculer taille réelle
                size_bytes = manifest.get("size_bytes", 0)
                if size_bytes == 0:
                    size_bytes = _dir_size(backup_dir)

                # Compter composants OK
                components = manifest.get("components", {})
                components_ok = sum(
                    1 for c in components.values()
                    if isinstance(c, dict) and c.get("status") == "success"
                )

                # Total points Qdrant
                qdrant_points = 0
                qdrant_data = components.get("qdrant", {})
                for coll in qdrant_data.get("collections", {}).values():
                    if isinstance(coll, dict):
                        qdrant_points += coll.get("point_count", 0)

                # Total nodes Neo4j
                neo4j_data = components.get("neo4j", {})
                neo4j_nodes = neo4j_data.get("total_nodes", 0)

                dc = manifest.get("domain_context", {})

                backups.append(BackupSummary(
                    name=manifest.get("name", backup_dir.name),
                    created_at=manifest.get("created_at", ""),
                    size_bytes=size_bytes,
                    size_human=_format_size(size_bytes),
                    industry=dc.get("industry", ""),
                    domain_summary=dc.get("domain_summary", ""),
                    neo4j_nodes=neo4j_nodes,
                    qdrant_points=qdrant_points,
                    documents_count=len(manifest.get("imported_documents", [])),
                    components_ok=components_ok,
                    components_total=5,
                ))
            except Exception as e:
                logger.warning(f"Erreur lecture manifest {manifest_path}: {e}")
                continue

        return BackupListResponse(
            backups=backups,
            total=len(backups),
            backups_dir=str(BACKUPS_DIR),
        )

    def get_backup(self, name: str) -> Optional[BackupManifest]:
        """Lit le manifest complet d'un backup."""
        manifest_path = BACKUPS_DIR / name / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return BackupManifest(**data)
        except Exception as e:
            logger.error(f"Erreur lecture manifest {name}: {e}")
            return None

    def delete_backup(self, name: str) -> bool:
        """Supprime un backup."""
        backup_dir = BACKUPS_DIR / name
        if not backup_dir.exists():
            return False

        try:
            shutil.rmtree(backup_dir)
            logger.info(f"Backup {name} supprimé")
            return True
        except Exception as e:
            logger.error(f"Erreur suppression backup {name}: {e}")
            return False

    def get_current_stats(self) -> CurrentSystemStats:
        """Collecte les stats du système actuel."""
        stats = CurrentSystemStats()

        # --- Neo4j ---
        try:
            from neo4j import GraphDatabase
            neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "password")
            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

            with driver.session() as session:
                result = session.run("""
                    MATCH (n)
                    WITH labels(n) as lbls, count(n) as cnt
                    UNWIND lbls as lbl
                    RETURN lbl, sum(cnt) as count
                    ORDER BY count DESC
                """)
                for record in result:
                    stats.neo4j_node_counts[record["lbl"]] = record["count"]

                result = session.run("MATCH (n) RETURN count(n) as c")
                stats.neo4j_nodes = result.single()["c"]

                result = session.run("MATCH ()-[r]->() RETURN count(r) as c")
                stats.neo4j_relationships = result.single()["c"]

                result = session.run("""
                    MATCH (d:DocumentContext)
                    RETURN d.doc_id as doc_id, d.primary_subject as primary_subject
                    ORDER BY d.doc_id
                """)
                for record in result:
                    stats.imported_documents.append(ImportedDocumentInfo(
                        doc_id=record["doc_id"] or "",
                        primary_subject=record.get("primary_subject"),
                    ))

            driver.close()
        except Exception as e:
            logger.warning(f"Erreur stats Neo4j: {e}")

        # --- Qdrant ---
        try:
            from knowbase.common.clients import get_qdrant_client
            qdrant = get_qdrant_client()

            for coll_name in QDRANT_COLLECTIONS:
                try:
                    info = qdrant.get_collection(coll_name)
                    stats.qdrant_collections[coll_name] = info.points_count or 0
                    stats.qdrant_total_points += info.points_count or 0
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Erreur stats Qdrant: {e}")

        # --- PostgreSQL ---
        try:
            from knowbase.db import get_db
            from knowbase.db.models import Session, SessionMessage, User

            db = next(get_db())
            try:
                stats.postgres_sessions = db.query(Session).count()
                stats.postgres_messages = db.query(SessionMessage).count()
                stats.postgres_users = db.query(User).count()
                stats.postgres_table_counts = {
                    "users": stats.postgres_users,
                    "sessions": stats.postgres_sessions,
                    "messages": stats.postgres_messages,
                }
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Erreur stats PostgreSQL: {e}")

        # --- Redis ---
        try:
            import redis
            redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=0,
            )
            stats.redis_keys = redis_client.dbsize()
        except Exception as e:
            logger.warning(f"Erreur stats Redis: {e}")

        # --- Extraction Cache ---
        if CACHE_DIR.exists():
            cache_files = list(CACHE_DIR.glob("*.v5cache.json")) + list(CACHE_DIR.glob("*.npz"))
            stats.extraction_cache_files = len(cache_files)
            stats.extraction_cache_size_bytes = sum(f.stat().st_size for f in cache_files)

        # --- Domain Context ---
        try:
            from knowbase.db import get_db
            from knowbase.db.models import DomainContextProfile

            db = next(get_db())
            try:
                dc = db.query(DomainContextProfile).filter(
                    DomainContextProfile.tenant_id == "default"
                ).first()
                if dc:
                    stats.domain_context = DomainContextInfo(
                        industry=dc.industry or "",
                        domain_summary=dc.domain_summary or "",
                    )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Erreur stats Domain Context: {e}")

        return stats

    def launch_backup(self, name: str, include_cache: bool = True) -> BackupJobStatus:
        """Lance un backup en background (thread Python)."""
        job_id = str(uuid.uuid4())[:8]

        logger.info(f"Lancement backup '{name}' (job={job_id})")

        status = BackupJobStatus(
            job_id=job_id,
            operation="backup",
            status="running",
            name=name,
            started_at=datetime.now().isoformat(),
        )
        self._write_job_status(job_id, status)

        thread = threading.Thread(
            target=self._do_backup,
            args=(name, include_cache, job_id),
            daemon=True,
        )
        thread.start()

        return status

    def _do_backup(self, name: str, include_cache: bool, job_id: str):
        """Exécute le backup complet (appelé dans un thread)."""
        start_time = time.time()
        backup_dir = BACKUPS_DIR / name
        backup_dir.mkdir(parents=True, exist_ok=True)
        log_lines: list = []

        log_lines.append(f"=== OSMOSE BACKUP : {name} ===")
        log_lines.append(f"Début : {datetime.now().isoformat()}")

        # Collecter stats pour le manifest
        log_lines.append("[0/5] Collecte des statistiques...")
        stats = self.get_current_stats()

        manifest_data = {
            "backup_id": job_id,
            "name": name,
            "created_at": datetime.now().isoformat(),
            "duration_seconds": 0,
            "size_bytes": 0,
            "tenant_id": "default",
            "osmose_version": "1.0",
            "domain_context": {
                "industry": stats.domain_context.industry if stats.domain_context else "",
                "domain_summary": stats.domain_context.domain_summary if stats.domain_context else "",
            },
            "components": {},
            "imported_documents": [
                {"doc_id": d.doc_id, "primary_subject": d.primary_subject}
                for d in stats.imported_documents
            ],
        }

        # 1. Neo4j
        log_lines.append("[1/5] Backup Neo4j...")
        self._update_job_progress(job_id, "running", "[1/5] Backup Neo4j...", log_lines)
        manifest_data["components"]["neo4j"] = _backup_neo4j(backup_dir, log_lines)

        # 2. Qdrant
        log_lines.append("[2/5] Backup Qdrant...")
        self._update_job_progress(job_id, "running", "[2/5] Backup Qdrant...", log_lines)
        manifest_data["components"]["qdrant"] = _backup_qdrant(backup_dir, log_lines)

        # 3. PostgreSQL
        log_lines.append("[3/5] Backup PostgreSQL...")
        self._update_job_progress(job_id, "running", "[3/5] Backup PostgreSQL...", log_lines)
        manifest_data["components"]["postgresql"] = _backup_postgresql(backup_dir, log_lines)

        # 4. Redis
        log_lines.append("[4/5] Backup Redis...")
        self._update_job_progress(job_id, "running", "[4/5] Backup Redis...", log_lines)
        manifest_data["components"]["redis"] = _backup_redis(backup_dir, log_lines)

        # 5. Extraction Cache
        log_lines.append("[5/5] Backup Extraction Cache...")
        self._update_job_progress(job_id, "running", "[5/5] Backup Extraction Cache...", log_lines)
        manifest_data["components"]["extraction_cache"] = _backup_extraction_cache(
            backup_dir, include_cache, log_lines
        )

        # Finaliser
        duration = time.time() - start_time
        total_size = _dir_size(backup_dir)
        manifest_data["duration_seconds"] = round(duration, 1)
        manifest_data["size_bytes"] = total_size

        manifest_path = backup_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )

        components_ok = sum(
            1 for c in manifest_data["components"].values()
            if c.get("status") == "success"
        )

        log_lines.append("")
        log_lines.append(f"=== BACKUP COMPLET : {name} ===")
        log_lines.append(f"Taille : {_format_size(total_size)}")
        log_lines.append(f"Durée : {round(duration, 1)}s")
        log_lines.append(f"Composants OK : {components_ok}/5")

        final_status = "completed" if components_ok >= 3 else "failed"
        self._update_job_progress(job_id, final_status, "Backup terminé", log_lines)

        logger.info(f"Backup '{name}' terminé en {round(duration, 1)}s — {components_ok}/5 OK")

    def launch_restore(self, name: str, auto_backup: bool = False) -> BackupJobStatus:
        """Lance une restauration en background (thread Python)."""
        job_id = str(uuid.uuid4())[:8]

        logger.info(f"Lancement restore '{name}' (job={job_id}, auto_backup={auto_backup})")

        status = BackupJobStatus(
            job_id=job_id,
            operation="restore",
            status="running",
            name=name,
            started_at=datetime.now().isoformat(),
        )
        self._write_job_status(job_id, status)

        thread = threading.Thread(
            target=self._do_restore,
            args=(name, auto_backup, job_id),
            daemon=True,
        )
        thread.start()

        return status

    def _do_restore(self, name: str, auto_backup: bool, job_id: str):
        """Exécute la restauration complète (appelé dans un thread)."""
        start_time = time.time()
        backup_dir = BACKUPS_DIR / name
        log_lines: list = []

        log_lines.append(f"=== OSMOSE RESTORE : {name} ===")
        log_lines.append(f"Début : {datetime.now().isoformat()}")

        # Auto-backup avant restore
        if auto_backup:
            auto_name = f"auto_before_restore_{datetime.now().strftime('%Y%m%d_%H%M')}"
            log_lines.append(f"[Auto] Backup préventif '{auto_name}'...")
            self._update_job_progress(job_id, "running", "Auto-backup en cours...", log_lines)
            self._do_backup(auto_name, True, str(uuid.uuid4())[:8])
            log_lines.append(f"[Auto] Backup préventif terminé")

        # 1. Neo4j
        log_lines.append("[1/5] Restore Neo4j...")
        self._update_job_progress(job_id, "running", "[1/5] Restore Neo4j...", log_lines)
        _restore_neo4j(backup_dir, log_lines)

        # 2. Qdrant
        log_lines.append("[2/5] Restore Qdrant...")
        self._update_job_progress(job_id, "running", "[2/5] Restore Qdrant...", log_lines)
        _restore_qdrant(backup_dir, log_lines)

        # 3. PostgreSQL
        log_lines.append("[3/5] Restore PostgreSQL...")
        self._update_job_progress(job_id, "running", "[3/5] Restore PostgreSQL...", log_lines)
        _restore_postgresql(backup_dir, log_lines)

        # 4. Redis
        log_lines.append("[4/5] Restore Redis...")
        self._update_job_progress(job_id, "running", "[4/5] Restore Redis...", log_lines)
        _restore_redis(backup_dir, log_lines)

        # 5. Cache
        log_lines.append("[5/5] Restore Extraction Cache...")
        self._update_job_progress(job_id, "running", "[5/5] Restore Cache...", log_lines)
        _restore_extraction_cache(backup_dir, log_lines)

        duration = time.time() - start_time

        log_lines.append("")
        log_lines.append(f"=== RESTORE COMPLET : {name} ===")
        log_lines.append(f"Durée : {round(duration, 1)}s")

        self._update_job_progress(job_id, "completed", "Restore terminé", log_lines)
        logger.info(f"Restore '{name}' terminé en {round(duration, 1)}s")

    def _update_job_progress(self, job_id: str, status_str: str, progress: str, log_lines: list):
        """Met à jour le statut et les logs d'un job."""
        status = BackupJobStatus(
            job_id=job_id,
            operation="backup",
            status=status_str,
            name="",
            started_at="",
            progress=progress,
            log_lines=log_lines[-30:],
        )
        # Relire le statut existant pour préserver name et started_at
        existing_path = JOBS_DIR / f"{job_id}.status.json"
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                status.name = existing.get("name", "")
                status.started_at = existing.get("started_at", "")
                status.operation = existing.get("operation", "backup")
            except Exception:
                pass

        self._write_job_status(job_id, status)

    def get_job_status(self, job_id: str) -> Optional[BackupJobStatus]:
        """Lit le statut d'un job."""
        status_path = JOBS_DIR / f"{job_id}.status.json"

        if not status_path.exists():
            return None

        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            return BackupJobStatus(**data)
        except Exception as e:
            logger.error(f"Erreur lecture job {job_id}: {e}")
            return None

    def _write_job_status(self, job_id: str, status: BackupJobStatus):
        """Écrit le statut d'un job."""
        status_path = JOBS_DIR / f"{job_id}.status.json"
        status_path.write_text(
            json.dumps(status.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def get_backup_service() -> BackupService:
    """Factory pour le service backup."""
    return BackupService()
