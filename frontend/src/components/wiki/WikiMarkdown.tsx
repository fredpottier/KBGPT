'use client'

import React from 'react'
import {
  Box,
  Heading,
  Text,
  Divider,
  Code,
  Link,
} from '@chakra-ui/react'
import NextLink from 'next/link'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

interface WikiMarkdownProps {
  content: string
}

const markdownComponents: Components = {
  h1: ({ children }) => (
    <Heading as="h1" size="xl" color="text.primary" mt={6} mb={3}>
      {children}
    </Heading>
  ),
  h2: ({ children }) => (
    <Heading as="h2" size="lg" color="text.primary" mt={5} mb={2} borderBottom="1px" borderColor="border.default" pb={2}>
      {children}
    </Heading>
  ),
  h3: ({ children }) => (
    <Heading as="h3" size="md" color="text.primary" mt={4} mb={2}>
      {children}
    </Heading>
  ),
  p: ({ children }) => (
    <Text color="text.secondary" mb={3} lineHeight="tall">
      {children}
    </Text>
  ),
  a: ({ href, children }) => {
    // Liens internes wiki
    if (href?.startsWith('/wiki/')) {
      return (
        <Link
          as={NextLink}
          href={href}
          color="blue.300"
          _hover={{ color: 'blue.200', textDecoration: 'underline' }}
          fontWeight="medium"
        >
          {children}
        </Link>
      )
    }
    // Liens externes
    return (
      <Link href={href} color="blue.300" isExternal>
        {children}
      </Link>
    )
  },
  ul: ({ children }) => (
    <Box as="ul" pl={6} mb={3} color="text.secondary">
      {children}
    </Box>
  ),
  ol: ({ children }) => (
    <Box as="ol" pl={6} mb={3} color="text.secondary">
      {children}
    </Box>
  ),
  li: ({ children }) => (
    <Box as="li" mb={1}>
      {children}
    </Box>
  ),
  table: ({ children }) => (
    <Box overflowX="auto" mb={4}>
      <Box as="table" w="full" fontSize="sm" borderWidth="1px" borderColor="border.default" rounded="md">
        {children}
      </Box>
    </Box>
  ),
  thead: ({ children }) => (
    <Box as="thead" bg="bg.hover">
      {children}
    </Box>
  ),
  th: ({ children }) => (
    <Box as="th" px={3} py={2} textAlign="left" fontWeight="semibold" color="text.primary" borderBottomWidth="1px" borderColor="border.default">
      {children}
    </Box>
  ),
  td: ({ children }) => (
    <Box as="td" px={3} py={2} borderBottomWidth="1px" borderColor="border.default" color="text.secondary">
      {children}
    </Box>
  ),
  code: ({ children, className }) => {
    const isInline = !className
    if (isInline) {
      return (
        <Code colorScheme="purple" fontSize="sm" px={1}>
          {children}
        </Code>
      )
    }
    return (
      <Box as="pre" bg="gray.900" p={4} rounded="md" overflowX="auto" mb={3}>
        <Code display="block" whiteSpace="pre" fontSize="sm" color="gray.200">
          {children}
        </Code>
      </Box>
    )
  },
  hr: () => <Divider my={4} borderColor="border.default" />,
  em: ({ children }) => (
    <Text as="em" color="text.muted" fontStyle="italic">
      {children}
    </Text>
  ),
  strong: ({ children }) => (
    <Text as="strong" color="text.primary" fontWeight="bold">
      {children}
    </Text>
  ),
}

export default function WikiMarkdown({ content }: WikiMarkdownProps) {
  return (
    <Box className="wiki-article">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </Box>
  )
}
