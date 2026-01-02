"""
OSMOSE Pass 2 - Test A/B: gpt-4o-mini vs Qwen-14B (vLLM on EC2 Spot)

Compare la qualité d'extraction de relations entre:
- Groupe A: gpt-4o-mini (OpenAI API, défaut)
- Groupe B: Qwen2-14B-Instruct-AWQ (vLLM sur EC2 Spot)

Métriques collectées:
- Précision: relations validées / relations proposées
- Latence: temps moyen par segment
- Distribution des prédicats
- Qualité des quotes (fuzzy score moyen)
- Coût estimé

Usage:
    python scripts/pass2_ab_test.py --documents 10 --dry-run
    python scripts/pass2_ab_test.py --documents 20 --execute

Author: OSMOSE Phase 2
Date: 2025-01
"""

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("Pass2ABTest")


@dataclass
class SegmentMetrics:
    """Métriques pour un segment."""
    segment_id: str
    latency_ms: float
    relations_proposed: int
    relations_validated: int
    relations_rejected: int
    fuzzy_score_avg: float
    predicates: Dict[str, int] = field(default_factory=dict)
    rejection_reasons: Dict[str, int] = field(default_factory=dict)


@dataclass
class DocumentMetrics:
    """Métriques pour un document."""
    document_id: str
    provider: str  # "openai" ou "vllm"
    total_segments: int
    total_latency_ms: float
    segments: List[SegmentMetrics] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(1, self.total_segments)

    @property
    def total_proposed(self) -> int:
        return sum(s.relations_proposed for s in self.segments)

    @property
    def total_validated(self) -> int:
        return sum(s.relations_validated for s in self.segments)

    @property
    def precision(self) -> float:
        if self.total_proposed == 0:
            return 0.0
        return self.total_validated / self.total_proposed

    @property
    def predicates_distribution(self) -> Dict[str, int]:
        dist = {}
        for s in self.segments:
            for pred, count in s.predicates.items():
                dist[pred] = dist.get(pred, 0) + count
        return dist


@dataclass
class ABTestResult:
    """Résultat global du test A/B."""
    test_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    documents_count: int = 0
    qwen_first: bool = False

    group_a_metrics: List[DocumentMetrics] = field(default_factory=list)  # gpt-4o-mini
    group_b_metrics: List[DocumentMetrics] = field(default_factory=list)  # Qwen-14B

    # Coûts
    group_a_cost_usd: float = 0.0
    group_b_cost_usd: float = 0.0  # Calculé à partir du temps EC2
    ec2_runtime_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "documents_count": self.documents_count,
            "qwen_first": self.qwen_first,
            "group_a": {
                "provider": "gpt-4o-mini",
                "documents": len(self.group_a_metrics),
                "total_segments": sum(m.total_segments for m in self.group_a_metrics),
                "avg_precision": sum(m.precision for m in self.group_a_metrics) / max(1, len(self.group_a_metrics)),
                "avg_latency_ms": sum(m.avg_latency_ms for m in self.group_a_metrics) / max(1, len(self.group_a_metrics)),
                "total_relations": sum(m.total_validated for m in self.group_a_metrics),
                "cost_usd": self.group_a_cost_usd,
                "docs": [{"id": m.document_id, "relations": m.total_validated, "ms": m.total_latency_ms} for m in self.group_a_metrics],
            },
            "group_b": {
                "provider": "Qwen2-14B-Instruct-AWQ",
                "documents": len(self.group_b_metrics),
                "total_segments": sum(m.total_segments for m in self.group_b_metrics),
                "avg_precision": sum(m.precision for m in self.group_b_metrics) / max(1, len(self.group_b_metrics)),
                "avg_latency_ms": sum(m.avg_latency_ms for m in self.group_b_metrics) / max(1, len(self.group_b_metrics)),
                "total_relations": sum(m.total_validated for m in self.group_b_metrics),
                "cost_usd": self.group_b_cost_usd,
                "docs": [{"id": m.document_id, "relations": m.total_validated, "ms": m.total_latency_ms} for m in self.group_b_metrics],
            },
            "ec2_runtime_seconds": self.ec2_runtime_seconds,
        }


