# Stratégie Unifiée d'Extraction LLM - Chunks + Entities + Facts

**Date**: 30 septembre 2025 (mise à jour avec Facts)
**Décision**: Mutualiser les appels LLM pour extraire simultanément chunks Qdrant, entités/relations KG, ET facts structurés
**Statut**: ✅ **VALIDÉ** - Approche optimale confirmée

---

## 🎯 DÉCISION ARCHITECTURALE

### Principe directeur

**Un seul appel LLM Vision par slide** extrait :
1. **Chunks textuels** (condensation sémantique pour Qdrant)
2. **Entités structurées** (concepts du domaine métier pour Knowledge Graph)
3. **Relations** (liens sémantiques entre entités pour Knowledge Graph)
4. **Facts structurés** (assertions quantifiables pour gouvernance)

### Justification

✅ **Économie coûts**: 0€ additionnel (réutilise appels existants)
✅ **Économie temps**: 0s latence additionnelle (extraction parallèle)
✅ **Qualité maximale**: Contexte complet préservé (image + texte + notes)
✅ **Cohérence parfaite**: Chunks et entités issus de la même analyse
✅ **Single source of truth**: Une seule interprétation LLM du contenu

---

## 📊 ARCHITECTURE ACTUELLE vs CIBLE

### Architecture Actuelle (Qdrant seulement)

```
1. Upload PPTX
   ↓
2. Conversion PPTX → PDF → PNG images
   ↓
3. 🤖 APPEL LLM #1: Analyse deck global (metadata)
   ↓
4. Pour chaque slide:
      🤖 APPEL LLM #2: Vision + texte
      → Output: concepts[]
      → Chunking + embedding
      → Ingestion Qdrant
   ↓
5. Finalisation
```

**Coût**: ~$0.01-0.03 par slide × N slides
**Latence**: 2-5s par slide

---

### Architecture Cible (Qdrant + Graphiti + Facts unifié)

```
1. Upload PPTX
   ↓
2. Conversion PPTX → PDF → PNG images
   ↓
3. 🤖 APPEL LLM #1: Analyse deck global (metadata)
   → Output: metadata + main_solution + supporting_solutions
   → 🆕 Ingestion entités principales dans Graphiti (status="proposed")
   ↓
4. Pour chaque slide:
      🤖 APPEL LLM #2: Vision + texte (MODIFIÉ - extraction unifiée)
      → Output:
         • concepts[] (pour chunks Qdrant)
         • 🆕 entities[] (pour Graphiti KG)
         • 🆕 relations[] (pour Graphiti KG)
         • 🆕 facts[] (pour gouvernance Facts)

      Ingestion parallèle:
      • Qdrant: chunks avec related_node_ids + related_facts
      • 🆕 Graphiti KG: entities/relations (status="candidate")
      • 🆕 Graphiti Facts: facts structurés (status="proposed")
   ↓
5. 🆕 Post-traitement:
   • Dédoublonnage entités/facts deck-wide
   • Linking entities ↔ chunks via related_node_ids
   • Linking facts ↔ chunks via related_facts
   • Canonicalisation entity names (Phase 4)
   • Détection conflits facts (Phase 3)
   ↓
6. Finalisation
```

**Coût**: **IDENTIQUE** (~$0.01-0.03 par slide × N slides)
**Latence**: **IDENTIQUE** (2-5s par slide)
**Bénéfice**: **+KG automatiquement enrichi** sans coût additionnel

---

## 🔧 IMPLÉMENTATION TECHNIQUE

### Étape 1: Extension du Prompt Slide

**Fichier**: `config/prompts.yaml`

**Prompt actuel** (simplifié):
```yaml
slide:
  default:
    template: |
      Analyze this slide and extract concepts.
      Return JSON: {"concepts": [...]}
```

