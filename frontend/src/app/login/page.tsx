'use client'

import { useState, useEffect } from 'react'
import {
  Box,
  Button,
  Container,
  FormControl,
  FormLabel,
  Input,
  VStack,
  Heading,
  Text,
  Alert,
  AlertIcon,
  Link,
  InputGroup,
  InputRightElement,
  IconButton,
} from '@chakra-ui/react'
import { ViewIcon, ViewOffIcon } from '@chakra-ui/icons'
import { useAuth } from '@/contexts/AuthContext'
import { useRouter, useSearchParams } from 'next/navigation'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const { login, isAuthenticated } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()

  // Récupérer l'URL de redirection depuis les query params
  const redirectUrl = searchParams.get('redirect') || '/'

  // Si déjà authentifié, rediriger vers l'URL de redirection ou home
  useEffect(() => {
    console.log('[Login] useEffect - isAuthenticated:', isAuthenticated, 'redirectUrl:', redirectUrl)
    if (isAuthenticated) {
      console.log('[Login] Already authenticated, redirecting to:', redirectUrl)
      router.push(redirectUrl)
    }
  }, [isAuthenticated, router, redirectUrl])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    console.log('[Login] Form submitted, email:', email)

    try {
      await login({ email, password })
      console.log('[Login] Login successful, waiting for useEffect to redirect...')

      // NE PAS faire router.push ici - laisser le useEffect gérer la redirection
      // automatiquement quand isAuthenticated devient true

    } catch (err: any) {
      console.error('[Login] Login error:', err)
      setError(err.message || 'Login failed. Please check your credentials.')
      setIsLoading(false)
    }
    // Note: setIsLoading(false) est dans le catch uniquement
    // En cas de succès, on laisse isLoading=true jusqu'à la redirection
  }

  return (
    <Container maxW="md" py={20}>
      <Box
        bg="white"
        p={8}
        borderRadius="lg"
        boxShadow="lg"
        border="1px"
        borderColor="gray.200"
      >
        <VStack spacing={6} align="stretch">
          <VStack spacing={2}>
            <Heading size="lg" textAlign="center" color="brand.700">
              SAP Knowledge Base
            </Heading>
            <Text fontSize="sm" color="gray.600" textAlign="center">
              Sign in to access the admin panel
            </Text>
          </VStack>

          {error && (
            <Alert status="error" borderRadius="md">
              <AlertIcon />
              {error}
            </Alert>
          )}

          <form onSubmit={handleSubmit}>
            <VStack spacing={4}>
              <FormControl isRequired>
                <FormLabel>Email</FormLabel>
                <Input
                  type="email"
                  placeholder="admin@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  autoFocus
                />
              </FormControl>

              <FormControl isRequired>
                <FormLabel>Password</FormLabel>
                <InputGroup>
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="current-password"
                  />
                  <InputRightElement>
                    <IconButton
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      icon={showPassword ? <ViewOffIcon /> : <ViewIcon />}
                      onClick={() => setShowPassword(!showPassword)}
                      variant="ghost"
                      size="sm"
                    />
                  </InputRightElement>
                </InputGroup>
              </FormControl>

              <Button
                type="submit"
                colorScheme="brand"
                width="full"
                size="lg"
                isLoading={isLoading}
                loadingText="Signing in..."
              >
                Sign In
              </Button>
            </VStack>
          </form>

          <Text fontSize="sm" color="gray.600" textAlign="center">
            Don't have an account?{' '}
            <Link color="brand.500" href="/register" fontWeight="medium">
              Register here
            </Link>
          </Text>

          <Box pt={4} borderTop="1px" borderColor="gray.200">
            <Text fontSize="xs" color="gray.500" textAlign="center">
              🔒 Phase 0 - JWT RS256 Authentication
            </Text>
            <Text fontSize="xs" color="gray.500" textAlign="center" mt={1}>
              Default credentials: admin@example.com / admin123
            </Text>
          </Box>
        </VStack>
      </Box>
    </Container>
  )
}
