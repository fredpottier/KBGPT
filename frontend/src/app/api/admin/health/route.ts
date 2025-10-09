import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function GET() {
  try {
    const url = `${BACKEND_URL}/api/admin/health`;

    const response = await fetch(url, {
      headers: {
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to check health' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error checking health:', error);
    return NextResponse.json(
      { error: 'Failed to check health' },
      { status: 500 }
    );
  }
}
