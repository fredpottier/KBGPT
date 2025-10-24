/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  typescript: {
    // ⚠️ Production: ignore type errors for faster deployment
    ignoreBuildErrors: true,
  },
  eslint: {
    // ⚠️ Production: ignore ESLint errors for faster deployment
    ignoreDuringBuilds: true,
  },
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
  },

  // Optimisations pour le développement
  onDemandEntries: {
    // Garde les pages en mémoire plus longtemps
    maxInactiveAge: 60 * 1000, // 1 minute au lieu de 15 secondes
    pagesBufferLength: 5, // Garde 5 pages en buffer
  },

  // Configuration webpack pour la vitesse
  webpack: (config, { dev, isServer }) => {
    if (dev) {
      // Parallélisation de la compilation en développement
      config.cache = {
        type: 'filesystem',
        buildDependencies: {
          config: [__filename],
        },
      };
    }
    return config;
  },

  // IMPORTANT: Ne PAS utiliser de rewrites pour /api/* car nous avons des routes API Next.js
  // dans src/app/api/* qui doivent être utilisées comme proxy avec authentification
  // async rewrites() {
  //   const apiUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
  //   return [
  //     {
  //       source: '/api/:path*',
  //       destination: `${apiUrl}/api/:path*`,
  //     },
  //   ]
  // },
  // Disable caching for all API calls
  async headers() {
    return [
      {
        source: '/api/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'no-store, no-cache, must-revalidate',
          },
        ],
      },
    ]
  },
}

module.exports = nextConfig