'use client'

import { useState, useEffect } from 'react'
import {
  Box,
  Container,
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
  Card,
  CardHeader,
  CardBody,
  Divider,
  Badge,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
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
} from '@chakra-ui/react'
import { FiSave, FiTrash2, FiEye, FiRefreshCw, FiGlobe } from 'react-icons/fi'

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
  { value: 'healthcare', label: 'Santé / Healthcare' },
  { value: 'pharma_clinical', label: 'Pharma & Recherche Clinique (complet)' },
  { value: 'pharmaceutical', label: 'Pharmaceutique / Life Sciences' },
  { value: 'clinical_research', label: 'Recherche Clinique' },
  { value: 'finance', label: 'Finance / Banque' },
  { value: 'insurance', label: 'Assurance' },
  { value: 'retail', label: 'Retail / Commerce' },
  { value: 'manufacturing', label: 'Industrie / Manufacturing' },
  { value: 'technology', label: 'Technologie / IT' },
  { value: 'energy', label: 'Énergie' },
  { value: 'logistics', label: 'Logistique / Transport' },
  { value: 'education', label: 'Éducation' },
  { value: 'government', label: 'Secteur Public' },
  { value: 'legal', label: 'Juridique' },
  { value: 'other', label: 'Autre' },
]

// Presets de suggestions par industrie
interface IndustryPreset {
  descriptionPlaceholder: string
  subDomainsSuggestions: string[]
  keyConceptsSuggestions: string[]
  acronymsSuggestions: Record<string, string>
  targetUsersSuggestions: string[]
  documentTypesSuggestions: string[]
}

