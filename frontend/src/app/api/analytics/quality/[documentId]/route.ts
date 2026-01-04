import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = 'http://app:8000'

export async function GET(
  request: NextRequest,
  { params }: { params: { documentId: string } }
) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const response = await fetch(
      `${BACKEND_URL}/api/analytics/quality/${encodeURIComponent(params.documentId)}`,
      {
        method: 'GET',
        headers: {
          'Authorization': authHeader,
          'Content-Type': 'application/json',
        },
      }
    )

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend error: ${response.status}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Document quality proxy error:', error)
    return NextResponse.json(
      { error: 'Failed to proxy request to backend' },
      { status: 500 }
    )
  }
}
