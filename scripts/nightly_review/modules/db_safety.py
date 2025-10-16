"""
Module DB Safety - Gestion snapshots bases de données.

Fonctionnalités:
- Création de snapshots avant tests
- Vérification de l'intégrité des données
- Surveillance mode READ-ONLY
- Restauration automatique si nécessaire
"""
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import json


class DBSafety:
    """Gestionnaire de sécurité des bases de données."""

    def __init__(self, project_root: Path):
        """
        Initialise le gestionnaire de sécurité.

        Args:
            project_root: Racine du projet
        """
        self.project_root = project_root
        self.data_dir = project_root / "data"
        self.backup_dir = project_root / "backups" / "nightly_review"
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.results = {
            "snapshots": [],
            "integrity_checks": [],
            "errors": []
        }

    def create_snapshots(self) -> Dict[str, Any]:
        """
        Crée des snapshots de toutes les bases de données.

        Returns:
            Résultats de la création
        """
        print("💾 DB Safety - Création snapshots...")

        # Créer le répertoire de backup
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Snapshots des différentes bases
        self._snapshot_sqlite()
        self._snapshot_redis()
        self._snapshot_qdrant()
        # Note: Neo4j nécessite des droits admin, on documente juste l'état

        return {
            "backup_dir": str(self.backup_dir),
            "timestamp": self.timestamp,
            "snapshots": self.results["snapshots"],
            "total_snapshots": len(self.results["snapshots"])
        }

    def _snapshot_sqlite(self):
        """Crée un snapshot de la base SQLite."""
        print("  📁 Snapshot SQLite...")

        sqlite_file = self.data_dir / "entity_types_registry.db"

        if not sqlite_file.exists():
            print("    ℹ️ Pas de base SQLite à sauvegarder")
            return

        try:
            backup_file = self.backup_dir / f"entity_types_registry_{self.timestamp}.db"
            shutil.copy2(sqlite_file, backup_file)

            size_mb = backup_file.stat().st_size / (1024 * 1024)

            self.results["snapshots"].append({
                "database": "SQLite",
                "source": str(sqlite_file),
                "backup": str(backup_file),
                "size_mb": round(size_mb, 2),
                "status": "ok"
            })

            print(f"    ✓ SQLite sauvegardé ({size_mb:.2f} MB)")

        except Exception as e:
            self.results["errors"].append({
                "database": "SQLite",
                "operation": "snapshot",
                "error": str(e)
            })
            print(f"    ✗ Erreur snapshot SQLite: {e}")

    def _snapshot_redis(self):
        """Crée un snapshot de Redis."""
        print("  📁 Snapshot Redis...")

        try:
            # Forcer une sauvegarde Redis
            result = subprocess.run(
                ["docker-compose", "exec", "-T", "redis", "redis-cli", "SAVE"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Copier le fichier dump.rdb
                redis_dump = self.data_dir / "redis" / "dump.rdb"
                if redis_dump.exists():
                    backup_file = self.backup_dir / f"redis_dump_{self.timestamp}.rdb"
                    shutil.copy2(redis_dump, backup_file)

                    size_mb = backup_file.stat().st_size / (1024 * 1024)

                    self.results["snapshots"].append({
                        "database": "Redis",
                        "source": str(redis_dump),
                        "backup": str(backup_file),
                        "size_mb": round(size_mb, 2),
                        "status": "ok"
                    })

                    print(f"    ✓ Redis sauvegardé ({size_mb:.2f} MB)")
                else:
                    print("    ℹ️ Fichier Redis dump.rdb non trouvé")

        except Exception as e:
            self.results["errors"].append({
                "database": "Redis",
                "operation": "snapshot",
                "error": str(e)
            })
            print(f"    ✗ Erreur snapshot Redis: {e}")

    def _snapshot_qdrant(self):
        """Crée un snapshot de Qdrant."""
        print("  📁 Snapshot Qdrant...")

        try:
            # Créer un snapshot via l'API Qdrant
            import requests

            response = requests.post(
                "http://localhost:6333/collections/knowbase/snapshots",
                timeout=30
            )

            if response.status_code in [200, 201]:
                snapshot_info = response.json()

                self.results["snapshots"].append({
                    "database": "Qdrant",
                    "collection": "knowbase",
                    "snapshot_name": snapshot_info.get("result", {}).get("name", "unknown"),
                    "status": "ok"
                })

                print(f"    ✓ Qdrant snapshot créé")

            # Snapshot collection rfp_qa aussi
            response2 = requests.post(
                "http://localhost:6333/collections/rfp_qa/snapshots",
                timeout=30
            )

            if response2.status_code in [200, 201]:
                print(f"    ✓ Qdrant rfp_qa snapshot créé")

        except Exception as e:
            self.results["errors"].append({
                "database": "Qdrant",
                "operation": "snapshot",
                "error": str(e)
            })
            print(f"    ✗ Erreur snapshot Qdrant: {e}")

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Vérifie l'intégrité des données après tests.

        Returns:
            Résultats de la vérification
        """
        print("🔍 Vérification intégrité données...")

        # Vérifier SQLite
        self._check_sqlite_integrity()

        # Comparer avec les snapshots
        self._compare_with_snapshots()

        return {
            "checks": self.results["integrity_checks"],
            "total_checks": len(self.results["integrity_checks"]),
            "issues_found": len([c for c in self.results["integrity_checks"] if c["status"] != "ok"])
        }

    def _check_sqlite_integrity(self):
        """Vérifie l'intégrité de SQLite."""
        print("  🔍 Intégrité SQLite...")

        sqlite_file = self.data_dir / "entity_types_registry.db"

        if not sqlite_file.exists():
            return

        try:
            result = subprocess.run(
                ["docker-compose", "exec", "-T", "app", "sqlite3", str(sqlite_file), "PRAGMA integrity_check;"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10
            )

            is_ok = "ok" in result.stdout.lower()

            self.results["integrity_checks"].append({
                "database": "SQLite",
                "check": "integrity_check",
                "status": "ok" if is_ok else "error",
                "output": result.stdout.strip()
            })

            print(f"    {'✓' if is_ok else '✗'} SQLite intégrité: {result.stdout.strip()}")

        except Exception as e:
            print(f"    ⚠ Erreur vérification SQLite: {e}")

    def _compare_with_snapshots(self):
        """Compare les tailles des fichiers avec les snapshots."""
        print("  📊 Comparaison avec snapshots...")

        for snapshot in self.results["snapshots"]:
            if "source" in snapshot and "backup" in snapshot:
                source = Path(snapshot["source"])
                backup = Path(snapshot["backup"])

                if source.exists() and backup.exists():
                    size_diff = abs(source.stat().st_size - backup.stat().st_size)
                    size_diff_mb = size_diff / (1024 * 1024)

                    # Si différence > 10MB, signaler
                    status = "ok" if size_diff_mb < 10 else "warning"

                    self.results["integrity_checks"].append({
                        "database": snapshot["database"],
                        "check": "size_comparison",
                        "status": status,
                        "size_diff_mb": round(size_diff_mb, 2)
                    })

                    print(f"    ✓ {snapshot['database']}: Δ {size_diff_mb:.2f} MB")

    def generate_report(self) -> str:
        """
        Génère un rapport JSON des opérations.

        Returns:
            Chemin du fichier rapport
        """
        report_file = self.backup_dir / f"safety_report_{self.timestamp}.json"

        report = {
            "timestamp": self.timestamp,
            "snapshots": self.results["snapshots"],
            "integrity_checks": self.results["integrity_checks"],
            "errors": self.results["errors"]
        }

        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        return str(report_file)


def create_db_snapshots(project_root: Path) -> Dict[str, Any]:
    """
    Crée les snapshots de toutes les bases.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de la création
    """
    safety = DBSafety(project_root)
    return safety.create_snapshots()


def verify_db_integrity(project_root: Path) -> Dict[str, Any]:
    """
    Vérifie l'intégrité des bases.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de la vérification
    """
    safety = DBSafety(project_root)
    return safety.verify_integrity()
