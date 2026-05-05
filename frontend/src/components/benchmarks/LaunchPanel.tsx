'use client'

import { Box, Button, HStack, Text, Progress, Select } from '@chakra-ui/react'
import { FiPlay } from 'react-icons/fi'

// Aligné sur preset-vars.css du thème actif (light/dark gérés par les CSS vars)
const C = {
  bgCard: 'var(--bg-surface)',
  bgInput: 'var(--bg-canvas)',
  borderSubtle: 'var(--border-default)',
  textPrimary: 'var(--fg-primary)',
  textSecondary: 'var(--fg-secondary)',
  textMuted: 'var(--fg-muted)',
  accentBlue: '#5B7FFF',
}

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
  onLaunchAll?: () => void
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
  onLaunchAll,
}: LaunchPanelProps) {
  return (
    <Box
      bg={C.bgCard}
      border="1px solid"
      borderColor={C.borderSubtle}
      rounded="lg"
      p={5}
    >
      <Text fontSize="sm" fontWeight="700" color={C.textPrimary} mb={4}>
        Lancer un benchmark
      </Text>

      <HStack spacing={4} mb={4} flexWrap="wrap">
        <Box>
          <Text fontSize="11px" color={C.textMuted} mb={1}>Profil</Text>
          <Select
            size="sm"
            value={selectedProfile}
            onChange={(e) => onProfileChange(e.target.value)}
            bg={C.bgInput}
            borderColor={C.borderSubtle}
            color={C.textPrimary}
            maxW="200px"
            sx={{ '> option': { bg: C.bgCard, color: C.textPrimary } }}
          >
            {profiles.map(p => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </Select>
        </Box>
        <Box>
          <Text fontSize="11px" color={C.textMuted} mb={1}>Tag</Text>
          <Box
            as="input"
            type="text"
            value={tag}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onTagChange(e.target.value)}
            placeholder="ex: POST_C6"
            bg={C.bgInput}
            border="1px solid"
            borderColor={C.borderSubtle}
            rounded="md"
            px={3} py={1.5}
            fontSize="sm"
            color={C.textPrimary}
            maxW="180px"
            _placeholder={{ color: C.textMuted, opacity: 0.6 }}
            _focus={{ borderColor: C.accentBlue, outline: 'none' }}
          />
        </Box>
        <Box flex={1} minW="200px">
          <Text fontSize="11px" color={C.textMuted} mb={1}>Description</Text>
          <Box
            as="input"
            type="text"
            value={description}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => onDescriptionChange(e.target.value)}
            placeholder="Ce que vous testez..."
            bg={C.bgInput}
            border="1px solid"
            borderColor={C.borderSubtle}
            rounded="md"
            px={3} py={1.5}
            fontSize="sm"
            color={C.textPrimary}
            w="100%"
            _placeholder={{ color: C.textMuted, opacity: 0.6 }}
            _focus={{ borderColor: C.accentBlue, outline: 'none' }}
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
        {onLaunchAll && (
          <Button
            size="sm"
            variant="outline"
            borderColor={C.textSecondary}
            color={C.textSecondary}
            _hover={{ bg: 'rgba(148, 163, 184, 0.12)' }}
            leftIcon={<FiPlay />}
            onClick={onLaunchAll}
            isDisabled={isRunning}
          >
            Lancer tout
          </Button>
        )}
      </HStack>

      {isRunning && runProgress && (
        <Box mt={4}>
          <Progress
            value={runProgress.total > 0 ? (runProgress.progress / runProgress.total) * 100 : 0}
            size="xs"
            colorScheme="blue"
            rounded="full"
            bg={C.borderSubtle}
          />
          <Text fontSize="11px" color={C.textMuted} mt={1}>
            {runProgress.phase} — {runProgress.progress}/{runProgress.total}
            {runProgress.current_question && ` — ${runProgress.current_question.slice(0, 60)}...`}
          </Text>
        </Box>
      )}
    </Box>
  )
}
