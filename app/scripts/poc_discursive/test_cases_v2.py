"""
POC Discursive Relation Discrimination - Jeu de Cas v2 (calibre)

Objectif v2:
- Eliminer l'ambiguite "HAS_X" (exact vs possible)
- Tester explicitement quantificateurs/exceptions (DEFAULT vs ALWAYS)
- Garder le meme PDF source

ATTENTION: Code jetable, non destine a la production.
"""

from models import (
    TestCase, TestCaseCategory, Verdict,
    EvidenceBundle, ConceptBundle, Extract
)

PDF = "020_RISE_with_SAP_Cloud_ERP_Private_full.pdf"


# =============================================================================
# TYPE 1 (ACCEPT attendu) - Relations textuelles/discursives directes
# =============================================================================

TYPE1_CASES = [
    TestCase(
        id="TCv2-T1-01",
        description="WAF securise l'acces internet inbound (assertion explicite)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-01",
                text="Internet based access scenarios",
                source=PDF,
                section="p37"
            ),
            concept_a=ConceptBundle(
                name="Internet inbound access",
                extracts=[
                    Extract(
                        id="A1",
                        text="A Web Application Firewall (WAF) is used to secure the internet inbound access. Such an access is not turned on by default and customer would require to highlight this requirement as part of onboarding preparation.",
                        source=PDF,
                        section="p37"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Web Application Firewall (WAF)",
                extracts=[
                    Extract(
                        id="B1",
                        text="A Web Application Firewall (WAF) is used to secure the internet inbound access.",
                        source=PDF,
                        section="p37"
                    )
                ]
            ),
            proposed_relation="Internet inbound access IS_SECURED_BY WAF"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Lien explicitement affirme dans l'extrait; pas d'interpretation ni concept intermediaire."
    ),

    TestCase(
        id="TCv2-T1-02",
        description="Autoscaling IaaS non applicable dans le modele RISE (assertion explicite)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-02",
                text="Customer FAQ – Autoscaling",
                source=PDF,
                section="p221"
            ),
            concept_a=ConceptBundle(
                name="RISE model",
                extracts=[
                    Extract(
                        id="A1",
                        text="Autoscaling in the traditional Infrastructure as a Service (IaaS) sense is not applicable within the RISE model.",
                        source=PDF,
                        section="p221"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Traditional IaaS autoscaling",
                extracts=[
                    Extract(
                        id="B1",
                        text="Autoscaling in the traditional Infrastructure as a Service (IaaS) sense is not applicable within the RISE model.",
                        source=PDF,
                        section="p221"
                    )
                ]
            ),
            proposed_relation="RISE model DOES_NOT_SUPPORT Traditional IaaS autoscaling"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Phrase directe; aucune deduction necessaire."
    ),
]


# =============================================================================
# TYPE 2 (REJECT attendu) - Causalite / sur-generalisation / contradiction avec exception
# =============================================================================

TYPE2_CASES = [
    TestCase(
        id="TCv2-T2-01",
        description="EXCEPTION: Rejeter un 'ALWAYS' quand le texte contient 'unless'",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-03",
                text="Perimeter firewall controls in RISE",
                source=PDF,
                section="p217"
            ),
            concept_a=ConceptBundle(
                name="Connectivity to RISE",
                extracts=[
                    Extract(
                        id="A1",
                        text="It is important to note that all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=PDF,
                        section="p217"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Always internal and trusted",
                extracts=[
                    Extract(
                        id="B1",
                        text="all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=PDF,
                        section="p217"
                    )
                ]
            ),
            proposed_relation="RISE CONNECTIVITY IS_ALWAYS_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="La relation proposee est absolue (ALWAYS) mais l'extrait introduit une exception explicite (unless)."
    ),

    TestCase(
        id="TCv2-T2-02",
        description="Causalite non affirmee: Active-Active => SLA 99.7",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-04",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="Active-Active across two Availability Zones",
                extracts=[
                    Extract(
                        id="A1",
                        text="Application components such as Application Servers and Web Dispatchers are running Active-Active across the two Availability Zones (AZ) with Application Load Balancer (ALB) in front distributing traffic.",
                        source=PDF,
                        section="p114"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA\n99.7",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="Active-Active across AZ ENABLES PROD SLA 99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte juxtapose HA et SLA, mais n'affirme pas un lien causal/justificatif entre les deux."
    ),
]


# =============================================================================
# FRONTIER - Tests calibres pour alternatives et exceptions
# Ici on desambigue: EXACT vs POSSIBLE/DEFAULT
# =============================================================================

FRONTIER_CASES = [
    # ---- Alternatives: RTO ----
    TestCase(
        id="TCv2-FR-01",
        description="RTO: '12 HOURS or 4 HOURS (ENHANCED)' => CAN_HAVE_RTO 4h (doit etre ACCEPT)",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-05",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO\n12 HOURS or\n4 HOURS\n(ENHANCED)",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS (option)",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO\n12 HOURS or\n4 HOURS\n(ENHANCED)",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE CAN_HAVE_RTO 4 HOURS"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste explicitement 4 HOURS comme possibilite. 'CAN_HAVE' matche la modalite 'or'."
    ),

    TestCase(
        id="TCv2-FR-02",
        description="RTO: '12 HOURS or 4 HOURS (ENHANCED)' => HAS_EXACT_RTO 4h (doit etre ABSTAIN)",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-06",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO\n12 HOURS or\n4 HOURS\n(ENHANCED)",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS exact",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO\n12 HOURS or\n4 HOURS\n(ENHANCED)",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE HAS_EXACT_RTO 4 HOURS"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale="Le texte n'etablit pas la condition permettant d'affirmer 'exactement 4h'. Alternative explicite => ambiguite."
    ),

    # ---- Alternatives: RPO ----
    TestCase(
        id="TCv2-FR-03",
        description="RPO: '0 or 30 MINUTES' => CAN_HAVE_RPO 0 (doit etre ACCEPT)",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-07",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO\n0 or 30 MINUTES",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0 (option)",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO\n0 or 30 MINUTES",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE CAN_HAVE_RPO 0"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste 0 comme possibilite. 'CAN_HAVE' est fidele a 'or'."
    ),

    TestCase(
        id="TCv2-FR-04",
        description="RPO: '0 or 30 MINUTES' => HAS_EXACT_RPO 0 (doit etre ABSTAIN)",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-08",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO\n0 or 30 MINUTES",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0 exact",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO\n0 or 30 MINUTES",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE HAS_EXACT_RPO 0"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale="Le texte ne permet pas d'affirmer l'exactitude (0 vs 30). Alternative explicite => ambiguite."
    ),

    # ---- Exception: DEFAULT vs ALWAYS ----
    TestCase(
        id="TCv2-FR-05",
        description="EXCEPTION: accepter un DEFAULT quand le texte dit 'considered ... unless ...' (ACCEPT attendu)",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-09",
                text="Perimeter firewall controls in RISE",
                source=PDF,
                section="p217"
            ),
            concept_a=ConceptBundle(
                name="Connectivity to RISE",
                extracts=[
                    Extract(
                        id="A1",
                        text="It is important to note that all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=PDF,
                        section="p217"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Default internal and trusted",
                extracts=[
                    Extract(
                        id="B1",
                        text="all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=PDF,
                        section="p217"
                    )
                ]
            ),
            proposed_relation="RISE CONNECTIVITY IS_DEFAULT_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="La formulation 'considered ... unless ...' supporte une lecture 'par defaut'. Le predicat DEFAULT correspond au texte."
    ),

    # ---- Pont discursif rompu (cross-pages) ----
    TestCase(
        id="TCv2-FR-06",
        description="CDC Option vs SLA 99.7 (cross-pages sans pont) => ABSTAIN attendu",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-10",
                text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                source=PDF,
                section="p160"
            ),
            concept_a=ConceptBundle(
                name="CDC Option",
                extracts=[
                    Extract(
                        id="A1",
                        text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                        source=PDF,
                        section="p160"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA\n99.7",
                        source=PDF,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="CDC Option HAS_PROD_SLA 99.7"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale="Deux contextes (CDC option vs business continuity slide) sans pont textuel explicite. Referent rompu => ABSTAIN."
    ),
]


# =============================================================================
# SUITE COMPLETE
# =============================================================================

ALL_TEST_CASES = TYPE1_CASES + TYPE2_CASES + FRONTIER_CASES


def get_test_cases_by_category(category: TestCaseCategory) -> list[TestCase]:
    """Retourne les cas de test d'une categorie donnee."""
    return [tc for tc in ALL_TEST_CASES if tc.category == category]


def get_all_test_cases() -> list[TestCase]:
    """Retourne tous les cas de test."""
    return ALL_TEST_CASES


# Stats pour verification
if __name__ == "__main__":
    print("=== POC v2 - Jeu de test calibre ===")
    print(f"Type 1 (ACCEPT attendu): {len(TYPE1_CASES)} cas")
    print(f"Type 2 (REJECT attendu): {len(TYPE2_CASES)} cas")
    print(f"Frontieres: {len(FRONTIER_CASES)} cas")
    print(f"  - ACCEPT attendu: {sum(1 for tc in FRONTIER_CASES if tc.expected_verdict == Verdict.ACCEPT)}")
    print(f"  - ABSTAIN attendu: {sum(1 for tc in FRONTIER_CASES if tc.expected_verdict == Verdict.ABSTAIN)}")
    print(f"Total: {len(ALL_TEST_CASES)} cas")

    print("\n--- Detail des cas ---")
    for tc in ALL_TEST_CASES:
        print(f"  {tc.id}: [{tc.expected_verdict.value}] {tc.description[:55]}...")
