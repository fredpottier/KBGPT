import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000'

export async function POST(request: NextRequest) {
  const authResult = verifyJWT(request)
  if (authResult instanceof NextResponse) {
    return authResult
  }
  const authHeader = authResult

  try {
    const body = await request.json()
    const response = await fetch(`${BACKEND_URL}/api/runtime_v2/answer`, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      return NextResponse.json(
        { error: errorData.detail || 'Pipeline V2 error' },
        { status: response.status }
      )
    }
    return NextResponse.json(await response.json())
  } catch (error) {
    console.error('Runtime V2 answer error:', error)
    return NextResponse.json(
      { error: 'Failed to call runtime V2' },
      { status: 500 }
    )
  }
}
