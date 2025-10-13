/**
 * Script de migration automatique JWT pour les routes API frontend.
 *
 * Parcourt tous les fichiers route.ts et ajoute la vérification JWT
 * pour les routes qui font des appels au backend sans authentification.
 *
 * Usage: node scripts/migrate-jwt-routes.js
 */

const fs = require('fs');
const path = require('path');

const FRONTEND_API_DIR = path.join(__dirname, '..', 'frontend', 'src', 'app', 'api');
const DRY_RUN = false; // Set to true pour voir les changements sans les appliquer

console.log('🔍 Migration JWT - Démarrage...\n');
console.log(`📂 Répertoire : ${FRONTEND_API_DIR}\n`);

/**
 * Trouve tous les fichiers route.ts dans l'arborescence API (récursif)
 */
function findRouteFiles(dir) {
  let results = [];
  const list = fs.readdirSync(dir);

  list.forEach(file => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);

    if (stat && stat.isDirectory()) {
      // Récursion dans les sous-dossiers
      results = results.concat(findRouteFiles(filePath));
    } else if (file === 'route.ts') {
      results.push(filePath);
    }
  });

  return results;
}

/**
 * Vérifie si un fichier route.ts a besoin de migration JWT
 */
function needsJWTMigration(content) {
  // Déjà migré si contient verifyJWT ou withJWT
  if (content.includes('verifyJWT') || content.includes('withJWT')) {
    return false;
  }

  // Déjà protégé si contient Authorization header check
  if (content.includes("request.headers.get('Authorization')") ||
      content.includes('request.headers.get("Authorization")')) {
    return false;
  }

  // Besoin de migration si fait des fetch vers le backend
  const hasBackendFetch = content.includes('http://app:8000') ||
                          content.includes('BACKEND_URL') ||
                          content.includes('fetch(');

  return hasBackendFetch;
}

/**
 * Ajoute l'import du helper JWT si absent
 */
function addJWTImport(content) {
  // Check si import existe déjà
  if (content.includes("from '@/lib/jwt-helpers'")) {
    return content;
  }

  // Trouver la dernière ligne d'import
  const lines = content.split('\n');
  let lastImportIndex = -1;

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().startsWith('import ') ||
        lines[i].trim().startsWith("import {")) {
      lastImportIndex = i;
    }
  }

  // Ajouter l'import après la dernière ligne d'import
  if (lastImportIndex >= 0) {
    lines.splice(lastImportIndex + 1, 0, "import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'");
    return lines.join('\n');
  }

  // Si pas d'import trouvé, ajouter au début (après commentaires)
  let insertIndex = 0;
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].trim().startsWith('//') &&
        !lines[i].trim().startsWith('/*') &&
        !lines[i].trim().startsWith('*') &&
        lines[i].trim() !== '') {
      insertIndex = i;
      break;
    }
  }

  lines.splice(insertIndex, 0, "import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'\n");
  return lines.join('\n');
}

/**
 * Ajoute la vérification JWT au début de la fonction handler
 */
function addJWTCheck(content) {
  // Pattern pour détecter le début de la fonction export async function
  const functionPattern = /(export\s+async\s+function\s+(?:GET|POST|PUT|DELETE|PATCH)\s*\([^)]*\)\s*\{)/;

  const match = content.match(functionPattern);
  if (!match) {
    console.warn('⚠️  Pattern fonction non trouvé, skip');
    return content;
  }

  const jwtCheckCode = `
  // ✅ Vérifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;
`;

  // Insérer après l'accolade ouvrante de la fonction
  const insertPosition = match.index + match[0].length;

  return content.slice(0, insertPosition) +
         jwtCheckCode +
         content.slice(insertPosition);
}

/**
 * Ajoute Authorization header aux fetch() calls
 */
function addAuthToFetch(content) {
  // Pattern pour trouver les fetch() avec headers
  // Cas 1: fetch avec headers object existant
  const fetchWithHeadersPattern = /fetch\([^,]+,\s*\{([^}]*headers:\s*\{[^}]*\}[^}]*)\}/g;

  let modified = content;

  // Remplacer tous les fetch qui ont déjà un headers object
  modified = modified.replace(fetchWithHeadersPattern, (match) => {
    // Si Authorization déjà présent, skip
    if (match.includes('Authorization')) {
      return match;
    }

    // Ajouter Authorization au headers object
    return match.replace(
      /headers:\s*\{/,
      "headers: {\n        'Authorization': authHeader,"
    );
  });

  // Cas 2: fetch sans headers (FormData)
  // Pattern: fetch(url, { method: 'POST', body: formData })
  const fetchNoHeadersPattern = /fetch\(([^,]+),\s*\{\s*method:\s*['"]POST['"]\s*,\s*body:/g;

  modified = modified.replace(fetchNoHeadersPattern, (match, url) => {
    return match.replace(
      /method:\s*['"]POST['"]\s*,/,
      "method: 'POST',\n      headers: {\n        'Authorization': authHeader,\n      },"
    );
  });

  return modified;
}

/**
 * Migre un fichier route.ts
 */
function migrateRouteFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');

  if (!needsJWTMigration(content)) {
    return { migrated: false, reason: 'Already protected or no backend calls' };
  }

  let modified = content;

  // Étape 1: Ajouter import JWT helpers
  modified = addJWTImport(modified);

  // Étape 2: Ajouter vérification JWT
  modified = addJWTCheck(modified);

  // Étape 3: Ajouter Authorization aux fetch()
  modified = addAuthToFetch(modified);

  if (DRY_RUN) {
    return { migrated: true, dryRun: true };
  }

  // Écrire le fichier modifié
  fs.writeFileSync(filePath, modified, 'utf-8');

  return { migrated: true };
}

/**
 * Main execution
 */
function main() {
  try {
    const routeFiles = findRouteFiles(FRONTEND_API_DIR);
    console.log(`📝 Trouvé ${routeFiles.length} fichiers route.ts\n`);

    let migratedCount = 0;
    let skippedCount = 0;
    let errorCount = 0;

    for (const file of routeFiles) {
      const relativePath = path.relative(FRONTEND_API_DIR, file);

      try {
        const result = migrateRouteFile(file);

        if (result.migrated) {
          migratedCount++;
          console.log(`✅ Migré: ${relativePath}${result.dryRun ? ' (DRY RUN)' : ''}`);
        } else {
          skippedCount++;
          console.log(`⏭️  Skip: ${relativePath} (${result.reason})`);
        }
      } catch (error) {
        errorCount++;
        console.error(`❌ Erreur: ${relativePath}`, error.message);
      }
    }

    console.log('\n' + '='.repeat(60));
    console.log('📊 Résumé de migration:');
    console.log(`   ✅ Migrés : ${migratedCount}`);
    console.log(`   ⏭️  Skipped : ${skippedCount}`);
    console.log(`   ❌ Erreurs : ${errorCount}`);
    console.log(`   📦 Total : ${routeFiles.length}`);
    console.log('='.repeat(60));

    if (DRY_RUN) {
      console.log('\n⚠️  Mode DRY RUN - Aucun fichier modifié');
      console.log('   Set DRY_RUN=false pour appliquer les changements');
    }

  } catch (error) {
    console.error('❌ Erreur fatale:', error);
    process.exit(1);
  }
}

main();