**Prompt étendu** (nouveau):
```yaml
slide:
  default:
    template: |
      Analyze this slide with image, text, and notes.

      Deck context: {{ deck_summary }}
      Slide {{ slide_index }}: {{ source_name }}
      Text: {{ text }}
      Notes: {{ notes }}
      MegaParse: {{ megaparse_content }}

      Extract THREE types of information:

      1. CONCEPTS (for semantic search chunks):
         - Detailed explanations of ideas/features
         - Business context and use cases
         - Technical details

      2. ENTITIES (for knowledge graph):
         - Products/Solutions (SAP S/4HANA, SAP Fiori, etc.)
         - Technologies (OData, APIs, protocols)
         - Personas/Roles (IT Manager, Developer, etc.)
         - Features/Modules (Financial Planning, Inventory Mgmt, etc.)
         - Concepts (Cloud-native, Real-time, Integration, etc.)

      3. RELATIONS (for knowledge graph):
         - USES_TECHNOLOGY (S/4HANA uses Fiori)
         - INTEGRATES_WITH (S/4HANA integrates with Ariba)
         - REQUIRES (Feature X requires Module Y)
         - REPLACES (S/4HANA replaces ECC)
         - TARGETS_PERSONA (Solution targets IT Managers)

      Return JSON with this EXACT structure:
      {
        "concepts": [
          {
            "full_explanation": "Detailed explanation...",
            "meta": {
              "scope": "solution-specific",
              "type": "feature_description",
              "level": "technical",
              "tags": ["integration", "API"],
              "mentioned_solutions": ["SAP BTP"]
            }
          }
        ],
        "entities": [
          {
            "name": "SAP S/4HANA Cloud",
            "entity_type": "PRODUCT",
            "description": "Cloud ERP solution with real-time analytics",
            "attributes": {
              "version": "2024 FPS01",
              "deployment": "Public Cloud",
              "vendor": "SAP"
            },
            "confidence": 0.95
          }
        ],
        "relations": [
          {
            "source_entity": "SAP S/4HANA Cloud",
            "target_entity": "SAP Fiori",
            "relation_type": "USES_TECHNOLOGY",
            "description": "S/4HANA uses Fiori for modern user experience",
            "confidence": 0.90
          }
        ]
      }

      IMPORTANT:
      - Extract entities even if briefly mentioned
      - Capture relations visible in diagrams/architecture images
      - Use confidence score (0-1) based on clarity of information
      - For entity_type, use: PRODUCT, TECHNOLOGY, PERSONA, FEATURE, CONCEPT
      - For relation_type, use verbs: USES_TECHNOLOGY, INTEGRATES_WITH, REQUIRES, REPLACES, TARGETS_PERSONA
```

---

### Étape 2: Modification `ask_gpt_slide_analysis()`

**Fichier**: `src/knowbase/ingestion/pipelines/pptx_pipeline.py` (ligne 913)

**Retour actuel**:
```python
return {
    "chunks": enriched,  # List[Dict] - pour Qdrant
}
```

**Retour modifié**:
```python
return {
    "chunks": enriched,           # List[Dict] - pour Qdrant (inchangé)
    "entities": entities,         # 🆕 List[Dict] - pour Graphiti
    "relations": relations,       # 🆕 List[Dict] - pour Graphiti
    "_extraction_meta": {         # 🆕 Métadonnées extraction
        "slide_index": slide_index,
        "extraction_time": datetime.now(timezone.utc).isoformat(),
        "llm_model": llm_router.model_name,
        "confidence_avg": avg_confidence
    }
}
```

