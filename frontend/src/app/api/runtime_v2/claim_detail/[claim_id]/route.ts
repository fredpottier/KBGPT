import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000'

export async function GET(
  request: NextRequest,
  { params }: { params: { claim_id: string } }
) {
  const authResult = verifyJWT(request)
  if (authResult instanceof NextResponse) return authResult
  try {
    const url = `${BACKEND_URL}/api/runtime_v2/claim_detail/${encodeURIComponent(params.claim_id)}`
    const response = await fetch(url, { headers: { 'Authorization': authResult } })
    if (!response.ok) {
      const e = await response.json().catch(() => ({}))
      return NextResponse.json({ error: e.detail || 'Not found' }, { status: response.status })
    }
    return NextResponse.json(await response.json())
  } catch (error) {
    return NextResponse.json({ error: 'Backend unreachable' }, { status: 500 })
  }
}
