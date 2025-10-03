"""
Neo4j Native Custom Layer

Ce module fournit une couche d'abstraction custom pour Neo4j,
adaptée aux besoins spécifiques du projet (Facts governance).

Composants:
- client.py: Neo4jCustomClient (wrapper driver Neo4j)
- schemas.py: Schémas Cypher (Facts, Entities, Relations)
- queries.py: Requêtes Cypher réutilisables
- migrations.py: Gestion migrations schéma
"""

__version__ = "1.0.0"
