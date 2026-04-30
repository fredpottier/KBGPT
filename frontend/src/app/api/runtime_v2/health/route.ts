import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000'

export async function GET(request: NextRequest) {
  const authResult = verifyJWT(request)
  if (authResult instanceof NextResponse) {
    return authResult
  }
  try {
    const response = await fetch(`${BACKEND_URL}/api/runtime_v2/health`, {
      headers: { 'Authorization': authResult },
    })
    return NextResponse.json(await response.json(), { status: response.status })
  } catch (error) {
    return NextResponse.json({ error: 'Backend unreachable' }, { status: 500 })
  }
}
