"""
Tests pour les modeles Pydantic du POC
"""

import pytest
from poc.models.schemas import (
    DependencyStructure,
    StructureJustification,
    Theme,
    ConceptSitue,
    ConceptRole,
    Information,
    InfoType,
    Anchor,
    MeaningSignature,
    DocumentStructure,
    QualityMetrics
)


class TestStructureJustification:
    """Tests pour la justification de structure"""

    def test_valid_justification(self):
        """Justification complete -> OK"""
        justif = StructureJustification(
            chosen=DependencyStructure.CENTRAL,
            justification="Ce document est centre sur SAP S/4HANA",
            rejected={
                "TRANSVERSAL": "Les assertions dependent de SAP",
                "CONTEXTUAL": "Pas de conditions recurrentes"
            }
        )

        assert justif.chosen == DependencyStructure.CENTRAL
        assert len(justif.rejected) == 2

    def test_missing_rejection(self):
        """Justification incomplete -> erreur"""
        with pytest.raises(ValueError):
            StructureJustification(
                chosen=DependencyStructure.CENTRAL,
                justification="Ce document est centre sur SAP S/4HANA",
                rejected={
                    "TRANSVERSAL": "Les assertions dependent de SAP"
                    # Missing CONTEXTUAL
                }
            )

    def test_short_rejection(self):
        """Justification trop courte -> erreur"""
        with pytest.raises(ValueError):
            StructureJustification(
                chosen=DependencyStructure.CENTRAL,
                justification="Ce document est centre sur SAP S/4HANA",
                rejected={
                    "TRANSVERSAL": "Trop court",  # < 10 chars
                    "CONTEXTUAL": "Pas assez de justification ici"
                }
            )


class TestTheme:
    """Tests pour les themes recursifs"""

    def test_theme_with_children(self):
        """Theme avec sous-themes"""
        theme = Theme(
            name="Conformite GDPR",
            children=[
                Theme(name="Droits des personnes"),
                Theme(name="Obligations du responsable")
            ]
        )

        assert theme.name == "Conformite GDPR"
        assert len(theme.children) == 2

    def test_nested_themes(self):
        """Themes imbriques"""
        theme = Theme(
            name="Niveau 1",
            children=[
                Theme(
                    name="Niveau 2",
                    children=[
                        Theme(name="Niveau 3")
                    ]
                )
            ]
        )

        assert theme.children[0].children[0].name == "Niveau 3"


class TestDocumentStructure:
    """Tests pour la structure document complete"""

    def test_frugality_validator(self):
        """Validateur frugalite integre"""
        # Plus de 60 concepts -> erreur
        concepts = [
            ConceptSitue(
                name=f"Concept_{i}",
                role=ConceptRole.STANDARD,
                theme_ref="Test"
            )
            for i in range(65)
        ]

        with pytest.raises(ValueError) as exc_info:
            DocumentStructure(
                doc_id="test",
                doc_title="Test Doc",
                source_path="/test.pdf",
                structure_decision=StructureJustification(
                    chosen=DependencyStructure.CENTRAL,
                    justification="Test justification here",
                    rejected={
                        "TRANSVERSAL": "Not applicable here",
                        "CONTEXTUAL": "Not applicable here"
                    }
                ),
                subject="Test Subject",
                themes=[],
                concepts=concepts,
                informations=[]
            )

        assert "FRUGALITY VIOLATION" in str(exc_info.value)

    def test_compute_metrics(self):
        """Calcul des metriques"""
        doc = DocumentStructure(
            doc_id="test",
            doc_title="Test Doc",
            source_path="/test.pdf",
            structure_decision=StructureJustification(
                chosen=DependencyStructure.TRANSVERSAL,
                justification="Knowledge is independent",
                rejected={
                    "CENTRAL": "No central artifact",
                    "CONTEXTUAL": "No recurring conditions"
                }
            ),
            subject="Test Subject",
            themes=[],
            concepts=[
                ConceptSitue(name="C1", role=ConceptRole.STANDARD, theme_ref="T1"),
                ConceptSitue(name="C2", role=ConceptRole.STANDARD, theme_ref="T1")
            ],
            informations=[
                Information(
                    info_type=InfoType.FACT,
                    anchor=Anchor(chunk_id="c1", start_char=0, end_char=50),
                    concept_refs=["C1"],
                    theme_ref="T1"
                )
            ] * 6  # 6 informations
        )

        doc.compute_metrics()

        assert doc.metrics.concept_count == 2
        assert doc.metrics.information_count == 6
        assert doc.metrics.info_per_concept_avg == 3.0


class TestAnchor:
    """Tests pour les anchors (pointeurs)"""

    def test_anchor_str(self):
        """Representation string"""
        anchor = Anchor(chunk_id="doc_chunk_001", start_char=100, end_char=250)
        assert str(anchor) == "doc_chunk_001:100-250"


class TestQualityMetrics:
    """Tests pour les metriques qualite"""

    def test_is_frugal_valid(self):
        """Frugalite valide"""
        metrics = QualityMetrics(concept_count=25)
        assert metrics.is_frugal is True

    def test_is_frugal_too_few(self):
        """Trop peu de concepts"""
        metrics = QualityMetrics(concept_count=3)
        assert metrics.is_frugal is False

    def test_is_frugal_too_many(self):
        """Trop de concepts"""
        metrics = QualityMetrics(concept_count=65)
        assert metrics.is_frugal is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
