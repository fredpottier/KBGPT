#!/usr/bin/env python3
"""
OSMOSE Pipeline V2 - Script d'Ingestion Batch
==============================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Script pour tester le pipeline V2 sur un corpus de documents.

Usage:
    python scripts/batch_ingest_v2.py --docs-dir data/docs_in --limit 10
    python scripts/batch_ingest_v2.py --doc-id doc-001
    python scripts/batch_ingest_v2.py --all

Options:
    --docs-dir DIR    Répertoire contenant les documents
    --doc-id ID       Traiter un document spécifique
    --limit N         Limiter à N documents
    --all             Traiter tous les documents
    --pass1-only      Exécuter uniquement Pass 1
    --pass2           Inclure Pass 2 (enrichissement)
    --pass3           Inclure Pass 3 (consolidation)
    --dry-run         Afficher sans exécuter
    --metrics         Afficher les métriques après traitement
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import time

# Ajouter le répertoire racine au path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


class BatchIngestV2:
    """Orchestrateur d'ingestion batch Pipeline V2."""

    def __init__(
        self,
        neo4j_driver=None,
        llm_client=None,
        tenant_id: str = "default",
        dry_run: bool = False,
    ):
        self.neo4j_driver = neo4j_driver
        self.llm_client = llm_client
        self.tenant_id = tenant_id
        self.dry_run = dry_run

        self.results: List[Dict] = []
        self.start_time = None

    def get_documents_from_neo4j(self, limit: Optional[int] = None) -> List[Dict]:
        """Récupère les documents depuis Neo4j."""
        if not self.neo4j_driver:
            logger.warning("Pas de driver Neo4j, retourne liste vide")
            return []

        documents = []
        with self.neo4j_driver.session() as session:
            query = """
            MATCH (d:Document {tenant_id: $tenant_id})
            RETURN d.doc_id AS doc_id,
                   d.title AS title,
                   d.document_type AS document_type
            ORDER BY d.created_at DESC
            """
            if limit:
                query += f" LIMIT {limit}"

            result = session.run(query, {"tenant_id": self.tenant_id})
            for record in result:
                documents.append({
                    "doc_id": record["doc_id"],
                    "title": record["title"],
                    "document_type": record["document_type"],
                })

        return documents

    def process_document(
        self,
        doc_id: str,
        run_pass2: bool = False,
        run_pass3: bool = False,
    ) -> Dict:
        """Traite un document avec Pipeline V2."""
        result = {
            "doc_id": doc_id,
            "status": "pending",
            "pass0": None,
            "pass1": None,
            "pass2": None,
            "pass3": None,
            "errors": [],
            "start_time": datetime.utcnow().isoformat(),
            "end_time": None,
            "duration_ms": None,
        }

        if self.dry_run:
            logger.info(f"[DRY-RUN] Traiterait: {doc_id}")
            result["status"] = "dry_run"
            return result

        start = time.time()

        try:
            # Pass 0: Structural Graph (déjà exécuté lors de l'import)
            result["pass0"] = {"status": "skipped", "message": "Utilise structure existante"}

            # Pass 1: Lecture Stratifiée
            logger.info(f"[Pass 1] Traitement: {doc_id}")
            pass1_result = self._run_pass1(doc_id)
            result["pass1"] = pass1_result

            if pass1_result.get("error"):
                result["errors"].append(f"Pass 1: {pass1_result['error']}")
                result["status"] = "partial"
            else:
                result["status"] = "pass1_complete"

            # Pass 2: Enrichissement (optionnel)
            if run_pass2 and not pass1_result.get("error"):
                logger.info(f"[Pass 2] Enrichissement: {doc_id}")
                pass2_result = self._run_pass2(doc_id)
                result["pass2"] = pass2_result

                if pass2_result.get("error"):
                    result["errors"].append(f"Pass 2: {pass2_result['error']}")
                    result["status"] = "partial"
                else:
                    result["status"] = "pass2_complete"

            # Pass 3: Consolidation (optionnel)
            if run_pass3:
                logger.info(f"[Pass 3] Consolidation: {doc_id}")
                pass3_result = self._run_pass3(doc_id)
                result["pass3"] = pass3_result

                if pass3_result.get("error"):
                    result["errors"].append(f"Pass 3: {pass3_result['error']}")
                else:
                    result["status"] = "complete"

        except Exception as e:
            logger.error(f"Erreur traitement {doc_id}: {e}")
            result["errors"].append(str(e))
            result["status"] = "error"

        end = time.time()
        result["end_time"] = datetime.utcnow().isoformat()
        result["duration_ms"] = int((end - start) * 1000)

        return result

    def _run_pass1(self, doc_id: str) -> Dict:
        """Exécute Pass 1 sur un document."""
        try:
            from knowbase.stratified.pass1 import run_pass1

            # Récupérer le contenu du document depuis Neo4j
            content = self._get_document_content(doc_id)

            if not content:
                return {"error": "Contenu non trouvé", "status": "error"}

            result = run_pass1(
                doc_id=doc_id,
                content=content,
                llm_client=self.llm_client,
                neo4j_driver=self.neo4j_driver,
                tenant_id=self.tenant_id,
            )

            return {
                "status": "success",
                "themes_count": result.stats.themes_count,
                "concepts_count": result.stats.concepts_count,
                "informations_count": result.stats.informations_count,
                "promoted_count": result.stats.promoted_count,
                "abstained_count": result.stats.abstained_count,
                "rejected_count": result.stats.rejected_count,
            }

        except Exception as e:
            return {"error": str(e), "status": "error"}

    def _run_pass2(self, doc_id: str) -> Dict:
        """Exécute Pass 2 sur un document."""
        try:
            from knowbase.stratified.pass2 import run_pass2

            result = run_pass2(
                doc_id=doc_id,
                neo4j_driver=self.neo4j_driver,
                llm_client=self.llm_client,
                tenant_id=self.tenant_id,
            )

            return {
                "status": "success",
                "relations_count": result.stats.relations_extracted,
            }

        except Exception as e:
            return {"error": str(e), "status": "error"}

    def _run_pass3(self, doc_id: str) -> Dict:
        """Exécute Pass 3 (incrémental) pour un document."""
        try:
            from knowbase.stratified.pass3 import run_pass3_incremental

            # Récupérer les concepts du document
            concepts = self._get_document_concepts(doc_id)

            result = run_pass3_incremental(
                new_concepts=concepts,
                neo4j_driver=self.neo4j_driver,
                llm_client=self.llm_client,
                tenant_id=self.tenant_id,
            )

            return {
                "status": "success",
                "canonical_concepts": len(result.canonical_concepts),
                "canonical_themes": len(result.canonical_themes),
            }

        except Exception as e:
            return {"error": str(e), "status": "error"}

    def _get_document_content(self, doc_id: str) -> Optional[str]:
        """Récupère le contenu textuel d'un document."""
        if not self.neo4j_driver:
            return None

        with self.neo4j_driver.session() as session:
            # Récupérer le texte des DocItems
            query = """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (d)-[:HAS_SECTION]->(s:Section)-[:HAS_DOCITEM]->(di:DocItem)
            RETURN d.title AS title,
                   collect(di.text) AS texts
            """
            result = session.run(query, {"doc_id": doc_id, "tenant_id": self.tenant_id})
            record = result.single()

            if record and record["texts"]:
                return "\n\n".join([t for t in record["texts"] if t])

        return None

    def _get_document_concepts(self, doc_id: str) -> List:
        """Récupère les concepts d'un document."""
        if not self.neo4j_driver:
            return []

        from knowbase.stratified.models import Concept, ConceptRole

        concepts = []
        with self.neo4j_driver.session() as session:
            query = """
            MATCH (c:Concept {tenant_id: $tenant_id})-[:BELONGS_TO]->(t:Theme)-[:THEME_OF]->(d:Document {doc_id: $doc_id})
            RETURN c.concept_id AS concept_id,
                   c.name AS name,
                   c.role AS role,
                   t.theme_id AS theme_id
            """
            result = session.run(query, {"doc_id": doc_id, "tenant_id": self.tenant_id})

            for record in result:
                concept = Concept(
                    concept_id=record["concept_id"],
                    theme_id=record["theme_id"],
                    name=record["name"],
                    role=ConceptRole(record["role"]) if record["role"] else ConceptRole.STANDARD,
                )
                concepts.append(concept)

        return concepts

    def run_batch(
        self,
        documents: List[Dict],
        run_pass2: bool = False,
        run_pass3: bool = False,
    ) -> Dict:
        """Exécute le batch sur une liste de documents."""
        self.start_time = time.time()
        self.results = []

        total = len(documents)
        logger.info(f"=== Début batch V2: {total} documents ===")

        for i, doc in enumerate(documents, 1):
            doc_id = doc.get("doc_id") or doc.get("id")
            logger.info(f"[{i}/{total}] Traitement: {doc_id}")

            result = self.process_document(
                doc_id=doc_id,
                run_pass2=run_pass2,
                run_pass3=run_pass3,
            )
            self.results.append(result)

        total_time = time.time() - self.start_time

        # Calculer les statistiques
        stats = self._compute_stats()
        stats["total_time_s"] = round(total_time, 2)
        stats["avg_time_per_doc_s"] = round(total_time / total, 2) if total > 0 else 0

        logger.info(f"=== Fin batch V2 ===")
        logger.info(f"Total: {total} docs en {stats['total_time_s']}s")
        logger.info(f"Succès: {stats['success_count']}, Erreurs: {stats['error_count']}")

        return {
            "batch_id": datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            "documents_processed": total,
            "results": self.results,
            "stats": stats,
        }

    def _compute_stats(self) -> Dict:
        """Calcule les statistiques du batch."""
        stats = {
            "success_count": 0,
            "error_count": 0,
            "partial_count": 0,
            "total_themes": 0,
            "total_concepts": 0,
            "total_informations": 0,
            "total_promoted": 0,
            "total_abstained": 0,
            "total_rejected": 0,
            "avg_concepts_per_doc": 0,
            "avg_informations_per_concept": 0,
            # Métriques V2 - E2E-004, E2E-005
            "total_nodes_v2": 0,
            "avg_nodes_per_doc": 0,
            "total_duration_ms": 0,
            "avg_duration_ms": 0,
            # Comparaison Legacy (E2E-006)
            "legacy_comparison": None,
        }

        durations = []
        for result in self.results:
            if result["status"] in ["pass1_complete", "pass2_complete", "complete"]:
                stats["success_count"] += 1

                if result.get("pass1"):
                    p1 = result["pass1"]
                    stats["total_themes"] += p1.get("themes_count", 0)
                    stats["total_concepts"] += p1.get("concepts_count", 0)
                    stats["total_informations"] += p1.get("informations_count", 0)
                    stats["total_promoted"] += p1.get("promoted_count", 0)
                    stats["total_abstained"] += p1.get("abstained_count", 0)
                    stats["total_rejected"] += p1.get("rejected_count", 0)

                # Temps de traitement
                if result.get("duration_ms"):
                    durations.append(result["duration_ms"])
                    stats["total_duration_ms"] += result["duration_ms"]

            elif result["status"] == "error":
                stats["error_count"] += 1
            elif result["status"] == "partial":
                stats["partial_count"] += 1

        # Moyennes
        if stats["success_count"] > 0:
            stats["avg_concepts_per_doc"] = round(
                stats["total_concepts"] / stats["success_count"], 2
            )
            stats["avg_duration_ms"] = round(
                stats["total_duration_ms"] / stats["success_count"], 0
            )

        if stats["total_concepts"] > 0:
            stats["avg_informations_per_concept"] = round(
                stats["total_informations"] / stats["total_concepts"], 2
            )

        # Compter nodes V2 dans Neo4j
        if self.neo4j_driver:
            stats["total_nodes_v2"] = self._count_v2_nodes()
            if stats["success_count"] > 0:
                stats["avg_nodes_per_doc"] = round(
                    stats["total_nodes_v2"] / stats["success_count"], 0
                )

        return stats

    def _count_v2_nodes(self) -> int:
        """Compte le nombre total de nodes V2 dans Neo4j."""
        if not self.neo4j_driver:
            return 0

        with self.neo4j_driver.session() as session:
            # Compter tous les nodes du modèle V2
            query = """
            MATCH (n)
            WHERE n.tenant_id = $tenant_id
              AND (n:Subject OR n:Theme OR n:Concept OR n:Information
                   OR n:CanonicalConcept OR n:CanonicalTheme)
            RETURN count(n) AS count
            """
            result = session.run(query, {"tenant_id": self.tenant_id})
            record = result.single()
            return record["count"] if record else 0

    def count_nodes_per_document(self, doc_id: str) -> Dict:
        """Compte les nodes V2 pour un document spécifique."""
        if not self.neo4j_driver:
            return {"error": "Neo4j non disponible"}

        with self.neo4j_driver.session() as session:
            query = """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (d)<-[:SUBJECT_OF]-(s:Subject)
            OPTIONAL MATCH (d)<-[:THEME_OF]-(t:Theme)
            OPTIONAL MATCH (t)<-[:BELONGS_TO]-(c:Concept)
            OPTIONAL MATCH (c)<-[:ASSERTION_OF]-(i:Information)
            RETURN count(DISTINCT s) AS subjects,
                   count(DISTINCT t) AS themes,
                   count(DISTINCT c) AS concepts,
                   count(DISTINCT i) AS informations
            """
            result = session.run(query, {"doc_id": doc_id, "tenant_id": self.tenant_id})
            record = result.single()

            if record:
                total = (
                    record["subjects"] +
                    record["themes"] +
                    record["concepts"] +
                    record["informations"]
                )
                return {
                    "subjects": record["subjects"],
                    "themes": record["themes"],
                    "concepts": record["concepts"],
                    "informations": record["informations"],
                    "total_nodes_v2": total,
                }

        return {"total_nodes_v2": 0}

    def compare_with_legacy(self) -> Dict:
        """
        Compare les métriques V2 avec le legacy (E2E-006).
        Retourne un rapport de comparaison.
        """
        if not self.neo4j_driver:
            return {"error": "Neo4j non disponible"}

        with self.neo4j_driver.session() as session:
            # Compter nodes legacy (ProtoConcept, RawAssertion, etc.)
            legacy_query = """
            MATCH (n)
            WHERE n.tenant_id = $tenant_id
              AND (n:ProtoConcept OR n:RawAssertion OR n:CanonicalRelation
                   OR n:Entity OR n:Fact)
            RETURN count(n) AS count
            """
            legacy_result = session.run(legacy_query, {"tenant_id": self.tenant_id})
            legacy_record = legacy_result.single()
            legacy_count = legacy_record["count"] if legacy_record else 0

            # Compter nodes V2
            v2_count = self._count_v2_nodes()

            # Compter documents
            doc_query = """
            MATCH (d:Document {tenant_id: $tenant_id})
            RETURN count(d) AS count
            """
            doc_result = session.run(doc_query, {"tenant_id": self.tenant_id})
            doc_record = doc_result.single()
            doc_count = doc_record["count"] if doc_record else 1

            legacy_per_doc = round(legacy_count / max(doc_count, 1), 0)
            v2_per_doc = round(v2_count / max(doc_count, 1), 0)

            reduction_pct = 0
            if legacy_per_doc > 0:
                reduction_pct = round((1 - v2_per_doc / legacy_per_doc) * 100, 1)

            return {
                "documents": doc_count,
                "legacy": {
                    "total_nodes": legacy_count,
                    "avg_per_doc": legacy_per_doc,
                },
                "v2": {
                    "total_nodes": v2_count,
                    "avg_per_doc": v2_per_doc,
                },
                "reduction_percentage": reduction_pct,
                "target_met": v2_per_doc <= 250,  # Cible: < 250 nodes/doc
            }

    def save_report(self, output_path: Path, batch_result: Dict):
        """Sauvegarde le rapport en JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(batch_result, f, indent=2, ensure_ascii=False)

        logger.info(f"Rapport sauvegardé: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="OSMOSE Pipeline V2 - Ingestion Batch"
    )

    parser.add_argument("--docs-dir", type=Path, help="Répertoire des documents")
    parser.add_argument("--doc-id", type=str, help="ID d'un document spécifique")
    parser.add_argument("--limit", type=int, default=10, help="Limite de documents")
    parser.add_argument("--all", action="store_true", help="Traiter tous les documents")
    parser.add_argument("--pass1-only", action="store_true", help="Pass 1 uniquement")
    parser.add_argument("--pass2", action="store_true", help="Inclure Pass 2")
    parser.add_argument("--pass3", action="store_true", help="Inclure Pass 3")
    parser.add_argument("--dry-run", action="store_true", help="Mode simulation")
    parser.add_argument("--metrics", action="store_true", help="Afficher métriques")
    parser.add_argument("--output", type=Path, help="Fichier de sortie JSON")
    parser.add_argument("--tenant-id", type=str, default="default", help="Tenant ID")

    args = parser.parse_args()

    # Initialiser les connexions
    neo4j_driver = None
    llm_client = None

    if not args.dry_run:
        try:
            from knowbase.common.neo4j_client import get_neo4j_driver
            neo4j_driver = get_neo4j_driver()
            logger.info("✅ Neo4j connecté")
        except Exception as e:
            logger.error(f"❌ Neo4j non disponible: {e}")

        try:
            from knowbase.common.llm_router import get_llm_client
            llm_client = get_llm_client()
            logger.info("✅ LLM client initialisé")
        except Exception as e:
            logger.error(f"❌ LLM client non disponible: {e}")

    # Initialiser l'ingestion batch
    batch = BatchIngestV2(
        neo4j_driver=neo4j_driver,
        llm_client=llm_client,
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
    )

    # Déterminer les documents à traiter
    documents = []

    if args.doc_id:
        documents = [{"doc_id": args.doc_id}]
    elif args.all:
        documents = batch.get_documents_from_neo4j()
    else:
        documents = batch.get_documents_from_neo4j(limit=args.limit)

    if not documents:
        logger.warning("Aucun document à traiter")
        return

    # Exécuter le batch
    result = batch.run_batch(
        documents=documents,
        run_pass2=args.pass2 and not args.pass1_only,
        run_pass3=args.pass3 and not args.pass1_only,
    )

    # Afficher les métriques
    if args.metrics:
        print("\n" + "=" * 60)
        print("MÉTRIQUES PIPELINE V2 - RAPPORT E2E")
        print("=" * 60)
        stats = result["stats"]
        print(f"Documents traités: {result['documents_processed']}")
        print(f"Succès: {stats['success_count']}")
        print(f"Erreurs: {stats['error_count']}")
        print(f"Partiels: {stats['partial_count']}")
        print("-" * 60)
        print("📊 EXTRACTION (Pass 1)")
        print(f"  Total thèmes: {stats['total_themes']}")
        print(f"  Total concepts: {stats['total_concepts']}")
        print(f"  Total informations: {stats['total_informations']}")
        print(f"  Concepts/doc: {stats['avg_concepts_per_doc']}")
        print(f"  Infos/concept: {stats['avg_informations_per_concept']}")
        print("-" * 60)
        print("📋 PROMOTION POLICY")
        print(f"  Promus: {stats['total_promoted']}")
        print(f"  Abstenus: {stats['total_abstained']}")
        print(f"  Rejetés: {stats['total_rejected']}")
        print("-" * 60)
        print("📦 NODES V2 (E2E-004)")
        print(f"  Total nodes V2: {stats['total_nodes_v2']}")
        print(f"  Nodes/document: {stats['avg_nodes_per_doc']}")
        target_status = "✅" if stats['avg_nodes_per_doc'] <= 250 else "❌"
        print(f"  Cible (<250): {target_status}")
        print("-" * 60)
        print("⏱️ PERFORMANCE (E2E-005)")
        print(f"  Temps total: {stats['total_time_s']}s")
        print(f"  Temps moyen/doc: {stats['avg_time_per_doc_s']}s")
        print(f"  Temps moyen/doc: {stats['avg_duration_ms']}ms")
        target_time = stats['avg_time_per_doc_s'] < 600  # < 10 min
        time_status = "✅" if target_time else "❌"
        print(f"  Cible (<10 min): {time_status}")

        # Comparaison legacy (E2E-006)
        if not args.dry_run:
            print("-" * 60)
            print("📈 COMPARAISON LEGACY (E2E-006)")
            comparison = batch.compare_with_legacy()
            if "error" not in comparison:
                print(f"  Documents: {comparison['documents']}")
                print(f"  Legacy: {comparison['legacy']['total_nodes']} nodes ({comparison['legacy']['avg_per_doc']}/doc)")
                print(f"  V2: {comparison['v2']['total_nodes']} nodes ({comparison['v2']['avg_per_doc']}/doc)")
                print(f"  Réduction: {comparison['reduction_percentage']}%")
                target_met = "✅" if comparison['target_met'] else "❌"
                print(f"  Cible (<250/doc): {target_met}")
            else:
                print(f"  {comparison['error']}")

        print("=" * 60)

    # Sauvegarder le rapport
    if args.output:
        batch.save_report(args.output, result)
    else:
        output_path = ROOT_DIR / "data" / "batch_v2_reports" / f"batch_{result['batch_id']}.json"
        batch.save_report(output_path, result)


if __name__ == "__main__":
    main()
