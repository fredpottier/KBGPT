# src/knowbase/claimfirst/extractors/question_signature_extractor.py
"""
QuestionSignature Extractor — Level A (patterns regex déterministes).

Extrait des QuestionSignatures depuis les claims en utilisant des patterns
regex. Précision ~100%, zéro coût LLM.

Patterns couverts :

IT/infra :
- Minimum/maximum version, RAM, connections, etc.
- Requires protocol/technology
- Default values
- Deprecated/end-of-support
- Supported platforms/databases
- Timeout/retention/limit values

Réglementaire :
- Amendes (montants absolus, % du CA)
- Délais d'entrée en vigueur (X mois/ans après)
- Notifications de violation (within X hours/days)
- Périodes de conformité (deadlines réglementaires)
- Pourcentages concrets (statistiques, seuils)
- Références Article (GDPR, AI Act, etc.)

Cloud-native / Kubernetes :
- Feature graduation (alpha → beta → GA/stable) avec version
- Available/introduced since version
- Deprecated/removed in version
- Replaced by / use X instead
- Defaults to value
- Service ports (listens on, binds to)
- Min/max replicas, nodes, pods
- Resource requests/limits (CPU, memory)
- Grace periods (terminationGracePeriodSeconds)
- API versions (apiVersion: group/version)
- Recommended counts (nodes, replicas)
- Supported platforms (Linux, Windows, arm64, etc.)

Biomédical / Recherche clinique :
- Survie (median OS, PFS, DFS en mois)
- Taux de réponse (ORR, CR, PR en %)
- Hazard ratio (HR avec intervalle de confiance)
- Phase d'essai clinique (Phase I/II/III)
- Approbation réglementaire (FDA/EMA approved in YYYY)
- Dosage (200mg, 2mg/kg, q2w/q3w)
- Seuils biomarqueurs (PCT > 0.25 ng/mL, CRP > 10 mg/L)
- Sensibilité/spécificité diagnostique (%)
- Taille d'échantillon (n=, N=, enrolled X patients)
- p-value et significativité statistique
- Réduction relative (reduced by X%, X-fold reduction)
- Efficacité d'édition CRISPR (editing efficiency X%)
- Composition microbiome (abundance, ratio, alpha diversity)
- NCT trial identifiers
- NNT (Number Needed to Treat)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.question_signature import (
    QuestionSignature,
    QSExtractionLevel,
    QSValueType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Pattern definitions
# =============================================================================


@dataclass
class QSPattern:
    """Définition d'un pattern Level A."""

    name: str
    regex: re.Pattern
    dimension_key: str
    question_template: str  # {subject}, {value}, {unit} placeholders
    value_type: QSValueType
    value_group: int = 1  # Groupe regex pour la valeur extraite
    subject_group: int = 0  # 0 = pas de groupe sujet (utiliser structured_form)


# Patterns Level A — IT/infra + réglementaire

