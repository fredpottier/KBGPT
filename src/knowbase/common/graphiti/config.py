"""
Configuration Graphiti avec variables d'environnement
"""
import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class GraphitiConfig:
    """Configuration Graphiti avec valeurs par défaut"""

    # Connexion Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    # API Anthropic pour LLM
    anthropic_api_key: Optional[str] = None

    # Configuration multi-tenant
    default_group_id: str = "default"
    enable_group_isolation: bool = True

    # Paramètres de performance
    search_limit_default: int = 20
    subgraph_depth_default: int = 2
    memory_limit_default: int = 50

    @classmethod
    def from_env(cls) -> "GraphitiConfig":
        """
        Crée la configuration depuis les variables d'environnement

        Variables supportées:
        - GRAPHITI_NEO4J_URI
        - GRAPHITI_NEO4J_USER
        - GRAPHITI_NEO4J_PASSWORD
        - ANTHROPIC_API_KEY (réutilise celle existante)
        - GRAPHITI_DEFAULT_GROUP_ID
        - GRAPHITI_ENABLE_GROUP_ISOLATION
        """
        return cls(
            neo4j_uri=os.getenv("GRAPHITI_NEO4J_URI", "bolt://localhost:7687"),
            neo4j_user=os.getenv("GRAPHITI_NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("GRAPHITI_NEO4J_PASSWORD", "password"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            default_group_id=os.getenv("GRAPHITI_DEFAULT_GROUP_ID", "default"),
            enable_group_isolation=os.getenv("GRAPHITI_ENABLE_GROUP_ISOLATION", "true").lower() == "true",
            search_limit_default=int(os.getenv("GRAPHITI_SEARCH_LIMIT", "20")),
            subgraph_depth_default=int(os.getenv("GRAPHITI_SUBGRAPH_DEPTH", "2")),
            memory_limit_default=int(os.getenv("GRAPHITI_MEMORY_LIMIT", "50"))
        )

    def validate(self) -> None:
        """Valide la configuration"""
        if not self.neo4j_uri:
            raise ValueError("Neo4j URI requis")

        if not self.neo4j_user:
            raise ValueError("Utilisateur Neo4j requis")

        if not self.neo4j_password:
            raise ValueError("Mot de passe Neo4j requis")

        if not self.anthropic_api_key:
            raise ValueError("Clé API Anthropic requise pour Graphiti")


# Instance globale de configuration
graphiti_config = GraphitiConfig.from_env()