"""
Migration: Ajout colonnes workflow normalisation
Phase 5B - Entity Types Normalization Status
Date: 2025-10-08
"""
from sqlalchemy import create_engine, text
import os

def run_migration():
    """Exécute la migration pour ajouter les colonnes de normalisation."""
    # Chemin base de données
    db_path = os.getenv("ENTITY_TYPES_DB_PATH", "/data/entity_types_registry.db")
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.connect() as conn:
        # Vérifier si les colonnes existent déjà
        result = conn.execute(text("PRAGMA table_info(entity_types_registry)"))
        columns = [row[1] for row in result.fetchall()]

        if 'normalization_status' in columns:
            print("✅ Colonnes déjà migrées")
            return

        print("📝 Migration en cours...")

        # Ajouter les colonnes
        conn.execute(text("ALTER TABLE entity_types_registry ADD COLUMN normalization_status VARCHAR(20)"))
        conn.execute(text("ALTER TABLE entity_types_registry ADD COLUMN normalization_job_id VARCHAR(50)"))
        conn.execute(text("ALTER TABLE entity_types_registry ADD COLUMN normalization_started_at TIMESTAMP"))

        conn.commit()

        print("✅ Migration terminée - Colonnes normalization ajoutées")

if __name__ == "__main__":
    run_migration()
