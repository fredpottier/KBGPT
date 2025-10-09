import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(request: NextRequest) {
  try {
    const url = `${BACKEND_URL}/api/imports/sync`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to sync imports' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error syncing imports:', error);
    return NextResponse.json(
      { error: 'Failed to sync imports' },
      { status: 500 }
    );
  }
}
