import { NextRequest, NextResponse } from 'next/server'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://app:8000'

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData()

    const resp = await fetch(`${API_BASE}/api/verify/upload-docx`, {
      method: 'POST',
      body: formData,
    })

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}))
      return NextResponse.json(
        { detail: errData.detail || `Backend returned ${resp.status}` },
        { status: resp.status }
      )
    }

    // Forward the binary response (docx file)
    const blob = await resp.arrayBuffer()

    return new NextResponse(blob, {
      status: 200,
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'Content-Disposition': resp.headers.get('Content-Disposition') || 'attachment; filename="osmosis_review.docx"',
        'X-Osmosis-Reliability': resp.headers.get('X-Osmosis-Reliability') || '',
        'X-Osmosis-Contradicted': resp.headers.get('X-Osmosis-Contradicted') || '',
        'X-Osmosis-Confirmed': resp.headers.get('X-Osmosis-Confirmed') || '',
      },
    })

  } catch (error) {
    return NextResponse.json({ detail: String(error) }, { status: 500 })
  }
}
