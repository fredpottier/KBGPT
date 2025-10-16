import { NextResponse } from 'next/server';
import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(
  request: Request,
  { params }: { params: { typeName: string; targetType: string } }
) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const { typeName, targetType } = params;

    const url = `${BACKEND_URL}/api/entity-types/${encodeURIComponent(typeName)}/merge-into/${encodeURIComponent(targetType)}`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error merging types:', error);
    return NextResponse.json(
      { error: 'Failed to merge types' },
      { status: 500 }
    );
  }
}
