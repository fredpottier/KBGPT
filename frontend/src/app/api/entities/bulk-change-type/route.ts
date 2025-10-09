import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const url = `${BACKEND_URL}/api/entities/bulk-change-type`;

    // Extraire admin_key du body et ne pas l'envoyer au backend
    const { admin_key, ...backendBody } = body;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': admin_key || 'admin-dev-key-change-in-production',
        'X-Tenant-ID': 'default',
      },
      body: JSON.stringify(backendBody),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      console.error('Backend bulk change-type error:', {
        status: response.status,
        errorData,
      });
      return NextResponse.json(
        {
          error: errorData.detail || errorData.message || 'Failed to bulk change entity types',
          detail: errorData.detail
        },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error bulk changing entity types:', error);
    return NextResponse.json(
      { error: 'Failed to bulk change entity types' },
      { status: 500 }
    );
  }
}
