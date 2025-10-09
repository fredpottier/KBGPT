import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function PATCH(
  request: NextRequest,
  { params }: { params: { uuid: string } }
) {
  try {
    const uuid = params.uuid;
    const body = await request.json();
    const url = `${BACKEND_URL}/api/entities/${uuid}/change-type`;

    // Extraire admin_key du body
    const { admin_key, ...backendBody } = body;

    const response = await fetch(url, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': admin_key || 'admin-dev-key-change-in-production',
      },
      body: JSON.stringify(backendBody),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to change entity type' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error changing entity type:', error);
    return NextResponse.json(
      { error: 'Failed to change entity type' },
      { status: 500 }
    );
  }
}
