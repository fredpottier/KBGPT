import { Button as ChakraButton, ButtonProps as ChakraButtonProps } from '@chakra-ui/react';

export interface ButtonProps extends ChakraButtonProps {
  variant?: 'default' | 'outline' | 'destructive' | 'ghost' | 'link' | 'solid';
}

export function Button({ variant = 'default', ...props }: ButtonProps) {
  let chakraVariant: ChakraButtonProps['variant'] = 'solid';
  let colorScheme = 'blue';

  switch (variant) {
    case 'outline':
      chakraVariant = 'outline';
      break;
    case 'destructive':
      chakraVariant = 'solid';
      colorScheme = 'red';
      break;
    case 'ghost':
      chakraVariant = 'ghost';
      break;
    case 'link':
      chakraVariant = 'link';
      break;
    case 'solid':
    case 'default':
    default:
      chakraVariant = 'solid';
      break;
  }

  return <ChakraButton variant={chakraVariant} colorScheme={colorScheme} {...props} />;
}