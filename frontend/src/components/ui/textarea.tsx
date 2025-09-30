import { Textarea as ChakraTextarea, TextareaProps as ChakraTextareaProps } from '@chakra-ui/react';

export interface TextareaProps extends ChakraTextareaProps {}

export function Textarea(props: TextareaProps) {
  return <ChakraTextarea {...props} />;
}