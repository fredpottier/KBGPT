# Revue Critique - Architecture Extraction V2

**Date:** 2026-01-02
**Objectif:** Identifier les zones d'ombre, incohérences et risques avant implémentation

---

## 🔴 PROBLÈMES CRITIQUES

### 1. Interface de sortie non définie vers OSMOSE

**Le problème:**
L'architecture V2 définit une sortie `DocumentOutput` avec `pages_or_slides[]`, mais OSMOSE actuel attend un **`full_text: str`** comme entrée.

```python
# OSMOSE actuel (osmose_agentique.py:633)
async def process_document_agentique(
    self,
    full_text: str,  # ← Entrée attendue: STRING
    document_id: str,
    ...
)
```

```python
# V2 proposée
@dataclass
class DocumentOutput:
    pages_or_slides: List[PageOrSlideOutput]  # ← Sortie: STRUCTURED
```

**Impact:**
- Comment transformer `DocumentOutput` → `full_text` sans perdre la structure préservée ?
- La segmentation par topics (`TopicSegmenter`) attend du texte linéaire
- Le chunking actuel ne connaît pas la notion de "page/slide"

**Questions non résolues:**
1. Faut-il adapter OSMOSE pour consommer des structures ?
2. Ou faut-il "linéariser" intelligemment la sortie V2 ?
3. Comment préserver les bounding boxes pour le cross-référencement ?

---

### 2. Double système DomainContext

**Le problème:**
Il existe DÉJÀ un système `DomainContextInjector` (`knowbase/ontology/domain_context_injector.py`) avec un `DomainContextStore`.

La spec V2 propose un NOUVEAU `DomainContext` dataclass dans le schéma de classes.

**Comparaison:**

| Aspect | Système existant | V2 proposé |
|--------|------------------|------------|
| Stockage | `DomainContextStore` (YAML) | `DomainContext` dataclass |
| Injection | `inject_context(base_prompt, tenant_id)` | Injection directe dans prompt Vision |
| Scope | Tous les prompts LLM (canonicalisation, extraction...) | Vision uniquement ? |
| Tenant | Multi-tenant supporté | Pas de notion tenant |

**Risques:**
- Duplication de code
- Incohérence entre contextes Vision et contextes OSMOSE
- Deux sources de vérité pour le vocabulaire métier

**Recommandation:**
→ Réutiliser `DomainContextStore` existant et adapter `DomainContextInjector` pour Vision

---

### 3. Sortie Vision incompatible avec le pipeline sémantique

**Le problème:**
La sortie Vision (`VisionExtraction`) contient des éléments structurés :

```json
{
  "elements": [{"id": "box_1", "type": "box", "text": "SAP S/4HANA"}],
  "relations": [{"source_id": "box_1", "target_id": "box_2", "type": "flows_to"}]
}
```

Mais le pipeline sémantique OSMOSE attend du **texte** pour :
1. Segmentation par topics
2. Extraction de concepts (ProtoConcept)
3. Détection de relations (via patterns ou LLM)

**Questions:**
- Les `relations` Vision doivent-elles alimenter directement le KG ?
- Ou doivent-elles être "textualisées" pour passer par OSMOSE ?
- Comment éviter les doublons (relation Vision vs relation OSMOSE) ?

---

## 🟠 ZONES D'OMBRE TECHNIQUES

### 4. Docling : support PPTX non vérifié

**Le problème:**
L'architecture suppose que Docling peut extraire des PPTX, mais :
- La doc Docling mentionne principalement PDF, DOCX, HTML
- Le support PPTX n'est pas explicitement confirmé
- Si Docling ne supporte pas PPTX, il faudra une conversion préalable (PPTX → PDF → Docling)

**Vérification nécessaire:**
```python
# À tester avant implémentation
from docling.document_converter import DocumentConverter
converter = DocumentConverter()
result = converter.convert("test.pptx")  # Supporte-t-il ?
```

