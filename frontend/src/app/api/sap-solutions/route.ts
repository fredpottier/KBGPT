import { NextRequest, NextResponse } from 'next/server';
import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

export async function GET(request: NextRequest) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const response = await fetch('http://app:8000/api/sap-solutions', {
      method: 'GET',
      headers: {
        'Authorization': authHeader,
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
    console.error('Erreur récupération solutions SAP:', error);
    return NextResponse.json(
      { error: 'Erreur interne du serveur' },
      { status: 500 }
    );
  }
}