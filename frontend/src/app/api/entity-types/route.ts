import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

// Désactiver le cache Next.js pour toujours afficher les types à jour
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET(request: NextRequest) {
  try {
    // Forward JWT token from client to backend
    const authHeader = request.headers.get('Authorization');
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Missing authorization token' },
        { status: 401 }
      );
    }

    // Récupérer les query params (status, etc.)
    const searchParams = request.nextUrl.searchParams;
    const queryString = searchParams.toString();
    const url = queryString
      ? `${BACKEND_URL}/api/entity-types?${queryString}`
      : `${BACKEND_URL}/api/entity-types`;

    const response = await fetch(url, {
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching entity types:', error);
    return NextResponse.json(
      { error: 'Failed to fetch entity types' },
      { status: 500 }
    );
  }
}
