"""
Script pour créer l'utilisateur admin par défaut.

Usage:
    python scripts/create_default_admin.py

Note: Script unifié (fusion de create_admin_user.py et create_default_admin.py)
"""
import sys
from pathlib import Path

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowbase.db import init_db, SessionLocal, User
from knowbase.api.services.auth_service import get_auth_service
from datetime import datetime, timezone


def create_default_admin():
    """Crée l'utilisateur admin par défaut."""
    # Initialiser DB (important pour première utilisation)
    init_db()

    db = SessionLocal()

    try:
        auth_service = get_auth_service(db)

        # Vérifier si l'admin existe déjà
        existing_admin = db.query(User).filter(User.email == "admin@example.com").first()

        if existing_admin:
            print("❌ Admin user already exists: admin@example.com")
            print(f"   User ID: {existing_admin.user_id}")
            print(f"   Role: {existing_admin.role}")
            print(f"   Active: {existing_admin.is_active}")
            return

        # Créer l'admin
        admin = User(
            email="admin@example.com",
            full_name="System Administrator",
            role="admin",
            tenant_id="default",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            password_hash=auth_service.hash_password("admin123")  # Attribut correct du modèle User
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print("✅ Admin user created successfully!")
        print(f"   Email: {admin.email}")
        print(f"   Password: admin123")
        print(f"   Role: {admin.role}")
        print(f"   User ID: {admin.user_id}")
        print(f"   Tenant: {admin.tenant_id}")
        print()
        print("🔐 You can now login at http://localhost:3000/login")
        print()
        print("⚠️  IMPORTANT: Change this password immediately in production!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error creating admin user: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_default_admin()
