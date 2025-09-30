import {
  Alert as ChakraAlert,
  AlertIcon,
  AlertTitle as ChakraAlertTitle,
  AlertDescription as ChakraAlertDescription,
  AlertProps as ChakraAlertProps,
} from '@chakra-ui/react';

export interface AlertProps extends ChakraAlertProps {
  variant?: 'default' | 'destructive';
}

export function Alert({ variant = 'default', ...props }: AlertProps) {
  const status = variant === 'destructive' ? 'error' : 'info';

  return <ChakraAlert status={status} {...props} />;
}

export function AlertTitle({ children }: { children: React.ReactNode }) {
  return <ChakraAlertTitle>{children}</ChakraAlertTitle>;
}

export function AlertDescription({ children }: { children: React.ReactNode }) {
  return <ChakraAlertDescription>{children}</ChakraAlertDescription>;
}