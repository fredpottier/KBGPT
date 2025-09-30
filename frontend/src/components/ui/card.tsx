import { Box, BoxProps } from '@chakra-ui/react';

export function Card({ children, ...props }: BoxProps) {
  return (
    <Box
      bg="white"
      borderRadius="lg"
      borderWidth="1px"
      borderColor="gray.200"
      shadow="sm"
      overflow="hidden"
      {...props}
    >
      {children}
    </Box>
  );
}