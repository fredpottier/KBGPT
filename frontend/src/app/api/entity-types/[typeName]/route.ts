import { NextRequest, NextResponse } from 'next/server';
import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

// Désactiver le cache Next.js pour toujours afficher les infos à jour
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET(
  request: NextRequest,
  { params }: { params: { typeName: string } }
) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const typeName = params.typeName;
    const url = `${BACKEND_URL}/api/entity-types/${typeName}`;

    const response = await fetch(url, {
      headers: {
        'Authorization': authHeader,
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to fetch entity type info' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching entity type info:', error);
    return NextResponse.json(
      { error: 'Failed to fetch entity type info' },
      { status: 500 }
    );
  }
}