**Code modifié**:
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
    # ... existing code jusqu'à l'appel LLM ...

    try:
        raw_content = llm_router.complete(TaskType.VISION, msg)
        cleaned_content = clean_gpt_response(raw_content or "")
        result = json.loads(cleaned_content)

        # Extraction CONCEPTS (existant, inchangé)
        concepts = result.get("concepts", [])
        enriched = []
        for it in concepts:
            full_text = it.get("full_explanation", "").strip()
            if len(full_text) < 20:
                continue
            # ... chunking logic existante ...
            enriched.append({
                "full_explanation": full_text,
                "meta": it.get("meta", {}),
                "prompt_meta": {...}
            })

        # 🆕 Extraction ENTITIES
        entities = result.get("entities", [])
        validated_entities = []
        for entity in entities:
            # Validation basique
            if not entity.get("name") or not entity.get("entity_type"):
                logger.warning(f"Slide {slide_index}: entité invalide ignorée")
                continue

            # Normalisation entity_type
            entity_type = entity.get("entity_type", "CONCEPT").upper()
            if entity_type not in ["PRODUCT", "TECHNOLOGY", "PERSONA", "FEATURE", "CONCEPT"]:
                entity_type = "CONCEPT"

            validated_entities.append({
                "name": entity["name"].strip(),
                "entity_type": entity_type,
                "description": entity.get("description", ""),
                "attributes": entity.get("attributes", {}),
                "confidence": float(entity.get("confidence", 0.8)),
                "provenance": {
                    "slide_index": slide_index,
                    "source_name": source_name,
                    "extraction_method": "llm_vision"
                }
            })

        # 🆕 Extraction RELATIONS
        relations = result.get("relations", [])
        validated_relations = []
        for relation in relations:
            # Validation basique
            if not relation.get("source_entity") or not relation.get("target_entity"):
                logger.warning(f"Slide {slide_index}: relation invalide ignorée")
                continue

            validated_relations.append({
                "source_entity": relation["source_entity"].strip(),
                "target_entity": relation["target_entity"].strip(),
                "relation_type": relation.get("relation_type", "RELATED_TO"),
                "description": relation.get("description", ""),
                "confidence": float(relation.get("confidence", 0.8)),
                "provenance": {
                    "slide_index": slide_index,
                    "source_name": source_name
                }
            })

        # Calcul confidence moyenne pour métadonnées
        all_confidences = (
            [e["confidence"] for e in validated_entities] +
            [r["confidence"] for r in validated_relations]
        )
        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0

        logger.info(
            f"Slide {slide_index}: {len(enriched)} chunks, "
            f"{len(validated_entities)} entités, "
            f"{len(validated_relations)} relations extraits"
        )

        return {
            "chunks": enriched,
            "entities": validated_entities,
            "relations": validated_relations,
            "_extraction_meta": {
                "slide_index": slide_index,
                "extraction_time": datetime.now(timezone.utc).isoformat(),
                "llm_model": llm_router.current_model,
                "confidence_avg": round(avg_confidence, 2)
            }
        }

    except json.JSONDecodeError as e:
        logger.error(f"Slide {slide_index}: JSON parse error: {e}")
        return {"chunks": [], "entities": [], "relations": []}

    except Exception as e:
        logger.error(f"Slide {slide_index}: extraction error: {e}")
        return {"chunks": [], "entities": [], "relations": []}
