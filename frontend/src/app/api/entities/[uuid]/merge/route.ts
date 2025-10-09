import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000';

export async function POST(
  request: NextRequest,
  { params }: { params: { uuid: string } }
) {
  try {
    const { uuid } = params;
    const body = await request.json();
    const { target_uuid, canonical_name } = body;

    if (!target_uuid) {
      return NextResponse.json(
        { error: 'target_uuid is required' },
        { status: 400 }
      );
    }

    const url = `${BACKEND_URL}/api/entities/${encodeURIComponent(uuid)}/merge`;

    // Construire le payload en omettant canonical_name s'il est vide
    const innerPayload: any = { target_uuid };
    if (canonical_name) {
      innerPayload.canonical_name = canonical_name;
    }

    // FastAPI attend le format imbriqué : { "merge_entities_request": {...} }
    const payload = {
      merge_entities_request: innerPayload
    };

    console.log('Merge request:', { uuid, payload, url });

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Key': 'admin-dev-key-change-in-production',
        'X-Tenant-ID': 'default',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      console.error('Backend merge error:', {
        status: response.status,
        errorData,
        requestBody: { target_uuid, canonical_name },
        url
      });
      return NextResponse.json(
        {
          error: errorData.detail || errorData.message || 'Failed to merge entities',
          detail: errorData.detail,
          validation_errors: errorData
        },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error merging entities:', error);
    return NextResponse.json(
      { error: 'Failed to merge entities' },
      { status: 500 }
    );
  }
}
