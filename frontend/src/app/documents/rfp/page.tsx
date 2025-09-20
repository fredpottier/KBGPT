'use client'

import {
  Box,
  Heading,
  Text,
  VStack,
} from '@chakra-ui/react'

export default function RfpPage() {
  return (
    <VStack spacing={6} align="stretch">
      <Box>
        <Heading size="lg" mb={2}>
          RFP Excel
        </Heading>
        <Text color="gray.600">
          Génération et remplissage automatique de fichiers Excel RFP
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
          Interface RFP Excel à développer
        </Text>
      </Box>
    </VStack>
  )
}