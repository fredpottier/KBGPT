/**
 * Helper pour vérifier et extraire le JWT token des requêtes Next.js API routes.
 *
 * Utilisé par les routes /app/api/** pour transmettre l'authentification au backend.
 */

import { NextRequest, NextResponse } from 'next/server'

/**
 * Vérifie la présence du JWT token dans les headers et le retourne.
 *
 * @param request - Next.js request object
 * @returns JWT token string ou NextResponse error si absent
 *
 * @example
 * ```typescript
 * export async function POST(request: NextRequest) {
 *   const authResult = verifyJWT(request);
 *   if (authResult instanceof NextResponse) {
 *     return authResult; // Error response
 *   }
 *
 *   const authHeader = authResult;
 *   // Use authHeader in backend fetch...
 * }
 * ```
 */
export function verifyJWT(request: NextRequest): string | NextResponse {
  const authHeader = request.headers.get('Authorization')

  if (!authHeader) {
    return NextResponse.json(
      { error: 'Missing authorization token' },
      { status: 401 }
    )
  }

  return authHeader
}

/**
 * Ajoute les headers d'authentification JWT à un fetch vers le backend.
 *
 * @param authHeader - JWT token (format: "Bearer <token>")
 * @param additionalHeaders - Headers additionnels optionnels
 * @returns Headers object avec Authorization + headers additionnels
 *
 * @example
 * ```typescript
 * const response = await fetch(`${BACKEND_URL}/endpoint`, {
 *   method: 'POST',
 *   headers: createAuthHeaders(authHeader, {
 *     'Content-Type': 'application/json'
 *   }),
 *   body: JSON.stringify(data)
 * })
 * ```
 */
export function createAuthHeaders(
  authHeader: string,
  additionalHeaders: Record<string, string> = {}
): Record<string, string> {
  return {
    'Authorization': authHeader,
    ...additionalHeaders
  }
}

/**
 * Higher-order function qui wrap une route handler avec vérification JWT automatique.
 *
 * @param handler - Route handler à protéger
 * @returns Route handler avec JWT vérifié
 *
 * @example
 * ```typescript
 * export const POST = withJWT(async (request: NextRequest, authHeader: string) => {
 *   const body = await request.json()
 *
 *   const response = await fetch(`${BACKEND_URL}/endpoint`, {
 *     method: 'POST',
 *     headers: createAuthHeaders(authHeader, {
 *       'Content-Type': 'application/json'
 *     }),
 *     body: JSON.stringify(body)
 *   })
 *
 *   const data = await response.json()
 *   return NextResponse.json(data)
 * })
 * ```
 */
export function withJWT(
  handler: (request: NextRequest, authHeader: string, ...args: any[]) => Promise<NextResponse>
) {
  return async (request: NextRequest, ...args: any[]): Promise<NextResponse> => {
    const authResult = verifyJWT(request)

    if (authResult instanceof NextResponse) {
      return authResult // Return error response
    }

    const authHeader = authResult
    return handler(request, authHeader, ...args)
  }
}
