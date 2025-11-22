# Sprint 1.8.1d : Guide d'Intégration SmartConceptMerger

**Date:** 2025-11-21
**Sprint:** Phase 1.8.1d - Extraction Locale + Fusion Contextuelle
**Status:** 🟢 IMPLÉMENTÉ - En attente intégration pipeline

---

## 🎯 Objectif

Intégrer le SmartConceptMerger dans le pipeline OSMOSE existant pour améliorer l'extraction de concepts des documents PPTX structurés.

**Problème résolu:** TopicSegmenter fusionne trop (87 slides → 5 segments → 28 concepts)
**Solution:** Extraction locale granulaire (par slide) + fusion intelligente basée sur règles

---

## 📦 Modules Implémentés

### Core
- ✅ `src/knowbase/semantic/fusion/smart_concept_merger.py` (280 lignes)
- ✅ `src/knowbase/semantic/fusion/fusion_rules.py` (ABC - 100 lignes)
- ✅ `src/knowbase/semantic/fusion/models.py` (150 lignes)

### Règles MVP
- ✅ `src/knowbase/semantic/fusion/rules/main_entities.py` (300 lignes)
- ✅ `src/knowbase/semantic/fusion/rules/alternatives.py` (280 lignes)
- ✅ `src/knowbase/semantic/fusion/rules/slide_specific.py` (200 lignes)

### Intégration
- ✅ `src/knowbase/semantic/fusion/fusion_integration.py` (320 lignes)

### Configuration
- ✅ `config/fusion_rules.yaml` (configuration complète)

### Modifications Existantes
- ✅ `src/knowbase/semantic/extraction/concept_extractor.py` (ajout mode "local")

---

## 🔌 Intégration dans le Pipeline

### Option 1: Intégration via ExtractorOrchestrator (RECOMMANDÉ)

**Fichier:** `src/knowbase/agents/extractor/orchestrator.py`

**Localisation:** Méthode `extract_concepts()` qui appelle `concept_extractor.extract_concepts()`

**Modification suggérée:**

```python
# AVANT (ligne ~490)
concepts_list = await extractor.extract_concepts(
    topic,
    enable_llm=use_llm,
    document_context=document_context
)

# APRÈS (avec fusion pour PPTX)
from knowbase.semantic.fusion import process_document_with_fusion

# Détecter si document PPTX avec slides_data disponible
if state.document_type == "PPTX" and hasattr(state, "slides_data") and state.slides_data:
    # Pipeline Fusion (Extraction Locale + SmartConceptMerger)
    canonical_concepts = await process_document_with_fusion(
        document_type="PPTX",
        slides_data=state.slides_data,
        document_context=document_context,
        concept_extractor=extractor,
        config=None  # Chargé automatiquement depuis config/fusion_rules.yaml
    )

    # Convertir CanonicalConcepts en format attendu par Gatekeeper
    concepts_list = _convert_canonical_to_dict(canonical_concepts)
else:
    # Pipeline classique (TopicSegmenter + ConceptExtractor)
    concepts_list = await extractor.extract_concepts(
        topic,
        enable_llm=use_llm,
        document_context=document_context
    )
```

**Fonction helper à ajouter:**

```python
def _convert_canonical_to_dict(canonical_concepts: List) -> List[Dict]:
    """
    Convertit CanonicalConcepts en format dict pour Gatekeeper.

    Args:
        canonical_concepts: Liste CanonicalConcept

    Returns:
        List[Dict]: Format compatible Gatekeeper
    """
    concepts_dict = []
    for canonical in canonical_concepts:
        concept_dict = {
            "name": canonical.name,
            "type": canonical.concept_type.value,
            "definition": canonical.definition,
            "confidence": canonical.confidence,
            "language": canonical.language,
            "metadata": canonical.metadata or {},
            "aliases": canonical.aliases,
            "extraction_method": canonical.metadata.get("fusion_rule", "FUSION")
        }
        concepts_dict.append(concept_dict)

    return concepts_dict
```

---

### Option 2: Intégration via OsmoseAgentique (Alternative)

