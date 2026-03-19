# src/knowbase/domain_packs/enterprise_sap/__init__.py
"""
Domain Pack SAP Enterprise — Ecosysteme SAP.

NER zero-shot via GLiNER (urchade/gliner_medium-v2.1) + gazetteer produits SAP.
Detecte SAP_PRODUCT, SAP_MODULE, SAP_SERVICE, SAP_PLATFORM, TECHNOLOGY_STANDARD, CERTIFICATION.
"""

from knowbase.domain_packs.enterprise_sap.pack import EnterpriseSapPack

__all__ = ["EnterpriseSapPack"]
