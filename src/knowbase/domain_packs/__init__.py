# src/knowbase/domain_packs/__init__.py
"""
Domain Packs — Packages métier activables OSMOSE.

INV-PACK : Le pack augmente le recall. Le core garde le monopole de la décision.
INV-CONFLICT : Conflit inter-pack → marque ambigu, review admin.
INV-PERSIST : Aucun artefact pack persiste sans passage par les gates core.
"""

from knowbase.domain_packs.base import DomainPack, DomainEntityExtractor
from knowbase.domain_packs.registry import PackRegistry, get_pack_registry

__all__ = [
    "DomainPack",
    "DomainEntityExtractor",
    "PackRegistry",
    "get_pack_registry",
]
