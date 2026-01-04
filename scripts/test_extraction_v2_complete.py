#!/usr/bin/env python3
"""
Test complet de l'architecture Extraction V2.

Verifie tous les composants:
1. Modeles de donnees
2. Signaux Vision Gating V4
3. GatingEngine
4. VisionAnalyzer (mock)
5. Merger + Linearizer
6. Pipeline complet

Usage:
    python scripts/test_extraction_v2_complete.py
"""

import sys
import asyncio


def test_models():
    """Test tous les modeles Phase 1."""
    print("\n" + "=" * 60)
    print("TEST 1: Modeles de donnees")
    print("=" * 60)

    from knowbase.extraction_v2.models.elements import (
        BoundingBox,
        TextBlock,
        VisualElement,
        TableData,
    )
    from knowbase.extraction_v2.models.signals import VisionSignals
    from knowbase.extraction_v2.models.gating import ExtractionAction, GatingDecision
    from knowbase.extraction_v2.models.vision_unit import VisionUnit
    from knowbase.extraction_v2.models.vision_output import (
        VisionElement,
        VisionRelation,
        VisionExtraction,
    )
    from knowbase.extraction_v2.models.extraction_result import (
        ExtractionResult,
        PageIndex,
        DocumentStructure,
        PageOutput,
    )
    from knowbase.extraction_v2.models.domain_context import (
        VisionDomainContext,
        SAP_VISION_CONTEXT,
    )

    # Test BoundingBox
    bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
    assert abs(bbox.area - 0.12) < 0.001, f"BoundingBox.area failed"
    print("  BoundingBox OK")

    # Test TextBlock
    block = TextBlock(type="paragraph", text="Hello world", level=0)
    assert block.char_count == 11
    assert block.is_short
    print("  TextBlock OK")

    # Test VisionSignals
    signals = VisionSignals(RIS=0.8, VDS=0.5, TFS=0.3, SDS=0.2, VTS=0.1)
    weights = {"RIS": 0.30, "VDS": 0.30, "TFS": 0.15, "SDS": 0.15, "VTS": 0.10}
    vns = signals.compute_weighted_score(weights)
    expected_vns = 0.8*0.30 + 0.5*0.30 + 0.3*0.15 + 0.2*0.15 + 0.1*0.10
    assert abs(vns - expected_vns) < 0.001, f"VisionSignals score failed"
    print("  VisionSignals OK")

    # Test ExtractionAction
    action = ExtractionAction.from_score(0.65)
    assert action == ExtractionAction.VISION_REQUIRED
    action = ExtractionAction.from_score(0.45)
    assert action == ExtractionAction.VISION_RECOMMENDED
    action = ExtractionAction.from_score(0.30)
    assert action == ExtractionAction.NONE
    print("  ExtractionAction OK")

    # Test VisionUnit
    unit = VisionUnit(
        id="PDF_PAGE_0",
        format="PDF",
        index=0,
        dimensions=(612, 792),
        blocks=[block],
    )
    assert unit.text_blocks_count == 1
    assert unit.full_text == "Hello world"
    print("  VisionUnit OK")

    # Test VisionDomainContext
    context = VisionDomainContext.default()
    assert context is not None
    prompt_section = SAP_VISION_CONTEXT.to_prompt_section()
    assert "SAP" in prompt_section
    print("  VisionDomainContext OK")

    # Test VisionExtraction
    elem = VisionElement(id="box_1", type="box", text="SAP S/4HANA", confidence=0.95)
    rel = VisionRelation(
        source_id="box_1",
        target_id="box_2",
        type="flows_to",
        evidence="arrow",
        confidence=0.9,
    )
    extraction = VisionExtraction(
        kind="architecture_diagram",
        elements=[elem],
        relations=[rel],
        page_index=6,
        confidence=0.85,
    )
    vision_text = extraction.to_vision_text()
    assert "[VISUAL_ENRICHMENT" in vision_text
    print("  VisionExtraction OK")

    print("\n  ALL MODELS OK")
    return True


