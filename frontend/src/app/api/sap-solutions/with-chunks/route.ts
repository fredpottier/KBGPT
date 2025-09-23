import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const extendSearch = searchParams.get('extend_search') === 'true';

    const response = await fetch(`http://app:8000/api/sap-solutions/with-chunks?extend_search=${extendSearch}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = await response.text();
      return NextResponse.json(
        { error: `Erreur backend: ${errorData}` },
        { status: response.status }
      );
    }

    const result = await response.json();
    return NextResponse.json(result);

  } catch (error) {
    console.error('Erreur récupération solutions SAP avec chunks:', error);
    return NextResponse.json(
      { error: 'Erreur interne du serveur' },
      { status: 500 }
    );
  }
}