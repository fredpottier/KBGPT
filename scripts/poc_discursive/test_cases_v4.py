"""
POC Discursive Relation Discrimination - Jeu de Cas (40 tests) - basé sur 3 PDFs réels
Généré par ChatGPT pour comparaison

Sources (selon v2cache Docling):
- 020_RISE_with_SAP_Cloud_ERP_Private_full.pdf
- 010_SAP_S4HANA_Cloud_Private_Edition_2025_Conversion_Guide.pdf
- 017_SAP_S4HANA_2023_Operations_Guide.pdf

Objectif:
- Maximiser la variété (modalité, exceptions, alternatives, "not supported", "not applicable", prereqs)
- Garder des cas Type 2 "pièges" (causalité, transitivité, connaissance externe)
- Ajouter des frontières (EXACT vs OR, scope rompu multi-sujets, cross-pages sans pont)
"""

from models import (
    TestCase, TestCaseCategory, Verdict,
    EvidenceBundle, ConceptBundle, Extract
)

SRC_RISE = "020_RISE_with_SAP_Cloud_ERP_Private_full.pdf"
SRC_CONV = "010_SAP_S4HANA_Cloud_Private_Edition_2025_Conversion_Guide.pdf"
SRC_OPS  = "017_SAP_S4HANA_2023_Operations_Guide.pdf"

# =============================================================================
# TYPE 1 - CANONICAL (DOIT ETRE ACCEPT)
# =============================================================================

