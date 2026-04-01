import { NextResponse } from 'next/server'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://app:8000'

export async function GET() {
  try {
    const resp = await fetch(`${API_BASE}/api/benchmarks/robustness`, {
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
    })
    if (!resp.ok) return NextResponse.json({ reports: [] })
    return NextResponse.json(await resp.json())
  } catch (error) {
    return NextResponse.json({ reports: [], error: String(error) })
  }
}
