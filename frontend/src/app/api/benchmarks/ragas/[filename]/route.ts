import { NextRequest, NextResponse } from 'next/server'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://app:8000'

export async function GET(req: NextRequest, { params }: { params: Promise<{ filename: string }> }) {
  const { filename } = await params
  try {
    const resp = await fetch(`${API_BASE}/api/benchmarks/ragas/${encodeURIComponent(filename)}`, {
      cache: 'no-store',
    })
    if (!resp.ok) return NextResponse.json({ error: `Backend ${resp.status}` }, { status: resp.status })
    return NextResponse.json(await resp.json())
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ filename: string }> }) {
  const { filename } = await params
  try {
    const resp = await fetch(`${API_BASE}/api/benchmarks/ragas/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    })
    if (!resp.ok) return NextResponse.json({ error: `Backend ${resp.status}` }, { status: resp.status })
    return NextResponse.json(await resp.json())
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}
