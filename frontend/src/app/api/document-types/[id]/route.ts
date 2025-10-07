import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const url = `${BACKEND_URL}/api/document-types/${params.id}`;

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
    console.error('Error fetching document type:', error);
    return NextResponse.json(
      { error: 'Failed to fetch document type' },
      { status: 500 }
    );
  }
}

export async function PUT(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const body = await request.json();
    const url = `${BACKEND_URL}/api/document-types/${params.id}`;

    const response = await fetch(url, {
      method: 'PUT',
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
    console.error('Error updating document type:', error);
    return NextResponse.json(
      { error: 'Failed to update document type' },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const url = `${BACKEND_URL}/api/document-types/${params.id}`;

    const response = await fetch(url, {
      method: 'DELETE',
      headers: {
        'X-Admin-Key': 'admin-dev-key-change-in-production',
      },
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    return new NextResponse(null, { status: 204 });
  } catch (error) {
    console.error('Error deleting document type:', error);
    return NextResponse.json(
      { error: 'Failed to delete document type' },
      { status: 500 }
    );
  }
}
