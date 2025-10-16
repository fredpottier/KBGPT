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
  Select,
  FormHelperText,
} from '@chakra-ui/react'
import { ViewIcon, ViewOffIcon } from '@chakra-ui/icons'
import { useAuth } from '@/contexts/AuthContext'
import { useRouter, useSearchParams } from 'next/navigation'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<'admin' | 'editor' | 'viewer'>('viewer')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const { register, isAuthenticated } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()

  // Récupérer l'URL de redirection depuis les query params
  const redirectUrl = searchParams.get('redirect') || '/'

  // Si déjà authentifié, rediriger vers l'URL de redirection ou home
  useEffect(() => {
    if (isAuthenticated) {
      router.push(redirectUrl)
    }
  }, [isAuthenticated, router, redirectUrl])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Validation
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters long')
      return
    }

    setIsLoading(true)

    try {
      await register({ email, password, full_name: fullName, role })
      // Après register réussi, rediriger vers l'URL de redirection
      router.push(redirectUrl)
    } catch (err: any) {
      setError(err.message || 'Registration failed. Please try again.')
    } finally {
      setIsLoading(false)
    }
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
              Create Account
            </Heading>
            <Text fontSize="sm" color="gray.600" textAlign="center">
              Register for SAP Knowledge Base
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
                <FormLabel>Full Name</FormLabel>
                <Input
                  type="text"
                  placeholder="John Doe"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  autoComplete="name"
                  autoFocus
                />
              </FormControl>

              <FormControl isRequired>
                <FormLabel>Email</FormLabel>
                <Input
                  type="email"
                  placeholder="john@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                />
              </FormControl>

              <FormControl isRequired>
                <FormLabel>Password</FormLabel>
                <InputGroup>
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    placeholder="Minimum 8 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
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
                <FormHelperText>At least 8 characters</FormHelperText>
              </FormControl>

              <FormControl isRequired>
                <FormLabel>Confirm Password</FormLabel>
                <Input
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Re-enter your password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </FormControl>

              <FormControl isRequired>
                <FormLabel>Role</FormLabel>
                <Select value={role} onChange={(e) => setRole(e.target.value as any)}>
                  <option value="viewer">Viewer (Read-only)</option>
                  <option value="editor">Editor (Can create/edit)</option>
                  <option value="admin">Admin (Full access)</option>
                </Select>
                <FormHelperText>
                  {role === 'viewer' && '👁️ View documents and search'}
                  {role === 'editor' && '✏️ Create entities and document types'}
                  {role === 'admin' && '👑 Full system access and approvals'}
                </FormHelperText>
              </FormControl>

              <Button
                type="submit"
                colorScheme="brand"
                width="full"
                size="lg"
                isLoading={isLoading}
                loadingText="Creating account..."
              >
                Create Account
              </Button>
            </VStack>
          </form>

          <Text fontSize="sm" color="gray.600" textAlign="center">
            Already have an account?{' '}
            <Link color="brand.500" href="/login" fontWeight="medium">
              Sign in here
            </Link>
          </Text>

          <Box pt={4} borderTop="1px" borderColor="gray.200">
            <Text fontSize="xs" color="gray.500" textAlign="center">
              🔒 Phase 0 - RBAC (admin / editor / viewer)
            </Text>
          </Box>
        </VStack>
      </Box>
    </Container>
  )
}
