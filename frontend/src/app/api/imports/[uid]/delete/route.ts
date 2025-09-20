import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://app:8000'

export async function DELETE(
  request: NextRequest,
  { params }: { params: { uid: string } }
) {
  try {
    const response = await fetch(`${BACKEND_URL}/imports/${params.uid}/delete`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      return NextResponse.json(
        { error: errorData.error || `Backend error: ${response.status}` },
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