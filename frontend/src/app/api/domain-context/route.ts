import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/domain-context`, {
      headers: {
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Error fetching domain context:', error);
    return NextResponse.json(
      { detail: 'Erreur de connexion au serveur' },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const response = await fetch(`${BACKEND_URL}/api/domain-context`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Error creating domain context:', error);
    return NextResponse.json(
      { detail: 'Erreur de connexion au serveur' },
      { status: 500 }
    );
  }
}

export async function DELETE() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/domain-context`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Error deleting domain context:', error);
    return NextResponse.json(
      { detail: 'Erreur de connexion au serveur' },
      { status: 500 }
    );
  }
}
