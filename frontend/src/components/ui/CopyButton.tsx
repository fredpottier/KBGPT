'use client'

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
        title: 'Copied!',
        description: 'Message copied to clipboard',
        status: 'success',
        duration: 2000,
        isClosable: true,
      })
      // Reset after 2 seconds
      setTimeout(() => setIsCopied(false), 2000)
    } catch (err) {
      toast({
        title: 'Copy failed',
        description: 'Failed to copy to clipboard',
        status: 'error',
        duration: 3000,
        isClosable: true,
      })
    }
  }

  return (
    <IconButton
      className={className}
      aria-label="Copy message"
      icon={isCopied ? <CheckIcon /> : <CopyIcon />}
      size={size}
      variant="ghost"
      opacity={0}
      transition="opacity 0.2s"
      color={isCopied ? 'green.500' : 'gray.500'}
      _hover={{
        opacity: 1,
        color: isCopied ? 'green.600' : 'gray.700',
        bg: 'gray.100'
      }}
      onClick={handleCopy}
    />
  )
}