"""
POC Discursive Relation Discrimination - Jeu de Cas de Test (PDF-backed)

Tous les extraits proviennent de:
020_RISE_with_SAP_Cloud_ERP_Private_full.pdf

ATTENTION: Code jetable, non destine a la production.
"""

from models import (
    TestCase, TestCaseCategory, Verdict,
    EvidenceBundle, ConceptBundle, Extract
)

PDF = "020_RISE_with_SAP_Cloud_ERP_Private_full.pdf"


# =============================================================================
# TYPE 1 (ACCEPT attendu) - Relations discursives deductibles du texte seul
# =============================================================================

TYPE1_CASES = [
    TestCase(
        id="TC-T1-01",
        description="PCE Business Continuity: PROD SLA 99.7 (referent explicite sur la slide)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-01",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112 (title)"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA Cloud, Private Edition",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                        source=PDF,
                        section="p112 (title)"
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
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            proposed_relation="SAP S/4HANA Cloud, Private Edition HAS_PROD_SLA 99.7"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale=(
            "Le referent (PCE) est dans le titre de la slide et le SLA 'PROD SLA 99.7' est liste sur la meme slide. "
            "Aucune transitivite ni connaissance externe n'est necessaire."
        )
    ),

    TestCase(
        id="TC-T1-02",
        description="Autoscaling: 'not applicable' dans le modele RISE (assertion explicite FAQ)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-02",
                text="Customer FAQ – Autoscaling",
                source=PDF,
                section="p221 (FAQ heading)"
            ),
            concept_a=ConceptBundle(
                name="RISE model",
                extracts=[
                    Extract(
                        id="A1",
                        text="Autoscaling in the traditional Infrastructure as a Service (IaaS) sense is not applicable within the RISE model.",
                        source=PDF,
                        section="p221 (FAQ – Autoscaling)"
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
                        section="p221 (FAQ – Autoscaling)"
                    )
                ]
            ),
            proposed_relation="RISE model DOES_NOT_SUPPORT Traditional IaaS autoscaling"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale=(
            "Le texte affirme explicitement l'inapplicabilite de l'autoscaling IaaS au modele RISE. "
            "Pas besoin d'inferer un mecanisme; c'est une phrase directe."
        )
    ),

    TestCase(
        id="TC-T1-03",
        description="Acces internet: WAF utilise et l'acces n'est pas active par defaut (assertion explicite)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-03",
                text="Internet based access scenarios",
                source=PDF,
                section="p37 (section heading)"
            ),
            concept_a=ConceptBundle(
                name="Internet inbound access",
                extracts=[
                    Extract(
                        id="A1",
                        text="A Web Application Firewall (WAF) is used to secure the internet inbound access. Such an access is not turned on by default and customer would require to highlight this requirement as part of onboarding preparation.",
                        source=PDF,
                        section="p37 (Internet based access scenarios)"
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
                        section="p37 (Internet based access scenarios)"
                    )
                ]
            ),
            proposed_relation="Internet inbound access IS_SECURED_BY WAF"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale=(
            "Le lien 'internet inbound access' -> 'WAF' est explicitement enonce. "
            "C'est une relation textuelle directe, sans transitivite."
        )
    ),

    TestCase(
        id="TC-T1-04",
        description="Coreference: 'this managed cloud service' renvoie a PCE mentionne dans le titre",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-04",
                text="SAP S/4HANA Cloud, Private Edition Overview",
                source=PDF,
                section="p5 (section title)"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA Cloud, Private Edition",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA Cloud, Private Edition is a managed cloud ERP offering that combines the power of SAP S/4HANA with the flexibility of cloud infrastructure.",
                        source=PDF,
                        section="p5 (Introduction)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Single-tenant architecture",
                extracts=[
                    Extract(
                        id="B1",
                        text="This managed cloud service provides customers with a dedicated, single-tenant environment, ensuring data isolation and customization capabilities.",
                        source=PDF,
                        section="p5 (Introduction, paragraph 2)"
                    )
                ]
            ),
            proposed_relation="SAP S/4HANA Cloud, Private Edition HAS Single-tenant architecture"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale=(
            "Le referent 'This managed cloud service' dans le paragraphe 2 renvoie clairement a "
            "'SAP S/4HANA Cloud, Private Edition' mentionne dans le paragraphe precedent. "
            "C'est une resolution de coreference discursive, sans concept intermediaire."
        )
    ),
]


