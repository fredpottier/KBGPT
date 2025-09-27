import { useState, useEffect } from 'react'

/**
 * Hook personnalisé pour gérer le localStorage avec synchronisation React
 */
export function useLocalStorage<T>(key: string, initialValue: T) {
  // État pour savoir si on est côté client
  const [isClient, setIsClient] = useState(false)

  // Récupérer la valeur du localStorage ou utiliser la valeur initiale
  const [storedValue, setStoredValue] = useState<T>(initialValue)

  // S'exécute seulement côté client
  useEffect(() => {
    setIsClient(true)

    try {
      const item = window.localStorage.getItem(key)
      const value = item ? JSON.parse(item) : initialValue
      setStoredValue(value)
    } catch (error) {
      console.warn(`Erreur lors de la lecture du localStorage pour la clé "${key}":`, error)
      setStoredValue(initialValue)
    }
  }, [key, initialValue])

  // Fonction pour mettre à jour la valeur
  const setValue = (value: T | ((val: T) => T)) => {
    try {
      // Permettre à la valeur d'être une fonction pour la mise à jour basée sur l'état précédent
      const valueToStore = value instanceof Function ? value(storedValue) : value
      setStoredValue(valueToStore)

      // Sauvegarder dans le localStorage seulement côté client
      if (isClient && typeof window !== 'undefined') {
        window.localStorage.setItem(key, JSON.stringify(valueToStore))
      }
    } catch (error) {
      console.error(`Erreur lors de la sauvegarde dans le localStorage pour la clé "${key}":`, error)
    }
  }

  return [storedValue, setValue] as const
}