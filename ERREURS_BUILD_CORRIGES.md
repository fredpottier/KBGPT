# Erreurs de Build Corrigées

**Date :** 2025-10-13

---

## ✅ Erreur 1 : Warning PYTHONPATH (Corrigé)

### Problème
```
1 warning found (use docker --debug to expand):
 - UndefinedVar: Usage of undefined variable '$PYTHONPATH' (line 15)
```

### Cause
Les Dockerfiles utilisaient `$PYTHONPATH` avant qu'il ne soit défini.

### Solution Appliquée
**Fichiers modifiés :**
- `ui/Dockerfile` (ligne 15)
- `app/Dockerfile` (ligne 67)

**Changement :**
```dockerfile
# ❌ AVANT
ENV PYTHONPATH="/app/src:$PYTHONPATH"

# ✅ APRÈS
ENV PYTHONPATH="/app/src"
```

**Résultat :** Warning disparaîtra au prochain build ✅

---

## ✅ Erreur 2 : React Hook Conditionnel (Corrigé)

### Problème
```
./src/app/admin/documents/[id]/timeline/page.tsx
225:47  Error: React Hook "useState" is called conditionally.
React Hooks must be called in the exact same order in every component render.
```

### Cause
Le `useState` était appelé APRÈS des `return` conditionnels, ce qui viole les règles des Hooks React.

### Solution Appliquée
**Fichier modifié :**
- `frontend/src/app/admin/documents/[id]/timeline/page.tsx` (lignes 172-173, 227)

**Changement :**
```tsx
// ❌ AVANT (MAUVAIS ORDRE)
export default function DocumentTimelinePage({ params }) {
  const { id } = use(params)
  const router = useRouter()

  // useQuery hooks...

  if (isLoading) {
    return (...)  // Return conditionnel
  }

  if (error) {
    return (...)  // Return conditionnel
  }

  // ❌ useState APRÈS les returns (INTERDIT)
  const [showActiveOnly, setShowActiveOnly] = useState(false)
}

// ✅ APRÈS (BON ORDRE)
export default function DocumentTimelinePage({ params }) {
  const { id } = use(params)
  const router = useRouter()

  // ✅ useState AVANT les returns
  const [showActiveOnly, setShowActiveOnly] = useState(false)

  // useQuery hooks...

  if (isLoading) {
    return (...)
  }

  if (error) {
    return (...)
  }
}
```

**Résultat :** Build Next.js fonctionnera au prochain build ✅

---

## 🚀 Prochaines Étapes

### Relancer le Build

```powershell
# Depuis la racine du projet
cd C:\Project\SAP_KB

# Relancer le build complet
.\scripts\aws\build-and-push-ecr.ps1

# Ou build rapide (sans third-party)
.\scripts\aws\build-and-push-ecr.ps1 -SkipThirdParty
```

### Vérifications Attendues

Le build devrait maintenant :
- ✅ Compiler l'image backend sans warning PYTHONPATH
- ✅ Compiler l'image UI sans warning PYTHONPATH
- ✅ Compiler l'image frontend Next.js sans erreur React Hook
- ✅ Pousser toutes les images vers ECR avec succès

---

## 📊 Résumé

| Erreur | Fichier(s) | Statut |
|--------|-----------|--------|
| Warning PYTHONPATH | `ui/Dockerfile`, `app/Dockerfile` | ✅ Corrigé |
| React Hook conditionnel | `frontend/.../timeline/page.tsx` | ✅ Corrigé |

**Toutes les erreurs sont corrigées. Vous pouvez relancer le build.**

---

## 💡 Leçons Apprises

### Règle des Hooks React
**TOUS les Hooks (`useState`, `useEffect`, `useCallback`, etc.) doivent être appelés :**
- ✅ En haut du composant
- ✅ AVANT tout `return` conditionnel
- ✅ AVANT tout `if/else`
- ✅ Dans le même ordre à chaque render

### Variables d'Environnement Docker
**Dans un Dockerfile, évitez de concaténer avec des variables inexistantes :**
```dockerfile
# ❌ Mauvais si $VAR n'existe pas
ENV PATH="/new/path:$VAR"

# ✅ Bon
ENV PATH="/new/path"

# ✅ Ou définir d'abord
ENV VAR=""
ENV PATH="/new/path:$VAR"
```

---

**Dernière mise à jour :** 2025-10-13 16:30
