'use client'

/**
 * OSMOSE Domain Context - Dark Elegance Edition v2
 *
 * Premium business context configuration with Version & Axes,
 * Rules Engine, and enhanced Preview sections.
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  Box,
  Heading,
  Text,
  VStack,
  HStack,
  FormControl,
  FormLabel,
  FormHelperText,
  Input,
  Textarea,
  Select,
  Button,
  useToast,
  Spinner,
  Tag,
  TagLabel,
  TagCloseButton,
  Wrap,
  WrapItem,
  Code,
  Accordion,
  AccordionItem,
  AccordionButton,
  AccordionPanel,
  AccordionIcon,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
  Icon,
  Center,
  Checkbox,
  SimpleGrid,
  Badge,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  NumberIncrementStepper,
  NumberDecrementStepper,
  IconButton,
  Divider,
} from '@chakra-ui/react'
import { motion } from 'framer-motion'
import {
  FiSave,
  FiTrash2,
  FiEye,
  FiRefreshCw,
  FiGlobe,
  FiInfo,
  FiCheckCircle,
  FiAlertTriangle,
  FiZap,
  FiChevronDown,
  FiSettings,
  FiCode,
  FiPlus,
  FiMinus,
} from 'react-icons/fi'

const MotionBox = motion(Box)

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DomainContext {
  tenant_id: string
  domain_summary: string
  industry: string
  sub_domains: string[]
  target_users: string[]
  document_types: string[]
  common_acronyms: Record<string, string>
  key_concepts: string[]
  context_priority: 'low' | 'medium' | 'high'
  versioning_hints: string
  identification_semantics: string
  axis_reclassification_rules: string
  axis_policy: string
  llm_injection_prompt: string
  created_at: string
  updated_at: string
}

interface FormData {
  domain_summary: string
  industry: string
  sub_domains: string[]
  target_users: string[]
  document_types: string[]
  common_acronyms: Record<string, string>
  key_concepts: string[]
  context_priority: 'low' | 'medium' | 'high'
  versioning_hints: string
  identification_semantics: string
  axis_reclassification_rules: string
  axis_policy: string
}

interface AxisPolicyState {
  strip_prefixes: string[]
  canonicalization_enabled: boolean
  expected_axes: string[]
  excluded_axes: string[]
  strict_expected: boolean
  year_range: { min: number; max_relative: number }
  plausibility_overrides: Record<string, { reject_patterns?: string[]; accept_patterns?: string[] }>
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NEUTRAL_AXIS_KEYS = [
  { key: 'release_id', label: 'Release ID' },
  { key: 'version', label: 'Version' },
  { key: 'regulation_version', label: 'Regulation Version' },
  { key: 'model_generation', label: 'Model Generation' },
  { key: 'trial_phase', label: 'Trial Phase' },
  { key: 'year', label: 'Year' },
  { key: 'effective_date', label: 'Effective Date' },
  { key: 'edition', label: 'Edition' },
  { key: 'region', label: 'Region' },
  { key: 'phase', label: 'Phase' },
  { key: 'tier', label: 'Tier' },
]

const DEFAULT_AXIS_POLICY: AxisPolicyState = {
  strip_prefixes: [],
  canonicalization_enabled: true,
  expected_axes: [],
  excluded_axes: [],
  strict_expected: false,
  year_range: { min: 1990, max_relative: 2 },
  plausibility_overrides: {},
}

const RULE_TEMPLATE = {
  rule_id: 'new_rule',
  priority: 50,
  conditions: {
    value_pattern: '',
    current_role: 'temporal',
    title_contains_value: false,
  },
  action: {
    new_role: 'revision',
  },
}

const INITIAL_FORM_DATA: FormData = {
  domain_summary: '',
  industry: '',
  sub_domains: [],
  target_users: [],
  document_types: [],
  common_acronyms: {},
  key_concepts: [],
  context_priority: 'medium',
  versioning_hints: '',
  identification_semantics: '',
  axis_reclassification_rules: '',
  axis_policy: '',
}

// ---------------------------------------------------------------------------
// Industry presets
// ---------------------------------------------------------------------------

const INDUSTRY_OPTIONS = [
  { value: 'regulatory', label: 'Reglementaire EU / Conformite' },
  { value: 'healthcare', label: 'Sante / Healthcare' },
  { value: 'pharma_clinical', label: 'Pharma & Recherche Clinique (complet)' },
  { value: 'pharmaceutical', label: 'Pharmaceutique / Life Sciences' },
  { value: 'clinical_research', label: 'Recherche Clinique' },
  { value: 'finance', label: 'Finance / Banque' },
  { value: 'insurance', label: 'Assurance' },
  { value: 'retail', label: 'Retail / Commerce' },
  { value: 'manufacturing', label: 'Industrie / Manufacturing' },
  { value: 'sap_ecosystem', label: 'SAP Ecosystem' },
  { value: 'technology', label: 'Technologie / IT' },
  { value: 'energy', label: 'Energie' },
  { value: 'logistics', label: 'Logistique / Transport' },
  { value: 'education', label: 'Education' },
  { value: 'government', label: 'Secteur Public' },
  { value: 'legal', label: 'Juridique' },
  { value: 'other', label: 'Autre' },
]

interface IndustryPreset {
  descriptionPlaceholder: string
  subDomainsSuggestions: string[]
  keyConceptsSuggestions: string[]
  acronymsSuggestions: Record<string, string>
  targetUsersSuggestions: string[]
  documentTypesSuggestions: string[]
  // Version & Axes presets (optional)
  versioningHints?: string
  identificationSemantics?: string
  axisReclassificationRules?: string
  axisPolicy?: AxisPolicyState
}

const INDUSTRY_PRESETS: Record<string, IndustryPreset> = {
  regulatory: {
    descriptionPlaceholder: "Base de connaissances reglementaire europeenne couvrant la protection des donnees (GDPR), la cybersecurite (NIS2, ENISA), l'intelligence artificielle (AI Act) et les droits fondamentaux. Documents officiels des autorites europeennes (EDPB, ENISA, CNIL) et frameworks internationaux (NIST).",
    subDomainsSuggestions: [
      'Protection des donnees personnelles',
      'Intelligence Artificielle',
      'Cybersecurite',
      'Transferts internationaux',
      'Droits des personnes',
      'Securite des systemes d\'information',
      'Gestion des risques',
      'Conformite reglementaire'
    ],
    keyConceptsSuggestions: [
      'Donnees personnelles',
      'Traitement de donnees',
      'Base legale',
      'Consentement',
      'Interet legitime',
      'Analyse d\'impact (AIPD/DPIA)',
      'Privacy by Design',
      'Systeme d\'IA a haut risque',
      'Transparence algorithmique',
      'Incident de securite',
      'Violation de donnees',
      'Mesures techniques et organisationnelles',
      'Responsable de traitement',
      'Sous-traitant',
      'Transfert vers pays tiers',
      'Decisions de conformite',
      'Pseudonymisation',
      'Chiffrement'
    ],
    acronymsSuggestions: {
      'GDPR': 'General Data Protection Regulation (RGPD)',
      'RGPD': 'Reglement General sur la Protection des Donnees',
      'EDPB': 'European Data Protection Board (Comite Europeen de la Protection des Donnees)',
      'EDPS': 'European Data Protection Supervisor',
      'CNIL': 'Commission Nationale de l\'Informatique et des Libertes',
      'DPO': 'Data Protection Officer (Delegue a la Protection des Donnees)',
      'DPD': 'Delegue a la Protection des Donnees',
      'AIPD': 'Analyse d\'Impact relative a la Protection des Donnees',
      'DPIA': 'Data Protection Impact Assessment',
      'AI Act': 'Artificial Intelligence Act (Reglement sur l\'Intelligence Artificielle)',
      'NIS2': 'Network and Information Security Directive 2',
      'ENISA': 'European Union Agency for Cybersecurity',
      'NIST': 'National Institute of Standards and Technology',
      'AI RMF': 'AI Risk Management Framework',
      'BCR': 'Binding Corporate Rules (Regles d\'entreprise contraignantes)',
      'SCC': 'Standard Contractual Clauses (Clauses Contractuelles Types)',
      'CCT': 'Clauses Contractuelles Types',
      'DPF': 'Data Privacy Framework (EU-US)',
      'RSSI': 'Responsable de la Securite des Systemes d\'Information',
      'PSSI': 'Politique de Securite des Systemes d\'Information',
      'LLM': 'Large Language Model',
      'GPAI': 'General Purpose AI (IA a usage general)',
      'DSA': 'Digital Services Act',
      'DMA': 'Digital Markets Act',
      'eIDAS': 'Electronic Identification and Trust Services'
    },
    targetUsersSuggestions: [
      'DPO / Delegues a la protection des donnees',
      'RSSI / Responsables securite',
      'Compliance Officers',
      'Juristes specialises',
      'Directeurs juridiques',
      'Responsables conformite',
      'Consultants GRC',
      'Auditeurs',
      'Risk Managers'
    ],
    documentTypesSuggestions: [
      'Guidelines EDPB',
      'Opinions EDPB',
      'Rapports annuels',
      'Threat Landscapes ENISA',
      'Guides de securite',
      'Frameworks de gestion des risques',
      'Textes reglementaires',
      'Analyses d\'impact',
      'Recommandations',
      'Statements officiels'
    ],
  },
  healthcare: {
    descriptionPlaceholder: "Organisation specialisee dans les soins de sante...",
    subDomainsSuggestions: ['Telemedecine', 'Dossier patient', 'Imagerie medicale', 'Gestion hospitaliere', 'Parcours de soins'],
    keyConceptsSuggestions: ['Dossier Medical Partage', 'Parcours patient', 'Consentement eclaire', 'Acte medical', 'Prescription'],
    acronymsSuggestions: { 'DMP': 'Dossier Medical Partage', 'HDS': 'Hebergeur de Donnees de Sante', 'PMSI': 'Programme de Medicalisation' },
    targetUsersSuggestions: ['Medecins', 'Infirmiers', 'Personnel administratif', 'Patients'],
    documentTypesSuggestions: ['Comptes-rendus medicaux', 'Protocoles de soins', 'Ordonnances'],
  },
  pharma_clinical: {
    descriptionPlaceholder: "Organization specializing in pharmaceutical industry and clinical research...",
    subDomainsSuggestions: ['R&D', 'Affaires reglementaires', 'Pharmacovigilance', 'Production', 'Qualite', 'Oncologie', 'Cardiologie'],
    keyConceptsSuggestions: ['Autorisation de Mise sur le Marche', 'Phase clinique', 'Endpoint primaire', 'Population ITT', 'Randomisation'],
    acronymsSuggestions: { 'AMM': 'Autorisation de Mise sur le Marche', 'ICH': 'International Council for Harmonisation', 'OS': 'Overall Survival' },
    targetUsersSuggestions: ['Chercheurs', 'Affaires reglementaires', 'Clinical Research Associates', 'Biostatisticiens'],
    documentTypesSuggestions: ['Protocoles d\'essai', 'Clinical Study Reports', 'Dossiers AMM'],
  },
  finance: {
    descriptionPlaceholder: "Institution financiere gerant des operations bancaires...",
    subDomainsSuggestions: ['Banque de detail', 'Asset Management', 'Trading', 'Conformite', 'Risk Management'],
    keyConceptsSuggestions: ['Ratio de solvabilite', 'Risque de credit', 'Liquidite', 'KYC', 'AML'],
    acronymsSuggestions: { 'KYC': 'Know Your Customer', 'AML': 'Anti-Money Laundering', 'VaR': 'Value at Risk' },
    targetUsersSuggestions: ['Traders', 'Analystes financiers', 'Risk managers', 'Compliance officers'],
    documentTypesSuggestions: ['Rapports de gestion', 'Analyses de risque', 'Prospectus'],
  },
  sap_ecosystem: {
    descriptionPlaceholder: "Base de connaissances SAP couvrant l'ensemble de l'ecosysteme : ERP (S/4HANA), plateforme cloud (BTP), solutions metiers (SuccessFactors, Ariba, Concur, Fieldglass), analytics, integration et IA. Le corpus inclut Feature Scope Descriptions, guides de securite, guides d'integration, operations guides et release notes.",
    subDomainsSuggestions: [
      'S/4HANA Cloud Public Edition',
      'S/4HANA Cloud Private Edition',
      'S/4HANA On-Premise',
      'SAP BTP',
      'SAP Integration Suite',
      'SAP SuccessFactors',
      'SAP Ariba',
      'SAP Concur',
      'SAP Fieldglass',
      'SAP Analytics Cloud',
      'SAP Signavio',
      'SAP Build',
      'SAP Joule',
      'SAP DRC',
      'SAP Business AI',
    ],
    keyConceptsSuggestions: [
      'Clean Core',
      'Key User Extensibility',
      'Developer Extensibility',
      'Side-by-Side Extensions',
      'In-App Extensions',
      'Communication Arrangements',
      'Intelligent Enterprise',
      'Business Network',
      'Spend Management',
    ],
    acronymsSuggestions: {
      'S/4HANA': 'SAP S/4HANA - Next-generation ERP suite',
      'BTP': 'Business Technology Platform',
      'PCE': 'Private Cloud Edition',
      'RISE': 'RISE with SAP (Private Edition offering)',
      'GROW': 'GROW with SAP (Public Edition offering)',
      'HCM': 'Human Capital Management (SuccessFactors)',
      'HXM': 'Human Experience Management (SuccessFactors)',
      'SAC': 'SAP Analytics Cloud',
      'CAP': 'Cloud Application Programming Model',
      'RAP': 'RESTful ABAP Programming Model',
      'CF': 'Cloud Foundry',
      'DRC': 'Document and Reporting Compliance',
      'FSD': 'Feature Scope Description',
      'SPS': 'Support Package Stack',
      'FPS': 'Feature Pack Stack',
      'CPI': 'Cloud Platform Integration (ancien nom Integration Suite)',
      'EWM': 'Extended Warehouse Management',
      'TM': 'Transportation Management',
    },
    targetUsersSuggestions: [
      'Solution Architects',
      'SAP Consultants',
      'Technical Consultants',
      'Developers',
      'Key Users',
      'Functional Consultants',
      'Integration Specialists',
    ],
    documentTypesSuggestions: [
      'Feature Scope Description',
      'Security Guide',
      'Integration Guide',
      'Operations Guide',
      'Release Notes',
      'Implementation Guide',
      'Best Practices',
      'API Documentation',
    ],
    versioningHints: "SAP INDEPENDENT versioning axes: (1) release_id: On-Premise YYMM (1503-1909), then YYYY (2020-2023+). Cloud uses YYMM (1603-2508+). Both are release identifiers, NOT dates. (2) SP 01..99: Support Packages, ordered within a release. (3) FPS01..FPS99: Feature Pack Stacks, cumulative. (4) Document Version (5.0, 3.1): document revision, NOT product release. Each is a SEPARATE axis.",
    identificationSemantics: 'Rule: YYMM or YYYY number immediately after SAP product name (e.g. "S/4HANA 2023", "S/4HANA Cloud 2302", "S/4HANA 1809") → release_id. These are product release identifiers, NOT publication dates or temporal references.\nRule: "Document Version" or "Doc Version" followed by X.Y (e.g. 5.0, 3.1) → document_version. This is the document revision, NOT the product release.\nRule: On-Premise releases switched from YYMM to YYYY in 2020: 1503, 1511, 1605, 1610, 1709, 1809, 1909 (YYMM), then 2020, 2021, 2022, 2023 (YYYY).\nCounter-example: 4-digit year in copyright/legal line ("© 2025 SAP SE") → NOT release_id.\nCounter-example: ISO date YYYY-MM-DD ("2025-08-06") → temporal date, NOT release_id.',
    axisReclassificationRules: JSON.stringify([
      {
        rule_id: 'yyyy_in_title_with_product_is_revision',
        priority: 100,
        description: 'YYYY temporal in title near product name = release_id, not temporal',
        conditions: {
          value_pattern: '^(19|20)\\d{2}$',
          current_role: 'temporal',
          title_contains_value: true,
          title_context_pattern: '(?i)(s/4hana|sap\\s|release|version|upgrade|feature pack)',
        },
        action: { new_role: 'revision' },
      },
      {
        rule_id: 'doc_version_not_product_release',
        priority: 90,
        description: 'Document Version X.Y in evidence = doc revision, not product release',
        conditions: {
          value_pattern: '^\\d+\\.\\d+$',
          current_role: 'revision',
          evidence_quote_contains_any: ['document version', 'doc version', 'document revision'],
        },
        action: { new_role: 'unknown', confidence_override: 0.3 },
      },
    ], null, 2),
    axisPolicy: {
      strip_prefixes: ['Version', 'Release', 'Edition'],
      canonicalization_enabled: true,
      expected_axes: ['release_id', 'version', 'edition'],
      excluded_axes: ['trial_phase', 'model_generation', 'regulation_version'],
      strict_expected: false,
      year_range: { min: 1990, max_relative: 2 },
      plausibility_overrides: {
        lifecycle_status: {
          reject_patterns: ['^\\d{4}-\\d{2}-\\d{2}$'],
        },
      },
    },
  },
  technology: {
    descriptionPlaceholder: "Entreprise technologique developpant des logiciels...",
    subDomainsSuggestions: ['Developpement', 'Infrastructure', 'Cybersecurite', 'Cloud', 'Data', 'DevOps'],
    keyConceptsSuggestions: ['Architecture microservices', 'API REST', 'CI/CD', 'Kubernetes', 'Machine Learning'],
    acronymsSuggestions: { 'API': 'Application Programming Interface', 'CI/CD': 'Continuous Integration / Continuous Deployment', 'SaaS': 'Software as a Service' },
    targetUsersSuggestions: ['Developpeurs', 'DevOps', 'Architectes', 'Product managers'],
    documentTypesSuggestions: ['Specifications techniques', 'Documentation API', 'Runbooks'],
  },
  other: {
    descriptionPlaceholder: "Decrivez le domaine d'activite de votre organisation...",
    subDomainsSuggestions: [],
    keyConceptsSuggestions: [],
    acronymsSuggestions: {},
    targetUsersSuggestions: [],
    documentTypesSuggestions: [],
  },
}

// ---------------------------------------------------------------------------
// Reusable UI components
// ---------------------------------------------------------------------------

const SectionCard = ({
  title,
  icon,
  children,
  actions,
}: {
  title: string
  icon: any
  children: React.ReactNode
  actions?: React.ReactNode
}) => (
  <Box
    bg="bg.secondary"
    border="1px solid"
    borderColor="border.default"
    rounded="xl"
    overflow="hidden"
  >
    <HStack
      px={5}
      py={4}
      borderBottom="1px solid"
      borderColor="border.default"
      bg="bg.tertiary"
      justify="space-between"
    >
      <HStack>
        <Icon as={icon} boxSize={5} color="brand.400" />
        <Text fontWeight="semibold" color="text.primary">{title}</Text>
      </HStack>
      {actions}
    </HStack>
    <Box p={5}>
      {children}
    </Box>
  </Box>
)

const StatusBadge = ({ configured }: { configured: boolean }) => (
  <HStack
    spacing={1.5}
    px={3}
    py={1}
    bg={configured ? 'rgba(34, 197, 94, 0.15)' : 'rgba(156, 163, 175, 0.15)'}
    rounded="full"
  >
    <Icon as={configured ? FiCheckCircle : FiInfo} boxSize={3.5} color={configured ? 'green.400' : 'gray.400'} />
    <Text fontSize="xs" fontWeight="medium" color={configured ? 'green.400' : 'gray.400'}>
      {configured ? 'Configure' : 'Non configure'}
    </Text>
  </HStack>
)

const inputStyles = {
  bg: 'bg.tertiary',
  border: '1px solid',
  borderColor: 'border.default',
  rounded: 'lg',
  color: 'text.primary',
  _placeholder: { color: 'text.muted' },
  _hover: { borderColor: 'border.active' },
  _focus: {
    borderColor: 'brand.500',
    boxShadow: '0 0 0 1px var(--chakra-colors-brand-500)',
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseAxisPolicy(raw: string): AxisPolicyState {
  if (!raw) return { ...DEFAULT_AXIS_POLICY }
  try {
    const parsed = JSON.parse(raw)
    return {
      strip_prefixes: Array.isArray(parsed.strip_prefixes) ? parsed.strip_prefixes : [],
      canonicalization_enabled: parsed.canonicalization_enabled ?? true,
      expected_axes: Array.isArray(parsed.expected_axes) ? parsed.expected_axes : [],
      excluded_axes: Array.isArray(parsed.excluded_axes) ? parsed.excluded_axes : [],
      strict_expected: parsed.strict_expected ?? false,
      year_range: {
        min: parsed.year_range?.min ?? 1990,
        max_relative: parsed.year_range?.max_relative ?? 2,
      },
      plausibility_overrides: parsed.plausibility_overrides && typeof parsed.plausibility_overrides === 'object'
        ? parsed.plausibility_overrides
        : {},
    }
  } catch {
    return { ...DEFAULT_AXIS_POLICY }
  }
}

function serializeAxisPolicy(state: AxisPolicyState): string {
  const obj: Record<string, any> = {}
  if (state.strip_prefixes.length > 0) obj.strip_prefixes = state.strip_prefixes
  if (!state.canonicalization_enabled) obj.canonicalization_enabled = false
  if (state.expected_axes.length > 0) obj.expected_axes = state.expected_axes
  if (state.excluded_axes.length > 0) obj.excluded_axes = state.excluded_axes
  if (state.strict_expected) obj.strict_expected = true
  if (state.year_range.min !== 1990 || state.year_range.max_relative !== 2) {
    obj.year_range = state.year_range
  }
  if (Object.keys(state.plausibility_overrides).length > 0) {
    obj.plausibility_overrides = state.plausibility_overrides
  }
  if (Object.keys(obj).length === 0) return ''
  return JSON.stringify(obj, null, 2)
}

function tryParseJson(raw: string): { valid: boolean; count: number; error?: string } {
  if (!raw.trim()) return { valid: true, count: 0 }
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return { valid: true, count: parsed.length }
    return { valid: true, count: 1 }
  } catch (e: any) {
    return { valid: false, count: 0, error: e.message }
  }
}

// ---------------------------------------------------------------------------
// Main Page Component
// ---------------------------------------------------------------------------

export default function DomainContextPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [existingContext, setExistingContext] = useState<DomainContext | null>(null)
  const [previewPrompt, setPreviewPrompt] = useState<string>('')
  const [previewTokens, setPreviewTokens] = useState<number>(0)
  const { isOpen: isDeleteOpen, onOpen: onDeleteOpen, onClose: onDeleteClose } = useDisclosure()
  const toast = useToast()

  // ---- Form state ----
  const [formData, setFormData] = useState<FormData>({ ...INITIAL_FORM_DATA })

  // ---- Axis policy structured state ----
  const [axisPolicy, setAxisPolicy] = useState<AxisPolicyState>({ ...DEFAULT_AXIS_POLICY })

  // ---- Tag input states ----
  const [newSubDomain, setNewSubDomain] = useState('')
  const [newTargetUser, setNewTargetUser] = useState('')
  const [newDocType, setNewDocType] = useState('')
  const [newKeyConcept, setNewKeyConcept] = useState('')
  const [newAcronym, setNewAcronym] = useState('')
  const [newAcronymExpansion, setNewAcronymExpansion] = useState('')
  const [newStripPrefix, setNewStripPrefix] = useState('')

  // ---- Rules JSON validation state ----
  const [rulesJsonStatus, setRulesJsonStatus] = useState<{ valid: boolean; count: number; error?: string }>({ valid: true, count: 0 })

  // ---- Override editor state ----
  const [newOverrideAxis, setNewOverrideAxis] = useState('')

  // ---- Computed ----
  const currentPreset = formData.industry ? INDUSTRY_PRESETS[formData.industry] || INDUSTRY_PRESETS.other : null

  // Validate rules JSON on change
  useEffect(() => {
    setRulesJsonStatus(tryParseJson(formData.axis_reclassification_rules))
  }, [formData.axis_reclassification_rules])

  // ---------------------------------------------------------------------------
  // Industry preset logic (preserved from v1)
  // ---------------------------------------------------------------------------

  const handleIndustryChange = (newIndustry: string) => {
    setFormData({ ...formData, industry: newIndustry })
  }

  const applyAllSuggestions = () => {
    if (!currentPreset) return
    setFormData({
      ...formData,
      domain_summary: formData.domain_summary || currentPreset.descriptionPlaceholder,
      sub_domains: [...new Set([...formData.sub_domains, ...currentPreset.subDomainsSuggestions])],
      key_concepts: [...new Set([...formData.key_concepts, ...currentPreset.keyConceptsSuggestions])],
      target_users: [...new Set([...formData.target_users, ...currentPreset.targetUsersSuggestions])],
      document_types: [...new Set([...formData.document_types, ...currentPreset.documentTypesSuggestions])],
      common_acronyms: { ...currentPreset.acronymsSuggestions, ...formData.common_acronyms },
      versioning_hints: formData.versioning_hints || currentPreset.versioningHints || '',
      identification_semantics: formData.identification_semantics || currentPreset.identificationSemantics || '',
      axis_reclassification_rules: formData.axis_reclassification_rules || currentPreset.axisReclassificationRules || '',
    })
    // Apply axis policy preset if available and current is default
    if (currentPreset.axisPolicy) {
      setAxisPolicy(prev => {
        const isDefault = prev.expected_axes.length === 0 && prev.excluded_axes.length === 0 && prev.strip_prefixes.length === 0
        return isDefault ? { ...currentPreset.axisPolicy! } : prev
      })
    }
  }

  const applySuggestions = (field: 'sub_domains' | 'key_concepts' | 'target_users' | 'document_types') => {
    if (!currentPreset) return
    const mapping: Record<string, string[]> = {
      sub_domains: currentPreset.subDomainsSuggestions,
      key_concepts: currentPreset.keyConceptsSuggestions,
      target_users: currentPreset.targetUsersSuggestions,
      document_types: currentPreset.documentTypesSuggestions,
    }
    const suggestions = mapping[field]
    const currentArray = formData[field] as string[]
    setFormData({ ...formData, [field]: [...new Set([...currentArray, ...suggestions])] })
  }

  const applyAcronymsSuggestions = () => {
    if (!currentPreset) return
    setFormData({
      ...formData,
      common_acronyms: { ...currentPreset.acronymsSuggestions, ...formData.common_acronyms }
    })
  }

  // ---------------------------------------------------------------------------
  // Array / acronym helpers (preserved from v1)
  // ---------------------------------------------------------------------------

  const addToArray = (field: keyof FormData, value: string) => {
    if (!value.trim()) return
    const currentArray = formData[field] as string[]
    if (!currentArray.includes(value.trim())) {
      setFormData({ ...formData, [field]: [...currentArray, value.trim()] })
    }
  }

  const removeFromArray = (field: keyof FormData, value: string) => {
    const currentArray = formData[field] as string[]
    setFormData({ ...formData, [field]: currentArray.filter(v => v !== value) })
  }

  const addAcronym = () => {
    if (!newAcronym.trim() || !newAcronymExpansion.trim()) return
    setFormData({
      ...formData,
      common_acronyms: { ...formData.common_acronyms, [newAcronym.trim().toUpperCase()]: newAcronymExpansion.trim() }
    })
    setNewAcronym('')
    setNewAcronymExpansion('')
  }

  const removeAcronym = (key: string) => {
    const newAcronyms = { ...formData.common_acronyms }
    delete newAcronyms[key]
    setFormData({ ...formData, common_acronyms: newAcronyms })
  }

  // ---------------------------------------------------------------------------
  // Axis policy helpers
  // ---------------------------------------------------------------------------

  const toggleExpectedAxis = (key: string) => {
    setAxisPolicy(prev => {
      const isChecked = prev.expected_axes.includes(key)
      return {
        ...prev,
        expected_axes: isChecked
          ? prev.expected_axes.filter(k => k !== key)
          : [...prev.expected_axes, key],
        excluded_axes: isChecked ? prev.excluded_axes : prev.excluded_axes.filter(k => k !== key),
      }
    })
  }

  const toggleExcludedAxis = (key: string) => {
    setAxisPolicy(prev => {
      const isChecked = prev.excluded_axes.includes(key)
      return {
        ...prev,
        excluded_axes: isChecked
          ? prev.excluded_axes.filter(k => k !== key)
          : [...prev.excluded_axes, key],
        expected_axes: isChecked ? prev.expected_axes : prev.expected_axes.filter(k => k !== key),
      }
    })
  }

  const addStripPrefix = (value: string) => {
    if (!value.trim()) return
    if (!axisPolicy.strip_prefixes.includes(value.trim())) {
      setAxisPolicy(prev => ({ ...prev, strip_prefixes: [...prev.strip_prefixes, value.trim()] }))
    }
  }

  const removeStripPrefix = (value: string) => {
    setAxisPolicy(prev => ({ ...prev, strip_prefixes: prev.strip_prefixes.filter(p => p !== value) }))
  }

  const addPlausibilityOverride = (axis: string) => {
    if (!axis || axisPolicy.plausibility_overrides[axis]) return
    setAxisPolicy(prev => ({
      ...prev,
      plausibility_overrides: {
        ...prev.plausibility_overrides,
        [axis]: { reject_patterns: [], accept_patterns: [] },
      },
    }))
    setNewOverrideAxis('')
  }

  const removePlausibilityOverride = (axis: string) => {
    setAxisPolicy(prev => {
      const updated = { ...prev.plausibility_overrides }
      delete updated[axis]
      return { ...prev, plausibility_overrides: updated }
    })
  }

  const updateOverridePatterns = (axis: string, field: 'reject_patterns' | 'accept_patterns', text: string) => {
    const patterns = text.split('\n').filter(line => line.trim() !== '')
    setAxisPolicy(prev => ({
      ...prev,
      plausibility_overrides: {
        ...prev.plausibility_overrides,
        [axis]: {
          ...prev.plausibility_overrides[axis],
          [field]: patterns,
        },
      },
    }))
  }

  // ---------------------------------------------------------------------------
  // API calls
  // ---------------------------------------------------------------------------

  useEffect(() => {
    loadDomainContext()
  }, [])

  const loadDomainContext = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/domain-context')
      if (response.status === 404) {
        setExistingContext(null)
      } else if (response.ok) {
        const data = await response.json()
        setExistingContext(data)
        setFormData({
          domain_summary: data.domain_summary || '',
          industry: data.industry || '',
          sub_domains: data.sub_domains || [],
          target_users: data.target_users || [],
          document_types: data.document_types || [],
          common_acronyms: data.common_acronyms || {},
          key_concepts: data.key_concepts || [],
          context_priority: data.context_priority || 'medium',
          versioning_hints: data.versioning_hints || '',
          identification_semantics: data.identification_semantics || '',
          axis_reclassification_rules: data.axis_reclassification_rules || '',
          axis_policy: data.axis_policy || '',
        })
        setAxisPolicy(parseAxisPolicy(data.axis_policy || ''))
      }
    } catch (error) {
      console.error('Error loading domain context:', error)
    } finally {
      setLoading(false)
    }
  }

  const buildPayload = useCallback((): FormData => {
    const serialized = serializeAxisPolicy(axisPolicy)
    return {
      ...formData,
      axis_policy: serialized,
    }
  }, [formData, axisPolicy])

  const handlePreview = async () => {
    setPreviewing(true)
    try {
      const payload = buildPayload()
      const response = await fetch('/api/domain-context/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (response.ok) {
        const data = await response.json()
        setPreviewPrompt(data.llm_injection_prompt)
        setPreviewTokens(data.estimated_tokens)
        toast({ title: 'Apercu genere', status: 'success', duration: 2000, position: 'top' })
      } else {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Erreur serveur: ${response.status}`)
      }
    } catch (error: any) {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000, position: 'top' })
    } finally {
      setPreviewing(false)
    }
  }

  const handleSave = async () => {
    if (!formData.domain_summary || !formData.industry) {
      toast({
        title: 'Champs requis manquants',
        description: 'Le resume du domaine et l\'industrie sont obligatoires.',
        status: 'warning',
        duration: 3000,
        position: 'top',
      })
      return
    }

    if (formData.axis_reclassification_rules.trim()) {
      const check = tryParseJson(formData.axis_reclassification_rules)
      if (!check.valid) {
        toast({
          title: 'JSON invalide dans Rules Engine',
          description: `Erreur: ${check.error}`,
          status: 'error',
          duration: 5000,
          position: 'top',
        })
        return
      }
    }

    setSaving(true)
    try {
      const payload = buildPayload()
      const response = await fetch('/api/domain-context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (response.ok) {
        const data = await response.json()
        setExistingContext(data)
        toast({ title: 'Contexte sauvegarde', status: 'success', duration: 3000, position: 'top' })
      } else {
        const error = await response.json()
        throw new Error(error.detail || 'Erreur inconnue')
      }
    } catch (error: any) {
      toast({ title: 'Erreur', description: error.message, status: 'error', duration: 5000, position: 'top' })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    try {
      const response = await fetch('/api/domain-context', { method: 'DELETE' })
      if (response.status === 204 || response.ok) {
        setExistingContext(null)
        setFormData({ ...INITIAL_FORM_DATA })
        setAxisPolicy({ ...DEFAULT_AXIS_POLICY })
        setPreviewPrompt('')
        toast({ title: 'Contexte supprime', status: 'info', duration: 3000, position: 'top' })
        onDeleteClose()
      }
    } catch (error) {
      console.error('Error deleting:', error)
    }
  }

  // ---------------------------------------------------------------------------
  // Rules engine helpers
  // ---------------------------------------------------------------------------

  const insertRuleTemplate = () => {
    const current = formData.axis_reclassification_rules.trim()
    let newVal: string
    if (!current) {
      newVal = JSON.stringify([RULE_TEMPLATE], null, 2)
    } else {
      try {
        const parsed = JSON.parse(current)
        const arr = Array.isArray(parsed) ? parsed : [parsed]
        arr.push({ ...RULE_TEMPLATE, rule_id: `new_rule_${arr.length + 1}` })
        newVal = JSON.stringify(arr, null, 2)
      } catch {
        newVal = current + '\n' + JSON.stringify(RULE_TEMPLATE, null, 2)
      }
    }
    setFormData({ ...formData, axis_reclassification_rules: newVal })
  }

  // ---------------------------------------------------------------------------
  // Pipeline impact summary
  // ---------------------------------------------------------------------------

  const pipelineImpact = useMemo(() => {
    const rulesCheck = tryParseJson(formData.axis_reclassification_rules)
    const overridesCount = Object.keys(axisPolicy.plausibility_overrides).length
    const errors: string[] = []
    if (!rulesCheck.valid) errors.push('JSON invalide dans axis_reclassification_rules')
    const overlap = axisPolicy.expected_axes.filter(a => axisPolicy.excluded_axes.includes(a))
    if (overlap.length > 0) errors.push(`Axes en conflit expected/excluded: ${overlap.join(', ')}`)

    return {
      expectedCount: axisPolicy.expected_axes.length,
      excludedCount: axisPolicy.excluded_axes.length,
      rulesCount: rulesCheck.valid ? rulesCheck.count : 0,
      overridesCount,
      errors,
    }
  }, [formData.axis_reclassification_rules, axisPolicy])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <Center h="400px">
        <VStack spacing={4}>
          <Spinner size="xl" color="brand.500" thickness="3px" />
          <Text color="text.muted">Chargement du Domain Context...</Text>
        </VStack>
      </Center>
    )
  }

  return (
    <Box maxW="1000px" mx="auto">
      {/* Header */}
      <MotionBox
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        mb={8}
      >
        <HStack justify="space-between" align="start" flexWrap="wrap" gap={4}>
          <HStack spacing={3}>
            <Box
              w={10}
              h={10}
              rounded="lg"
              bgGradient="linear(to-br, brand.500, accent.400)"
              display="flex"
              alignItems="center"
              justifyContent="center"
              boxShadow="0 0 20px rgba(99, 102, 241, 0.3)"
            >
              <Icon as={FiGlobe} boxSize={5} color="white" />
            </Box>
            <VStack align="start" spacing={0}>
              <HStack>
                <Text fontSize="2xl" fontWeight="bold" color="text.primary">
                  Domain Context
                </Text>
                <StatusBadge configured={!!existingContext} />
              </HStack>
              <Text color="text.secondary">
                Contexte metier pour l'extraction intelligente
              </Text>
            </VStack>
          </HStack>

          <HStack>
            <Button
              leftIcon={<Icon as={FiRefreshCw} />}
              variant="ghost"
              color="text.secondary"
              onClick={loadDomainContext}
              _hover={{ color: 'text.primary', bg: 'bg.hover' }}
            >
              Actualiser
            </Button>
            {existingContext && (
              <Button
                leftIcon={<Icon as={FiTrash2} />}
                variant="ghost"
                color="red.400"
                onClick={onDeleteOpen}
                _hover={{ bg: 'rgba(239, 68, 68, 0.1)' }}
              >
                Supprimer
              </Button>
            )}
          </HStack>
        </HStack>
      </MotionBox>

      <VStack spacing={6} align="stretch">
        {/* Info Alert */}
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <Box
            p={4}
            bg="rgba(99, 102, 241, 0.1)"
            border="1px solid"
            borderColor="rgba(99, 102, 241, 0.3)"
            rounded="xl"
          >
            <HStack align="start" spacing={3}>
              <Icon as={FiInfo} boxSize={5} color="brand.400" mt={0.5} />
              <VStack align="start" spacing={1}>
                <Text fontWeight="medium" color="brand.400">Comment ca fonctionne ?</Text>
                <Text fontSize="sm" color="text.secondary">
                  Le Domain Context est injecte automatiquement dans tous les prompts LLM lors de l'extraction.
                  Il aide le systeme a mieux comprendre votre domaine metier et produire des extractions plus precises.
                </Text>
              </VStack>
            </HStack>
          </Box>
        </MotionBox>

        {/* ================================================================= */}
        {/* SECTION 1 : Configuration Generale                                */}
        {/* ================================================================= */}
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
        >
          <SectionCard title="Configuration du contexte" icon={FiGlobe}>
            <VStack spacing={6} align="stretch">
              {/* Industry Select */}
              <FormControl isRequired>
                <FormLabel color="text.secondary" fontSize="sm">Industrie</FormLabel>
                <Select
                  value={formData.industry}
                  onChange={(e) => handleIndustryChange(e.target.value)}
                  placeholder="Selectionnez une industrie"
                  {...inputStyles}
                  icon={<FiChevronDown />}
                  sx={{ '> option': { bg: 'bg.secondary', color: 'text.primary' } }}
                >
                  {INDUSTRY_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </Select>
                <FormHelperText color="text.muted">
                  Selectionnez l'industrie pour obtenir des suggestions contextualisees
                </FormHelperText>
              </FormControl>

              {/* Apply all suggestions */}
              {currentPreset && currentPreset.subDomainsSuggestions.length > 0 && (
                <Box
                  p={4}
                  bg="rgba(34, 211, 238, 0.08)"
                  border="1px solid"
                  borderColor="rgba(34, 211, 238, 0.2)"
                  rounded="lg"
                >
                  <HStack justify="space-between" flexWrap="wrap" gap={3}>
                    <HStack>
                      <Icon as={FiZap} color="accent.400" />
                      <Text fontSize="sm" color="accent.400">
                        Suggestions disponibles pour cette industrie
                      </Text>
                    </HStack>
                    <Button
                      size="sm"
                      bg="accent.400"
                      color="bg.primary"
                      onClick={applyAllSuggestions}
                      _hover={{ bg: 'accent.300' }}
                    >
                      Appliquer toutes les suggestions
                    </Button>
                  </HStack>
                </Box>
              )}

              {/* Domain Summary */}
              <FormControl isRequired>
                <FormLabel color="text.secondary" fontSize="sm">Description du domaine</FormLabel>
                <Textarea
                  value={formData.domain_summary}
                  onChange={(e) => setFormData({ ...formData, domain_summary: e.target.value })}
                  placeholder={currentPreset?.descriptionPlaceholder || "Decrivez votre domaine d'activite..."}
                  rows={4}
                  maxLength={500}
                  {...inputStyles}
                />
                <FormHelperText color="text.muted">
                  {formData.domain_summary.length}/500 caracteres
                </FormHelperText>
              </FormControl>

              {/* Sub-domains */}
              <FormControl>
                <HStack justify="space-between" mb={2}>
                  <FormLabel color="text.secondary" fontSize="sm" mb={0}>Sous-domaines</FormLabel>
                  {currentPreset && currentPreset.subDomainsSuggestions.length > 0 && (
                    <Button size="xs" variant="ghost" color="brand.400" onClick={() => applySuggestions('sub_domains')}>
                      + Suggestions ({currentPreset.subDomainsSuggestions.length})
                    </Button>
                  )}
                </HStack>
                <HStack mb={3}>
                  <Input
                    value={newSubDomain}
                    onChange={(e) => setNewSubDomain(e.target.value)}
                    placeholder="Ajouter un sous-domaine"
                    {...inputStyles}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('sub_domains', newSubDomain); setNewSubDomain('') } }}
                  />
                  <Button onClick={() => { addToArray('sub_domains', newSubDomain); setNewSubDomain('') }} bg="bg.tertiary" _hover={{ bg: 'bg.hover' }}>
                    Ajouter
                  </Button>
                </HStack>
                <Wrap>
                  {formData.sub_domains.map(sd => (
                    <WrapItem key={sd}>
                      <Tag bg="rgba(99, 102, 241, 0.15)" color="brand.400" borderRadius="full">
                        <TagLabel>{sd}</TagLabel>
                        <TagCloseButton onClick={() => removeFromArray('sub_domains', sd)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
              </FormControl>

              {/* Key Concepts */}
              <FormControl>
                <HStack justify="space-between" mb={2}>
                  <FormLabel color="text.secondary" fontSize="sm" mb={0}>Concepts cles</FormLabel>
                  {currentPreset && currentPreset.keyConceptsSuggestions.length > 0 && (
                    <Button size="xs" variant="ghost" color="purple.400" onClick={() => applySuggestions('key_concepts')}>
                      + Suggestions ({currentPreset.keyConceptsSuggestions.length})
                    </Button>
                  )}
                </HStack>
                <HStack mb={3}>
                  <Input
                    value={newKeyConcept}
                    onChange={(e) => setNewKeyConcept(e.target.value)}
                    placeholder="Ajouter un concept"
                    {...inputStyles}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('key_concepts', newKeyConcept); setNewKeyConcept('') } }}
                  />
                  <Button onClick={() => { addToArray('key_concepts', newKeyConcept); setNewKeyConcept('') }} bg="bg.tertiary" _hover={{ bg: 'bg.hover' }}>
                    Ajouter
                  </Button>
                </HStack>
                <Wrap>
                  {formData.key_concepts.map(kc => (
                    <WrapItem key={kc}>
                      <Tag bg="rgba(168, 85, 247, 0.15)" color="purple.400" borderRadius="full">
                        <TagLabel>{kc}</TagLabel>
                        <TagCloseButton onClick={() => removeFromArray('key_concepts', kc)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
              </FormControl>

              {/* Acronyms */}
              <FormControl>
                <HStack justify="space-between" mb={2}>
                  <FormLabel color="text.secondary" fontSize="sm" mb={0}>Acronymes</FormLabel>
                  {currentPreset && Object.keys(currentPreset.acronymsSuggestions).length > 0 && (
                    <Button size="xs" variant="ghost" color="teal.400" onClick={applyAcronymsSuggestions}>
                      + Suggestions ({Object.keys(currentPreset.acronymsSuggestions).length})
                    </Button>
                  )}
                </HStack>
                <HStack mb={3}>
                  <Input
                    value={newAcronym}
                    onChange={(e) => setNewAcronym(e.target.value)}
                    placeholder="Ex: API"
                    width="120px"
                    {...inputStyles}
                  />
                  <Input
                    value={newAcronymExpansion}
                    onChange={(e) => setNewAcronymExpansion(e.target.value)}
                    placeholder="Ex: Application Programming Interface"
                    flex={1}
                    {...inputStyles}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addAcronym() } }}
                  />
                  <Button onClick={addAcronym} bg="bg.tertiary" _hover={{ bg: 'bg.hover' }}>
                    Ajouter
                  </Button>
                </HStack>
                <Wrap>
                  {Object.entries(formData.common_acronyms).map(([key, value]) => (
                    <WrapItem key={key}>
                      <Tag bg="rgba(20, 184, 166, 0.15)" color="teal.400" borderRadius="full">
                        <TagLabel><strong>{key}</strong>: {value}</TagLabel>
                        <TagCloseButton onClick={() => removeAcronym(key)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
              </FormControl>

              {/* Priority */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Priorite d'injection</FormLabel>
                <Select
                  value={formData.context_priority}
                  onChange={(e) => setFormData({ ...formData, context_priority: e.target.value as any })}
                  {...inputStyles}
                  sx={{ '> option': { bg: 'bg.secondary', color: 'text.primary' } }}
                >
                  <option value="low">Basse - ~50 tokens</option>
                  <option value="medium">Moyenne - ~150 tokens</option>
                  <option value="high">Haute - ~300 tokens</option>
                </Select>
              </FormControl>

              {/* Advanced Options */}
              <Accordion allowToggle>
                <AccordionItem border="none">
                  <AccordionButton px={0} _hover={{ bg: 'transparent' }}>
                    <Text fontWeight="medium" color="text.secondary">Options avancees</Text>
                    <AccordionIcon color="text.muted" ml={2} />
                  </AccordionButton>
                  <AccordionPanel px={0}>
                    <VStack spacing={4} align="stretch">
                      {/* Target Users */}
                      <FormControl>
                        <HStack justify="space-between" mb={2}>
                          <FormLabel color="text.secondary" fontSize="sm" mb={0}>Utilisateurs cibles</FormLabel>
                          {currentPreset && currentPreset.targetUsersSuggestions.length > 0 && (
                            <Button size="xs" variant="ghost" color="orange.400" onClick={() => applySuggestions('target_users')}>
                              + Suggestions
                            </Button>
                          )}
                        </HStack>
                        <HStack mb={3}>
                          <Input
                            value={newTargetUser}
                            onChange={(e) => setNewTargetUser(e.target.value)}
                            placeholder="Type d'utilisateur"
                            {...inputStyles}
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('target_users', newTargetUser); setNewTargetUser('') } }}
                          />
                          <Button onClick={() => { addToArray('target_users', newTargetUser); setNewTargetUser('') }} bg="bg.tertiary" _hover={{ bg: 'bg.hover' }}>
                            Ajouter
                          </Button>
                        </HStack>
                        <Wrap>
                          {formData.target_users.map(tu => (
                            <WrapItem key={tu}>
                              <Tag bg="rgba(249, 115, 22, 0.15)" color="orange.400" borderRadius="full">
                                <TagLabel>{tu}</TagLabel>
                                <TagCloseButton onClick={() => removeFromArray('target_users', tu)} />
                              </Tag>
                            </WrapItem>
                          ))}
                        </Wrap>
                      </FormControl>

                      {/* Document Types */}
                      <FormControl>
                        <HStack justify="space-between" mb={2}>
                          <FormLabel color="text.secondary" fontSize="sm" mb={0}>Types de documents</FormLabel>
                          {currentPreset && currentPreset.documentTypesSuggestions.length > 0 && (
                            <Button size="xs" variant="ghost" color="cyan.400" onClick={() => applySuggestions('document_types')}>
                              + Suggestions
                            </Button>
                          )}
                        </HStack>
                        <HStack mb={3}>
                          <Input
                            value={newDocType}
                            onChange={(e) => setNewDocType(e.target.value)}
                            placeholder="Type de document"
                            {...inputStyles}
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('document_types', newDocType); setNewDocType('') } }}
                          />
                          <Button onClick={() => { addToArray('document_types', newDocType); setNewDocType('') }} bg="bg.tertiary" _hover={{ bg: 'bg.hover' }}>
                            Ajouter
                          </Button>
                        </HStack>
                        <Wrap>
                          {formData.document_types.map(dt => (
                            <WrapItem key={dt}>
                              <Tag bg="rgba(34, 211, 238, 0.15)" color="cyan.400" borderRadius="full">
                                <TagLabel>{dt}</TagLabel>
                                <TagCloseButton onClick={() => removeFromArray('document_types', dt)} />
                              </Tag>
                            </WrapItem>
                          ))}
                        </Wrap>
                      </FormControl>
                    </VStack>
                  </AccordionPanel>
                </AccordionItem>
              </Accordion>
            </VStack>
          </SectionCard>
        </MotionBox>

        {/* ================================================================= */}
        {/* SECTION 2 : Version & Axes                                        */}
        {/* ================================================================= */}
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.25 }}
        >
          <SectionCard title="Version & Axes" icon={FiSettings}>
            <VStack spacing={6} align="stretch">
              {/* Versioning Hints */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Versioning Hints</FormLabel>
                <Textarea
                  value={formData.versioning_hints}
                  onChange={(e) => setFormData({ ...formData, versioning_hints: e.target.value })}
                  placeholder="Decrivez les conventions de versionnage de votre domaine..."
                  rows={3}
                  maxLength={500}
                  {...inputStyles}
                />
                <FormHelperText color="text.muted">
                  Ex: Release = annee (2023), FPS = patch cumulatif, SP = support pack
                  <br />
                  {formData.versioning_hints.length}/500 caracteres
                </FormHelperText>
              </FormControl>

              {/* Identification Semantics */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Identification Semantics</FormLabel>
                <Textarea
                  value={formData.identification_semantics}
                  onChange={(e) => setFormData({ ...formData, identification_semantics: e.target.value })}
                  placeholder={"Rule: <pattern> -> <interpretation>\nCounter-example: <pattern> -> NOT <this>"}
                  rows={5}
                  maxLength={1000}
                  {...inputStyles}
                />
                <FormHelperText color="text.muted">
                  Format recommande : Rule: &lt;pattern&gt; -&gt; &lt;interpretation&gt;. Counter-example: &lt;pattern&gt; -&gt; NOT &lt;this&gt;
                  <br />
                  {formData.identification_semantics.length}/1000 caracteres
                </FormHelperText>
              </FormControl>

              <Divider borderColor="border.default" />

              {/* Expected Axes */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Expected Axes</FormLabel>
                <FormHelperText color="text.muted" mb={3}>
                  Axes que le pipeline doit s'attendre a trouver dans les documents de ce domaine
                </FormHelperText>
                <SimpleGrid columns={{ base: 2, md: 3, lg: 4 }} spacing={2}>
                  {NEUTRAL_AXIS_KEYS.map(axis => {
                    const isExcluded = axisPolicy.excluded_axes.includes(axis.key)
                    return (
                      <Checkbox
                        key={`expected-${axis.key}`}
                        isChecked={axisPolicy.expected_axes.includes(axis.key)}
                        isDisabled={isExcluded}
                        onChange={() => toggleExpectedAxis(axis.key)}
                        colorScheme="purple"
                        size="sm"
                        sx={{
                          '.chakra-checkbox__label': { color: isExcluded ? 'text.muted' : 'text.secondary', fontSize: 'sm' },
                          '.chakra-checkbox__control': { borderColor: 'border.default' },
                        }}
                      >
                        {axis.label}
                      </Checkbox>
                    )
                  })}
                </SimpleGrid>
              </FormControl>

              {/* Excluded Axes */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Excluded Axes</FormLabel>
                <FormHelperText color="text.muted" mb={3}>
                  Axes a ignorer systematiquement pour ce domaine
                </FormHelperText>
                <SimpleGrid columns={{ base: 2, md: 3, lg: 4 }} spacing={2}>
                  {NEUTRAL_AXIS_KEYS.map(axis => {
                    const isExpected = axisPolicy.expected_axes.includes(axis.key)
                    return (
                      <Checkbox
                        key={`excluded-${axis.key}`}
                        isChecked={axisPolicy.excluded_axes.includes(axis.key)}
                        isDisabled={isExpected}
                        onChange={() => toggleExcludedAxis(axis.key)}
                        colorScheme="red"
                        size="sm"
                        sx={{
                          '.chakra-checkbox__label': { color: isExpected ? 'text.muted' : 'text.secondary', fontSize: 'sm' },
                          '.chakra-checkbox__control': { borderColor: 'border.default' },
                        }}
                      >
                        {axis.label}
                      </Checkbox>
                    )
                  })}
                </SimpleGrid>
              </FormControl>

              {/* Strict Expected toggle */}
              <FormControl>
                <HStack spacing={3}>
                  <Checkbox
                    isChecked={axisPolicy.strict_expected}
                    onChange={(e) => setAxisPolicy(prev => ({ ...prev, strict_expected: e.target.checked }))}
                    colorScheme="purple"
                    sx={{
                      '.chakra-checkbox__control': { borderColor: 'border.default' },
                    }}
                  >
                    <Text fontSize="sm" color="text.secondary">Strict mode</Text>
                  </Checkbox>
                </HStack>
                <FormHelperText color="text.muted" ml={6}>
                  Si active, les axes hors "Expected" sont rejetes (hard filter). Sinon, ils sont gardes avec une note (soft boost).
                </FormHelperText>
              </FormControl>

              <Divider borderColor="border.default" />

              {/* Strip Prefixes */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Strip Prefixes</FormLabel>
                <FormHelperText color="text.muted" mb={3}>
                  Mots-prefixes a retirer des valeurs d'axes pour canonicalisation (ex: "Version 2025" → "2025")
                </FormHelperText>
                <HStack mb={3}>
                  <Input
                    value={newStripPrefix}
                    onChange={(e) => setNewStripPrefix(e.target.value)}
                    placeholder="Ex: Version, Release, Edition"
                    {...inputStyles}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addStripPrefix(newStripPrefix)
                        setNewStripPrefix('')
                      }
                    }}
                  />
                  <Button onClick={() => { addStripPrefix(newStripPrefix); setNewStripPrefix('') }} bg="bg.tertiary" _hover={{ bg: 'bg.hover' }}>
                    Ajouter
                  </Button>
                </HStack>
                <Wrap>
                  {axisPolicy.strip_prefixes.map(prefix => (
                    <WrapItem key={prefix}>
                      <Tag bg="rgba(245, 158, 11, 0.15)" color="yellow.400" borderRadius="full">
                        <TagLabel>{`"${prefix}"`}</TagLabel>
                        <TagCloseButton onClick={() => removeStripPrefix(prefix)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
              </FormControl>

              {/* Canonicalization toggle */}
              {axisPolicy.strip_prefixes.length > 0 && (
                <FormControl>
                  <HStack spacing={3}>
                    <Checkbox
                      isChecked={axisPolicy.canonicalization_enabled}
                      onChange={(e) => setAxisPolicy(prev => ({ ...prev, canonicalization_enabled: e.target.checked }))}
                      colorScheme="green"
                      sx={{
                        '.chakra-checkbox__control': { borderColor: 'border.default' },
                      }}
                    >
                      <Text fontSize="sm" color="text.secondary">Canonicalisation active</Text>
                    </Checkbox>
                  </HStack>
                  <FormHelperText color="text.muted" ml={6}>
                    Decochez pour desactiver la canonicalisation meme si des prefixes sont configures.
                  </FormHelperText>
                </FormControl>
              )}

              {/* Year Range */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Year Range</FormLabel>
                <FormHelperText color="text.muted" mb={3}>
                  Plage d'annees considerees plausibles pour les axes temporels
                </FormHelperText>
                <HStack spacing={4}>
                  <VStack align="start" spacing={1}>
                    <Text fontSize="xs" color="text.muted">Annee minimum</Text>
                    <NumberInput
                      value={axisPolicy.year_range.min}
                      onChange={(_, val) => setAxisPolicy(prev => ({
                        ...prev,
                        year_range: { ...prev.year_range, min: isNaN(val) ? 1990 : val },
                      }))}
                      min={1900}
                      max={2100}
                      size="sm"
                    >
                      <NumberInputField {...inputStyles} />
                      <NumberInputStepper>
                        <NumberIncrementStepper borderColor="border.default" color="text.muted" />
                        <NumberDecrementStepper borderColor="border.default" color="text.muted" />
                      </NumberInputStepper>
                    </NumberInput>
                  </VStack>
                  <VStack align="start" spacing={1}>
                    <Text fontSize="xs" color="text.muted">Max relative (+N ans)</Text>
                    <NumberInput
                      value={axisPolicy.year_range.max_relative}
                      onChange={(_, val) => setAxisPolicy(prev => ({
                        ...prev,
                        year_range: { ...prev.year_range, max_relative: isNaN(val) ? 2 : val },
                      }))}
                      min={0}
                      max={20}
                      size="sm"
                    >
                      <NumberInputField {...inputStyles} />
                      <NumberInputStepper>
                        <NumberIncrementStepper borderColor="border.default" color="text.muted" />
                        <NumberDecrementStepper borderColor="border.default" color="text.muted" />
                      </NumberInputStepper>
                    </NumberInput>
                  </VStack>
                </HStack>
              </FormControl>

              <Divider borderColor="border.default" />

              {/* Plausibility Overrides */}
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Plausibility Overrides</FormLabel>
                <FormHelperText color="text.muted" mb={3}>
                  Patterns personnalises de rejet/acceptation par axe (regex, un par ligne)
                </FormHelperText>

                {/* Existing overrides */}
                <VStack spacing={4} align="stretch" mb={Object.keys(axisPolicy.plausibility_overrides).length > 0 ? 4 : 0}>
                  {Object.entries(axisPolicy.plausibility_overrides).map(([axis, override]) => (
                    <Box
                      key={axis}
                      p={4}
                      bg="bg.tertiary"
                      border="1px solid"
                      borderColor="border.default"
                      rounded="lg"
                    >
                      <HStack justify="space-between" mb={3}>
                        <HStack>
                          <Badge colorScheme="purple" fontSize="xs">{axis}</Badge>
                        </HStack>
                        <IconButton
                          aria-label={`Supprimer override ${axis}`}
                          icon={<FiMinus />}
                          size="xs"
                          variant="ghost"
                          color="red.400"
                          onClick={() => removePlausibilityOverride(axis)}
                          _hover={{ bg: 'rgba(239, 68, 68, 0.1)' }}
                        />
                      </HStack>
                      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
                        <Box>
                          <Text fontSize="xs" color="red.400" mb={1}>Reject patterns</Text>
                          <Textarea
                            value={(override.reject_patterns || []).join('\n')}
                            onChange={(e) => updateOverridePatterns(axis, 'reject_patterns', e.target.value)}
                            placeholder="Un pattern par ligne..."
                            rows={3}
                            fontSize="sm"
                            fontFamily="mono"
                            {...inputStyles}
                          />
                        </Box>
                        <Box>
                          <Text fontSize="xs" color="green.400" mb={1}>Accept patterns</Text>
                          <Textarea
                            value={(override.accept_patterns || []).join('\n')}
                            onChange={(e) => updateOverridePatterns(axis, 'accept_patterns', e.target.value)}
                            placeholder="Un pattern par ligne..."
                            rows={3}
                            fontSize="sm"
                            fontFamily="mono"
                            {...inputStyles}
                          />
                        </Box>
                      </SimpleGrid>
                    </Box>
                  ))}
                </VStack>

                {/* Add new override */}
                <HStack>
                  <Select
                    value={newOverrideAxis}
                    onChange={(e) => setNewOverrideAxis(e.target.value)}
                    placeholder="Selectionner un axe..."
                    size="sm"
                    {...inputStyles}
                    sx={{ '> option': { bg: 'bg.secondary', color: 'text.primary' } }}
                  >
                    {NEUTRAL_AXIS_KEYS
                      .filter(a => !axisPolicy.plausibility_overrides[a.key])
                      .map(axis => (
                        <option key={axis.key} value={axis.key}>{axis.label}</option>
                      ))
                    }
                  </Select>
                  <Button
                    size="sm"
                    leftIcon={<FiPlus />}
                    onClick={() => addPlausibilityOverride(newOverrideAxis)}
                    isDisabled={!newOverrideAxis}
                    bg="bg.tertiary"
                    _hover={{ bg: 'bg.hover' }}
                  >
                    Ajouter
                  </Button>
                </HStack>
              </FormControl>
            </VStack>
          </SectionCard>
        </MotionBox>

        {/* ================================================================= */}
        {/* SECTION 3 : Rules Engine                                          */}
        {/* ================================================================= */}
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.3 }}
        >
          <SectionCard
            title="Rules Engine"
            icon={FiCode}
            actions={
              <HStack spacing={2}>
                {formData.axis_reclassification_rules.trim() && (
                  <Badge
                    colorScheme={rulesJsonStatus.valid ? 'green' : 'red'}
                    variant="subtle"
                    fontSize="xs"
                    px={2}
                    py={0.5}
                    rounded="full"
                  >
                    {rulesJsonStatus.valid
                      ? `${rulesJsonStatus.count} regle${rulesJsonStatus.count !== 1 ? 's' : ''}`
                      : 'JSON invalide'
                    }
                  </Badge>
                )}
              </HStack>
            }
          >
            <VStack spacing={4} align="stretch">
              <FormControl>
                <FormLabel color="text.secondary" fontSize="sm">Axis Reclassification Rules (JSON)</FormLabel>
                <Textarea
                  value={formData.axis_reclassification_rules}
                  onChange={(e) => setFormData({ ...formData, axis_reclassification_rules: e.target.value })}
                  placeholder='[\n  {\n    "rule_id": "...",\n    "priority": 50,\n    "conditions": { ... },\n    "action": { "new_role": "..." }\n  }\n]'
                  rows={12}
                  maxLength={5000}
                  fontFamily="mono"
                  fontSize="sm"
                  {...inputStyles}
                  onBlur={() => setRulesJsonStatus(tryParseJson(formData.axis_reclassification_rules))}
                />
                <HStack justify="space-between" mt={2}>
                  <FormHelperText color="text.muted">
                    {formData.axis_reclassification_rules.length}/5000 caracteres
                  </FormHelperText>
                  {!rulesJsonStatus.valid && (
                    <Text fontSize="xs" color="red.400">
                      {rulesJsonStatus.error}
                    </Text>
                  )}
                </HStack>
              </FormControl>

              {/* Add template button */}
              <Button
                size="sm"
                leftIcon={<FiPlus />}
                onClick={insertRuleTemplate}
                bg="bg.tertiary"
                color="text.secondary"
                _hover={{ bg: 'bg.hover', color: 'text.primary' }}
                alignSelf="flex-start"
              >
                Ajouter template de regle
              </Button>

              {/* Help accordion */}
              <Accordion allowToggle>
                <AccordionItem border="none">
                  <AccordionButton px={0} _hover={{ bg: 'transparent' }}>
                    <HStack>
                      <Icon as={FiInfo} boxSize={3.5} color="text.muted" />
                      <Text fontSize="sm" fontWeight="medium" color="text.muted">Aide - Structure d'une regle</Text>
                    </HStack>
                    <AccordionIcon color="text.muted" ml={2} />
                  </AccordionButton>
                  <AccordionPanel px={0} pt={2}>
                    <Box
                      p={4}
                      bg="bg.tertiary"
                      rounded="lg"
                      border="1px solid"
                      borderColor="border.default"
                    >
                      <VStack align="start" spacing={2}>
                        <Text fontSize="sm" color="text.secondary">
                          Chaque regle a la structure suivante :
                        </Text>
                        <Code
                          p={3}
                          bg="bg.primary"
                          rounded="md"
                          display="block"
                          whiteSpace="pre-wrap"
                          fontSize="xs"
                          color="text.secondary"
                          w="100%"
                        >
{`{
  "rule_id": "identifiant_unique",
  "priority": 50,              // 0-100, plus haut = prioritaire
  "conditions": {
    "value_pattern": "\\\\d{4}",  // regex sur la valeur
    "current_role": "temporal",   // role actuel de l'axe
    "title_contains_value": false // valeur presente dans le titre ?
  },
  "action": {
    "new_role": "revision"        // nouveau role a assigner
  }
}`}
                        </Code>
                        <Text fontSize="xs" color="text.muted">
                          Les regles sont evaluees dans l'ordre de priorite. La premiere condition matchee determine le nouveau role.
                          Roles possibles : temporal, revision, identification, classification, spatial.
                        </Text>
                      </VStack>
                    </Box>
                  </AccordionPanel>
                </AccordionItem>
              </Accordion>
            </VStack>
          </SectionCard>
        </MotionBox>

        {/* ================================================================= */}
        {/* SECTION 4 : Preview                                               */}
        {/* ================================================================= */}
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.35 }}
        >
          <SectionCard
            title="Apercu du prompt"
            icon={FiEye}
            actions={
              <Button
                size="sm"
                leftIcon={<Icon as={FiEye} />}
                onClick={handlePreview}
                isDisabled={!formData.domain_summary || !formData.industry}
                isLoading={previewing}
                loadingText="Generation..."
                bg="bg.hover"
                _hover={{ bg: 'brand.500', color: 'white' }}
              >
                Generer
              </Button>
            }
          >
            {previewPrompt ? (
              <VStack align="stretch" spacing={3}>
                <Code
                  p={4}
                  bg="bg.tertiary"
                  rounded="lg"
                  whiteSpace="pre-wrap"
                  display="block"
                  color="text.secondary"
                  border="1px solid"
                  borderColor="border.default"
                >
                  {previewPrompt}
                </Code>
                <Text fontSize="sm" color="text.muted">
                  Tokens estimes: ~{previewTokens}
                </Text>
              </VStack>
            ) : (
              <Text color="text.muted" textAlign="center" py={4}>
                Cliquez sur "Generer" pour voir le prompt qui sera injecte dans les LLM.
              </Text>
            )}

            {/* Pipeline Impact Summary */}
            <Box
              mt={4}
              p={4}
              bg="bg.tertiary"
              rounded="lg"
              border="1px solid"
              borderColor="border.default"
            >
              <Text fontSize="sm" fontWeight="semibold" color="text.primary" mb={3}>
                Impact pipeline
              </Text>
              <SimpleGrid columns={{ base: 2, md: 4 }} spacing={3}>
                <VStack spacing={1}>
                  <Text fontSize="2xl" fontWeight="bold" color="purple.400">
                    {pipelineImpact.expectedCount}
                  </Text>
                  <Text fontSize="xs" color="text.muted" textAlign="center">Axes expected</Text>
                </VStack>
                <VStack spacing={1}>
                  <Text fontSize="2xl" fontWeight="bold" color="red.400">
                    {pipelineImpact.excludedCount}
                  </Text>
                  <Text fontSize="xs" color="text.muted" textAlign="center">Axes excluded</Text>
                </VStack>
                <VStack spacing={1}>
                  <Text fontSize="2xl" fontWeight="bold" color="brand.400">
                    {pipelineImpact.rulesCount}
                  </Text>
                  <Text fontSize="xs" color="text.muted" textAlign="center">Regles reclassification</Text>
                </VStack>
                <VStack spacing={1}>
                  <Text fontSize="2xl" fontWeight="bold" color="yellow.400">
                    {pipelineImpact.overridesCount}
                  </Text>
                  <Text fontSize="xs" color="text.muted" textAlign="center">Overrides plausibilite</Text>
                </VStack>
              </SimpleGrid>

              {/* Errors */}
              {pipelineImpact.errors.length > 0 && (
                <Box mt={3} p={3} bg="rgba(239, 68, 68, 0.1)" rounded="md" border="1px solid" borderColor="rgba(239, 68, 68, 0.3)">
                  <HStack align="start" spacing={2}>
                    <Icon as={FiAlertTriangle} color="red.400" boxSize={4} mt={0.5} />
                    <VStack align="start" spacing={1}>
                      {pipelineImpact.errors.map((err, i) => (
                        <Text key={i} fontSize="xs" color="red.400">{err}</Text>
                      ))}
                    </VStack>
                  </HStack>
                </Box>
              )}
            </Box>
          </SectionCard>
        </MotionBox>

        {/* Save Button */}
        <MotionBox
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, delay: 0.4 }}
        >
          <HStack justify="flex-end">
            <Button
              leftIcon={<Icon as={FiSave} />}
              size="lg"
              bg="brand.500"
              color="white"
              onClick={handleSave}
              isLoading={saving}
              loadingText="Sauvegarde..."
              isDisabled={!formData.domain_summary || !formData.industry}
              _hover={{ bg: 'brand.600', transform: 'translateY(-2px)', boxShadow: '0 0 20px rgba(99, 102, 241, 0.4)' }}
              _active={{ transform: 'translateY(0)' }}
              transition="all 0.2s"
            >
              {existingContext ? 'Mettre a jour' : 'Sauvegarder'}
            </Button>
          </HStack>
        </MotionBox>
      </VStack>

      {/* Delete Modal */}
      <Modal isOpen={isDeleteOpen} onClose={onDeleteClose} isCentered>
        <ModalOverlay bg="rgba(0, 0, 0, 0.7)" backdropFilter="blur(4px)" />
        <ModalContent bg="bg.secondary" border="1px solid" borderColor="border.default" rounded="xl">
          <ModalHeader>
            <HStack>
              <Icon as={FiAlertTriangle} color="red.400" />
              <Text color="text.primary">Supprimer le Domain Context ?</Text>
            </HStack>
          </ModalHeader>
          <ModalCloseButton color="text.muted" />
          <ModalBody>
            <Text color="text.secondary">
              Cette action supprimera le contexte metier configure. L'instance reviendra en mode generique.
            </Text>
            <Text mt={3} fontWeight="medium" color="text.primary">
              Les documents deja importes ne seront pas affectes.
            </Text>
          </ModalBody>
          <ModalFooter gap={3}>
            <Button variant="ghost" onClick={onDeleteClose} _hover={{ bg: 'bg.hover' }}>
              Annuler
            </Button>
            <Button bg="red.500" color="white" onClick={handleDelete} _hover={{ bg: 'red.600' }}>
              Supprimer
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}
