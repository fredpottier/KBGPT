# -*- coding: utf-8 -*-
"""
⚠️  DEPRECATED - Migré vers config/ontologies/solutions.yaml

Dictionnaire des solutions SAP avec noms canoniques et alias etendus.
Peut etre utilise pour le fuzzy matching afin de normaliser les noms detectes
dans les documents injectes dans la knowledge base.

Ce fichier est conservé pour compatibilité mais les données ont été migrées
vers le nouveau système d'ontologies YAML (config/ontologies/solutions.yaml).
"""

import warnings

warnings.warn(
    "solutions_dict.py est déprécié. Les données ont été migrées vers config/ontologies/solutions.yaml",
    DeprecationWarning,
    stacklevel=2
)

SAP_SOLUTIONS = {
    # --- ERP ---
    "S4HANA_PCE": {
        "canonical_name": "SAP S/4HANA Cloud, Private Edition",
        "aliases": [
            "S/4HANA PCE",
            "Private Cloud Edition",
            "RISE Private Cloud",
            "ERP Cloud Private Edition",
            "Private ERP Cloud",
            "S4 PCE",
        ],
    },
    "S4HANA_PUBLIC": {
        "canonical_name": "SAP S/4HANA Cloud, Public Edition",
        "aliases": [
            "S/4HANA Public Cloud",
            "S4 Public",
            "Essentials Edition",
            "ERP Cloud Public Edition",
            "SAP Cloud ERP",
            "SAP S/4HANA Cloud",
            "S/4HANA Cloud",
        ],
    },
    "S4HANA_ONPREM": {
        "canonical_name": "SAP S/4HANA (On-Premise)",
        "aliases": ["S/4HANA On-Premise", "S/4 on-prem", "On-Prem ERP"],
    },
    "SAP_ECC6": {
        "canonical_name": "SAP ERP 6.0 (SAP ECC 6.0)",
        "aliases": ["SAP ECC", "ERP Central Component", "ECC6", "SAP ERP"],
    },
    "SAP_R3": {
        "canonical_name": "SAP R/3 (Enterprise)",
        "aliases": ["R/3", "SAP R/3 4.x", "SAP ERP (R/3)"],
    },
    "BUSINESS_ONE": {
        "canonical_name": "SAP Business One",
        "aliases": ["SAP B1", "Business One"],
    },
    "BYDESIGN": {
        "canonical_name": "SAP Business ByDesign",
        "aliases": ["SAP ByD", "ByDesign"],
    },
    # --- Data & Risk Compliance ---
    "SAP_DRC": {
        "canonical_name": "SAP Document and Reporting Compliance",
        "aliases": [
            "SAP DRC",
            "Document & Reporting Compliance",
            "ACR",
            "Advanced Compliance Reporting",
        ],
    },
    "SAP_GRC": {
        "canonical_name": "SAP Governance, Risk and Compliance",
        "aliases": ["SAP GRC", "Governance Risk & Compliance"],
    },
    "ACCESS_CTRL": {
        "canonical_name": "SAP Access Control",
        "aliases": ["GRC Access Control", "SAP GRC AC"],
    },
    "PROCESS_CTRL": {
        "canonical_name": "SAP Process Control",
        "aliases": ["GRC Process Control", "SAP GRC PC"],
    },
    "RISK_MGMT": {
        "canonical_name": "SAP Risk Management",
        "aliases": ["GRC Risk Management", "SAP GRC RM"],
    },
    "AUDIT_MGMT": {
        "canonical_name": "SAP Audit Management",
        "aliases": ["GRC Audit Management", "Audit Mgmt"],
    },
    "SAP_GTS": {
        "canonical_name": "SAP Global Trade Services",
        "aliases": ["SAP GTS", "Global Trade Services"],
    },
    # --- HR ---
    "SUCCESSFACTORS": {
        "canonical_name": "SAP SuccessFactors HXM Suite",
        "aliases": ["SuccessFactors", "SAP SF", "HXM Suite"],
    },
    "SAP_HCM": {
        "canonical_name": "SAP ERP Human Capital Management",
        "aliases": ["SAP HCM", "SAP HR", "SAP ECC HR"],
    },
    "SAP_FIELDGLASS": {
        "canonical_name": "SAP Fieldglass",
        "aliases": ["Fieldglass", "SAP Fieldglass Network"],
    },
    # --- Finance ---
    "SAP_CONCUR": {
        "canonical_name": "SAP Concur",
        "aliases": ["Concur", "Concur Travel", "Concur Expense"],
    },
    "SAP_BPC": {
        "canonical_name": "SAP Business Planning and Consolidation",
        "aliases": ["SAP BPC", "BPC"],
    },
    "SAP_GROUPRPT": {
        "canonical_name": "SAP S/4HANA for Group Reporting",
        "aliases": ["Group Reporting", "Financial Consolidation"],
    },
    # --- Customer Experience ---
    "SAP_CX_SUITE": {
        "canonical_name": "SAP Customer Experience Suite",
        "aliases": ["SAP CX", "SAP C/4HANA", "Customer Experience"],
    },
    "SAP_SALES_CLOUD": {
        "canonical_name": "SAP Sales Cloud",
        "aliases": ["Sales Cloud", "Cloud for Customer Sales", "C4C Sales"],
    },
    "SAP_SERVICE_CLOUD": {
        "canonical_name": "SAP Service Cloud",
        "aliases": ["Service Cloud", "Cloud for Customer Service", "C4C Service"],
    },
    "SAP_MARKETING_CLOUD": {
        "canonical_name": "SAP Marketing Cloud",
        "aliases": ["Marketing Cloud"],
    },
    "SAP_COMMERCE_CLOUD": {
        "canonical_name": "SAP Commerce Cloud",
        "aliases": ["Commerce Cloud", "SAP Hybris", "Hybris Commerce"],
    },
    "SAP_CDC": {
        "canonical_name": "SAP Customer Data Cloud",
        "aliases": ["Customer Data Cloud", "Gigya"],
    },
    "SAP_CRM": {
        "canonical_name": "SAP Customer Relationship Management",
        "aliases": ["SAP CRM", "SAP Customer Management"],
    },
    # --- Procurement ---
    "SAP_ARIBA": {"canonical_name": "SAP Ariba", "aliases": ["Ariba", "Ariba Network"]},
    "SAP_SRM": {
        "canonical_name": "SAP Supplier Relationship Management",
        "aliases": ["SAP SRM", "Supplier Relationship Mgmt"],
    },
    "SAP_SLC": {
        "canonical_name": "SAP Business Network (Supplier Lifecycle Collaboration)",
        "aliases": ["SAP SLC", "Supplier Lifecycle Collaboration"],
    },
    # --- Analytics ---
    "SAP_SAC": {
        "canonical_name": "SAP Analytics Cloud",
        "aliases": ["SAC", "Analytics Cloud", "SAP BusinessObjects Cloud"],
    },
    "SAP_BO": {
        "canonical_name": "SAP BusinessObjects BI Platform",
        "aliases": ["SAP BO", "BOBJ", "BusinessObjects"],
    },
    "SAP_BW4HANA": {"canonical_name": "SAP BW/4HANA", "aliases": ["BW/4HANA", "BW4"]},
    "SAP_BW": {
        "canonical_name": "SAP Business Warehouse",
        "aliases": ["SAP BW", "Business Warehouse"],
    },
    "SAP_DATASPHERE": {
        "canonical_name": "SAP Datasphere",
        "aliases": ["Datasphere", "SAP Data Warehouse Cloud", "SAP DWC"],
    },
    # --- LeanIX ---
    "LEANIX_APM": {
        "canonical_name": "SAP LeanIX Application Portfolio Management",
        "aliases": ["LeanIX APM", "Application Portfolio Mgmt"],
    },
    "LEANIX_TRC": {
        "canonical_name": "SAP LeanIX Technology Risk and Compliance",
        "aliases": ["LeanIX TRC", "Technology Risk & Compliance"],
    },
    "LEANIX_ARP": {
        "canonical_name": "SAP LeanIX Architecture & Road Map Planning",
        "aliases": ["LeanIX Roadmap Planning", "Architecture & Roadmap"],
    },
}