# =============================================================================
# TYPE 2 (REJECT attendu) - Causalite/implication/transitivite non affirmee
# =============================================================================

TYPE2_CASES = [
    TestCase(
        id="TC-T2-01",
        description="Causalite non affirmee: 'Active-Active across AZ' => 'PROD SLA 99.7'",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-T2-01",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112 (title)"
            ),
            concept_a=ConceptBundle(
                name="Active-Active across Availability Zones",
                extracts=[
                    Extract(
                        id="A1",
                        text="Application components such as Application Servers and Web Dispatchers are running Active-Active across the two Availability Zones (AZ) with Application Load Balancer (ALB) in front distributing traffic.",
                        source=PDF,
                        section="p114 (HA/DR architecture bullets)"
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
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            proposed_relation="Active-Active across AZ ENABLES PROD SLA 99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale=(
            "Le texte decrit 'Active-Active' et liste 'PROD SLA 99.7', mais n'affirme jamais une causalite/implication "
            "entre les deux. Le lien propose est une deduction mecanistique (Type 2)."
        )
    ),

    TestCase(
        id="TC-T2-02",
        description="Transitivite masquee: 'Treats on-prem as trusted' + 'Internet optional' => 'RISE always internal/trusted'",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-T2-02",
                text="Perimeter firewall controls in RISE",
                source=PDF,
                section="p217 (FAQ heading)"
            ),
            concept_a=ConceptBundle(
                name="Treats customer on-premise systems as trusted",
                extracts=[
                    Extract(
                        id="A1",
                        text="RISE treats customer on-premise systems as trusted systems.",
                        source=PDF,
                        section="p217 (Perimeter firewall controls)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="All connectivity to RISE is considered internal and trusted",
                extracts=[
                    Extract(
                        id="B1",
                        text="It is important to note that all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=PDF,
                        section="p217 (Perimeter firewall controls)"
                    )
                ]
            ),
            proposed_relation="RISE CONNECTIVITY IS_ALWAYS_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale=(
            "Le texte inclut explicitement une exception ('unless the customer specifically requests... via the Internet'). "
            "La proposition 'always' est plus forte que ce qui est dit et ne peut pas etre justifiee par citation."
        )
    ),

    TestCase(
        id="TC-T2-03",
        description="Causalite non affirmee: 'Reserved Instances' => 'autoscaling possible'",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-T2-03",
                text="Customer FAQ – Autoscaling",
                source=PDF,
                section="p221 (FAQ heading)"
            ),
            concept_a=ConceptBundle(
                name="Reserved Instances",
                extracts=[
                    Extract(
                        id="A1",
                        text="As we handle predictable workloads for SAP S/4HANA applications, SAP utilizes Reserved Instances for customers throughout the duration of their contracts.",
                        source=PDF,
                        section="p221 (FAQ – Autoscaling)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Autoscaling",
                extracts=[
                    Extract(
                        id="B1",
                        text="Autoscaling in the traditional Infrastructure as a Service (IaaS) sense is not applicable within the RISE model.",
                        source=PDF,
                        section="p221 (FAQ – Autoscaling)"
                    )
                ]
            ),
            proposed_relation="Because Reserved Instances are used, RISE SUPPORTS Autoscaling"
        ),
        expected_verdict=Verdict.REJECT,
        rationale=(
            "Le texte dit explicitement que l'autoscaling IaaS n'est pas applicable. "
            "Relier 'Reserved Instances' a 'autoscaling support' est une conclusion causale non affirmee."
        )
    ),

    TestCase(
        id="TC-T2-04",
        description="Inference 'SLA 99.7 couvre end-to-end stack' (le texte mentionne end-to-end sans chiffrer 99.7 dans cette phrase)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-T2-04",
                text="Customer FAQ – Data Corruption",
                source=PDF,
                section="p218 (FAQ heading)"
            ),
            concept_a=ConceptBundle(
                name="End-to-end stack coverage",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP offers a comprehensive Service Level Agreement (SLA) that covers the end-to-end stack, including infrastructure, operating system, database, and application layers.",
                        source=PDF,
                        section="p218 (Data Corruption FAQ)"
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
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            proposed_relation="The end-to-end stack SLA IS 99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale=(
            "Le document dit qu'il existe un SLA couvrant l'end-to-end stack, et ailleurs il liste 'PROD SLA 99.7'. "
            "Mais il n'y a pas de citation qui identifie explicitement que CES DEUX elements sont le meme engagement. "
            "Le lien propose est une consolidation cross-extraits (non explicitee) -> Type 2."
        )
    ),

    TestCase(
        id="TC-T2-05",
        description="Connaissance externe: SAP HANA est la base de donnees de S/4HANA (evident mais non dit)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-T2-05",
                text="SAP S/4HANA Cloud, Private Edition Overview",
                source=PDF,
                section="p5 (title)"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA Cloud, Private Edition",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA Cloud, Private Edition is a managed cloud ERP offering that combines the power of SAP S/4HANA with the flexibility of cloud infrastructure.",
                        source=PDF,
                        section="p5 (Introduction)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP HANA Database",
                extracts=[
                    Extract(
                        id="B1",
                        text="The database layer is managed by SAP and benefits from automated backups and high availability configurations.",
                        source=PDF,
                        section="p114 (HA/DR architecture)"
                    )
                ]
            ),
            proposed_relation="SAP S/4HANA Cloud, Private Edition RUNS_ON SAP HANA Database"
        ),
        expected_verdict=Verdict.REJECT,
        rationale=(
            "Pour un expert SAP, le lien S/4HANA -> HANA est evident (c'est meme dans le nom). "
            "Mais les extraits fournis ne l'affirment pas explicitement. "
            "L'extrait B1 parle de 'database layer' sans nommer HANA. "
            "Tester si le LLM resiste a utiliser sa connaissance externe latente."
        )
    ),
]


