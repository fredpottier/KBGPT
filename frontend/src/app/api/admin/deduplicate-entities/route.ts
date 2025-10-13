import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

// Désactiver le cache Next.js
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function POST(request: NextRequest) {
  try {
    // Forward JWT token from client to backend
    const authHeader = request.headers.get('Authorization');
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Missing authorization token' },
        { status: 401 }
      );
    }

    // Parse request body
    const body = await request.json();
    const dry_run = body.dry_run || false;

    const url = `${BACKEND_URL}/api/admin/deduplicate-entities?dry_run=${dry_run}`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to deduplicate entities' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error deduplicating entities:', error);
    return NextResponse.json(
      { error: 'Failed to deduplicate entities' },
      { status: 500 }
    );
  }
}