const INDUSTRY_PRESETS: Record<string, IndustryPreset> = {
  healthcare: {
    descriptionPlaceholder: "Organisation spécialisée dans les soins de santé. Nous gérons des données médicales sensibles (dossiers patients, prescriptions, résultats d'examens) et devons respecter les normes de confidentialité (RGPD, HDS).",
    subDomainsSuggestions: ['Télémédecine', 'Dossier patient', 'Imagerie médicale', 'Gestion hospitalière', 'Parcours de soins'],
    keyConceptsSuggestions: ['Dossier Médical Partagé', 'Parcours patient', 'Consentement éclairé', 'Acte médical', 'Prescription'],
    acronymsSuggestions: {
      'DMP': 'Dossier Médical Partagé',
      'HDS': 'Hébergeur de Données de Santé',
      'PMSI': 'Programme de Médicalisation des Systèmes d\'Information',
      'GHM': 'Groupe Homogène de Malades',
      'ALD': 'Affection Longue Durée',
    },
    targetUsersSuggestions: ['Médecins', 'Infirmiers', 'Personnel administratif', 'Patients'],
    documentTypesSuggestions: ['Comptes-rendus médicaux', 'Protocoles de soins', 'Ordonnances', 'Résultats d\'analyses'],
  },
  pharma_clinical: {
    descriptionPlaceholder: "Organization specializing in pharmaceutical industry and clinical research. We analyze clinical studies (phases I-IV), regulatory files (MAA, pharmacovigilance), trial protocols, and efficacy/safety reports.",
    subDomainsSuggestions: [
      'R&D', 'Affaires réglementaires', 'Pharmacovigilance', 'Production', 'Qualité', 'Commercial',
      'Oncologie', 'Cardiologie', 'Neurologie', 'Immunologie', 'Maladies rares', 'Vaccins', 'Dispositifs médicaux'
    ],
    keyConceptsSuggestions: [
      'Autorisation de Mise sur le Marché', 'Pharmacovigilance', 'Brevet', 'Molécule', 'Formulation galénique',
      'Phase clinique (I, II, III, IV)', 'Endpoint primaire / secondaire', 'Population ITT (Intent-to-Treat)',
      'Population PP (Per-Protocol)', 'Critères d\'inclusion/exclusion', 'Randomisation', 'Double-aveugle',
      'Placebo-contrôlé', 'Intervalle de confiance', 'Hazard Ratio', 'Overall Survival (OS)',
      'Progression-Free Survival (PFS)', 'Événements indésirables (EI/AE)', 'Événements indésirables graves (EIG/SAE)'
    ],
    acronymsSuggestions: {
      'AMM': 'Autorisation de Mise sur le Marché',
      'DCI': 'Dénomination Commune Internationale',
      'RCP': 'Résumé des Caractéristiques du Produit',
      'EMA': 'European Medicines Agency',
      'FDA': 'Food and Drug Administration',
      'GMP': 'Good Manufacturing Practices',
      'ICH': 'International Council for Harmonisation',
      'RCT': 'Randomized Controlled Trial',
      'ITT': 'Intent-to-Treat',
      'PP': 'Per-Protocol',
      'OS': 'Overall Survival',
      'PFS': 'Progression-Free Survival',
      'ORR': 'Overall Response Rate',
      'DLT': 'Dose-Limiting Toxicity',
      'MTD': 'Maximum Tolerated Dose',
      'AE': 'Adverse Event',
      'SAE': 'Serious Adverse Event',
      'ICF': 'Informed Consent Form',
      'CRF': 'Case Report Form',
      'IRB': 'Institutional Review Board',
      'IND': 'Investigational New Drug',
      'NDA': 'New Drug Application',
      'MAA': 'Marketing Authorization Application',
    },
    targetUsersSuggestions: ['Chercheurs', 'Affaires réglementaires', 'Pharmacovigilants', 'Clinical Research Associates', 'Biostatisticiens', 'Medical Writers', 'Quality Assurance'],
    documentTypesSuggestions: ['Protocoles d\'essai', 'Clinical Study Reports', 'Dossiers AMM', 'Rapports de pharmacovigilance', 'Statistical Analysis Plans', 'Formulaires de consentement'],
  },
  pharmaceutical: {
    descriptionPlaceholder: "Entreprise pharmaceutique développant et commercialisant des médicaments. Nous gérons des données réglementaires (AMM, pharmacovigilance), des études cliniques et de la documentation scientifique.",
    subDomainsSuggestions: ['R&D', 'Affaires réglementaires', 'Pharmacovigilance', 'Production', 'Qualité', 'Commercial'],
    keyConceptsSuggestions: ['Autorisation de Mise sur le Marché', 'Pharmacovigilance', 'Brevet', 'Molécule', 'Formulation galénique'],
    acronymsSuggestions: {
      'AMM': 'Autorisation de Mise sur le Marché',
      'DCI': 'Dénomination Commune Internationale',
      'RCP': 'Résumé des Caractéristiques du Produit',
      'EMA': 'European Medicines Agency',
      'FDA': 'Food and Drug Administration',
      'GMP': 'Good Manufacturing Practices',
      'ICH': 'International Council for Harmonisation',
    },
    targetUsersSuggestions: ['Chercheurs', 'Affaires réglementaires', 'Pharmacovigilants', 'Quality Assurance'],
    documentTypesSuggestions: ['Dossiers AMM', 'Rapports de pharmacovigilance', 'Fiches produit', 'Études de stabilité'],
  },
  clinical_research: {
    descriptionPlaceholder: "Organisation spécialisée dans la recherche clinique et le développement de médicaments. Nous analysons des études cliniques (phases I-IV), protocoles d'essais, rapports d'efficacité et de sécurité.",
    subDomainsSuggestions: ['Oncologie', 'Cardiologie', 'Neurologie', 'Immunologie', 'Maladies rares', 'Vaccins'],
    keyConceptsSuggestions: ['Phase clinique', 'Endpoint primaire', 'Population ITT', 'Randomisation', 'Double-aveugle', 'Hazard Ratio', 'Overall Survival', 'Progression-Free Survival'],
    acronymsSuggestions: {
      'RCT': 'Randomized Controlled Trial',
      'ITT': 'Intent-to-Treat',
      'PP': 'Per-Protocol',
      'OS': 'Overall Survival',
      'PFS': 'Progression-Free Survival',
      'ORR': 'Overall Response Rate',
      'DLT': 'Dose-Limiting Toxicity',
      'MTD': 'Maximum Tolerated Dose',
      'AE': 'Adverse Event',
      'SAE': 'Serious Adverse Event',
      'ICF': 'Informed Consent Form',
      'CRF': 'Case Report Form',
      'IRB': 'Institutional Review Board',
    },
    targetUsersSuggestions: ['Clinical Research Associates', 'Biostatisticiens', 'Medical Writers', 'Investigateurs'],
    documentTypesSuggestions: ['Protocoles d\'essai', 'Clinical Study Reports', 'Formulaires de consentement', 'Statistical Analysis Plans'],
  },
  finance: {
    descriptionPlaceholder: "Institution financière gérant des opérations bancaires, investissements et services financiers. Nous traitons des données réglementaires (Bâle III, MiFID II) et des analyses de marché.",
    subDomainsSuggestions: ['Banque de détail', 'Asset Management', 'Trading', 'Conformité', 'Risk Management', 'Crédit'],
    keyConceptsSuggestions: ['Ratio de solvabilité', 'Risque de crédit', 'Liquidité', 'KYC', 'AML', 'Stress test'],
    acronymsSuggestions: {
      'KYC': 'Know Your Customer',
      'AML': 'Anti-Money Laundering',
      'PNL': 'Profit and Loss',
      'NAV': 'Net Asset Value',
      'ROI': 'Return On Investment',
      'VaR': 'Value at Risk',
      'MiFID': 'Markets in Financial Instruments Directive',
      'UCITS': 'Undertakings for Collective Investment in Transferable Securities',
    },
    targetUsersSuggestions: ['Traders', 'Analystes financiers', 'Risk managers', 'Compliance officers'],
    documentTypesSuggestions: ['Rapports de gestion', 'Analyses de risque', 'Prospectus', 'États financiers'],
  },
  insurance: {
    descriptionPlaceholder: "Compagnie d'assurance proposant des produits d'assurance vie, santé, et dommages. Nous gérons des contrats, sinistres et analyses actuarielles.",
    subDomainsSuggestions: ['Assurance vie', 'Assurance santé', 'IARD', 'Réassurance', 'Actuariat', 'Indemnisation'],
    keyConceptsSuggestions: ['Prime', 'Sinistre', 'Franchise', 'Provision technique', 'Table de mortalité', 'Solvabilité II'],
    acronymsSuggestions: {
      'IARD': 'Incendie, Accidents et Risques Divers',
      'S/P': 'Sinistres sur Primes',
      'PSAP': 'Provision pour Sinistres À Payer',
      'SCR': 'Solvency Capital Requirement',
      'MCR': 'Minimum Capital Requirement',
      'ORSA': 'Own Risk and Solvency Assessment',
    },
    targetUsersSuggestions: ['Actuaires', 'Souscripteurs', 'Gestionnaires de sinistres', 'Agents commerciaux'],
    documentTypesSuggestions: ['Contrats d\'assurance', 'Rapports de sinistres', 'Études actuarielles', 'Conditions générales'],
  },
  retail: {
    descriptionPlaceholder: "Entreprise de distribution et commerce de détail. Nous gérons des catalogues produits, des données de vente et de logistique, ainsi que des analyses de comportement client.",
    subDomainsSuggestions: ['E-commerce', 'Supply chain', 'Merchandising', 'CRM', 'Pricing', 'Fidélité'],
    keyConceptsSuggestions: ['Panier moyen', 'Taux de conversion', 'Stock', 'Marge brute', 'Category management'],
    acronymsSuggestions: {
      'SKU': 'Stock Keeping Unit',
      'UGS': 'Unité de Gestion de Stock',
      'PLV': 'Publicité sur Lieu de Vente',
      'NPS': 'Net Promoter Score',
      'CAC': 'Coût d\'Acquisition Client',
      'LTV': 'Lifetime Value',
    },
    targetUsersSuggestions: ['Category managers', 'Supply chain managers', 'Responsables marketing', 'Chefs de rayon'],
    documentTypesSuggestions: ['Fiches produit', 'Analyses de ventes', 'Rapports de stock', 'Études de marché'],
  },
  manufacturing: {
    descriptionPlaceholder: "Entreprise industrielle spécialisée dans la fabrication et production. Nous gérons des processus de production, qualité, maintenance et supply chain.",
    subDomainsSuggestions: ['Production', 'Qualité', 'Maintenance', 'Supply chain', 'R&D', 'HSE'],
    keyConceptsSuggestions: ['Ordre de fabrication', 'Gamme de production', 'Non-conformité', 'TRS', 'Lean manufacturing'],
    acronymsSuggestions: {
      'OEE': 'Overall Equipment Effectiveness',
      'TRS': 'Taux de Rendement Synthétique',
      'MES': 'Manufacturing Execution System',
      'GMAO': 'Gestion de Maintenance Assistée par Ordinateur',
      'HSE': 'Hygiène Sécurité Environnement',
      'AMDEC': 'Analyse des Modes de Défaillance et de leurs Effets et Criticité',
    },
    targetUsersSuggestions: ['Responsables production', 'Qualiticiens', 'Techniciens maintenance', 'Ingénieurs méthodes'],
    documentTypesSuggestions: ['Gammes de fabrication', 'Rapports de non-conformité', 'Fiches de maintenance', 'Cahiers des charges'],
  },
  technology: {
    descriptionPlaceholder: "Entreprise technologique développant des logiciels et solutions IT. Nous gérons de la documentation technique, des spécifications et de l'architecture système.",
    subDomainsSuggestions: ['Développement', 'Infrastructure', 'Cybersécurité', 'Cloud', 'Data', 'DevOps'],
    keyConceptsSuggestions: ['Architecture microservices', 'API REST', 'CI/CD', 'Kubernetes', 'Machine Learning'],
    acronymsSuggestions: {
      'API': 'Application Programming Interface',
      'CI/CD': 'Continuous Integration / Continuous Deployment',
      'SaaS': 'Software as a Service',
      'MVP': 'Minimum Viable Product',
      'SLA': 'Service Level Agreement',
      'RGPD': 'Règlement Général sur la Protection des Données',
    },
    targetUsersSuggestions: ['Développeurs', 'DevOps', 'Architectes', 'Product managers'],
    documentTypesSuggestions: ['Spécifications techniques', 'Documentation API', 'Runbooks', 'Post-mortems'],
  },
  energy: {
    descriptionPlaceholder: "Entreprise du secteur énergétique (production, distribution, ou services). Nous gérons des données de production, de consommation, de maintenance d'installations et de conformité environnementale.",
    subDomainsSuggestions: ['Production', 'Distribution', 'Énergies renouvelables', 'Nucléaire', 'Smart grid', 'Efficacité énergétique'],
    keyConceptsSuggestions: ['Mix énergétique', 'Capacité installée', 'Facteur de charge', 'Certificat vert', 'Bilan carbone'],
    acronymsSuggestions: {
      'GES': 'Gaz à Effet de Serre',
      'EnR': 'Énergies Renouvelables',
      'PV': 'Photovoltaïque',
      'REE': 'Responsabilité Élargie du Producteur',
      'CSPE': 'Contribution au Service Public de l\'Électricité',
      'TURPE': 'Tarif d\'Utilisation des Réseaux Publics d\'Électricité',
    },
    targetUsersSuggestions: ['Ingénieurs exploitation', 'Traders énergie', 'Responsables environnement', 'Techniciens maintenance'],
    documentTypesSuggestions: ['Rapports de production', 'Études d\'impact', 'Bilans énergétiques', 'Audits de conformité'],
  },
  logistics: {
    descriptionPlaceholder: "Entreprise de logistique et transport. Nous gérons des flux de marchandises, entrepôts, livraisons et documentation douanière.",
    subDomainsSuggestions: ['Transport routier', 'Transport maritime', 'Entreposage', 'Douane', 'Last mile', 'Reverse logistics'],
    keyConceptsSuggestions: ['Incoterm', 'Lettre de voiture', 'Bon de livraison', 'Cross-docking', 'Taux de service'],
    acronymsSuggestions: {
      'WMS': 'Warehouse Management System',
      'TMS': 'Transport Management System',
      'BL': 'Bill of Lading',
      'CMR': 'Convention relative au contrat de transport international de Marchandises par Route',
      'DEB': 'Déclaration d\'Échanges de Biens',
      'AWB': 'Air Waybill',
    },
    targetUsersSuggestions: ['Responsables logistique', 'Déclarants en douane', 'Chauffeurs', 'Gestionnaires d\'entrepôt'],
    documentTypesSuggestions: ['Lettres de voiture', 'Documents douaniers', 'Bons de livraison', 'États de stock'],
  },
  education: {
    descriptionPlaceholder: "Organisation éducative (université, école, centre de formation). Nous gérons des contenus pédagogiques, évaluations, parcours de formation et données étudiantes.",
    subDomainsSuggestions: ['Formation initiale', 'Formation continue', 'E-learning', 'Recherche', 'Vie étudiante'],
    keyConceptsSuggestions: ['Maquette pédagogique', 'ECTS', 'Compétence', 'Évaluation', 'Certification'],
    acronymsSuggestions: {
      'ECTS': 'European Credits Transfer System',
      'LMS': 'Learning Management System',
      'MOOC': 'Massive Open Online Course',
      'VAE': 'Validation des Acquis de l\'Expérience',
      'RNCP': 'Répertoire National des Certifications Professionnelles',
    },
    targetUsersSuggestions: ['Enseignants', 'Étudiants', 'Responsables pédagogiques', 'Administratifs'],
    documentTypesSuggestions: ['Programmes de cours', 'Supports pédagogiques', 'Examens', 'Rapports de stage'],
  },
  government: {
    descriptionPlaceholder: "Administration publique ou collectivité territoriale. Nous gérons des données citoyennes, des procédures administratives et des documents réglementaires.",
    subDomainsSuggestions: ['État civil', 'Urbanisme', 'Social', 'Fiscalité', 'Marchés publics', 'Services aux citoyens'],
    keyConceptsSuggestions: ['Délibération', 'Arrêté', 'Dématérialisation', 'RGPD', 'Open data'],
    acronymsSuggestions: {
      'DGFIP': 'Direction Générale des Finances Publiques',
      'CAF': 'Caisse d\'Allocations Familiales',
      'DSP': 'Délégation de Service Public',
      'PLU': 'Plan Local d\'Urbanisme',
      'CADA': 'Commission d\'Accès aux Documents Administratifs',
    },
    targetUsersSuggestions: ['Agents administratifs', 'Élus', 'Citoyens', 'Responsables de service'],
    documentTypesSuggestions: ['Délibérations', 'Arrêtés', 'Comptes-rendus de conseil', 'Documents d\'urbanisme'],
  },
  legal: {
    descriptionPlaceholder: "Cabinet juridique ou service juridique d'entreprise. Nous gérons des contrats, contentieux, veille juridique et documentation réglementaire.",
    subDomainsSuggestions: ['Droit des affaires', 'Droit social', 'Propriété intellectuelle', 'Contentieux', 'M&A', 'Compliance'],
    keyConceptsSuggestions: ['Contrat', 'Clause', 'Jurisprudence', 'Mise en demeure', 'Due diligence'],
    acronymsSuggestions: {
      'NDA': 'Non-Disclosure Agreement',
      'LOI': 'Letter of Intent',
      'SPA': 'Share Purchase Agreement',
      'CGV': 'Conditions Générales de Vente',
      'CNIL': 'Commission Nationale de l\'Informatique et des Libertés',
    },
    targetUsersSuggestions: ['Avocats', 'Juristes d\'entreprise', 'Paralegals', 'Compliance officers'],
    documentTypesSuggestions: ['Contrats', 'Actes juridiques', 'Conclusions', 'Notes de veille'],
  },
  other: {
    descriptionPlaceholder: "Décrivez le domaine d'activité de votre organisation, les types de données que vous traitez, et les objectifs d'extraction de connaissances.",
    subDomainsSuggestions: [],
    keyConceptsSuggestions: [],
    acronymsSuggestions: {},
    targetUsersSuggestions: [],
    documentTypesSuggestions: [],
  },
}