def test_gating_signals():
    """Test les signaux Vision Gating V4."""
    print("\n" + "=" * 60)
    print("TEST 2: Signaux Vision Gating V4")
    print("=" * 60)

    from knowbase.extraction_v2.gating.signals import (
        compute_raster_image_signal,
        compute_vector_drawing_signal,
        compute_text_fragmentation_signal,
        compute_spatial_dispersion_signal,
        compute_visual_table_signal,
        compute_all_signals,
    )
    from knowbase.extraction_v2.models.elements import (
        BoundingBox,
        TextBlock,
        VisualElement,
    )
    from knowbase.extraction_v2.models.vision_unit import VisionUnit

    # Creer une unit avec une grande image
    large_image = VisualElement(
        kind="raster_image",
        bbox=BoundingBox(x=0.1, y=0.1, width=0.6, height=0.6, normalized=True),
        element_id="img_1",
    )
    unit_with_image = VisionUnit(
        id="PDF_PAGE_0",
        format="PDF",
        index=0,
        dimensions=(612, 792),
        blocks=[],
        visual_elements=[large_image],
    )
    ris = compute_raster_image_signal(unit_with_image)
    assert ris == 1.0, f"RIS should be 1.0 for large image, got {ris}"
    print(f"  RIS (large image): {ris} OK")

    # Creer une unit avec beaucoup de blocs courts
    short_blocks = [
        TextBlock(type="paragraph", text=f"Label {i}", level=0)
        for i in range(15)
    ]
    unit_fragmented = VisionUnit(
        id="PPTX_SLIDE_0",
        format="PPTX",
        index=0,
        dimensions=(960, 540),
        blocks=short_blocks,
    )
    tfs = compute_text_fragmentation_signal(unit_fragmented)
    assert tfs == 1.0, f"TFS should be 1.0 for fragmented text, got {tfs}"
    print(f"  TFS (fragmented): {tfs} OK")

    # Unit vide
    unit_empty = VisionUnit(
        id="PDF_PAGE_1",
        format="PDF",
        index=1,
        dimensions=(612, 792),
        blocks=[],
    )
    ris_empty = compute_raster_image_signal(unit_empty)
    vds_empty = compute_vector_drawing_signal(unit_empty)
    tfs_empty = compute_text_fragmentation_signal(unit_empty)
    assert ris_empty == 0.0
    assert vds_empty == 0.0
    assert tfs_empty == 0.0
    print(f"  Empty unit signals: RIS={ris_empty}, VDS={vds_empty}, TFS={tfs_empty} OK")

    # Test compute_all_signals
    signals = compute_all_signals(unit_with_image)
    assert signals.RIS == 1.0
    print(f"  compute_all_signals OK")

    print("\n  ALL SIGNALS OK")
    return True


def test_gating_engine():
    """Test le GatingEngine."""
    print("\n" + "=" * 60)
    print("TEST 3: GatingEngine")
    print("=" * 60)

    from knowbase.extraction_v2.gating.engine import GatingEngine
    from knowbase.extraction_v2.models.elements import (
        BoundingBox,
        TextBlock,
        VisualElement,
    )
    from knowbase.extraction_v2.models.vision_unit import VisionUnit
    from knowbase.extraction_v2.models.gating import ExtractionAction

    engine = GatingEngine()
    print(f"  GatingEngine created with weights={engine.weights}")

    # Unit avec grande image -> VISION_REQUIRED
    large_image = VisualElement(
        kind="raster_image",
        bbox=BoundingBox(x=0.1, y=0.1, width=0.6, height=0.6, normalized=True),
        element_id="img_1",
    )
    unit_image = VisionUnit(
        id="PDF_PAGE_0",
        format="PDF",
        index=0,
        dimensions=(612, 792),
        blocks=[],
        visual_elements=[large_image],
    )
    decision = engine.gate(unit_image)
    assert decision.action == ExtractionAction.VISION_REQUIRED, \
        f"Expected VISION_REQUIRED, got {decision.action}"
    print(f"  Unit with large image: {decision.action.value} (VNS={decision.vision_need_score}) OK")

    # Unit vide -> NONE
    unit_empty = VisionUnit(
        id="PDF_PAGE_1",
        format="PDF",
        index=1,
        dimensions=(612, 792),
        blocks=[TextBlock(type="paragraph", text="Simple text paragraph.", level=0)],
    )
    decision_empty = engine.gate(unit_empty)
    assert decision_empty.action == ExtractionAction.NONE, \
        f"Expected NONE, got {decision_empty.action}"
    print(f"  Simple text unit: {decision_empty.action.value} (VNS={decision_empty.vision_need_score}) OK")

    # Test gate_document
    units = [unit_image, unit_empty]
    decisions = engine.gate_document(units)
    assert len(decisions) == 2
    print(f"  gate_document: {len(decisions)} decisions OK")

    # Test summary
    summary = engine.summary(decisions)
    assert summary["total_units"] == 2
    assert summary["vision_required"] == 1
    print(f"  summary: {summary} OK")

    print("\n  GATING ENGINE OK")
    return True


