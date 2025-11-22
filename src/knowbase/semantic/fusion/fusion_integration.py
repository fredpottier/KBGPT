"""
🌊 OSMOSE Semantic Intelligence - Fusion Integration

Phase 1.8.1d: Intégration SmartConceptMerger dans pipeline OSMOSE.

Ce module fournit la couche d'intégration entre:
- Pipeline d'extraction classique (TopicSegmenter + ConceptExtractor)
- Nouveau pipeline fusion (Extraction Locale + SmartConceptMerger)

Usage:
    from knowbase.semantic.fusion.fusion_integration import process_document_with_fusion

    canonical_concepts = await process_document_with_fusion(
        document_type="PPTX",
        slides_data=slides,
        document_context=context,
        config=fusion_config
    )
"""

from typing import List, Dict, Optional, Any
import logging
import yaml
from pathlib import Path

from knowbase.semantic.models import Concept, Topic, Window
from .smart_concept_merger import SmartConceptMerger
from .models import FusionConfig
from .rules import MainEntitiesMergeRule, AlternativesFeaturesRule, SlideSpecificPreserveRule


logger = logging.getLogger(__name__)


def load_fusion_config(config_path: Optional[Path] = None) -> FusionConfig:
    """
    Charge configuration fusion depuis YAML.

    Args:
        config_path: Chemin vers fusion_rules.yaml (default: config/fusion_rules.yaml)

    Returns:
        FusionConfig: Configuration chargée

    Note:
        Si fichier absent ou erreur, retourne config par défaut
    """
    if config_path is None:
        config_path = Path("config/fusion_rules.yaml")

    try:
        if not config_path.exists():
            logger.warning(
                f"[OSMOSE:Fusion] Config file not found: {config_path}, using defaults"
            )
            return FusionConfig()

        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        if not yaml_data or "fusion" not in yaml_data:
            logger.warning(
                f"[OSMOSE:Fusion] Invalid config structure in {config_path}, using defaults"
            )
            return FusionConfig()

        # Parser section fusion
        fusion_data = yaml_data["fusion"]
        config = FusionConfig.from_yaml(fusion_data)

        logger.info(f"[OSMOSE:Fusion] ✅ Config loaded from {config_path}")
        return config

    except Exception as e:
        logger.error(f"[OSMOSE:Fusion] Error loading config: {e}", exc_info=True)
        logger.warning("[OSMOSE:Fusion] Using default config")
        return FusionConfig()


def create_fusion_rules(config: FusionConfig) -> List:
    """
    Crée instances des règles de fusion depuis config.

    Args:
        config: Configuration fusion

    Returns:
        List[FusionRule]: Règles instanciées et triées par priorité
    """
    rules = []

    if not config.rules_config:
        logger.warning("[OSMOSE:Fusion] No rules configured, using defaults")
        # Créer règles par défaut
        rules.append(MainEntitiesMergeRule(config={
            "enabled": True,
            "priority": 1,
            "min_occurrence_ratio": 0.15,
            "similarity_threshold": 0.88,
            "eligible_types": ["entity", "product", "technology"]  # Types domain-agnostic
        }))
        rules.append(AlternativesFeaturesRule(config={
            "enabled": True,
            "priority": 2,
            "antonym_keywords": ["vs", "versus", "instead of", "alternative"],
            "min_co_occurrence": 3
        }))
        rules.append(SlideSpecificPreserveRule(config={
            "enabled": True,
            "priority": 3,
            "max_occurrence": 2,
            "preserve_types": ["metric", "detail", "technical", "value"],  # Types domain-agnostic
            "min_name_length": 10
        }))
        return rules

    # Parser config YAML pour créer règles
    for rule_config in config.rules_config:
        rule_name = rule_config.get("name")
        rule_enabled = rule_config.get("enabled", True)

        if not rule_enabled:
            logger.debug(f"[OSMOSE:Fusion] Rule {rule_name} disabled, skipping")
            continue

        rule_params = rule_config.get("config", {})
        rule_params["enabled"] = rule_enabled
        rule_params["priority"] = rule_config.get("priority", 99)

        # Instancier règle selon nom
        if rule_name == "main_entities_merge":
            rules.append(MainEntitiesMergeRule(config=rule_params))
        elif rule_name == "alternatives_features":
            rules.append(AlternativesFeaturesRule(config=rule_params))
        elif rule_name == "slide_specific_preserve":
            rules.append(SlideSpecificPreserveRule(config=rule_params))
        else:
            logger.warning(f"[OSMOSE:Fusion] Unknown rule name: {rule_name}, skipping")

    if not rules:
        logger.warning("[OSMOSE:Fusion] No valid rules created, using defaults")
        # Fallback règles par défaut
        return create_fusion_rules(FusionConfig())

    logger.info(f"[OSMOSE:Fusion] Created {len(rules)} fusion rules")
    return rules


