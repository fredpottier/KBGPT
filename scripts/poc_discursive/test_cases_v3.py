"""
POC Discursive Relation Discrimination - Jeu de Cas v3 (Final - 50+ cas)

Objectif v3:
- Couvrir 3 documents sources distincts (RISE, Conversion Guide, Operations Guide)
- ~50 cas de test couvrant les patterns critiques
- Validation de la capacite de discrimination sur un corpus realiste

Sources:
- doc 020: RISE with SAP Cloud ERP Private (363f5357...v2cache.json)
- doc 010: Conversion Guide 2025 (6075f24e...v2cache.json)
- doc 017: Operations Guide 2023 (b11842e3...v2cache.json)

ATTENTION: Code jetable, non destine a la production.
"""

from models import (
    TestCase, TestCaseCategory, Verdict,
    EvidenceBundle, ConceptBundle, Extract
)

# =============================================================================
# CONSTANTES - Noms des documents sources
# =============================================================================

DOC_RISE = "020_RISE_with_SAP_Cloud_ERP_Private_full.pdf"
DOC_CONVERSION = "010_SAP_S4HANA_Cloud_Private_Edition_2025_Conversion_Guide.pdf"
DOC_OPERATIONS = "017_SAP_S4HANA_2023_Operations_Guide.pdf"


# =============================================================================
# A) RISE (doc 020) - 16 cas
# =============================================================================

