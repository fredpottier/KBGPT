#!/usr/bin/env node

/**
 * Script de warmup pour précompiler les pages Next.js principales
 * après le démarrage du conteneur.
 */

const https = require('http');

const BASE_URL = 'http://localhost:3000';

// Fonction pour attendre que le serveur soit prêt
async function waitForServer(maxAttempts = 30, interval = 2000) {
  console.log('⏳ Attente que le serveur Next.js soit prêt...');

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      await new Promise((resolve) => {
        const req = https.get(`${BASE_URL}/api/health`, (res) => {
          console.log(`✅ Serveur prêt (tentative ${attempt})`);
          res.on('data', () => {});
          res.on('end', () => resolve());
        });

        req.on('error', () => {
          if (attempt === maxAttempts) {
            console.log(`❌ Serveur non disponible après ${maxAttempts} tentatives`);
          }
          resolve();
        });

        req.setTimeout(3000, () => {
          req.destroy();
          resolve();
        });
      });

      // Si on arrive ici sans erreur, le serveur est prêt
      return true;
    } catch (error) {
      if (attempt < maxAttempts) {
        console.log(`⏳ Tentative ${attempt}/${maxAttempts} - Retry dans ${interval/1000}s...`);
        await new Promise(resolve => setTimeout(resolve, interval));
      }
    }
  }

  return false;
}

// Liste des pages principales à précompiler
const ROUTES_TO_WARMUP = [
  '/',                              // Accueil
  '/chat',                          // Chat
  '/documents/import',              // Import documents
  '/documents/status',              // Status des imports
  '/rfp-excel',                     // RFP Excel
  '/api/health',                    // API health
  '/api/imports/history',           // API imports history
  '/api/imports/active',            // API imports actifs
  '/api/sap-solutions',             // API solutions SAP
];

async function warmupRoute(route) {
  return new Promise((resolve) => {
    const startTime = Date.now();

    const req = https.get(`${BASE_URL}${route}`, (res) => {
      const duration = Date.now() - startTime;
      console.log(`✅ ${route} - ${res.statusCode} (${duration}ms)`);
      res.on('data', () => {}); // Consommer la réponse
      res.on('end', () => resolve());
    });

    req.on('error', (err) => {
      console.log(`❌ ${route} - Error: ${err.message}`);
      resolve();
    });

    req.setTimeout(10000, () => {
      console.log(`⏰ ${route} - Timeout`);
      req.destroy();
      resolve();
    });
  });
}

async function warmupAll() {
  console.log('🚀 Démarrage du warmup Next.js...');
  console.log(`📍 Base URL: ${BASE_URL}`);
  console.log(`📝 Routes à précompiler: ${ROUTES_TO_WARMUP.length}`);

  // Attendre que le serveur soit prêt
  const serverReady = await waitForServer();
  if (!serverReady) {
    console.log('❌ Impossible de se connecter au serveur - Abandon du warmup');
    return;
  }

  const startTime = Date.now();

  // Warmup séquentiel pour éviter la surcharge
  for (const route of ROUTES_TO_WARMUP) {
    await warmupRoute(route);
  }

  const totalDuration = Date.now() - startTime;
  console.log(`🎯 Warmup terminé en ${totalDuration}ms`);
}

// Démarrage immédiat mais avec attente serveur intégrée
warmupAll();