async def process_document_with_fusion(
    document_type: str,
    slides_data: Optional[List[Dict[str, Any]]] = None,
    text_content: Optional[str] = None,
    document_context: Optional[str] = None,
    concept_extractor: Optional[Any] = None,  # MultilingualConceptExtractor
    config: Optional[FusionConfig] = None
) -> List[Any]:  # List[CanonicalConcept]
    """
    Point d'entrée principal pour extraction avec fusion intelligente.

    Args:
        document_type: Type document ("PPTX", "PDF", "TXT", etc.)
        slides_data: Données slides si PPTX (liste de dicts avec 'text', 'notes', 'index')
        text_content: Contenu textuel brut si non-PPTX
        document_context: Contexte document global (Phase 1.8 P0.1)
        concept_extractor: Instance MultilingualConceptExtractor
        config: Configuration fusion (chargée si None)

    Returns:
        List[CanonicalConcept]: Concepts fusionnés

    Process:
        - Si PPTX + slides_data → Extraction Locale + Fusion
        - Sinon → Pipeline classique (TopicSegmenter)
    """
    # Charger config si nécessaire
    if config is None:
        config = load_fusion_config()

    if not config.enabled:
        logger.info("[OSMOSE:Fusion] Fusion disabled, using standard pipeline")
        # TODO: Appeler pipeline classique (TopicSegmenter)
        return []

    # Vérifier éligibilité document pour fusion
    if document_type.upper() not in config.local_extraction_types:
        logger.info(
            f"[OSMOSE:Fusion] Document type {document_type} not eligible for local extraction, "
            "using standard pipeline"
        )
        # TODO: Appeler pipeline classique (TopicSegmenter)
        return []

    # Pipeline Fusion (PPTX uniquement pour MVP)
    if document_type.upper() in ["PPTX", "PPTX_SLIDES"] and slides_data:
        logger.info(
            f"[OSMOSE:Fusion] Processing {len(slides_data)} slides with local extraction + fusion"
        )

        # Étape 1: Extraction locale par slide
        local_concepts = await extract_concepts_per_slide(
            slides_data=slides_data,
            document_context=document_context,
            concept_extractor=concept_extractor
        )

        logger.info(
            f"[OSMOSE:Fusion] Extracted {sum(len(concepts) for concepts in local_concepts)} "
            f"local concepts from {len(local_concepts)} slides"
        )

        # Étape 2: Fusion intelligente
        rules = create_fusion_rules(config)
        merger = SmartConceptMerger(rules=rules, config=config)

        context_metadata = {
            "total_slides": len(slides_data),
            "document_type": document_type
        }

        canonical_concepts = await merger.merge(
            local_concepts=local_concepts,
            document_context=document_context,
            context_metadata=context_metadata
        )

        logger.info(
            f"[OSMOSE:Fusion] ✅ Fusion complete: {len(canonical_concepts)} canonical concepts"
        )

        return canonical_concepts

    else:
        logger.warning(
            f"[OSMOSE:Fusion] PPTX document but no slides_data provided, "
            "cannot use local extraction"
        )
        # TODO: Fallback pipeline classique
        return []


async def extract_concepts_per_slide(
    slides_data: List[Dict[str, Any]],
    document_context: Optional[str],
    concept_extractor: Optional[Any],  # MultilingualConceptExtractor
    document_id: str = "fusion_doc"  # Document ID pour traçabilité
) -> List[List[Concept]]:
    """
    Extrait concepts localement pour chaque slide.

    Args:
        slides_data: Données slides (avec 'text', 'notes', 'index')
        document_context: Contexte document global
        concept_extractor: Instance MultilingualConceptExtractor
        document_id: ID document pour traçabilité

    Returns:
        List[List[Concept]]: Liste de listes (1 liste par slide)

    Note:
        Utilise extraction_mode="local" pour granularité fine
    """
    if not concept_extractor:
        logger.error("[OSMOSE:Fusion] No concept extractor provided, cannot extract")
        return []

    local_concepts = []

    for i, slide in enumerate(slides_data):
        slide_index = slide.get("index", i)
        slide_text = slide.get("text", "")
        slide_notes = slide.get("notes", "")

        # Combiner texte + notes
        combined_text = f"{slide_text}\n{slide_notes}".strip()

        if not combined_text:
            logger.debug(f"[OSMOSE:Fusion] Slide {slide_index} empty, skipping")
            local_concepts.append([])
            continue

        # Créer Topic pour ConceptExtractor
        # Note: ConceptExtractor attend un Topic avec tous les champs requis
        topic = Topic(
            topic_id=f"slide_{slide_index}",
            document_id=document_id,
            section_path=f"Slide {slide_index}",
            windows=[Window(text=combined_text, start=0, end=len(combined_text))],
            anchors=[],  # Sera rempli par ConceptExtractor si nécessaire
            cohesion_score=1.0,  # Slide = unité atomique cohésive
            language="unknown"  # Sera détecté par ConceptExtractor
        )

        # Extraire concepts en mode local
        try:
            concepts = await concept_extractor.extract_concepts(
                topic=topic,
                enable_llm=True,
                document_context=document_context,
                extraction_mode="local",
                source_metadata={"slide_index": slide_index}
            )

            local_concepts.append(concepts)

            logger.debug(
                f"[OSMOSE:Fusion] Slide {slide_index}: {len(concepts)} concepts extracted"
            )

        except Exception as e:
            logger.error(
                f"[OSMOSE:Fusion] Error extracting concepts from slide {slide_index}: {e}",
                exc_info=True
            )
            local_concepts.append([])

    return local_concepts
