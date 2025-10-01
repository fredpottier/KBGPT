"""
Backup Audit Trail Redis - Phase 0.5 P1.10

Script pour backuper audit trail Redis vers fichiers JSON
À exécuter via cron quotidiennement

Usage:
    python scripts/backup_audit_trail.py
"""

import redis
import json
from datetime import datetime
from pathlib import Path


def backup_audit_trail(
    redis_url: str = "redis://redis:6379/1",
    backup_dir: str = "/data/backups/audit_trail"
):
    """
    Backup audit trail Redis vers JSON

    Args:
        redis_url: URL Redis contenant audit trail
        backup_dir: Répertoire backups
    """
    r = redis.Redis.from_url(redis_url, decode_responses=True)
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    # Récupérer toutes clés audit:merge:*
    keys = r.keys("audit:merge:*")
    print(f"Found {len(keys)} audit entries to backup")

    entries = []
    for key in keys:
        data = r.get(key)
        if data:
            entries.append({
                "key": key,
                "data": json.loads(data)
            })

    # Sauvegarder avec timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = backup_path / f"audit_trail_{timestamp}.json"

    with open(filename, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"✅ Backup saved: {filename} ({len(entries)} entries)")
    return filename


if __name__ == "__main__":
    backup_audit_trail()
