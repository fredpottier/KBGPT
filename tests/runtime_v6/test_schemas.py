"""Tests domain-agnostiques pour V6 schemas.

Valide que les 5 archétypes + ConceptCard instancient correctement sur :
- SAP (technique)
- Legal (RGPD)
- Medical (asthme protocole)
- Aerospace (CS-25)

avec le MÊME code Pydantic. Charge la preuve de l'universalité.
"""
from __future__ import annotations

import pytest

from knowbase.runtime_v6.schemas import (
    AtomicFact,
    ConceptCard,
    ConceptCardFact,
    Constraint,
    NamedEntity,
    Procedure,
    ProcedureStep,
    Reference,
    SectionExtraction,
)


# ─── NamedEntity — 4 domaines, même schema ──────────────────────────────────


def test_named_entity_sap_transaction():
    ent = NamedEntity(
        canonical_name="CGSADM",
        aliases=["CGSADM transaction"],
        entity_kind="code",
        domain_type="SAP_TRANSACTION",
        description="Outil administration centrale EHS",
        evidence_section_id="sec_admin_tools_014",
    )
    assert ent.canonical_name == "CGSADM"
    assert ent.entity_kind == "code"
    assert ent.domain_type == "SAP_TRANSACTION"


def test_named_entity_legal_gdpr_article():
    ent = NamedEntity(
        canonical_name="Article 32",
        aliases=["GDPR Art. 32", "Art. 32 RGPD"],
        entity_kind="regulation",
        domain_type="GDPR_ARTICLE",
        description="Sécurité du traitement",
        evidence_section_id="sec_security_processing",
    )
    assert ent.entity_kind == "regulation"


def test_named_entity_medical_icd_code():
    ent = NamedEntity(
        canonical_name="ICD-10 J45",
        aliases=["J45", "Asthme (CIM-10)"],
        entity_kind="code",
        domain_type="ICD_CODE",
        description="Asthme bronchique",
        evidence_section_id="sec_diagnosis_classification",
    )
    assert ent.entity_kind == "code"


def test_named_entity_aerospace_standard():
    ent = NamedEntity(
        canonical_name="CS-25.105",
        aliases=["§25.105", "Take-off speeds"],
        entity_kind="standard",
        domain_type="EASA_CS25",
        description="Vitesses au décollage",
        evidence_section_id="sec_perf_25_b",
    )
    assert ent.entity_kind == "standard"


# ─── AtomicFact — 4 domaines, même schema ───────────────────────────────────


def test_atomic_fact_sap():
    fact = AtomicFact(
        subject="CGSADM",
        predicate="initializes",
        object="Expert cache",
        modality="asserted",
        evidence_section_id="sec_admin_tools",
        evidence_text="Use transaction CGSADM to initialize the Expert cache.",
    )
    assert fact.predicate == "initializes"


def test_atomic_fact_legal():
    fact = AtomicFact(
        subject="Article 32 GDPR",
        predicate="requires",
        object="encryption of personal data in transit",
        modality="asserted",
        evidence_section_id="sec_art_32",
        evidence_text="Personal data shall be encrypted during transmission.",
    )
    assert fact.predicate == "requires"


def test_atomic_fact_medical_negated():
    fact = AtomicFact(
        subject="Salbutamol",
        predicate="indicated_for",
        object="patients under 12 years",
        modality="negated",
        evidence_section_id="sec_contraindications",
        evidence_text="Salbutamol is contraindicated in patients younger than 12 years.",
    )
    assert fact.modality == "negated"


def test_atomic_fact_aerospace_conditional():
    fact = AtomicFact(
        subject="ETOPS-180",
        predicate="permits",
        object="180-minute single-engine flight",
        modality="conditional",
        evidence_section_id="sec_etops_chap_3",
        evidence_text="If certified ETOPS-180, the aircraft may operate up to 180 min from suitable airport on one engine.",
    )
    assert fact.modality == "conditional"


