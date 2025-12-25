/**
 * Hooks Domain - Logique métier
 *
 * Ces hooks encapsulent la logique métier de l'application.
 * Ils sont découplés de la présentation et peuvent être réutilisés
 * avec n'importe quel système de theming.
 */

export { useSearch } from './useSearch'
export type {
  SearchResult,
  SearchSynthesis,
  SearchResponse,
  SearchParams,
  UseSearchOptions,
  UseSearchReturn,
} from './useSearch'
