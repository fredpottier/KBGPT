# source-viewer — viewer PDF in-app avec surlignage du span (Phase C)

Module **autonome et supprimable**, livré le 09/06/2026. Permet, au clic sur une
citation du chat, d'ouvrir le PDF source **dans l'app** (modale) avec la page
cible rendue et le **span verbatim surligné**, au lieu d'ouvrir un onglet natif.

## Choix d'isolation
- **Aucune dépendance npm ajoutée** : `pdf.js` est chargé à la volée depuis un CDN
  (`import(/* webpackIgnore */ …)`). Donc pas de `package.json`/rebuild frontend.
- **Un seul point de câblage** dans `RuntimeA3Panel.tsx`, balisé `// [SOURCE_VIEWER]`.
- Champs backend consommés (`source_verbatim_quote`, `valid_from`, …) : **additifs**
  dans `CitedClaimRef` (runtime_v6.py), inoffensifs si le module est retiré.

## Désactiver (sans supprimer)
`index.ts` → `SOURCE_VIEWER_ENABLED = false`. Le clic citation reprend le
comportement historique (`openSourceFile` → onglet).

## Supprimer proprement
1. Effacer le dossier `frontend/src/components/source-viewer/`.
2. Dans `RuntimeA3Panel.tsx`, retirer les blocs balisés `// [SOURCE_VIEWER]`
   (import, state, `<SourceViewer>`, branche du onClick).
3. (Optionnel) Retirer les champs Phase C de `CitedClaimRef` + de
   `_hydrate_citation_sources`/`_build_response` dans `runtime_v6.py`.

## Limites connues (v1)
- Surlignage **approximatif** : on matche les fragments du text-layer pdf.js par
  tokens de la citation (les bornes ne s'alignent pas). Surligne les bons mots,
  pas toujours la phrase exacte au pixel.
- PDF natifs scannés (image, sans text-layer) → aucun surlignage (page affichée
  quand même). Repli « ouvrir dans un onglet » toujours disponible.
- Dépend d'un accès CDN navigateur (jsdelivr). Hors-ligne strict → repli onglet.