**Impact si non supporté:**
- Pipeline différent pour PPTX (garder python-pptx actuel ?)
- Conversion PPTX → PDF (LibreOffice) avec perte potentielle de metadata

---

### 5. VDS (Vector Drawing Signal) : détection connecteurs

**Le problème:**
Le signal VDS doit détecter les "connecteurs" (flèches, lignes) pour identifier les diagrammes en shapes.

**Pour PDF:** `fitz.Page.get_drawings()` existe et retourne les paths vectoriels.

**Pour PPTX via Docling:**
- Comment Docling expose-t-il les shapes PPTX ?
- Les connecteurs PPTX (`MSO_CONNECTOR`) sont-ils distingués des shapes normaux ?
- Si Docling "aplatit" la structure PPTX, on perd cette info cruciale.

**Risque:**
Le signal VDS pourrait ne pas fonctionner du tout pour PPTX si Docling ne préserve pas la distinction shape vs connector.

---

### 6. SDS (Spatial Dispersion Signal) : seuils empiriques

**Le problème:**
Les seuils sont définis empiriquement :

```python
HIGH_THRESHOLD = 0.08
MEDIUM_THRESHOLD = 0.04
```

Ces valeurs sont arbitraires et non validées sur un corpus réel.

**Questions:**
- Ces seuils sont-ils corrects pour des documents SAP techniques ?
- Faut-il un calibrage par type de document ?
- La variance normalisée est-elle la bonne métrique ?

---

### 7. VTS (Visual Table Signal) : détection de grilles

**Le problème:**
Le code proposé détecte les tables visuelles via :

```python
if len(horizontal_lines) >= 3 and len(vertical_lines) >= 2:
    return 1.0
```

Mais :
- Comment distinguer une table dessinée d'un encadré simple ?
- Docling détecte déjà des `tables[]` structurées - comment gérer le chevauchement ?
- Les "pseudo-tables" (alignements texte) nécessitent une heuristique plus fine

---

### 8. Structured Merge : règles non définies

**Le problème:**
Le document dit :
> "Docling = socle, Vision = enrichissement attaché"

Mais il n'y a **aucune spécification** de :
- Comment attacher les éléments Vision aux blocs Docling ?
- Par bounding box overlap ? Par page/slide index ?
- Que faire si Vision détecte des éléments absents de Docling ?
- Comment stocker la provenance (Docling vs Vision) ?

---

## 🟡 INCOHÉRENCES AVEC LE SYSTÈME EXISTANT

### 9. Cache d'extraction (`extraction_cache.py`)

**Le problème:**
Le système actuel utilise un cache `.knowcache.json` avec le format :

```json
{
  "source_file_hash": "abc123",
  "extracted_text": { "full_text": "..." },
  "document_metadata": { ... }
}
```

La V2 produit une structure complètement différente (`DocumentOutput`).

**Questions:**
- Nouveau format de cache ?
- Migration des caches existants ?
- Invalidation si le pipeline V2 est activé ?

---

### 10. Hiérarchie documentaire pour OSMOSE

**Le problème:**
OSMOSE utilise la hiérarchie (titres, sections) pour :
- La segmentation par topics (`TopicSegmenter`)
- La contextualisation des concepts
- La structure des DocumentChunks

La V2 préserve la hiérarchie via Docling, mais :
- Comment la transmettre à OSMOSE ?
- Le `TopicSegmenter` actuel attend du texte brut, pas une structure hiérarchique
- Faut-il adapter le segmenter ?

---

### 11. Tables multi-pages

**Le problème:**
Docling peut gérer des tables multi-pages, mais :
- Le Vision Gating décide par PAGE/SLIDE
- Une table sur 3 pages aurait 3 décisions différentes ?
- Comment fusionner les extractions Vision d'une même table ?

---

### 12. VISION_RECOMMENDED : comportement non défini

**Le problème:**
Le gating peut retourner `VISION_RECOMMENDED`, mais :

