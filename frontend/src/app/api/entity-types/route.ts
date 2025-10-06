import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function GET(request: NextRequest) {
  try {
    // Récupérer les query params (status, etc.)
    const searchParams = request.nextUrl.searchParams;
    const queryString = searchParams.toString();
    const url = queryString
      ? `${BACKEND_URL}/api/entity-types?${queryString}`
      : `${BACKEND_URL}/api/entity-types`;

    const response = await fetch(url, {
      headers: {
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching entity types:', error);
    return NextResponse.json(
      { error: 'Failed to fetch entity types' },
      { status: 500 }
    );
  }
}
