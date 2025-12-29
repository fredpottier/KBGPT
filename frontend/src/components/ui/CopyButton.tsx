'use client'

/**
 * OSMOS Copy Button - Dark Elegance Edition
 */

import { IconButton, IconButtonProps, useToast } from '@chakra-ui/react'
import { CopyIcon, CheckIcon } from '@chakra-ui/icons'
import { useState } from 'react'

interface CopyButtonProps extends Omit<IconButtonProps, 'aria-label' | 'icon' | 'onClick'> {
  text: string
}

export default function CopyButton({ text, size = 'xs', variant = 'ghost', color, _hover, ...rest }: CopyButtonProps) {
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

  // Couleurs par defaut si non fournies
  const defaultColor = isCopied ? 'green.400' : 'text.muted'
  const defaultHover = {
    color: isCopied ? 'green.300' : 'text.primary',
    bg: 'bg.hover',
  }

  return (
    <IconButton
      aria-label="Copier"
      icon={isCopied ? <CheckIcon /> : <CopyIcon />}
      size={size}
      variant={variant}
      color={color || defaultColor}
      _hover={_hover || defaultHover}
      transition="all 0.2s"
      onClick={handleCopy}
      {...rest}
    />
  )
}
