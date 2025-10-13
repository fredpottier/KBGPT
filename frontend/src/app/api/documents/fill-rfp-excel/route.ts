import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    // ✅ Récupérer le JWT token depuis les headers
    const authHeader = request.headers.get('Authorization');
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Missing authorization token' },
        { status: 401 }
      );
    }

    const formData = await request.formData();
    const file = formData.get('file') as File;
    const metadataStr = formData.get('metadata') as string;

    if (!file) {
      return NextResponse.json(
        { error: 'Aucun fichier fourni' },
        { status: 400 }
      );
    }

    if (!metadataStr) {
      return NextResponse.json(
        { error: 'Métadonnées manquantes' },
        { status: 400 }
      );
    }

    const metadata = JSON.parse(metadataStr);

    // Créer un FormData pour l'API backend
    const backendFormData = new FormData();
    backendFormData.append('file', file);

    // Créer le fichier .meta.json comme Blob (compatible Node.js)
    const metaBlob = new Blob([JSON.stringify(metadata, null, 2)], {
      type: 'application/json'
    });
    backendFormData.append('meta_file', metaBlob, `${file.name}.meta.json`);

    // Envoyer vers l'API backend avec JWT
    const response = await fetch('http://app:8000/documents/fill-excel-rfp', {
      method: 'POST',
      headers: {
        'Authorization': authHeader,  // ✅ Transmettre JWT au backend
      },
      body: backendFormData,
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
    console.error('Erreur fill RFP Excel:', error);
    return NextResponse.json(
      { error: 'Erreur interne du serveur' },
      { status: 500 }
    );
  }
}