**Fichier:** `src/knowbase/ingestion/osmose_agentique.py`

**Localisation:** Méthode `process_document_agentique()` avant appel Supervisor

**Modification suggérée:**

```python
# AVANT appel Supervisor (ligne ~420)
supervisor = SupervisorAgent(...)

# INSÉRER détection PPTX et préparation slides_data
if document_path.suffix.lower() == ".pptx":
    # Extraire slides_data depuis document
    slides_data = await self._extract_slides_data(document_path)

    # Ajouter aux initial_data pour ExtractorOrchestrator
    initial_data = AgentState(
        document_id=document_id,
        document_title=document_title,
        document_type="PPTX",
        slides_data=slides_data,  # NOUVEAU
        ...
    )
else:
    initial_data = AgentState(...)

# Appel Supervisor (inchangé)
result = await supervisor.execute(initial_data)
```

**Fonction helper à ajouter:**

```python
async def _extract_slides_data(self, document_path: Path) -> List[Dict[str, Any]]:
    """
    Extrait données slides depuis fichier PPTX.

    Args:
        document_path: Chemin vers fichier .pptx

    Returns:
        List[Dict]: Données slides (text, notes, index)
    """
    # Utiliser extraction Vision existante (GPT-4)
    from knowbase.ingestion.components.extractors.vision_extractor import extract_slides_via_vision

    slides_data = await extract_slides_via_vision(document_path)
    return slides_data
```

---

## ⚙️ Configuration

### Activation/Désactivation

**Fichier:** `config/fusion_rules.yaml`

```yaml
fusion:
  enabled: true  # false pour désactiver fusion

  local_extraction_types:
    - PPTX          # Types de documents éligibles
    - PPTX_SLIDES
```

### Ajustement Seuils

**Règle 1 - Main Entities:**
```yaml
- name: main_entities_merge
  config:
    min_occurrence_ratio: 0.15  # 15% des slides minimum
    similarity_threshold: 0.88   # Cosine similarity ≥ 0.88
```

**Règle 2 - Alternatives:**
```yaml
- name: alternatives_features
  config:
    min_co_occurrence: 3  # Présents ensemble sur ≥3 slides
```

**Règle 3 - Slide Specific:**
```yaml
- name: slide_specific_preserve
  config:
    max_occurrence: 2      # Mentionnés ≤ 2 fois → préservés
    min_name_length: 10    # Noms longs = détails précis
```

---

## 🧪 Tests

### Test Unitaire Fusion

```python
# tests/semantic/fusion/test_integration.py
import pytest
from knowbase.semantic.fusion import process_document_with_fusion

@pytest.mark.asyncio
async def test_pptx_fusion_integration():
    """Test fusion PPTX avec 10 slides"""
    slides_data = [
        {"index": i, "text": f"SAP S/4HANA slide {i}", "notes": ""}
        for i in range(10)
    ]

    canonical_concepts = await process_document_with_fusion(
        document_type="PPTX",
        slides_data=slides_data,
        document_context="Document about SAP S/4HANA",
        concept_extractor=mock_extractor
    )

    # Vérifier fusion
    assert len(canonical_concepts) > 0
    assert any("SAP S/4HANA" in c.name for c in canonical_concepts)
```

### Test End-to-End

```bash
# Tester sur document PPTX réel
docker-compose exec app python -c "
from pathlib import Path
from knowbase.ingestion.osmose_agentique import OsmoseIntegration

# Import document test
doc_path = Path('data/docs_in/test_87_slides.pptx')
integration = OsmoseIntegration()

result = await integration.process_document_agentique(
    document_id='test_fusion',
    document_title='Test 87 slides',
    document_path=doc_path,
    text_content='...'
)

print(f'Concepts extracted: {result.canonical_concepts_count}')
# Attendu: ~300-400 concepts (vs 28 avant)
"
```

---

## 📊 Métriques de Succès

