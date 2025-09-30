# Analyse Pipeline PPTX - Opportunités d'Optimisation LLM → KG

**Date**: 30 septembre 2025
**Contexte**: Analyse des appels LLM durant l'import PPTX pour identifier les opportunités de réutilisation pour alimenter le Knowledge Graph Graphiti

---

## 📊 Architecture Actuelle du Pipeline PPTX

### Flux Global (`pptx_pipeline.py`)

```
1. Upload PPTX
   ↓
2. Suppression slides cachés (remove_hidden_slides_inplace)
   ↓
3. Conversion PPTX → PDF (LibreOffice)
   ↓
4. Extraction contenu texte (MegaParse ou python-pptx)
   ↓
5. 🤖 APPEL LLM #1: Analyse deck global (analyze_deck_summary)
   ↓
6. Conversion PDF → Images PNG (PyMuPDF)
   ↓
7. Pour chaque slide:
      7a. 🤖 APPEL LLM #2: Analyse slide + image (ask_gpt_slide_analysis)
      7b. Chunking avec overlap (recursive_chunk)
      7c. Embedding SentenceTransformer
      7d. Ingestion Qdrant (ingest_chunks)
   ↓
8. Déplacement vers docs_done
```

---

## 🤖 Appels LLM Identifiés

### APPEL LLM #1: Analyse Deck Global
**Fonction**: `analyze_deck_summary()` (ligne 832)
**Modèle**: LLMRouter avec `TaskType.METADATA_EXTRACTION`
**Input**:
- Résumé agrégé de tous les slides (limité à MAX_TOKENS_THRESHOLD)
- Texte des notes si disponibles
- Nom du fichier source

**Output JSON**:
```json
{
  "summary": "Résumé narratif complet du deck",
  "metadata": {
    "title": "Titre du document",
    "objective": "Objectif du document",
    "audience": ["Type audience 1", "Type audience 2"],
    "source_date": "2025-01-15",
    "main_solution": "SAP S/4HANA Cloud",
    "main_solution_id": "s4hana_cloud",
    "family": "ERP",
    "supporting_solutions": ["SAP Fiori", "SAP HANA"],
    "mentioned_solutions": ["SAP BTP", "SAP Analytics Cloud"],
    "version": "2024 FPS01",
    "deployment_model": "Public Cloud",
    "document_type": "technical_presentation"
  },
  "_prompt_meta": {
    "document_type": "default",
    "deck_prompt_id": "deck_analysis_v2",
    "prompts_version": "2.5.0"
  }
}
```

**Coût estimé**: ~$0.002-0.005 par deck (selon taille)
**Temps**: 1-3 secondes

---

### APPEL LLM #2: Analyse Slide Individuelle
**Fonction**: `ask_gpt_slide_analysis()` (ligne 913)
**Modèle**: LLMRouter avec `TaskType.VISION`
**Input**:
- Image PNG du slide (base64)
- Résumé du deck (contexte)
- Texte extrait du slide
- Notes du présentateur
- Contenu MegaParse structuré
- Index du slide

**Output JSON** (array de concepts):
```json
[
  {
    "full_explanation": "Explication détaillée du concept 1 avec contexte business...",
    "meta": {
      "scope": "solution-specific",
      "type": "feature_description",
      "level": "technical",
      "tags": ["integration", "API", "real-time"],
      "slide_role": "content",
      "mentioned_solutions": ["SAP BTP", "SAP Integration Suite"]
    },
    "prompt_meta": {
      "document_type": "default",
      "slide_prompt_id": "slide_vision_v3",
      "prompts_version": "2.5.0"
    }
  },
  {
    "full_explanation": "Explication détaillée du concept 2...",
    "meta": { /* ... */ }
  }
]
```

**Coût estimé**: ~$0.01-0.03 par slide (vision + texte)
**Temps**: 2-5 secondes par slide
**Volume**: 1 appel × nombre de slides (peut être 50-500 slides)

---

## 💡 Opportunités d'Optimisation Identifiées

### Option 1: Enrichissement Direct Pendant l'Analyse Slide ✅ **RECOMMANDÉ**

**Principe**: Modifier le prompt de `ask_gpt_slide_analysis()` pour extraire aussi des **entités structurées** et **relations** en plus des chunks textuels.

**Avantages**:
- ✅ **Zéro appel LLM supplémentaire** - réutilise l'appel vision existant
- ✅ **Contexte riche** - le LLM a déjà l'image + texte + contexte deck
- ✅ **Latence nulle** - extraction parallèle aux chunks
- ✅ **Cohérence parfaite** - entités alignées avec les chunks ingérés

**Modifications nécessaires**:

