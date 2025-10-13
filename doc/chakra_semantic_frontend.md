# Modern Admin Frontend - Mantine + Semantic Intelligence KG

**Vision:** Interface d'administration intelligente qui s'adapte à l'architecture semantic intelligence, avec Mantine comme foundation moderne pour dashboards temps réel, UX enterprise-grade, performance optimisée et workflows intuitifs avec drag & drop natifs.

**Philosophie Design:** Moins de clics, plus d'insights. L'interface révèle la structure sémantique du KG au lieu de la cacher derrière des tableaux, en exploitant la puissance native de Mantine pour les applications dashboard complexes.

## Pourquoi Mantine vs ChakraUI pour ce Projet

### Avantages Décisifs pour Dashboard Semantic Intelligence

**Dashboard-First Design**
- 100+ composants optimisés pour applications data-intensive
- DataTable native avec tri/filtrage/groupement avancés
- Notifications système temps réel intégrées
- Rich Text Editor pour documentation inline

**Performance Enterprise**
- Croissance +1900% (25k → 500k téléchargements/semaine)
- Bundle size optimisé avec tree-shaking intelligent
- Memoization native pour éviter re-renders inutiles
- Server-Side Rendering support complet

**Interactions Avancées Natives**
- Hooks drag & drop intégrés (useMove, useListState)
- Touch/mobile support out-of-the-box
- Keyboard navigation enterprise-grade
- Multi-select avec actions bulk natives

**Developer Experience Supérieur**
- TypeScript-first avec inférence de types complète
- Theme engine plus puissant que ChakraUI
- 50+ hooks utilitaires vs développement custom
- Documentation avec exemples interactifs

### Comparaison Technique

| Aspect | Mantine | ChakraUI |
|--------|---------|----------|
| **Dashboard Components** | DataTable, Charts, Timeline natifs | Nécessite librairies externes |
| **Real-time Updates** | Notifications + hooks optimisés | Toast basique + développement custom |
| **Drag & Drop** | useMove, useDrag hooks natifs | Nécessite react-dnd ou dnd-kit |
| **Data Visualization** | Intégration recharts optimisée | Configuration manuelle requise |
| **Enterprise Features** | Spotlight search, Command palette | Développement from scratch |
| **Bundle Size** | 140kb (core) | 180kb (équivalent) |
| **TypeScript** | 100% natif | Support ajouté |

### Stratégies d'Adoption

**Option 1: Migration Progressive (Recommandée)**
- Migration composant par composant sur 8-12 semaines
- Thème Mantine adapté aux couleurs ChakraUI existantes
- Coexistence temporaire possible pendant transition
- ROI visible dès les premiers composants dashboard migré

**Option 2: Approche Hybride**
- Garder ChakraUI pour layouts/navigation de base
- Mantine pour composants dashboard avancés uniquement
- Migration sélective des pages à forte valeur ajoutée
- Intégration via providers séparés

---

## Architecture Frontend Mantine Globale

### Stratégie Mantine Dashboard-First

**Foundation (90% Mantine natif)**
- Layout système : `Container`, `Grid`, `SimpleGrid`, `Stack`, `AppShell`
- Navigation : `Navbar`, `Breadcrumbs`, `Tabs`, `Drawer` avec Spotlight search
- Formulaires : `TextInput`, `Select`, `DatePicker`, `Form` avec validation
- Dashboard data : `DataTable`, `ScrollArea`, `ActionIcon`, `Stats`
- Real-time : `Notifications`, `Loader`, `Progress` optimisés

**Composants Avancés Natifs (8% Mantine spécialisé)**
- Interactions : `useMove`, `useDrag` hooks pour drag & drop
- Data viz : Recharts intégration optimisée dans `Paper`
- Rich content : `RichTextEditor`, `CodeHighlight` 
- Enterprise : `CommandPalette`, `Spotlight`, `Affix`

**Custom Visualizations (2% spécialisé)**
- Entity constellation explorer (D3 + Mantine theming)
- Network graph avec Mantine overlays
- Semantic metrics dashboard personnalisés

### Theme Sémantique Mantine + Migration Strategy

```typescript
import { createTheme, MantineProvider } from '@mantine/core'
import { DataTable } from '@mantine/datatable'
import { Notifications } from '@mantine/notifications'

// Theme sémantique personnalisé - Compatible migration ChakraUI
const semanticIntelligenceTheme = createTheme({
  colors: {
    semantic: [
      "#E6F3FF", "#BAE0FF", "#7CC4FA", "#4299E1", // Intelligence (compatible Chakra blue)
      "#B8E6B8", "#85D185", "#48BB78", "#2F855A", // Quality (compatible Chakra green) 
      "#FFE5B8", "#FFCC80", "#ED8936", "#C05621", // Warning (compatible Chakra orange)
      "#FFB8B8", "#FF8080", "#F56565", "#E53E3E"  // Critical (compatible Chakra red)
    ]
  },
  
  components: {
    Paper: {
      defaultProps: {
        shadow: 'sm',
        radius: 'lg',
        withBorder: true
      }
    },
    
    DataTable: {
      defaultProps: {
        highlightOnHover: true,
        withBorder: true,
        borderRadius: 'lg'
      },
      styles: {
        root: {
          borderColor: 'var(--mantine-color-gray-2)'
        }
      }
    },
    
    Button: {
      styles: {
        root: {
          // Migration douce depuis ChakraUI Button
          fontWeight: 500,
          borderRadius: '6px'
        }
      }
    }
  },
  
  defaultRadius: 'md', // Compatible avec borderRadius ChakraUI
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif'
})

// Strategy de migration progressive
const MigrationProvider = ({ children, useLegacyChakra = false }) => {
  if (useLegacyChakra) {
    return (
      <ChakraProvider theme={existingChakraTheme}>
        <MantineProvider theme={semanticIntelligenceTheme}>
          {children}
        </MantineProvider>
      </ChakraProvider>
    )
  }
  
  return (
    <MantineProvider theme={semanticIntelligenceTheme}>
      <Notifications position="top-right" />
      {children}
    </MantineProvider>
  )
}
```

---

## Layout Adaptatif ChakraUI

### Navigation RepensÃ©e par Workflow