```

---

### Étape 3: Ingestion Unifiée dans `process_pptx()`

**Fichier**: `src/knowbase/ingestion/pipelines/pptx_pipeline.py` (ligne 1062)

**Ajout après la boucle de traitement des slides**:

```python
def process_pptx(pptx_path: Path, document_type: str = "default", progress_callback=None, rq_job=None):
    # ... existing code jusqu'à la boucle slides ...

    # 🆕 Initialiser service KG
    from knowbase.api.services.knowledge_graph import get_knowledge_graph_service
    from knowbase.api.schemas.graphiti import EntityCreate, RelationCreate, EntityType

    kg_service = get_knowledge_graph_service()

    # Contexte utilisateur (group_id pour multi-tenant)
    user_context = {
        "user_id": rq_job.meta.get("user_id", "system") if rq_job else "system",
        "group_id": rq_job.meta.get("group_id", "default") if rq_job else "default"
    }

    # Accumulateurs deck-wide
    all_kg_entities = []
    all_kg_relations = []
    slide_entity_map = {}  # {slide_index: [entity_ids]}

    # Boucle traitement slides (existant)
    for i, (idx, future) in enumerate(tasks):
        # ... existing progress tracking ...

        result = future.result()
        chunks = result.get("chunks", [])
        entities = result.get("entities", [])
        relations = result.get("relations", [])

        # ✅ Ingestion Qdrant (existant, temporairement sans related_node_ids)
        chunk_ids = ingest_chunks(chunks, metadata, pptx_path.stem, idx, summary)

        # 🆕 Accumulation KG data
        if entities:
            all_kg_entities.extend(entities)
            logger.info(f"Slide {idx}: {len(entities)} entités pour KG")

        if relations:
            all_kg_relations.extend(relations)
            logger.info(f"Slide {idx}: {len(relations)} relations pour KG")

        slide_entity_map[idx] = entities  # Pour linking ultérieur

    # 🆕 POST-TRAITEMENT: Dédoublonnage entités deck-wide
    logger.info(f"🔄 Dédoublonnage de {len(all_kg_entities)} entités...")
    unique_entities = deduplicate_entities(all_kg_entities)
    logger.info(f"✅ {len(unique_entities)} entités uniques après dédoublonnage")

    # 🆕 INGESTION GRAPHITI: Entités
    entity_id_map = {}  # {entity_name: graphiti_uuid}

    if unique_entities:
        logger.info(f"🔄 Ingestion de {len(unique_entities)} entités dans Graphiti...")
        for entity_data in unique_entities:
            try:
                # Normalisation nom (canonicalisation SAP si applicable)
                canonical_name = normalize_entity_name(entity_data["name"])

                entity_create = EntityCreate(
                    name=canonical_name,
                    entity_type=EntityType[entity_data["entity_type"]],
                    description=entity_data.get("description", ""),
                    attributes={
                        **entity_data.get("attributes", {}),
                        "confidence": entity_data.get("confidence", 0.8),
                        "source_document": pptx_path.name,
                        "extraction_method": "llm_vision_unified"
                    },
                    status="proposed"  # 🔑 Nécessite validation humaine
                )

                created_entity = await kg_service.create_entity(entity_create, user_context)
                entity_id_map[canonical_name] = created_entity.uuid

                logger.debug(f"✅ Entité créée: {canonical_name} ({created_entity.uuid})")

            except Exception as e:
                logger.error(f"❌ Erreur création entité '{entity_data['name']}': {e}")

    # 🆕 INGESTION GRAPHITI: Relations
    if all_kg_relations:
        logger.info(f"🔄 Ingestion de {len(all_kg_relations)} relations dans Graphiti...")
        for relation_data in all_kg_relations:
            try:
                # Résolution des UUIDs via entity_id_map
                source_name = normalize_entity_name(relation_data["source_entity"])
                target_name = normalize_entity_name(relation_data["target_entity"])

                source_uuid = entity_id_map.get(source_name)
                target_uuid = entity_id_map.get(target_name)

                if not source_uuid or not target_uuid:
                    logger.warning(
                        f"Relation ignorée: entités non trouvées "
                        f"({source_name} → {target_name})"
                    )
                    continue

                relation_create = RelationCreate(
                    source_entity_uuid=source_uuid,
                    target_entity_uuid=target_uuid,
                    relation_type=relation_data["relation_type"],
                    description=relation_data.get("description", ""),
                    attributes={
                        "confidence": relation_data.get("confidence", 0.8),
                        "source_document": pptx_path.name,
                        "slide_index": relation_data["provenance"]["slide_index"]
                    },
                    status="proposed"
                )

                created_relation = await kg_service.create_relation(relation_create, user_context)
                logger.debug(
                    f"✅ Relation créée: {source_name} --[{relation_data['relation_type']}]--> {target_name}"
                )

            except Exception as e:
                logger.error(
                    f"❌ Erreur création relation "
                    f"'{relation_data['source_entity']} → {relation_data['target_entity']}': {e}"
                )

    # 🆕 LINKING: Mise à jour related_node_ids dans Qdrant (Phase 2)
    # TODO: Pour chaque chunk, trouver entities mentionnées et ajouter leurs UUIDs
    # await update_chunk_related_nodes(chunk_ids, entity_id_map)

    # Statistiques finales
    logger.info("=" * 60)
    logger.info("📊 RÉSUMÉ INGESTION")
    logger.info("=" * 60)
    logger.info(f"Chunks Qdrant: {len(chunk_ids)}")
    logger.info(f"Entités KG: {len(entity_id_map)}")
    logger.info(f"Relations KG: {len(all_kg_relations)}")
    logger.info("=" * 60)

    # ... existing finalization code ...
```

---

### Étape 4: Fonctions Utilitaires

**Fichier**: `src/knowbase/ingestion/extractors/entity_utils.py` (nouveau)

```python
from typing import List, Dict
from rapidfuzz import fuzz

