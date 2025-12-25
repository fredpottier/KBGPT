'use client'

/**
 * OSMOS Domain Context - Dark Elegance Edition
 *
 * Premium business context configuration
 */

import { useState, useEffect } from 'react'
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
} from 'react-icons/fi'

const MotionBox = motion(Box)

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
}

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

// Section Card Component
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

// Status Badge
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

// Input style
const inputStyles = {
  bg: "bg.tertiary",
  border: "1px solid",
  borderColor: "border.default",
  rounded: "lg",
  color: "text.primary",
  _placeholder: { color: 'text.muted' },
  _hover: { borderColor: 'border.active' },
  _focus: {
    borderColor: 'brand.500',
    boxShadow: '0 0 0 1px var(--chakra-colors-brand-500)',
  },
}

export default function DomainContextPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [existingContext, setExistingContext] = useState<DomainContext | null>(null)
  const [previewPrompt, setPreviewPrompt] = useState<string>('')
  const [previewTokens, setPreviewTokens] = useState<number>(0)
  const { isOpen: isDeleteOpen, onOpen: onDeleteOpen, onClose: onDeleteClose } = useDisclosure()
  const toast = useToast()

  const [formData, setFormData] = useState<FormData>({
    domain_summary: '',
    industry: '',
    sub_domains: [],
    target_users: [],
    document_types: [],
    common_acronyms: {},
    key_concepts: [],
    context_priority: 'medium',
  })

  const [newSubDomain, setNewSubDomain] = useState('')
  const [newTargetUser, setNewTargetUser] = useState('')
  const [newDocType, setNewDocType] = useState('')
  const [newKeyConcept, setNewKeyConcept] = useState('')
  const [newAcronym, setNewAcronym] = useState('')
  const [newAcronymExpansion, setNewAcronymExpansion] = useState('')

  const currentPreset = formData.industry ? INDUSTRY_PRESETS[formData.industry] || INDUSTRY_PRESETS.other : null

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
    })
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
          domain_summary: data.domain_summary,
          industry: data.industry,
          sub_domains: data.sub_domains || [],
          target_users: data.target_users || [],
          document_types: data.document_types || [],
          common_acronyms: data.common_acronyms || {},
          key_concepts: data.key_concepts || [],
          context_priority: data.context_priority || 'medium',
        })
      }
    } catch (error) {
      console.error('Error loading domain context:', error)
    } finally {
      setLoading(false)
    }
  }

  const handlePreview = async () => {
    setPreviewing(true)
    try {
      const response = await fetch('/api/domain-context/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
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

    setSaving(true)
    try {
      const response = await fetch('/api/domain-context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
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
        setFormData({
          domain_summary: '', industry: '', sub_domains: [], target_users: [],
          document_types: [], common_acronyms: {}, key_concepts: [], context_priority: 'medium',
        })
        setPreviewPrompt('')
        toast({ title: 'Contexte supprime', status: 'info', duration: 3000, position: 'top' })
        onDeleteClose()
      }
    } catch (error) {
      console.error('Error deleting:', error)
    }
  }

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

        {/* Main Form */}
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
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('sub_domains', newSubDomain); setNewSubDomain('') }}}
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
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('key_concepts', newKeyConcept); setNewKeyConcept('') }}}
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
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addAcronym() }}}
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
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('target_users', newTargetUser); setNewTargetUser('') }}}
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
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addToArray('document_types', newDocType); setNewDocType('') }}}
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

        {/* Preview Section */}
        <MotionBox
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.3 }}
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