```typescript
const AdminLayout = ({ children }: { children: React.ReactNode }) => {
  const { isOpen, onOpen, onClose } = useDisclosure()
  
  return (
    <Box minH="100vh" bg="gray.50">
      {/* Header */}
      <Flex
        as="header"
        align="center"
        justify="space-between"
        w="100%"
        px={6}
        py={4}
        bg="white"
        borderBottom="1px"
        borderColor="gray.200"
        shadow="sm"
      >
        <HStack spacing={4}>
          <IconButton
            aria-label="Menu"
            icon={<HamburgerIcon />}
            variant="ghost"
            onClick={onOpen}
            display={{ base: "flex", lg: "none" }}
          />
          <Heading size="md" color="brand.500">
            🧠 Semantic Intelligence KG Admin
          </Heading>
        </HStack>
        
        <HStack spacing={4}>
          <IconButton aria-label="Notifications" icon={<BellIcon />} variant="ghost" />
          <IconButton aria-label="Analytics" icon={<BarChartIcon />} variant="ghost" />
          <Avatar size="sm" />
        </HStack>
      </Flex>
      
      <Flex>
        {/* Sidebar */}
        <WorkflowSidebar isOpen={isOpen} onClose={onClose} />
        
        {/* Main Content */}
        <Box flex="1" p={6}>
          <Container maxW="container.xl">
            {children}
          </Container>
        </Box>
      </Flex>
    </Box>
  )
}

const WorkflowSidebar = ({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) => (
  <Drawer isOpen={isOpen} placement="left" onClose={onClose}>
    <DrawerOverlay />
    <DrawerContent>
      <DrawerCloseButton />
      <DrawerHeader>Workflows</DrawerHeader>
      
      <DrawerBody>
        <VStack align="stretch" spacing={1}>
          <SidebarSection 
            title="🧠 Intelligence Management"
            items={[
              { label: "Document Processing Pipeline", href: "/pipeline" },
              { label: "Semantic Quality Control", href: "/quality" },
              { label: "Pattern Discovery Lab", href: "/patterns" },
              { label: "Budget & Performance", href: "/budget" }
            ]}
          />
          
          <SidebarSection 
            title="🕸️ Knowledge Graph"
            items={[
              { label: "Ontology Designer", href: "/ontology" },
              { label: "Entity Constellation", href: "/entities" },
              { label: "Relation Networks", href: "/relations" },
              { label: "Knowledge Validation", href: "/validation" }
            ]}
          />
          
          <SidebarSection 
            title="⚙️ System Administration"
            items={[
              { label: "Processing Status", href: "/status" },
              { label: "Error Investigation", href: "/errors" },
              { label: "System Health", href: "/health" },
              { label: "Configuration", href: "/config" }
            ]}
          />
        </VStack>
      </DrawerBody>
    </DrawerContent>
  </Drawer>
)
```

---

## 1. Dashboard Intelligence - Mantine Enterprise

### Design : Semantic Health Overview avec DataTable Native

```typescript
import { Paper, SimpleGrid, Group, Text, Badge, Progress, Button } from '@mantine/core'
import { DataTable } from '@mantine/datatable'
import { notifications } from '@mantine/notifications'
import { useQuery } from '@tanstack/react-query'
import { IconRefresh, IconDownload, IconTrendingUp } from '@tabler/icons'

const DashboardIntelligence = () => {
  const { data: healthMetrics, refetch } = useQuery(['health-metrics'], fetchHealthMetrics)
  
  // Real-time notifications via WebSocket
  useEffect(() => {
    const ws = new WebSocket('/ws/semantic-updates')
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data)
      if (update.type === 'INTELLIGENCE_SCORE_UPDATE') {
        notifications.show({
          title: 'Intelligence Score Updated',
          message: `New score: ${update.score} (+${update.delta})`,
          color: 'blue',
          icon: <IconTrendingUp size="1rem" />
        })
      }
    }
    return () => ws.close()
  }, [])
  
  return (
    <Stack spacing="xl">
      {/* Header avec actions natives Mantine */}
      <Group position="apart" align="center">
        <div>
          <Text size="xl" fw={700}>Semantic Intelligence Health</Text>
          <Text size="sm" c="dimmed">Updated 2 min ago</Text>
        </div>
        
        <Group spacing="xs">
          <Button 
            variant="light" 
            leftIcon={<IconDownload size="1rem" />}
            onClick={() => exportIntelligenceReport()}
          >
            Export Report
          </Button>
          <Button 
            leftIcon={<IconRefresh size="1rem" />}
            onClick={() => refetch()}
          >
            Refresh
          </Button>
        </Group>
      </Group>
      
      {/* Métriques principales - Cards Mantine optimisées */}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="md">
        <Paper withBorder p="md" radius="lg">
          <Group position="apart">
            <div>
              <Text c="dimmed" size="sm" transform="uppercase" fw={700}>
                Intelligence Score
              </Text>
              <Text fw={700} size="xl">
                0.87
              </Text>
            </div>
            <Badge color="green" variant="filled" radius="xl">
              +0.03
            </Badge>
          </Group>
          <Progress value={87} mt="md" size="sm" radius="xl" />
        </Paper>
        
        <Paper withBorder p="md" radius="lg">
          <Group position="apart">
            <div>
              <Text c="dimmed" size="sm" transform="uppercase" fw={700}>
                Knowledge Growth
              </Text>
              <Text fw={700} size="xl">
                +127
              </Text>
            </div>
            <Text c="dimmed" size="sm">facts today</Text>
          </Group>
        </Paper>
        
        <Paper withBorder p="md" radius="lg">
          <Group position="apart">
            <div>
              <Text c="dimmed" size="sm" transform="uppercase" fw={700}>
                Processing Pipeline
              </Text>
              <Text fw={700} size="xl">
                12
              </Text>
            </div>
            <Badge color="blue" variant="light">Processing</Badge>
          </Group>
        </Paper>
        
        <Paper withBorder p="md" radius="lg">
          <Group position="apart">
            <div>
              <Text c="dimmed" size="sm" transform="uppercase" fw={700}>
                Quality Metrics
              </Text>
              <Text fw={700} size="xl">
                94%
              </Text>
            </div>
            <Badge color="green" variant="filled" radius="xl">
              +2%
            </Badge>
          </Group>
        </Paper>
      </SimpleGrid>
      
      {/* Chart trends - Integration Recharts optimisée Mantine */}
      <Paper withBorder p="lg" radius="lg">
        <Text size="lg" fw={600} mb="md">
          Semantic Intelligence Trends (7 days)
        </Text>
        <Box h={300}>
          <IntelligenceTrendsChart data={healthMetrics?.trends} />
        </Box>
      </Paper>
      
      {/* Alerts et Actions - Notifications Mantine */}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        <Paper withBorder p="md" radius="lg" bg="orange.0">
          <Group align="flex-start" spacing="md">
            <ThemeIcon color="orange" size={24} radius="xl">
              <IconAlertTriangle size="1rem" />
            </ThemeIcon>
            <div style={{ flex: 1 }}>
              <Text fw={600} size="sm">Attention Required</Text>
              <Stack spacing={4} mt="xs">
                <Text size="xs" c="dimmed">• 23 entity types pending</Text>
                <Text size="xs" c="dimmed">• Proto-KG 87% capacity</Text>
                <Text size="xs" c="dimmed">• 3 pattern conflicts</Text>
              </Stack>
            </div>
          </Group>
        </Paper>
        
        <Paper withBorder p="md" radius="lg">
          <Text fw={600} size="sm" mb="md">Quick Actions</Text>
          <Stack spacing="xs">
            <Button variant="light" size="xs" fullWidth>
              Review Pending Discoveries
            </Button>
            <Button variant="light" size="xs" fullWidth>
              Optimize Budget Allocation  
            </Button>
            <Button variant="light" size="xs" fullWidth>
              Export Intelligence Report
            </Button>
          </Stack>
        </Paper>
      </SimpleGrid>
    </Stack>
  )
}
```

