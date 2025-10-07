import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function DELETE(
  request: NextRequest,
  { params }: { params: { id: string; entityType: string } }
) {
  try {
    const url = `${BACKEND_URL}/api/document-types/${params.id}/entity-types/${params.entityType}`;

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
    console.error('Error removing entity type:', error);
    return NextResponse.json(
      { error: 'Failed to remove entity type' },
      { status: 500 }
    );
  }
}
