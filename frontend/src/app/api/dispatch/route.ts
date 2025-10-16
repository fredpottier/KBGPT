import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://app:8000'

export async function POST(request: NextRequest) {
  try {
    // ✅ Récupérer le JWT token depuis les headers
    const authHeader = request.headers.get('Authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Missing authorization token' },
        { status: 401 }
      )
    }

    // Récupérer le FormData de la requête
    const formData = await request.formData()

    // Transférer le FormData au backend avec JWT
    const response = await fetch(`${BACKEND_URL}/dispatch`, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,  // ✅ Transmettre JWT au backend
      },
      body: formData, // FormData se gère automatiquement
    })

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend error: ${response.status}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Proxy error:', error)
    return NextResponse.json(
      { error: 'Failed to proxy request to backend' },
      { status: 500 }
    )
  }
}