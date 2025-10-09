import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST() {
  try {
    const url = `${BACKEND_URL}/api/admin/purge-data`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Admin-Key': 'admin-dev-key-change-in-production',
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to purge data' },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error purging data:', error);
    return NextResponse.json(
      { error: 'Failed to purge data' },
      { status: 500 }
    );
  }
}
