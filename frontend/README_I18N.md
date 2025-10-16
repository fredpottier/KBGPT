# Système d'Internationalisation (i18n)

**Date** : 11 octobre 2025
**Statut** : ✅ Implémenté - Prêt à l'emploi

---

## 📚 Vue d'Ensemble

Le frontend utilise un système d'internationalisation **léger et natif** basé sur l'API `Intl` du navigateur, sans dépendance externe lourde.

### ✅ Avantages

- **Aucune dépendance externe** (pas de i18next, react-intl, etc.)
- **API native du navigateur** (Intl.RelativeTimeFormat, Intl.DateTimeFormat)
- **Performances optimales** - Pas de bundle JS supplémentaire
- **Pas de problème webpack/build** - Fonctionne immédiatement
- **Support multilingue extensible** - Ajouter des langues facilement

### 🌍 Langues Supportées

| Locale | Langue | Statut |
|--------|--------|--------|
| `fr` | Français | ✅ Défaut |
| `en` | English | ✅ Actif |
| `es` | Español | ✅ Actif |
| `de` | Deutsch | ✅ Actif |

---

## 🚀 Utilisation

### 1. Formatage de Dates Relatives

```tsx
import { formatDistanceToNow } from '@/lib/date-utils'
import { useLocale } from '@/contexts/LocaleContext'

function MyComponent() {
  const { locale } = useLocale()
  const date = new Date('2024-10-01')

  return (
    <Text>
      {formatDistanceToNow(date, locale)}
      {/* Affiche : "il y a 10 jours" (fr) ou "10 days ago" (en) */}
    </Text>
  )
}
```

### 2. Autres Formats de Dates

```tsx
import { formatDate, formatDateTime, formatDateShort } from '@/lib/date-utils'

// Date longue : "11 octobre 2024"
formatDate(new Date(), 'fr')

// Date + heure : "11 octobre 2024 à 14:30"
formatDateTime(new Date(), 'fr')

// Date courte : "11/10/2024"
formatDateShort(new Date(), 'fr')
```

### 3. Sélecteur de Langue

Ajouter un sélecteur de langue dans les paramètres utilisateur :

```tsx
import LanguageSelector from '@/components/common/LanguageSelector'

function SettingsPage() {
  return (
    <Box>
      <Heading>Préférences</Heading>
      <LanguageSelector showLabel={true} size="md" />
    </Box>
  )
}
```

### 4. Changer la Langue Programmatiquement

```tsx
import { useLocale } from '@/contexts/LocaleContext'

function MyComponent() {
  const { locale, setLocale } = useLocale()

  const switchToEnglish = () => {
    setLocale('en')
  }

  return <Button onClick={switchToEnglish}>Switch to English</Button>
}
```

---

## 🛠️ Architecture

### Fichiers Clés

```
frontend/
├── src/
│   ├── lib/
│   │   └── date-utils.ts           # Utilitaires de formatage de dates
│   ├── contexts/
│   │   └── LocaleContext.tsx       # Contexte React pour la langue
│   ├── components/
│   │   └── common/
│   │       └── LanguageSelector.tsx # Composant sélecteur de langue
│   └── app/
│       └── providers.tsx           # LocaleProvider enregistré ici
```

### Flux de Données

```
localStorage ('locale')
      ↓
LocaleProvider (détecte langue navigateur ou sauvegardée)
      ↓
useLocale() hook
      ↓
Composants (utilisent la locale courante)
```

---

## 📝 Extension du Système

### Ajouter une Nouvelle Langue

**1. Ajouter la locale dans le type**

Fichier : `frontend/src/lib/date-utils.ts`

```typescript
export type SupportedLocale = 'fr' | 'en' | 'es' | 'de' | 'it' // ← Ajouter 'it'
```

**2. Ajouter dans le contexte**

Fichier : `frontend/src/contexts/LocaleContext.tsx`

```typescript
const saved = localStorage.getItem('locale') as SupportedLocale | null
if (saved && ['fr', 'en', 'es', 'de', 'it'].includes(saved)) { // ← Ajouter 'it'
  return saved
}
```

**3. Ajouter dans le sélecteur**

Fichier : `frontend/src/components/common/LanguageSelector.tsx`

```typescript
const LANGUAGE_OPTIONS = [
  { value: 'fr', label: 'Français', flag: '🇫🇷' },
  { value: 'en', label: 'English', flag: '🇬🇧' },
  { value: 'es', label: 'Español', flag: '🇪🇸' },
  { value: 'de', label: 'Deutsch', flag: '🇩🇪' },
  { value: 'it', label: 'Italiano', flag: '🇮🇹' }, // ← Nouvelle langue
]
```

**C'est tout !** 🎉 L'API `Intl` du navigateur gère automatiquement les traductions.

---

## 🧪 Tests

### Tester le Changement de Langue

```tsx
import { render, screen } from '@testing-library/react'
import { LocaleProvider } from '@/contexts/LocaleContext'
import MyComponent from './MyComponent'

test('affiche la date en français', () => {
  render(
    <LocaleProvider>
      <MyComponent />
    </LocaleProvider>
  )
  expect(screen.getByText(/il y a/)).toBeInTheDocument()
})
```

---

## 🔮 Évolutions Futures

### Phase 2 : Traduction des Textes UI

Si tu veux traduire les textes de l'interface (boutons, labels, etc.), tu peux :

**Option A : Créer un dictionnaire simple**

```typescript
// frontend/src/lib/translations.ts
export const translations = {
  fr: {
    save: 'Enregistrer',
    cancel: 'Annuler',
    delete: 'Supprimer',
  },
  en: {
    save: 'Save',
    cancel: 'Cancel',
    delete: 'Delete',
  },
}

// Utilisation
import { useLocale } from '@/contexts/LocaleContext'
import { translations } from '@/lib/translations'

function MyComponent() {
  const { locale } = useLocale()
  const t = translations[locale]

  return <Button>{t.save}</Button>
}
```

**Option B : Utiliser une bibliothèque (si vraiment nécessaire)**

Si le projet grandit énormément, tu peux ajouter `next-intl` ou `react-i18next` plus tard.

---

## 📚 Ressources

- [MDN - Intl.RelativeTimeFormat](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/RelativeTimeFormat)
- [MDN - Intl.DateTimeFormat](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat)
- [Can I Use - Intl API](https://caniuse.com/mdn-javascript_builtins_intl_relativetimeformat)

---

## ✅ Checklist Implémentation

- [x] Créer `date-utils.ts` avec fonctions de formatage
- [x] Créer `LocaleContext` avec hook `useLocale()`
- [x] Enregistrer `LocaleProvider` dans `providers.tsx`
- [x] Créer composant `LanguageSelector`
- [x] Mettre à jour page Timeline pour utiliser le système
- [ ] Ajouter sélecteur de langue dans les paramètres utilisateur
- [ ] (Optionnel) Créer dictionnaire de traductions pour les textes UI

---

**Maintenu par** : Équipe Frontend SAP KB
**Dernière mise à jour** : 11 octobre 2025