---

## 2. Document Processing Pipeline - ChakraUI Forms + Real-time

### Design : Processing Flow Control

```typescript
const DocumentProcessingPipeline = () => {
  const { data: profiles } = useQuery(['extraction-profiles'], fetchProfiles)
  const { data: queue } = useQuery(['processing-queue'], fetchQueue, {
    refetchInterval: 5000 // Real-time updates
  })
  const toast = useToast()
  
  // WebSocket pour updates temps réel
  useEffect(() => {
    const ws = new WebSocket('/ws/processing-status')
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data)
      if (update.type === 'DOCUMENT_COMPLETED') {
        toast({
          title: "Document processed",
          description: `${update.document} completed successfully`,
          status: "success",
          duration: 3000
        })
      }
    }
    return () => ws.close()
  }, [toast])
  
  return (
    <VStack spacing={8} align="stretch">
      <Breadcrumb>
        <BreadcrumbItem>
          <BreadcrumbLink href="/admin">Admin</BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbItem isCurrentPage>
          <BreadcrumbLink>Document Processing</BreadcrumbLink>
        </BreadcrumbItem>
      </Breadcrumb>
      
      <Grid templateColumns={{ base: "1fr", lg: "1fr 1fr" }} gap={6}>
        {/* Extraction Profiles */}
        <Card>
          <CardHeader>
            <Heading size="md">🔥 Extraction Profiles</Heading>
          </CardHeader>
          <CardBody>
            <VStack align="stretch" spacing={4}>
              {profiles?.map(profile => (
                <Box key={profile.id} p={4} borderWidth="1px" borderRadius="lg">
                  <HStack justify="space-between" mb={2}>
                    <Text fontWeight="bold">{profile.name}</Text>
                    <Badge colorScheme={profile.active ? "green" : "gray"}>
                      {profile.active ? "✓" : "Edit"}
                    </Badge>
                  </HStack>
                  
                  <VStack align="start" spacing={1} fontSize="sm" color="gray.600">
                    <Text>├─ Context: {profile.context}</Text>
                    <Text>├─ Expected: {profile.expectedTypes.join(", ")}</Text>
                    <Text>└─ Success Rate: {profile.successRate}%</Text>
                  </VStack>
                  
                  <Progress 
                    value={profile.successRate} 
                    colorScheme={profile.successRate > 90 ? "green" : "yellow"}
                    size="sm"
                    mt={2}
                  />
                </Box>
              ))}
              
              <Button leftIcon={<AddIcon />} variant="outline" size="sm">
                Create New Profile
              </Button>
            </VStack>
          </CardBody>
        </Card>
        
        {/* Pattern Library */}
        <Card>
          <CardHeader>
            <Heading size="md">🎯 Pattern Library</Heading>
          </CardHeader>
          <CardBody>
            <VStack align="stretch" spacing={4}>
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={2}>Recently Discovered</Text>
                <VStack align="stretch" spacing={2}>
                  <HStack justify="space-between">
                    <Badge colorScheme="orange">OPTIMIZES (pending)</Badge>
                    <Button size="xs" variant="ghost">Review</Button>
                  </HStack>
                  <HStack justify="space-between">
                    <Badge colorScheme="green">FACILITATES (approved)</Badge>
                    <Button size="xs" variant="ghost">View</Button>
                  </HStack>
                </VStack>
              </Box>
              
              <Divider />
              
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={2}>Confidence Distribution</Text>
                <VStack align="stretch" spacing={1}>
                  <HStack justify="space-between">
                    <Text fontSize="sm">High:</Text>
                    <HStack>
                      <Progress value={80} size="sm" flex="1" maxW="100px" />
                      <Text fontSize="sm">34</Text>
                    </HStack>
                  </HStack>
                  <HStack justify="space-between">
                    <Text fontSize="sm">Med:</Text>
                    <HStack>
                      <Progress value={60} size="sm" flex="1" maxW="100px" />
                      <Text fontSize="sm">12</Text>
                    </HStack>
                  </HStack>
                </VStack>
              </Box>
            </VStack>
          </CardBody>
        </Card>
      </Grid>
      
      {/* Live Processing Queue */}
      <Card>
        <CardHeader>
          <Heading size="md">⚡ Live Processing Queue</Heading>
        </CardHeader>
        <CardBody>
          <Table variant="simple">
            <Thead>
              <Tr>
                <Th>Document</Th>
                <Th>Status</Th>
                <Th>Context</Th>
                <Th>ETA</Th>
                <Th>Actions</Th>
              </Tr>
            </Thead>
            <Tbody>
              {queue?.map(item => (
                <Tr key={item.id}>
                  <Td>
                    <VStack align="start" spacing={0}>
                      <Text fontWeight="bold" fontSize="sm">{item.filename}</Text>
                      <Text fontSize="xs" color="gray.500">
                        Complexity: {item.complexity}
                      </Text>
                    </VStack>
                  </Td>
                  <Td>
                    <Badge colorScheme={getStatusColor(item.status)}>
                      {item.status}
                    </Badge>
                  </Td>
                  <Td>
                    <VStack align="start" spacing={0}>
                      <Text fontSize="sm">Budget: {item.budget}</Text>
                      <Text fontSize="xs" color="gray.500">
                        Cost est: ${item.estimatedCost}
                      </Text>
                    </VStack>
                  </Td>
                  <Td>
                    <Text fontSize="sm">{item.eta}</Text>
                  </Td>
                  <Td>
                    <ButtonGroup size="xs">
                      <IconButton 
                        aria-label="View details"
                        icon={<ViewIcon />}
                        variant="ghost"
                      />
                      <IconButton 
                        aria-label="Pause"
                        icon={<Icon />}
                        variant="ghost"
                      />
                    </ButtonGroup>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>
    </VStack>
  )
}
```

