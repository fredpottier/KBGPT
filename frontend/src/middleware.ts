import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Note: Middleware ne peut pas accéder à localStorage (client-side uniquement).
// La protection des routes est gérée par AuthContext côté client.
// Ce middleware ne fait que des redirections basiques.

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Laisser passer toutes les requêtes
  // La vraie protection est gérée par AuthContext + useEffect dans les pages
  return NextResponse.next()
}

// Configurer les routes où le middleware s'applique
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
}
