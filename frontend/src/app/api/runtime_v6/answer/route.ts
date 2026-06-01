import { NextRequest, NextResponse } from 'next/server'
import { verifyJWT } from '@/lib/jwt-helpers'

const BACKEND_URL = process.env.BACKEND_URL || 'http://app:8000'

// runtime_a3 (answering KG-first) peut prendre jusqu'à ~5 min sur les questions
// difficiles (synthèse Novita, gros prompts). On laisse une marge large : le chat
// privilégie une réponse FIABLE et TRACÉE à une réponse rapide mais fausse.
export const maxDuration = 320

export async function POST(request: NextRequest) {
  const authResult = verifyJWT(request)
  if (authResult instanceof NextResponse) {
    return authResult
  }
  const authHeader = authResult

  try {
    const body = await request.json()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 310_000)
    const response = await fetch(`${BACKEND_URL}/api/runtime_v6/answer`, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    clearTimeout(timeout)
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      return NextResponse.json(
        { error: errorData.detail || 'runtime_a3 (answering) error' },
        { status: response.status }
      )
    }
    return NextResponse.json(await response.json())
  } catch (error) {
    console.error('runtime_a3 answer error:', error)
    return NextResponse.json(
      { error: 'Failed to call runtime_a3 (answering)' },
      { status: 500 }
    )
  }
}
