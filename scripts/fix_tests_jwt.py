#!/usr/bin/env python3
"""
Script pour ajouter automatiquement JWT headers aux tests API.

Transforme :
    def test_something(self, client):
        response = client.get("/api/endpoint")

En :
    def test_something(self, client, viewer_headers):
        response = client.get("/api/endpoint", headers=viewer_headers)

Pour les tests qui nécessitent admin :
    def test_something(self, client, admin_headers):
        response = client.get("/api/endpoint", headers=admin_headers)
"""

import re
import sys
from pathlib import Path

def fix_test_file(file_path: Path, default_role="viewer"):
    """
    Ajoute JWT headers aux tests d'un fichier.

    Args:
        file_path: Chemin vers le fichier de test
        default_role: Rôle par défaut (viewer, editor, admin)
    """
    print(f"\n[INFO] Traitement {file_path.name}...")

    content = file_path.read_text(encoding='utf-8')
    original_content = content

    # Patterns pour détecter les tests qui nécessitent JWT
    # Pattern 1: def test_xxx(self, client):
    pattern1 = r'(def test_\w+\(self, client)\):'

    # Déterminer les headers à utiliser selon le contexte
    headers_fixture = f"{default_role}_headers"

    # Remplacer signature de fonction
    content = re.sub(
        pattern1,
        rf'\1, {headers_fixture}):',
        content
    )

    # Pattern 2: client.get("/api/...") sans headers
    # Capturer méthode HTTP et endpoint
    pattern2 = r'(client\.(get|post|put|delete|patch)\(["\'][^"\']+["\'])\)'

    def add_headers(match):
        base_call = match.group(1)
        # Ne pas ajouter headers si déjà présent
        if 'headers=' in match.group(0):
            return match.group(0)
        return f'{base_call}, headers={headers_fixture})'

    content = re.sub(pattern2, add_headers, content)

    # Pattern 3: client.xxx(..., json=...) sans headers
    pattern3 = r'(client\.(get|post|put|delete|patch)\([^)]+json=[^)]+)\)'

    def add_headers_with_json(match):
        base_call = match.group(1)
        # Ne pas ajouter headers si déjà présent
        if 'headers=' in match.group(0):
            return match.group(0)
        return f'{base_call}, headers={headers_fixture})'

    content = re.sub(pattern3, add_headers_with_json, content)

    # Compter changements
    if content != original_content:
        changes = content.count(headers_fixture) - original_content.count(headers_fixture)
        file_path.write_text(content, encoding='utf-8')
        print(f"[OK] {changes} ajouts de {headers_fixture}")
        return True
    else:
        print(f"[SKIP] Aucun changement nécessaire")
        return False


def main():
    """Point d'entrée principal."""
    if len(sys.argv) < 2:
        print("Usage: python fix_tests_jwt.py <test_file.py> [role]")
        print("Roles: viewer (default), editor, admin")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    role = sys.argv[2] if len(sys.argv) > 2 else "viewer"

    if not file_path.exists():
        print(f"[ERROR] Fichier introuvable: {file_path}")
        sys.exit(1)

    if role not in ["viewer", "editor", "admin"]:
        print(f"[ERROR] Rôle invalide: {role}. Utilisez viewer, editor ou admin")
        sys.exit(1)

    success = fix_test_file(file_path, default_role=role)

    if success:
        print(f"\n[SUCCESS] Fichier mis à jour: {file_path}")
    else:
        print(f"\n[INFO] Aucune modification nécessaire")


if __name__ == "__main__":
    main()
