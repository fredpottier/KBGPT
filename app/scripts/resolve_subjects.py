"""
Re-resoud les ComparableSubjects pour les DocumentContexts deja ingeres.

Utile apres avoir fixe le SubjectResolverV2 (branchement du gazetteer) :
permet de regenerer les ComparableSubjects sans avoir a re-ingerer les
documents. Utilise le nom de fichier original (via docs_done/) et les
raw_subjects deja extraits comme candidats d'entree.

USAGE
─────
    # Dry-run (ne modifie pas le graphe)
    docker exec knowbase-app python app/scripts/resolve_subjects.py --dry-run

    # Ecriture effective
    docker exec knowbase-app python app/scripts/resolve_subjects.py

    # Filtrer par tenant
    docker exec knowbase-app python app/scripts/resolve_subjects.py --tenant default

    # Purger les anciens ComparableSubjects avant regeneration
    docker exec knowbase-app python app/scripts/resolve_subjects.py --purge

COMPORTEMENT
────────────
1. Liste tous les DocumentContext du tenant
2. Pour chacun :
   a) retrouve le filename original dans data/docs_done/ (via prefix du doc_id)
   b) construit les inputs resolver : filename, title (derive), candidates
      (= [primary_subject + raw_subjects])
   c) appelle SubjectResolverV2.resolve()
   d) MERGE le ComparableSubject retourne (cree s'il n'existe pas)
   e) remplace la relation ABOUT_COMPARABLE existante
   f) met a jour dc.primary_subject avec le nouveau canonical
3. En fin de run, rapport comptable (nb resolus, nb abstentions, nb erreurs,
   liste des canonicals uniques crees)

NOTE
────
Ce script NE TOUCHE PAS aux Claims, aux Entities, aux Perspectives. Il se
limite strictement a la couche ComparableSubject. Si on souhaite re-executer
des etapes plus larges (Perspectives notamment, qui dependent des Subjects),
il faut ensuite lancer l'etape de reconstruction Perspective separement.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, "/app/src")

from neo4j import GraphDatabase

from knowbase.claimfirst.models.comparable_subject import ComparableSubject
from knowbase.claimfirst.resolution.subject_resolver_v2 import SubjectResolverV2
from knowbase.domain_packs.registry import get_pack_registry

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowbase_chunks_v2")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("resolve_subjects")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
DOCS_DONE_DIR = Path("/data/docs_done")


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════


def strip_hash_suffix(doc_id: str) -> str:
    """Retire le suffixe de hash (8 hex chars) du doc_id.

    Ex : "027_SAP_S4HANA_2023_Security_Guide_c160af0e" → "027_SAP_S4HANA_2023_Security_Guide"
    """
    parts = doc_id.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 8 and all(c in "0123456789abcdef" for c in parts[1]):
        return parts[0]
    return doc_id


def find_source_file(doc_id: str, docs_dir: Path) -> Optional[Path]:
    """Trouve le fichier source dans docs_done/ pour un doc_id donne."""
    stem = strip_hash_suffix(doc_id)
    if not docs_dir.exists():
        return None
    # Recherche exacte puis fuzzy sur le prefix numerique
    for candidate in docs_dir.iterdir():
        if candidate.is_file() and candidate.stem == stem:
            return candidate
    # Fallback : match sur le prefix (premiers 3-4 caracteres = numero du doc)
    prefix = stem.split("_", 1)[0]
    for candidate in docs_dir.iterdir():
        if candidate.is_file() and candidate.stem.startswith(prefix + "_"):
            return candidate
    return None


def derive_title_from_filename(filename_stem: str) -> str:
    """Derive un titre lisible depuis un stem de filename.

    Ex : "027_SAP_S4HANA_2023_Security_Guide" → "SAP S/4HANA 2023 Security Guide"
    """
    # Retirer le prefix numerique "NNN_"
    parts = filename_stem.split("_", 1)
    if len(parts) == 2 and parts[0].isdigit():
        rest = parts[1]
    else:
        rest = filename_stem
    # Remplacer les underscores par des espaces
    rest = rest.replace("_", " ")
    # Normaliser "S4HANA" en "S/4HANA" qui est le nom canonique correct
    rest = rest.replace("S4HANA", "S/4HANA")
    return rest.strip()


# ══════════════════════════════════════════════════════════════════════════
# Data loading / writing
# ══════════════════════════════════════════════════════════════════════════


def load_document_contexts(driver, tenant_id: str) -> List[Dict]:
    """Charge tous les DocumentContext du tenant avec leurs raw_subjects."""
    query = """
    MATCH (dc:DocumentContext)
    WHERE dc.tenant_id = $tenant_id
    RETURN dc.doc_id AS doc_id,
           dc.primary_subject AS primary_subject,
           dc.raw_subjects AS raw_subjects,
           dc.document_type AS document_type,
           dc.resolution_status AS resolution_status
    """
    with driver.session() as session:
        result = session.run(query, tenant_id=tenant_id)
        return [dict(record) for record in result]


def purge_comparable_subjects(driver, tenant_id: str) -> int:
    """Supprime tous les ComparableSubjects + relations ABOUT_COMPARABLE du tenant."""
    with driver.session() as session:
        # Detach delete pour supprimer aussi les relations
        result = session.run(
            """
            MATCH (cs:ComparableSubject)
            WHERE cs.tenant_id = $tenant_id
            DETACH DELETE cs
            RETURN count(cs) AS deleted
            """,
            tenant_id=tenant_id,
        )
        record = result.single()
        return record["deleted"] if record else 0


def upsert_comparable_subject(driver, cs: ComparableSubject) -> None:
    """MERGE un ComparableSubject en se basant sur canonical_name (unicite)."""
    with driver.session() as session:
        session.run(
            """
            MERGE (cs:ComparableSubject {tenant_id: $tenant_id, canonical_name: $canonical_name})
            ON CREATE SET cs += $props, cs.created_at = datetime()
            ON MATCH SET cs.updated_at = datetime()
            """,
            tenant_id=cs.tenant_id,
            canonical_name=cs.canonical_name,
            props=cs.to_neo4j_properties() if hasattr(cs, "to_neo4j_properties") else {
                "subject_id": cs.subject_id,
                "canonical_name": cs.canonical_name,
                "tenant_id": cs.tenant_id,
                "confidence": getattr(cs, "confidence", 0.0),
                "rationale": getattr(cs, "rationale", ""),
            },
        )


def link_dc_to_subject(driver, doc_id: str, canonical_name: str, tenant_id: str) -> None:
    """Etablit la relation DC -[ABOUT_COMPARABLE]-> CS, supprime l'ancienne si elle existe."""
    with driver.session() as session:
        # Supprimer l'ancienne relation (si elle existe)
        session.run(
            """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
                  -[r:ABOUT_COMPARABLE]->(:ComparableSubject)
            DELETE r
            """,
            doc_id=doc_id,
            tenant_id=tenant_id,
        )
        # Creer la nouvelle relation
        session.run(
            """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            MATCH (cs:ComparableSubject {canonical_name: $canonical_name, tenant_id: $tenant_id})
            MERGE (dc)-[:ABOUT_COMPARABLE]->(cs)
            SET dc.primary_subject = $canonical_name,
                dc.resolution_status = 'resolved',
                dc.resolved_at = datetime()
            """,
            doc_id=doc_id,
            canonical_name=canonical_name,
            tenant_id=tenant_id,
        )


