"""
⚠️ DEPRECATED - Ce fichier n'est plus utilisé ⚠️

Dépendances d'authentification et autorisation.

Phase 3 - Security & RBAC (OLD)

Ce fichier contenait un système d'authentification simplifié avec clé hardcodée.
Il a été remplacé par JWT + RBAC dans `knowbase.api.dependencies`.

HISTORIQUE:
- Phase 3: Authentification basique avec X-Admin-Key hardcodée
- Phase 0: Migration vers JWT complet (RS256, refresh tokens, RBAC)

NOUVEAU SYSTÈME:
Utiliser `knowbase.api.dependencies`:
- `get_current_user()` - Extraction JWT claims
- `require_admin()` - Vérification rôle admin
- `require_editor()` - Vérification rôle editor
- `get_tenant_id()` - Isolation multi-tenant

Ce fichier est conservé pour traçabilité historique uniquement.
"""

# DEPRECATED - Ne pas utiliser
# L'ancien système avec clé hardcodée a été supprimé pour des raisons de sécurité
# Voir knowbase.api.dependencies pour le nouveau système JWT

# Ancien code supprimé :
# - require_admin() avec ADMIN_KEY hardcodée
# - get_tenant_id() basé sur headers non sécurisés
#
# Nouveau système JWT dans knowbase.api.dependencies :
# - Authentification RS256 avec tokens signés
# - RBAC (admin/editor/viewer)
# - Multi-tenancy via JWT claims
# - Refresh tokens
# - Audit trail complet

__all__ = []  # Plus d'exports - fichier déprécié
