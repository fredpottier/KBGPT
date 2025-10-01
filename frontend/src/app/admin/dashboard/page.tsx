'use client'

import {
  Box,
  Heading,
  Text,
  VStack,
  SimpleGrid,
  Card,
  CardBody,
  Button,
  HStack,
  Icon,
} from '@chakra-ui/react'
import { useRouter } from 'next/navigation'
import { SettingsIcon, ExternalLinkIcon } from '@chakra-ui/icons'

export default function AdminDashboardPage() {
  const router = useRouter()

  return (
    <VStack spacing={6} align="stretch">
      <Box>
        <Heading size="lg" mb={2}>
          Administration
        </Heading>
        <Text color="gray.600">
          Interface d&apos;administration de la base de connaissances SAP
        </Text>
      </Box>

      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4}>
        {/* Bootstrap Knowledge Graph */}
        <Card>
          <CardBody>
            <HStack spacing={3} mb={3}>
              <Icon as={SettingsIcon} boxSize={6} color="blue.500" />
              <Heading size="md">Bootstrap KG</Heading>
            </HStack>
            <Text color="gray.600" mb={4}>
              Auto-promotion des entités candidates fréquentes en entités seed canoniques
            </Text>
            <Button
              colorScheme="blue"
              rightIcon={<ExternalLinkIcon />}
              onClick={() => router.push('/admin/bootstrap')}
            >
              Accéder
            </Button>
          </CardBody>
        </Card>

        {/* Placeholder pour futures fonctionnalités */}
        <Card opacity={0.5}>
          <CardBody>
            <Heading size="md" mb={3}>
              Autres outils
            </Heading>
            <Text color="gray.500" mb={4}>
              Fonctionnalités administratives à venir
            </Text>
            <Button isDisabled>
              À développer
            </Button>
          </CardBody>
        </Card>
      </SimpleGrid>
    </VStack>
  )
}