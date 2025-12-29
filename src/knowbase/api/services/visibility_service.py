"""
Phase 2.12 - Visibility Service

Implements Couche 3 (Politique) of the Agnostic KG Architecture.
Filters relations based on visibility profiles.

4 Profiles:
- verified: Only validated facts (2+ sources)
- balanced: Validated + reliable candidates (default)
- exploratory: Maximum connections for discovery
- full_access: Admin access, no filters

See: doc/ongoing/KG_AGNOSTIC_ARCHITECTURE.md

Author: Claude Code
Date: 2025-12-26
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


# =============================================================================
# MODELS
# =============================================================================

class ProfileSettings(BaseModel):
    """Technical settings for a visibility profile."""
    min_maturity: str = "CANDIDATE"
    min_confidence: float = 0.5
    min_source_count: int = 1
    allowed_maturities: List[str] = Field(
        default_factory=lambda: ["VALIDATED", "CANDIDATE"]
    )
    show_conflicts: bool = False
    show_context_dependent: bool = True
    show_ambiguous: bool = False


class ProfileUI(BaseModel):
    """UI display settings for a profile."""
    show_maturity_badge: bool = True
    show_confidence: bool = True
    show_source_count: bool = True
    show_internal_ids: bool = False
    show_timestamps: bool = False
    mandatory_disclaimer: bool = False
    disclaimer_text: Optional[str] = None
    filtered_count_visible: bool = False


class VisibilityProfile(BaseModel):
    """Complete visibility profile definition."""
    id: str
    icon: str = ""
    name: str
    short_description: str = ""
    explanation: str = ""
    settings: ProfileSettings = Field(default_factory=ProfileSettings)
    ui: ProfileUI = Field(default_factory=ProfileUI)


class VisibleRelation(BaseModel):
    """A relation that passed visibility filtering."""
    relation_type: str
    source_concept_id: str
    source_concept_name: Optional[str] = None
    target_concept_id: str
    target_concept_name: Optional[str] = None
    maturity: str
    confidence: float
    source_count: int
    predicate_norm: Optional[str] = None
    canonical_relation_id: str
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class VisibilityResult(BaseModel):
    """Result of visibility filtering."""
    profile_id: str
    profile_name: str
    visible_relations: List[VisibleRelation]
    total_relations: int
    filtered_count: int
    ui_settings: ProfileUI
    disclaimer: Optional[str] = None


class ProfileSummary(BaseModel):
    """Summary of a profile for UI display."""
    id: str
    icon: str
    name: str
    short_description: str
    explanation: str
    is_current: bool = False


# =============================================================================
# SERVICE
# =============================================================================

class VisibilityService:
    """
    Applies visibility profiles to KG queries.

    Couche 3 of the 5-layer agnostic architecture.
    Uses simple behavioral profiles instead of domain-specific policies.

    Profiles:
    - verified: Maximum reliability, only multi-source validated
    - balanced: Good balance for everyday use (default)
    - exploratory: Maximum discovery, shows more
    - full_access: Admin mode, no filters
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default",
        config_path: Optional[str] = None
    ):
        """
        Initialize visibility service.

        Args:
            neo4j_client: Neo4j client instance
            tenant_id: Tenant ID for multi-tenancy
            config_path: Path to visibility_policies.yaml
        """
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id

        # Load configuration
        if config_path is None:
            config_path = self._find_config_file()
        self.config = self._load_config(config_path)

        # Parse profiles
        self.profiles: Dict[str, VisibilityProfile] = {}
        self._parse_profiles()

        # Get tenant profile mapping
        self.tenant_profiles = self.config.get("tenant_profiles", {"default": "balanced"})
        self.default_profile = self.config.get("default_profile", "balanced")

    def _find_config_file(self) -> str:
        """Find the visibility_policies.yaml file."""
        possible_paths = [
            Path("config/visibility_policies.yaml"),
            Path("/app/config/visibility_policies.yaml"),
            Path(__file__).parent.parent.parent.parent.parent / "config" / "visibility_policies.yaml"
        ]

        for path in possible_paths:
            if path.exists():
                return str(path)

        logger.warning("[VisibilityService] Config file not found, using defaults")
        return ""

    def _load_config(self, path: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not path:
            return {"profiles": {}, "default_profile": "balanced"}

        try:
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                logger.info(f"[VisibilityService] Loaded config from {path}")
                return config or {}
        except Exception as e:
            logger.warning(f"[VisibilityService] Could not load config: {e}")
            return {"profiles": {}, "default_profile": "balanced"}

    def _parse_profiles(self) -> None:
        """Parse profiles from configuration."""
        profiles_config = self.config.get("profiles", {})

        for profile_id, profile_data in profiles_config.items():
            try:
                settings_data = profile_data.get("settings", {})
                ui_data = profile_data.get("ui", {})

                self.profiles[profile_id] = VisibilityProfile(
                    id=profile_data.get("id", profile_id),
                    icon=profile_data.get("icon", ""),
                    name=profile_data.get("name", profile_id),
                    short_description=profile_data.get("short_description", ""),
                    explanation=profile_data.get("explanation", ""),
                    settings=ProfileSettings(**settings_data),
                    ui=ProfileUI(**ui_data)
                )
            except Exception as e:
                logger.warning(f"[VisibilityService] Error parsing profile {profile_id}: {e}")

        # Ensure we have at least a default profile
        if "balanced" not in self.profiles:
            self.profiles["balanced"] = VisibilityProfile(
                id="balanced",
                name="Équilibré",
                short_description="Profil par défaut"
            )

    def get_profile(self, profile_id: str) -> VisibilityProfile:
        """Get a specific profile by ID."""
        return self.profiles.get(profile_id, self.profiles.get("balanced"))

    def get_profile_for_tenant(self, tenant_id: Optional[str] = None) -> str:
        """Get the profile ID for a tenant."""
        tenant = tenant_id or self.tenant_id
        return self.tenant_profiles.get(tenant, self.default_profile)

    def list_profiles(self, current_profile_id: Optional[str] = None) -> List[ProfileSummary]:
        """
        List all available profiles with their descriptions.

        Args:
            current_profile_id: ID of the currently active profile

        Returns:
            List of ProfileSummary for UI display
        """
        summaries = []
        # Order: verified, balanced, exploratory, full_access
        order = ["verified", "balanced", "exploratory", "full_access"]

        for profile_id in order:
            if profile_id in self.profiles:
                profile = self.profiles[profile_id]
                summaries.append(ProfileSummary(
                    id=profile.id,
                    icon=profile.icon,
                    name=profile.name,
                    short_description=profile.short_description,
                    explanation=profile.explanation,
                    is_current=(profile_id == current_profile_id)
                ))

        return summaries

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def get_visible_relations(
        self,
        concept_id: str,
        profile_id: Optional[str] = None,
        direction: str = "both",
        limit: int = 100
    ) -> VisibilityResult:
        """
        Get visible relations for a concept according to profile.

        Args:
            concept_id: The concept ID to get relations for
            profile_id: Profile to apply (uses tenant default if None)
            direction: "outgoing", "incoming", or "both"
            limit: Maximum relations to return

        Returns:
            VisibilityResult with filtered relations
        """
        # Determine profile
        if profile_id is None:
            profile_id = self.get_profile_for_tenant()
        profile = self.get_profile(profile_id)

        # Build query based on direction
        if direction == "outgoing":
            match_pattern = "(source:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})-[r]->(target:CanonicalConcept)"
        elif direction == "incoming":
            match_pattern = "(source:CanonicalConcept)<-[r]-(target:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})"
        else:
            match_pattern = "(source:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})-[r]-(target:CanonicalConcept)"

        # Query all typed relations
        query = f"""
        MATCH {match_pattern}
        WHERE NOT type(r) IN ['RELATES_FROM', 'RELATES_TO', 'AGGREGATES', 'PROMOTED_TO', 'HAS_SUBJECT', 'HAS_OBJECT']
          AND target.tenant_id = $tenant_id
        RETURN
            type(r) AS relation_type,
            source.canonical_id AS source_id,
            source.canonical_name AS source_name,
            target.canonical_id AS target_id,
            target.canonical_name AS target_name,
            r.maturity AS maturity,
            r.confidence AS confidence,
            r.source_count AS source_count,
            r.predicate_norm AS predicate_norm,
            r.canonical_relation_id AS cr_id,
            r.first_seen AS first_seen,
            r.last_seen AS last_seen
        ORDER BY r.confidence DESC
        LIMIT $limit
        """

        all_relations = self._execute_query(query, {
            "concept_id": concept_id,
            "tenant_id": self.tenant_id,
            "limit": limit * 2  # Fetch more to account for filtering
        })

        # Apply profile filtering
        visible = []
        for rel in all_relations:
            if self._passes_profile(rel, profile):
                visible.append(VisibleRelation(
                    relation_type=rel.get("relation_type", "UNKNOWN"),
                    source_concept_id=rel.get("source_id", ""),
                    source_concept_name=rel.get("source_name"),
                    target_concept_id=rel.get("target_id", ""),
                    target_concept_name=rel.get("target_name"),
                    maturity=rel.get("maturity", "CANDIDATE"),
                    confidence=rel.get("confidence", 0.0) or 0.0,
                    source_count=rel.get("source_count", 1) or 1,
                    predicate_norm=rel.get("predicate_norm"),
                    canonical_relation_id=rel.get("cr_id", ""),
                    first_seen=rel.get("first_seen"),
                    last_seen=rel.get("last_seen")
                ))

            if len(visible) >= limit:
                break

        # Build disclaimer if needed
        disclaimer = None
        if profile.ui.mandatory_disclaimer and profile.ui.disclaimer_text:
            disclaimer = profile.ui.disclaimer_text

        return VisibilityResult(
            profile_id=profile.id,
            profile_name=profile.name,
            visible_relations=visible,
            total_relations=len(all_relations),
            filtered_count=len(all_relations) - len(visible),
            ui_settings=profile.ui,
            disclaimer=disclaimer
        )

    def _passes_profile(self, relation: Dict[str, Any], profile: VisibilityProfile) -> bool:
        """
        Check if a relation passes the profile filters.

        Args:
            relation: Relation data from Neo4j
            profile: Profile to check against

        Returns:
            True if relation should be visible
        """
        settings = profile.settings

        maturity = relation.get("maturity", "CANDIDATE")
        confidence = relation.get("confidence", 0.0) or 0.0
        source_count = relation.get("source_count", 1) or 1

        # Check maturity
        if maturity not in settings.allowed_maturities:
            # Special handling for specific maturities
            if maturity == "CONFLICTING" and settings.show_conflicts:
                pass  # Allow
            elif maturity == "AMBIGUOUS_TYPE" and settings.show_ambiguous:
                pass  # Allow
            elif maturity == "CONTEXT_DEPENDENT" and settings.show_context_dependent:
                pass  # Allow
            else:
                return False

        # Check confidence threshold
        if confidence < settings.min_confidence:
            return False

        # Check source count
        if source_count < settings.min_source_count:
            return False

        return True

    def set_tenant_profile(self, tenant_id: str, profile_id: str) -> bool:
        """
        Set the profile for a tenant.

        Note: This only updates in-memory. For persistence,
        the caller should update the database or config file.

        Args:
            tenant_id: Tenant ID
            profile_id: Profile ID to set

        Returns:
            True if successful
        """
        if profile_id not in self.profiles:
            return False

        self.tenant_profiles[tenant_id] = profile_id
        logger.info(f"[VisibilityService] Set profile '{profile_id}' for tenant '{tenant_id}'")
        return True


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_service_instance: Optional[VisibilityService] = None


def get_visibility_service(
    tenant_id: str = "default",
    **kwargs
) -> VisibilityService:
    """Get or create VisibilityService instance."""
    global _service_instance
    if _service_instance is None or _service_instance.tenant_id != tenant_id:
        _service_instance = VisibilityService(tenant_id=tenant_id, **kwargs)
    return _service_instance
