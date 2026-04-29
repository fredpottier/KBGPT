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
        <Text color="fg.secondary">
          Génération et remplissage automatique de fichiers Excel RFP
        </Text>
      </Box>

      <Box
        bg="bg.canvas"
        p={8}
        borderRadius="lg"
        shadow="sm"
        border="1px"
        borderColor="border.default"
      >
        <Text color="fg.muted" textAlign="center">
          Interface RFP Excel à développer
        </Text>
      </Box>
    </VStack>
  )
}