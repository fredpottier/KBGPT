"""
Service de backup & restore OSMOSE.

Lecture des stats système, gestion des manifests,
et orchestration des opérations via subprocess kw.ps1.
"""

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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

# Répertoire des backups
BACKUPS_DIR = Path("data/backups/snapshots")
JOBS_DIR = Path("data/backups/jobs")


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


class BackupService:
    """Service backup/restore — lecture stats + orchestration."""

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
                # Compter nodes par label
                result = session.run("""
                    MATCH (n)
                    WITH labels(n) as lbls, count(n) as cnt
                    UNWIND lbls as lbl
                    RETURN lbl, sum(cnt) as count
                    ORDER BY count DESC
                """)
                for record in result:
                    stats.neo4j_node_counts[record["lbl"]] = record["count"]

                # Total nodes
                result = session.run("MATCH (n) RETURN count(n) as c")
                stats.neo4j_nodes = result.single()["c"]

                # Total relationships
                result = session.run("MATCH ()-[r]->() RETURN count(r) as c")
                stats.neo4j_relationships = result.single()["c"]

                # Documents importés
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

            for coll_name in [settings.qdrant_collection, settings.qdrant_qa_collection]:
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
        cache_dir = Path("data/extraction_cache")
        if cache_dir.exists():
            cache_files = list(cache_dir.glob("*.knowcache.json"))
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
        """Lance un backup via kw.ps1 en subprocess."""
        job_id = str(uuid.uuid4())[:8]
        log_path = JOBS_DIR / f"{job_id}.log"

        # Construire la commande
        cmd = f"./kw.ps1 backup {name}"
        if not include_cache:
            cmd += " --no-cache"

        logger.info(f"Lancement backup '{name}' (job={job_id})")

        # Écrire statut initial
        status = BackupJobStatus(
            job_id=job_id,
            operation="backup",
            status="running",
            name=name,
            started_at=datetime.now().isoformat(),
        )
        self._write_job_status(job_id, status)

        # Lancer en background
        try:
            with open(log_path, "w", encoding="utf-8") as logfile:
                subprocess.Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", "kw.ps1", "backup", name]
                    + (["--no-cache"] if not include_cache else []),
                    stdout=logfile,
                    stderr=subprocess.STDOUT,
                    cwd=str(Path.cwd()),
                )
        except Exception as e:
            status.status = "failed"
            status.error = str(e)
            self._write_job_status(job_id, status)

        return status

    def launch_restore(self, name: str, auto_backup: bool = False) -> BackupJobStatus:
        """Lance une restauration via kw.ps1 en subprocess."""
        job_id = str(uuid.uuid4())[:8]
        log_path = JOBS_DIR / f"{job_id}.log"

        logger.info(f"Lancement restore '{name}' (job={job_id}, auto_backup={auto_backup})")

        status = BackupJobStatus(
            job_id=job_id,
            operation="restore",
            status="running",
            name=name,
            started_at=datetime.now().isoformat(),
        )
        self._write_job_status(job_id, status)

        try:
            args = ["powershell", "-ExecutionPolicy", "Bypass", "-File", "kw.ps1", "restore", name, "--force"]
            if auto_backup:
                args.append("--auto-backup")

            with open(log_path, "w", encoding="utf-8") as logfile:
                subprocess.Popen(
                    args,
                    stdout=logfile,
                    stderr=subprocess.STDOUT,
                    cwd=str(Path.cwd()),
                )
        except Exception as e:
            status.status = "failed"
            status.error = str(e)
            self._write_job_status(job_id, status)

        return status

    def get_job_status(self, job_id: str) -> Optional[BackupJobStatus]:
        """Lit le statut d'un job."""
        status_path = JOBS_DIR / f"{job_id}.status.json"
        log_path = JOBS_DIR / f"{job_id}.log"

        if not status_path.exists():
            return None

        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            status = BackupJobStatus(**data)

            # Lire les dernières lignes du log
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                status.log_lines = lines[-30:]  # 30 dernières lignes

                # Détecter la complétion depuis le log
                full_text = "\n".join(lines)
                if "Backup termine" in full_text or "BACKUP COMPLET" in full_text:
                    status.status = "completed"
                    self._write_job_status(job_id, status)
                elif "Restore termine" in full_text or "RESTORE COMPLET" in full_text:
                    status.status = "completed"
                    self._write_job_status(job_id, status)
                elif "ERREUR" in full_text or "Error" in full_text:
                    if status.status == "running":
                        # Vérifier si le process est toujours actif
                        pass

            return status
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
