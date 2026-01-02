# OSMOSIS Extraction V2 - Tracking d'implémentation

**Date de création:** 2026-01-02
**Objectif:** Refonte complète du pipeline d'extraction documentaire
**Status global:** ✅ ARCHITECTURE VALIDÉE - Prêt pour implémentation

---

## 📚 Documents de référence

| Document | Chemin | Description |
|----------|--------|-------------|
| Cadrage initial | (conversation) | Problèmes structurels, principes directeurs |
| Architecture cible | `doc/ongoing/OSMOSIS_ARCHITECTURE_CIBLE_V2.md` | Flow Docling → Gating → Vision → Merge |
| Vision Gating v4 Spec | `doc/ongoing/VISION_GATING_V4_SPEC.md` | 5 signaux, scoring, pseudo-code |
| Vision Gating v4 Checklist | `doc/ongoing/VISION_GATING_V4_CHECKLIST.md` | Checklist d'implémentation détaillée |
| Schéma de classes Python | `doc/ongoing/VISION_GATING_V4_CLASS_SCHEMA.py` | Modèles de données, interfaces |
| Prompt Vision canonique | `doc/ongoing/VISION_PROMPT_CANONICAL.md` | Prompt agnostique + Domain Context |
| **Décisions consolidées** | `doc/ongoing/OSMOSIS_EXTRACTION_V2_DECISIONS.md` | **Arbitrage final - 10 décisions** |
| Revue critique | `doc/ongoing/OSMOSIS_EXTRACTION_V2_CRITICAL_REVIEW.md` | Analyse des zones d'ombre |
| Pipeline actuel (référence) | `doc/ongoing/EXTRACTION_PIPELINE_ARCHITECTURE.md` | Documentation du pipeline existant |

---

## 🎯 Objectifs de la refonte

### Ce que la V2 doit résoudre

- ✅ Tables préservées (pas aplaties)
- ✅ Hiérarchie fiable (titres/sections)
- ✅ Diagrammes images **ET** shapes vectoriels
- ✅ Vision contextuelle et conditionnelle
- ✅ Aucune hallucination systémique
- ✅ Scalabilité grands documents (500+ pages)

### Principe fondamental

> **L'extraction factuelle doit être séparée de la compréhension.**

---

## 🔄 Architecture cible (vue synthétique - MISE À JOUR 2026-01-02)

```
Document brut (PDF / DOCX / PPTX / XLSX / Image)
          │
          ▼
    Ingestion Router
          │
    ┌─────┴─────────────────────┐
    ▼                           ▼
 Formats Office              Images
 (PDF/DOCX/PPTX/XLSX)        (PNG/JPEG/etc.)
    │                           │
 Docling (unifié)           OCR + Vision direct
    │                           │
    └─────────┬─────────────────┘
              ▼
    VisionUnit (structure normalisée)
              │
              ▼
    Vision Gating v4 (décision par page/slide)
              │
    ┌─────────┴─────────┐
    ▼                   ▼
NO_VISION          VISION_REQUIRED
    │                   │
    │           Vision Path + Domain Context
    │                   │ (via DomainContextStore existant)
    │                   │
    │           ┌───────┴───────┐
    │           ▼               ▼
    │    VisionExtraction    vision_text
    │    (→ KG direct)       (→ full_text)
    │           │               │
    └─────┬─────┴───────────────┘
          ▼
    Structured Merge + Linéarisation
          │
          ▼
    ExtractionResult
    ├── full_text (avec marqueurs) → OSMOSE
    └── structure (DocumentOutput) → Futur/Audit
```

### Décisions clés intégrées

1. **Docling = point d'entrée unifié** pour tous les formats Office (PDF, DOCX, PPTX, XLSX)
2. **Vision produit 2 sorties** : `VisionExtraction` (KG) + `vision_text` (OSMOSE)
3. **DomainContext unique** : via `DomainContextStore` existant + adaptateur
4. **Linéarisation avec marqueurs** : `[PAGE]`, `[TITLE]`, `[TABLE_START/END]`, `[VISUAL_ENRICHMENT]`
5. **VDS Signal** : Docling `visual_elements[]` en priorité, fallback PyMuPDF/python-pptx si nécessaire

---

## 📋 Phases d'implémentation

### Phase 0: Préparation (Status: 🟡 EN COURS)