```python
if gating.decision == "VISION_RECOMMENDED":
    run_vision_if_budget_allows()  # ???
```

- Qu'est-ce que "budget allows" ?
- Qui gère le budget ?
- Fallback si budget épuisé ?

---

## 🔵 SUGGESTIONS D'AMÉLIORATION

### A. Définir une interface claire Extraction V2 → OSMOSE

```python
@dataclass
class ExtractionResult:
    """Interface de sortie vers OSMOSE."""

    # Pour compatibilité OSMOSE actuel
    full_text: str  # Texte linéarisé avec marqueurs structure

    # Métadonnées enrichies
    hierarchy: List[HeadingInfo]  # Titres avec niveaux
    tables: List[TableData]  # Tables structurées

    # Résultats Vision (optionnels)
    visual_extractions: List[VisionExtraction]  # Par page/slide ayant eu Vision

    # Provenance
    gating_decisions: List[GatingDecision]  # Pour audit
```

### B. Unifier DomainContext

Étendre `DomainContextStore` existant avec les champs V2 :
- `interpretation_rules`
- `extraction_focus`

Et créer un adaptateur :
```python
def get_vision_domain_context(tenant_id: str) -> DomainContext:
    """Convertit DomainContextProfile → DomainContext pour Vision."""
    profile = get_domain_context_store().get_profile(tenant_id)
    return DomainContext(
        name=profile.industry,
        interpretation_rules=profile.interpretation_rules,
        domain_vocabulary=profile.common_acronyms,
        ...
    )
```

### C. Valider Docling avant implémentation

**Tâche 0 obligatoire:**
1. Installer Docling dans un environnement de test
2. Tester sur 3 PDF et 3 PPTX de notre corpus
3. Vérifier les champs retournés (`blocks`, `tables`, `drawings`)
4. Documenter les limitations

### D. Calibrer les seuils sur corpus réel

Avant de fixer les seuils VG v4 :
1. Annoter manuellement 50 pages (25 avec diagrammes, 25 sans)
2. Calculer les signaux pour chaque page
3. Optimiser les seuils pour minimiser faux positifs/négatifs

### E. Définir le format de merge

Proposer un schema JSON pour la sortie merge :

```json
{
  "page_index": 6,
  "docling_blocks": [...],
  "vision_enrichment": {
    "attached_to_block": "block_3",
    "elements": [...],
    "relations": [...]
  },
  "provenance": {
    "docling_version": "2.0.1",
    "vision_model": "gpt-4o",
    "gating_score": 0.78
  }
}
```

---

## 📋 CHECKLIST PRÉ-IMPLÉMENTATION

Avant de commencer Phase 1, résoudre :

- [ ] **Valider Docling** : support PPTX, format sortie exacte
- [ ] **Définir interface → OSMOSE** : comment OSMOSE consommera la sortie V2
- [ ] **Unifier DomainContext** : réutiliser l'existant ou migrer
- [ ] **Définir comportement VISION_RECOMMENDED** : budget, fallback
- [ ] **Spécifier Structured Merge** : règles d'attachement, format sortie
- [ ] **Tester VDS sur PPTX** : Docling expose-t-il les connecteurs ?
- [ ] **Clarifier cache** : nouveau format, migration

---

## 🎯 CONCLUSION

L'architecture V2 est **conceptuellement solide** mais présente des **lacunes d'intégration** avec le système OSMOSE existant :

1. **Critique** : L'interface de sortie vers OSMOSE n'est pas définie
2. **Critique** : Double système DomainContext → risque d'incohérence
3. **Important** : Docling non validé sur notre stack (PPTX ?)
4. **Important** : Règles de merge non spécifiées

**Recommandation :** Avant l'implémentation, produire un **document d'intégration** qui spécifie exactement :
- Le format de sortie V2 compatible OSMOSE
- La stratégie de gestion DomainContext
- Le plan de migration du cache
- Les tests de validation Docling

Cela évitera une refonte en cours de route.