def deduplicate_entities(entities: List[Dict]) -> List[Dict]:
    """
    Déduplique entités avec fuzzy matching et fusion attributs.

    Exemple:
        ["SAP S/4HANA Cloud", "S/4HANA Cloud"] → "SAP S/4HANA Cloud"
    """
    unique = []
    seen_names = set()

    for entity in entities:
        name = entity["name"]

        # Recherche fuzzy dans entités déjà vues
        best_match = None
        best_score = 0

        for existing_name in seen_names:
            score = fuzz.ratio(name.lower(), existing_name.lower())
            if score > best_score:
                best_score = score
                best_match = existing_name

        # Si score > 85, considérer comme doublon
        if best_score > 85:
            # Fusionner attributs avec entité existante
            for existing_entity in unique:
                if existing_entity["name"] == best_match:
                    existing_entity["attributes"].update(entity.get("attributes", {}))
                    # Garder la confidence la plus élevée
                    existing_entity["confidence"] = max(
                        existing_entity["confidence"],
                        entity.get("confidence", 0.8)
                    )
                    break
        else:
            # Nouvelle entité unique
            unique.append(entity)
            seen_names.add(name)

    return unique


def normalize_entity_name(name: str) -> str:
    """
    Normalise nom d'entité (canonicalisation SAP si applicable).

    Exemple:
        "SAP Cloud ERP" → "SAP S/4HANA Cloud, Public Edition"
    """
    from knowbase.common.sap.normalizer import normalize_solution_name

    # Tentative normalisation SAP
    solution_id, canonical_name = normalize_solution_name(name)

    if solution_id != "UNMAPPED":
        return canonical_name

    # Sinon, simple nettoyage
    return name.strip()
```

---

## 📊 FLUX DE DONNÉES UNIFIÉ

### Diagramme architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      PPTX Upload                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│          Conversion PPTX → PDF → PNG Images                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  🤖 LLM #1: Deck Global Analysis                             │
│  Output: metadata + main_solution + supporting_solutions     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ├──────────────────────┬────────────────┐
                       ▼                      ▼                ▼
              ┌────────────────┐    ┌──────────────┐  ┌──────────────┐
              │  Entités deck  │    │ Metadata doc │  │   Summary    │
              │  (proposed)    │    │              │  │              │
              └────────┬───────┘    └──────┬───────┘  └──────┬───────┘
                       │                   │                 │
                       ▼                   ▼                 ▼
              ┌─────────────────────────────────────────────────┐
              │            Graphiti KG (status=proposed)        │
              └─────────────────────────────────────────────────┘

                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Pour chaque slide:                                          │
│  🤖 LLM #2: Vision + Text Analysis (UNIFIÉ)                  │
│  Output:                                                     │
│    • concepts[] → chunks Qdrant                              │
│    • entities[] → Graphiti KG                                │
│    • relations[] → Graphiti KG                               │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
┌────────────┐  ┌────────────┐  ┌────────────┐
│  concepts  │  │  entities  │  │  relations │
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │               │               │
      ▼               ▼               ▼
┌──────────────┐  ┌──────────────────────────┐
│ Chunking +   │  │ Dédoublonnage + Fusion   │
│ Embedding    │  │ Canonicalisation         │
└─────┬────────┘  └─────┬────────────────────┘
      │                 │
      ▼                 ▼
┌──────────────┐  ┌──────────────────────────┐
│   Qdrant     │  │    Graphiti KG           │
│   (chunks)   │  │ (entities + relations)   │
└──────────────┘  │   status=proposed        │
                  └──────────────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │ Linking via         │
              │ related_node_ids    │
              │ (Phase 2)           │
              └─────────────────────┘
```

---

## 💰 ÉCONOMIE DE COÛTS

### Comparaison approches

| Approche | Coût LLM | Latence | Qualité Extraction |
|----------|----------|---------|-------------------|
| **Double appel** (non recommandé) | 2× coût | 2× temps | Risque incohérence |
| **Post-processing chunks** | +30% coût | +50% temps | Perte contexte visuel |
| **✅ Appel unifié** (recommandé) | **0€ additionnel** | **0s additionnel** | **Contexte complet** |

### Estimation sur volume réel

**Document type**: PPTX 50 slides

| Méthode | Coût Total | Temps Total |
|---------|-----------|-------------|
| Double appel | ~$3.00 | ~8 minutes |
| Post-processing | ~$2.00 | ~6 minutes |
| **Appel unifié** | **~$1.50** | **~4 minutes** |

**Économie annuelle** (1000 docs/an):
- Coût: **−$1500** vs double appel
- Temps: **−4000 minutes** (66 heures)

---

## ✅ PLAN D'IMPLÉMENTATION

### Phase 1: POC Minimal (2-3 jours)

