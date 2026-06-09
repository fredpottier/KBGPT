/**
 * source-viewer — point d'entrée du module autonome (Phase C).
 *
 * Flag d'activation : mettre SOURCE_VIEWER_ENABLED à false pour repasser au
 * comportement historique (openSourceFile → onglet natif) SANS rien supprimer.
 * Suppression complète : effacer ce dossier + le bloc `// [SOURCE_VIEWER]` dans
 * RuntimeA3Panel.tsx.
 */
export { default as SourceViewer } from './SourceViewer'
export type { SourceViewerTarget } from './SourceViewer'

// Activable/désactivable d'un seul endroit. (Volontairement une constante simple
// plutôt qu'une var d'env NEXT_PUBLIC_ inlined au build → flip à chaud en dev.)
export const SOURCE_VIEWER_ENABLED = true
