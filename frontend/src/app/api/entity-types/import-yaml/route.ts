import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const url = `${BACKEND_URL}/api/entity-types/import-yaml`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Admin-Key': request.headers.get('X-Admin-Key') || 'admin-dev-key-change-in-production',
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to import YAML' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error importing YAML:', error);
    return NextResponse.json(
      { error: 'Failed to import YAML' },
      { status: 500 }
    );
  }
}
