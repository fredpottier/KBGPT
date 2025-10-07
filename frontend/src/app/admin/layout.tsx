import { Box, Container } from '@chakra-ui/react'
import AdminNav from '@/components/admin/AdminNav'

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <Box>
      <AdminNav />
      <Container maxW="container.xl" py={6}>
        {children}
      </Container>
    </Box>
  )
}