---

## 2. Semantic Quality Control - Mantine DataTable + Drag & Drop

### Design : Validation Workflows avec Table Enterprise

```typescript
import { DataTable, type DataTableSortStatus } from '@mantine/datatable'
import { useMove, useListState } from '@mantine/hooks'
import { modals } from '@mantine/modals'
import { Checkbox, ActionIcon, Badge, Group, Text, Button } from '@mantine/core'

const SemanticQualityControl = () => {
  const [sortStatus, setSortStatus] = useState<DataTableSortStatus>({ 
    columnAccessor: 'priority', 
    direction: 'desc' 
  })
  
  const [records, handlers] = useListState(initialValidationData)
  const [selectedRecords, setSelectedRecords] = useState<string[]>([])
  
  // Drag & drop pour priorités avec hook Mantine natif
  const { ref: dragRef, active } = useMove({
    onDragEnd: ({ source, destination }) => {
      if (destination) {
        handlers.reorder({
          from: source.index,
          to: destination.index
        })
      }
    }
  })
  
  const handleBulkAction = async (action: 'approve' | 'reject' | 'merge') => {
    modals.openConfirmModal({
      title: `${action.toUpperCase()} Selected Items`,
      children: (
        <Text size="sm">
          Are you sure you want to {action} {selectedRecords.length} selected items?
          This action cannot be undone.
        </Text>
      ),
      labels: { confirm: `${action.toUpperCase()}`, cancel: 'Cancel' },
      confirmProps: { color: action === 'reject' ? 'red' : 'green' },
      onConfirm: async () => {
        try {
          await bulkValidationAction(selectedRecords, action)
          notifications.show({
            title: 'Action completed',
            message: `${selectedRecords.length} items ${action}ed successfully`,
            color: 'green'
          })
          setSelectedRecords([])
        } catch (error) {
          notifications.show({
            title: 'Action failed',
            message: error.message,
            color: 'red'
          })
        }
      }
    })
  }
  
  return (
    <Stack spacing="xl">
      {/* Header avec stats live */}
      <Group position="apart">
        <div>
          <Text size="xl" fw={700}>Semantic Quality Control</Text>
          <Group spacing="md" mt="xs">
            <Badge color="blue" size="lg">Queue: 234 pending</Badge>
            <Badge color="green" size="lg">Auto-approved: 89%</Badge>
          </Group>
        </div>
        
        {selectedRecords.length > 0 && (
          <Group spacing="xs">
            <Button 
              color="green"
              leftIcon={<IconCheck size="1rem" />}
              onClick={() => handleBulkAction('approve')}
            >
              Approve ({selectedRecords.length})
            </Button>
            <Button 
              color="red" 
              variant="light"
              leftIcon={<IconX size="1rem" />}
              onClick={() => handleBulkAction('reject')}
            >
              Reject
            </Button>
            <Button 
              variant="light"
              leftIcon={<IconGitMerge size="1rem" />}
              onClick={() => handleBulkAction('merge')}
            >
              Merge
            </Button>
          </Group>
        )}
      </Group>
      
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        {/* Smart Triage - Progress cards Mantine */}
        <Paper withBorder p="lg" radius="lg">
          <Text fw={600} mb="md">Smart Triage</Text>
          
          <Stack spacing="md">
            <div>
              <Group position="apart" mb="xs">
                <Text size="sm" fw={500}>High Confidence (Auto ✓)</Text>
                <Text size="sm" c="dimmed">89%</Text>
              </Group>
              <Progress value={89} color="green" size="lg" radius="xl" />
            </div>
            
            <div>
              <Group position="apart" mb="xs">
                <Text size="sm" fw={500}>Needs Review</Text>
                <Text size="sm" c="dimmed">8%</Text>
              </Group>
              <Progress value={8} color="yellow" size="lg" radius="xl" />
            </div>
            
            <div>
              <Group position="apart" mb="xs">
                <Text size="sm" fw={500}>Flagged Issues</Text>
                <Text size="sm" c="dimmed">3%</Text>
              </Group>
              <Progress value={3} color="red" size="lg" radius="xl" />
            </div>
          </Stack>
        </Paper>
        
        {/* Quality Metrics */}
        <Paper withBorder p="lg" radius="lg">
          <Text fw={600} mb="md">Quality Metrics</Text>
          
          <Stack spacing="md">
            <Group position="apart">
              <Text size="sm">Evidence Strength</Text>
              <div>
                <Text size="xs" c="dimmed" ta="right">Strong: 156</Text>
                <Progress value={78} size="sm" w={100} color="green" radius="xl" />
              </div>
            </Group>
            
            <Group position="apart">
              <Text size="sm">Semantic Coherence</Text>
              <div>
                <Text size="xs" c="dimmed" ta="right">Coherent: 203</Text>
                <Progress value={91} size="sm" w={100} color="blue" radius="xl" />
              </div>
            </Group>
            
            <Group position="apart">
              <Text size="sm">Cross-validation</Text>
              <div>
                <Text size="xs" c="dimmed" ta="right">Validated: 89</Text>
                <Progress value={67} size="sm" w={100} color="violet" radius="xl" />
              </div>
            </Group>
          </Stack>
        </Paper>
      </SimpleGrid>
      
      {/* DataTable Enterprise avec drag & drop natif */}
      <Paper withBorder radius="lg">
        <DataTable
          ref={dragRef}
          withBorder={false}
          borderRadius="lg"
          striped
          highlightOnHover
          records={records}
          sortStatus={sortStatus}
          onSortStatusChange={setSortStatus}
          selectedRecords={selectedRecords.map(id => records.find(r => r.id === id))}
          onSelectedRecordsChange={(selected) => 
            setSelectedRecords(selected.map(record => record.id))
          }
          columns={[
            { 
              accessor: 'id',
              title: '',
              width: 40,
              render: ({ id }) => (
                <Checkbox
                  checked={selectedRecords.includes(id)}
                  onChange={(event) => {
                    if (event.currentTarget.checked) {
                      setSelectedRecords(prev => [...prev, id])
                    } else {
                      setSelectedRecords(prev => prev.filter(selectedId => selectedId !== id))
                    }
                  }}
                />
              )
            },
            {
              accessor: 'priority',
              title: 'Priority',
              width: 100,
              sortable: true,
              render: ({ priority, conflicts }) => (
                <Group spacing="xs">
                  <Badge 
                    color={priority === 'critical' ? 'red' : priority === 'medium' ? 'yellow' : 'blue'}
                    variant="filled"
                    size="sm"
                  >
                    {priority.toUpperCase()}
                  </Badge>
                  {conflicts && (
                    <IconAlertTriangle size="1rem" color="orange" />
                  )}
                </Group>
              )
            },
            {
              accessor: 'relation',
              title: 'Relation',
              sortable: true,
              render: ({ subject, relation, object, confidence }) => (
                <div>
                  <Text size="sm" fw={500}>
                    {subject} → "{relation}" → {object}
                  </Text>
                  <Group spacing="md" mt="xs">
                    <Badge variant="light" size="xs">
                      Conf: {confidence}
                    </Badge>
                  </Group>
                </div>
              )
            },
            {
              accessor: 'evidence',
              title: 'Evidence',
              render: ({ evidence, sources }) => (
                <div>
                  <Text size="xs" c="dimmed" lineClamp={2}>
                    "{evidence}"
                  </Text>
                  <Text size="xs" c="dimmed" mt="xs">
                    Sources: {sources}
                  </Text>
                </div>
              )
            },
            {
              accessor: 'actions',
              title: '',
              width: 200,
              textAlignment: 'center',
              render: (record) => (
                <Group spacing="xs" position="center">
                  <ActionIcon 
                    color="green" 
                    variant="light"
                    onClick={() => handleSingleAction(record.id, 'approve')}
                  >
                    <IconCheck size="1rem" />
                  </ActionIcon>
                  <ActionIcon 
                    color="red" 
                    variant="light"
                    onClick={() => handleSingleAction(record.id, 'reject')}
                  >
                    <IconX size="1rem" />
                  </ActionIcon>
                  <ActionIcon 
                    variant="light"
                    onClick={() => openDetailModal(record)}
                  >
                    <IconEye size="1rem" />
                  </ActionIcon>
                  <ActionIcon 
                    variant="light"
                    onClick={() => openMergeModal(record)}
                  >
                    <IconGitMerge size="1rem" />
                  </ActionIcon>
                </Group>
              )
            }
          ]}
          // Pagination native
          totalRecords={totalRecords}
          recordsPerPage={50}
          page={page}
          onPageChange={(p) => setPage(p)}
          // Loading state
          fetching={loading}
          // Empty state
          noRecordsText="No validation items pending"
        />
      </Paper>
    </Stack>
  )
}
```