class Pass2ABTester:
    """
    Orchestrateur du test A/B Pass 2.

    Exécute le même processus d'extraction de relations avec deux providers:
    1. gpt-4o-mini (défaut, via OpenAI API)
    2. Qwen-14B (via vLLM sur EC2 Spot)
    """

    def __init__(
        self,
        tenant_id: str = "default",
        max_documents: int = 10,
        dry_run: bool = True,
        qwen_first: bool = False
    ):
        self.tenant_id = tenant_id
        self.max_documents = max_documents
        self.dry_run = dry_run
        self.qwen_first = qwen_first

        self.test_id = f"ab_pass2_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.result = ABTestResult(
            test_id=self.test_id,
            started_at=datetime.now(),
            documents_count=max_documents,
            qwen_first=qwen_first
        )

        # Lazy imports
        self._burst_orchestrator = None
        self._pass2_service = None

    def _get_burst_orchestrator(self):
        """Lazy load du BurstOrchestrator."""
        if self._burst_orchestrator is None:
            from knowbase.ingestion.burst.orchestrator import BurstOrchestrator
            from knowbase.ingestion.burst.types import BurstConfig

            config = BurstConfig()  # Utilise les valeurs par défaut
            self._burst_orchestrator = BurstOrchestrator(config)
        return self._burst_orchestrator

    def _get_pass2_service(self):
        """Lazy load du Pass2Service."""
        if self._pass2_service is None:
            from knowbase.api.services.pass2_service import get_pass2_service
            self._pass2_service = get_pass2_service(self.tenant_id)
        return self._pass2_service

    async def get_test_documents(self) -> List[str]:
        """
        Récupère une liste de documents pour le test.

        Critères de sélection:
        - Documents avec suffisamment de segments
        - Documents avec anchored_concepts
        - Limite au nombre demandé
        """
        from knowbase.common.clients.neo4j_client import Neo4jClient
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )

        # Récupérer documents avec le plus de concepts
        query = """
        MATCH (d:Document {tenant_id: $tenant_id})
        OPTIONAL MATCH (pc:ProtoConcept {tenant_id: $tenant_id, document_id: d.document_id})
        WITH d, count(pc) AS concept_count
        WHERE concept_count >= 10
        RETURN d.document_id AS doc_id, concept_count
        ORDER BY concept_count DESC
        LIMIT $limit
        """

        database = getattr(neo4j, 'database', 'neo4j')
        with neo4j.driver.session(database=database) as session:
            result = session.run(query, {
                "tenant_id": self.tenant_id,
                "limit": self.max_documents
            })
            docs = [record["doc_id"] for record in result if record["doc_id"]]

        neo4j.close()

        logger.info(f"[ABTest] Selected {len(docs)} documents for testing")
        return docs

    async def run_group_a(self, document_ids: List[str]) -> List[DocumentMetrics]:
        """
        Exécute le groupe A avec gpt-4o-mini (provider par défaut).
        """
        logger.info(f"[ABTest] === GROUP A: gpt-4o-mini ({len(document_ids)} documents) ===")

        if self.dry_run:
            logger.info("[ABTest] DRY RUN - Skipping actual extraction")
            return [DocumentMetrics(
                document_id=doc_id,
                provider="openai",
                total_segments=0,
                total_latency_ms=0.0
            ) for doc_id in document_ids]

        metrics = []
        pass2_service = self._get_pass2_service()

        for i, doc_id in enumerate(document_ids, 1):
            logger.info(f"[ABTest] Processing {doc_id} with gpt-4o-mini ({i}/{len(document_ids)})")
            start = time.time()

            try:
                result = await pass2_service.run_enrich_relations(
                    document_id=doc_id,
                    max_relations_per_doc=150
                )

                latency_ms = (time.time() - start) * 1000

                doc_metrics = DocumentMetrics(
                    document_id=doc_id,
                    provider="openai",
                    total_segments=result.items_processed,
                    total_latency_ms=latency_ms
                )

                # Extraire métriques détaillées depuis result.details
                if result.details.get("observability_summary"):
                    obs = result.details["observability_summary"]
                    doc_metrics.segments.append(SegmentMetrics(
                        segment_id="aggregated",
                        latency_ms=latency_ms,
                        relations_proposed=obs.get("total_proposed", 0),
                        relations_validated=obs.get("total_validated", 0),
                        relations_rejected=obs.get("total_rejected", 0),
                        fuzzy_score_avg=0.0
                    ))

                metrics.append(doc_metrics)

                # Sauvegarde incrémentale après chaque document
                self.result.group_a_metrics = metrics
                self.result.group_a_cost_usd = self.estimate_openai_cost(metrics)
                self._save_results(f"_gpt_doc{i}")

                logger.info(f"[ABTest] {doc_id}: {result.items_created} relations, {latency_ms:.0f}ms (saved)")

            except Exception as e:
                logger.error(f"[ABTest] Error processing {doc_id}: {e}")
                self._save_results("_gpt_error")

        # Sauvegarde finale groupe A
        self._save_results("_gpt_complete")
        return metrics

    async def run_group_b(self, document_ids: List[str]) -> List[DocumentMetrics]:
        """
        Exécute le groupe B avec Qwen-14B via vLLM sur EC2 Spot.

        Utilise l'orchestrateur Burst directement:
        1. Créer un fichier dummy + prepare_batch()
        2. start_infrastructure() (déploie EC2 + switch providers)
        3. Exécuter l'extraction Pass2
        4. cancel() pour cleanup
        """
        logger.info(f"[ABTest] === GROUP B: Qwen-14B/vLLM ({len(document_ids)} documents) ===")

        if self.dry_run:
            logger.info("[ABTest] DRY RUN - Skipping EC2 deployment and extraction")
            return [DocumentMetrics(
                document_id=doc_id,
                provider="vllm",
                total_segments=0,
                total_latency_ms=0.0
            ) for doc_id in document_ids]

        import asyncio

        pass2_service = self._get_pass2_service()
        orchestrator = self._get_burst_orchestrator()
        metrics = []
        ec2_start_time = time.time()

        try:
            # 1. Préparer un batch avec un fichier dummy
            logger.info("[ABTest] Preparing burst batch...")
            dummy_path = Path("data/burst/pending/ab_test_dummy.txt")
            dummy_path.parent.mkdir(parents=True, exist_ok=True)
            dummy_path.write_text("AB Test dummy file - triggers burst infrastructure")

            batch_id = orchestrator.prepare_batch([dummy_path])
            logger.info(f"[ABTest] Batch prepared: {batch_id}")

            # 2. Démarrer l'infrastructure EC2 Spot (5-10 min)
            logger.info("[ABTest] Starting EC2 Spot infrastructure (5-10 min)...")
            success = await asyncio.to_thread(orchestrator.start_infrastructure)

            if not success:
                logger.error("[ABTest] Failed to start EC2 infrastructure")
                self._save_results("_qwen_start_failed")
                return metrics

            vllm_url = orchestrator.state.vllm_url if orchestrator.state else None
            logger.info(f"[ABTest] EC2 ready - vLLM: {vllm_url}")
            # Note: Les providers sont automatiquement switchés par start_infrastructure()

            # 3. Exécuter l'extraction pour chaque document
            for i, doc_id in enumerate(document_ids, 1):
                logger.info(f"[ABTest] Processing {doc_id} with Qwen-14B ({i}/{len(document_ids)})")
                start = time.time()

                try:
                    result = await pass2_service.run_enrich_relations(
                        document_id=doc_id,
                        max_relations_per_doc=150
                    )

                    latency_ms = (time.time() - start) * 1000

                    doc_metrics = DocumentMetrics(
                        document_id=doc_id,
                        provider="vllm",
                        total_segments=result.items_processed,
                        total_latency_ms=latency_ms
                    )

                    if result.details.get("observability_summary"):
                        obs = result.details["observability_summary"]
                        doc_metrics.segments.append(SegmentMetrics(
                            segment_id="aggregated",
                            latency_ms=latency_ms,
                            relations_proposed=obs.get("total_proposed", 0),
                            relations_validated=obs.get("total_validated", 0),
                            relations_rejected=obs.get("total_rejected", 0),
                            fuzzy_score_avg=0.0
                        ))

                    metrics.append(doc_metrics)

                    # Sauvegarde incrémentale
                    self.result.group_b_metrics = metrics
                    self.result.ec2_runtime_seconds = time.time() - ec2_start_time
                    self.result.group_b_cost_usd = (self.result.ec2_runtime_seconds / 3600) * 1.30
                    self._save_results(f"_qwen_doc{i}")

                    logger.info(f"[ABTest] {doc_id}: {result.items_created} relations, {latency_ms:.0f}ms (saved)")

                except Exception as e:
                    logger.error(f"[ABTest] Error processing {doc_id}: {e}")
                    self._save_results("_qwen_error")

            # 4. Cleanup (désactive providers, conserve EC2 si souhaité)
            logger.info("[ABTest] Cancelling burst batch (cleanup)...")
            orchestrator.cancel()
            logger.info("[ABTest] Burst cancelled, providers back to normal")

        except Exception as e:
            logger.error(f"[ABTest] Group B failed: {e}")
            self._save_results("_qwen_failed")
            # Toujours essayer de cleanup
            try:
                orchestrator.cancel()
            except:
                pass

        finally:
            # Calculer le temps EC2
            self.result.ec2_runtime_seconds = time.time() - ec2_start_time

            # Coût EC2: ~1.20€/heure pour g6e.xlarge spot
            hours = self.result.ec2_runtime_seconds / 3600
            self.result.group_b_cost_usd = hours * 1.30  # ~1.30 USD (taux de change)

            logger.info(
                f"[ABTest] EC2 runtime: {self.result.ec2_runtime_seconds:.0f}s, "
                f"estimated cost: ${self.result.group_b_cost_usd:.2f}"
            )
            self.result.group_b_metrics = metrics
            self._save_results("_qwen_complete")

        return metrics

    def estimate_openai_cost(self, metrics: List[DocumentMetrics]) -> float:
        """
        Estime le coût OpenAI basé sur les tokens utilisés.

        gpt-4o-mini pricing (2024):
        - Input: $0.15 / 1M tokens
        - Output: $0.60 / 1M tokens

        Estimation: ~2000 tokens input + ~500 tokens output par segment
        """
        total_segments = sum(m.total_segments for m in metrics)

        # Estimation tokens
        input_tokens = total_segments * 2000
        output_tokens = total_segments * 500

        cost = (input_tokens * 0.15 / 1_000_000) + (output_tokens * 0.60 / 1_000_000)
        return cost

    async def run_test(self) -> ABTestResult:
        """
        Exécute le test A/B complet.

        Ordre configurable via qwen_first:
        - Par défaut: gpt-4o-mini puis Qwen-14B
        - Avec qwen_first: Qwen-14B puis gpt-4o-mini (détecte problèmes EC2 tôt)
        """
        logger.info(f"[ABTest] Starting test {self.test_id}")
        logger.info(f"[ABTest] Max documents: {self.max_documents}, Dry run: {self.dry_run}")
        logger.info(f"[ABTest] Order: {'Qwen FIRST' if self.qwen_first else 'GPT FIRST'}")

        # 1. Sélectionner les documents
        document_ids = await self.get_test_documents()

        if not document_ids:
            logger.error("[ABTest] No documents found for testing")
            self.result.ended_at = datetime.now()
            return self.result

        self.result.documents_count = len(document_ids)
        self._save_results("_started")

        if self.qwen_first:
            # Qwen d'abord (détecte problèmes EC2 rapidement)
            self.result.group_b_metrics = await self.run_group_b(document_ids)
            self.result.group_a_metrics = await self.run_group_a(document_ids)
            self.result.group_a_cost_usd = self.estimate_openai_cost(self.result.group_a_metrics)
        else:
            # GPT d'abord (par défaut)
            self.result.group_a_metrics = await self.run_group_a(document_ids)
            self.result.group_a_cost_usd = self.estimate_openai_cost(self.result.group_a_metrics)
            self.result.group_b_metrics = await self.run_group_b(document_ids)

        # Finaliser
        self.result.ended_at = datetime.now()

        # Sauvegarder les résultats finaux
        self._save_results()

        # Afficher le résumé
        self._print_summary()

        return self.result

    def _save_results(self, suffix: str = ""):
        """Sauvegarde incrémentale des résultats en JSON."""
        output_dir = Path("data/ab_tests")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Fichier principal (toujours mis à jour)
        output_file = output_dir / f"{self.test_id}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(self.result.to_dict(), f, indent=2, ensure_ascii=False)

        # Checkpoint avec suffixe si spécifié
        if suffix:
            checkpoint = output_dir / f"{self.test_id}{suffix}.json"
            with open(checkpoint, "w", encoding="utf-8") as f:
                json.dump(self.result.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"[ABTest] Checkpoint: {checkpoint}")
        else:
            logger.info(f"[ABTest] Final: {output_file}")

    def _print_summary(self):
        """Affiche un résumé du test."""
        data = self.result.to_dict()

        print("\n" + "=" * 70)
        print(f"  TEST A/B PASS 2 - RÉSULTATS")
        print(f"  Test ID: {self.test_id}")
        print("=" * 70)

        print(f"\n📊 Documents testés: {data['documents_count']}")

        print("\n┌────────────────────┬──────────────────┬──────────────────┐")
        print("│ Métrique           │ gpt-4o-mini      │ Qwen-14B (vLLM)  │")
        print("├────────────────────┼──────────────────┼──────────────────┤")

        ga = data["group_a"]
        gb = data["group_b"]

        print(f"│ Segments traités   │ {ga['total_segments']:>16} │ {gb['total_segments']:>16} │")
        print(f"│ Relations extraites│ {ga['total_relations']:>16} │ {gb['total_relations']:>16} │")
        print(f"│ Précision moyenne  │ {ga['avg_precision']:>15.1%} │ {gb['avg_precision']:>15.1%} │")
        print(f"│ Latence moyenne    │ {ga['avg_latency_ms']:>13.0f} ms │ {gb['avg_latency_ms']:>13.0f} ms │")
        print(f"│ Coût estimé        │ ${ga['cost_usd']:>14.2f} │ ${gb['cost_usd']:>14.2f} │")

        print("└────────────────────┴──────────────────┴──────────────────┘")

        if data["ec2_runtime_seconds"] > 0:
            print(f"\n⏱️  Temps EC2 total: {data['ec2_runtime_seconds']:.0f}s")

        # Verdict
        print("\n" + "-" * 70)
        if ga['total_relations'] > 0 and gb['total_relations'] > 0:
            quality_diff = (gb['avg_precision'] - ga['avg_precision']) / max(0.001, ga['avg_precision']) * 100
            cost_diff = (gb['cost_usd'] - ga['cost_usd']) / max(0.001, ga['cost_usd']) * 100

            print(f"📈 Différence qualité: {quality_diff:+.1f}% (Qwen-14B vs gpt-4o-mini)")
            print(f"💰 Différence coût: {cost_diff:+.1f}%")

            if quality_diff > 5 and cost_diff < 50:
                print("\n✅ VERDICT: Qwen-14B offre un meilleur rapport qualité/prix")
            elif quality_diff < -5:
                print("\n⚠️  VERDICT: gpt-4o-mini offre une meilleure qualité")
            else:
                print("\n🤔 VERDICT: Différence marginale, considérer d'autres facteurs")
        else:
            print("⚠️  Pas assez de données pour un verdict")

        print("=" * 70 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="Test A/B Pass 2: gpt-4o-mini vs Qwen-14B")

    parser.add_argument(
        "--documents", "-d",
        type=int,
        default=10,
        help="Nombre de documents à tester (défaut: 10)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation sans exécution réelle"
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Exécuter réellement le test (sans dry-run)"
    )

    parser.add_argument(
        "--tenant",
        type=str,
        default="default",
        help="Tenant ID (défaut: default)"
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
    )

    parser.add_argument(
        "--qwen-first",
        action="store_true",
        help="Tester Qwen-14B en premier (detecte problemes EC2 rapidement)"
    )

    args = parser.parse_args()

    # Dry run par défaut sauf si --execute
    dry_run = not args.execute

    if not dry_run and not args.yes:
        print("\n⚠️  ATTENTION: Mode exécution réelle!")
        print("   - EC2 Spot sera déployé (~1.20€/heure)")
        print("   - Les relations extraites seront persistées")
        try:
            confirm = input("   Continuer? [y/N] ")
            if confirm.lower() != 'y':
                print("Annulé.")
                return
        except EOFError:
            print("   Mode non-interactif détecté, utilisez --yes pour confirmer")
            return

    tester = Pass2ABTester(
        tenant_id=args.tenant,
        max_documents=args.documents,
        dry_run=dry_run,
        qwen_first=args.qwen_first
    )

    result = await tester.run_test()

    if dry_run:
        print("\nPour executer: python scripts/pass2_ab_test.py --execute --yes")
        print("Pour Qwen en premier: python scripts/pass2_ab_test.py --execute --yes --qwen-first")


if __name__ == "__main__":
    asyncio.run(main())
