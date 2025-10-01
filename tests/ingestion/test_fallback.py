"""
Tests Fallback Extraction Phase 0 Critere 6
"""
import pytest
import json
from unittest.mock import patch
from pathlib import Path
from knowbase.ingestion.pipelines.pptx_pipeline import create_fallback_chunks, ask_gpt_slide_analysis

class TestCreateFallbackChunks:
    def test_fallback_chunks_with_megaparse(self):
        chunks = create_fallback_chunks(
            text="Slide text", notes="Notes", megaparse_content="MegaParse content",
            slide_index=1, document_type="default", slide_prompt_id="test"
        )
        assert len(chunks) > 0
        assert chunks[0]["prompt_meta"]["extraction_status"] == "chunks_only_fallback"
        print(f"OK: {len(chunks)} fallback chunks")

    def test_fallback_chunks_empty(self):
        chunks = create_fallback_chunks(
            text="", notes="", megaparse_content="",
            slide_index=1, document_type="default", slide_prompt_id="test"
        )
        assert len(chunks) == 0
        print("OK: empty content gives 0 chunks")

class TestAskGptSlideAnalysisFallback:
    @patch('knowbase.ingestion.pipelines.pptx_pipeline.llm_router')
    def test_llm_success(self, mock_llm, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        mock_llm.complete.return_value = json.dumps([{
            "full_explanation": "LLM chunk",
            "meta": {"type": "concept"}
        }])
        chunks = ask_gpt_slide_analysis(
            img, "summary", 1, "test.pptx", "text", "notes", "megaparse", "default", "prompt", 2
        )
        assert len(chunks) > 0
        assert chunks[0]["prompt_meta"]["extraction_status"] == "unified_success"
        print(f"OK: LLM success {len(chunks)} chunks")

    @patch('knowbase.ingestion.pipelines.pptx_pipeline.llm_router')
    def test_llm_timeout_fallback(self, mock_llm, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake")
        mock_llm.complete.side_effect = Exception("Timeout")
        chunks = ask_gpt_slide_analysis(
            img, "summary", 1, "test.pptx", "text", "notes", "megaparse", "default", "prompt", 2
        )
        assert len(chunks) > 0
        assert chunks[0]["prompt_meta"]["extraction_status"] == "chunks_only_fallback"
        assert mock_llm.complete.call_count == 2
        print(f"OK: Fallback activated {len(chunks)} chunks")
