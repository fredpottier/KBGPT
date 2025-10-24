"""
Script d'initialisation de l'utilisateur admin par défaut.

Ce script est appelé au démarrage de l'application pour s'assurer
qu'un utilisateur admin existe toujours dans la base de données.

Utilisateur par défaut:
- Email: admin@example.com
- Password: admin123
- Role: admin
- Tenant: default

⚠️ IMPORTANT: Changez le mot de passe admin après le premier déploiement !
"""
import logging
from sqlalchemy.orm import Session

from knowbase.db.base import SessionLocal
from knowbase.db.models import User
from knowbase.common.auth import hash_password

logger = logging.getLogger(__name__)

# Credentials par défaut (à changer en production !)
DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_ADMIN_NAME = "Administrator"


def create_default_admin(db: Session) -> None:
    """
    Crée l'utilisateur admin par défaut s'il n'existe pas.

    Args:
        db: Session SQLAlchemy
    """
    try:
        # Vérifier si l'admin existe déjà
        existing_admin = db.query(User).filter(User.email == DEFAULT_ADMIN_EMAIL).first()

        if existing_admin:
            logger.info(f"✅ Utilisateur admin existe déjà: {DEFAULT_ADMIN_EMAIL}")
            return

        # Créer l'utilisateur admin
        admin_user = User(
            email=DEFAULT_ADMIN_EMAIL,
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            full_name=DEFAULT_ADMIN_NAME,
            role="admin",
            tenant_id="default",
            is_active=True
        )

        db.add(admin_user)
        db.commit()

        logger.info(f"✅ Utilisateur admin créé avec succès: {DEFAULT_ADMIN_EMAIL}")
        logger.warning("⚠️  SÉCURITÉ: Changez le mot de passe admin après le premier déploiement !")

    except Exception as e:
        logger.error(f"❌ Erreur création utilisateur admin: {e}")
        db.rollback()
        raise


def init_default_admin() -> None:
    """
    Point d'entrée principal pour initialiser l'admin par défaut.

    À appeler au démarrage de l'application (dans main.py).
    """
    db = SessionLocal()
    try:
        create_default_admin(db)
    finally:
        db.close()


if __name__ == "__main__":
    # Permet d'exécuter le script directement
    logging.basicConfig(level=logging.INFO)
    init_default_admin()
    print("✅ Initialisation admin terminée")