def test_merger_linearizer():
    """Test le Merger et Linearizer."""
    print("\n" + "=" * 60)
    print("TEST 4: Merger + Linearizer")
    print("=" * 60)

    from knowbase.extraction_v2.merge.merger import StructuredMerger
    from knowbase.extraction_v2.merge.linearizer import Linearizer
    from knowbase.extraction_v2.models.elements import TextBlock, TableData
    from knowbase.extraction_v2.models.vision_unit import VisionUnit
    from knowbase.extraction_v2.models.vision_output import (
        VisionElement,
        VisionRelation,
        VisionExtraction,
    )
    from knowbase.extraction_v2.models.gating import GatingDecision, ExtractionAction
    from knowbase.extraction_v2.models.signals import VisionSignals

    # Creer des units
    blocks = [
        TextBlock(type="heading", text="Architecture Overview", level=1),
        TextBlock(type="paragraph", text="This document describes the SAP architecture.", level=0),
    ]
    tables = [
        TableData(
            table_id="tbl_1",
            headers=["Component", "Role"],
            cells=[["SAP BTP", "Integration Platform"]],
            num_rows=2,
            num_cols=2,
            is_structured=True,
        )
    ]
    unit = VisionUnit(
        id="PDF_PAGE_0",
        format="PDF",
        index=0,
        dimensions=(612, 792),
        blocks=blocks,
        tables=tables,
        title="Architecture Overview",
    )

    # Creer une extraction Vision
    vision_extraction = VisionExtraction(
        kind="architecture_diagram",
        elements=[
            VisionElement(id="box_1", type="box", text="SAP BTP", confidence=0.9),
            VisionElement(id="box_2", type="box", text="Customer", confidence=0.85),
        ],
        relations=[
            VisionRelation(
                source_id="box_1",
                target_id="box_2",
                type="integrates_with",
                evidence="arrow",
                confidence=0.8,
            )
        ],
        page_index=0,
        confidence=0.87,
    )

    # Creer une decision de gating
    gating_decision = GatingDecision(
        index=0,
        unit_id="PDF_PAGE_0",
        action=ExtractionAction.VISION_REQUIRED,
        vision_need_score=0.75,
        signals=VisionSignals(RIS=1.0, VDS=0.0, TFS=0.0, SDS=0.0, VTS=0.0),
        reasons=["large raster image detected"],
    )

    # Test Merger
    merger = StructuredMerger()
    merged = merger.merge_page(unit, vision_extraction, gating_decision)

    assert merged.page_index == 0
    assert merged.has_vision
    assert len(merged.base_blocks) == 2
    assert len(merged.base_tables) == 1
    print(f"  Merger.merge_page: {len(merged.base_blocks)} blocks, vision={merged.has_vision} OK")

    # Test merge_document
    merged_pages = merger.merge_document(
        units=[unit],
        vision_extractions={0: vision_extraction},
        gating_decisions=[gating_decision],
    )
    assert len(merged_pages) == 1
    print(f"  Merger.merge_document: {len(merged_pages)} pages OK")

    # Test Linearizer
    linearizer = Linearizer()
    full_text, page_index = linearizer.linearize(merged_pages)

    assert "[PAGE 0" in full_text
    assert "[VISUAL_ENRICHMENT" in full_text
    assert "architecture_diagram" in full_text
    assert len(page_index) == 1
    print(f"  Linearizer.linearize: {len(full_text)} chars, {len(page_index)} pages OK")

    # Test linearize_page
    page_text = linearizer.linearize_page(merged_pages[0])
    assert "[PAGE 0" in page_text
    print(f"  Linearizer.linearize_page OK")

    # Test parse_marker
    marker_result = linearizer.parse_marker("[PAGE 0 | TYPE=ARCHITECTURE_DIAGRAM]")
    assert marker_result is not None
    assert marker_result[0] == "PAGE"
    print(f"  Linearizer.parse_marker OK")

    print("\n  MERGER + LINEARIZER OK")
    return True


