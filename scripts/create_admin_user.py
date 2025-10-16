"""
Script pour créer un utilisateur admin par défaut.

Phase 0 - Security Hardening

Usage:
    python scripts/create_admin_user.py
"""
import sys
from pathlib import Path

# Ajouter src/ au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.db import init_db, SessionLocal
from knowbase.db.models import User
from knowbase.api.services.auth_service import get_auth_service


def create_admin_user():
    """Crée un utilisateur admin par défaut si aucun admin n'existe."""
    # Initialiser DB
    init_db()

    # Session
    db = SessionLocal()

    try:
        # Vérifier si un admin existe
        admin_exists = db.query(User).filter(User.role == "admin").first()

        if admin_exists:
            print(f"✅ Un utilisateur admin existe déjà: {admin_exists.email}")
            return

        # Créer admin par défaut
        auth_service = get_auth_service()

        admin_email = "admin@example.com"
        admin_password = "Admin123!"  # ⚠️ À CHANGER EN PRODUCTION
        tenant_id = "default"

        password_hash = auth_service.hash_password(admin_password)

        admin_user = User(
            email=admin_email,
            password_hash=password_hash,
            full_name="Administrator",
            role="admin",
            tenant_id=tenant_id,
            is_active=True
        )

        db.add(admin_user)
        db.commit()

        print("✅ Utilisateur admin créé avec succès!")
        print(f"   Email: {admin_email}")
        print(f"   Password: {admin_password}")
        print(f"   Tenant ID: {tenant_id}")
        print("")
        print("⚠️  IMPORTANT: Changez ce mot de passe immédiatement en production!")

    except Exception as e:
        print(f"❌ Erreur lors de la création de l'admin: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_admin_user()
