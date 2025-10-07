import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const url = `${BACKEND_URL}/api/document-types/analyze-sample`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error analyzing document:', error);
    return NextResponse.json(
      { error: 'Failed to analyze document' },
      { status: 500 }
    );
  }
}
