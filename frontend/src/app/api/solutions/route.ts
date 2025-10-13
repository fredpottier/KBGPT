import { verifyJWT, createAuthHeaders } from '@/lib/jwt-helpers'

﻿import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  // Verifier JWT token
  const authResult = verifyJWT(request);
  if (authResult instanceof NextResponse) {
    return authResult;
  }
  const authHeader = authResult;

  try {
    const response = await fetch('http://app:8000/solutions', {
      method: 'GET',
      headers: {
        'Authorization': authHeader,
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
