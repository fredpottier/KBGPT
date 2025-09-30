import {
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  Text,
  ModalProps as ChakraModalProps,
} from '@chakra-ui/react';

export interface DialogProps extends Omit<ChakraModalProps, 'isOpen' | 'onClose'> {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

export function Dialog({ open, onOpenChange, children, ...props }: DialogProps) {
  return (
    <Modal isOpen={open || false} onClose={() => onOpenChange?.(false)} {...props}>
      <ModalOverlay />
      {children}
    </Modal>
  );
}

export function DialogContent({ children }: { children: React.ReactNode }) {
  return <ModalContent>{children}</ModalContent>;
}

export function DialogHeader({ children }: { children: React.ReactNode }) {
  return (
    <>
      <ModalHeader>{children}</ModalHeader>
      <ModalCloseButton />
    </>
  );
}

export function DialogTitle({ children }: { children: React.ReactNode }) {
  return <Text fontWeight="bold" fontSize="lg">{children}</Text>;
}

export function DialogDescription({ children }: { children: React.ReactNode }) {
  return <Text fontSize="sm" color="gray.600" mt={2}>{children}</Text>;
}

export function DialogFooter({ children }: { children: React.ReactNode }) {
  return <ModalFooter>{children}</ModalFooter>;
}