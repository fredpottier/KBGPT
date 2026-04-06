import { NextRequest, NextResponse } from 'next/server'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://app:8000'

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url)
    const a = searchParams.get('a') || ''
    const b = searchParams.get('b') || ''
    const resp = await fetch(`${API_BASE}/api/benchmarks/ragas/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`, {
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    })
    if (!resp.ok) {
      const text = await resp.text()
      return NextResponse.json({ error: text }, { status: resp.status })
    }
    const data = await resp.json()
    return NextResponse.json(data)
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}
