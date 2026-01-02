#!/usr/bin/env python3
"""
Test du Vision Gating v3.1 sur un PDF.
Usage: docker exec knowbase-app python scripts/test_vision_gating.py /data/test_joule.pdf
"""

import sys
sys.path.insert(0, '/app/src')

from pathlib import Path
import fitz  # PyMuPDF

from knowbase.ingestion.components.transformers.vision_gating import (
    gate_document,
    estimate_vision_savings,
    VisionDecision,
    profile_document,
)


def test_pdf_vision_gating(pdf_path: str):
    """Teste le vision gating v3.1 sur un PDF complet."""

    doc = fitz.open(pdf_path)
    print(f"PDF: {pdf_path}")
    print(f"Pages: {len(doc)}")
    print("=" * 120)

    # Pass 1: Profiling document
    print("\n[PASS 1] Profiling document...")
    profile = profile_document(doc)
    print(f"  Document class: {profile.doc_class}")
    print(f"  Template clusters: {len(profile.template_clusters)}")
    print(f"  Header limit: {profile.header_limit:.2f} (adaptatif)")
    print(f"  Footer limit: {profile.footer_limit:.2f} (adaptatif)")
    print(f"  Text threshold: {profile.text_threshold} chars")
    print(f"  Drawings threshold: {profile.drawings_count_threshold}")

    # Afficher les clusters template
    if profile.template_clusters:
        print(f"  Template clusters details:")
        for i, tc in enumerate(profile.template_clusters[:5]):  # Max 5
            freq = len(tc.pages) / profile.total_pages
            print(f"    [{i+1}] type={tc.element_type}, cx={tc.cx:.2f}, cy={tc.cy:.2f}, "
                  f"w={tc.w:.2f}, h={tc.h:.2f}, freq={freq:.1%}")

    print("\n[PASS 2] Page decisions...")
    print("=" * 120)
    print(f"{'Page':>4} | {'Decision':8} | {'Chars':>5} | {'Signal':>6} | {'NonTpl':>6} | {'ImgArea':>7} | {'DrawArea':>8} | Reason")
    print("-" * 120)

    # Pass 2: Gating complet
    results = gate_document(doc)

    for i, result in enumerate(results):
        icon = "VISION" if result.decision == VisionDecision.REQUIRED else (
            "SKIP" if result.decision == VisionDecision.SKIP else "OPT"
        )

        print(
            f"{i + 1:4d} | {icon:8s} | {result.chars:5d} | {result.visual_signal:6.2f} | "
            f"{result.non_template_cnt:6d} | {result.img_area:7.3f} | {result.draw_area:8.3f} | {result.reason[:35]}"
        )

    doc.close()

    # Stats globales avec document rechargé
    doc = fitz.open(pdf_path)
    stats = estimate_vision_savings(doc)
    doc.close()

    print("=" * 120)
    print(f"""
RESUME v3.1:
  Total pages:      {stats['total_pages']}
  Skip Vision:      {stats['skip']}
  Required Vision:  {stats['vision_required']}
  Optional:         {stats['optional']}

  Sans gating:      {stats['total_pages']} appels Vision (~${stats['estimated_cost_no_gating_usd']:.2f})
  Avec gating:      {stats['vision_required']} appels Vision (~${stats['estimated_cost_with_gating_usd']:.2f})
  Economie:         {stats['savings_percent']:.1f}% (~${stats['estimated_savings_usd']:.2f})
""")

    return stats


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_vision_gating.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    test_pdf_vision_gating(pdf_path)