| # | Tâche | Status | Notes |
|---|-------|--------|-------|
| 0.1 | Ajouter Docling aux requirements | ⬜ TODO | `docling>=2.0.0` |
| 0.2 | Tester Docling sur PDF sample | ⬜ TODO | Valider sortie JSON |
| 0.3 | Tester Docling sur PPTX sample | ⬜ TODO | Valider support officiel PPTX |
| 0.4 | Tester Docling sur DOCX/XLSX samples | ⬜ TODO | Valider tous formats Office |
| 0.5 | Vérifier exposition `visual_elements[]` | ⬜ TODO | Pour signal VDS |
| 0.6 | Créer structure de fichiers | ⬜ TODO | `src/knowbase/extraction_v2/` |

> ✅ **Clarification PPTX** : Docling supporte officiellement PPTX (format Office Open XML).
> Source : documentation officielle Docling. L'approche est donc unifiée pour tous formats Office.

### Phase 1: Modèles de données (Status: ⬜ TODO) ⚠️ CRITIQUE

> **Cette phase DOIT être gelée avant Phase 3.**
> Tous les signaux, décisions et merges dépendent de ces modèles.

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 1.1 | Créer `VisionUnit` | ⬜ TODO | `extraction_v2/models/vision_unit.py` |
| 1.2 | Créer `VisionSignals` | ⬜ TODO | `extraction_v2/models/signals.py` |
| 1.3 | Créer `GatingDecision` | ⬜ TODO | `extraction_v2/models/gating.py` |
| 1.4 | Créer `BoundingBox`, `TextBlock`, `VisualElement` | ⬜ TODO | `extraction_v2/models/elements.py` |
| 1.5 | Créer `ExtractionResult` (interface OSMOSE) | ⬜ TODO | `extraction_v2/models/extraction_result.py` |
| 1.6 | Créer adaptateur `DomainContext` | ⬜ TODO | `extraction_v2/models/domain_context.py` |
| 1.7 | Créer `VisionExtraction` + `vision_text` | ⬜ TODO | `extraction_v2/models/vision_output.py` |

### Phase 2: Extracteurs (Status: ⬜ TODO)

> **Architecture unifiée** : Docling pour tous les formats Office (PDF, DOCX, PPTX, XLSX)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 2.1 | Créer `DoclingExtractor` (unifié) | ⬜ TODO | `extraction_v2/extractors/docling_extractor.py` |
| 2.2 | Implémenter `extract_document()` | ⬜ TODO | Support PDF, DOCX, PPTX, XLSX |
| 2.3 | Implémenter détection auto format | ⬜ TODO | Via extension ou magic bytes |
| 2.4 | Créer `DoclingUnitAdapter` | ⬜ TODO | `extraction_v2/adapters/docling_adapter.py` |
| 2.5 | Mapper sortie Docling → `VisionUnit` | ⬜ TODO | Pour chaque page/slide |
| 2.6 | Implémenter fallback VDS | ⬜ TODO | PyMuPDF (PDF) / python-pptx (PPTX) si `visual_elements[]` insuffisant |
| 2.7 | Tests unitaires extracteur | ⬜ TODO | `tests/extraction_v2/test_docling_extractor.py` |

### Phase 3: Vision Gating v4 - Signaux (Status: ⬜ TODO)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 3.1 | Implémenter `compute_raster_image_signal()` (RIS) | ⬜ TODO | `extraction_v2/gating/signals.py` |
| 3.2 | Implémenter `compute_vector_drawing_signal()` (VDS) | ⬜ TODO | |
| 3.3 | Implémenter `compute_text_fragmentation_signal()` (TFS) | ⬜ TODO | |
| 3.4 | Implémenter `compute_spatial_dispersion_signal()` (SDS) | ⬜ TODO | |
| 3.5 | Implémenter `compute_visual_table_signal()` (VTS) | ⬜ TODO | |
| 3.6 | Tests unitaires pour chaque signal | ⬜ TODO | `tests/extraction_v2/test_signals.py` |

### Phase 4: Vision Gating v4 - Engine (Status: ⬜ TODO)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 4.1 | Implémenter `GatingEngine` | ⬜ TODO | `extraction_v2/gating/engine.py` |
| 4.2 | Implémenter `compute_vision_need_score()` | ⬜ TODO | |
| 4.3 | Implémenter `adjust_weights()` (Domain Context) | ⬜ TODO | |
| 4.4 | Implémenter règle de sécurité (RIS=1 OU VDS=1) | ⬜ TODO | |
| 4.5 | Implémenter seuils de décision | ⬜ TODO | |
| 4.6 | Tests unitaires engine | ⬜ TODO | `tests/extraction_v2/test_gating_engine.py` |

