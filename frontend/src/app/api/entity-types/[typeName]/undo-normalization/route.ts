import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(
  request: Request,
  { params }: { params: { typeName: string } }
) {
  try {
    const { typeName } = params;
    const body = await request.json();

    const url = `${BACKEND_URL}/api/entity-types/${encodeURIComponent(typeName)}/undo-normalization`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
      body: JSON.stringify(body),
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