def propagate_axis_to_qdrant(
    doc_id: str, release_id: Optional[str], edition: Optional[str]
) -> int:
    """Propage les axis_values vers les chunks Qdrant du document.

    Le retriever filtre sur `axis_release_id` dans le payload Qdrant
    (cf. src/knowbase/api/services/retriever.py:91), pas via Neo4j.
    Il faut donc populer ce champ sur tous les chunks du doc_id cible
    pour que le filtrage "use_latest" et les comparaisons cross-version
    fonctionnent.

    Utilise l'API Qdrant set_payload avec un filter par doc_id.

    Returns:
        Nombre de chunks affectes (0 si aucun axis a propager ou si
        l'appel echoue).
    """
    if not release_id and not edition:
        return 0

    import requests

    payload_to_set = {}
    if release_id:
        payload_to_set["axis_release_id"] = release_id
    if edition:
        payload_to_set["axis_edition"] = edition

    # set_payload API : applique payload aux points matchant le filter
    try:
        # D'abord, compter combien de chunks vont etre affectes
        count_resp = requests.post(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/count",
            json={
                "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}
            },
            timeout=10,
        )
        count_resp.raise_for_status()
        n_chunks = count_resp.json()["result"]["count"]
        if n_chunks == 0:
            logger.debug(f"  Qdrant: no chunks found for doc_id={doc_id}")
            return 0

        # Puis appliquer le payload
        update_resp = requests.post(
            f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload?wait=true",
            json={
                "payload": payload_to_set,
                "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
            },
            timeout=30,
        )
        update_resp.raise_for_status()
        result = update_resp.json()
        if result.get("status") == "ok":
            logger.info(
                f"  Qdrant: updated {n_chunks} chunks with {payload_to_set}"
            )
            return n_chunks
        else:
            logger.warning(f"  Qdrant update returned status={result.get('status')}")
            return 0
    except Exception as e:
        logger.warning(f"  Qdrant propagation failed for {doc_id}: {e}")
        return 0