# ─── Procedure — 4 domaines ─────────────────────────────────────────────────


def test_procedure_sap():
    proc = Procedure(
        name="Initialize Expert cache",
        goal="Make the Expert cache available after rule changes",
        steps=[
            ProcedureStep(step_number=1, action="Open transaction CGSADM"),
            ProcedureStep(step_number=2, action="Navigate to Cache Administration menu"),
            ProcedureStep(step_number=3, action="Click Initialize button"),
        ],
        prerequisites=["Authorization C_SHES_VWS"],
        evidence_section_id="sec_admin_tools",
    )
    assert len(proc.steps) == 3
    assert proc.steps[0].step_number == 1


def test_procedure_medical():
    proc = Procedure(
        name="Treat acute asthma exacerbation",
        goal="Restore normal breathing in acute asthma attack",
        steps=[
            ProcedureStep(step_number=1, action="Administer salbutamol 5mg via nebulizer"),
            ProcedureStep(step_number=2, action="Monitor SpO2 every 5 minutes"),
            ProcedureStep(step_number=3, action="If no improvement at 20min, escalate to systemic corticosteroids"),
        ],
        prerequisites=["Patient ≥12 years old", "Established acute exacerbation"],
        evidence_section_id="sec_acute_management",
    )
    assert proc.prerequisites[0].startswith("Patient")


def test_procedure_legal():
    proc = Procedure(
        name="Notify personal data breach",
        goal="Comply with GDPR Article 33 notification obligation",
        steps=[
            ProcedureStep(step_number=1, action="Identify and document the breach"),
            ProcedureStep(step_number=2, action="Assess risk to data subjects"),
            ProcedureStep(step_number=3, action="Notify supervisory authority within 72 hours"),
            ProcedureStep(step_number=4, action="Notify data subjects if high risk"),
        ],
        evidence_section_id="sec_art_33",
    )
    assert len(proc.steps) == 4


# ─── Constraint — 4 domaines ────────────────────────────────────────────────


def test_constraint_sap_requirement():
    cstr = Constraint(
        constraint_type="requirement",
        statement="Requires authorization object P_RCF_POOL",
        applies_to=["E-Recruiting Manager scenario"],
        evidence_section_id="sec_authorizations_hr",
    )
    assert cstr.constraint_type == "requirement"


def test_constraint_legal_prohibition():
    cstr = Constraint(
        constraint_type="prohibition",
        statement="Processing of personal data revealing political opinions is prohibited",
        applies_to=["Article 9 GDPR"],
        evidence_section_id="sec_special_categories",
    )
    assert cstr.constraint_type == "prohibition"


def test_constraint_medical_exception():
    cstr = Constraint(
        constraint_type="exception",
        statement="Salbutamol may be used in patients < 12 years only under specialist supervision",
        applies_to=["Salbutamol", "Pediatric prescription"],
        evidence_section_id="sec_pediatric_use",
    )
    assert cstr.constraint_type == "exception"


def test_constraint_aerospace_condition():
    cstr = Constraint(
        constraint_type="condition",
        statement="ETOPS rules apply only to twin-engine aircraft on extended overwater routes",
        applies_to=["ETOPS-120", "ETOPS-180"],
        evidence_section_id="sec_etops_applicability",
    )
    assert cstr.constraint_type == "condition"


# ─── Reference — 4 domaines ─────────────────────────────────────────────────


def test_reference_sap_external_doc():
    ref = Reference(
        reference_text="see SAP Note 1061242",
        target_kind="external_document",
        evidence_section_id="sec_monitoring",
    )
    assert ref.target_kind == "external_document"
    assert ref.resolved_target is None  # not resolved yet


def test_reference_legal_internal():
    ref = Reference(
        reference_text="see Article 17 GDPR",
        target_kind="internal_section",
        evidence_section_id="sec_art_32",
    )
    assert ref.target_kind == "internal_section"


