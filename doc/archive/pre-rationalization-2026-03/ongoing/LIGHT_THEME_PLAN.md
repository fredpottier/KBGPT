# Plan — Thème Light pour le Frontend

**Statut** : À planifier
**Priorité** : Basse (amélioration UX future)
**Effort estimé** : 2-3 jours

## Contexte

Le frontend utilise un thème "Dark Modern" unique. Certains utilisateurs pourraient préférer un thème clair. L'architecture actuelle supporte bien l'ajout d'un second thème grâce à la tokenisation existante.

## État actuel

- `theme/tokens.ts` — contient déjà une `paletteLight` (partiellement définie)
- `theme/darkTheme.ts` — 440 lignes mappant les tokens sémantiques
- **55 fichiers** utilisent des tokens sémantiques (`text.primary`, `surface.default`) → bascule automatique
- **~12 fichiers** avec couleurs hex en dur → à convertir en tokens
- **~32 fichiers** avec rgba() hardcodés → ajuster opacités pour le light
- `globals.css` — variables CSS dark only → ajouter variantes light

## Tâches

1. Compléter `paletteLight` dans `tokens.ts`
2. Créer `lightTheme.ts` (miroir structurel de `darkTheme.ts`)
3. Ajouter variables CSS light dans `globals.css` (media query ou classe)
4. Câbler `useColorMode()` de Chakra + provider
5. Créer composant toggle theme (header ou settings)
6. Auditer/corriger les ~12 fichiers avec hex en dur
7. Ajuster les rgba() dans les ~32 fichiers concernés
8. Tests visuels sur toutes les pages en mode light
9. Persister le choix utilisateur (localStorage)

## Notes

- Le gros du travail est le QA visuel, pas le code
- Les pages admin (claimfirst notamment avec 121 hex) demanderont le plus d'effort
- Possibilité future d'ajouter d'autres thèmes (high contrast, etc.) avec la même architecture
