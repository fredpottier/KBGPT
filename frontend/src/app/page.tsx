'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Box, Spinner, Center } from '@chakra-ui/react'

export default function HomePage() {
  const router = useRouter()

  useEffect(() => {
    // Redirect to chat as default page
    router.push('/chat')
  }, [router])

  return (
    <Center h="100vh">
      <Box>
        <Spinner size="xl" color="brand.500" />
      </Box>
    </Center>
  )
}