---

## 3. Entity Constellation Explorer - Mantine + D3 avec Spotlight

### Design : Galaxy-Style avec Search Natif Mantine

```typescript
import { Spotlight, spotlight } from '@mantine/spotlight'
import { useMove } from '@mantine/hooks'
import { Paper, TextInput, ActionIcon, Group, Badge } from '@mantine/core'

const EntityConstellation = () => {
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null)
  const { data: entityData } = useQuery(['entity-constellation'], fetchEntityConstellation)
  
  // Spotlight search intégré pour entités
  const spotlightActions = entityData?.entities?.map(entity => ({
    id: entity.id,
    label: entity.name,
    description: `${entity.type} - Confidence: ${entity.confidence}`,
    onTrigger: () => {
      setSelectedEntity(entity.id)
      // Pan to entity dans la visualisation
      focusEntityInVisualization(entity.id)
    },
    keywords: [entity.type, entity.domain, ...entity.tags]
  })) || []
  
  return (
    <Stack spacing="md">
      <Group position="apart">
        <Text size="xl" fw={700}>Entity Constellation Explorer</Text>
        
        <Group spacing="md">
          <Button 
            leftIcon={<IconSearch size="1rem" />}
            variant="light"
            onClick={spotlight.open}
          >
            Search Entities
          </Button>
          
          <Button leftIcon={<IconEye size="1rem" />} variant="light">
            Focus View
          </Button>
          <Button leftIcon={<IconChartDots size="1rem" />} variant="light">
            Metrics
          </Button>
          <Button leftIcon={<IconDownload size="1rem" />} variant="light">
            Save View
          </Button>
        </Group>
      </Group>
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 350px', gap: '1rem', height: '600px' }}>
        {/* Galaxy View - D3 custom dans Paper Mantine */}
        <Paper withBorder radius="lg" p={0} style={{ overflow: 'hidden' }}>
          <Box pos="relative" w="100%" h="100%">
            <EntityGalaxyVisualization 
              data={entityData}
              selectedEntity={selectedEntity}
              onEntitySelect={setSelectedEntity}
              theme={mantineTheme} // Intégration theming
            />
          </Box>
        </Paper>
        
        {/* Entity Intelligence Panel - Mantine natif */}
        <Paper withBorder p="lg" radius="lg">
          <Text fw={600} size="lg" mb="md">Entity Intelligence Panel</Text>
          
          {selectedEntity ? (
            <EntityDetailsPanel entityId={selectedEntity} />
          ) : (
            <Center h={200}>
              <Stack align="center" spacing="xs">
                <IconNodes size="3rem" color="var(--mantine-color-gray-4)" />
                <Text c="dimmed" ta="center">
                  Select an entity to view details
                </Text>
                <Button 
                  variant="light" 
                  size="sm"
                  onClick={spotlight.open}
                >
                  Search Entities
                </Button>
              </Stack>
            </Center>
          )}
        </Paper>
      </div>
      
      {/* Spotlight search avec actions personnalisées */}
      <Spotlight
        actions={spotlightActions}
        searchIcon={<IconSearch size="1.2rem" />}
        searchPlaceholder="Search entities, relations, patterns..."
        shortcut="mod + K"
        nothingFoundMessage="No entities found..."
      />
    </Stack>
  )
}

const EntityDetailsPanel = ({ entityId }: { entityId: string }) => {
  const { data: entity } = useQuery(['entity', entityId], () => fetchEntity(entityId))
  
  if (!entity) {
    return (
      <Stack align="center" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">Loading entity details...</Text>
      </Stack>
    )
  }
  
  return (
    <Stack spacing="lg">
      {/* Entity Header avec badges */}
      <div>
        <Group mb="sm">
          <Text fw={700} size="lg">{entity.name}</Text>
          <Badge color="green" variant="filled">Approved</Badge>
        </Group>
        
        <Stack spacing="xs">
          <Group spacing="xs">
            <Text size="sm" c="dimmed">Type:</Text>
            <Badge variant="light">{entity.type}</Badge>
          </Group>
          <Group spacing="xs">
            <Text size="sm" c="dimmed">Confidence:</Text>
            <Badge color="blue" variant="outline">{entity.confidence}</Badge>
          </Group>
          <Group spacing="xs">
            <Text size="sm" c="dimmed">Sources:</Text>
            <Text size="sm">{entity.sources} documents</Text>
          </Group>
          <Group spacing="xs">
            <Text size="sm" c="dimmed">Relations:</Text>
            <Text size="sm">{entity.connections} connections</Text>
          </Group>
        </Stack>
      </div>
      
      <Divider />
      
      {/* Key Relations avec scroll */}
      <div>
        <Text fw={600} size="sm" mb="sm">Key Relations</Text>
        <ScrollArea.Autosize maxHeight={150}>
          <Stack spacing="xs">
            {entity.keyRelations?.map((rel, idx) => (
              <Group key={idx} position="apart" spacing="xs">
                <Text size="xs" style={{ flex: 1 }}>
                  {rel.type} → {rel.target}
                </Text>
                <Badge size="xs" color="blue" variant="outline">
                  {rel.confidence}
                </Badge>
              </Group>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </div>
      
      <Divider />
      
      {/* Insights */}
      <div>
        <Text fw={600} size="sm" mb="sm">Insights</Text>
        <Stack spacing="xs">
          {entity.insights?.map((insight, idx) => (
            <Text key={idx} size="xs" c="dimmed">
              • {insight}
            </Text>
          ))}
        </Stack>
      </div>
      
      {/* Actions avec variants Mantine */}
      <Group spacing="xs">
        <Button 
          size="xs" 
          variant="light"
          leftIcon={<IconEdit size="0.8rem" />}
        >
          Edit
        </Button>
        <Button 
          size="xs" 
          variant="light"
          leftIcon={<IconExternalLink size="0.8rem" />}
        >
          Explore
        </Button>
        <ActionIcon 
          variant="light" 
          size="lg"
          onClick={() => exportEntityReport(entity)}
        >
          <IconDownload size="1rem" />
        </ActionIcon>
      </Group>
    </Stack>
  )
}
```

