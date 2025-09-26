import { NextResponse } from 'next/server'

export async function GET() {
  try {
    const response = await fetch('http://app:8000/solutions', {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      cache: 'no-store',
    })

    if (!response.ok) {
      const errorText = await response.text()
      return NextResponse.json(
        { error: `Backend error: ${errorText}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Erreur récupération solutions:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}
