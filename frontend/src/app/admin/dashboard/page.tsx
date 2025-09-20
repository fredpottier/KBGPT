'use client'

import {
  Box,
  Heading,
  Text,
  VStack,
} from '@chakra-ui/react'

export default function AdminDashboardPage() {
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

      <Box
        bg="white"
        p={8}
        borderRadius="lg"
        shadow="sm"
        border="1px"
        borderColor="gray.200"
      >
        <Text color="gray.500" textAlign="center">
          Interface d&apos;administration à développer
        </Text>
      </Box>
    </VStack>
  )
}