---

## 5. Budget Intelligence Center - ChakraUI Analytics

### Design : Financial Intelligence Center

```typescript
const BudgetIntelligenceCenter = () => {
  const { data: budgetData } = useQuery(['budget-analytics'], fetchBudgetAnalytics)
  const { data: realTimeProcessing } = useQuery(['processing-costs'], fetchRealTimeProcessing, {
    refetchInterval: 30000 // Update every 30s
  })
  
  return (
    <VStack spacing={8} align="stretch">
      <Flex justify="space-between" align="center">
        <VStack align="start" spacing={1}>
          <Heading size="lg">Budget Intelligence Center</Heading>
          <HStack>
            <Badge colorScheme="blue">Monthly: ${budgetData?.used} / ${budgetData?.total}</Badge>
            <Progress 
              value={(budgetData?.used / budgetData?.total) * 100} 
              colorScheme={budgetData?.used / budgetData?.total > 0.8 ? "red" : "green"}
              size="sm"
              w="100px"
            />
          </HStack>
        </VStack>
        
        <ButtonGroup>
          <Button leftIcon={<DownloadIcon />} variant="outline">Export Report</Button>
          <Button leftIcon={<SettingsIcon />} colorScheme="brand">Optimize</Button>
        </ButtonGroup>
      </Flex>
      
      <Grid templateColumns={{ base: "1fr", lg: "2fr 1fr" }} gap={6}>
        {/* Smart Budget Allocation */}
        <Card>
          <CardHeader>
            <Heading size="md">💰 Smart Budget Allocation</Heading>
          </CardHeader>
          <CardBody>
            <VStack align="stretch" spacing={6}>
              {/* Current Allocation Progress */}
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={2}>Current Allocation</Text>
                <Progress value={74} colorScheme="blue" size="lg" mb={2} />
                <Text fontSize="xs" color="gray.600">74% of monthly budget used</Text>
              </Box>
              
              {/* By Intelligence Level */}
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={3}>By Intelligence Level:</Text>
                <VStack align="stretch" spacing={2}>
                  <HStack justify="space-between">
                    <Text fontSize="sm">Premium processing:</Text>
                    <HStack>
                      <Text fontSize="sm" fontWeight="bold">${budgetData?.premium}</Text>
                      <Text fontSize="xs" color="gray.500">(48%)</Text>
                    </HStack>
                  </HStack>
                  
                  <HStack justify="space-between">
                    <Text fontSize="sm">Standard processing:</Text>
                    <HStack>
                      <Text fontSize="sm" fontWeight="bold">${budgetData?.standard}</Text>
                      <Text fontSize="xs" color="gray.500">(35%)</Text>
                    </HStack>
                  </HStack>
                  
                  <HStack justify="space-between">
                    <Text fontSize="sm">Basic processing:</Text>
                    <HStack>
                      <Text fontSize="sm" fontWeight="bold">${budgetData?.basic}</Text>
                      <Text fontSize="xs" color="gray.500">(17%)</Text>
                    </HStack>
                  </HStack>
                </VStack>
              </Box>
              
              {/* By Component */}
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={3}>By Component:</Text>
                <SimpleGrid columns={2} spacing={4}>
                  <VStack>
                    <CircularProgress value={23} color="blue.400" size="60px">
                      <CircularProgressLabel fontSize="xs">23%</CircularProgressLabel>
                    </CircularProgress>
                    <Text fontSize="xs" textAlign="center">Narrative analysis</Text>
                  </VStack>
                  
                  <VStack>
                    <CircularProgress value={39} color="green.400" size="60px">
                      <CircularProgressLabel fontSize="xs">39%</CircularProgressLabel>
                    </CircularProgress>
                    <Text fontSize="xs" textAlign="center">Context extraction</Text>
                  </VStack>
                  
                  <VStack>
                    <CircularProgress value={13} color="purple.400" size="60px">
                      <CircularProgressLabel fontSize="xs">13%</CircularProgressLabel>
                    </CircularProgress>
                    <Text fontSize="xs" textAlign="center">Pattern discovery</Text>
                  </VStack>
                  
                  <VStack>
                    <CircularProgress value={25} color="orange.400" size="60px">
                      <CircularProgressLabel fontSize="xs">25%</CircularProgressLabel>
                    </CircularProgress>
                    <Text fontSize="xs" textAlign="center">Validation</Text>
                  </VStack>
                </SimpleGrid>
              </Box>
            </VStack>
          </CardBody>
        </Card>
        
        {/* ROI Intelligence */}
        <Card>
          <CardHeader>
            <Heading size="md">📊 ROI Intelligence</Heading>
          </CardHeader>
          <CardBody>
            <VStack align="stretch" spacing={4}>
              <Stat>
                <StatLabel>Cost per Insight</StatLabel>
                <StatNumber fontSize="2xl">$0.32</StatNumber>
                <StatHelpText>
                  <StatArrow type="increase" />
                  +14% from last month
                </StatHelpText>
              </Stat>
              
              <Divider />
              
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={2}>Semantic ROI</Text>
                <VStack align="start" spacing={1}>
                  <HStack justify="space-between" w="100%">
                    <Text fontSize="sm">vs Basic:</Text>
                    <Badge colorScheme="green">3.2x</Badge>
                  </HStack>
                  <HStack justify="space-between" w="100%">
                    <Text fontSize="sm">vs Manual:</Text>
                    <Badge colorScheme="green">12.7x</Badge>
                  </HStack>
                </VStack>
              </Box>
              
              <Divider />
              
              <Box>
                <Text fontSize="sm" fontWeight="bold" mb={2}>Performance</Text>
                <VStack align="start" spacing={1}>
                  <HStack justify="space-between" w="100%">
                    <Text fontSize="sm">Break-even:</Text>
                    <Text fontSize="sm" fontWeight="bold">Day 18</Text>
                  </HStack>
                  <HStack justify="space-between" w="100%">
                    <Text fontSize="sm">Payback:</Text>
                    <Text fontSize="sm" fontWeight="bold">4.2 months</Text>
                  </HStack>
                </VStack>
              </Box>
            </VStack>
          </CardBody>
        </Card>
      </Grid>
      
      {/* Real-time Processing Costs */}
      <Card>
        <CardHeader>
          <Flex justify="space-between" align="center">
            <Heading size="md">⚡ Real-time Processing Costs</Heading>
            <Badge colorScheme="green">Live</Badge>
          </Flex>
        </CardHeader>
        <CardBody>
          {realTimeProcessing?.currentDocument && (
            <Alert status="info" mb={4}>
              <AlertIcon />
              <VStack align="start" spacing={1}>
                <Text fontSize="sm" fontWeight="bold">
                  Now Processing: {realTimeProcessing.currentDocument.name}
                </Text>
                <HStack spacing={4} fontSize="xs" color="gray.600">
                  <Text>Intelligence Level: {realTimeProcessing.currentDocument.level}</Text>
                  <Text>Current Cost: ${realTimeProcessing.currentDocument.currentCost}</Text>
                  <Text>Est. Total: ${realTimeProcessing.currentDocument.estimatedTotal}</Text>
                </HStack>
              </VStack>
            </Alert>
          )}
          
          <VStack align="stretch" spacing={4}>
            <Box>
              <Text fontSize="sm" fontWeight="bold" mb={2}>Queue Impact Analysis:</Text>
              <VStack align="start" spacing={1} fontSize="sm">
                <Text>• {realTimeProcessing?.queueCount} docs pending: Est. ${realTimeProcessing?.queueEstimate} total</Text>
                <Text>• {realTimeProcessing?.expensiveDocs} docs flagged expensive: Manual review recommended</Text>
                <Text color="green.600">• Smart routing saved: ${realTimeProcessing?.savedThisWeek} this week</Text>
              </VStack>
            </Box>
          </VStack>
        </CardBody>
      </Card>
      
      {/* Optimization Recommendations */}
      <Card>
        <CardHeader>
          <Heading size="md">🎯 Optimization Recommendations</Heading>
        </CardHeader>
        <CardBody>
          <VStack align="stretch" spacing={4}>
            <Alert status="warning">
              <AlertIcon />
              <VStack align="start" spacing={1}>
                <Text fontSize="sm" fontWeight="bold">💡 Cache Hit Rate Low (23%) - Consider extending TTL</Text>
                <Text fontSize="xs" color="gray.600">Potential savings: $156/month</Text>
              </VStack>
            </Alert>
            
            <Alert status="info">
              <AlertIcon />
              <VStack align="start" spacing={1}>
                <Text fontSize="sm" fontWeight="bold">🔄 Batch Processing Underutilized</Text>
                <Text fontSize="xs" color="gray.600">Current: 2.1 segments/call | Target: 3.5 | Savings: $67/month</Text>
              </VStack>
            </Alert>
            
            <Alert status="warning">
              <AlertIcon />
              <VStack align="start" spacing={1}>
                <Text fontSize="sm" fontWeight="bold">📊 A/B Test Results: LLM_BIG vs LLM_SMALL</Text>
                <Text fontSize="xs" color="gray.600">Quality gain: +12% | Cost increase: +89% | ROI: Negative ❌</Text>
                <Text fontSize="xs" color="blue.600">Recommendation: Use LLM_BIG only for premium documents</Text>
              </VStack>
            </Alert>
          </VStack>
        </CardBody>
      </Card>
    </VStack>
  )
}
```

