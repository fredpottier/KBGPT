import { NextRequest, NextResponse } from 'next/server';
import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(
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
    const body = await request.json();
    const url = `${BACKEND_URL}/api/entity-types/${typeName}/reject`;

    // Extraire admin_key du body
    const { admin_key, ...backendBody } = body;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
        'X-Admin-Key': admin_key || 'admin-dev-key-change-in-production',
      },
      body: JSON.stringify(backendBody),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to reject entity type' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error rejecting entity type:', error);
    return NextResponse.json(
      { error: 'Failed to reject entity type' },
      { status: 500 }
    );
  }
}
