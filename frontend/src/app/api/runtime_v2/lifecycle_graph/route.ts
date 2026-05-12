import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000'

export async function GET(request: NextRequest) {
  const authResult = verifyJWT(request)
  if (authResult instanceof NextResponse) return authResult
  try {
    const focus = request.nextUrl.searchParams.get('focus_doc_id') || ''
    const depth = request.nextUrl.searchParams.get('depth') || '1'
    const url = `${BACKEND_URL}/api/runtime_v2/lifecycle_graph?focus_doc_id=${encodeURIComponent(focus)}&depth=${encodeURIComponent(depth)}`
    const response = await fetch(url, { headers: { 'Authorization': authResult } })
    if (!response.ok) {
      const e = await response.json().catch(() => ({}))
      return NextResponse.json({ error: e.detail || 'Failed' }, { status: response.status })
    }
    return NextResponse.json(await response.json())
  } catch (error) {
    return NextResponse.json({ error: 'Backend unreachable' }, { status: 500 })
  }
}