#### 1. Extension du prompt slide (`config/prompts.yaml`)
```yaml
slide:
  default:
    system: "You analyze slides to extract concepts AND structured knowledge graph entities."
    template: |
      Deck summary: {{ deck_summary }}
      Slide {{ slide_index }}: {{ source_name }}

      Text: {{ text }}
      Notes: {{ notes }}
      MegaParse: {{ megaparse_content }}

      Extract:
      1. Concepts as before (full_explanation + meta)
      2. NEW: Entities (name, type, attributes)
      3. NEW: Relations (source, target, type, description)

      Return JSON:
      {
        "concepts": [ /* existing format */ ],
        "entities": [
          {
            "name": "SAP S/4HANA Cloud",
            "entity_type": "PRODUCT",
            "description": "Cloud ERP solution...",
            "attributes": {
              "version": "2024 FPS01",
              "deployment": "Public Cloud",
              "vendor": "SAP"
            }
          }
        ],
        "relations": [
          {
            "source": "SAP S/4HANA Cloud",
            "target": "SAP Fiori",
            "relation_type": "USES_TECHNOLOGY",
            "description": "Modern UX layer for S/4HANA"
          }
        ]
      }
```

#### 2. Modification de `ask_gpt_slide_analysis()` (ligne 913)
```python
def ask_gpt_slide_analysis(
    image_path,
    deck_summary,
    slide_index,
    source_name,
    text,
    notes,
    megaparse_content="",
    document_type="default",
    deck_prompt_id="unknown",
    retries=2,
):
    # ... existing code ...

    try:
        raw_content = llm_router.complete(TaskType.VISION, msg)
        cleaned_content = clean_gpt_response(raw_content or "")
        result = json.loads(cleaned_content)

        # Extraction existante des concepts
        concepts = result.get("concepts", [])
        enriched = []
        for it in concepts:
            # ... existing chunking logic ...

        # 🆕 NOUVEAU: Extraction entités et relations
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        return {
            "chunks": enriched,  # Pour Qdrant (existant)
            "entities": entities,  # Pour Graphiti (nouveau)
            "relations": relations  # Pour Graphiti (nouveau)
        }
    except Exception as e:
        logger.warning(f"Slide {slide_index} attempt {attempt} failed: {e}")
        time.sleep(2 * (attempt + 1))

    return {"chunks": [], "entities": [], "relations": []}
```

#### 3. Ajout de l'ingestion Knowledge Graph dans `process_pptx()` (ligne 1062)
```python
def process_pptx(pptx_path: Path, document_type: str = "default", progress_callback=None, rq_job=None):
    # ... existing code jusqu'à la boucle de traitement des slides ...

    # 🆕 NOUVEAU: Initialiser le service KG
    from knowbase.api.services.knowledge_graph import get_knowledge_graph_service
    kg_service = get_knowledge_graph_service()

    # Contexte utilisateur (pour group_id)
    user_context = {"user_id": "system", "group_id": "corporate"}  # À adapter selon le contexte

    all_kg_entities = []  # Accumuler les entités du deck
    all_kg_relations = []  # Accumuler les relations du deck

    for i, (idx, future) in enumerate(tasks):
        # ... existing progress tracking ...

        result = future.result()
        chunks = result.get("chunks", [])
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # Ingestion existante dans Qdrant
        ingest_chunks(chunks, metadata, pptx_path.stem, idx, summary)

        # 🆕 NOUVEAU: Ingestion dans Knowledge Graph
        if entities:
            all_kg_entities.extend(entities)
            logger.info(f"Slide {idx}: {len(entities)} entités extraites pour KG")

        if relations:
            all_kg_relations.extend(relations)
            logger.info(f"Slide {idx}: {len(relations)} relations extraites pour KG")

    # 🆕 NOUVEAU: Ingestion batch dans Graphiti après traitement de toutes les slides
    if all_kg_entities:
        logger.info(f"🔄 Ingestion de {len(all_kg_entities)} entités dans Graphiti...")
        for entity_data in all_kg_entities:
            try:
                entity_create = EntityCreate(
                    name=entity_data["name"],
                    entity_type=EntityType[entity_data["entity_type"]],
                    description=entity_data.get("description", ""),
                    attributes=entity_data.get("attributes", {})
                )
                created_entity = await kg_service.create_entity(entity_create, user_context)
                logger.debug(f"✅ Entité créée: {created_entity.name}")
            except Exception as e:
                logger.error(f"❌ Erreur création entité {entity_data['name']}: {e}")

    if all_kg_relations:
        logger.info(f"🔄 Ingestion de {len(all_kg_relations)} relations dans Graphiti...")
        # TODO: Implémenter création relations via KG service

    # ... existing finalization code ...
```

---

