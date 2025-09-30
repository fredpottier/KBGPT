import { Badge as ChakraBadge, BadgeProps as ChakraBadgeProps } from '@chakra-ui/react';

export interface BadgeProps extends ChakraBadgeProps {
  variant?: 'default' | 'secondary' | 'outline' | 'destructive';
}

export function Badge({ variant = 'default', ...props }: BadgeProps) {
  let chakraVariant: ChakraBadgeProps['variant'] = 'solid';
  let colorScheme = 'blue';

  switch (variant) {
    case 'secondary':
      colorScheme = 'gray';
      break;
    case 'outline':
      chakraVariant = 'outline';
      break;
    case 'destructive':
      colorScheme = 'red';
      break;
    case 'default':
    default:
      colorScheme = 'blue';
      break;
  }

  return <ChakraBadge variant={chakraVariant} colorScheme={colorScheme} {...props} />;
}