import { NextResponse } from 'next/server';
import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(
  request: Request,
  { params }: { params: { typeName: string } }
) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const { typeName } = params;
    const body = await request.json();
    const snapshotId = body.snapshot_id;

    if (!snapshotId) {
      return NextResponse.json(
        { error: 'snapshot_id is required' },
        { status: 400 }
      );
    }

    const url = `${BACKEND_URL}/api/entity-types/${encodeURIComponent(typeName)}/undo-normalization/${encodeURIComponent(snapshotId)}`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
      body: JSON.stringify({}),
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error undoing normalization:', error);
    return NextResponse.json(
      { error: 'Failed to undo normalization' },
      { status: 500 }
    );
  }
}
