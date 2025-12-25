'use client'

/**
 * OSMOS Copy Button - Dark Elegance Edition
 */

import { IconButton, useToast } from '@chakra-ui/react'
import { CopyIcon, CheckIcon } from '@chakra-ui/icons'
import { useState } from 'react'

interface CopyButtonProps {
  text: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
  className?: string
}

export default function CopyButton({ text, size = 'xs', className }: CopyButtonProps) {
  const [isCopied, setIsCopied] = useState(false)
  const toast = useToast()

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setIsCopied(true)
      toast({
        title: 'Copie',
        description: 'Contenu copie dans le presse-papiers',
        status: 'success',
        duration: 2000,
        isClosable: true,
      })
      setTimeout(() => setIsCopied(false), 2000)
    } catch (err) {
      toast({
        title: 'Erreur',
        description: 'Impossible de copier dans le presse-papiers',
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    }
  }

  return (
    <IconButton
      className={className}
      aria-label="Copier"
      icon={isCopied ? <CheckIcon /> : <CopyIcon />}
      size={size}
      variant="ghost"
      color={isCopied ? 'green.400' : 'text.muted'}
      _hover={{
        color: isCopied ? 'green.300' : 'text.primary',
        bg: 'bg.hover',
      }}
      transition="all 0.2s"
      onClick={handleCopy}
    />
  )
}