LEVEL_A_PATTERNS: List[QSPattern] = [
    # --- Version requirements ---
    QSPattern(
        name="minimum_version",
        regex=re.compile(
            r"(?:minimum|min\.?)\s+(?:required\s+)?version\s+(?:is\s+)?[\"']?(\d[\w.]+)[\"']?",
            re.IGNORECASE,
        ),
        dimension_key="min_version",
        question_template="What is the minimum version of {subject}?",
        value_type=QSValueType.VERSION,
    ),
    QSPattern(
        name="minimum_version_required",
        regex=re.compile(
            r"(\d[\w.]+)\s+is\s+the\s+minimum\s+(?:required\s+)?version",
            re.IGNORECASE,
        ),
        dimension_key="min_version",
        question_template="What is the minimum version of {subject}?",
        value_type=QSValueType.VERSION,
    ),
    QSPattern(
        name="requires_version",
        regex=re.compile(
            r"requires?\s+(?:at\s+least\s+)?(?:version\s+)?(\d[\w.]+)",
            re.IGNORECASE,
        ),
        dimension_key="required_version",
        question_template="What version does {subject} require?",
        value_type=QSValueType.VERSION,
    ),

    # --- Numeric requirements (RAM, connections, etc.) ---
    QSPattern(
        name="minimum_ram",
        regex=re.compile(
            r"(?:minimum|min\.?)\s+(?:required\s+)?(?:RAM|memory)\s+(?:is\s+)?(\d+)\s*(GB|MB|TB|GiB)",
            re.IGNORECASE,
        ),
        dimension_key="min_ram",
        question_template="What is the minimum RAM for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=1,
    ),
    QSPattern(
        name="minimum_ram_reverse",
        regex=re.compile(
            r"(\d+)\s*(GB|MB|TB|GiB)\s+(?:of\s+)?(?:RAM|memory)\s+(?:is\s+)?(?:required|minimum|needed)",
            re.IGNORECASE,
        ),
        dimension_key="min_ram",
        question_template="What is the minimum RAM for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=1,
    ),
    QSPattern(
        name="maximum_connections",
        regex=re.compile(
            r"(?:maximum|max\.?)\s+(?:number\s+of\s+)?(?:concurrent\s+)?connections?\s+(?:is\s+)?(\d[\d,]*)",
            re.IGNORECASE,
        ),
        dimension_key="max_connections",
        question_template="What is the maximum number of connections for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
    QSPattern(
        name="maximum_value_generic",
        regex=re.compile(
            r"(?:maximum|max\.?)\s+(\w[\w\s]{2,20}?)\s+(?:is|of)\s+(\d[\d,.]*)\s*(\w+)?",
            re.IGNORECASE,
        ),
        dimension_key="max_{dim}",
        question_template="What is the maximum {dim} for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=2,
    ),

    # --- Protocol/technology requirements ---
    QSPattern(
        name="requires_protocol",
        regex=re.compile(
            r"requires?\s+(TLS|SSL|HTTPS?|SSH|SFTP|LDAPS?|OAuth\s*2?\.?0?|SAML|Kerberos)\s*(\d[\d.]*)?",
            re.IGNORECASE,
        ),
        dimension_key="required_protocol",
        question_template="What protocol does {subject} require?",
        value_type=QSValueType.STRING,
    ),

    # --- Default values ---
    QSPattern(
        name="default_value",
        regex=re.compile(
            r"(?:the\s+)?default\s+(?:value\s+)?(?:is|=)\s+[\"']?(\w[\w\s./-]{0,30}?)[\"']?(?:\s*[.,;)]|$)",
            re.IGNORECASE,
        ),
        dimension_key="default_value",
        question_template="What is the default value for {subject}?",
        value_type=QSValueType.STRING,
    ),
    QSPattern(
        name="default_port",
        regex=re.compile(
            r"default\s+port\s+(?:(?:is|of)\s+)?(\d{2,5})",
            re.IGNORECASE,
        ),
        dimension_key="default_port",
        question_template="What is the default port for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Deprecation/end-of-support ---
    QSPattern(
        name="deprecated_since",
        regex=re.compile(
            r"deprecated\s+(?:since|as\s+of|in)\s+(\w[\w\s./-]{2,20})",
            re.IGNORECASE,
        ),
        dimension_key="deprecated_since",
        question_template="Since when is {subject} deprecated?",
        value_type=QSValueType.STRING,
    ),
    QSPattern(
        name="end_of_support",
        regex=re.compile(
            r"end\s+of\s+(?:mainstream\s+)?(?:support|maintenance|life)\s*(?::|is|date)?\s*(\w[\w\s./-]{2,20})",
            re.IGNORECASE,
        ),
        dimension_key="end_of_support",
        question_template="When is the end of support for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Timeout/retention ---
    QSPattern(
        name="timeout_value",
        regex=re.compile(
            r"(?:session\s+)?timeout\s+(?:is\s+)?(?:set\s+to\s+)?(\d+)\s*(seconds?|minutes?|hours?|ms|s|min|hrs?)",
            re.IGNORECASE,
        ),
        dimension_key="timeout",
        question_template="What is the timeout for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
    QSPattern(
        name="retention_period",
        regex=re.compile(
            r"(?:data\s+)?retention\s+(?:period\s+)?(?:is\s+)?(\d+)\s*(days?|months?|years?|weeks?)",
            re.IGNORECASE,
        ),
        dimension_key="retention_period",
        question_template="What is the retention period for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Limit values ---
    QSPattern(
        name="limit_generic",
        regex=re.compile(
            r"(?:hard|soft)?\s*limit\s+(?:is\s+|of\s+)?(\d[\d,.]*)\s*(\w+)?",
            re.IGNORECASE,
        ),
        dimension_key="limit",
        question_template="What is the limit for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # =================================================================
    # Patterns réglementaires
    # =================================================================

    # --- Amendes / Pénalités (montants absolus) ---
    QSPattern(
        name="fine_amount",
        regex=re.compile(
            r"(?:fines?|penalt(?:y|ies)|sanctions?)\s+.*?"
            r"(?:up\s+to\s+)?(?:[€$£]\s*|(?:EUR|USD|GBP)\s+)"
            r"(\d[\d.,]*\s*(?:million|billion|thousand|M|B|K)?)",
            re.IGNORECASE,
        ),
        dimension_key="fine_amount",
        question_template="What is the fine amount for {subject}?",
        value_type=QSValueType.STRING,
    ),
    # Variante : montant avant la devise ("35 million EUR")
    QSPattern(
        name="fine_amount_postfix",
        regex=re.compile(
            r"(?:fines?|penalt(?:y|ies)|sanctions?)\s+.*?"
            r"(?:up\s+to\s+)?(\d[\d.,]*\s*(?:million|billion|thousand|M|B|K)?)"
            r"\s*(?:EUR|€|\$|£|GBP|USD)",
            re.IGNORECASE,
        ),
        dimension_key="fine_amount",
        question_template="What is the fine amount for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Amendes / Pénalités (% du CA) ---
    QSPattern(
        name="fine_percent_turnover",
        regex=re.compile(
            r"(?:fines?|penalt(?:y|ies)|sanctions?|subject\s+to)\s+.*?"
            r"(?:up\s+to\s+)?(\d+(?:\.\d+)?)\s*%\s+(?:of\s+)?(?:(?:total\s+)?(?:worldwide\s+)?(?:global\s+)?)?"
            r"(?:annual\s+)?(?:turnover|revenue)",
            re.IGNORECASE,
        ),
        dimension_key="fine_percent_turnover",
        question_template="What is the fine as percentage of turnover for {subject}?",
        value_type=QSValueType.PERCENT,
    ),

    # --- Noncompliance penalties (reverse pattern : "up to X% of ... turnover") ---
    QSPattern(
        name="noncompliance_percent",
        regex=re.compile(
            r"(?:noncompliance|non-compliance|infringement)\s+.*?"
            r"(?:up\s+to|of)\s+(\d+(?:\.\d+)?)\s*%\s+(?:of\s+)?.*?(?:turnover|revenue)",
            re.IGNORECASE,
        ),
        dimension_key="fine_percent_turnover",
        question_template="What is the noncompliance penalty for {subject}?",
        value_type=QSValueType.PERCENT,
    ),

    # --- Délais de notification (breach notification within X hours/days) ---
    QSPattern(
        name="notification_deadline",
        regex=re.compile(
            r"(?:notif(?:y|ied|ication)|report(?:ed|ing)?)\s+.*?"
            r"(?:within|in|no\s+later\s+than)\s+(\d+)\s*(hours?|days?|weeks?|business\s+days?)",
            re.IGNORECASE,
        ),
        dimension_key="notification_deadline",
        question_template="What is the notification deadline for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Entrée en vigueur (X months/years after entry into force) ---
    QSPattern(
        name="effective_after_entry",
        regex=re.compile(
            r"(\d+)\s*(months?|years?)\s+after\s+(?:(?:the\s+)?(?:Act|regulation|directive|law)\s+)?"
            r"(?:(?:their|its?|the)\s+)?(?:enters?\s+into\s+force|entry\s+into\s+force|entry|adoption)",
            re.IGNORECASE,
        ),
        dimension_key="effective_delay",
        question_template="When does {subject} take effect after entry into force?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Dates d'effet concrètes (starting from / by DD Month YYYY) ---
    QSPattern(
        name="effective_date",
        regex=re.compile(
            r"(?:take\s+effect|come\s+into\s+effect|apply|applicable|enter\s+into\s+force)"
            r".*?(?:from|on|by|starting)\s+"
            r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        ),
        dimension_key="effective_date",
        question_template="What is the effective date for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Compliance deadline (have X months/years to comply) ---
    QSPattern(
        name="compliance_period",
        regex=re.compile(
            r"(?:have|will\s+have|granted|given|allowed)\s+(?:an?\s+)?(?:additional\s+)?"
            r"(\d+)\s*(months?|years?|days?)\s+to\s+comply",
            re.IGNORECASE,
        ),
        dimension_key="compliance_period",
        question_template="What is the compliance period for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Obligations "shall" avec délai (shall X within Y days/months) ---
    QSPattern(
        name="obligation_deadline",
        regex=re.compile(
            r"shall\s+.*?(?:within|in|no\s+later\s+than)\s+(\d+)\s*(hours?|days?|months?|weeks?|business\s+days?)",
            re.IGNORECASE,
        ),
        dimension_key="obligation_deadline",
        question_template="What is the obligation deadline for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Pourcentages concrets dans des claims factuelles ---
    QSPattern(
        name="factual_percentage",
        regex=re.compile(
            r"(\d+(?:\.\d+)?)\s*%\s+(?:of\s+)?(?:the\s+)?"
            r"((?:MSs?|member\s+states?|entities|organizations?|companies|respondents?|users?))",
            re.IGNORECASE,
        ),
        dimension_key="factual_stat",
        question_template="What percentage of {subject} is concerned?",
        value_type=QSValueType.PERCENT,
    ),

    # --- Référence Article réglementaire ---
    QSPattern(
        name="article_reference",
        regex=re.compile(
            r"(?:Article|Art\.?)\s+(\d+(?:\(\d+\))?(?:\([a-z]\))?)"
            r"(?:\s+(?:of\s+(?:the\s+)?)?(?:GDPR|AI\s*Act|eIDAS|NIS\s*2?|DORA|DSA|DMA|"
            r"(?:the\s+)?(?:regulation|directive|proposal)))?",
            re.IGNORECASE,
        ),
        dimension_key="article_ref",
        question_template="What does this Article require regarding {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Durée de validité/applicabilité (valid for X years) ---
    QSPattern(
        name="validity_period",
        regex=re.compile(
            r"(?:valid|applicable)\s+(?:for\s+)?(?:a\s+(?:period\s+of\s+)?)?(\d+)\s*(years?|months?|days?)",
            re.IGNORECASE,
        ),
        dimension_key="validity_period",
        question_template="What is the validity period for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # =================================================================
    # Patterns Cloud-native / Kubernetes
    # =================================================================

    # --- Feature graduated to GA/stable/beta ---
    QSPattern(
        name="graduated_to_stable",
        regex=re.compile(
            r"graduated\s+to\s+(?:GA|stable|beta)\s+(?:in\s+)?(?:(?:the\s+)?(?:Kubernetes|K8s)\s+)?v?(\d+\.\d+)",
            re.IGNORECASE,
        ),
        dimension_key="feature_maturity",
        question_template="When did {subject} graduate to stable/GA?",
        value_type=QSValueType.STRING,
    ),

    # --- Feature available/introduced since version ---
    QSPattern(
        name="available_since_version",
        regex=re.compile(
            r"(?:available|introduced|added|supported)\s+(?:since|in|from)\s+(?:Kubernetes\s+)?v?(\d+\.\d+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
        dimension_key="available_since",
        question_template="Since which version is {subject} available?",
        value_type=QSValueType.VERSION,
    ),

    # --- Beta/alpha since version ---
    QSPattern(
        name="feature_stage_since",
        regex=re.compile(
            r"(alpha|beta)\s+since\s+(?:Kubernetes\s+)?v?(\d+\.\d+)",
            re.IGNORECASE,
        ),
        dimension_key="feature_stage_since",
        question_template="Since which version is {subject} in alpha/beta?",
        value_type=QSValueType.VERSION,
        value_group=2,
    ),

    # --- Deprecated in/since version ---
    QSPattern(
        name="deprecated_in_version",
        regex=re.compile(
            r"deprecated\s+(?:since|in|as\s+of)\s+(?:Kubernetes\s+)?v?(\d+\.\d+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
        dimension_key="deprecated_since",
        question_template="Since which version is {subject} deprecated?",
        value_type=QSValueType.VERSION,
    ),

    # --- Removed in version ---
    QSPattern(
        name="removed_in_version",
        regex=re.compile(
            r"removed\s+in\s+(?:(?:Kubernetes|K8s|release)\s+)?v?(\d+\.\d+(?:\.\d+)?)",
            re.IGNORECASE,
        ),
        dimension_key="removed_in",
        question_template="In which version was {subject} removed?",
        value_type=QSValueType.VERSION,
    ),

    # --- Replaced by / use X instead ---
    QSPattern(
        name="replaced_by",
        regex=re.compile(
            r"(?:replaced|superseded|succeeded)\s+by\s+(?:the\s+)?(\w[\w\s.-]{2,40}?)(?:\s*[.,;)]|$)",
            re.IGNORECASE,
        ),
        dimension_key="replaced_by",
        question_template="What replaces {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Defaults to value ---
    QSPattern(
        name="defaults_to",
        regex=re.compile(
            r"defaults?\s+to\s+[`\"']?(\w[\w./:%-]{1,40}?)[`\"']?(?:\s+(?:for|when|if|by|on|in)\b|\s*[.,;)]|$)",
            re.IGNORECASE,
        ),
        dimension_key="default_value",
        question_template="What is the default value for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Default port (cloud-native services) ---
    QSPattern(
        name="default_port_listens",
        regex=re.compile(
            r"(?:listens?\s+on|serves?\s+on|binds?\s+to|exposes?)\s+(?:port\s+)?(\d{2,5})",
            re.IGNORECASE,
        ),
        dimension_key="default_port",
        question_template="What port does {subject} listen on?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Minimum/maximum replicas, nodes, pods ---
    QSPattern(
        name="min_replicas",
        regex=re.compile(
            r"(?:minimum|min\.?)\s+(?:number\s+of\s+)?(?:replicas?|instances?|nodes?|pods?)\s+(?:is\s+)?(\d+)",
            re.IGNORECASE,
        ),
        dimension_key="min_replicas",
        question_template="What is the minimum number of replicas/nodes for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
    QSPattern(
        name="max_pods_per_node",
        regex=re.compile(
            r"(?:maximum|max\.?)\s+(?:number\s+of\s+)?(?:pods?|containers?)\s+(?:per\s+node\s+)?(?:is\s+)?(\d+)",
            re.IGNORECASE,
        ),
        dimension_key="max_pods",
        question_template="What is the maximum number of pods for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Resource requests/limits (cpu, memory) ---
    QSPattern(
        name="resource_cpu_limit",
        regex=re.compile(
            r"(?:cpu|CPU)\s+(?:limit|request)\s+(?:is\s+|of\s+|=\s*)?[\"']?(\d+(?:\.\d+)?m?)[\"']?",
            re.IGNORECASE,
        ),
        dimension_key="cpu_resource",
        question_template="What is the CPU limit/request for {subject}?",
        value_type=QSValueType.STRING,
    ),
    QSPattern(
        name="resource_memory_limit",
        regex=re.compile(
            r"(?:memory|Memory)\s+(?:limit|request)\s+(?:is\s+|of\s+|=\s*)?[\"']?(\d+(?:\.\d+)?\s*(?:Mi|Gi|Ki|Ti|MB|GB))[\"']?",
            re.IGNORECASE,
        ),
        dimension_key="memory_resource",
        question_template="What is the memory limit/request for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Grace period / termination ---
    QSPattern(
        name="grace_period",
        regex=re.compile(
            r"(?:grace\s+period|terminationGracePeriodSeconds)\s+(?:is\s+|of\s+|=\s*|:\s*)?(\d+)\s*(seconds?|s)?",
            re.IGNORECASE,
        ),
        dimension_key="grace_period",
        question_template="What is the grace period for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- API version for resource kind ---
    QSPattern(
        name="api_version_resource",
        regex=re.compile(
            r"apiVersion:\s+(\S+/v\w+)",
            re.IGNORECASE,
        ),
        dimension_key="api_version",
        question_template="What is the API version for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Recommended/required number of X ---
    QSPattern(
        name="recommended_count",
        regex=re.compile(
            r"(?:recommended|suggested|advised)\s+(?:to\s+(?:have|run|use)\s+)?(?:at\s+least\s+)?(\d+)\s+"
            r"(nodes?|replicas?|instances?|control\s+plane)",
            re.IGNORECASE,
        ),
        dimension_key="recommended_count",
        question_template="What is the recommended number of {dim} for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Supported platforms/architectures ---
    QSPattern(
        name="supported_platform",
        regex=re.compile(
            r"(?:supports?|compatible\s+with|runs?\s+on)\s+"
            r"(Linux|Windows|amd64|arm64|x86_64|s390x|ppc64le|darwin)",
            re.IGNORECASE,
        ),
        dimension_key="supported_platform",
        question_template="What platforms does {subject} support?",
        value_type=QSValueType.STRING,
    ),

    # =========================================================================
    # Biomedical / Clinical Research patterns
    # =========================================================================

    # --- Median survival (OS, PFS, DFS) ---
    QSPattern(
        name="median_survival",
        regex=re.compile(
            r"median\s+(OS|PFS|DFS|overall\s+survival|progression[- ]free\s+survival|"
            r"disease[- ]free\s+survival)\s+(?:was\s+|of\s+|=\s*)?(\d+\.?\d*)\s*"
            r"(?:months?|mo|weeks?|wk|years?|yr)",
            re.IGNORECASE,
        ),
        dimension_key="median_survival",
        question_template="What is the median {dim} for {subject}?",
        value_type=QSValueType.NUMBER,
        value_group=2,
    ),

    # --- Overall/objective response rate (ORR, CR, PR) ---
    QSPattern(
        name="response_rate",
        regex=re.compile(
            r"(?:overall\s+response\s+rate|ORR|objective\s+response\s+rate|"
            r"complete\s+response(?:\s+rate)?|CR\s+rate|partial\s+response(?:\s+rate)?|"
            r"PR\s+rate)\s+(?:was\s+|of\s+|=\s*)?(\d+\.?\d*)\s*%",
            re.IGNORECASE,
        ),
        dimension_key="response_rate",
        question_template="What is the response rate for {subject}?",
        value_type=QSValueType.PERCENT,
    ),

    # --- Hazard ratio (HR) ---
    QSPattern(
        name="hazard_ratio",
        regex=re.compile(
            r"(?:hazard\s+ratio|HR)\s*(?:=|was|of|,)?\s*(\d+\.?\d*)\s*"
            r"(?:\(?\s*95\s*%?\s*CI\s*[,:;]?\s*(\d+\.?\d*)\s*[-\u2013]\s*(\d+\.?\d*)\s*\)?)?",
            re.IGNORECASE,
        ),
        dimension_key="hazard_ratio",
        question_template="What is the hazard ratio for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Clinical trial phase ---
    QSPattern(
        name="trial_phase",
        regex=re.compile(
            r"(?:phase\s+)(I{1,3}V?(?:/I{1,3}V?)?|[1-4](?:/[1-4])?)\s+"
            r"(?:clinical\s+)?(?:trial|study|investigation|research)",
            re.IGNORECASE,
        ),
        dimension_key="trial_phase",
        question_template="What phase of clinical trial was conducted for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- FDA/EMA approval ---
    QSPattern(
        name="regulatory_approval",
        regex=re.compile(
            r"(?:FDA|EMA|NMPA|MHRA|Health\s+Canada)[- ]?approved\s+"
            r"(?:in\s+)?(\d{4})|"
            r"(?:approved\s+by\s+(?:the\s+)?(?:FDA|EMA|NMPA|MHRA))\s+in\s+(\d{4})",
            re.IGNORECASE,
        ),
        dimension_key="approval_year",
        question_template="When was {subject} approved by regulatory authorities?",
        value_type=QSValueType.STRING,
    ),

    # --- Drug dosage ---
    QSPattern(
        name="drug_dosage",
        regex=re.compile(
            r"(?:dose|dosage|administered|given|received)\s+(?:of\s+|at\s+|was\s+)?"
            r"(\d+\.?\d*\s*(?:mg(?:/kg)?|ug|mcg|g|IU|U)(?:\s*(?:every|q)\s*\d+\s*(?:weeks?|days?|w|d))?)",
            re.IGNORECASE,
        ),
        dimension_key="dosage",
        question_template="What is the dosage used for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Biomarker threshold / cutoff ---
    QSPattern(
        name="biomarker_threshold",
        regex=re.compile(
            r"(?:PCT|procalcitonin|CRP|C[- ]reactive\s+protein|PD[- ]L1|"
            r"TMB|tumor\s+mutational\s+burden)\s+"
            r"(?:level\s+|value\s+|threshold\s+|cutoff\s+|cut[- ]off\s+)?"
            r"(?:of\s+|was\s+|above\s+|below\s+|[><=]+\s*)?"
            r"(\d+\.?\d*)\s*(ng/mL|ug/L|mg/L|mg/dL|%|mut/Mb)",
            re.IGNORECASE,
        ),
        dimension_key="biomarker_threshold",
        question_template="What is the threshold value for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Diagnostic sensitivity/specificity ---
    QSPattern(
        name="diagnostic_accuracy",
        regex=re.compile(
            r"(sensitivity|specificity|PPV|NPV|positive\s+predictive\s+value|"
            r"negative\s+predictive\s+value|AUC|AUROC)\s+"
            r"(?:was\s+|of\s+|=\s*)?(\d+\.?\d*)\s*%?",
            re.IGNORECASE,
        ),
        dimension_key="diagnostic_accuracy",
        question_template="What is the {dim} of {subject}?",
        value_type=QSValueType.PERCENT,
        value_group=2,
    ),

    # --- Sample size / enrollment ---
    QSPattern(
        name="sample_size",
        regex=re.compile(
            r"(?:enrolled|included|recruited|randomized|comprising)\s+"
            r"(\d[\d,]*)\s+(?:patients?|participants?|subjects?|individuals?)",
            re.IGNORECASE,
        ),
        dimension_key="sample_size",
        question_template="How many patients were enrolled in {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- p-value / statistical significance ---
    QSPattern(
        name="p_value",
        regex=re.compile(
            r"(?:p\s*[<>=]\s*|p[- ]value\s*(?:of\s+|was\s+|=\s*)?)(\d*\.?\d+(?:e[- ]?\d+)?)",
            re.IGNORECASE,
        ),
        dimension_key="p_value",
        question_template="What is the statistical significance (p-value) for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Relative reduction (reduced by X%, X-fold) ---
    QSPattern(
        name="relative_reduction",
        regex=re.compile(
            r"(?:reduced?|decreased?|lowered?)\s+(?:\w+\s+)?(?:by\s+)?(\d+\.?\d*)\s*(%|[- ]?fold|percent)",
            re.IGNORECASE,
        ),
        dimension_key="relative_reduction",
        question_template="By how much did {subject} reduce the outcome?",
        value_type=QSValueType.PERCENT,
    ),

    # --- CRISPR editing efficiency ---
    QSPattern(
        name="editing_efficiency",
        regex=re.compile(
            r"(?:editing|knockout|knockdown|indel|gene\s+disruption)\s+"
            r"(?:efficiency|rate)\s+(?:of\s+|was\s+|=\s*|reached\s+)?(\d+\.?\d*)\s*%",
            re.IGNORECASE,
        ),
        dimension_key="editing_efficiency",
        question_template="What is the editing efficiency for {subject}?",
        value_type=QSValueType.PERCENT,
    ),

    # --- Microbiome abundance / ratio ---
    QSPattern(
        name="microbiome_abundance",
        regex=re.compile(
            r"(?:relative\s+abundance|abundance)\s+(?:of\s+)?"
            r"([A-Z][a-z]+(?:\s+[a-z]+)?)\s+"  # genus/species name
            r"(?:was\s+|=\s*|of\s+)?(\d+\.?\d*)\s*%",
            re.IGNORECASE,
        ),
        dimension_key="microbiome_abundance",
        question_template="What is the abundance of {dim} in {subject}?",
        value_type=QSValueType.PERCENT,
        value_group=2,
    ),

    # --- Clinical trial ID (NCT) ---
    QSPattern(
        name="clinical_trial_id",
        regex=re.compile(
            r"(NCT\d{8,})",
            re.IGNORECASE,
        ),
        dimension_key="trial_id",
        question_template="What is the clinical trial ID for {subject}?",
        value_type=QSValueType.STRING,
    ),

    # --- Number needed to treat (NNT) ---
    QSPattern(
        name="number_needed_to_treat",
        regex=re.compile(
            r"(?:number\s+needed\s+to\s+treat|NNT)\s*(?:=|was|of|,)?\s*(\d+\.?\d*)",
            re.IGNORECASE,
        ),
        dimension_key="nnt",
        question_template="What is the NNT for {subject}?",
        value_type=QSValueType.NUMBER,
    ),

    # --- Mortality rate ---
    QSPattern(
        name="mortality_rate",
        regex=re.compile(
            r"(?:mortality|death)\s+(?:rate\s+)?(?:was\s+|of\s+|=\s*)?(\d+\.?\d*)\s*%",
            re.IGNORECASE,
        ),
        dimension_key="mortality_rate",
        question_template="What is the mortality rate for {subject}?",
        value_type=QSValueType.PERCENT,
    ),

    # --- Antibiotic duration reduction ---
    QSPattern(
        name="antibiotic_duration",
        regex=re.compile(
            r"(?:antibiotic|antimicrobial|treatment)\s+(?:duration|course|exposure)\s+"
            r"(?:was\s+)?(?:reduced\s+(?:to|by)\s+|of\s+|shortened\s+(?:to|by)\s+)?"
            r"(\d+\.?\d*)\s*(?:days?|d|hours?|h)",
            re.IGNORECASE,
        ),
        dimension_key="antibiotic_duration",
        question_template="What is the antibiotic treatment duration for {subject}?",
        value_type=QSValueType.NUMBER,
    ),
]


# =============================================================================
# Extractor
# =============================================================================


MAX_QS_PER_DOC = 50


def extract_question_signatures_level_a(
    claims: List[Any],
    doc_id: str,
    tenant_id: str = "default",
) -> List[QuestionSignature]:
    """
    Extrait des QuestionSignatures Level A (regex) depuis une liste de claims.

    Args:
        claims: Liste de claims (doivent avoir .claim_id, .text, .structured_form)
        doc_id: ID du document
        tenant_id: Tenant ID

    Returns:
        Liste de QuestionSignatures (max MAX_QS_PER_DOC par document)
    """
    results: List[QuestionSignature] = []
    seen_keys: set = set()  # Déduplicate dimension_key+value par doc

    for claim in claims:
        text = getattr(claim, "text", "") or ""
        claim_id = getattr(claim, "claim_id", "")
        sf = getattr(claim, "structured_form", None) or {}

        if not text or len(text) < 20:
            continue

        subject = sf.get("subject", "")

        for pattern in LEVEL_A_PATTERNS:
            match = pattern.regex.search(text)
            if not match:
                continue

            # Extraire la valeur
            try:
                raw_value = match.group(pattern.value_group).strip()
            except (IndexError, AttributeError):
                continue

            if not raw_value or len(raw_value) > 50:
                continue

            # Dimension key (résoudre {dim} pour les patterns génériques)
            dim_key = pattern.dimension_key
            if "{dim}" in dim_key:
                dim_part = match.group(1).strip().lower()
                dim_part = re.sub(r"[^a-z0-9]+", "_", dim_part).strip("_")[:30]
                dim_key = dim_key.replace("{dim}", dim_part)

            # Déduplication par dimension_key + valeur
            dedup_key = f"{dim_key}:{raw_value}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            # Construire la question
            question = pattern.question_template.replace("{subject}", subject or "this component")
            if "{dim}" in question:
                dim_label = match.group(1).strip() if match.lastindex >= 1 else ""
                question = question.replace("{dim}", dim_label)

            qs = QuestionSignature(
                qs_id=f"qs_{claim_id}_{pattern.name}",
                claim_id=claim_id,
                doc_id=doc_id,
                tenant_id=tenant_id,
                question=question,
                dimension_key=dim_key,
                value_type=pattern.value_type,
                extracted_value=raw_value,
                extraction_level=QSExtractionLevel.LEVEL_A,
                pattern_name=pattern.name,
                confidence=1.0,
                scope_subject=subject or None,
            )
            results.append(qs)

            if len(results) >= MAX_QS_PER_DOC:
                logger.info(
                    f"[OSMOSE:QS] Cap atteint: {MAX_QS_PER_DOC} QS pour doc {doc_id}"
                )
                return results

    logger.info(
        f"[OSMOSE:QS] Extracted {len(results)} QuestionSignatures (Level A) "
        f"from doc {doc_id}"
    )
    return results


__all__ = [
    "LEVEL_A_PATTERNS",
    "QSPattern",
    "MAX_QS_PER_DOC",
    "extract_question_signatures_level_a",
]