### Option 2: Appel LLM Additionnel Post-Analyse ⚠️ **NON RECOMMANDÉ**

**Principe**: Après ingestion Qdrant, faire un appel LLM séparé pour extraire entités.

**Inconvénients**:
- ❌ **Coût doublé** - appel LLM vision supplémentaire par slide
- ❌ **Latence augmentée** - +2-5s par slide
- ❌ **Risque incohérence** - entités peuvent diverger des chunks
- ❌ **Complexité** - gestion de deux workflows parallèles

**Verdict**: Ne pas implémenter cette option.

---

### Option 3: Extraction Post-Ingestion depuis Qdrant ⚠️ **PARTIEL**

**Principe**: Utiliser les chunks déjà dans Qdrant pour extraire entités a posteriori.

**Avantages**:
- ✅ Pas de modification du pipeline existant
- ✅ Peut être fait progressivement

**Inconvénients**:
- ⚠️ **Perte de contexte** - plus d'accès à l'image, seulement texte des chunks
- ⚠️ **Qualité inférieure** - entités moins précises sans contexte visuel
- ⚠️ **Appels LLM supplémentaires** - coût additionnel sans vision

**Usage recommandé**: Uniquement pour migration historique des données existantes, pas pour nouveaux imports.

---

## 📋 Données LLM Réutilisables pour Graphiti

### Depuis `analyze_deck_summary()` (Deck global)

| Donnée LLM | Utilisation Graphiti | Type Entité |
|------------|----------------------|-------------|
| `metadata.main_solution` | Entité principale PRODUCT | `EntityType.PRODUCT` |
| `metadata.supporting_solutions[]` | Entités PRODUCT + relations SUPPORTS | `EntityType.PRODUCT` |
| `metadata.mentioned_solutions[]` | Entités PRODUCT + relations MENTIONS | `EntityType.PRODUCT` |
| `metadata.title` | Attribut document | Métadonnée |
| `metadata.objective` | Attribut document | Métadonnée |
| `metadata.audience[]` | Entités PERSONA | `EntityType.CONCEPT` |
| `metadata.version` | Attribut version produit | Attribut |
| `metadata.deployment_model` | Attribut deployment | Attribut |
| `summary` | Description document | Contexte global |

**Exemple d'entité créée**:
```python
EntityCreate(
    name="SAP S/4HANA Cloud",
    entity_type=EntityType.PRODUCT,
    description=deck_summary,  # Contexte riche du deck
    attributes={
        "version": "2024 FPS01",
        "deployment_model": "Public Cloud",
        "family": "ERP",
        "document_source": "presentation_xyz.pptx",
        "source_date": "2025-01-15"
    }
)
```

---

### Depuis `ask_gpt_slide_analysis()` (Par slide)

| Donnée LLM | Utilisation Graphiti | Type Entité |
|------------|----------------------|-------------|
| `full_explanation` | Description détaillée | Attribut/Description |
| `meta.mentioned_solutions[]` | Relations PRODUCT | Relation |
| `meta.tags[]` | Tags/catégories | Attribut |
| `meta.type` | Type de contenu | Attribut |
| `meta.level` | Niveau technique | Attribut |
| `meta.scope` | Scope (solution-specific, general) | Attribut |

**Nouvelles extractions à ajouter** (modification prompt):
- **Entités nommées**: Features, Modules, Technologies, Personas
- **Relations**: USES, REQUIRES, REPLACES, INTEGRATES_WITH
- **Événements temporels**: Releases, Migrations, Deadlines

---

## 🎯 Recommandation Finale

### ✅ Implémenter Option 1: Enrichissement Direct

**Justification**:
1. **Coût LLM nul** - réutilise appels existants
2. **Qualité maximale** - contexte vision + texte complet
3. **Latence nulle** - extraction parallèle
4. **Cohérence garantie** - entités alignées avec chunks Qdrant

**Implémentation suggérée**:

#### Phase 1: Extension minimale (2-3 heures)
1. ✅ Modifier prompt slide pour ajouter section "entities" et "relations"
2. ✅ Modifier retour de `ask_gpt_slide_analysis()` pour inclure entités
3. ✅ Ajouter ingestion KG dans `process_pptx()` après boucle slides
4. ✅ Tests avec 1 PPTX simple (5-10 slides)

#### Phase 2: Optimisations (1-2 jours)
1. ⏳ Dédoublonnage entités (même entité sur plusieurs slides)
2. ⏳ Fusion intelligente des attributs
3. ⏳ Création des relations entre entités
4. ⏳ Linking entités ↔ chunks Qdrant (via UUIDs)

