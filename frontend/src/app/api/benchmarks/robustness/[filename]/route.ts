import { NextRequest, NextResponse } from 'next/server'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://app:8000'

export async function GET(_req: NextRequest, { params }: { params: { filename: string } }) {
  try {
    const resp = await fetch(`${API_BASE}/api/benchmarks/robustness/${params.filename}`, {
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    })
    if (!resp.ok) return NextResponse.json({ error: 'Not found' }, { status: 404 })
    return NextResponse.json(await resp.json())
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}

export async function DELETE(_req: NextRequest, { params }: { params: { filename: string } }) {
  try {
    const resp = await fetch(`${API_BASE}/api/benchmarks/robustness/${params.filename}`, {
      method: 'DELETE',
    })
    return NextResponse.json(await resp.json(), { status: resp.status })
  } catch (error) {
    return NextResponse.json({ error: String(error) }, { status: 500 })
  }
}
