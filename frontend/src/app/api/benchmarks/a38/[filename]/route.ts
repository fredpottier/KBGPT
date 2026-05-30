import { NextRequest, NextResponse } from 'next/server'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://app:8000'

export async function GET(
  _req: NextRequest,
  { params }: { params: { filename: string } },
) {
  try {
    const resp = await fetch(
      `${API_BASE}/api/benchmarks/a38/${encodeURIComponent(params.filename)}`,
      { headers: { 'Content-Type': 'application/json' }, cache: 'no-store' },
    )
    if (!resp.ok) {
      return NextResponse.json({ error: `Backend returned ${resp.status}` }, { status: resp.status })
    }
    const data = await resp.json()
    return NextResponse.json(data)
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}
