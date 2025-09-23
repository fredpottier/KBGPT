#!/usr/bin/env node

/**
 * Script de warmup pour précompiler les pages Next.js principales
 * après le démarrage du conteneur.
 */

const https = require('http');

const BASE_URL = 'http://localhost:3000';

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

  const startTime = Date.now();

  // Warmup séquentiel pour éviter la surcharge
  for (const route of ROUTES_TO_WARMUP) {
    await warmupRoute(route);
  }

  const totalDuration = Date.now() - startTime;
  console.log(`🎯 Warmup terminé en ${totalDuration}ms`);
}

// Attendre quelques secondes pour que le serveur soit prêt
setTimeout(warmupAll, 5000);