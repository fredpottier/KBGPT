import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = 'http://app:8000'

export async function GET(request: NextRequest) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const { searchParams } = new URL(request.url)
    const limit = searchParams.get('limit') || '50'

    const response = await fetch(`${BACKEND_URL}/api/analytics/imports?limit=${limit}`, {
      method: 'GET',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend error: ${response.status}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Analytics proxy error:', error)
    return NextResponse.json(
      { error: 'Failed to proxy request to backend' },
      { status: 500 }
    )
  }
}
