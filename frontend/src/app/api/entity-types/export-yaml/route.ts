import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;
    const queryString = searchParams.toString();
    const url = `${BACKEND_URL}/api/entity-types/export-yaml${queryString ? `?${queryString}` : ''}`;

    const response = await fetch(url);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to export YAML' },
        { status: response.status }
      );
    }

    // Return the YAML file as a stream
    const blob = await response.blob();
    return new NextResponse(blob, {
      status: 200,
      headers: {
        'Content-Type': 'application/x-yaml',
        'Content-Disposition': response.headers.get('Content-Disposition') || 'attachment; filename="entity_types_export.yaml"',
      },
    });
  } catch (error) {
    console.error('Error exporting YAML:', error);
    return NextResponse.json(
      { error: 'Failed to export YAML' },
      { status: 500 }
    );
  }
}
