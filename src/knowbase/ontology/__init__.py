"""
Package gestion ontologies Neo4j.

Module pour stocker et gérer les ontologies d'entités dans Neo4j.
"""
from .neo4j_schema import OntologySchema, apply_ontology_schema

__all__ = [
    "OntologySchema",
    "apply_ontology_schema",
]
