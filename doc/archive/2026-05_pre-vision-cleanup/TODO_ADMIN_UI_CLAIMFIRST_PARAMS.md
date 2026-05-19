# TODO — Frontend admin : paramètres ClaimFirst configurables

**Contexte (18/04/2026)** : pendant l'investigation du faible linkage Claim→Facet (27%) sur le corpus biomedical prééclampsie (57 docs, 7627 claims), on a identifié que le paramètre `MAX_FACETS_PER_DOC = 6` hardcodé était le principal goulot.

Solution temporaire : exposé via `config/feature_flags.yaml` → `claimfirst_pipeline.facet_extraction.max_per_doc`.

## Besoin

Certains paramètres du pipeline ClaimFirst sont **très dépendants du type de corpus** et devraient être ajustables **sans redémarrer le worker** ni modifier un fichier YAML par l'admin technique.

### Paramètres à exposer (par ordre d'impact)

**1. `facet_extraction.max_per_doc`** *(priorité haute)*
- Nombre max de facettes extraites par document
- Valeur actuelle : 12 (passé de 6 après tuning biomédical)
- Recommandations UI :
  - `6` — corpus compacts (notes, fiches)
  - `10-12` — corpus scientifique/technique (défaut)
  - `15+` — corpus très riches (manuels, régulatoire complexe)
- Impact : +20-30 pts sur le score "Linkage Claim→Facet" de l'audit KG

**2. `extraction.min_unit_length` / `max_unit_length`** *(priorité moyenne)*
- Longueurs min/max d'une unité (AssertionUnit) pour l'extraction de claims
- Actuels : 30 / 500
- Corpus avec phrases longues (juridique, scientifique) → max_unit_length 800+
- Corpus télégraphique (techniques, specs) → min_unit_length 15

**3. `clustering.embedding_threshold`** *(priorité moyenne)*
- Seuil de similarité embedding pour clustering de claims similaires
- Actuel : 0.85 (conservateur)
- Corpus à forte variabilité linguistique (multi-source) → 0.80 pour recall
- Corpus homogène → 0.90 pour précision

**4. `canonicalize.embedding_threshold`** *(à ajouter — pas encore exposé)*
- Seuil pour fusion d'Entity vers CanonicalEntity
- Hardcodé actuellement, diagnostic en cours

## Design frontend proposé

Page `/admin/claimfirst-settings` :
- Section "Extraction de facettes"
  - Slider / input numérique pour `max_per_doc` (range 3-20)
  - Description contextuelle (selon type de corpus détecté)
- Section "Extraction de claims"
  - Inputs min/max unit_length
  - Input batch_size
- Section "Clustering"
  - Slider `embedding_threshold` (0.70-0.95)
- Bouton "Appliquer" → écrit dans PostgreSQL `tenant_settings` + invalide cache feature_flags
- Bouton "Reset aux défauts"

## Implémentation technique

- Ajouter table `tenant_settings(tenant_id, section, params_json)` en PostgreSQL
- Modifier `get_feature_flags(tenant_id)` pour merger `feature_flags.yaml` + settings tenant-spécifiques
- Endpoints API :
  - `GET /api/admin/claimfirst/params` → retourne settings effectifs + défauts
  - `PATCH /api/admin/claimfirst/params` → met à jour settings du tenant
- Invalidation : clear `_feature_flags_cache` après PATCH

## Priorité
Chantier à planifier après validation du workflow corpus biomédical. Non bloquant pour les runs actuels.

---
*Créé le 18/04/2026 pendant la session de tuning post-ingestion prééclampsie.*