---

## 6. Architecture Technique - ChakraUI Integration

### Performance Strategy avec ChakraUI

**Code Splitting Intelligent**
```typescript
// Lazy loading par workflow avec ChakraUI
const SemanticQualityControl = lazy(() => 
  import('@/workflows/quality-control').then(module => ({
    default: module.SemanticQualityControlWithChakra
  }))
)

// Suspense avec Spinner ChakraUI
const WorkflowSuspense = ({ children }: { children: React.ReactNode }) => (
  <Suspense fallback={
    <Center h="400px">
      <VStack>
        <Spinner size="xl" color="brand.500" />
        <Text>Loading workflow...</Text>
      </VStack>
    </Center>
  }>
    {children}
  </Suspense>
)
```

**Data Management avec ChakraUI Feedback**
```typescript
// React Query avec toast notifications ChakraUI
const useSemanticData = (entityType: string) => {
  const toast = useToast()
  
  return useQuery({
    queryKey: ['entities', entityType],
    queryFn: () => fetchEntities(entityType),
    onError: (error) => {
      toast({
        title: "Data loading failed",
        description: error.message,
        status: "error",
        duration: 5000,
        isClosable: true
      })
    },
    onSuccess: () => {
      toast({
        title: "Data refreshed",
        status: "success",
        duration: 2000
      })
    }
  })
}

// Infinite scroll avec ChakraUI skeleton
const useInfiniteEntitiesWithSkeleton = (entityType: string) => {
  const query = useInfiniteQuery({
    queryKey: ['entities', entityType],
    queryFn: ({ pageParam = 0 }) => 
      fetchEntities(entityType, { offset: pageParam, limit: 20 }),
    getNextPageParam: (lastPage, pages) => 
      lastPage.hasMore ? pages.length * 20 : undefined
  })
  
  return {
    ...query,
    LoadingSkeleton: () => (
      <VStack spacing={4}>
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} height="80px" borderRadius="md" />
        ))}
      </VStack>
    )
  }
}
```