### Phase 5: Vision Path (Status: ⬜ TODO)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 5.1 | Créer `VisionAnalyzer` (interface) | ⬜ TODO | `extraction_v2/vision/analyzer.py` |
| 5.2 | Implémenter prompt Vision canonique | ⬜ TODO | `extraction_v2/vision/prompts.py` |
| 5.3 | Implémenter injection Domain Context | ⬜ TODO | |
| 5.4 | Implémenter appel GPT-4o Vision | ⬜ TODO | |
| 5.5 | Parser sortie JSON stricte | ⬜ TODO | |
| 5.6 | Tests Vision (avec mocks) | ⬜ TODO | `tests/extraction_v2/test_vision.py` |

### Phase 6: Structured Merge (Status: ⬜ TODO)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 6.1 | Créer `StructuredMerger` | ⬜ TODO | `extraction_v2/merge/merger.py` |
| 6.2 | Fusionner Docling + Vision (sans écrasement) | ⬜ TODO | |
| 6.3 | Générer `DocumentOutput` final | ⬜ TODO | |
| 6.4 | Tests merge | ⬜ TODO | `tests/extraction_v2/test_merge.py` |

### Phase 7: Intégration Pipeline (Status: ⬜ TODO)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 7.1 | Créer `ExtractionPipelineV2` | ⬜ TODO | `extraction_v2/pipeline.py` |
| 7.2 | Intégrer avec système de cache existant | ⬜ TODO | |
| 7.3 | Intégrer avec OSMOSE agentique | ⬜ TODO | |
| 7.4 | Migration progressive (feature flag) | ⬜ TODO | `config/feature_flags.yaml` |
| 7.5 | Tests end-to-end | ⬜ TODO | `tests/extraction_v2/test_pipeline_e2e.py` |

### Phase 8: Observabilité (Status: ⬜ TODO)

| # | Tâche | Status | Fichier cible |
|---|-------|--------|---------------|
| 8.1 | Logs structurés par unit | ⬜ TODO | |
| 8.2 | Export JSON pour audit | ⬜ TODO | |
| 8.3 | Métriques (décisions, scores, temps) | ⬜ TODO | |

---

## 📐 Structure de fichiers cible

```
src/knowbase/extraction_v2/
├── __init__.py
├── pipeline.py                    # ExtractionPipelineV2
│
├── models/
│   ├── __init__.py
│   ├── vision_unit.py             # VisionUnit
│   ├── signals.py                 # VisionSignals
│   ├── gating.py                  # GatingDecision, ExtractionAction
│   ├── elements.py                # BoundingBox, TextBlock, VisualElement
│   ├── extraction_result.py       # ExtractionResult (interface OSMOSE)
│   ├── domain_context.py          # VisionDomainContext + adaptateur
│   └── vision_output.py           # VisionExtraction, VisionElement, etc.
│
├── extractors/
│   ├── __init__.py
│   ├── docling_extractor.py       # DoclingExtractor (unifié tous formats)
│   └── vds_fallback.py            # Fallback VDS (PyMuPDF, python-pptx)
│
├── adapters/
│   ├── __init__.py
│   └── docling_adapter.py         # DoclingUnitAdapter → VisionUnit
│
├── gating/
│   ├── __init__.py
│   ├── signals.py                 # compute_*_signal() functions
│   ├── engine.py                  # GatingEngine
│   └── weights.py                 # DEFAULT_WEIGHTS, THRESHOLDS
│
├── vision/
│   ├── __init__.py
│   ├── analyzer.py                # VisionAnalyzer
│   ├── prompts.py                 # Prompt Vision canonique
│   └── text_generator.py          # Génération vision_text pour OSMOSE
│
├── merge/
│   ├── __init__.py
│   ├── merger.py                  # StructuredMerger
│   └── linearizer.py              # Linéarisation full_text avec marqueurs
│
└── cache/
    ├── __init__.py
    └── versioned_cache.py         # Cache versionné (v2)

tests/extraction_v2/
├── __init__.py
├── test_docling_extractor.py
├── test_signals.py
├── test_gating_engine.py
├── test_vision.py
├── test_merge.py
├── test_linearizer.py
└── test_pipeline_e2e.py
```

---

## 🧠 Prompt Vision canonique

Le prompt Vision est **agnostique du domaine** et permet l'injection dynamique du Domain Context.

### Structure du prompt

