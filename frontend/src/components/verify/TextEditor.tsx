'use client'

import { Box, Textarea, Text, HStack, Badge } from '@chakra-ui/react'
import { FiFileText } from 'react-icons/fi'

interface TextEditorProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  maxLength?: number
  isDisabled?: boolean
}

export function TextEditor({
  value,
  onChange,
  placeholder = 'Collez ou saisissez le texte à vérifier...',
  maxLength = 50000,
  isDisabled = false,
}: TextEditorProps) {
  const charCount = value.length
  const isNearLimit = charCount > maxLength * 0.9

  return (
    <Box flex="1" display="flex" flexDirection="column">
      <HStack justify="space-between" mb={2}>
        <HStack spacing={2} color="text.muted">
          <FiFileText />
          <Text fontSize="sm">Texte à vérifier</Text>
        </HStack>
        <Badge
          colorScheme={isNearLimit ? 'orange' : 'gray'}
          variant="subtle"
          fontSize="xs"
        >
          {charCount.toLocaleString()} / {maxLength.toLocaleString()} caractères
        </Badge>
      </HStack>

      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        isDisabled={isDisabled}
        flex="1"
        minH="300px"
        resize="none"
        bg="bg.primary"
        border="1px solid"
        borderColor="border.default"
        rounded="xl"
        p={4}
        fontSize="md"
        lineHeight="1.7"
        color="text.primary"
        _placeholder={{ color: 'text.muted' }}
        _hover={{ borderColor: 'border.hover' }}
        _focus={{
          borderColor: 'brand.500',
          boxShadow: '0 0 0 1px var(--chakra-colors-brand-500)',
        }}
      />
    </Box>
  )
}
