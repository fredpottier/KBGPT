#!/usr/bin/env python
"""
Migration Script: Add structured_form to existing Claims

Parcourt tous les Claim nodes dans Neo4j et calcule leur structured_form
pour la comparaison déterministe V1.1.

Usage:
    python -m knowbase.verification.scripts.migrate_claims_structured_form
    python -m knowbase.verification.scripts.migrate_claims_structured_form --dry-run
    python -m knowbase.verification.scripts.migrate_claims_structured_form --limit 100

Author: Claude Code
Date: 2026-02-03
Version: 1.1
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import List, Dict, Any, Optional

# Setup path for imports
sys.path.insert(0, "src")

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.verification.comparison import (
    StructuredExtractor,
    AuthorityLevel,
    ClaimFormType,
)
from knowbase.verification.comparison.claim_forms import StructuredClaimForm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class ClaimMigrator:
    """Migrates existing claims to add structured_form."""

    def __init__(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None,
        tenant_id: str = "default"
    ):
        self.dry_run = dry_run
        self.limit = limit
        self.tenant_id = tenant_id

        self.settings = get_settings()
        self.extractor = StructuredExtractor()

        self.neo4j_client = Neo4jClient(
            uri=self.settings.neo4j_uri,
            user=self.settings.neo4j_user,
            password=self.settings.neo4j_password
        )

        # Stats
        self.stats = {
            "total": 0,
            "migrated": 0,
            "skipped_already_migrated": 0,
            "skipped_text_value": 0,
            "errors": 0,
        }

    async def run(self):
        """Run the migration."""
        logger.info(f"Starting migration (dry_run={self.dry_run}, limit={self.limit})")

        if not self.neo4j_client.driver:
            logger.error("Neo4j driver not connected")
            return

        # 1. Fetch claims to migrate
        claims = self._fetch_claims_to_migrate()
        self.stats["total"] = len(claims)

        logger.info(f"Found {len(claims)} claims to process")

        # 2. Process each claim
        for i, claim in enumerate(claims):
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(claims)}")

            await self._process_claim(claim)

        # 3. Print summary
        self._print_summary()

    def _fetch_claims_to_migrate(self) -> List[Dict[str, Any]]:
        """Fetch claims that need migration."""
        database = getattr(self.neo4j_client, 'database', 'neo4j')

        # Fetch claims without structured_form_json
        query = """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NULL
        RETURN
            c.claim_id AS claim_id,
            c.text AS text,
            c.verbatim_quote AS verbatim_quote,
            c.doc_id AS doc_id,
            c.claim_type AS claim_type
        """
        if self.limit:
            query += f" LIMIT {self.limit}"

        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, {"tenant_id": self.tenant_id})
            return [dict(record) for record in result]

    async def _process_claim(self, claim: Dict[str, Any]):
        """Process a single claim."""
        claim_id = claim.get("claim_id")
        text = claim.get("verbatim_quote") or claim.get("text", "")

        if not text:
            self.stats["errors"] += 1
            return

        try:
            # Infer authority from doc_id
            authority = self._infer_authority(claim)

            # Extract structured form
            form = await self.extractor.extract(
                text,
                default_authority=authority
            )

            if not form:
                self.stats["errors"] += 1
                return

            # Check if TEXT_VALUE (not useful for deterministic comparison)
            if form.form_type == ClaimFormType.TEXT_VALUE:
                self.stats["skipped_text_value"] += 1
                logger.debug(f"Skipping TEXT_VALUE claim: {claim_id}")
                return

            # Convert to StructuredClaimForm for storage
            structured = StructuredClaimForm.from_claim_form(form)
            json_str = structured.model_dump_json()

            if self.dry_run:
                logger.debug(f"Would migrate {claim_id}: {form.form_type.value}")
                self.stats["migrated"] += 1
                return

            # Update Neo4j
            self._update_claim(claim_id, json_str)
            self.stats["migrated"] += 1

        except Exception as e:
            logger.error(f"Error processing claim {claim_id}: {e}")
            self.stats["errors"] += 1

    def _infer_authority(self, claim: Dict[str, Any]) -> AuthorityLevel:
        """Infer authority level from claim metadata."""
        doc_id = claim.get("doc_id", "").lower()
        claim_type = claim.get("claim_type", "").lower()

        # HIGH authority indicators
        if any(ind in doc_id for ind in ["contract", "sla", "spec", "official"]):
            return AuthorityLevel.HIGH
        if claim_type in ["sla", "contract", "specification"]:
            return AuthorityLevel.HIGH

        # LOW authority indicators
        if any(ind in doc_id for ind in ["marketing", "slide", "presentation"]):
            return AuthorityLevel.LOW

        return AuthorityLevel.MEDIUM

    def _update_claim(self, claim_id: str, structured_form_json: str):
        """Update claim in Neo4j with structured_form."""
        database = getattr(self.neo4j_client, 'database', 'neo4j')

        query = """
        MATCH (c:Claim {claim_id: $claim_id, tenant_id: $tenant_id})
        SET c.structured_form_json = $structured_form_json
        RETURN c.claim_id
        """

        with self.neo4j_client.driver.session(database=database) as session:
            session.run(query, {
                "claim_id": claim_id,
                "tenant_id": self.tenant_id,
                "structured_form_json": structured_form_json
            })

    def _print_summary(self):
        """Print migration summary."""
        logger.info("=" * 50)
        logger.info("Migration Summary")
        logger.info("=" * 50)
        logger.info(f"Total claims processed: {self.stats['total']}")
        logger.info(f"Successfully migrated: {self.stats['migrated']}")
        logger.info(f"Skipped (TEXT_VALUE): {self.stats['skipped_text_value']}")
        logger.info(f"Errors: {self.stats['errors']}")

        if self.dry_run:
            logger.info("")
            logger.info("*** DRY RUN - No changes were made ***")


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate Claims to add structured_form for V1.1"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of claims to process"
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="default",
        help="Tenant ID to migrate"
    )

    args = parser.parse_args()

    migrator = ClaimMigrator(
        dry_run=args.dry_run,
        limit=args.limit,
        tenant_id=args.tenant_id
    )

    await migrator.run()


if __name__ == "__main__":
    asyncio.run(main())
