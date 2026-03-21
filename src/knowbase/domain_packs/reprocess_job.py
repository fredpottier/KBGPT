# src/knowbase/domain_packs/reprocess_job.py
"""
Job RQ pour le reprocessing rétroactif des Domain Packs.

Enrichit les claims isolées (sans ABOUT) du KG existant
via les extracteurs du pack activé.

Retourne à la fois les nouvelles entités ET les liens ABOUT
vers des entités existantes détectées dans les claims.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def enqueue_reprocess(pack_name: str, tenant_id: str) -> str:
    """Enqueue le job de reprocessing dans RQ."""
    from redis import Redis
    from rq import Queue
    import os

    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_conn = Redis.from_url(redis_url)
    queue = Queue("reprocess", connection=redis_conn)

    job = queue.enqueue(
        run_reprocess,
        pack_name,
        tenant_id,
        job_timeout="30m",
    )

    return job.id


def run_reprocess(pack_name: str, tenant_id: str) -> dict:
    """
    Job principal de reprocessing.

    1. Query claims sans ABOUT dans Neo4j
    2. Charge les extracteurs du pack
    3. Valide via gates core (nouvelles entités)
    4. Persiste nouvelles entités + ABOUT
    5. Persiste ABOUT vers entités existantes détectées
    """
    from knowbase.domain_packs.registry import get_pack_registry
    from knowbase.claimfirst.models.entity import (
        Entity,
        is_valid_entity_name,
    )
    from knowbase.claimfirst.models.claim import Claim
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    registry = get_pack_registry()
    pack = registry.get_pack(pack_name)

    if not pack:
        return {"error": f"Pack '{pack_name}' not found"}

    driver = get_neo4j_client().driver
    _update_state(tenant_id, "running", 0.0)

    try:
        # 1. Query TOUTES les claims (pas seulement les isolées)
        # Le NER du pack gère la dedup via existing_norms
        with driver.session() as session:
            result = session.run(
                """
                MATCH (c:Claim {tenant_id: $tenant_id})
                RETURN c.claim_id as claim_id, c.text as text,
                       c.tenant_id as tenant_id
                """,
                tenant_id=tenant_id,
            )
            all_records = list(result)

        if not all_records:
            _update_state(tenant_id, "completed", 1.0)
            return {"entities_created": 0, "claims_linked": 0, "aliases_resolved": 0}

        # Construire des objets Claim légers (model_construct = pas de validation)
        claims = []
        for record in all_records:
            text = record["text"] or ""
            claims.append(Claim.model_construct(
                claim_id=record["claim_id"],
                text=text,
                tenant_id=record["tenant_id"],
                doc_id="reprocess",
                unit_ids=[],
                claim_type="FACTUAL",
                verbatim_quote=text,
                passage_id="reprocess",
            ))

        logger.info(
            f"[Reprocess:{pack_name}] {len(claims)} claims to process (all)"
        )
        _update_state(tenant_id, "running", 0.1)

        # 2. Charger les entités existantes (pour dedup + relinking)
        with driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tenant_id})
                RETURN e.entity_id, e.name, e.entity_type,
                       e.normalized_name, e.tenant_id
                """,
                tenant_id=tenant_id,
            )
            existing_entities = []
            for r in result:
                existing_entities.append(Entity(
                    entity_id=r["e.entity_id"],
                    name=r["e.name"],
                    entity_type=r["e.entity_type"] or "other",
                    normalized_name=r["e.normalized_name"] or "",
                    tenant_id=r["e.tenant_id"],
                ))

        existing_norms = {e.normalized_name for e in existing_entities}
        existing_norm_to_id = {e.normalized_name: e.entity_id for e in existing_entities}

        # 3. Charger domain context
        domain_context = None
        try:
            from knowbase.ontology.domain_context_store import (
                get_domain_context_store,
            )
            domain_context = get_domain_context_store().get_profile(tenant_id)
        except Exception:
            pass

        _update_state(tenant_id, "running", 0.2)

        # 4. Lancer les extracteurs par batches (évite les timeouts sidecar)
        BATCH_SIZE = 500
        pack_stoplist = set(
            Entity.normalize(s) for s in pack.get_entity_stoplist()
        )

        new_entities: List[Entity] = []
        all_links: List[Tuple[str, str]] = []  # (claim_id, entity_id)
        seen_norms: Dict[str, str] = {}

        total_batches = (len(claims) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(
            f"[Reprocess:{pack_name}] {len(claims)} claims en {total_batches} batches de {BATCH_SIZE}"
        )

        for extractor in pack.get_entity_extractors():
            for batch_idx in range(total_batches):
                batch_start = batch_idx * BATCH_SIZE
                batch_claims = claims[batch_start:batch_start + BATCH_SIZE]

                try:
                    candidates, candidate_map = extractor.extract(
                        claims=batch_claims,
                        existing_entities=existing_entities + new_entities,
                        domain_context=domain_context,
                    )
                except Exception as e:
                    logger.error(
                        f"[Reprocess:{pack_name}] Extractor error batch {batch_idx + 1}/{total_batches}: {e}"
                    )
                    continue

                # Gate core pour les nouvelles entités
                for entity in candidates:
                    norm = entity.normalized_name

                    if norm in pack_stoplist:
                        continue
                    if not is_valid_entity_name(entity.name, ner_sourced=True):
                        continue
                    if norm in existing_norms:
                        continue
                    if norm in seen_norms:
                        continue

                    object.__setattr__(entity, "source_pack", pack_name)
                    new_entities.append(entity)
                    seen_norms[norm] = entity.entity_id
                    existing_norms.add(norm)

                # Créer les liens (nouvelles entités + entités existantes)
                valid_new_ids = {e.entity_id for e in new_entities} | set(seen_norms.values())
                valid_existing_ids = set(existing_norm_to_id.values())
                all_valid_ids = valid_new_ids | valid_existing_ids

                for claim_id, entity_ids in candidate_map.items():
                    for eid in entity_ids:
                        if eid in all_valid_ids:
                            all_links.append((claim_id, eid))

                progress_pct = 0.2 + (batch_idx + 1) / total_batches * 0.4
                _update_state(tenant_id, "running", progress_pct,
                              entities_created=len(new_entities),
                              claims_linked=len(all_links))

                if (batch_idx + 1) % 5 == 0 or batch_idx == total_batches - 1:
                    logger.info(
                        f"[Reprocess:{pack_name}] Batch {batch_idx + 1}/{total_batches}: "
                        f"{len(new_entities)} new entities, {len(all_links)} links"
                    )

        _update_state(tenant_id, "running", 0.6)

        # 5. Persister dans Neo4j
        entities_created = 0
        links_created = 0

        if new_entities:
            with driver.session() as session:
                batch = [e.to_neo4j_properties() for e in new_entities]
                session.run(
                    """
                    UNWIND $batch AS item
                    MERGE (e:Entity {
                        normalized_name: item.normalized_name,
                        tenant_id: item.tenant_id
                    })
                    ON CREATE SET e += item
                    ON MATCH SET e.mention_count = e.mention_count + 1
                    """,
                    batch=batch,
                )
                entities_created = len(new_entities)

        _update_state(tenant_id, "running", 0.8)

        if all_links:
            with driver.session() as session:
                link_batch = [
                    {
                        "claim_id": cid,
                        "entity_id": eid,
                        "method": f"domain_pack:{pack_name}",
                    }
                    for cid, eid in all_links
                ]
                # Par lots de 5000 pour éviter les timeouts
                for start in range(0, len(link_batch), 5000):
                    chunk = link_batch[start:start + 5000]
                    session.run(
                        """
                        UNWIND $batch AS item
                        MATCH (c:Claim {claim_id: item.claim_id})
                        MATCH (e:Entity {entity_id: item.entity_id})
                        MERGE (c)-[r:ABOUT]->(e)
                        ON CREATE SET r.method = item.method
                        """,
                        batch=chunk,
                    )
                links_created = len(all_links)

        _update_state(tenant_id, "running", 0.85)

        # 6. Résolution d'aliases canoniques sur les entités existantes
        aliases_resolved = 0
        try:
            defaults = pack._load_defaults_json()
            raw_aliases = defaults.get("canonical_aliases", {})
            if raw_aliases:
                alias_map = {alias.lower(): canonical for alias, canonical in raw_aliases.items()}

                with driver.session() as session:
                    # Charger les entités dont le nom matche un alias
                    for alias_lower, canonical in alias_map.items():
                        result = session.run(
                            """
                            MATCH (e:Entity {tenant_id: $tid})
                            WHERE toLower(e.name) = $alias
                              AND toLower(e.name) <> toLower($canonical)
                            RETURN e.entity_id AS eid, e.name AS old_name
                            """,
                            tid=tenant_id,
                            alias=alias_lower,
                            canonical=canonical,
                        )
                        for r in result:
                            # Renommer l'entité vers le nom canonique
                            session.run(
                                """
                                MATCH (e:Entity {entity_id: $eid, tenant_id: $tid})
                                SET e.name = $canonical,
                                    e.normalized_name = $canonical_norm,
                                    e.aliases = CASE
                                        WHEN e.aliases IS NULL THEN [$old_name]
                                        WHEN NOT $old_name IN e.aliases THEN e.aliases + $old_name
                                        ELSE e.aliases
                                    END
                                """,
                                eid=r["eid"],
                                tid=tenant_id,
                                canonical=canonical,
                                canonical_norm=canonical.lower().strip(),
                                old_name=r["old_name"],
                            )
                            aliases_resolved += 1
                            logger.debug(
                                f"[Reprocess:{pack_name}] Alias resolved: "
                                f"'{r['old_name']}' → '{canonical}'"
                            )

                if aliases_resolved > 0:
                    logger.info(
                        f"[Reprocess:{pack_name}] {aliases_resolved} entities renamed "
                        f"via canonical aliases"
                    )
        except Exception as e:
            logger.warning(f"[Reprocess:{pack_name}] Alias resolution error: {e}")

        stats = {
            "entities_created": entities_created,
            "claims_linked": links_created,
            "aliases_resolved": aliases_resolved,
        }
        _update_state(
            tenant_id, "completed", 1.0,
            entities_created=entities_created,
            claims_linked=links_created,
        )

        logger.info(
            f"[Reprocess:{pack_name}] Completed: "
            f"{entities_created} new entities, {links_created} links, "
            f"{aliases_resolved} aliases resolved"
        )
        return stats

    except Exception as e:
        logger.error(f"[Reprocess:{pack_name}] Error: {e}")
        _update_state(tenant_id, "failed", 0.0, error=str(e))
        raise


def _update_state(
    tenant_id: str,
    state: str,
    progress: float,
    entities_created: int = 0,
    claims_linked: int = 0,
    error: Optional[str] = None,
) -> None:
    """Met à jour l'état du reprocessing dans Redis."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        rc = get_redis_client()
        redis = rc.client  # redis.Redis natif
        state_key = f"osmose:domain_pack:reprocess:state:{tenant_id}"
        data = {
            "state": state,
            "progress": progress,
            "entities_created": entities_created,
            "claims_linked": claims_linked,
        }
        if error:
            data["error"] = error
        redis.set(state_key, json.dumps(data), ex=3600)
    except Exception:
        pass
