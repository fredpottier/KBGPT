#!/usr/bin/env python3
"""
Script de migration automatique JWT pour les routes API frontend.

Parcourt tous les fichiers route.ts et ajoute la vérification JWT
pour les routes qui font des appels au backend sans authentification.

Usage: python scripts/migrate_jwt_routes.py
"""

import os
import re
from pathlib import Path

FRONTEND_API_DIR = Path(__file__).parent.parent / "frontend" / "src" / "app" / "api"
DRY_RUN = False  # Set to True pour voir les changements sans les appliquer

print("[INFO] Migration JWT - Demarrage...\n")
print(f"[INFO] Repertoire : {FRONTEND_API_DIR}\n")


def find_route_files():
    """Trouve tous les fichiers route.ts dans l'arborescence API"""
    return list(FRONTEND_API_DIR.rglob("route.ts"))


def needs_jwt_migration(content):
    """Vérifie si un fichier route.ts a besoin de migration JWT"""
    # Déjà migré si contient verifyJWT ou withJWT
    if "verifyJWT" in content or "withJWT" in content:
        return False

    # Déjà protégé si contient Authorization header check
    if "request.headers.get('Authorization')" in content or \
       'request.headers.get("Authorization")' in content:
        return False

    # Besoin de migration si fait des fetch vers le backend
    has_backend_fetch = "http://app:8000" in content or \
                        "BACKEND_URL" in content or \
                        "fetch(" in content

    return has_backend_fetch


def add_jwt_import(content):
    """Ajoute l'import du helper JWT si absent"""
    # Check si import existe déjà
    if "from '@/lib/jwt-helpers'" in content:
        return content

    # Trouver la dernière ligne d'import
    lines = content.split('\n')
    last_import_index = -1

    for i, line in enumerate(lines):
        if line.strip().startswith('import '):
            last_import_index = i

    # Ajouter l'import après la dernière ligne d'import
    if last_import_index >= 0:
        lines.insert(last_import_index + 1, "import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'")
        return '\n'.join(lines)

    # Si pas d'import trouvé, ajouter au début
    insert_index = 0
    for i, line in enumerate(lines):
        if not line.strip().startswith('//') and \
           not line.strip().startswith('/*') and \
           not line.strip().startswith('*') and \
           line.strip() != '':
            insert_index = i
            break

    lines.insert(insert_index, "import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'\n")
    return '\n'.join(lines)


def add_jwt_check(content):
    """Ajoute la vérification JWT au début de la fonction handler"""
    # Pattern pour détecter le début de la fonction export async function
    function_pattern = r'(export\s+async\s+function\s+(?:GET|POST|PUT|DELETE|PATCH)\s*\([^)]*\)\s*\{)'

    match = re.search(function_pattern, content)
    if not match:
        print('[WARNING] Pattern fonction non trouve, skip')
        return content

    jwt_check_code = """
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;
"""

    # Insérer après l'accolade ouvrante de la fonction
    insert_position = match.end()

    return content[:insert_position] + jwt_check_code + content[insert_position:]


def add_auth_to_fetch(content):
    """Ajoute Authorization header aux fetch() calls"""
    # Cas 1: fetch avec headers object existant
    def replace_headers(match):
        if 'Authorization' in match.group(0):
            return match.group(0)

        return match.group(0).replace(
            'headers: {',
            "headers: {\n        'Authorization': authHeader,"
        )

    fetch_with_headers_pattern = r'fetch\([^,]+,\s*\{[^}]*headers:\s*\{[^}]*\}[^}]*\}'
    modified = re.sub(fetch_with_headers_pattern, replace_headers, content)

    # Cas 2: fetch sans headers (FormData)
    def replace_method(match):
        return match.group(0).replace(
            "method: 'POST',",
            "method: 'POST',\n      headers: {\n        'Authorization': authHeader,\n      },"
        )

    fetch_no_headers_pattern = r"fetch\([^,]+,\s*\{\s*method:\s*['\"]POST['\"]\s*,\s*body:"
    modified = re.sub(fetch_no_headers_pattern, replace_method, modified)

    return modified


def migrate_route_file(file_path):
    """Migre un fichier route.ts"""
    content = file_path.read_text(encoding='utf-8')

    if not needs_jwt_migration(content):
        return {'migrated': False, 'reason': 'Already protected or no backend calls'}

    modified = content

    # Étape 1: Ajouter import JWT helpers
    modified = add_jwt_import(modified)

    # Étape 2: Ajouter vérification JWT
    modified = add_jwt_check(modified)

    # Étape 3: Ajouter Authorization aux fetch()
    modified = add_auth_to_fetch(modified)

    if DRY_RUN:
        return {'migrated': True, 'dry_run': True}

    # Écrire le fichier modifié
    file_path.write_text(modified, encoding='utf-8')

    return {'migrated': True}


def main():
    """Main execution"""
    try:
        route_files = find_route_files()
        print(f"[INFO] Trouve {len(route_files)} fichiers route.ts\n")

        migrated_count = 0
        skipped_count = 0
        error_count = 0

        for file in route_files:
            relative_path = file.relative_to(FRONTEND_API_DIR)

            try:
                result = migrate_route_file(file)

                if result['migrated']:
                    migrated_count += 1
                    dry_run_msg = ' (DRY RUN)' if result.get('dry_run') else ''
                    print(f"[OK] Migre: {relative_path}{dry_run_msg}")
                else:
                    skipped_count += 1
                    print(f"[SKIP] {relative_path} ({result['reason']})")
            except Exception as e:
                error_count += 1
                print(f"[ERROR] {relative_path} - {str(e)}")

        print('\n' + '=' * 60)
        print('[SUMMARY] Resume de migration:')
        print(f'   [OK] Migres : {migrated_count}')
        print(f'   [SKIP] Skipped : {skipped_count}')
        print(f'   [ERROR] Erreurs : {error_count}')
        print(f'   [TOTAL] Total : {len(route_files)}')
        print('=' * 60)

        if DRY_RUN:
            print('\n[WARNING] Mode DRY RUN - Aucun fichier modifie')
            print('   Set DRY_RUN=False pour appliquer les changements')

    except Exception as error:
        print(f'[FATAL] Erreur fatale: {error}')
        exit(1)


if __name__ == '__main__':
    main()
