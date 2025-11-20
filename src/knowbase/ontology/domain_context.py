"""
DomainContextPersonalizer - Phase 2 Module Fondation

Permet la personnalisation du contexte métier par tenant sans compromettre
la généricité du moteur.

Architecture:
- DomainContextProfile: Modèle Pydantic profil contexte métier
- DomainContextExtractor: Extraction LLM texte libre → profil structuré
- DomainContextStore: Persistence Neo4j
- DomainContextInjector: Middleware injection dans prompts LLM

Principe:
- Code moteur: Domain-agnostic (aucun biais hardcodé)
- Contexte utilisateur: Domain-specific (personnalisé par tenant)
- Injection dynamique: Contexte injecté automatiquement dans prompts LLM
"""

from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional, Literal
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DomainContextProfile(BaseModel):
    """
    Profil contexte métier pour un tenant.

    Extrait automatiquement depuis description textuelle libre via LLM.
    Utilisé pour injection dynamique dans tous les prompts LLM du système.

    Example:
        >>> profile = DomainContextProfile(
        ...     tenant_id="sap_sales",
        ...     domain_summary="SAP enterprise software ecosystem",
        ...     industry="enterprise_software",
        ...     common_acronyms={"SAC": "SAP Analytics Cloud", "BTP": "Business Technology Platform"},
        ...     key_concepts=["SAP S/4HANA", "SuccessFactors"],
        ...     llm_injection_prompt="You are analyzing SAP ecosystem documents..."
        ... )
    """

    tenant_id: str = Field(
        ...,
        description="Tenant ID unique",
        min_length=1,
        max_length=100
    )

    domain_summary: str = Field(
        ...,
        description="Résumé concis du domaine métier (1-2 phrases)",
        min_length=10,
        max_length=500
    )

    industry: str = Field(
        ...,
        description="Industrie principale (enterprise_software, pharmaceutical, retail, etc.)",
        min_length=2,
        max_length=100
    )

    sub_domains: List[str] = Field(
        default_factory=list,
        description="Sous-domaines spécifiques (ex: ['ERP', 'HCM', 'Analytics'])",
        max_length=20
    )

    target_users: List[str] = Field(
        default_factory=list,
        description="Profils utilisateurs cibles (ex: ['consultants', 'solution_architects'])",
        max_length=10
    )

    document_types: List[str] = Field(
        default_factory=list,
        description="Types documents traités (ex: ['technical', 'marketing', 'functional'])",
        max_length=10
    )

    common_acronyms: Dict[str, str] = Field(
        default_factory=dict,
        description="Acronymes courants → Expansions (max 50 entrées)"
    )

    key_concepts: List[str] = Field(
        default_factory=list,
        description="Concepts clés du domaine à reconnaître prioritairement (max 20)",
        max_length=20
    )

    context_priority: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Priorité injection contexte dans prompts LLM"
    )

    llm_injection_prompt: str = Field(
        ...,
        description="Texte prêt pour injection dans prompts système LLM",
        min_length=20,
        max_length=2000
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date création profil"
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date dernière mise à jour"
    )

    @field_validator("common_acronyms")
    @classmethod
    def validate_acronyms_limit(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Limite nombre d'acronymes à 50 max."""
        if len(v) > 50:
            logger.warning(
                f"Too many acronyms ({len(v)}), keeping only first 50"
            )
            return dict(list(v.items())[:50])
        return v

    @field_validator("llm_injection_prompt")
    @classmethod
    def validate_injection_prompt_quality(cls, v: str) -> str:
        """Valide qualité prompt injection."""
        if len(v.strip()) < 20:
            raise ValueError(
                "llm_injection_prompt must be at least 20 characters (meaningful context)"
            )
        return v.strip()

    def to_neo4j_properties(self) -> Dict:
        """
        Convertit profil en propriétés Neo4j.

        Returns:
            Dict compatible Neo4j (JSON serialization pour listes/dicts)
        """
        import json

        return {
            "tenant_id": self.tenant_id,
            "domain_summary": self.domain_summary,
            "industry": self.industry,
            "sub_domains": json.dumps(self.sub_domains),
            "target_users": json.dumps(self.target_users),
            "document_types": json.dumps(self.document_types),
            "common_acronyms": json.dumps(self.common_acronyms),
            "key_concepts": json.dumps(self.key_concepts),
            "context_priority": self.context_priority,
            "llm_injection_prompt": self.llm_injection_prompt,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_neo4j_properties(cls, props: Dict) -> "DomainContextProfile":
        """
        Crée profil depuis propriétés Neo4j.

        Args:
            props: Propriétés Neo4j node

        Returns:
            DomainContextProfile instance
        """
        import json

        return cls(
            tenant_id=props["tenant_id"],
            domain_summary=props["domain_summary"],
            industry=props["industry"],
            sub_domains=json.loads(props.get("sub_domains", "[]")),
            target_users=json.loads(props.get("target_users", "[]")),
            document_types=json.loads(props.get("document_types", "[]")),
            common_acronyms=json.loads(props.get("common_acronyms", "{}")),
            key_concepts=json.loads(props.get("key_concepts", "[]")),
            context_priority=props.get("context_priority", "medium"),
            llm_injection_prompt=props["llm_injection_prompt"],
            created_at=datetime.fromisoformat(props["created_at"]),
            updated_at=datetime.fromisoformat(props["updated_at"])
        )

    class Config:
        json_schema_extra = {
            "example": {
                "tenant_id": "sap_emea_sales",
                "domain_summary": "Enterprise software ecosystem focusing on SAP cloud products and integrations",
                "industry": "enterprise_software",
                "sub_domains": ["ERP", "HCM", "Analytics", "Integration Platform"],
                "target_users": ["consultants", "solution_architects", "pre_sales"],
                "document_types": ["technical", "marketing", "functional"],
                "common_acronyms": {
                    "SAC": "SAP Analytics Cloud",
                    "BTP": "Business Technology Platform",
                    "SF": "SuccessFactors",
                    "HCM": "Human Capital Management"
                },
                "key_concepts": [
                    "SAP S/4HANA",
                    "SuccessFactors",
                    "Concur",
                    "SAP Analytics Cloud",
                    "Business Technology Platform"
                ],
                "context_priority": "high",
                "llm_injection_prompt": "You are analyzing documents from SAP enterprise software ecosystem. Common products include S/4HANA (ERP), SuccessFactors (HCM), SAP Analytics Cloud (BI), and Business Technology Platform (integration). When you see acronyms like SAC, BTP, SF, or HCM, interpret them in this SAP context unless context clearly suggests otherwise."
            }
        }


__all__ = ["DomainContextProfile"]
