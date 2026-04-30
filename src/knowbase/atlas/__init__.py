"""
Atlas narratif — Pipeline de génération.

Module qui consomme les Perspectives V2 existantes pour produire un Atlas
documentaire structuré (AtlasHomepage, AtlasRoot, NarrativeTopic) avec
contenu prose rédigé par LLM.

Conformément à memory project_atlas_narratif.md : sortir du modèle "1 entité
= 1 article" pour passer à un Atlas narratif (10-20 articles avec sections
dérivées des Perspectives V2).
"""
from knowbase.atlas.generator import (
    AtlasGenerator,
    AtlasGenerationStats,
)

__all__ = ["AtlasGenerator", "AtlasGenerationStats"]