TYPE1_CASES = [

    # -------------------------
    # RISE / PCE (deck)
    # -------------------------

    TestCase(
        id="TC40-T1-01",
        description="Connectivity default internal & trusted (exception explicitly present -> DEFAULT ok)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-01",
                text="RISE with SAP: SAP Cloud ERP Private (presentation).",
                source=SRC_RISE,
                section="Cover (Page 0)"
            ),
            concept_a=ConceptBundle(
                name="RISE connectivity",
                extracts=[
                    Extract(
                        id="A1",
                        text="... all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Default trust model",
                extracts=[
                    Extract(
                        id="B1",
                        text="It is important to note that all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            proposed_relation="RISE CONNECTIVITY IS_DEFAULT_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="La phrase exprime explicitement un défaut ('considered internal and trusted') avec une exception ('unless...'). Un prédicat DEFAULT est discursive et vérifiable."
    ),

    TestCase(
        id="TC40-T1-02",
        description="Internet access optional and only enabled upon customer request",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-02",
                text="RISE with SAP connectivity guidance includes optional internet exposure.",
                source=SRC_RISE,
                section="Page 216"
            ),
            concept_a=ConceptBundle(
                name="RISE Internet access",
                extracts=[
                    Extract(
                        id="A1",
                        text="Internet access to RISE is optional and only enabled upon customer request.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Customer request condition",
                extracts=[
                    Extract(
                        id="B1",
                        text="... optional and only enabled upon customer request.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            proposed_relation="RISE INTERNET_ACCESS IS_OPTIONAL_AND_CUSTOMER_REQUESTED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Relation explicitement portée par une phrase normative: 'optional' + 'only enabled upon customer request'."
    ),

    TestCase(
        id="TC40-T1-03",
        description="If internet access requested, WAF gateway is used (conditional)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-03",
                text="RISE connectivity includes an explicit conditional security mechanism for Internet exposure.",
                source=SRC_RISE,
                section="Page 216"
            ),
            concept_a=ConceptBundle(
                name="RISE internet exposure request",
                extracts=[
                    Extract(
                        id="A1",
                        text="... unless the customer specifically requests to open RISE access via the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Secure Application Gateway with WAF",
                extracts=[
                    Extract(
                        id="B1",
                        text="In such cases, a Secure Application Gateway with Web Application Firewall (WAF) features is used to secure the network traffic coming from the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            proposed_relation="RISE INTERNET_EXPOSURE_REQUEST IMPLIES_WAF_GATEWAY_USED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte établit explicitement une condition locale ('In such cases') et la mesure associée. Ce n'est pas une causalité déduite: c'est une règle discursive."
    ),

    TestCase(
        id="TC40-T1-04",
        description="Autoscaling (IaaS sense) is not applicable within RISE model",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-04",
                text="Customer FAQ – Autoscaling (RISE).",
                source=SRC_RISE,
                section="Page 220"
            ),
            concept_a=ConceptBundle(
                name="RISE autoscaling",
                extracts=[
                    Extract(
                        id="A1",
                        text="Autoscaling in the traditional Infrastructure as a Service (IaaS) sense is not applicable within the RISE model.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Not applicable (IaaS autoscaling)",
                extracts=[
                    Extract(
                        id="B1",
                        text="... is not applicable within the RISE model.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            proposed_relation="RISE AUTOSCALING_IAAS_SENSE IS_NOT_APPLICABLE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Assertion explicite 'not applicable' dans une FAQ. Aucun raisonnement externe requis."
    ),

    TestCase(
        id="TC40-T1-05",
        description="RISE uses Reserved Instances throughout contract duration (statement in autoscaling FAQ)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-05",
                text="Customer FAQ – Autoscaling mentions Reserved Instances usage.",
                source=SRC_RISE,
                section="Page 220"
            ),
            concept_a=ConceptBundle(
                name="RISE contracts",
                extracts=[
                    Extract(
                        id="A1",
                        text="... SAP utilizes Reserved Instances for customers throughout the duration of their contracts.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Reserved Instances",
                extracts=[
                    Extract(
                        id="B1",
                        text="SAP utilizes Reserved Instances for customers throughout the duration of their contracts.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            proposed_relation="RISE CONTRACTS USE_RESERVED_INSTANCES"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Lien direct, explicite, local au texte."
    ),

    TestCase(
        id="TC40-T1-06",
        description="PCE Business Continuity lists PROD SLA 99.7",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-06",
                text="SAP S/4HANA Cloud, Private Edition – Business Continuity slide includes SLA figures.",
                source=SRC_RISE,
                section="Page 111"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA Cloud, Private Edition",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA 99.7",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE HAS_SLA_PROD 99.7"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le slide maintient un référent clair (PCE) et liste explicitement la valeur SLA."
    ),

    TestCase(
        id="TC40-T1-07",
        description="PCE Business Continuity lists NON-PROD SLA 95.0",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-07",
                text="Business Continuity slide lists both PROD and NON-PROD SLA.",
                source=SRC_RISE,
                section="Page 111"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA Cloud, Private Edition",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA Cloud, Private Edition – Business Continuity",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="NON-PROD SLA 95.0",
                extracts=[
                    Extract(
                        id="B1",
                        text="NON-PROD SLA 95.0",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE HAS_SLA_NONPROD 95.0"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Idem: valeur explicitement listée sous un référent PCE."
    ),

    TestCase(
        id="TC40-T1-08",
        description="PCE RTO alternatives are possible (modal CAN_HAVE) when text says '12 HOURS or 4 HOURS (ENHANCED)'",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-08",
                text="Business Continuity slide lists RTO alternatives.",
                source=SRC_RISE,
                section="Page 111"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE CAN_HAVE_RTO 4_HOURS"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte exprime une alternative ('or'). Le prédicat CAN_HAVE correspond: '4 HOURS' est une possibilité documentée."
    ),

    TestCase(
        id="TC40-T1-09",
        description="PCE RPO alternatives are possible (modal CAN_HAVE) when text says '0 or 30 MINUTES'",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-09",
                text="Business Continuity slide lists RPO alternatives.",
                source=SRC_RISE,
                section="Page 111"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO 0 or 30 MINUTES",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO 0 or 30 MINUTES",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE CAN_HAVE_RPO 0"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Même logique: alternative => CAN_HAVE acceptable."
    ),

    TestCase(
        id="TC40-T1-10",
        description="CDC option explicitly described as RISE with SAP Customer Data Center Option (no inference)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-10",
                text="Slide explicitly titled CDC Option.",
                source=SRC_RISE,
                section="Page 159"
            ),
            concept_a=ConceptBundle(
                name="RISE with SAP - Customer Data Center Option",
                extracts=[
                    Extract(
                        id="A1",
                        text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                        source=SRC_RISE,
                        section="Page 159"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Delivered on customer premises",
                extracts=[
                    Extract(
                        id="B1",
                        text="... delivered on customer premises ...",
                        source=SRC_RISE,
                        section="Page 159"
                    )
                ]
            ),
            proposed_relation="RISE CDC_OPTION IS_DELIVERED_ON_CUSTOMER_PREMISES"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte dit explicitement 'delivered on customer premises'. Pas d'inférence."
    ),

    TestCase(
        id="TC40-T1-11",
        description="Certain Azure peering statement 'can currently not be supported' (negative capability)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-11",
                text="Network / connectivity limitations are listed.",
                source=SRC_RISE,
                section="Page 131"
            ),
            concept_a=ConceptBundle(
                name="Azure VNET Peering",
                extracts=[
                    Extract(
                        id="A1",
                        text="VNET Peering on Azure can currently not be supported.",
                        source=SRC_RISE,
                        section="Page 131"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Not supported",
                extracts=[
                    Extract(
                        id="B1",
                        text="... can currently not be supported.",
                        source=SRC_RISE,
                        section="Page 131"
                    )
                ]
            ),
            proposed_relation="AZURE_VNET_PEERING IS_NOT_SUPPORTED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Négation explicite de capacité ('not be supported')."
    ),

    TestCase(
        id="TC40-T1-12",
        description="Autoscaling model can address scale-up requirements quickly (capability claim)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-12",
                text="Autoscaling FAQ includes a capability statement about scale-up.",
                source=SRC_RISE,
                section="Page 220"
            ),
            concept_a=ConceptBundle(
                name="RISE model",
                extracts=[
                    Extract(
                        id="A1",
                        text="However, the model is capable of addressing scale-up requirements quickly in the cloud.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Scale-up quickly",
                extracts=[
                    Extract(
                        id="B1",
                        text="... capable of addressing scale-up requirements quickly in the cloud.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            proposed_relation="RISE_MODEL CAN_ADDRESS_SCALE_UP_QUICKLY"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Assertion explicite de capacité, pas de causalité induite."
    ),

    # -------------------------
    # Conversion Guide 2025
    # -------------------------

    TestCase(
        id="TC40-T1-13",
        description="Readiness Check is recommended but not mandatory",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-01",
                text="Conversion Guide for SAP S/4HANA Cloud Private Edition 2025.",
                source=SRC_CONV,
                section="Page 0-5"
            ),
            concept_a=ConceptBundle(
                name="SAP Readiness Check",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP Readiness Check ...  Recommendation Although not mandatory, this tool is highly recommended.",
                        source=SRC_CONV,
                        section="Page 5"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Not mandatory (but recommended)",
                extracts=[
                    Extract(
                        id="B1",
                        text="Although not mandatory, this tool is highly recommended.",
                        source=SRC_CONV,
                        section="Page 5"
                    )
                ]
            ),
            proposed_relation="SAP_READINESS_CHECK IS_RECOMMENDED_NOT_MANDATORY"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte exprime explicitement 'not mandatory' + 'highly recommended'."
    ),

    TestCase(
        id="TC40-T1-14",
        description="Conversion assets: 'You require the following conversion assets' (explicit requirement framing)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-02",
                text="Section on required documents/tools/SAP notes.",
                source=SRC_CONV,
                section="2.1 (Page 6)"
            ),
            concept_a=ConceptBundle(
                name="Conversion project",
                extracts=[
                    Extract(
                        id="A1",
                        text="You require the following conversion assets to prepare and run a conversion project.",
                        source=SRC_CONV,
                        section="Page 6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Conversion assets",
                extracts=[
                    Extract(
                        id="B1",
                        text="You require the following conversion assets to prepare and run a conversion project.",
                        source=SRC_CONV,
                        section="Page 6"
                    )
                ]
            ),
            proposed_relation="CONVERSION_PROJECT REQUIRES_CONVERSION_ASSETS_LISTED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Formulation explicite d'une exigence ('You require...')."
    ),

    TestCase(
        id="TC40-T1-15",
        description="Maintenance Planner step is mandatory because SUM requires stack file",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-03",
                text="Planning section mentions mandatory stack file for SUM.",
                source=SRC_CONV,
                section="Page 12"
            ),
            concept_a=ConceptBundle(
                name="Maintenance Planner",
                extracts=[
                    Extract(
                        id="A1",
                        text="This step is mandatory, because the Software Update Manager requires the stack file for the conversion process.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Stack file for SUM",
                extracts=[
                    Extract(
                        id="B1",
                        text="... Software Update Manager requires the stack file for the conversion process.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            proposed_relation="MAINTENANCE_PLANNER_STEP IS_MANDATORY_FOR_SUM_STACK_FILE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Lien direct dans le texte: mandatory car SUM requires stack file."
    ),

    TestCase(
        id="TC40-T1-16",
        description="Maintenance Optimizer is not supported by S/4HANA Cloud Private Edition",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-04",
                text="Conversion planning section states replacement and non-support.",
                source=SRC_CONV,
                section="Page 12"
            ),
            concept_a=ConceptBundle(
                name="Maintenance Optimizer",
                extracts=[
                    Extract(
                        id="A1",
                        text="The Maintenance Planner has replaced the Maintenance Optimizer, which is not supported by SAP S/4HANA Cloud Private Edition.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Not supported",
                extracts=[
                    Extract(
                        id="B1",
                        text="... Maintenance Optimizer, which is not supported by SAP S/4HANA Cloud Private Edition.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            proposed_relation="MAINTENANCE_OPTIMIZER IS_NOT_SUPPORTED_BY_S4HANA_CLOUD_PCE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Phrase explicite 'not supported by ...'."
    ),

    TestCase(
        id="TC40-T1-17",
        description="Two SAP Fiori deployment options: embedded or standalone",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-05",
                text="Conversion guide describes SAP Fiori deployment options for PCE.",
                source=SRC_CONV,
                section="Page 28"
            ),
            concept_a=ConceptBundle(
                name="SAP Fiori deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="There are two possible deployment options for SAP Fiori for SAP S/4HANA Cloud Private Edition, the embedded or the standalone deployment option.",
                        source=SRC_CONV,
                        section="Page 28"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Embedded deployment option",
                extracts=[
                    Extract(
                        id="B1",
                        text="... the embedded or the standalone deployment option.",
                        source=SRC_CONV,
                        section="Page 28"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE_FIORI HAS_DEPLOYMENT_OPTION EMBEDDED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste explicitement l'option embedded parmi les deux options."
    ),

    TestCase(
        id="TC40-T1-18",
        description="If text says embedded or standalone, then standalone is also an available option",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-06",
                text="Same sentence expresses both options.",
                source=SRC_CONV,
                section="Page 28"
            ),
            concept_a=ConceptBundle(
                name="SAP Fiori deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="... two possible deployment options ... embedded or the standalone deployment option.",
                        source=SRC_CONV,
                        section="Page 28"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Standalone deployment option",
                extracts=[
                    Extract(
                        id="B1",
                        text="... embedded or the standalone deployment option.",
                        source=SRC_CONV,
                        section="Page 28"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE_FIORI HAS_DEPLOYMENT_OPTION STANDALONE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Idem: option explicitement listée."
    ),

    TestCase(
        id="TC40-T1-19",
        description="Sequence planning: must consider entire system group regarding sequence of conversions",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-07",
                text="Planning baseline about system landscape sequencing.",
                source=SRC_CONV,
                section="Page 12"
            ),
            concept_a=ConceptBundle(
                name="System group conversion sequence",
                extracts=[
                    Extract(
                        id="A1",
                        text="... you must consider the entire system group regarding the sequence of conversions.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Must consider entire system group",
                extracts=[
                    Extract(
                        id="B1",
                        text="you must consider the entire system group regarding the sequence of conversions.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            proposed_relation="CONVERSION_PLANNING REQUIRES_CONSIDERING_ENTIRE_SYSTEM_GROUP_SEQUENCE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte utilise 'must' + obligation explicite."
    ),

    # -------------------------
    # Operations Guide 2023/2025
    # -------------------------

    TestCase(
        id="TC40-T1-20",
        description="Operations guide does not replace daily operations handbook; handbook is recommended to create",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-01",
                text="Operations Guide for SAP S/4HANA and SAP S/4HANA Cloud Private Edition.",
                source=SRC_OPS,
                section="Page 0-5"
            ),
            concept_a=ConceptBundle(
                name="Daily operations handbook",
                extracts=[
                    Extract(
                        id="A1",
                        text="This guide does not replace the daily operations handbook that we recommend you to create for your specific production operations.",
                        source=SRC_OPS,
                        section="Page 5"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Recommended to create",
                extracts=[
                    Extract(
                        id="B1",
                        text="... we recommend you to create for your specific production operations.",
                        source=SRC_OPS,
                        section="Page 5"
                    )
                ]
            ),
            proposed_relation="DAILY_OPERATIONS_HANDBOOK IS_RECOMMENDED_TO_CREATE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Recommandation explicite, localisée."
    ),

    TestCase(
        id="TC40-T1-21",
        description="New installation needs to run on SAP HANA database",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-02",
                text="Landscape example: new installation prerequisites.",
                source=SRC_OPS,
                section="Page 6"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA new installation",
                extracts=[
                    Extract(
                        id="A1",
                        text="A new installation of SAP S/4HANA needs to run on the SAP HANA database.",
                        source=SRC_OPS,
                        section="Page 6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP HANA database",
                extracts=[
                    Extract(
                        id="B1",
                        text="... needs to run on the SAP HANA database.",
                        source=SRC_OPS,
                        section="Page 6"
                    )
                ]
            ),
            proposed_relation="S4HANA_NEW_INSTALLATION REQUIRES_SAP_HANA_DATABASE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Exigence explicite: 'needs to run on'."
    ),

    TestCase(
        id="TC40-T1-22",
        description="Solution Manager recommended (not required) in landscape example",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-03",
                text="Landscape example mentions recommendation for Solution Manager.",
                source=SRC_OPS,
                section="Page 6"
            ),
            concept_a=ConceptBundle(
                name="SAP Solution Manager",
                extracts=[
                    Extract(
                        id="A1",
                        text="It is recommended to use the SAP Solution Manager, which can run on any database.",
                        source=SRC_OPS,
                        section="Page 6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Recommended",
                extracts=[
                    Extract(
                        id="B1",
                        text="It is recommended to use the SAP Solution Manager...",
                        source=SRC_OPS,
                        section="Page 6"
                    )
                ]
            ),
            proposed_relation="S4HANA_LANDSCAPE RECOMMENDS_SAP_SOLUTION_MANAGER"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Formulation explicite 'recommended'."
    ),

    TestCase(
        id="TC40-T1-23",
        description="Output control uses bgRFC; without bgRFC configuration no output can be performed (hard dependency)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-04",
                text="Output Management prerequisites.",
                source=SRC_OPS,
                section="Page 10"
            ),
            concept_a=ConceptBundle(
                name="Output control",
                extracts=[
                    Extract(
                        id="A1",
                        text="Output control uses a bgRFC to process output. Therefore, you need to maintain the bgRFC configuration. Otherwise, no output can be performed.",
                        source=SRC_OPS,
                        section="Page 10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="bgRFC configuration",
                extracts=[
                    Extract(
                        id="B1",
                        text="... you need to maintain the bgRFC configuration. Otherwise, no output can be performed.",
                        source=SRC_OPS,
                        section="Page 10"
                    )
                ]
            ),
            proposed_relation="OUTPUT_CONTROL REQUIRES_BGRFC_CONFIGURATION"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Dépendance explicitée ('Therefore' + 'Otherwise'). Ce n'est pas une causalité implicite, c'est une règle du texte."
    ),

    TestCase(
        id="TC40-T1-24",
        description="bgRFC doesn't work without supervisor destination (explicit requirement)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-05",
                text="bgRFC configuration instructions.",
                source=SRC_OPS,
                section="Page 10"
            ),
            concept_a=ConceptBundle(
                name="bgRFC",
                extracts=[
                    Extract(
                        id="A1",
                        text="One of the most important steps is defining a supervisor destination, as bgRFC doesn't work without it.",
                        source=SRC_OPS,
                        section="Page 10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Supervisor destination",
                extracts=[
                    Extract(
                        id="B1",
                        text="... defining a supervisor destination, as bgRFC doesn't work without it.",
                        source=SRC_OPS,
                        section="Page 10"
                    )
                ]
            ),
            proposed_relation="BGRFC REQUIRES_SUPERVISOR_DESTINATION"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Exigence explicite 'doesn't work without it'."
    ),
]


# =============================================================================
# TYPE 2 - CANONICAL (DOIT ETRE REJETÉ)
# =============================================================================

TYPE2_CASES = [

    # -------------------------
    # RISE / PCE (deck) - pièges
    # -------------------------

    TestCase(
        id="TC40-T2-01",
        description="ALWAYS vs unless (should reject absolute quantifier)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-01",
                text="Connectivity statement includes an explicit exception.",
                source=SRC_RISE,
                section="Page 216"
            ),
            concept_a=ConceptBundle(
                name="RISE connectivity",
                extracts=[
                    Extract(
                        id="A1",
                        text="... all connectivity to RISE is considered internal and trusted unless the customer specifically requests ... via the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Always internal and trusted",
                extracts=[
                    Extract(
                        id="B1",
                        text="... considered internal and trusted unless ...",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            proposed_relation="RISE CONNECTIVITY IS_ALWAYS_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le prédicat 'ALWAYS' contredit l'exception ('unless'). C'est précisément un Type 2: sur-généralisation."
    ),

    TestCase(
        id="TC40-T2-02",
        description="Causal leap: WAF implies internal trust (not stated)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-02",
                text="Text says WAF used when internet exposure is requested.",
                source=SRC_RISE,
                section="Page 216"
            ),
            concept_a=ConceptBundle(
                name="WAF Gateway usage",
                extracts=[
                    Extract(
                        id="A1",
                        text="In such cases, a Secure Application Gateway with Web Application Firewall (WAF) features is used to secure the network traffic coming from the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Internal & trusted",
                extracts=[
                    Extract(
                        id="B1",
                        text="... connectivity ... considered internal and trusted unless ... open RISE access via the Internet.",
                        source=SRC_RISE,
                        section="Page 216"
                    )
                ]
            ),
            proposed_relation="WAF_GATEWAY CAUSES_INTERNAL_TRUST_MODEL"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte n'affirme aucune causalité 'WAF => internal trust'. Il décrit une mesure de sécurisation en cas d'accès Internet. Causalité non affirmée."
    ),

    TestCase(
        id="TC40-T2-03",
        description="Transitive inference: Reserved Instances => 99.7% SLA (not stated)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-03",
                text="Autoscaling FAQ mentions Reserved Instances; Business Continuity slide mentions SLA 99.7.",
                source=SRC_RISE,
                section="Pages 220 & 111"
            ),
            concept_a=ConceptBundle(
                name="Reserved Instances",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP utilizes Reserved Instances for customers throughout the duration of their contracts.",
                        source=SRC_RISE,
                        section="Page 220"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA 99.7",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="RESERVED_INSTANCES ENABLE_SLA_99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Lien compositionnel/transitif non présent dans le texte: aucune phrase ne relie Reserved Instances à la SLA 99.7."
    ),

    TestCase(
        id="TC40-T2-04",
        description="Cross-topic: Active-Active VPN implies SLA 99.7 (not stated)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-04",
                text="Active-Active VPN appears in IPSEC design patterns; SLA appears in Business Continuity slide.",
                source=SRC_RISE,
                section="Pages 42-43 & 111"
            ),
            concept_a=ConceptBundle(
                name="Active-Active AWS VPN",
                extracts=[
                    Extract(
                        id="A1",
                        text="... Active-Active AWS VPN ...",
                        source=SRC_RISE,
                        section="Page 42"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA 99.7",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="ACTIVE_ACTIVE_VPN CAUSES_SLA_99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Causalité et lien direct non affirmés; nécessite des concepts intermédiaires (HA architecture) et/ou connaissance externe."
    ),

    TestCase(
        id="TC40-T2-05",
        description="CDC option implies customer data sovereignty requirements (not directly asserted as implication)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-05",
                text="CDC slide lists multiple motivations as bullets (not a logical implication).",
                source=SRC_RISE,
                section="Page 159"
            ),
            concept_a=ConceptBundle(
                name="CDC Option",
                extracts=[
                    Extract(
                        id="A1",
                        text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                        source=SRC_RISE,
                        section="Page 159"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Data sovereignty requirement",
                extracts=[
                    Extract(
                        id="B1",
                        text="Customer data sovereignty, privacy, and residency requirements",
                        source=SRC_RISE,
                        section="Page 159"
                    )
                ]
            ),
            proposed_relation="DATA_SOVEREIGNTY_REQUIREMENT IMPLIES_CDC_OPTION"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte liste des motivations/points, mais ne dit pas 'if data sovereignty then choose CDC'. Implication logique déduite."
    ),

    # -------------------------
    # Conversion Guide - pièges
    # -------------------------

    TestCase(
        id="TC40-T2-06",
        description="External knowledge: SUM applies to every conversion project (not asserted as universal)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-01",
                text="Guide references SUM contextually; universal requirement not proven by single excerpt.",
                source=SRC_CONV,
                section="Pages 5-12"
            ),
            concept_a=ConceptBundle(
                name="Conversion project",
                extracts=[
                    Extract(
                        id="A1",
                        text="You require the following conversion assets to prepare and run a conversion project.",
                        source=SRC_CONV,
                        section="Page 6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Software Update Manager (SUM)",
                extracts=[
                    Extract(
                        id="B1",
                        text="... Software Update Manager requires the stack file for the conversion process.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            proposed_relation="EVERY_CONVERSION_PROJECT REQUIRES_SUM"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte ne dit pas 'every conversion project requires SUM' de façon universelle; on ne doit pas sur-généraliser."
    ),

    TestCase(
        id="TC40-T2-07",
        description="Causal jump: Readiness Check causes add-on compatibility (it 'analyzes', not 'causes')",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-02",
                text="Readiness Check description lists what it analyzes.",
                source=SRC_CONV,
                section="Page 5"
            ),
            concept_a=ConceptBundle(
                name="SAP Readiness Check",
                extracts=[
                    Extract(
                        id="A1",
                        text="This tool analyzes your SAP ERP 6.0 system and highlights ... add-on compatibility ...",
                        source=SRC_CONV,
                        section="Page 5"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Add-on compatibility",
                extracts=[
                    Extract(
                        id="B1",
                        text="... highlights ... add-on compatibility ...",
                        source=SRC_CONV,
                        section="Page 5"
                    )
                ]
            ),
            proposed_relation="SAP_READINESS_CHECK CAUSES_ADDON_COMPATIBILITY"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'analyzes/highlights', pas 'causes'. Causalité inventée."
    ),

    TestCase(
        id="TC40-T2-08",
        description="Transitive: Maintenance Optimizer not supported => therefore SUM requires stack file (wrong direction)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-03",
                text="Page includes two separate statements about SUM stack file and optimizer replacement.",
                source=SRC_CONV,
                section="Page 12"
            ),
            concept_a=ConceptBundle(
                name="Maintenance Optimizer not supported",
                extracts=[
                    Extract(
                        id="A1",
                        text="... Maintenance Optimizer, which is not supported by SAP S/4HANA Cloud Private Edition.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SUM stack file requirement",
                extracts=[
                    Extract(
                        id="B1",
                        text="... Software Update Manager requires the stack file for the conversion process.",
                        source=SRC_CONV,
                        section="Page 12"
                    )
                ]
            ),
            proposed_relation="MAINTENANCE_OPTIMIZER_NOT_SUPPORTED CAUSES_SUM_STACKFILE_REQUIREMENT"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Aucune causalité exprimée entre ces deux phrases; ce sont deux informations adjacentes."
    ),

    # -------------------------
    # Operations Guide - pièges
    # -------------------------

    TestCase(
        id="TC40-T2-09",
        description="Causal jump: Using Solution Manager causes S/4HANA to run on HANA (wrong causality)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-01",
                text="Page 6: 'needs to run on HANA' and 'recommended to use Solution Manager' are separate statements.",
                source=SRC_OPS,
                section="Page 6"
            ),
            concept_a=ConceptBundle(
                name="SAP Solution Manager",
                extracts=[
                    Extract(
                        id="A1",
                        text="It is recommended to use the SAP Solution Manager...",
                        source=SRC_OPS,
                        section="Page 6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Runs on SAP HANA database",
                extracts=[
                    Extract(
                        id="B1",
                        text="A new installation of SAP S/4HANA needs to run on the SAP HANA database.",
                        source=SRC_OPS,
                        section="Page 6"
                    )
                ]
            ),
            proposed_relation="USING_SOLUTION_MANAGER CAUSES_S4HANA_RUNS_ON_HANA"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte n'établit aucune causalité entre Solution Manager et la DB HANA; ce sont deux faits distincts."
    ),

    TestCase(
        id="TC40-T2-10",
        description="Transitive/overreach: because bgRFC required, therefore Adobe Document Services required (not stated as implication)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-02",
                text="Prerequisites list multiple items; no implication chain between them.",
                source=SRC_OPS,
                section="Page 10"
            ),
            concept_a=ConceptBundle(
                name="bgRFC requirement",
                extracts=[
                    Extract(
                        id="A1",
                        text="Output control uses a bgRFC ... Otherwise, no output can be performed.",
                        source=SRC_OPS,
                        section="Page 10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Adobe Document Services availability",
                extracts=[
                    Extract(
                        id="B1",
                        text="Adobe Document Services is available (when using Adobe Forms)",
                        source=SRC_OPS,
                        section="Page 10"
                    )
                ]
            ),
            proposed_relation="BGRFC_REQUIREMENT IMPLIES_ADOBE_DOCUMENT_SERVICES_REQUIRED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="La liste de prérequis ne fournit pas une implication logique bgRFC -> ADS; implication inventée."
    ),
]


# =============================================================================
# FRONTIER - CAS FRONTIERE (souvent ABSTAIN / ou REJECT conservateur)
# =============================================================================

FRONTIER_CASES = [

    # -------------------------
    # RISE / PCE frontières
    # -------------------------

    TestCase(
        id="TC40-FR-01",
        description="EXACT RTO 4 hours (should not be asserted because text says '12 HOURS or 4 HOURS')",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-RISE-01",
                text="Business Continuity shows multiple RTO values (alternatives).",
                source=SRC_RISE,
                section="Page 111"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS (exact)",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE HAS_EXACT_RTO 4_HOURS"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Avec 'or', on ne peut pas affirmer une valeur EXACTE sans condition de sélection. REJECT conservateur (ou ABSTAIN) attendu."
    ),

    TestCase(
        id="TC40-FR-02",
        description="EXACT RPO 0 (should not be asserted because text says '0 or 30 MINUTES')",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-RISE-02",
                text="Business Continuity shows multiple RPO values (alternatives).",
                source=SRC_RISE,
                section="Page 111"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO 0 or 30 MINUTES",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0 (exact)",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO 0 or 30 MINUTES",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE HAS_EXACT_RPO 0"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Même logique: alternative => EXACT invalide (REJECT/ABSTAIN attendu)."
    ),

    TestCase(
        id="TC40-FR-03",
        description="Cross-pages without explicit bridge: SLA 99.7 on page 111 vs architecture 99.7 on page 114 (no explicit 'this architecture provides SLA')",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-RISE-03",
                text="Two different slides mention 99.7 but without an explicit linking statement.",
                source=SRC_RISE,
                section="Pages 111 & 114"
            ),
            concept_a=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="A1",
                        text="PROD SLA 99.7",
                        source=SRC_RISE,
                        section="Page 111"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Architecture for 99.7 Multi-AZ + LDDR",
                extracts=[
                    Extract(
                        id="B1",
                        text="Architecture for 99.7 Multi-AZ + LDDR ... This depicts the architecture for 99.7 Multi-AZ + LDDR ...",
                        source=SRC_RISE,
                        section="Page 114"
                    )
                ]
            ),
            proposed_relation="ARCHITECTURE_99_7 SUPPORTS_SLA_99_7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Juxtaposition de deux '99.7' ≠ relation explicitée. REJECT conservateur attendu."
    ),

    # -------------------------
    # Conversion Guide frontières
    # -------------------------

    TestCase(
        id="TC40-FR-04",
        description="Embedded vs standalone are options; 'HAS_EXACT_DEPLOYMENT embedded' should be rejected",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-CONV-01",
                text="Fiori has two deployment options: embedded or standalone.",
                source=SRC_CONV,
                section="Page 28"
            ),
            concept_a=ConceptBundle(
                name="SAP Fiori deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="There are two possible deployment options ... embedded or the standalone deployment option.",
                        source=SRC_CONV,
                        section="Page 28"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Embedded (exact)",
                extracts=[
                    Extract(
                        id="B1",
                        text="... embedded or the standalone deployment option.",
                        source=SRC_CONV,
                        section="Page 28"
                    )
                ]
            ),
            proposed_relation="S4HANA_PCE_FIORI HAS_EXACT_DEPLOYMENT_OPTION EMBEDDED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Deux options sont possibles; 'EXACT' est injustifiable sans condition."
    ),

    TestCase(
        id="TC40-FR-05",
        description="Recommended but not mandatory: forcing 'REQUIRES' should be rejected",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-CONV-02",
                text="Readiness Check is 'not mandatory' but recommended.",
                source=SRC_CONV,
                section="Page 5"
            ),
            concept_a=ConceptBundle(
                name="Conversion project",
                extracts=[
                    Extract(
                        id="A1",
                        text="... Conversion to SAP S/4HANA ... SAP Readiness Check ...  Recommendation Although not mandatory, this tool is highly recommended.",
                        source=SRC_CONV,
                        section="Page 5"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP Readiness Check",
                extracts=[
                    Extract(
                        id="B1",
                        text="Although not mandatory, this tool is highly recommended.",
                        source=SRC_CONV,
                        section="Page 5"
                    )
                ]
            ),
            proposed_relation="CONVERSION_PROJECT REQUIRES_SAP_READINESS_CHECK"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit explicitement 'not mandatory'. REQUIRES contredit la modalité."
    ),

    # -------------------------
    # Operations Guide frontières
    # -------------------------

    TestCase(
        id="TC40-FR-06",
        description="Handbook recommendation should not become a strict requirement",
        category=TestCaseCategory.FRONTIER,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-FR-OPS-01",
                text="Guide says it recommends creating a daily operations handbook.",
                source=SRC_OPS,
                section="Page 5"
            ),
            concept_a=ConceptBundle(
                name="Operations handbook",
                extracts=[
                    Extract(
                        id="A1",
                        text="... the daily operations handbook that we recommend you to create ...",
                        source=SRC_OPS,
                        section="Page 5"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Required",
                extracts=[
                    Extract(
                        id="B1",
                        text="... we recommend you to create ...",
                        source=SRC_OPS,
                        section="Page 5"
                    )
                ]
            ),
            proposed_relation="DAILY_OPERATIONS_HANDBOOK IS_MANDATORY"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte exprime une recommandation, pas une obligation. Transformer 'recommend' en 'mandatory' est une sur-interprétation."
    ),
]

# -----------------------------------------------------------------------------


ALL_TEST_CASES = TYPE1_CASES + TYPE2_CASES + FRONTIER_CASES

# Sanity check for a quick import-time validation
assert len(ALL_TEST_CASES) == 40, f"Expected 40 test cases, got {len(ALL_TEST_CASES)}"