def test_vision_prompts():
    """Test les prompts Vision."""
    print("\n" + "=" * 60)
    print("TEST 5: Vision Prompts")
    print("=" * 60)

    from knowbase.extraction_v2.vision.prompts import (
        VISION_SYSTEM_PROMPT,
        VISION_JSON_SCHEMA,
        build_vision_prompt,
        get_vision_messages,
    )
    from knowbase.extraction_v2.models.domain_context import SAP_VISION_CONTEXT

    # Test build_vision_prompt
    prompt = build_vision_prompt(
        domain_context=SAP_VISION_CONTEXT,
        local_snippets="Title: SAP Architecture Overview",
    )
    assert "SAP" in prompt
    assert "Title: SAP Architecture Overview" in prompt
    assert "diagram_type" in prompt
    print(f"  build_vision_prompt: {len(prompt)} chars OK")

    # Test get_vision_messages (sans image)
    try:
        get_vision_messages()
        assert False, "Should raise ValueError without image"
    except ValueError:
        pass
    print("  get_vision_messages validation OK")

    # Test avec image base64 mock
    messages = get_vision_messages(
        domain_context=SAP_VISION_CONTEXT,
        local_snippets="Test",
        image_base64="dGVzdA==",  # "test" en base64
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    print(f"  get_vision_messages: {len(messages)} messages OK")

    print("\n  VISION PROMPTS OK")
    return True


def test_pipeline_config():
    """Test la configuration du pipeline."""
    print("\n" + "=" * 60)
    print("TEST 6: Pipeline Configuration")
    print("=" * 60)

    from knowbase.extraction_v2.pipeline import (
        PipelineConfig,
        PipelineMetrics,
        ExtractionPipelineV2,
    )

    # Test PipelineConfig
    config = PipelineConfig(
        tenant_id="test_tenant",
        enable_vision=True,
        vision_budget=5,
    )
    config_dict = config.to_dict()
    assert config_dict["tenant_id"] == "test_tenant"
    assert config_dict["vision_budget"] == 5
    print(f"  PipelineConfig: {config_dict} OK")

    # Test PipelineMetrics
    metrics = PipelineMetrics(
        total_pages=10,
        vision_required_pages=3,
        vision_processed_pages=3,
        total_time_ms=1500.5,
    )
    metrics_dict = metrics.to_dict()
    assert metrics_dict["total_pages"] == 10
    assert metrics_dict["total_time_ms"] == 1500.5
    print(f"  PipelineMetrics: {metrics_dict} OK")

    # Test ExtractionPipelineV2 creation
    pipeline = ExtractionPipelineV2(config)
    assert pipeline.config.tenant_id == "test_tenant"
    assert not pipeline._initialized
    print(f"  ExtractionPipelineV2 created OK")

    print("\n  PIPELINE CONFIG OK")
    return True


def test_imports():
    """Test tous les imports du module principal."""
    print("\n" + "=" * 60)
    print("TEST 7: Module Imports")
    print("=" * 60)

    from knowbase.extraction_v2 import (
        # Pipeline
        ExtractionPipelineV2,
        PipelineConfig,
        extract_document,
        # Modeles
        BoundingBox,
        TextBlock,
        VisualElement,
        VisionUnit,
        VisionSignals,
        GatingDecision,
        ExtractionAction,
        VisionDomainContext,
        VisionExtraction,
        ExtractionResult,
        # Extracteurs
        DoclingExtractor,
        VDSFallback,
        # Gating
        GatingEngine,
        compute_all_signals,
        DEFAULT_GATING_WEIGHTS,
        # Vision
        VisionAnalyzer,
        build_vision_prompt,
        # Merge
        StructuredMerger,
        Linearizer,
    )

    print("  All main imports OK")

    # Verifier version
    from knowbase.extraction_v2 import __version__
    assert __version__ == "2.0.0"
    print(f"  Version: {__version__} OK")

    print("\n  ALL IMPORTS OK")
    return True


def main():
    """Execute tous les tests."""
    print("=" * 60)
    print("OSMOSE EXTRACTION V2 - TESTS COMPLETS")
    print("=" * 60)

    tests = [
        ("Modeles de donnees", test_models),
        ("Signaux Vision Gating", test_gating_signals),
        ("GatingEngine", test_gating_engine),
        ("Merger + Linearizer", test_merger_linearizer),
        ("Vision Prompts", test_vision_prompts),
        ("Pipeline Configuration", test_pipeline_config),
        ("Module Imports", test_imports),
    ]

    results = []
    for name, test_fn in tests:
        try:
            success = test_fn()
            results.append((name, success, None))
        except Exception as e:
            import traceback
            results.append((name, False, str(e)))
            traceback.print_exc()

    # Resume
    print("\n" + "=" * 60)
    print("RESUME DES TESTS")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, success, error in results:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {name}")
        if error:
            print(f"        Error: {error}")
        if success:
            passed += 1
        else:
            failed += 1

    print("\n" + "-" * 60)
    print(f"Total: {passed}/{len(results)} tests passed")

    if failed == 0:
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        return True
    else:
        print(f"\n{failed} test(s) failed")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
