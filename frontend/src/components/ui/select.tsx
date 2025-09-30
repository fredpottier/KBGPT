import { Select as ChakraSelect, SelectProps as ChakraSelectProps } from '@chakra-ui/react';

export interface SelectProps extends ChakraSelectProps {
  value?: string;
  onValueChange?: (value: string) => void;
}

export function Select({ value, onValueChange, onChange, children, ...props }: SelectProps) {
  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    if (onValueChange) {
      onValueChange(e.target.value);
    }
    if (onChange) {
      onChange(e);
    }
  };

  return (
    <ChakraSelect value={value} onChange={handleChange} {...props}>
      {children}
    </ChakraSelect>
  );
}

export function SelectTrigger({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function SelectValue() {
  return null;
}

export function SelectContent({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function SelectItem({ value, children }: { value: string; children: React.ReactNode }) {
  return <option value={value}>{children}</option>;
}