**Real-time Updates avec ChakraUI**
```typescript
// WebSocket integration avec toast notifications
const useRealtimeUpdates = () => {
  const toast = useToast()
  const queryClient = useQueryClient()
  
  useEffect(() => {
    const ws = new WebSocket('/ws/semantic-updates')
    
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data)
      
      switch(update.type) {
        case 'PROCESSING_COMPLETE':
          toast({
            title: "Document processed",
            description: `${update.document} analysis complete`,
            status: "success",
            duration: 4000,
            position: "bottom-right"
          })
          queryClient.invalidateQueries(['processing-queue'])
          break
          
        case 'GATEKEEPER_CONFLICT':
          toast({
            title: "Validation required",
            description: "New conflicts detected in quality control",
            status: "warning",
            duration: 6000,
            isClosable: true,
            position: "top-right"
          })
          queryClient.invalidateQueries(['pending-validation'])
          break
          
        case 'BUDGET_ALERT':
          toast({
            title: "Budget threshold reached",
            description: `${update.percentage}% of monthly budget used`,
            status: update.percentage > 90 ? "error" : "warning",
            duration: 8000,
            isClosable: true
          })
          break
      }
    }
    
    return () => ws.close()
  }, [toast, queryClient])
}
```

### Responsive Design avec ChakraUI

**Adaptive Components**
```typescript
// Hook pour responsive behavior ChakraUI-aware
const useSemanticLayout = () => {
  const [windowSize] = useToken('breakpoints', ['sm', 'md', 'lg', 'xl'])
  const { width } = useWindowSize()
  
  return useMemo(() => ({
    // ChakraUI breakpoints integration
    sidebarVariant: width < 768 ? 'drawer' : 'sidebar',
    cardsPerRow: width < 768 ? 1 : width < 1024 ? 2 : width < 1280 ? 3 : 4,
    showAdvancedMetrics: width >= 1024,
    useCompactMode: width < 1280,
    // Responsive grid templates pour ChakraUI
    dashboardGrid: {
      base: 'repeat(1, 1fr)',
      md: 'repeat(2, 1fr)', 
      lg: 'repeat(3, 1fr)',
      xl: 'repeat(4, 1fr)'
    }
  }), [width])
}

// Component adaptatif utilisant le hook
const ResponsiveDashboard = () => {
  const layout = useSemanticLayout()
  
  return (
    <SimpleGrid columns={layout.dashboardGrid} spacing={6}>
      {/* Content adapte automatiquement */}
    </SimpleGrid>
  )
}
```

---

## 7. Accessibility & UX avec ChakraUI

### Navigation Clavier Complète
```typescript
// Navigation au clavier avec ChakraUI focus management
const useKeyboardNavigation = () => {
  const toast = useToast()
  
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Global shortcuts
      if (event.metaKey || event.ctrlKey) {
        switch(event.key) {
          case 'k':
            event.preventDefault()
            // Ouvrir global search
            break
          case '/':
            event.preventDefault()
            // Focus search bar
            break
          case 'n':
            event.preventDefault()
            // New document
            break
        }
      }
      
      // Escape pour fermer modales/drawers
      if (event.key === 'Escape') {
        // ChakraUI gère automatiquement les modales
        toast.closeAll()
      }
    }
    
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [toast])
}
```

### ARIA Complete avec ChakraUI
```typescript
// Composant accessible par défaut avec ChakraUI
const AccessibleEntityCard = ({ 
  entity, 
  onSelect, 
  isSelected 
}: EntityCardProps) => (
  <Card
    as="button"
    role="button"
    tabIndex={0}
    aria-label={`Entity ${entity.name}, type ${entity.type}, confidence ${entity.confidence}`}
    aria-selected={isSelected}
    cursor="pointer"
    transition="all 0.2s"
    borderColor={isSelected ? "brand.500" : "gray.200"}
    borderWidth={isSelected ? "2px" : "1px"}
    _hover={{
      shadow: "md",
      transform: "translateY(-1px)"
    }}
    _focus={{
      shadow: "outline",
      borderColor: "brand.500"
    }}
    onClick={() => onSelect(entity)}
    onKeyDown={(e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onSelect(entity)
      }
    }}
  >
    <CardBody>
      {/* Card content avec proper ARIA labels */}
    </CardBody>
  </Card>
)
```

---

## Conclusion : Frontend ChakraUI Optimisé

### Avantages Architecture ChakraUI + Semantic Intelligence

**Développement Accéléré (70% plus rapide)**
- Composants ChakraUI couvrent 80% des besoins interface
- Theme system cohérent sans CSS custom
- Responsive design automatique avec breakpoints

**Performance Native**
- Tree-shaking ChakraUI = bundle optimisé
- Lazy loading intelligent avec Suspense + Skeleton
- Real-time updates via toast/alert system

**Accessibilité par Défaut**
- ARIA complet sur tous composants ChakraUI
- Navigation clavier native
- Focus management automatique

**Maintenance Simplifiée**
- Design system cohérent = moins de bugs visuels
- Composants standardisés = code prévisible  
- Thèmes centralisés = updates faciles

### Strategy Implementation

**Phase 1 : Foundation ChakraUI (Semaines 1-4)**
- Setup theme semantic intelligence
- Layouts de base avec Grid/Stack system
- Navigation avec Drawer responsive
- Components de base (Dashboard, Stats)

**Phase 2 : Workflows Intelligence (Semaines 5-8)**
- Quality Control avec validation flows
- Processing Pipeline avec real-time updates
- Budget Intelligence avec charts intégrés
- Entity management avec infinite scroll

**Phase 3 : Advanced Features (Semaines 9-12)**
- Entity Constellation (ChakraUI + D3 hybrid)
- Pattern Discovery Lab avec visualizations
- Advanced metrics avec custom components
- Performance optimizations

**Phase 4 : Polish & Optimization (Semaines 13-16)**
- Accessibility audit complet
- Performance fine-tuning
- User testing & feedback
- Production deployment

Cette approche ChakraUI-first vous donne une interface moderne, performante et accessible qui révèle parfaitement la valeur de votre architecture semantic intelligence tout en respectant vos contraintes de développement.