def persist_axis_values(
    driver, doc_id: str, axis_values: List, tenant_id: str
) -> int:
    """Persiste les AxisValues du resolver sur le DocumentContext.

    Structure de stockage : applicability_frame_json et qualifiers_json
    sont mis a jour pour que les autres composants du pipeline puissent
    les lire (FrameBuilder, ApplicabilityAxisDetector, etc.).

    Note : cette persistance est simplifiee par rapport au flow normal du
    FrameBuilder (pas de evidence_unit_ids, pas de AuthorityContract). Elle
    est destinee au re-run offline des AxisValues apres fix du ComparableSubject.
    """
    import json as _json

    if not axis_values:
        return 0

    # Mapper discriminating_role -> field_name standard
    role_to_field = {
        "temporal": "publication_year",
        "revision": "release_id",
        "geographic": "region",
        "applicability_scope": "edition",
        "status": "status",
    }

    fields = []
    qualifiers = {}
    for av in axis_values:
        role_str = av.discriminating_role.value if hasattr(av.discriminating_role, "value") else str(av.discriminating_role)
        field_name = role_to_field.get(role_str, role_str)
        fields.append({
            "field_name": field_name,
            "value_raw": av.value_raw,
            "value_normalized": av.value_raw,  # pas de normalisation sophistiquee ici
            "discriminating_role": role_str,
            "confidence": av.confidence,
            "reasoning": av.rationale,
            "source": "subject_resolver_v2_rerun",
        })
        qualifiers[field_name] = av.value_raw

    frame_json = {
        "doc_id": doc_id,
        "fields": fields,
        "unknowns": [],
        "method": "subject_resolver_v2_rerun",
        "validation_notes": [
            f"Rebuilt from SubjectResolverV2 rerun (offline) — "
            f"{len(fields)} axis values persisted, no FrameBuilder evidence-locking"
        ],
    }

    with driver.session() as session:
        session.run(
            """
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            SET dc.applicability_frame_json = $frame_json,
                dc.qualifiers_json = $qualifiers_json,
                dc.applicability_frame_method = 'subject_resolver_v2_rerun',
                dc.applicability_frame_field_count = $n_fields
            """,
            doc_id=doc_id,
            tenant_id=tenant_id,
            frame_json=_json.dumps(frame_json, ensure_ascii=False),
            qualifiers_json=_json.dumps(qualifiers, ensure_ascii=False),
            n_fields=len(fields),
        )

    # Propager aussi vers Qdrant pour que le retrieval puisse filtrer
    # sur axis_release_id et axis_edition au niveau des chunks.
    release_id = qualifiers.get("release_id") or qualifiers.get("publication_year")
    edition = qualifiers.get("edition")
    propagate_axis_to_qdrant(doc_id, release_id, edition)

    return len(fields)


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Re-resolve ComparableSubjects for existing DocumentContexts")
    parser.add_argument("--tenant", default="default", help="Tenant ID")
    parser.add_argument("--dry-run", action="store_true", help="N'ecrit pas dans le graphe, juste affiche les resolutions")
    parser.add_argument("--purge", action="store_true", help="Purge tous les ComparableSubjects existants avant regeneration")
    parser.add_argument("--limit", type=int, default=0, help="Limiter a N DocumentContexts (0 = tous)")
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        # Charger les packs domaine actifs pour le tenant
        registry = get_pack_registry()
        active_packs = registry.get_active_packs(args.tenant) or []
        logger.info(f"Active domain packs for tenant {args.tenant}: {[p.name for p in active_packs]}")

        # Initialiser le resolver (avec les packs pour acces au gazetteer)
        resolver = SubjectResolverV2(
            tenant_id=args.tenant,
            domain_packs=active_packs,
        )

        # Purge optionnelle
        if args.purge and not args.dry_run:
            deleted = purge_comparable_subjects(driver, args.tenant)
            logger.info(f"Purged {deleted} existing ComparableSubjects")
        elif args.purge and args.dry_run:
            logger.info("[DRY-RUN] Would purge existing ComparableSubjects")

        # Charger les DocumentContexts
        dcs = load_document_contexts(driver, args.tenant)
        if args.limit > 0:
            dcs = dcs[: args.limit]
        logger.info(f"Loaded {len(dcs)} DocumentContexts to process")

        # Stats
        stats = {
            "total": len(dcs),
            "resolved": 0,
            "abstained": 0,
            "errors": 0,
            "file_not_found": 0,
            "axis_values_persisted": 0,
        }
        canonical_counts: Dict[str, int] = {}
        axis_role_counts: Dict[str, int] = {}

        for i, dc in enumerate(dcs, 1):
            doc_id = dc["doc_id"]
            logger.info(f"\n[{i}/{len(dcs)}] {doc_id}")

            # Retrouver le fichier source
            source_file = find_source_file(doc_id, DOCS_DONE_DIR)
            if source_file is None:
                logger.warning(f"  Source file not found in {DOCS_DONE_DIR} — using stripped doc_id as filename")
                filename = strip_hash_suffix(doc_id)
                filename_stem = filename
            else:
                filename = source_file.name
                filename_stem = source_file.stem
                logger.info(f"  Source file: {filename}")

            title = derive_title_from_filename(filename_stem)

            # Construire les candidates : primary_subject + raw_subjects + title
            candidates = []
            primary = dc.get("primary_subject")
            if primary:
                candidates.append(primary)
            raw = dc.get("raw_subjects") or []
            if isinstance(raw, list):
                candidates.extend(raw)
            # Ajouter le titre decomposable comme candidat haut niveau
            if title and title not in candidates:
                candidates.append(title)
            # Deduplication en preservant l'ordre
            seen = set()
            candidates = [c for c in candidates if c and not (c in seen or seen.add(c))]

            logger.info(f"  Title: {title}")
            logger.info(f"  Candidates: {candidates[:5]}{' ...' if len(candidates) > 5 else ''}")

            # Appeler le resolver
            try:
                output, new_cs = resolver.resolve(
                    candidates=candidates,
                    filename=filename,
                    title=title,
                    header_snippets=[],
                    cover_snippets=[],
                    global_view_excerpt="",
                )
            except Exception as e:
                logger.error(f"  Resolver error: {e}")
                stats["errors"] += 1
                continue

            # Traiter le resultat
            if output and output.abstain.must_abstain:
                logger.info(f"  ABSTAINED: {output.abstain.reason}")
                stats["abstained"] += 1
                continue

            if new_cs is None:
                logger.warning(f"  No ComparableSubject produced (no abstain either)")
                stats["errors"] += 1
                continue

            canonical = new_cs.canonical_name
            logger.info(f"  RESOLVED → {canonical}")
            stats["resolved"] += 1
            canonical_counts[canonical] = canonical_counts.get(canonical, 0) + 1

            # Extraire les axis_values pour logging et persistance
            axis_values = output.axis_values if output else []
            if axis_values:
                axis_summary = ", ".join(
                    f"{av.discriminating_role.value if hasattr(av.discriminating_role,'value') else av.discriminating_role}={av.value_raw}"
                    for av in axis_values
                )
                logger.info(f"  AXIS_VALUES → {axis_summary}")
                for av in axis_values:
                    role = av.discriminating_role.value if hasattr(av.discriminating_role,'value') else str(av.discriminating_role)
                    axis_role_counts[role] = axis_role_counts.get(role, 0) + 1
            else:
                logger.info(f"  AXIS_VALUES → (none)")

            if not args.dry_run:
                upsert_comparable_subject(driver, new_cs)
                link_dc_to_subject(driver, doc_id, canonical, args.tenant)
                if axis_values:
                    n = persist_axis_values(driver, doc_id, axis_values, args.tenant)
                    stats["axis_values_persisted"] += n

        # Rapport final
        print("\n" + "=" * 78)
        print("RESOLUTION SUMMARY")
        print("=" * 78)
        print(f"Total DocumentContexts : {stats['total']}")
        print(f"Resolved              : {stats['resolved']}")
        print(f"Abstained             : {stats['abstained']}")
        print(f"Errors                : {stats['errors']}")
        print(f"File not found        : {stats['file_not_found']}")
        print()
        print(f"Unique canonical subjects ({len(canonical_counts)}) :")
        for canonical, count in sorted(canonical_counts.items(), key=lambda x: -x[1]):
            print(f"  {count:3d} × {canonical}")

        print()
        print(f"Axis values persisted : {stats['axis_values_persisted']}")
        if axis_role_counts:
            print(f"Axis roles distribution :")
            for role, count in sorted(axis_role_counts.items(), key=lambda x: -x[1]):
                print(f"  {count:3d} × {role}")

        if args.dry_run:
            print("\n[DRY-RUN] No changes written to the graph.")
        else:
            print("\n[OK] Changes committed to the graph.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