```
SYSTEM:
  - Rôle: visual analysis engine
  - Contraintes: no inference, no domain expansion, JSON only

USER:
  1. Image (page/slide)
  2. Local text snippets (optionnel)
  3. Domain Context (injecté dynamiquement)
  4. JSON schema strict

CONTRAINTES CRITIQUES:
  - No inference without visual evidence
  - No domain expansion
  - Every relation must reference visual evidence
  - Ambiguity must be declared, not resolved
  - Output ONLY JSON
```

### Schema JSON de sortie Vision

```json
{
  "diagram_type": "architecture_diagram | process_workflow | system_landscape | ...",
  "elements": [
    {
      "id": "string",
      "type": "box | label | arrow | group | icon | other",
      "text": "string",
      "confidence": 0.0
    }
  ],
  "relations": [
    {
      "source_id": "string",
      "target_id": "string",
      "relation_type": "contains | flows_to | integrates_with | depends_on | grouped_with | other",
      "evidence": "arrow | line | grouping | alignment | proximity | label_near_line",
      "confidence": 0.0
    }
  ],
  "ambiguities": [
    {
      "term": "string",
      "possible_interpretations": ["string"],
      "reason": "string"
    }
  ],
  "uncertainties": [
    {
      "item": "string",
      "reason": "string"
    }
  ]
}
```

### Injection Domain Context

Le Domain Context est injecté dans une section dédiée du prompt :

```
## DOMAIN CONTEXT (INJECTED BY SYSTEM)

<<< INSERT DOMAIN CONTEXT HERE >>>

Example for SAP:
- interpretation_rules: ["Interpret acronyms in SAP context", "Disambiguate Cloud variants"]
- domain_vocabulary: {"ERP": "S/4HANA, RISE, GROW", "Platform": "BTP, CPI, SAC"}
- extraction_focus: "Identify SAP solutions only if explicitly visible"
```

---

## 🔧 Dépendances à ajouter

### requirements.txt (à ajouter)

```
# === Extraction V2 - Docling ===
docling>=2.0.0
```

### Vérifications préalables

- [x] Docling supporte PPTX nativement → ✅ **OUI** (format Office Open XML officiel)
- [ ] Taille des dépendances Docling (OCR models ?)
- [ ] Compatibilité avec PyMuPDF existant
- [ ] Exposition `visual_elements[]` pour VDS (shapes, connecteurs)
- [ ] Performance sur gros documents (500+ pages)

---

## 📊 Métriques de succès

### Vision Gating v4

| Métrique | Cible |
|----------|-------|
| Faux positifs (Vision inutile) | < 10% |
| Faux négatifs (Diagramme raté) | ~ 0% |
| Temps de gating par page | < 50ms |

### Pipeline global

| Métrique | Cible |
|----------|-------|
| Préservation tables | 100% |
| Préservation hiérarchie | > 95% |
| Hallucinations Vision | 0% |

---

## 📝 Notes de session

### 2026-01-02 (mise à jour)

**Matin:**
- Création des documents de spécification (architecture, VG v4, checklist, classes)
- Identification: Docling non installé, MegaParse actuellement utilisé
- Prompt Vision canonique défini (agnostique + Domain Context injectable)
- Structure de fichiers cible définie

**Après-midi:**
- Revue critique identifiant zones d'ombre (interface OSMOSE, DomainContext, PPTX)
- Arbitrage ChatGPT résolvant tous les problèmes
- Décisions consolidées dans `OSMOSIS_EXTRACTION_V2_DECISIONS.md`

**Soir:**
- ✅ **Clarification PPTX** : Docling supporte officiellement PPTX (Office Open XML)
- Architecture mise à jour → **Docling unifié pour tous formats Office**
- Suppression de l'approche séparée python-pptx
- VDS : Docling `visual_elements[]` en priorité, fallback si nécessaire

### Prochaines actions immédiates

1. ⬜ Ajouter Docling aux requirements (`docling>=2.0.0`)
2. ⬜ Tester Docling sur échantillons PDF/PPTX/DOCX
3. ⬜ Vérifier exposition `visual_elements[]` pour VDS
4. ⬜ Créer la structure de dossiers `src/knowbase/extraction_v2/`
5. ⬜ **Phase 1** : Implémenter les modèles de données (CRITIQUE)

---

## 🔗 Liens utiles

- Docling GitHub: `https://github.com/DS4SD/docling`
- Vision Gating v3.4 (actuel): `src/knowbase/ingestion/components/transformers/vision_gating.py`
- Pipeline actuel: `src/knowbase/ingestion/pipelines/pdf_pipeline.py`

---

*Dernière mise à jour: 2026-01-02 (soir) - Architecture unifiée Docling*
