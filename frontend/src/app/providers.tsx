'use client'

import { ChakraProvider } from '@chakra-ui/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { useState } from 'react'
import theme from '@/lib/theme'
import { UserProvider } from '@/contexts/UserContext'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({
      defaultOptions: {
        queries: {
          retry: (failureCount, error: any) => {
            if (error?.response?.status >= 400 && error?.response?.status < 500) {
              return false
            }
            return failureCount < 3
          },
          staleTime: 5 * 60 * 1000,
          gcTime: 10 * 60 * 1000,
          refetchOnWindowFocus: false,
        },
        mutations: {
          retry: false,
        },
      },
    })
  )

  return (
    <QueryClientProvider client={queryClient}>
      <ChakraProvider theme={theme}>
        <UserProvider>
          {children}
          <ReactQueryDevtools initialIsOpen={false} />
        </UserProvider>
      </ChakraProvider>
    </QueryClientProvider>
  )
}