'use client'

import { Textarea, TextareaProps } from '@chakra-ui/react'
import { forwardRef, useEffect, useRef, useCallback } from 'react'

interface AutoResizeTextareaProps extends Omit<TextareaProps, 'onChange'> {
  value: string
  onChange: (value: string) => void
  minHeight?: number
  maxHeight?: number
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
}

const AutoResizeTextarea = forwardRef<HTMLTextAreaElement, AutoResizeTextareaProps>(
  ({ value, onChange, minHeight = 40, maxHeight = 200, onKeyDown, ...props }, ref) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    const resize = useCallback(() => {
      const textarea = textareaRef.current
      if (!textarea) return

      textarea.style.height = 'auto'
      const scrollHeight = textarea.scrollHeight

      if (scrollHeight <= maxHeight) {
        textarea.style.height = `${Math.max(scrollHeight, minHeight)}px`
        textarea.style.overflowY = 'hidden'
      } else {
        textarea.style.height = `${maxHeight}px`
        textarea.style.overflowY = 'auto'
      }

      // Keep cursor visible when scrolling
      if (scrollHeight > maxHeight) {
        textarea.scrollTop = textarea.scrollHeight
      }
    }, [minHeight, maxHeight])

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value)
      resize()
    }

    // Resize on value changes (e.g., when clearing)
    useEffect(() => {
      resize()
    }, [value, resize])

    // Reset size when value is empty
    useEffect(() => {
      if (!value && textareaRef.current) {
        textareaRef.current.style.height = `${minHeight}px`
        textareaRef.current.style.overflowY = 'hidden'
      }
    }, [value, minHeight])

    return (
      <Textarea
        ref={(node) => {
          if (textareaRef.current !== node) {
            ;(textareaRef as any).current = node
          }
          if (typeof ref === 'function') {
            ref(node)
          } else if (ref) {
            ;(ref as any).current = node
          }
        }}
        value={value}
        onChange={handleChange}
        onKeyDown={onKeyDown}
        resize="none"
        minH={`${minHeight}px`}
        maxH={`${maxHeight}px`}
        h={`${minHeight}px`}
        transition="height 0.1s ease"
        sx={{
          '&::-webkit-scrollbar': {
            width: '4px',
          },
          '&::-webkit-scrollbar-track': {
            background: 'transparent',
          },
          '&::-webkit-scrollbar-thumb': {
            background: 'gray.300',
            borderRadius: '2px',
          },
          '&::-webkit-scrollbar-thumb:hover': {
            background: 'gray.400',
          },
        }}
        {...props}
      />
    )
  }
)

AutoResizeTextarea.displayName = 'AutoResizeTextarea'

export default AutoResizeTextarea