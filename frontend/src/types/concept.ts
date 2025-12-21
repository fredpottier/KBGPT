/**
 * Types pour les Concepts - Phase 3.5 Explainable Graph-RAG
 */

import { ConceptType, RelationType } from './graph';

/**
 * Référence à une source documentaire
 */
export interface SourceReference {
  documentId: string;
  documentName: string;
  documentType: 'PDF' | 'PPTX' | 'DOCX' | 'XLSX' | 'TXT' | 'OTHER';
  pages?: string;
  slideNumber?: number;
  excerpt: string;
  confidence: number;
  mentionCount: number;
}

/**
 * Relation d'un concept vers un autre
 */
export interface ConceptRelation {
  targetId: string;
  targetName: string;
  relationType: RelationType;
  direction: 'incoming' | 'outgoing' | 'bidirectional';
  confidence: number;
  evidence?: string;
}

/**
 * Événement dans la timeline d'un concept
 */
export interface TimelineEvent {
  date: string;
  event: string;
  document?: string;
  changeType?: 'added' | 'modified' | 'deprecated' | 'removed';
}

/**
 * Carte d'identité complète d'un concept (pour le panel slide-in)
 */
export interface ConceptCard {
  // Identité
  id: string;
  canonicalName: string;
  fullName?: string;
  aliases: string[];
  type: ConceptType;

  // Qualité
  confidence: number;
  mentionCount: number;
  documentCount: number;

  // Définition
  definition: {
    text: string;
    sourceCount: number;
    consensusScore: number;
  };

  // Relations
  relations: ConceptRelation[];

  // Sources
  sources: SourceReference[];

  // Évolution temporelle
  timeline?: TimelineEvent[];

  // Suggestions
  suggestedQuestions: string[];
}

/**
 * Résumé d'un concept (pour tooltips et badges)
 */
export interface ConceptSummary {
  id: string;
  name: string;
  type: ConceptType;
  confidence: number;
  mentionCount: number;
  documentCount: number;
  shortDefinition?: string;
  relationCount: number;
}

/**
 * Props pour le panel carte concept
 */
export interface ConceptCardPanelProps {
  conceptId: string | null;
  isOpen: boolean;
  onClose: () => void;
  onConceptClick: (conceptId: string) => void;
  onQuestionClick: (question: string) => void;
}

/**
 * Props pour la section définition
 */
export interface ConceptDefinitionProps {
  definition: ConceptCard['definition'];
}

/**
 * Props pour la section relations
 */
export interface ConceptRelationsProps {
  relations: ConceptRelation[];
  onConceptClick: (conceptId: string) => void;
}

/**
 * Props pour la section sources
 */
export interface ConceptSourcesProps {
  sources: SourceReference[];
  onSourceClick: (sourceId: string) => void;
  maxVisible?: number;
}

/**
 * Props pour la section timeline
 */
export interface ConceptTimelineProps {
  timeline: TimelineEvent[];
}

/**
 * Props pour les questions suggérées
 */
export interface ConceptSuggestionsProps {
  questions: string[];
  onQuestionClick: (question: string) => void;
}

/**
 * Labels pour les types de relations (affichage UI)
 */
export const RELATION_TYPE_LABELS: Record<RelationType, string> = {
  PART_OF: 'Fait partie de',
  SUBTYPE_OF: 'Type de',
  REQUIRES: 'Requiert',
  USES: 'Utilise',
  INTEGRATES_WITH: 'S\'intègre avec',
  EXTENDS: 'Étend',
  ENABLES: 'Permet',
  VERSION_OF: 'Version de',
  PRECEDES: 'Précède',
  REPLACES: 'Remplace',
  DEPRECATES: 'Déprécie',
  ALTERNATIVE_TO: 'Alternative à',
  RELATED_TO: 'Lié à',
};

/**
 * Labels pour les types de concepts (affichage UI)
 */
export const CONCEPT_TYPE_LABELS: Record<ConceptType, string> = {
  PRODUCT: 'Produit',
  SERVICE: 'Service',
  TECHNOLOGY: 'Technologie',
  PRACTICE: 'Pratique',
  ORGANIZATION: 'Organisation',
  PERSON: 'Personne',
  LOCATION: 'Lieu',
  EVENT: 'Événement',
  CONCEPT: 'Concept',
  UNKNOWN: 'Inconnu',
};

/**
 * Couleurs pour les types de concepts
 */
export const CONCEPT_TYPE_COLORS: Record<ConceptType, string> = {
  PRODUCT: 'blue',
  SERVICE: 'green',
  TECHNOLOGY: 'purple',
  PRACTICE: 'orange',
  ORGANIZATION: 'cyan',
  PERSON: 'pink',
  LOCATION: 'yellow',
  EVENT: 'red',
  CONCEPT: 'gray',
  UNKNOWN: 'gray',
};