#### Phase 3: Production (optionnel)
1. ⏳ Gestion erreurs robuste (entité existe déjà, etc.)
2. ⏳ Statistiques KG dans réponse ingestion
3. ⏳ UI pour visualiser entités extraites d'un document
4. ⏳ Tests charge (deck 100+ slides)

---

## 📊 Estimation Coûts/Bénéfices

### Coûts Additionnels
- **Coût LLM**: 0€ (réutilise appels existants)
- **Latence**: +0s (extraction parallèle)
- **Stockage Neo4j**: ~50-200 entités par deck (négligeable)
- **Développement**: 2-3 jours (estimation)

### Bénéfices
- ✅ **Knowledge Graph automatiquement enrichi** lors de chaque import
- ✅ **Qualité supérieure** vs migration a posteriori (contexte visuel préservé)
- ✅ **Zéro impact performance** sur pipeline existant
- ✅ **Workflow unifié** - 1 seul job pour Qdrant + Graphiti
- ✅ **Cohérence parfaite** entre chunks vectoriels et entités graph

---

## 🔄 Comparaison avec Stratégie de Migration

| Aspect | Import Direct (Option 1) | Migration Post-Ingestion |
|--------|---------------------------|--------------------------|
| **Coût LLM** | $0 (réutilise existant) | ~$14 pour 1000 docs |
| **Temps** | +0s par document | 8-16h pour 1000 docs |
| **Qualité** | ⭐⭐⭐⭐⭐ (vision + texte) | ⭐⭐⭐ (texte seulement) |
| **Latence ingestion** | Identique | N/A |
| **Cohérence données** | Parfaite | Risque divergence |
| **Complexité implémentation** | Moyenne | Faible |
| **Maintenance** | Simple (1 workflow) | Double (2 workflows) |

**Verdict**: L'import direct (Option 1) est **largement supérieur** pour les nouveaux documents.

---

## 📝 Exemple Concret

### Document: "SAP S/4HANA Cloud - Technical Overview.pptx" (50 slides)

#### Données LLM Actuelles (Déjà Extraites)
```json
{
  "deck_analysis": {
    "summary": "Présentation technique complète de SAP S/4HANA Cloud...",
    "metadata": {
      "main_solution": "SAP S/4HANA Cloud",
      "supporting_solutions": ["SAP Fiori", "SAP HANA", "SAP BTP"],
      "mentioned_solutions": ["SAP Analytics Cloud", "SAP Integration Suite"]
    }
  },
  "slide_5_analysis": {
    "concepts": [
      {
        "full_explanation": "SAP S/4HANA Cloud utilise une architecture 3-tier...",
        "meta": {
          "tags": ["architecture", "cloud", "scalability"],
          "mentioned_solutions": ["SAP HANA", "SAP BTP"]
        }
      }
    ]
  }
}
```

#### Entités Graphiti Créées (Après Modification)
```python
# Depuis analyze_deck_summary()
Entity(
    uuid="uuid-s4hana-cloud",
    name="SAP S/4HANA Cloud",
    entity_type=EntityType.PRODUCT,
    description="Cloud ERP solution with real-time analytics",
    attributes={"family": "ERP", "deployment": "Public Cloud"}
)

# Depuis slide 5 analysis
Entity(
    uuid="uuid-fiori",
    name="SAP Fiori",
    entity_type=EntityType.PRODUCT,
    description="Modern user experience layer",
    attributes={"type": "UX Framework"}
)

Relation(
    source_uuid="uuid-s4hana-cloud",
    target_uuid="uuid-fiori",
    relation_type="USES_TECHNOLOGY",
    description="S/4HANA Cloud uses Fiori for modern UX"
)
```

---

## ✅ Action Items

### Priorité Haute (Implémenter maintenant)
- [ ] Modifier prompt slide dans `config/prompts.yaml` pour ajouter extraction entités/relations
- [ ] Adapter `ask_gpt_slide_analysis()` pour parser nouvelles sections
- [ ] Intégrer ingestion KG dans `process_pptx()`
- [ ] Tester avec 1 PPTX simple

### Priorité Moyenne (Après validation)
- [ ] Dédoublonnage entités au niveau deck
- [ ] Création relations entre entités
- [ ] Linking entités ↔ chunks Qdrant
- [ ] Tests avec gros deck (100+ slides)

### Priorité Basse (Nice to have)
- [ ] UI visualisation entités extraites
- [ ] Statistiques KG dans réponse API
- [ ] Export graph knowledge d'un document
- [ ] Tests E2E complets

---

**Conclusion**: La modification du pipeline PPTX pour enrichir directement le Knowledge Graph est **hautement recommandée** car elle offre zéro coût LLM additionnel, qualité maximale grâce au contexte vision, et cohérence parfaite avec les données vectorielles Qdrant.