**Objectif**: Valider faisabilité technique

- [ ] Modifier prompt slide dans `prompts.yaml`
- [ ] Adapter `ask_gpt_slide_analysis()` pour parser entities/relations
- [ ] Créer `entity_utils.py` (dédoublonnage + normalisation)
- [ ] Intégrer ingestion KG dans `process_pptx()`
- [ ] Tester avec 1 PPTX simple (5-10 slides)

**Critères succès**:
- ✅ Prompt retourne JSON valide avec concepts + entities + relations
- ✅ Entités ingérées dans Graphiti (status="proposed")
- ✅ Aucune régression Qdrant (chunks identiques)
- ✅ Latence stable (+0-10% acceptable)

---

### Phase 2: Production Ready (1 semaine)

**Objectif**: Robustesse et optimisations

- [ ] Gestion erreurs (LLM, parsing, ingestion)
- [ ] Dédoublonnage entités deck-wide
- [ ] Canonicalisation SAP automatique
- [ ] Linking entities ↔ chunks (related_node_ids)
- [ ] Tests avec gros deck (100+ slides)
- [ ] Statistiques KG dans réponse API

**Critères succès**:
- ✅ Gestion erreurs gracieuse (pas de crash)
- ✅ Dédoublonnage fonctionne (fuzzy matching)
- ✅ Tests E2E passent (ingestion + recherche)

---

### Phase 3: Optimisations Avancées (2-3 semaines)

**Objectif**: Qualité extraction maximale

- [ ] Fine-tuning prompt avec exemples concrets
- [ ] Active learning sur rejets validation humaine
- [ ] Détection relations depuis diagrammes (vision améliorée)
- [ ] Fusion intelligente attributs entités dupliquées
- [ ] UI visualisation entités extraites par document

---

## 🎯 MÉTRIQUES DE SUCCÈS

### Court Terme (Phase 1)

- ✅ Prompt parse correctement ≥95% slides
- ✅ Entités extraites ≥5 par slide en moyenne
- ✅ Relations extraites ≥2 par slide en moyenne
- ✅ Latence ingestion +0-10% vs baseline

### Moyen Terme (Phase 2)

- ✅ Dédoublonnage réduit entités de 30-50%
- ✅ Canonicalisation SAP fonctionne (100% noms corrects)
- ✅ related_node_ids liés pour ≥80% chunks
- ✅ Zero régression qualité chunks Qdrant

### Long Terme (Phase 3)

- ✅ Qualité extraction validée ≥85% par humains
- ✅ Active learning améliore prompts (+10% précision)
- ✅ KG enrichi automatiquement (≥80% docs avec entités)

---

## 🚨 RISQUES & MITIGATIONS

### Risque 1: Prompt trop complexe → LLM confus

**Probabilité**: Moyenne
**Impact**: Élevé (parsing échoue)

**Mitigation**:
- Tester prompt avec few-shot examples
- Fournir schema JSON strict
- Fallback: si parsing échoue, retourner seulement chunks

---

### Risque 2: Entités dupliquées (variations de noms)

**Probabilité**: Élevée
**Impact**: Moyen (pollution KG)

**Mitigation**:
- Dédoublonnage fuzzy matching deck-wide
- Canonicalisation SAP automatique
- Validation humaine (status="proposed")

---

### Risque 3: Latence accrue si LLM plus lent

**Probabilité**: Faible
**Impact**: Moyen

**Mitigation**:
- Monitoring latence par slide
- Timeout configurables
- Retry logic robuste

---

## 📝 CONCLUSION

### ✅ Décision Validée

**L'approche unifiée** (un seul appel LLM par slide) est **optimale** car:

1. **Économie maximale**: 0€ et 0s additionnels
2. **Qualité supérieure**: Contexte complet (vision + texte)
3. **Cohérence parfaite**: Chunks et entités issus de même analyse
4. **Simplicité**: Un seul workflow à maintenir

### 🚀 Prochaine Étape

**Démarrer Phase 1 (POC Minimal)** :
1. Créer branche `feat/unified-llm-extraction`
2. Modifier prompt slide
3. Adapter `ask_gpt_slide_analysis()`
4. Tester sur 1 PPTX

**Estimation effort**: 2-3 jours développement + tests

---

**Document de référence** pour implémentation unifiée extraction LLM.
