"use client";

import {
  Container,
  Heading,
  Text,
  VStack,
  Alert,
  AlertIcon,
} from "@chakra-ui/react";

export default function AdminSettingsPage() {
  return (
    <Container maxW="container.xl" py={8}>
      <VStack align="stretch" spacing={6}>
        <Heading size="lg">⚙️ Configuration</Heading>
        <Alert status="info">
          <AlertIcon />
          Page de configuration en cours de développement.
        </Alert>
        <Text color="gray.600">
          Cette page permettra de gérer les paramètres généraux du système.
        </Text>
      </VStack>
    </Container>
  );
}