| Métrique | Baseline (Avant) | Target (Après Sprint 1.8.1d) | Validation |
|----------|------------------|------------------------------|------------|
| **Concepts extraits (87 slides PPTX)** | 28 | 200-400 | `result.canonical_concepts_count` |
| **Granularité** | Trop générique | Fine (slide-level) | Vérifier `metadata.source_slides` |
| **Détection alternatives** | 0% | ≥ 80% paires | Compter relations `alternative_to` |
| **Préservation détails techniques** | Fusionnés/perdus | 100% préservés | Vérifier `metadata.frequency = "rare"` |
| **Latence extraction** | 7.5 min | ≤ 15 min (2× acceptable) | `result.extraction_duration` |

---

## 🚨 Troubleshooting

### Problème 1: Fusion désactivée automatiquement

**Symptôme:** Logs `[OSMOSE:Fusion] Fusion disabled, using standard pipeline`

**Cause:** `config/fusion_rules.yaml` → `fusion.enabled: false`

**Solution:**
```yaml
fusion:
  enabled: true
```

### Problème 2: Aucun concept fusionné

**Symptôme:** Logs `[OSMOSE:Fusion] No repeated concepts found`

**Cause:** Seuil `min_occurrence_ratio` trop élevé

**Solution:**
```yaml
- name: main_entities_merge
  config:
    min_occurrence_ratio: 0.10  # Réduire de 0.15 à 0.10
```

### Problème 3: Trop de concepts fusionnés

**Symptôme:** Détails slide-specific perdus

**Cause:** Règle 3 (slide_specific_preserve) désactivée ou mal configurée

**Solution:**
```yaml
- name: slide_specific_preserve
  enabled: true
  config:
    max_occurrence: 2      # Augmenter à 3 si besoin
    min_name_length: 8     # Réduire à 8 si détails courts
```

### Problème 4: Import errors

**Symptôme:** `ModuleNotFoundError: No module named 'knowbase.semantic.fusion'`

**Cause:** Container app non redémarré après ajout modules

**Solution:**
```bash
./kw.ps1 restart app
```

---

## 📝 Checklist Intégration

- [ ] **Code intégration ExtractorOrchestrator**
  - [ ] Ajouter import `process_document_with_fusion`
  - [ ] Détecter type document PPTX
  - [ ] Appeler fusion si éligible
  - [ ] Convertir CanonicalConcepts en format Gatekeeper

- [ ] **Préparation slides_data**
  - [ ] Extraire slides_data depuis document PPTX
  - [ ] Ajouter au state AgentState
  - [ ] Passer à ExtractorOrchestrator

- [ ] **Tests**
  - [ ] Tests unitaires fusion rules
  - [ ] Tests intégration process_document_with_fusion
  - [ ] Test end-to-end sur document PPTX réel

- [ ] **Configuration**
  - [ ] Vérifier `config/fusion_rules.yaml` présent
  - [ ] Ajuster seuils si nécessaire
  - [ ] Activer `fusion.enabled: true`

- [ ] **Validation**
  - [ ] Import document 87 slides
  - [ ] Vérifier concepts_count ≥ 200
  - [ ] Vérifier metadata.source_slides préservées
  - [ ] Vérifier latence ≤ 15 min

---

## 🔄 Rollback Plan

Si problème critique détecté en production :

1. **Désactivation rapide:**
   ```yaml
   # config/fusion_rules.yaml
   fusion:
     enabled: false
   ```

2. **Redémarrage service:**
   ```bash
   ./kw.ps1 restart app
   ```

3. **Vérification:**
   - Pipeline revient à TopicSegmenter classique
   - Pas de changement comportement extraction PDF/TXT

---

## 📚 Documentation Référence

- **Architecture Design:** `doc/ongoing/SPRINT_1_8_1d_ARCHITECTURE_DESIGN.md`
- **Tracking Sprint:** `doc/ongoing/PHASE1_8_TRACKING.md` (Sprint 1.8.1d)
- **Code Source:** `src/knowbase/semantic/fusion/`

---

**Status:** ✅ PRÊT POUR INTÉGRATION
**Prochaine étape:** T1.8.1d.6 - Tests End-to-End + Validation
