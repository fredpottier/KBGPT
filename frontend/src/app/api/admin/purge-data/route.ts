import { NextRequest, NextResponse } from 'next/server';
import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(request: NextRequest) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const url = `${BACKEND_URL}/api/admin/purge-data`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,  // ✅ JWT uniquement, pas de clé hardcodée
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to purge data' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error purging data:', error);
    return NextResponse.json(
      { error: 'Failed to purge data' },
      { status: 500 }
    );
  }
}