def test_reference_medical_standard():
    ref = Reference(
        reference_text="ATS Guidelines 2024 on Asthma Management",
        target_kind="standard",
        evidence_section_id="sec_acute_management",
    )
    assert ref.target_kind == "standard"


# ─── SectionExtraction — agrégat ────────────────────────────────────────────


def test_section_extraction_propagates_section_id():
    """Si LLM oublie evidence_section_id, propage automatiquement du parent."""
    extr = SectionExtraction(
        doc_id="doc_014_operations",
        section_id="sec_admin_tools",
        entities=[
            NamedEntity(
                canonical_name="CGSADM",
                entity_kind="code",
                evidence_section_id="",  # LLM oublie
            )
        ],
        facts=[
            AtomicFact(
                subject="CGSADM",
                predicate="initializes",
                object="Expert cache",
                evidence_section_id="sec_admin_tools",  # OK
                evidence_text="Use CGSADM to init cache.",
            )
        ],
    )
    assert extr.entities[0].evidence_section_id == "sec_admin_tools"  # propagated
    assert extr.facts[0].evidence_section_id == "sec_admin_tools"     # unchanged


# ─── ConceptCard — 4 domaines ───────────────────────────────────────────────


def test_concept_card_sap():
    card = ConceptCard(
        entity_id="ent_cgsadm_xxx",
        entity_canonical_name="CGSADM",
        summary=(
            "Transaction d'administration centrale SAP EHS pour la gestion "
            "combinée de WWI et Expert. Utilisée notamment pour initialiser "
            "le cache Expert après modification des règles."
        ),
        typical_usage="Après modification des règles Expert, ou après transport.",
        key_facts=[
            ConceptCardFact(
                statement="CGSADM initialise le cache Expert",
                evidence_section_id="sec_admin_tools",
            ),
            ConceptCardFact(
                statement="CGSADM centralise l'administration WWI et Expert",
                evidence_section_id="sec_admin_overview",
            ),
        ],
        related_entities=["WWI", "Expert server", "Expert cache"],
        contexts=["Post-transport", "Post-rule-change", "Initial installation"],
        source_section_ids=["sec_admin_tools", "sec_admin_overview"],
    )
    assert len(card.key_facts) == 2
    assert card.entity_canonical_name == "CGSADM"


def test_concept_card_medical():
    card = ConceptCard(
        entity_id="ent_salbutamol_xxx",
        entity_canonical_name="Salbutamol",
        summary=(
            "Bronchodilatateur β2-agoniste de courte durée d'action utilisé "
            "dans le traitement de l'asthme aigu et de la BPCO."
        ),
        typical_usage="Première ligne dans les exacerbations asthmatiques.",
        key_facts=[
            ConceptCardFact(
                statement="Salbutamol soulage le bronchospasme",
                evidence_section_id="sec_pharmacology",
            ),
        ],
        related_entities=["Asthme", "BPCO", "β2-agoniste"],
        contexts=["Crise aiguë asthme", "Exacerbation BPCO"],
        source_section_ids=["sec_pharmacology", "sec_acute_management"],
    )
    assert "Salbutamol" in card.entity_canonical_name
    assert len(card.related_entities) == 3


def test_concept_card_legal():
    card = ConceptCard(
        entity_id="ent_art_32_xxx",
        entity_canonical_name="GDPR Article 32",
        summary=(
            "Article du Règlement Général sur la Protection des Données "
            "imposant des mesures techniques et organisationnelles pour "
            "garantir la sécurité du traitement."
        ),
        key_facts=[
            ConceptCardFact(
                statement="Article 32 exige le chiffrement des données personnelles",
                evidence_section_id="sec_art_32_para_1",
            ),
        ],
        related_entities=["DPO", "Privacy by design", "Article 33", "Pseudonymisation"],
        source_section_ids=["sec_art_32_para_1", "sec_art_32_para_2"],
    )
    assert "GDPR" in card.entity_canonical_name
