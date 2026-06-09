'use client'

/**
 * SourceViewer — viewer PDF IN-APP avec surlignage du span source (Phase C, 09/06/2026).
 *
 * ⚠️ MODULE AUTONOME ET SUPPRIMABLE. Aucune dépendance npm ajoutée : pdf.js est
 * chargé à la volée depuis un CDN (import ESM runtime, `webpackIgnore`). Pour
 * retirer toute la fonctionnalité : supprimer ce dossier `source-viewer/` + le
 * bloc balisé `// [SOURCE_VIEWER]` dans RuntimeA3Panel.tsx. Rien d'autre à toucher
 * (les champs backend `source_verbatim_quote`/dates sont additifs et inoffensifs).
 *
 * Rendu : récupère le PDF via /api/documents/source-file?doc_id=… (fetch authentifié,
 * même endpoint que openSourceFile), rend la page cible sur un <canvas>, puis
 * superpose des rectangles de surlignage sur les fragments de texte qui matchent
 * la citation verbatim. Fail-soft total : toute erreur → message + bouton de repli
 * « ouvrir dans un onglet » (openSourceFile natif).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box, Flex, HStack, IconButton, Modal, ModalBody, ModalCloseButton,
  ModalContent, ModalHeader, ModalOverlay, Spinner, Text, Tooltip,
} from '@chakra-ui/react'
import { FiChevronLeft, FiChevronRight, FiExternalLink, FiZoomIn, FiZoomOut } from 'react-icons/fi'

// Version pdf.js pinée (ESM + worker depuis le même CDN). Mettre à jour ensemble.
const PDFJS_VERSION = '4.7.76'
const PDFJS_ESM = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.min.mjs`
const PDFJS_WORKER = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.worker.min.mjs`

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface SourceViewerTarget {
  docId: string
  page?: number | null
  quote?: string | null
  docTitle?: string | null
}

// Cache du module pdf.js (chargé une seule fois pour toute la session).
// Import masqué via `new Function` : garantit que le bundler (webpack/Next) ne
// tente PAS de résoudre l'URL CDN au build — l'import est purement runtime navigateur.
const _dynamicImport: (url: string) => Promise<any> = new Function(
  'url', 'return import(url)',
) as any
let _pdfjsPromise: Promise<any> | null = null
async function loadPdfjs(): Promise<any> {
  if (!_pdfjsPromise) {
    _pdfjsPromise = _dynamicImport(PDFJS_ESM).then((m: any) => {
      const lib = m.default ?? m
      lib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER
      return lib
    })
  }
  return _pdfjsPromise
}

function normalize(s: string): string {
  return (s || '')
    .toLowerCase()
    .replace(/[‘’ʼ`´]/g, "'") // apostrophes typographiques → '
    .replace(/[“”]/g, '"')                   // guillemets courbes → "
    .replace(/\s+/g, ' ')
    .trim()
}

export default function SourceViewer({
  target,
  onClose,
}: {
  target: SourceViewerTarget | null
  onClose: () => void
}) {
  const isOpen = !!target
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const overlayRef = useRef<HTMLDivElement | null>(null)
  const docRef = useRef<any>(null)
  const bufRef = useRef<ArrayBuffer | null>(null)
  const [pageNum, setPageNum] = useState(1)
  const [numPages, setNumPages] = useState(0)
  const [scale, setScale] = useState(1.3)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nHighlights, setNHighlights] = useState(0)
  const [matchMode, setMatchMode] = useState<'exact' | 'approx' | 'none'>('none')

  const openInTab = useCallback(async () => {
    if (!target) return
    const { openSourceFile } = await import('@/lib/openSourceFile')
    await openSourceFile(target.docId, target.page ?? undefined)
  }, [target])

  // Chargement du document à l'ouverture.
  useEffect(() => {
    if (!isOpen || !target) return
    let cancelled = false
    setError(null)
    setLoading(true)
    setNumPages(0)
    docRef.current = null
    bufRef.current = null
    ;(async () => {
      try {
        const pdfjs = await loadPdfjs()
        const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
        const res = await fetch(
          `${API_BASE_URL}/api/documents/source-file?doc_id=${encodeURIComponent(target.docId)}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
        )
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const blob = await res.blob()
        if (blob.type && blob.type !== 'application/pdf') {
          throw new Error('not_pdf') // Office/autre → repli onglet
        }
        const buf = await blob.arrayBuffer()
        if (cancelled) return
        bufRef.current = buf
        // getDocument consomme le buffer → copie défensive par page (slice).
        const doc = await pdfjs.getDocument({ data: buf.slice(0) }).promise
        if (cancelled) return
        docRef.current = doc
        setNumPages(doc.numPages)
        setPageNum(Math.min(Math.max(1, target.page || 1), doc.numPages))
      } catch (e) {
        if (!cancelled) setError((e as Error).message === 'not_pdf'
          ? "Aperçu in-app indisponible pour ce format (non-PDF)."
          : "Impossible de charger le PDF in-app.")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [isOpen, target])

  // Rendu de la page courante + surlignage.
  useEffect(() => {
    const doc = docRef.current
    if (!doc || !isOpen || error) return
    let cancelled = false
    ;(async () => {
      try {
        const pdfjs = await loadPdfjs()
        const page = await doc.getPage(pageNum)
        const viewport = page.getViewport({ scale })
        const canvas = canvasRef.current
        const overlay = overlayRef.current
        if (!canvas || !overlay) return
        const ctx = canvas.getContext('2d')!
        canvas.width = viewport.width
        canvas.height = viewport.height
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`
        overlay.style.width = `${viewport.width}px`
        overlay.style.height = `${viewport.height}px`
        await page.render({ canvasContext: ctx, viewport }).promise
        if (cancelled) return

        // Surlignage en 2 niveaux (jamais de tokens épars) :
        //  (1) match EXACT de la citation comme sous-chaîne contiguë → span précis ;
        //  (2) sinon « meilleure fenêtre contiguë » par recouvrement des mots
        //      significatifs (tolère OCR/garbles via préfixes) → on surligne la ZONE
        //      la plus probable. Si recouvrement trop faible → rien (honnête).
        overlay.innerHTML = ''
        let hits = 0
        let mode: 'exact' | 'approx' | 'none' = 'none'
        const quote = target?.quote || ''
        if (quote) {
          const tc = await page.getTextContent()
          let concat = ''
          const ranges: { start: number; end: number; item: any; words: string[] }[] = []
          for (const item of tc.items as any[]) {
            const ns = normalize(item.str || '')
            if (!ns) continue
            const start = concat.length
            concat += ns
            ranges.push({ start, end: concat.length, item, words: ns.split(' ') })
            concat += ' '
          }
          const draw = (item: any) => {
            const tx = pdfjs.Util.transform(viewport.transform, item.transform)
            const fontH = Math.hypot(tx[2], tx[3]) || 10
            const w = (item.width || 0) * scale
            const mark = document.createElement('div')
            mark.style.cssText =
              `position:absolute;left:${tx[4]}px;top:${tx[5] - fontH}px;width:${w}px;` +
              `height:${fontH * 1.15}px;background:rgba(255,213,0,0.42);` +
              `border-radius:2px;pointer-events:none;mix-blend-mode:multiply;`
            overlay.appendChild(mark)
            hits++
          }
          // (1) exact contigu
          let nq = normalize(quote)
          let mStart = concat.indexOf(nq)
          if (mStart < 0) {
            const stripped = nq.replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, '')
            if (stripped && stripped !== nq) {
              const k = concat.indexOf(stripped)
              if (k >= 0) { mStart = k; nq = stripped }
            }
          }
          if (mStart >= 0) {
            const mEnd = mStart + nq.length
            for (const r of ranges) if (!(r.end <= mStart || r.start >= mEnd)) draw(r.item)
            mode = 'exact'
          } else {
            // (2) meilleure fenêtre contiguë par recouvrement de tokens significatifs
            const sig = Array.from(new Set(
              nq.split(/[^a-z0-9]+/).filter((t) => t.length >= 4 || /\d/.test(t)),
            ))
            const covers = (w: string, t: string) =>
              w === t || (Math.min(w.length, t.length) >= 4 && (w.startsWith(t) || t.startsWith(w)))
            const win = Math.max(nq.length, 40)
            let best = { score: -1, i: 0, j: 0 }
            for (let i = 0; i < ranges.length; i++) {
              let j = i
              while (j < ranges.length && ranges[j].end - ranges[i].start < win) j++
              const cov = new Set<string>()
              for (let k = i; k < j; k++)
                for (const w of ranges[k].words)
                  for (const t of sig) if (covers(w, t)) cov.add(t)
              if (cov.size > best.score) best = { score: cov.size, i, j }
            }
            const need = Math.max(2, Math.ceil(sig.length * 0.34))
            if (sig.length > 0 && best.score >= need) {
              for (let k = best.i; k < best.j; k++) draw(ranges[k].item)
              mode = 'approx'
            }
          }
        }
        if (!cancelled) { setNHighlights(hits); setMatchMode(mode) }
      } catch {
        /* rendu best-effort : on n'efface pas la modale sur échec d'une page */
      }
    })()
    return () => { cancelled = true }
  }, [pageNum, scale, isOpen, error, target])

  const title = target?.docTitle || target?.docId || 'Document source'

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="6xl" scrollBehavior="inside" isCentered>
      <ModalOverlay />
      <ModalContent maxH="92vh" bg="bg.surface">
        <ModalHeader fontSize="sm" pr={12}>
          <Flex align="center" justify="space-between" gap={3} wrap="wrap">
            <Text noOfLines={1} title={title}>{title}</Text>
            <HStack spacing={1}>
              <Tooltip label="Page précédente"><IconButton aria-label="prev" size="xs" icon={<FiChevronLeft />} isDisabled={pageNum <= 1} onClick={() => setPageNum((p) => Math.max(1, p - 1))} /></Tooltip>
              <Text fontSize="xs" minW="64px" textAlign="center">{numPages ? `${pageNum} / ${numPages}` : '—'}</Text>
              <Tooltip label="Page suivante"><IconButton aria-label="next" size="xs" icon={<FiChevronRight />} isDisabled={!numPages || pageNum >= numPages} onClick={() => setPageNum((p) => Math.min(numPages, p + 1))} /></Tooltip>
              <Box w="1px" h="16px" bg="border.subtle" mx={1} />
              <Tooltip label="Dézoomer"><IconButton aria-label="zoom out" size="xs" icon={<FiZoomOut />} onClick={() => setScale((s) => Math.max(0.6, +(s - 0.2).toFixed(2)))} /></Tooltip>
              <Tooltip label="Zoomer"><IconButton aria-label="zoom in" size="xs" icon={<FiZoomIn />} onClick={() => setScale((s) => Math.min(3, +(s + 0.2).toFixed(2)))} /></Tooltip>
              <Tooltip label="Ouvrir dans un onglet"><IconButton aria-label="open tab" size="xs" icon={<FiExternalLink />} onClick={openInTab} /></Tooltip>
            </HStack>
          </Flex>
          {target?.quote ? (
            <Text fontSize="11px" color="text.secondary" fontWeight="normal" mt={1} noOfLines={2}>
              Span recherché : « {target.quote} » {matchMode === 'exact'
                ? '· span surligné'
                : matchMode === 'approx'
                ? '· zone la plus probable surlignée (citation source approximative)'
                : '· non localisé sur cette page'}
            </Text>
          ) : null}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody bg="bg.canvas" display="flex" justifyContent="center" py={4}>
          {loading ? (
            <Flex direction="column" align="center" gap={3} py={10}><Spinner /><Text fontSize="sm" color="text.secondary">Chargement du PDF…</Text></Flex>
          ) : error ? (
            <Flex direction="column" align="center" gap={3} py={10}>
              <Text fontSize="sm" color="text.secondary">{error}</Text>
              <Text as="button" fontSize="sm" color="brand.300" textDecoration="underline" onClick={openInTab}>Ouvrir le document dans un onglet ↗</Text>
            </Flex>
          ) : (
            <Box position="relative" display="inline-block">
              <canvas ref={canvasRef} style={{ display: 'block' }} />
              <Box ref={overlayRef} position="absolute" top={0} left={0} pointerEvents="none" />
            </Box>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}
