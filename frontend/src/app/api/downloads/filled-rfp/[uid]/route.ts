import { NextRequest, NextResponse } from 'next/server';

interface DownloadParams {
  params: {
    uid: string;
  };
}

export async function GET(request: NextRequest, { params }: DownloadParams) {
  try {
    const { uid } = params;

    if (!uid) {
      return NextResponse.json(
        { error: 'UID requis' },
        { status: 400 }
      );
    }

    // Proxy vers l'API backend
    const response = await fetch(`http://app:8000/api/downloads/filled-rfp/${uid}`, {
      method: 'GET',
    });

    if (!response.ok) {
      const errorData = await response.text();
      return NextResponse.json(
        { error: `Erreur backend: ${errorData}` },
        { status: response.status }
      );
    }

    // Récupérer les headers de fichier du backend
    const contentType = response.headers.get('content-type') || 'application/octet-stream';
    const contentDisposition = response.headers.get('content-disposition') || 'attachment';

    // Créer la réponse avec le stream du fichier
    const fileBuffer = await response.arrayBuffer();

    return new NextResponse(fileBuffer, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Disposition': contentDisposition,
        'Cache-Control': 'no-cache, no-store, must-revalidate',
      },
    });

  } catch (error) {
    console.error('Erreur téléchargement RFP complété:', error);
    return NextResponse.json(
      { error: 'Erreur interne du serveur' },
      { status: 500 }
    );
  }
}