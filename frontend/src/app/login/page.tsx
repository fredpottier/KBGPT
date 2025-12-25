'use client'

/**
 * OSMOS Login - Dark Elegance Edition
 *
 * "Neural Gateway" - Premium authentication experience
 */

import { useState, useEffect } from 'react'
import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Input,
  VStack,
  Text,
  Link,
  InputGroup,
  InputLeftElement,
  InputRightElement,
  IconButton,
  Flex,
  HStack,
  Image,
} from '@chakra-ui/react'
import { ViewIcon, ViewOffIcon } from '@chakra-ui/icons'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuth } from '@/contexts/AuthContext'
import { useRouter, useSearchParams } from 'next/navigation'
import { FiMail, FiLock, FiArrowRight, FiAlertCircle } from 'react-icons/fi'

const MotionBox = motion(Box)
const MotionFlex = motion(Flex)

// Animated background grid pattern
const BackgroundPattern = () => (
  <Box
    position="absolute"
    inset={0}
    overflow="hidden"
    zIndex={0}
  >
    {/* Gradient mesh */}
    <Box
      position="absolute"
      top="-50%"
      left="-50%"
      w="200%"
      h="200%"
      bgGradient="radial(ellipse at 30% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 50%)"
    />
    <Box
      position="absolute"
      bottom="-30%"
      right="-30%"
      w="150%"
      h="150%"
      bgGradient="radial(ellipse at 70% 80%, rgba(34, 211, 238, 0.1) 0%, transparent 50%)"
    />

    {/* Grid lines */}
    <Box
      position="absolute"
      inset={0}
      opacity={0.03}
      backgroundImage={`
        linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)
      `}
      backgroundSize="60px 60px"
    />

    {/* Floating orbs */}
    <MotionBox
      position="absolute"
      top="20%"
      left="15%"
      w={3}
      h={3}
      rounded="full"
      bg="brand.500"
      opacity={0.6}
      boxShadow="0 0 20px rgba(99, 102, 241, 0.5)"
      animate={{
        y: [0, -20, 0],
        opacity: [0.6, 0.8, 0.6],
      }}
      transition={{
        duration: 4,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    />
    <MotionBox
      position="absolute"
      top="60%"
      right="20%"
      w={2}
      h={2}
      rounded="full"
      bg="accent.400"
      opacity={0.5}
      boxShadow="0 0 15px rgba(34, 211, 238, 0.5)"
      animate={{
        y: [0, 15, 0],
        opacity: [0.5, 0.7, 0.5],
      }}
      transition={{
        duration: 3,
        repeat: Infinity,
        ease: "easeInOut",
        delay: 1,
      }}
    />
    <MotionBox
      position="absolute"
      bottom="25%"
      left="25%"
      w={2}
      h={2}
      rounded="full"
      bg="brand.400"
      opacity={0.4}
      boxShadow="0 0 12px rgba(99, 102, 241, 0.4)"
      animate={{
        y: [0, -12, 0],
        x: [0, 8, 0],
        opacity: [0.4, 0.6, 0.4],
      }}
      transition={{
        duration: 5,
        repeat: Infinity,
        ease: "easeInOut",
        delay: 2,
      }}
    />
  </Box>
)

// Animated Logo
const Logo = () => (
  <MotionBox
    initial={{ opacity: 0, y: -20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.6, ease: "easeOut" }}
  >
    <VStack spacing={3}>
      <HStack spacing={3}>
        <Image
          src="/logo.png"
          alt="OSMOS Logo"
          h={14}
          w="auto"
          objectFit="contain"
          filter="drop-shadow(0 0 20px rgba(99, 102, 241, 0.4))"
        />
        <Text
          fontSize="2xl"
          fontWeight="bold"
          bgGradient="linear(to-r, text.primary, brand.400)"
          bgClip="text"
        >
          OSMOS
        </Text>
      </HStack>
      <Text
        fontSize="sm"
        color="text.muted"
        letterSpacing="wider"
        textTransform="uppercase"
      >
        Le Cortex Documentaire
      </Text>
    </VStack>
  </MotionBox>
)

// Error Alert Component
const ErrorAlert = ({ message }: { message: string }) => (
  <MotionBox
    initial={{ opacity: 0, y: -10, scale: 0.95 }}
    animate={{ opacity: 1, y: 0, scale: 1 }}
    exit={{ opacity: 0, y: -10, scale: 0.95 }}
    transition={{ duration: 0.2 }}
  >
    <HStack
      spacing={3}
      px={4}
      py={3}
      bg="rgba(239, 68, 68, 0.1)"
      border="1px solid"
      borderColor="error.500"
      rounded="xl"
      boxShadow="0 0 20px rgba(239, 68, 68, 0.1)"
    >
      <Box as={FiAlertCircle} color="error.500" flexShrink={0} />
      <Text fontSize="sm" color="error.500">
        {message}
      </Text>
    </HStack>
  </MotionBox>
)

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const { login, isAuthenticated } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()

  const redirectUrl = searchParams.get('redirect') || '/'

  useEffect(() => {
    if (isAuthenticated) {
      router.push(redirectUrl)
    }
  }, [isAuthenticated, router, redirectUrl])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login({ email, password })
    } catch (err: any) {
      setError(err.message || 'Échec de la connexion. Vérifiez vos identifiants.')
      setIsLoading(false)
    }
  }

  return (
    <Box
      minH="100vh"
      bg="bg.primary"
      display="flex"
      alignItems="center"
      justifyContent="center"
      position="relative"
      overflow="hidden"
      p={4}
    >
      <BackgroundPattern />

      <MotionFlex
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        direction="column"
        align="center"
        maxW="420px"
        w="full"
        position="relative"
        zIndex={1}
      >
        <Logo />

        {/* Login Card */}
        <MotionBox
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2, ease: "easeOut" }}
          w="full"
          mt={10}
        >
          <Box
            bg="rgba(26, 26, 46, 0.8)"
            backdropFilter="blur(20px)"
            border="1px solid"
            borderColor="border.default"
            rounded="2xl"
            p={8}
            boxShadow="0 0 40px rgba(0, 0, 0, 0.3), 0 0 80px rgba(99, 102, 241, 0.1)"
            position="relative"
            overflow="hidden"
            _before={{
              content: '""',
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              height: '1px',
              bgGradient: 'linear(to-r, transparent, brand.500, transparent)',
              opacity: 0.5,
            }}
          >
            <VStack spacing={6} align="stretch">
              <Text
                fontSize="xl"
                fontWeight="semibold"
                color="text.primary"
                textAlign="center"
              >
                Connexion
              </Text>

              <AnimatePresence mode="wait">
                {error && <ErrorAlert message={error} />}
              </AnimatePresence>

              <form onSubmit={handleSubmit}>
                <VStack spacing={5}>
                  <FormControl isRequired>
                    <FormLabel fontSize="sm" color="text.secondary" mb={2}>
                      Email
                    </FormLabel>
                    <InputGroup>
                      <InputLeftElement h="full" pointerEvents="none">
                        <Box as={FiMail} color="text.muted" />
                      </InputLeftElement>
                      <Input
                        type="email"
                        placeholder="vous@entreprise.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        autoComplete="email"
                        autoFocus
                        size="lg"
                        bg="bg.tertiary"
                        border="1px solid"
                        borderColor="border.default"
                        rounded="xl"
                        pl={10}
                        color="text.primary"
                        _placeholder={{ color: 'text.muted' }}
                        _hover={{ borderColor: 'border.active' }}
                        _focus={{
                          borderColor: 'brand.500',
                          boxShadow: '0 0 0 1px var(--chakra-colors-brand-500), 0 0 20px rgba(99, 102, 241, 0.2)',
                        }}
                        transition="all 0.2s"
                      />
                    </InputGroup>
                  </FormControl>

                  <FormControl isRequired>
                    <FormLabel fontSize="sm" color="text.secondary" mb={2}>
                      Mot de passe
                    </FormLabel>
                    <InputGroup>
                      <InputLeftElement h="full" pointerEvents="none">
                        <Box as={FiLock} color="text.muted" />
                      </InputLeftElement>
                      <Input
                        type={showPassword ? 'text' : 'password'}
                        placeholder="Votre mot de passe"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="current-password"
                        size="lg"
                        bg="bg.tertiary"
                        border="1px solid"
                        borderColor="border.default"
                        rounded="xl"
                        pl={10}
                        pr={12}
                        color="text.primary"
                        _placeholder={{ color: 'text.muted' }}
                        _hover={{ borderColor: 'border.active' }}
                        _focus={{
                          borderColor: 'brand.500',
                          boxShadow: '0 0 0 1px var(--chakra-colors-brand-500), 0 0 20px rgba(99, 102, 241, 0.2)',
                        }}
                        transition="all 0.2s"
                      />
                      <InputRightElement h="full">
                        <IconButton
                          aria-label={showPassword ? 'Masquer' : 'Afficher'}
                          icon={showPassword ? <ViewOffIcon /> : <ViewIcon />}
                          onClick={() => setShowPassword(!showPassword)}
                          variant="ghost"
                          size="sm"
                          color="text.muted"
                          _hover={{ color: 'text.primary', bg: 'bg.hover' }}
                          rounded="lg"
                        />
                      </InputRightElement>
                    </InputGroup>
                  </FormControl>

                  <Button
                    type="submit"
                    w="full"
                    size="lg"
                    bg="brand.500"
                    color="white"
                    rounded="xl"
                    isLoading={isLoading}
                    loadingText="Connexion..."
                    rightIcon={<FiArrowRight />}
                    _hover={{
                      bg: 'brand.600',
                      transform: 'translateY(-2px)',
                      boxShadow: '0 0 30px rgba(99, 102, 241, 0.4)',
                    }}
                    _active={{
                      transform: 'translateY(0)',
                    }}
                    transition="all 0.2s"
                    mt={2}
                  >
                    Se connecter
                  </Button>
                </VStack>
              </form>

              <Text fontSize="sm" color="text.muted" textAlign="center" mt={2}>
                Pas encore de compte ?{' '}
                <Link
                  href="/register"
                  color="brand.400"
                  fontWeight="medium"
                  _hover={{ color: 'brand.300', textDecoration: 'none' }}
                  transition="color 0.2s"
                >
                  Créer un compte
                </Link>
              </Text>
            </VStack>
          </Box>
        </MotionBox>

        {/* Footer hint */}
        <MotionBox
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.5 }}
          mt={8}
        >
          <VStack spacing={1}>
            <Text fontSize="xs" color="text.muted" textAlign="center">
              Authentification sécurisée JWT RS256
            </Text>
            <Text fontSize="xs" color="text.muted" textAlign="center">
              admin@example.com / admin123
            </Text>
          </VStack>
        </MotionBox>
      </MotionFlex>
    </Box>
  )
}