export default function DomainContextPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
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

  // Temporary input states for adding items
  const [newSubDomain, setNewSubDomain] = useState('')
  const [newTargetUser, setNewTargetUser] = useState('')
  const [newDocType, setNewDocType] = useState('')
  const [newKeyConcept, setNewKeyConcept] = useState('')
  const [newAcronym, setNewAcronym] = useState('')
  const [newAcronymExpansion, setNewAcronymExpansion] = useState('')

  // Get current industry preset
  const currentPreset = formData.industry ? INDUSTRY_PRESETS[formData.industry] : null

  // Handler for industry change - updates placeholder suggestions
  const handleIndustryChange = (newIndustry: string) => {
    setFormData({ ...formData, industry: newIndustry })
  }

  // Apply all suggestions from preset
  const applyAllSuggestions = () => {
    if (!currentPreset) return
    setFormData({
      ...formData,
      sub_domains: [...new Set([...formData.sub_domains, ...currentPreset.subDomainsSuggestions])],
      key_concepts: [...new Set([...formData.key_concepts, ...currentPreset.keyConceptsSuggestions])],
      target_users: [...new Set([...formData.target_users, ...currentPreset.targetUsersSuggestions])],
      document_types: [...new Set([...formData.document_types, ...currentPreset.documentTypesSuggestions])],
      common_acronyms: { ...currentPreset.acronymsSuggestions, ...formData.common_acronyms },
    })
  }

  // Apply suggestions for a specific field
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
        toast({
          title: 'Aperçu généré',
          status: 'success',
          duration: 2000,
        })
      } else {
        const error = await response.json()
        toast({
          title: 'Erreur de prévisualisation',
          description: error.detail || `Erreur ${response.status}`,
          status: 'error',
          duration: 5000,
        })
      }
    } catch (error: any) {
      console.error('Error previewing:', error)
      toast({
        title: 'Erreur de connexion',
        description: error.message || 'Impossible de contacter le serveur',
        status: 'error',
        duration: 5000,
      })
    }
  }

  const handleSave = async () => {
    if (!formData.domain_summary || !formData.industry) {
      toast({
        title: 'Champs requis manquants',
        description: 'Le résumé du domaine et l\'industrie sont obligatoires.',
        status: 'warning',
        duration: 3000,
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
        toast({
          title: 'Contexte sauvegardé',
          description: 'Le Domain Context a été configuré avec succès.',
          status: 'success',
          duration: 3000,
        })
      } else {
        const error = await response.json()
        throw new Error(error.detail || 'Erreur inconnue')
      }
    } catch (error: any) {
      toast({
        title: 'Erreur',
        description: error.message,
        status: 'error',
        duration: 5000,
      })
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
          domain_summary: '',
          industry: '',
          sub_domains: [],
          target_users: [],
          document_types: [],
          common_acronyms: {},
          key_concepts: [],
          context_priority: 'medium',
        })
        setPreviewPrompt('')
        toast({
          title: 'Contexte supprimé',
          description: 'L\'instance est maintenant en mode générique (domain-agnostic).',
          status: 'info',
          duration: 3000,
        })
        onDeleteClose()
      }
    } catch (error) {
      console.error('Error deleting:', error)
    }
  }

  // Helper functions to add/remove items from arrays
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
      common_acronyms: {
        ...formData.common_acronyms,
        [newAcronym.trim().toUpperCase()]: newAcronymExpansion.trim()
      }
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
      <Container maxW="container.xl" py={8}>
        <VStack spacing={4}>
          <Spinner size="xl" />
          <Text>Chargement du Domain Context...</Text>
        </VStack>
      </Container>
    )
  }

  return (
    <Container maxW="container.xl" py={8}>
      <VStack spacing={6} align="stretch">
        {/* Header */}
        <HStack justify="space-between" wrap="wrap" gap={4}>
          <VStack align="start" spacing={1}>
            <HStack>
              <FiGlobe size={24} />
              <Heading size="lg">Domain Context</Heading>
              {existingContext && (
                <Badge colorScheme="green" ml={2}>Configuré</Badge>
              )}
              {!existingContext && (
                <Badge colorScheme="gray" ml={2}>Non configuré</Badge>
              )}
            </HStack>
            <Text color="gray.600">
              Configurez le contexte métier global de votre instance pour améliorer la précision de l'extraction.
            </Text>
          </VStack>
          <HStack>
            <Button
              leftIcon={<FiRefreshCw />}
              variant="ghost"
              onClick={loadDomainContext}
            >
              Actualiser
            </Button>
            {existingContext && (
              <Button
                leftIcon={<FiTrash2 />}
                colorScheme="red"
                variant="outline"
                onClick={onDeleteOpen}
              >
                Supprimer
              </Button>
            )}
          </HStack>
        </HStack>

        {/* Info Alert */}
        <Alert status="info" borderRadius="md">
          <AlertIcon />
          <Box>
            <AlertTitle>Comment ça fonctionne ?</AlertTitle>
            <AlertDescription>
              Le Domain Context est injecté automatiquement dans tous les prompts LLM lors de l'extraction de documents.
              Il aide le système à mieux comprendre votre domaine métier, reconnaître les acronymes et concepts clés,
              et produire des extractions plus précises.
            </AlertDescription>
          </Box>
        </Alert>

        {/* Main Form */}
        <Card>
          <CardHeader>
            <Heading size="md">Configuration du contexte</Heading>
          </CardHeader>
          <CardBody>
            <VStack spacing={6} align="stretch">
              {/* Industry - FIRST to drive suggestions */}
              <FormControl isRequired>
                <FormLabel>Industrie</FormLabel>
                <Select
                  value={formData.industry}
                  onChange={(e) => handleIndustryChange(e.target.value)}
                  placeholder="Sélectionnez une industrie"
                >
                  {INDUSTRY_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </Select>
                <FormHelperText>
                  Sélectionnez d'abord l'industrie pour obtenir des suggestions contextualisées
                </FormHelperText>
              </FormControl>

              {/* Apply all suggestions button */}
              {currentPreset && currentPreset.subDomainsSuggestions.length > 0 && (
                <Alert status="info" borderRadius="md">
                  <AlertIcon />
                  <Box flex="1">
                    <AlertTitle fontSize="sm">Suggestions disponibles pour cette industrie</AlertTitle>
                    <AlertDescription fontSize="sm">
                      Des suggestions de sous-domaines, concepts, acronymes et plus sont disponibles.
                    </AlertDescription>
                  </Box>
                  <Button size="sm" colorScheme="blue" onClick={applyAllSuggestions}>
                    Appliquer toutes les suggestions
                  </Button>
                </Alert>
              )}

              {/* Domain Summary */}
              <FormControl isRequired>
                <FormLabel>Description du domaine</FormLabel>
                <Textarea
                  value={formData.domain_summary}
                  onChange={(e) => setFormData({ ...formData, domain_summary: e.target.value })}
                  placeholder={currentPreset?.descriptionPlaceholder || "Describe your organization's business domain, the types of data you process, and knowledge extraction objectives."}
                  rows={4}
                  maxLength={500}
                />
                <FormHelperText>
                  {formData.domain_summary.length}/500 caractères •
                  <Text as="span" color="blue.500" ml={1}>
                    Recommandé en anglais pour cohérence avec les prompts LLM
                  </Text>
                </FormHelperText>
              </FormControl>

              {/* Sub-domains */}
              <FormControl>
                <HStack justify="space-between" mb={2}>
                  <FormLabel mb={0}>Sous-domaines</FormLabel>
                  {currentPreset && currentPreset.subDomainsSuggestions.length > 0 && (
                    <Button size="xs" variant="ghost" colorScheme="blue" onClick={() => applySuggestions('sub_domains')}>
                      + Ajouter suggestions ({currentPreset.subDomainsSuggestions.length})
                    </Button>
                  )}
                </HStack>
                <HStack mb={2}>
                  <Input
                    value={newSubDomain}
                    onChange={(e) => setNewSubDomain(e.target.value)}
                    placeholder={currentPreset?.subDomainsSuggestions[0] ? `Ex: ${currentPreset.subDomainsSuggestions[0]}` : "Ex: sous-domaine d'expertise"}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addToArray('sub_domains', newSubDomain)
                        setNewSubDomain('')
                      }
                    }}
                  />
                  <Button onClick={() => { addToArray('sub_domains', newSubDomain); setNewSubDomain('') }}>
                    Ajouter
                  </Button>
                </HStack>
                <Wrap>
                  {formData.sub_domains.map(sd => (
                    <WrapItem key={sd}>
                      <Tag colorScheme="blue">
                        <TagLabel>{sd}</TagLabel>
                        <TagCloseButton onClick={() => removeFromArray('sub_domains', sd)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
                {currentPreset && currentPreset.subDomainsSuggestions.length > 0 && formData.sub_domains.length === 0 && (
                  <FormHelperText>
                    Suggestions: {currentPreset.subDomainsSuggestions.slice(0, 3).join(', ')}...
                  </FormHelperText>
                )}
              </FormControl>

              {/* Key Concepts */}
              <FormControl>
                <HStack justify="space-between" mb={2}>
                  <FormLabel mb={0}>Concepts clés à reconnaître</FormLabel>
                  {currentPreset && currentPreset.keyConceptsSuggestions.length > 0 && (
                    <Button size="xs" variant="ghost" colorScheme="purple" onClick={() => applySuggestions('key_concepts')}>
                      + Ajouter suggestions ({currentPreset.keyConceptsSuggestions.length})
                    </Button>
                  )}
                </HStack>
                <HStack mb={2}>
                  <Input
                    value={newKeyConcept}
                    onChange={(e) => setNewKeyConcept(e.target.value)}
                    placeholder={currentPreset?.keyConceptsSuggestions[0] ? `Ex: ${currentPreset.keyConceptsSuggestions[0]}` : "Ex: concept métier important"}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addToArray('key_concepts', newKeyConcept)
                        setNewKeyConcept('')
                      }
                    }}
                  />
                  <Button onClick={() => { addToArray('key_concepts', newKeyConcept); setNewKeyConcept('') }}>
                    Ajouter
                  </Button>
                </HStack>
                <Wrap>
                  {formData.key_concepts.map(kc => (
                    <WrapItem key={kc}>
                      <Tag colorScheme="purple">
                        <TagLabel>{kc}</TagLabel>
                        <TagCloseButton onClick={() => removeFromArray('key_concepts', kc)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
                {currentPreset && currentPreset.keyConceptsSuggestions.length > 0 && formData.key_concepts.length === 0 && (
                  <FormHelperText>
                    Suggestions: {currentPreset.keyConceptsSuggestions.slice(0, 3).join(', ')}...
                  </FormHelperText>
                )}
                <FormHelperText>Ajoutez autant de concepts que nécessaire</FormHelperText>
              </FormControl>

              <Divider />

              {/* Acronyms */}
              <FormControl>
                <HStack justify="space-between" mb={2}>
                  <FormLabel mb={0}>Acronymes du domaine</FormLabel>
                  {currentPreset && Object.keys(currentPreset.acronymsSuggestions).length > 0 && (
                    <Button size="xs" variant="ghost" colorScheme="teal" onClick={applyAcronymsSuggestions}>
                      + Ajouter suggestions ({Object.keys(currentPreset.acronymsSuggestions).length})
                    </Button>
                  )}
                </HStack>
                <HStack mb={2}>
                  <Input
                    value={newAcronym}
                    onChange={(e) => setNewAcronym(e.target.value)}
                    placeholder={currentPreset && Object.keys(currentPreset.acronymsSuggestions)[0] ? `Ex: ${Object.keys(currentPreset.acronymsSuggestions)[0]}` : "Acronyme"}
                    width="150px"
                  />
                  <Input
                    value={newAcronymExpansion}
                    onChange={(e) => setNewAcronymExpansion(e.target.value)}
                    placeholder={currentPreset && Object.values(currentPreset.acronymsSuggestions)[0] ? `Ex: ${Object.values(currentPreset.acronymsSuggestions)[0]}` : "Expansion complète"}
                    flex={1}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addAcronym()
                      }
                    }}
                  />
                  <Button onClick={addAcronym}>Ajouter</Button>
                </HStack>
                <Wrap>
                  {Object.entries(formData.common_acronyms).map(([key, value]) => (
                    <WrapItem key={key}>
                      <Tag colorScheme="teal">
                        <TagLabel><strong>{key}</strong>: {value}</TagLabel>
                        <TagCloseButton onClick={() => removeAcronym(key)} />
                      </Tag>
                    </WrapItem>
                  ))}
                </Wrap>
                {currentPreset && Object.keys(currentPreset.acronymsSuggestions).length > 0 && Object.keys(formData.common_acronyms).length === 0 && (
                  <FormHelperText>
                    Suggestions: {Object.keys(currentPreset.acronymsSuggestions).slice(0, 4).join(', ')}...
                  </FormHelperText>
                )}
                <FormHelperText>Ajoutez autant d'acronymes que nécessaire (max 100)</FormHelperText>
              </FormControl>

              <Divider />

              {/* Priority */}
              <FormControl>
                <FormLabel>Priorité d'injection</FormLabel>
                <Select
                  value={formData.context_priority}
                  onChange={(e) => setFormData({ ...formData, context_priority: e.target.value as any })}
                >
                  <option value="low">Basse - Industrie + description seulement (~50 tokens)</option>
                  <option value="medium">Moyenne - + 5 sous-domaines, 8 concepts, 5 acronymes (~150 tokens)</option>
                  <option value="high">Haute - + 10 sous-domaines, 15 concepts, 20 acronymes (~300 tokens)</option>
                </Select>
                <FormHelperText>
                  Plus la priorité est haute, plus le contexte injecté est détaillé (mais consomme plus de tokens)
                </FormHelperText>
              </FormControl>

              {/* Target Users (optional) */}
              <Accordion allowToggle>
                <AccordionItem border="none">
                  <AccordionButton px={0}>
                    <Box flex="1" textAlign="left">
                      <Text fontWeight="medium">Options avancées</Text>
                    </Box>
                    <AccordionIcon />
                  </AccordionButton>
                  <AccordionPanel px={0}>
                    <VStack spacing={4} align="stretch">
                      <FormControl>
                        <HStack justify="space-between" mb={2}>
                          <FormLabel mb={0}>Utilisateurs cibles</FormLabel>
                          {currentPreset && currentPreset.targetUsersSuggestions.length > 0 && (
                            <Button size="xs" variant="ghost" colorScheme="orange" onClick={() => applySuggestions('target_users')}>
                              + Ajouter suggestions ({currentPreset.targetUsersSuggestions.length})
                            </Button>
                          )}
                        </HStack>
                        <HStack mb={2}>
                          <Input
                            value={newTargetUser}
                            onChange={(e) => setNewTargetUser(e.target.value)}
                            placeholder={currentPreset?.targetUsersSuggestions[0] ? `Ex: ${currentPreset.targetUsersSuggestions[0]}` : "Ex: type d'utilisateur"}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                addToArray('target_users', newTargetUser)
                                setNewTargetUser('')
                              }
                            }}
                          />
                          <Button onClick={() => { addToArray('target_users', newTargetUser); setNewTargetUser('') }}>
                            Ajouter
                          </Button>
                        </HStack>
                        <Wrap>
                          {formData.target_users.map(tu => (
                            <WrapItem key={tu}>
                              <Tag colorScheme="orange">
                                <TagLabel>{tu}</TagLabel>
                                <TagCloseButton onClick={() => removeFromArray('target_users', tu)} />
                              </Tag>
                            </WrapItem>
                          ))}
                        </Wrap>
                        {currentPreset && currentPreset.targetUsersSuggestions.length > 0 && formData.target_users.length === 0 && (
                          <FormHelperText>
                            Suggestions: {currentPreset.targetUsersSuggestions.slice(0, 3).join(', ')}...
                          </FormHelperText>
                        )}
                      </FormControl>

                      <FormControl>
                        <HStack justify="space-between" mb={2}>
                          <FormLabel mb={0}>Types de documents traités</FormLabel>
                          {currentPreset && currentPreset.documentTypesSuggestions.length > 0 && (
                            <Button size="xs" variant="ghost" colorScheme="cyan" onClick={() => applySuggestions('document_types')}>
                              + Ajouter suggestions ({currentPreset.documentTypesSuggestions.length})
                            </Button>
                          )}
                        </HStack>
                        <HStack mb={2}>
                          <Input
                            value={newDocType}
                            onChange={(e) => setNewDocType(e.target.value)}
                            placeholder={currentPreset?.documentTypesSuggestions[0] ? `Ex: ${currentPreset.documentTypesSuggestions[0]}` : "Ex: type de document"}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                addToArray('document_types', newDocType)
                                setNewDocType('')
                              }
                            }}
                          />
                          <Button onClick={() => { addToArray('document_types', newDocType); setNewDocType('') }}>
                            Ajouter
                          </Button>
                        </HStack>
                        <Wrap>
                          {formData.document_types.map(dt => (
                            <WrapItem key={dt}>
                              <Tag colorScheme="cyan">
                                <TagLabel>{dt}</TagLabel>
                                <TagCloseButton onClick={() => removeFromArray('document_types', dt)} />
                              </Tag>
                            </WrapItem>
                          ))}
                        </Wrap>
                        {currentPreset && currentPreset.documentTypesSuggestions.length > 0 && formData.document_types.length === 0 && (
                          <FormHelperText>
                            Suggestions: {currentPreset.documentTypesSuggestions.slice(0, 3).join(', ')}...
                          </FormHelperText>
                        )}
                      </FormControl>
                    </VStack>
                  </AccordionPanel>
                </AccordionItem>
              </Accordion>
            </VStack>
          </CardBody>
        </Card>

        {/* Preview Section */}
        <Card>
          <CardHeader>
            <HStack justify="space-between">
              <Heading size="md">Aperçu du prompt d'injection</Heading>
              <Button
                leftIcon={<FiEye />}
                onClick={handlePreview}
                size="sm"
                isDisabled={!formData.domain_summary || !formData.industry}
              >
                Générer l'aperçu
              </Button>
            </HStack>
          </CardHeader>
          <CardBody>
            {previewPrompt ? (
              <VStack align="stretch" spacing={3}>
                <Code p={4} borderRadius="md" whiteSpace="pre-wrap" display="block">
                  {previewPrompt}
                </Code>
                <Text fontSize="sm" color="gray.600">
                  Tokens estimés: ~{previewTokens}
                </Text>
              </VStack>
            ) : (
              <Text color="gray.500">
                Cliquez sur "Générer l'aperçu" pour voir le prompt qui sera injecté dans les LLM.
              </Text>
            )}
          </CardBody>
        </Card>

        {/* Save Button */}
        <HStack justify="flex-end">
          <Button
            leftIcon={<FiSave />}
            colorScheme="blue"
            size="lg"
            onClick={handleSave}
            isLoading={saving}
            isDisabled={!formData.domain_summary || !formData.industry}
          >
            {existingContext ? 'Mettre à jour' : 'Sauvegarder'}
          </Button>
        </HStack>

        {/* Delete Confirmation Modal */}
        <Modal isOpen={isDeleteOpen} onClose={onDeleteClose}>
          <ModalOverlay />
          <ModalContent>
            <ModalHeader>Supprimer le Domain Context ?</ModalHeader>
            <ModalCloseButton />
            <ModalBody>
              <Text>
                Cette action supprimera le contexte métier configuré. L'instance reviendra en mode
                générique (domain-agnostic) et les extractions futures seront moins spécialisées.
              </Text>
              <Text mt={2} fontWeight="bold">
                Les documents déjà importés ne seront pas affectés.
              </Text>
            </ModalBody>
            <ModalFooter>
              <Button variant="ghost" mr={3} onClick={onDeleteClose}>
                Annuler
              </Button>
              <Button colorScheme="red" onClick={handleDelete}>
                Supprimer
              </Button>
            </ModalFooter>
          </ModalContent>
        </Modal>
      </VStack>
    </Container>
  )
}
