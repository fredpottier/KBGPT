import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(
  request: NextRequest,
  { params }: { params: { typeName: string } }
) {
  try {
    const { typeName } = params;

    // Récupérer query params (include_validated, model_preference)
    const searchParams = request.nextUrl.searchParams;
    const includeValidated = searchParams.get('include_validated') || 'false';
    const modelPreference = searchParams.get('model_preference') || 'claude-sonnet';

    const url = `${BACKEND_URL}/api/entity-types/${encodeURIComponent(typeName)}/generate-ontology?include_validated=${includeValidated}&model_preference=${modelPreference}`;

    const response = await fetch(url, {
      method: 'POST',
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
    console.error('Error generating ontology:', error);
    return NextResponse.json(
      { error: 'Failed to generate ontology' },
      { status: 500 }
    );
  }
}
