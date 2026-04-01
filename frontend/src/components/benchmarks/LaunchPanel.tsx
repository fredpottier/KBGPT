'use client'

import { Box, Button, HStack, VStack, Text, Progress, Select } from '@chakra-ui/react'
import { FiPlay } from 'react-icons/fi'

interface LaunchPanelProps {
  profiles: { key: string; label: string }[]
  selectedProfile: string
  onProfileChange: (v: string) => void
  tag: string
  onTagChange: (v: string) => void
  description: string
  onDescriptionChange: (v: string) => void
  onLaunch: (benchType: string) => void
  benchTypes: { key: string; label: string; color: string }[]
  isRunning?: boolean
  runProgress?: { phase: string; progress: number; total: number; current_question?: string }
  accentColor?: string
}

export function LaunchPanel({
  profiles,
  selectedProfile,
  onProfileChange,
  tag,
  onTagChange,
  description,
  onDescriptionChange,
  onLaunch,
  benchTypes,
  isRunning,
  runProgress,
}: LaunchPanelProps) {
  return (
    <Box
      bg="var(--bg-card, #12122a)"
      border="1px solid"
      borderColor="var(--border-subtle, #1e1e3a)"
      rounded="lg"
      p={5}
    >
      <Text fontSize="sm" fontWeight="700" color="var(--text-primary, #f8fafc)" mb={4}>
        Lancer un benchmark
      </Text>

      <HStack spacing={4} mb={4} flexWrap="wrap">
        <Box>
          <Text fontSize="11px" color="var(--text-muted, #475569)" mb={1}>Profil</Text>
          <Select
            size="sm"
            value={selectedProfile}
            onChange={(e) => onProfileChange(e.target.value)}
            bg="var(--bg-input, #0f0f24)"
            borderColor="var(--border-subtle, #1e1e3a)"
            color="var(--text-primary, #f8fafc)"
            maxW="200px"
          >
            {profiles.map(p => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </Select>
        </Box>
        <Box>
          <Text fontSize="11px" color="var(--text-muted, #475569)" mb={1}>Tag</Text>
          <Box
            as="input"
            type="text"
            value={tag}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onTagChange(e.target.value)}
            placeholder="ex: POST_C6"
            bg="var(--bg-input, #0f0f24)"
            border="1px solid"
            borderColor="var(--border-subtle, #1e1e3a)"
            rounded="md"
            px={3} py={1.5}
            fontSize="sm"
            color="var(--text-primary, #f8fafc)"
            maxW="180px"
            _placeholder={{ color: 'var(--text-muted)', opacity: 0.5 }}
            _focus={{ borderColor: '#5B7FFF', outline: 'none' }}
          />
        </Box>
        <Box flex={1} minW="200px">
          <Text fontSize="11px" color="var(--text-muted, #475569)" mb={1}>Description</Text>
          <Box
            as="input"
            type="text"
            value={description}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onDescriptionChange(e.target.value)}
            placeholder="Ce que vous testez..."
            bg="var(--bg-input, #0f0f24)"
            border="1px solid"
            borderColor="var(--border-subtle, #1e1e3a)"
            rounded="md"
            px={3} py={1.5}
            fontSize="sm"
            color="var(--text-primary, #f8fafc)"
            w="100%"
            _placeholder={{ color: 'var(--text-muted)', opacity: 0.5 }}
            _focus={{ borderColor: '#5B7FFF', outline: 'none' }}
          />
        </Box>
      </HStack>

      <HStack spacing={3} flexWrap="wrap">
        {benchTypes.map(bt => (
          <Button
            key={bt.key}
            size="sm"
            variant="outline"
            borderColor={bt.color}
            color={bt.color}
            _hover={{ bg: `${bt.color}18` }}
            leftIcon={<FiPlay />}
            onClick={() => onLaunch(bt.key)}
            isDisabled={isRunning}
          >
            {bt.label}
          </Button>
        ))}
      </HStack>

      {isRunning && runProgress && (
        <Box mt={4}>
          <Progress
            value={runProgress.total > 0 ? (runProgress.progress / runProgress.total) * 100 : 0}
            size="xs"
            colorScheme="blue"
            rounded="full"
            bg="var(--border-subtle, #1e1e3a)"
          />
          <Text fontSize="11px" color="var(--text-muted, #475569)" mt={1}>
            {runProgress.phase} — {runProgress.progress}/{runProgress.total}
            {runProgress.current_question && ` — ${runProgress.current_question.slice(0, 60)}...`}
          </Text>
        </Box>
      )}
    </Box>
  )
}
