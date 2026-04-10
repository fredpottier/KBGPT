"""
Domain Pack: Regulatory & Legal Documents.

NER via GLiNER zero-shot for regulations, laws, compliance standards.
Gazetteer: 55+ regulations worldwide (GDPR, AI Act, CCPA, PIPL, etc.)
Aliases: 45+ canonical mappings (RGPD→GDPR, AI Act→EU AI Act, etc.)
"""

from knowbase.domain_packs.regulatory.pack import RegulatoryPack

__all__ = ["RegulatoryPack"]
