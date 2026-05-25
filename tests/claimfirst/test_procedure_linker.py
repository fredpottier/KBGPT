"""Tests du pont Procedure ↔ Claims (P1.3, Phase B).

Mock l'extracteur v6 pour valider la logique de liaison (matching étape→claim,
STEP_OF, PREREQUISITE_OF, HAS_OUTCOME) de façon déterministe et offline.

Domain-agnostic : cas testés sur un exemple procédural neutre (SSO config).
"""

import pytest

from knowbase.claimfirst.models.claim import Claim, ClaimType
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import RelationType
from knowbase.claimfirst.v6.procedure_linker import ProcedureLinker
from knowbase.runtime_v6.schemas import Procedure, ProcedureStep


class _MockExtractor:
    """Retourne des procédures prédéfinies par section_id."""

    def __init__(self, by_section):
        self.by_section = by_section
        self.calls = []

    def extract_for_section(self, doc_id, section_id, section_title, section_text):
        self.calls.append(section_id)
        return self.by_section.get(section_id, [])


def _claim(cid, text, passage_id, ctype=ClaimType.PROCEDURAL):
    return Claim(
        claim_id=cid,
        tenant_id="default",
        doc_id="doc_001",
        text=text,
        claim_type=ctype,
        verbatim_quote=text,
        passage_id=passage_id,
    )


def _passage(pid, section_id, text, order=0):
    return Passage(
        passage_id=pid,
        tenant_id="default",
        doc_id="doc_001",
        text=text,
        section_id=section_id,
        reading_order_index=order,
    )


def _sso_procedure():
    return Procedure(
        procedure_id="proc_sso",
        name="Enable Single Sign-On",
        goal="Single sign-on is enabled for all users",
        steps=[
            ProcedureStep(step_number=1, action="Configure the identity provider"),
            ProcedureStep(step_number=2, action="Activate the SAML trust relationship"),
            ProcedureStep(step_number=3, action="Assign users to the application role"),
        ],
        prerequisites=["Administrator authorization required"],
        evidence_section_id="sec_sso",
    )


class TestProcedureLinker:
    def _setup(self):
        passages = [
            _passage("p1", "sec_sso",
                     "This section describes how to enable single sign-on for the "
                     "platform. To enable single sign-on, first configure the "
                     "identity provider with the correct metadata, then activate "
                     "the SAML trust relationship between the systems, and finally "
                     "assign users to the application role. Once all steps are "
                     "complete, single sign-on is enabled for all users of the "
                     "tenant and they can authenticate seamlessly.", order=0),
        ]
        claims = [
            _claim("c1", "Configure the identity provider for the tenant", "p1"),
            _claim("c2", "Activate the SAML trust relationship between systems", "p1"),
            _claim("c3", "Assign users to the application role to grant access", "p1"),
            _claim("c4", "Single sign-on is enabled for all users once complete", "p1"),
            # claim non-procédural ignoré
            _claim("c5", "SAML is an XML-based protocol", "p1", ctype=ClaimType.DEFINITIONAL),
        ]
        extractor = _MockExtractor({"sec_sso": [_sso_procedure()]})
        linker = ProcedureLinker(extractor, tenant_id="default")
        return linker, claims, passages

    def test_extractor_called_only_for_sections_with_procedural_claims(self):
        linker, claims, passages = self._setup()
        # ajouter une section sans claim procédural
        passages.append(_passage("p2", "sec_intro", "x" * 300, order=1))
        linker.link(claims, passages, doc_id="doc_001")
        assert linker.extractor.calls == ["sec_sso"]  # sec_intro ignorée

    def test_step_of_links_created(self):
        linker, claims, passages = self._setup()
        res = linker.link(claims, passages, doc_id="doc_001")
        assert len(res.procedures) == 1
        # 3 étapes → 3 STEP_OF
        assert res.stats["step_of_links"] == 3
        step_claim_ids = {cid for cid, _, _ in res.step_of_links}
        assert {"c1", "c2", "c3"} <= step_claim_ids

    def test_claims_mutated_with_procedure_metadata(self):
        linker, claims, passages = self._setup()
        linker.link(claims, passages, doc_id="doc_001")
        by_id = {c.claim_id: c for c in claims}
        assert by_id["c1"].procedure_id == "proc_sso"
        assert by_id["c1"].procedure_role == "STEP"
        assert by_id["c1"].step_index == 1
        assert by_id["c2"].step_index == 2
        assert by_id["c3"].step_index == 3
        # claim non-procédural intact
        assert by_id["c5"].procedure_id is None

    def test_prerequisite_chain(self):
        linker, claims, passages = self._setup()
        res = linker.link(claims, passages, doc_id="doc_001")
        # 3 étapes → 2 PREREQUISITE_OF consécutifs
        assert res.stats["prerequisite_of"] == 2
        for rel in res.prerequisite_relations:
            assert rel.relation_type == RelationType.PREREQUISITE_OF
        # ordre : step1 prereq step2, step2 prereq step3
        pairs = {(r.source_claim_id, r.target_claim_id) for r in res.prerequisite_relations}
        assert ("c1", "c2") in pairs
        assert ("c2", "c3") in pairs

    def test_has_outcome_link(self):
        linker, claims, passages = self._setup()
        res = linker.link(claims, passages, doc_id="doc_001")
        # c4 décrit le goal → HAS_OUTCOME
        assert res.stats["outcome_links"] == 1
        pid, cid = res.outcome_links[0]
        assert pid == "proc_sso"
        assert cid == "c4"
        by_id = {c.claim_id: c for c in claims}
        assert by_id["c4"].procedure_role == "OUTCOME"

    def test_no_procedural_claims_no_extraction(self):
        passages = [_passage("p1", "sec_x", "y" * 300)]
        claims = [_claim("c1", "SAML is a protocol", "p1", ctype=ClaimType.FACTUAL)]
        extractor = _MockExtractor({"sec_x": [_sso_procedure()]})
        linker = ProcedureLinker(extractor)
        res = linker.link(claims, passages, doc_id="doc_001")
        assert extractor.calls == []  # aucune section avec claim procédural
        assert res.stats["procedures_extracted"] == 0

    def test_unmatched_steps_skipped_gracefully(self):
        # étapes sans aucun recouvrement avec les claims → pas de STEP_OF, pas d'erreur
        passages = [_passage("p1", "sec_z",
                             "Totally unrelated content about quantum mechanics " * 5)]
        claims = [_claim("c1", "Quantum entanglement links two particles", "p1")]
        proc = Procedure(
            procedure_id="proc_z", name="Bake a cake", goal="A cake is baked",
            steps=[
                ProcedureStep(step_number=1, action="Preheat the oven to 180 degrees"),
                ProcedureStep(step_number=2, action="Mix flour sugar and eggs"),
            ],
            prerequisites=[], evidence_section_id="sec_z",
        )
        extractor = _MockExtractor({"sec_z": [proc]})
        linker = ProcedureLinker(extractor)
        res = linker.link(claims, passages, doc_id="doc_001")
        assert res.stats["procedures_extracted"] == 1
        assert res.stats["step_of_links"] == 0
        assert res.stats["prerequisite_of"] == 0