RISE_TYPE1_CASES = [
    # --- Type 1 (ACCEPT) ---

    TestCase(
        id="TCv3-RISE-T1-01",
        description="DEFAULT + exception: connectivity is internal unless...",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-01",
                text="Perimeter firewall controls in RISE",
                source=DOC_RISE,
                section="p217"
            ),
            concept_a=ConceptBundle(
                name="RISE Connectivity",
                extracts=[
                    Extract(
                        id="A1",
                        text="It is important to note that all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=DOC_RISE,
                        section="p217"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Default internal and trusted status",
                extracts=[
                    Extract(
                        id="B1",
                        text="all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet",
                        source=DOC_RISE,
                        section="p217"
                    )
                ]
            ),
            proposed_relation="RISE_CONNECTIVITY IS_DEFAULT_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Pattern 'considered X unless Y' supporte une lecture 'par defaut'. Le predicat DEFAULT correspond exactement au texte."
    ),

    TestCase(
        id="TCv3-RISE-T1-02",
        description="CAN_HAVE option: PCE peut avoir RTO 4 HOURS",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-02",
                text="SAP S/4HANA Cloud, Private Edition - Business Continuity",
                source=DOC_RISE,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS option",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE CAN_HAVE_RTO 4 HOURS"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste explicitement 4 HOURS comme option. CAN_HAVE matche la modalite 'or'."
    ),

    TestCase(
        id="TCv3-RISE-T1-03",
        description="CAN_HAVE option: PCE peut avoir RPO 0",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-03",
                text="SAP S/4HANA Cloud, Private Edition - Business Continuity",
                source=DOC_RISE,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO 0 or 30 MINUTES",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0 option",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO 0 or 30 MINUTES",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE CAN_HAVE_RPO 0"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste 0 comme possibilite. CAN_HAVE est fidele a 'or'."
    ),

    TestCase(
        id="TCv3-RISE-T1-04",
        description="WAF secures inbound access (assertion explicite)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-04",
                text="Internet based access scenarios",
                source=DOC_RISE,
                section="p37"
            ),
            concept_a=ConceptBundle(
                name="Internet inbound access",
                extracts=[
                    Extract(
                        id="A1",
                        text="A Web Application Firewall (WAF) is used to secure the internet inbound access. Such an access is not turned on by default and customer would require to highlight this requirement as part of onboarding preparation.",
                        source=DOC_RISE,
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
                        source=DOC_RISE,
                        section="p37"
                    )
                ]
            ),
            proposed_relation="INTERNET_INBOUND_ACCESS IS_SECURED_BY WAF"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Lien explicitement affirme dans l'extrait avec 'is used to secure'."
    ),

    TestCase(
        id="TCv3-RISE-T1-05",
        description="PROD SLA explicitement mentionne",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-05",
                text="SAP S/4HANA Cloud, Private Edition - Business Continuity",
                source=DOC_RISE,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE Production",
                extracts=[
                    Extract(
                        id="A1",
                        text="PROD SLA 99.7 NON-PROD SLA 95.0",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA 99.7",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE_PROD HAS_SLA 99.7"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Association explicite dans le meme extrait."
    ),

    TestCase(
        id="TCv3-RISE-T1-06",
        description="Active-Active across AZ (assertion directe)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-06",
                text="High Availability Architecture",
                source=DOC_RISE,
                section="p114"
            ),
            concept_a=ConceptBundle(
                name="Application components",
                extracts=[
                    Extract(
                        id="A1",
                        text="Application components such as Application Servers and Web Dispatchers are running Active-Active across the two Availability Zones (AZ) with Application Load Balancer (ALB) in front distributing traffic.",
                        source=DOC_RISE,
                        section="p114"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Active-Active AZ",
                extracts=[
                    Extract(
                        id="B1",
                        text="running Active-Active across the two Availability Zones (AZ)",
                        source=DOC_RISE,
                        section="p114"
                    )
                ]
            ),
            proposed_relation="APPLICATION_COMPONENTS RUN_AS Active-Active_AZ"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Phrase directe; relation explicitement affirmee."
    ),
]

RISE_TYPE2_CASES = [
    # --- Type 2 (REJECT) ---

    TestCase(
        id="TCv3-RISE-T2-01",
        description="ALWAYS vs unless: rejeter un ALWAYS quand le texte dit 'unless'",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-01",
                text="Perimeter firewall controls in RISE",
                source=DOC_RISE,
                section="p217"
            ),
            concept_a=ConceptBundle(
                name="Connectivity to RISE",
                extracts=[
                    Extract(
                        id="A1",
                        text="It is important to note that all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=DOC_RISE,
                        section="p217"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Always internal status",
                extracts=[
                    Extract(
                        id="B1",
                        text="all connectivity to RISE is considered internal and trusted unless the customer specifically requests to open RISE access via the Internet.",
                        source=DOC_RISE,
                        section="p217"
                    )
                ]
            ),
            proposed_relation="RISE_CONNECTIVITY IS_ALWAYS_INTERNAL_AND_TRUSTED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="La relation proposee est absolue (ALWAYS) mais l'extrait introduit une exception explicite (unless)."
    ),

    TestCase(
        id="TCv3-RISE-T2-02",
        description="HAS_EXACT vs alternatives: rejeter HAS_EXACT quand 'or' present",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-02",
                text="SAP S/4HANA Cloud, Private Edition - Business Continuity",
                source=DOC_RISE,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RTO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RTO 4 HOURS exact",
                extracts=[
                    Extract(
                        id="B1",
                        text="RTO 12 HOURS or 4 HOURS (ENHANCED)",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE HAS_EXACT_RTO 4 HOURS"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte contient 'or' = alternative. On ne peut affirmer une valeur exacte sans savoir quelle option est selectionnee."
    ),

    TestCase(
        id="TCv3-RISE-T2-03",
        description="HAS_EXACT vs alternatives: rejeter HAS_EXACT_RPO quand 'or' present",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-03",
                text="SAP S/4HANA Cloud, Private Edition - Business Continuity",
                source=DOC_RISE,
                section="p112"
            ),
            concept_a=ConceptBundle(
                name="PCE RPO",
                extracts=[
                    Extract(
                        id="A1",
                        text="RPO 0 or 30 MINUTES",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="RPO 0 exact",
                extracts=[
                    Extract(
                        id="B1",
                        text="RPO 0 or 30 MINUTES",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="PCE HAS_EXACT_RPO 0"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Alternative explicite (or) => on ne peut pas affirmer l'exactitude."
    ),

    TestCase(
        id="TCv3-RISE-T2-04",
        description="Causalite non affirmee: Active-Active n'ENABLES pas SLA 99.7",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-04",
                text="SAP S/4HANA Cloud, Private Edition - Business Continuity",
                source=DOC_RISE,
                section="p112-114"
            ),
            concept_a=ConceptBundle(
                name="Active-Active across two Availability Zones",
                extracts=[
                    Extract(
                        id="A1",
                        text="Application components such as Application Servers and Web Dispatchers are running Active-Active across the two Availability Zones (AZ) with Application Load Balancer (ALB) in front distributing traffic.",
                        source=DOC_RISE,
                        section="p114"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA 99.7",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="Active-Active_AZ ENABLES PROD_SLA_99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte juxtapose HA et SLA mais n'affirme pas un lien causal/justificatif entre les deux."
    ),

    TestCase(
        id="TCv3-RISE-T2-05",
        description="Cross-pages sans pont: CDC Option vs SLA",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-05",
                text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                source=DOC_RISE,
                section="p160"
            ),
            concept_a=ConceptBundle(
                name="CDC Option",
                extracts=[
                    Extract(
                        id="A1",
                        text="RISE with SAP S/4HANA Cloud, private edition, CDC Option",
                        source=DOC_RISE,
                        section="p160"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="PROD SLA 99.7",
                extracts=[
                    Extract(
                        id="B1",
                        text="PROD SLA 99.7",
                        source=DOC_RISE,
                        section="p112"
                    )
                ]
            ),
            proposed_relation="CDC_OPTION HAS_PROD_SLA 99.7"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Deux contextes distincts (CDC option p160 vs business continuity p112) sans pont textuel explicite."
    ),

    TestCase(
        id="TCv3-RISE-T2-06",
        description="Connaissance externe: WAF PREVENTS_ALL attacks",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-RISE-T2-06",
                text="Internet based access scenarios",
                source=DOC_RISE,
                section="p37"
            ),
            concept_a=ConceptBundle(
                name="WAF",
                extracts=[
                    Extract(
                        id="A1",
                        text="A Web Application Firewall (WAF) is used to secure the internet inbound access.",
                        source=DOC_RISE,
                        section="p37"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="All web attacks",
                extracts=[
                    Extract(
                        id="B1",
                        text="secure the internet inbound access",
                        source=DOC_RISE,
                        section="p37"
                    )
                ]
            ),
            proposed_relation="WAF PREVENTS_ALL WEB_ATTACKS"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'secure' mais ne dit pas 'prevents all'. C'est une inference basee sur connaissance externe."
    ),
]


# =============================================================================
# B) CONVERSION GUIDE 2025 (doc 010) - 16 cas
# =============================================================================

CONVERSION_TYPE1_CASES = [
    # --- Type 1 (ACCEPT) ---

    TestCase(
        id="TCv3-CONV-T1-01",
        description="Deux options listees: CBC peut etre deploye EMBEDDED",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-01",
                text="SAP Fiori Deployment Options",
                source=DOC_CONVERSION,
                section="p29"
            ),
            concept_a=ConceptBundle(
                name="SAP Fiori deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="There are two possible deployment options for SAP Fiori for SAP S/4HANA Cloud Private Edition, the embedded or the standalone deployment option.",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Embedded deployment",
                extracts=[
                    Extract(
                        id="B1",
                        text="the embedded or the standalone deployment option",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            proposed_relation="SAP_FIORI CAN_BE_DEPLOYED EMBEDDED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste explicitement 'embedded' comme une des deux options possibles."
    ),

    TestCase(
        id="TCv3-CONV-T1-02",
        description="Deux options listees: CBC peut etre deploye STANDALONE",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-02",
                text="SAP Fiori Deployment Options",
                source=DOC_CONVERSION,
                section="p29"
            ),
            concept_a=ConceptBundle(
                name="SAP Fiori deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="There are two possible deployment options for SAP Fiori for SAP S/4HANA Cloud Private Edition, the embedded or the standalone deployment option.",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Standalone deployment",
                extracts=[
                    Extract(
                        id="B1",
                        text="the embedded or the standalone deployment option",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            proposed_relation="SAP_FIORI CAN_BE_DEPLOYED STANDALONE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Le texte liste explicitement 'standalone' comme une des deux options possibles."
    ),

    TestCase(
        id="TCv3-CONV-T1-03",
        description="Prerequisite: standalone deployment requires DB migration",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-03",
                text="Standalone Deployment",
                source=DOC_CONVERSION,
                section="p29"
            ),
            concept_a=ConceptBundle(
                name="Standalone Deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="As a prerequisite, you have to migrate the database of the central hub system (supported databases are SAP HANA, SAP MaxDB, or SAP ASE) and upgrade the system.",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="DB migration prerequisite",
                extracts=[
                    Extract(
                        id="B1",
                        text="As a prerequisite, you have to migrate the database of the central hub system",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            proposed_relation="STANDALONE_DEPLOYMENT REQUIRES DB_MIGRATION_OF_CENTRAL_HUB"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'As a prerequisite, you have to' exprime clairement une exigence."
    ),

    TestCase(
        id="TCv3-CONV-T1-04",
        description="Prerequisite: standalone deployment requires upgrade",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-04",
                text="Standalone Deployment",
                source=DOC_CONVERSION,
                section="p29"
            ),
            concept_a=ConceptBundle(
                name="Standalone Deployment",
                extracts=[
                    Extract(
                        id="A1",
                        text="As a prerequisite, you have to migrate the database of the central hub system (supported databases are SAP HANA, SAP MaxDB, or SAP ASE) and upgrade the system.",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="System upgrade prerequisite",
                extracts=[
                    Extract(
                        id="B1",
                        text="and upgrade the system",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            proposed_relation="STANDALONE_DEPLOYMENT REQUIRES CENTRAL_HUB_UPGRADE"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'and upgrade the system' fait partie de la meme phrase prerequis."
    ),

    TestCase(
        id="TCv3-CONV-T1-05",
        description="Outil explicitement requis: Conversion uses SUM",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-05",
                text="Conversion Scenarios",
                source=DOC_CONVERSION,
                section="p10"
            ),
            concept_a=ConceptBundle(
                name="System Conversion",
                extracts=[
                    Extract(
                        id="A1",
                        text="The system conversion will be accomplished using the SAP Software Update Manager (SUM) in a one-step procedure with a single downtime.",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP Software Update Manager (SUM)",
                extracts=[
                    Extract(
                        id="B1",
                        text="using the SAP Software Update Manager (SUM)",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            proposed_relation="SYSTEM_CONVERSION USES_TOOL SUM"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'will be accomplished using' indique clairement l'outil utilise."
    ),

    TestCase(
        id="TCv3-CONV-T1-06",
        description="Ordre/dependance: Maintenance Planner mentionne avec SUM",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-06",
                text="Getting Started - Required Documents and Tools",
                source=DOC_CONVERSION,
                section="p6"
            ),
            concept_a=ConceptBundle(
                name="System Conversion Tools",
                extracts=[
                    Extract(
                        id="A1",
                        text="System Conversion to SAP S/4HANA using SUM 2.0 SP <latest version>. Maintenance Planner User Guide.",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Maintenance Planner",
                extracts=[
                    Extract(
                        id="B1",
                        text="Maintenance Planner User Guide",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            proposed_relation="CONVERSION USES_TOOL MAINTENANCE_PLANNER"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Maintenance Planner explicitement liste parmi les outils requis."
    ),

    TestCase(
        id="TCv3-CONV-T1-07",
        description="Migration de DB incluse dans la conversion",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-07",
                text="Conversion Scenarios",
                source=DOC_CONVERSION,
                section="p10"
            ),
            concept_a=ConceptBundle(
                name="One-step conversion",
                extracts=[
                    Extract(
                        id="A1",
                        text="Migration of any database for SAP ERP to the SAP HANA database. Conversion of the data model for SAP ERP to that for SAP S/4HANA",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Database migration to HANA",
                extracts=[
                    Extract(
                        id="B1",
                        text="Migration of any database for SAP ERP to the SAP HANA database",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            proposed_relation="SYSTEM_CONVERSION INCLUDES DB_MIGRATION_TO_HANA"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="La migration DB est explicitement listee comme partie de la conversion."
    ),

    TestCase(
        id="TCv3-CONV-T1-08",
        description="SAP Readiness Check recommande (explicite)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-08",
                text="Getting Started",
                source=DOC_CONVERSION,
                section="p6"
            ),
            concept_a=ConceptBundle(
                name="SAP Readiness Check",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP Readiness Check. This tool analyzes your SAP ERP 6.0 system and highlights important aspects of the conversion. Recommendation: Although not mandatory, this tool is highly recommended.",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Highly recommended status",
                extracts=[
                    Extract(
                        id="B1",
                        text="Although not mandatory, this tool is highly recommended",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            proposed_relation="SAP_READINESS_CHECK IS_RECOMMENDED"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'is highly recommended' est une assertion explicite."
    ),
]

CONVERSION_TYPE2_CASES = [
    # --- Type 2 (REJECT) ---

    TestCase(
        id="TCv3-CONV-T2-01",
        description="ALWAYS trop fort: conversion n'INCLUT PAS TOUJOURS DB migration",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-01",
                text="Conversion Scenarios",
                source=DOC_CONVERSION,
                section="p10"
            ),
            concept_a=ConceptBundle(
                name="System Conversion",
                extracts=[
                    Extract(
                        id="A1",
                        text="Migration of any database for SAP ERP to the SAP HANA database",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="DB Migration mandatory",
                extracts=[
                    Extract(
                        id="B1",
                        text="Migration of any database for SAP ERP to the SAP HANA database",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            proposed_relation="SYSTEM_CONVERSION ALWAYS_INCLUDES DB_MIGRATION_TO_HANA"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte liste ce qui est POSSIBLE dans un scenario, pas ce qui est TOUJOURS inclus. ALWAYS est trop fort."
    ),

    TestCase(
        id="TCv3-CONV-T2-02",
        description="Connaissance externe SAP: SUM DMO pas explicitement nomme",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-02",
                text="Conversion Scenarios",
                source=DOC_CONVERSION,
                section="p10"
            ),
            concept_a=ConceptBundle(
                name="System Conversion",
                extracts=[
                    Extract(
                        id="A1",
                        text="The system conversion will be accomplished using the SAP Software Update Manager (SUM) in a one-step procedure.",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SUM DMO",
                extracts=[
                    Extract(
                        id="B1",
                        text="using the SAP Software Update Manager (SUM)",
                        source=DOC_CONVERSION,
                        section="p10"
                    )
                ]
            ),
            proposed_relation="SYSTEM_CONVERSION REQUIRES SUM_DMO"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'SUM' mais pas 'SUM DMO' specifiquement. DMO est connaissance externe SAP."
    ),

    TestCase(
        id="TCv3-CONV-T2-03",
        description="HAS_EXACT vs alternative: rejeter EXACTLY_TWO quand 'or' implicite",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-03",
                text="SAP Fiori Deployment Options",
                source=DOC_CONVERSION,
                section="p29"
            ),
            concept_a=ConceptBundle(
                name="SAP Fiori",
                extracts=[
                    Extract(
                        id="A1",
                        text="There are two possible deployment options for SAP Fiori for SAP S/4HANA Cloud Private Edition, the embedded or the standalone deployment option.",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Embedded as sole option",
                extracts=[
                    Extract(
                        id="B1",
                        text="the embedded or the standalone deployment option",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            proposed_relation="SAP_FIORI HAS_ONLY_DEPLOYMENT_OPTION EMBEDDED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'embedded OR standalone'. Affirmer ONLY embedded est faux."
    ),

    TestCase(
        id="TCv3-CONV-T2-04",
        description="Causalite non affirmee: Readiness Check n'ASSURE pas la reussite",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-04",
                text="Getting Started",
                source=DOC_CONVERSION,
                section="p6"
            ),
            concept_a=ConceptBundle(
                name="SAP Readiness Check",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP Readiness Check. This tool analyzes your SAP ERP 6.0 system and highlights important aspects of the conversion.",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Conversion success",
                extracts=[
                    Extract(
                        id="B1",
                        text="analyzes your SAP ERP 6.0 system and highlights important aspects",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            proposed_relation="SAP_READINESS_CHECK ENSURES CONVERSION_SUCCESS"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'analyzes' et 'highlights', pas 'ensures success'. Lien causal non affirme."
    ),

    TestCase(
        id="TCv3-CONV-T2-05",
        description="Ordre non specifie: Maintenance Planner n'est pas BEFORE SUM explicitement",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-05",
                text="Getting Started - Required Documents and Tools",
                source=DOC_CONVERSION,
                section="p6"
            ),
            concept_a=ConceptBundle(
                name="Maintenance Planner",
                extracts=[
                    Extract(
                        id="A1",
                        text="System Conversion to SAP S/4HANA using SUM 2.0 SP <latest version>. Maintenance Planner User Guide.",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SUM execution",
                extracts=[
                    Extract(
                        id="B1",
                        text="System Conversion to SAP S/4HANA using SUM 2.0",
                        source=DOC_CONVERSION,
                        section="p6"
                    )
                ]
            ),
            proposed_relation="MAINTENANCE_PLANNER MUST_RUN_BEFORE SUM"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Les outils sont listes mais l'ordre d'execution n'est pas explicitement specifie dans cet extrait."
    ),

    TestCase(
        id="TCv3-CONV-T2-06",
        description="Generalisation: SAP HANA n'est pas le SEUL DB supporte pour hub",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-CONV-T2-06",
                text="Standalone Deployment",
                source=DOC_CONVERSION,
                section="p29"
            ),
            concept_a=ConceptBundle(
                name="Central hub system",
                extracts=[
                    Extract(
                        id="A1",
                        text="supported databases are SAP HANA, SAP MaxDB, or SAP ASE",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP HANA only",
                extracts=[
                    Extract(
                        id="B1",
                        text="supported databases are SAP HANA, SAP MaxDB, or SAP ASE",
                        source=DOC_CONVERSION,
                        section="p29"
                    )
                ]
            ),
            proposed_relation="CENTRAL_HUB REQUIRES_ONLY SAP_HANA"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte liste 3 DB supportees. ONLY SAP_HANA est faux."
    ),
]


# =============================================================================
# C) OPERATIONS GUIDE 2023 (doc 017) - 16 cas
# =============================================================================

OPERATIONS_TYPE1_CASES = [
    # --- Type 1 (ACCEPT) ---

    TestCase(
        id="TCv3-OPS-T1-01",
        description="HANA database requis (needs to run on)",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-01",
                text="User Management",
                source=DOC_OPERATIONS,
                section="p16"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA generally relies on the user management and authentication mechanisms provided with ABAP Platform, in particular the Application Server ABAP and the SAP HANA Platform.",
                        source=DOC_OPERATIONS,
                        section="p16"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP HANA Platform",
                extracts=[
                    Extract(
                        id="B1",
                        text="the SAP HANA Platform",
                        source=DOC_OPERATIONS,
                        section="p16"
                    )
                ]
            ),
            proposed_relation="S4HANA RELIES_ON SAP_HANA_PLATFORM"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'relies on' exprime une dependance explicite."
    ),

    TestCase(
        id="TCv3-OPS-T1-02",
        description="bgRFC requis pour output control",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-02",
                text="Output Management",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="Output control",
                extracts=[
                    Extract(
                        id="A1",
                        text="Output control uses a bgRFC to process output. Therefore, you need to maintain the bgRFC configuration. Otherwise, no output can be performed.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="bgRFC configuration",
                extracts=[
                    Extract(
                        id="B1",
                        text="you need to maintain the bgRFC configuration. Otherwise, no output can be performed.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="OUTPUT_CONTROL REQUIRES bgRFC_CONFIGURATION"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'you need to' + 'Otherwise, no output can be performed' = exigence claire."
    ),

    TestCase(
        id="TCv3-OPS-T1-03",
        description="BRFplus utilise pour output parameter determination",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-03",
                text="Output Management - BRFplus",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="Output control",
                extracts=[
                    Extract(
                        id="A1",
                        text="Output control uses BRFplus for the output parameter determination. Technically, BRFplus is based on WebDynpro applications.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="BRFplus",
                extracts=[
                    Extract(
                        id="B1",
                        text="Output control uses BRFplus for the output parameter determination",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="OUTPUT_CONTROL USES BRFplus"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'uses BRFplus for' est une assertion explicite d'utilisation."
    ),

    TestCase(
        id="TCv3-OPS-T1-04",
        description="Supervisor destination requise pour bgRFC",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-04",
                text="bgRFC Configuration",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="bgRFC",
                extracts=[
                    Extract(
                        id="A1",
                        text="One of the most important steps is defining a supervisor destination, as bgRFC doesn't work without it.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Supervisor destination",
                extracts=[
                    Extract(
                        id="B1",
                        text="defining a supervisor destination, as bgRFC doesn't work without it",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="bgRFC REQUIRES SUPERVISOR_DESTINATION"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'doesn't work without it' = exigence absolue."
    ),

    TestCase(
        id="TCv3-OPS-T1-05",
        description="Storage system requis pour output control",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-05",
                text="Storage System and Category",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="Output control",
                extracts=[
                    Extract(
                        id="A1",
                        text="Output control needs a defined storage system (content repository) to save the rendered form output as PDF.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Storage system",
                extracts=[
                    Extract(
                        id="B1",
                        text="needs a defined storage system (content repository)",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="OUTPUT_CONTROL NEEDS STORAGE_SYSTEM"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'needs' exprime une exigence claire."
    ),

    TestCase(
        id="TCv3-OPS-T1-06",
        description="Transaction SBGRFCCONF pour configuration bgRFC",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-06",
                text="bgRFC Configuration",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="bgRFC configuration",
                extracts=[
                    Extract(
                        id="A1",
                        text="You can perform all the relevant steps in transaction SBGRFCCONF.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Transaction SBGRFCCONF",
                extracts=[
                    Extract(
                        id="B1",
                        text="transaction SBGRFCCONF",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="bgRFC_CONFIGURATION USES_TRANSACTION SBGRFCCONF"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="Transaction explicitement mentionnee pour la configuration."
    ),

    TestCase(
        id="TCv3-OPS-T1-07",
        description="BRFplus base sur WebDynpro",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-07",
                text="BRFplus technical basis",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="BRFplus",
                extracts=[
                    Extract(
                        id="A1",
                        text="Technically, BRFplus is based on WebDynpro applications. Therefore, you need to set up the according ICF services.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="WebDynpro",
                extracts=[
                    Extract(
                        id="B1",
                        text="BRFplus is based on WebDynpro applications",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="BRFplus IS_BASED_ON WebDynpro"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'is based on' est une assertion explicite de dependance technique."
    ),

    TestCase(
        id="TCv3-OPS-T1-08",
        description="ICF services requis pour BRFplus",
        category=TestCaseCategory.CANONICAL_TYPE1,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-08",
                text="BRFplus ICF requirement",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="BRFplus",
                extracts=[
                    Extract(
                        id="A1",
                        text="Technically, BRFplus is based on WebDynpro applications. Therefore, you need to set up the according ICF services.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="ICF services",
                extracts=[
                    Extract(
                        id="B1",
                        text="you need to set up the according ICF services",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="BRFplus REQUIRES ICF_SERVICES"
        ),
        expected_verdict=Verdict.ACCEPT,
        rationale="'you need to set up' = exigence explicite."
    ),
]

OPERATIONS_TYPE2_CASES = [
    # --- Type 2 (REJECT) ---

    TestCase(
        id="TCv3-OPS-T2-01",
        description="Causalite non affirmee: bgRFC ne CAUSE pas les problemes de formatage",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-01",
                text="Output Management",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="bgRFC",
                extracts=[
                    Extract(
                        id="A1",
                        text="Output control uses a bgRFC to process output. Therefore, you need to maintain the bgRFC configuration.",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Output formatting issues",
                extracts=[
                    Extract(
                        id="B1",
                        text="bgRFC to process output",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="bgRFC CAUSES OUTPUT_FORMATTING_ISSUES"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte ne dit pas que bgRFC cause des problemes. Il dit qu'il est utilise pour traiter."
    ),

    TestCase(
        id="TCv3-OPS-T2-02",
        description="Connaissance externe: SAP BTP requis pour Clean Core",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-02",
                text="Operations Guide TOC",
                source=DOC_OPERATIONS,
                section="p2"
            ),
            concept_a=ConceptBundle(
                name="Clean Core Development Environment",
                extracts=[
                    Extract(
                        id="A1",
                        text="Set Up Clean Core Development Environment",
                        source=DOC_OPERATIONS,
                        section="p2"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP BTP",
                extracts=[
                    Extract(
                        id="B1",
                        text="Clean Core Development Environment",
                        source=DOC_OPERATIONS,
                        section="p2"
                    )
                ]
            ),
            proposed_relation="CLEAN_CORE_SETUP REQUIRES SAP_BTP"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte mentionne Clean Core mais pas SAP BTP. Le lien est connaissance externe SAP."
    ),

    TestCase(
        id="TCv3-OPS-T2-03",
        description="ALWAYS trop fort: security guidelines ne sont pas ALWAYS appliquees",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-03",
                text="User Management",
                source=DOC_OPERATIONS,
                section="p16"
            ),
            concept_a=ConceptBundle(
                name="Security guidelines",
                extracts=[
                    Extract(
                        id="A1",
                        text="the security recommendations and guidelines for user administration and authentication as described in the Application Server ABAP Security Guide and SAP HANA Platform documentation apply.",
                        source=DOC_OPERATIONS,
                        section="p16"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Automatic enforcement",
                extracts=[
                    Extract(
                        id="B1",
                        text="security recommendations and guidelines... apply",
                        source=DOC_OPERATIONS,
                        section="p16"
                    )
                ]
            ),
            proposed_relation="SECURITY_GUIDELINES ARE_ALWAYS_AUTOMATICALLY_ENFORCED"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'apply' (sont applicables) pas 'are automatically enforced'."
    ),

    TestCase(
        id="TCv3-OPS-T2-04",
        description="Inference: storage type MUST be database",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-04",
                text="Storage System and Category",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="Storage system",
                extracts=[
                    Extract(
                        id="A1",
                        text="You can set up the storage type which fits your needs, for example a SAP System Database, or a HTTP content server (such as fileserver, database, or external archive).",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Database storage only",
                extracts=[
                    Extract(
                        id="B1",
                        text="SAP System Database, or a HTTP content server",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="OUTPUT_STORAGE MUST_BE_TYPE DATABASE"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte liste plusieurs options ('or'). MUST_BE database est faux."
    ),

    TestCase(
        id="TCv3-OPS-T2-05",
        description="Cross-section: lien entre output control et backup/recovery",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-05",
                text="Operations Guide sections",
                source=DOC_OPERATIONS,
                section="TOC"
            ),
            concept_a=ConceptBundle(
                name="Output Management",
                extracts=[
                    Extract(
                        id="A1",
                        text="4.3 Output Management",
                        source=DOC_OPERATIONS,
                        section="p10"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Backup and Recovery",
                extracts=[
                    Extract(
                        id="B1",
                        text="4.4 Backup and Recovery",
                        source=DOC_OPERATIONS,
                        section="p13"
                    )
                ]
            ),
            proposed_relation="OUTPUT_MANAGEMENT DEPENDS_ON BACKUP_RECOVERY"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Sections distinctes dans la TOC. Aucun lien textuel entre output et backup."
    ),

    TestCase(
        id="TCv3-OPS-T2-06",
        description="Generalisation: S/4HANA ne REQUIRES pas Solution Manager obligatoirement",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-06",
                text="SAP S/4HANA System Landscape",
                source=DOC_OPERATIONS,
                section="p7"
            ),
            concept_a=ConceptBundle(
                name="SAP S/4HANA",
                extracts=[
                    Extract(
                        id="A1",
                        text="SAP S/4HANA System Landscape Information",
                        source=DOC_OPERATIONS,
                        section="p7"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="SAP Solution Manager",
                extracts=[
                    Extract(
                        id="B1",
                        text="SAP S/4HANA System Landscape",
                        source=DOC_OPERATIONS,
                        section="p7"
                    )
                ]
            ),
            proposed_relation="S4HANA REQUIRES SAP_SOLUTION_MANAGER"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="La mention de S/4HANA System Landscape n'implique pas une exigence de Solution Manager."
    ),

    TestCase(
        id="TCv3-OPS-T2-07",
        description="Transitive: WebDynpro => ICF => Output (chaine non affirmee)",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-07",
                text="BRFplus technical",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="WebDynpro",
                extracts=[
                    Extract(
                        id="A1",
                        text="BRFplus is based on WebDynpro applications",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Output processing",
                extracts=[
                    Extract(
                        id="B1",
                        text="Output control uses BRFplus",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="WebDynpro DIRECTLY_PROCESSES OUTPUT"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Chaine transitive: WebDynpro -> BRFplus -> Output. Le lien direct n'est pas affirme."
    ),

    TestCase(
        id="TCv3-OPS-T2-08",
        description="Inference: Adobe Forms est OBLIGATOIRE",
        category=TestCaseCategory.CANONICAL_TYPE2,
        evidence_bundle=EvidenceBundle(
            scope=Extract(
                id="SCOPE-OPS-T2-08",
                text="Output Management prerequisites",
                source=DOC_OPERATIONS,
                section="p11"
            ),
            concept_a=ConceptBundle(
                name="Output control prerequisites",
                extracts=[
                    Extract(
                        id="A1",
                        text="Adobe Document Services is available (when using Adobe Forms)",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            concept_b=ConceptBundle(
                name="Adobe Forms requirement",
                extracts=[
                    Extract(
                        id="B1",
                        text="Adobe Document Services is available (when using Adobe Forms)",
                        source=DOC_OPERATIONS,
                        section="p11"
                    )
                ]
            ),
            proposed_relation="OUTPUT_CONTROL REQUIRES ADOBE_FORMS"
        ),
        expected_verdict=Verdict.REJECT,
        rationale="Le texte dit 'when using Adobe Forms' = conditionnel. Pas une exigence absolue."
    ),
]


# =============================================================================
# SUITE COMPLETE - 48 cas
# =============================================================================

ALL_RISE_CASES = RISE_TYPE1_CASES + RISE_TYPE2_CASES
ALL_CONVERSION_CASES = CONVERSION_TYPE1_CASES + CONVERSION_TYPE2_CASES
ALL_OPERATIONS_CASES = OPERATIONS_TYPE1_CASES + OPERATIONS_TYPE2_CASES

ALL_TYPE1_CASES = RISE_TYPE1_CASES + CONVERSION_TYPE1_CASES + OPERATIONS_TYPE1_CASES
ALL_TYPE2_CASES = RISE_TYPE2_CASES + CONVERSION_TYPE2_CASES + OPERATIONS_TYPE2_CASES

ALL_TEST_CASES = ALL_TYPE1_CASES + ALL_TYPE2_CASES


def get_test_cases_by_category(category: TestCaseCategory) -> list[TestCase]:
    """Retourne les cas de test d'une categorie donnee."""
    return [tc for tc in ALL_TEST_CASES if tc.category == category]


def get_test_cases_by_document(doc_name: str) -> list[TestCase]:
    """Retourne les cas de test pour un document donne."""
    return [tc for tc in ALL_TEST_CASES
            if tc.evidence_bundle.scope and doc_name in tc.evidence_bundle.scope.source]


def get_all_test_cases() -> list[TestCase]:
    """Retourne tous les cas de test."""
    return ALL_TEST_CASES


# Stats pour verification
if __name__ == "__main__":
    print("=== POC v3 - Jeu de test final (3 documents, ~50 cas) ===\n")

    print("Par document:")
    print(f"  RISE (doc 020):")
    print(f"    - Type 1 (ACCEPT): {len(RISE_TYPE1_CASES)} cas")
    print(f"    - Type 2 (REJECT): {len(RISE_TYPE2_CASES)} cas")

    print(f"  Conversion Guide (doc 010):")
    print(f"    - Type 1 (ACCEPT): {len(CONVERSION_TYPE1_CASES)} cas")
    print(f"    - Type 2 (REJECT): {len(CONVERSION_TYPE2_CASES)} cas")

    print(f"  Operations Guide (doc 017):")
    print(f"    - Type 1 (ACCEPT): {len(OPERATIONS_TYPE1_CASES)} cas")
    print(f"    - Type 2 (REJECT): {len(OPERATIONS_TYPE2_CASES)} cas")

    print(f"\nTotal par type:")
    print(f"  - Type 1 (ACCEPT attendu): {len(ALL_TYPE1_CASES)} cas")
    print(f"  - Type 2 (REJECT attendu): {len(ALL_TYPE2_CASES)} cas")
    print(f"  - TOTAL: {len(ALL_TEST_CASES)} cas")

    print("\n--- Detail des cas ---")
    for tc in ALL_TEST_CASES:
        doc_short = "RISE" if "RISE" in tc.id else ("CONV" if "CONV" in tc.id else "OPS")
        print(f"  {tc.id}: [{tc.expected_verdict.value}] {tc.description[:55]}...")
