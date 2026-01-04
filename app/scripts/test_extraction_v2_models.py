#!/usr/bin/env python3
"""
Test des modèles Extraction V2 - Phase 1.

Vérifie que tous les imports et fonctionnalités de base fonctionnent.
"""

import sys


def test_models():
    """Test tous les modèles Phase 1."""
    print("=" * 60)
    print("Test Extraction V2 - Phase 1 Models")
    print("=" * 60)

    # 1. Elements
    print("\n[1] Testing elements.py...")
    from knowbase.extraction_v2.models.elements import (
        BoundingBox,
        TextBlock,
        VisualElement,
        TableData,
    )

    bbox = BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4)
    assert bbox.area == 0.12, f"Expected 0.12, got {bbox.area}"
    assert bbox.center == (0.25, 0.4), f"Expected (0.25, 0.4), got {bbox.center}"
    print(f"  BoundingBox: area={bbox.area:.2f}, center={bbox.center}")

    block = TextBlock(type="paragraph", text="Hello world", level=0)
    assert block.char_count == 11
    assert block.is_short  # 11 < 200 = court
    print(f"  TextBlock: {block.type}, {block.char_count} chars")

    print("  ✅ elements.py OK")

    # 2. Signals
    print("\n[2] Testing signals.py...")
    from knowbase.extraction_v2.models.signals import VisionSignals

    signals = VisionSignals(RIS=0.8, VDS=0.5, TFS=0.3, SDS=0.2, VTS=0.1)
    print(f"  Signals: {signals}")

    weights = {"RIS": 0.30, "VDS": 0.30, "TFS": 0.15, "SDS": 0.15, "VTS": 0.10}
    vns = signals.compute_weighted_score(weights)
    expected_vns = 0.8*0.30 + 0.5*0.30 + 0.3*0.15 + 0.2*0.15 + 0.1*0.10
    assert abs(vns - expected_vns) < 0.001, f"Expected {expected_vns}, got {vns}"
    print(f"  VNS Score: {vns:.3f}")

    assert signals.has_mandatory_vision_trigger() == False  # RIS=0.8 < 1.0
    signals_trigger = VisionSignals(RIS=1.0, VDS=0.5)
    assert signals_trigger.has_mandatory_vision_trigger() == True
    print("  ✅ signals.py OK")

    # 3. Gating
    print("\n[3] Testing gating.py...")
    from knowbase.extraction_v2.models.gating import ExtractionAction, GatingDecision

    action = ExtractionAction.from_score(0.65)
    assert action == ExtractionAction.VISION_REQUIRED
    print(f"  VNS=0.65 -> {action.value}")

    action = ExtractionAction.from_score(0.45)
    assert action == ExtractionAction.VISION_RECOMMENDED
    print(f"  VNS=0.45 -> {action.value}")

    action = ExtractionAction.from_score(0.30)
    assert action == ExtractionAction.NONE
    print(f"  VNS=0.30 -> {action.value}")

    decision = GatingDecision(
        index=0,
        unit_id="PDF_PAGE_0",
        action=ExtractionAction.VISION_REQUIRED,
        vision_need_score=0.72,
        signals=signals,
    )
    print(f"  GatingDecision: {decision}")
    print("  ✅ gating.py OK")

    # 4. VisionUnit
    print("\n[4] Testing vision_unit.py...")
    from knowbase.extraction_v2.models.vision_unit import VisionUnit

    unit = VisionUnit(
        id="PDF_PAGE_0",
        format="PDF",
        index=0,
        dimensions=(612, 792),
        blocks=[block],
    )
    assert unit.text_blocks_count == 1
    assert unit.full_text == "Hello world"
    print(f"  VisionUnit: {unit}")
    print("  ✅ vision_unit.py OK")

    # 5. Domain Context
    print("\n[5] Testing domain_context.py...")
    from knowbase.extraction_v2.models.domain_context import (
        VisionDomainContext,
        SAP_VISION_CONTEXT,
    )

    context = VisionDomainContext.default()
    print(f"  Default context: {context}")

    prompt_section = SAP_VISION_CONTEXT.to_prompt_section()
    assert "SAP" in prompt_section
    print(f"  SAP context prompt section: {len(prompt_section)} chars")
    print("  ✅ domain_context.py OK")

    # 6. Vision Output
    print("\n[6] Testing vision_output.py...")
    from knowbase.extraction_v2.models.vision_output import (
        VisionElement,
        VisionRelation,
        VisionExtraction,
    )

    elem = VisionElement(id="box_1", type="box", text="SAP S/4HANA", confidence=0.95)
    print(f"  VisionElement: {elem.to_text_format()}")

    rel = VisionRelation(
        source_id="box_1",
        target_id="box_2",
        type="flows_to",
        evidence="arrow",
        confidence=0.9,
    )
    print(f"  VisionRelation: {rel}")

    extraction = VisionExtraction(
        kind="architecture_diagram",
        elements=[elem],
        relations=[rel],
        page_index=6,
        confidence=0.85,
    )
    vision_text = extraction.to_vision_text()
    assert "[VISUAL_ENRICHMENT" in vision_text
    assert "architecture_diagram" in vision_text
    print(f"  VisionExtraction vision_text: {len(vision_text)} chars")
    print("  ✅ vision_output.py OK")

    # 7. Extraction Result
    print("\n[7] Testing extraction_result.py...")
    from knowbase.extraction_v2.models.extraction_result import (
        ExtractionResult,
        PageIndex,
        DocumentStructure,
        PageOutput,
    )

    page_output = PageOutput(
        index=0,
        text_markdown="# Title\n\nParagraph",
        gating=decision,
    )
    structure = DocumentStructure(pages=[page_output])

    result = ExtractionResult(
        document_id="doc_001",
        source_path="/path/to/doc.pdf",
        file_type="pdf",
        full_text="[PAGE 0]\n# Title\n\nParagraph",
        structure=structure,
        page_index=[PageIndex(page_index=0, start_offset=0, end_offset=30)],
    )
    print(f"  ExtractionResult: {result}")
    print("  ✅ extraction_result.py OK")

    print("\n" + "=" * 60)
    print("✅ ALL PHASE 1 MODELS TESTS PASSED!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_models()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