# =============================================================================
# FRONTIER (ABSTAIN attendu majoritairement) - Ambiguites/alternatives/options
# Note: Pour TC-FR-04, REJECT est egalement acceptable (sur-affirmation)
# =============================================================================

FRONTIER_CASES = [
    TestCase(
        id="TC-FR-01",
        description="CDC option vs hyperscaler PCE: le SLA 99.7 s'applique-t-il aussi au CDC Option ?",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-01",
                text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                source=PDF,
                section="p160 (CDC option title)"
            ),
            concept_a=ConceptBundle(
                name="CDC Option",
                extracts=[
                    Extract(
                        id="A1",
                        text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                        source=PDF,
                        section="p160 (CDC option title)"
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
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            proposed_relation="CDC Option HAS_PROD_SLA 99.7"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale=(
            "Le document couvre plusieurs contextes (PCE sur hyperscaler + option CDC). "
            "On voit 'CDC Option ... backed by an SLA...' mais pas de pont textuel explicite qui attribue '99.7' au CDC Option. "
            "Referent potentiellement rompu -> ABSTAIN."
        )
    ),

    TestCase(
        id="TC-FR-02",
        description="RTO a deux valeurs possibles (12h ou 4h Enhanced) - ne pas trancher",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-02",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112 (title)"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO\n12 HOURS or\n4 HOURS\n(ENHANCED)",
                        source=PDF,
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO\n12 HOURS or\n4 HOURS\n(ENHANCED)",
                        source=PDF,
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            proposed_relation="PCE HAS_RTO 4 HOURS"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale=(
            "Le texte donne une alternative '12 HOURS or 4 HOURS (ENHANCED)'. "
            "Sans condition supplementaire, trancher sur 4h serait une sur-interpretation."
        )
    ),

    TestCase(
        id="TC-FR-03",
        description="RPO a deux valeurs possibles (0 ou 30 minutes) - ne pas trancher",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-03",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                source=PDF,
                section="p112 (title)"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO\n0 or 30 MINUTES",
                        source=PDF,
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO\n0 or 30 MINUTES",
                        source=PDF,
                        section="p112 (Business Continuity metrics)"
                    )
                ]
            ),
            proposed_relation="PCE HAS_RPO 0"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale=(
            "Le texte presente '0 or 30 MINUTES'. "
            "Sans autre contrainte, impossible d'affirmer la valeur exacte."
        )
    ),

    TestCase(
        id="TC-FR-04",
        description="Segmentation: 'we do not recommend' != 'not supported' (nuance normative)",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-04",
                text="Customer FAQ – Segmentation",
                source=PDF,
                section="p223 (FAQ heading)"
            ),
            concept_a=ConceptBundle(
                name="Database and applications on different subnets",
                extracts=[
                    Extract(
                        id="A1",
                        text="We can separate systems into distinct subnets and apply security group rules as needed. However, we do not recommend placing the database and applications on different subnets.",
                        source=PDF,
                        section="p223 (Segmentation FAQ)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Not supported",
                extracts=[
                    Extract(
                        id="B1",
                        text="we do not recommend placing the database and applications on different subnets.",
                        source=PDF,
                        section="p223 (Segmentation FAQ)"
                    )
                ]
            ),
            proposed_relation="Placing DB and App on different subnets IS_NOT_SUPPORTED"
        ),
        expected_verdict=Verdict.ABSTAIN,  # REJECT egalement acceptable
        rationale=(
            "Le texte exprime une recommandation ('do not recommend'), pas une interdiction explicite ('not supported'). "
            "Transformer 'not recommended' en 'not supported' est une sur-affirmation. "
            "ABSTAIN ou REJECT sont tous deux acceptables; classe FRONTIER car c'est un cas de nuance normative."
        )
    ),

    TestCase(
        id="TC-FR-05",
        description="Internet access: optionnel / sur demande - eviter de deduire une configuration standard",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-05",
                text="Perimeter firewall controls in RISE",
                source=PDF,
                section="p217 (FAQ heading)"
            ),
            concept_a=ConceptBundle(
                name="Internet access to RISE",
                extracts=[
                    Extract(
                        id="A1",
                        text="Internet access to RISE is optional and only enabled upon customer request.",
                        source=PDF,
                        section="p217 (Perimeter firewall controls)"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Secure Application Gateway with WAF",
                extracts=[
                    Extract(
                        id="B1",
                        text="In such cases, a Secure Application Gateway with Web Application Firewall (WAF) features is used to secure the network traffic coming from the Internet.",
                        source=PDF,
                        section="p217 (Perimeter firewall controls)"
                    )
                ]
            ),
            proposed_relation="RISE ALWAYS uses Secure Application Gateway with WAF"
        ),
        expected_verdict=Verdict.ABSTAIN,
        rationale=(
            "Le texte conditionne l'usage du Secure Application Gateway+WAF a l'ouverture Internet ('In such cases'). "
            "Sans dire si c'est standard ou non. L'assertion 'ALWAYS' force une generalisation -> ABSTAIN attendu."
        )
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
    print(f"Type 1 (ACCEPT attendu): {len(TYPE1_CASES)} cas")
    print(f"Type 2 (REJECT attendu): {len(TYPE2_CASES)} cas")
    print(f"Frontieres (ABSTAIN attendu majoritairement): {len(FRONTIER_CASES)} cas")
    print(f"Total: {len(ALL_TEST_CASES)} cas")

    print("\n--- Detail des cas ---")
    for tc in ALL_TEST_CASES:
        print(f"  {tc.id}: {tc.description[:60]}... [{tc.expected_verdict.value}]")
