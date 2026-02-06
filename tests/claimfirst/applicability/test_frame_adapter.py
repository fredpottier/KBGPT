# tests/claimfirst/applicability/test_frame_adapter.py
"""Tests pour FrameAdapter (rétrocompatibilité)."""

import pytest

from knowbase.claimfirst.applicability.frame_adapter import FrameAdapter
from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    FrameField,
    FrameFieldConfidence,
)
from knowbase.claimfirst.models.document_context import DocumentContext


class TestFrameToObservations:
    """Tests pour frame_to_observations."""

    def setup_method(self):
        self.adapter = FrameAdapter()

    def test_basic_conversion(self):
        """Convertit un frame basique en observations."""
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="2023",
                    display_label="version",
                    evidence_unit_ids=["EU:0:0", "EU:0:1"],
                    confidence=FrameFieldConfidence.HIGH,
                ),
            ],
        )

        observations = self.adapter.frame_to_observations(frame)

        assert len(observations) == 1
        obs = observations[0]
        assert obs.axis_key == "release_id"
        assert obs.axis_display_name == "version"
        assert obs.values_extracted == ["2023"]
        assert obs.reliability == "explicit_text"

    def test_low_confidence_to_inferred(self):
        """Confiance LOW convertie en reliability 'inferred'."""
        frame = ApplicabilityFrame(
            doc_id="test",
            fields=[
                FrameField(
                    field_name="year",
                    value_normalized="2019",
                    evidence_unit_ids=["EU:0:0"],
                    confidence=FrameFieldConfidence.LOW,
                ),
            ],
        )

        observations = self.adapter.frame_to_observations(frame)

        assert observations[0].reliability == "inferred"

    def test_empty_frame(self):
        """Frame vide → observations vides."""
        frame = ApplicabilityFrame(doc_id="test", fields=[])
        observations = self.adapter.frame_to_observations(frame)
        assert len(observations) == 0


class TestFrameToAxes:
    """Tests pour frame_to_axes."""

    def setup_method(self):
        self.adapter = FrameAdapter()

    def test_creates_axes(self):
        """Crée des ApplicabilityAxis depuis le frame."""
        frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="2023",
                    display_label="version",
                    evidence_unit_ids=["EU:0:0"],
                    confidence=FrameFieldConfidence.HIGH,
                ),
            ],
        )

        axes = self.adapter.frame_to_axes(frame, "default", "test_doc")

        assert len(axes) == 1
        assert axes[0].axis_key == "release_id"
        assert "2023" in axes[0].known_values
        assert axes[0].tenant_id == "default"
        assert "test_doc" in axes[0].source_doc_ids

    def test_empty_frame_no_axes(self):
        """Frame vide → pas d'axes."""
        frame = ApplicabilityFrame(doc_id="test", fields=[])
        axes = self.adapter.frame_to_axes(frame, "default", "test_doc")
        assert len(axes) == 0


class TestUpdateDocumentContext:
    """Tests pour update_document_context."""

    def setup_method(self):
        self.adapter = FrameAdapter()

    def test_updates_axis_values(self):
        """Met à jour les axis_values du DocumentContext."""
        frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                    confidence=FrameFieldConfidence.HIGH,
                ),
                FrameField(
                    field_name="year",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:1"],
                    confidence=FrameFieldConfidence.MEDIUM,
                ),
            ],
        )

        doc_context = DocumentContext(
            doc_id="test_doc",
            tenant_id="default",
        )

        self.adapter.update_document_context(frame, doc_context)

        assert "release_id" in doc_context.axis_values
        assert doc_context.axis_values["release_id"]["scalar_value"] == "2023"
        assert "release_id" in doc_context.applicable_axes
        assert "year" in doc_context.applicable_axes

    def test_no_duplicate_axes(self):
        """N'ajoute pas de doublons dans applicable_axes."""
        frame = ApplicabilityFrame(
            doc_id="test_doc",
            fields=[
                FrameField(
                    field_name="release_id",
                    value_normalized="2023",
                    evidence_unit_ids=["EU:0:0"],
                ),
            ],
        )

        doc_context = DocumentContext(
            doc_id="test_doc",
            tenant_id="default",
            applicable_axes=["release_id"],
        )

        self.adapter.update_document_context(frame, doc_context)

        assert doc_context.applicable_axes.count("release_id") == 1
