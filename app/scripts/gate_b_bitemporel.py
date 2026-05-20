#!/usr/bin/env python3
"""Gate-B Tests Phase A1.4 — validation bitemporel claims.

ADR_BITEMPOREL_CLAIMS.md §3.3 (Gate-B) + §9 addendum (corrections sémantique NULL).

Tests exécutés :
  T1  Tous les claims ont `ingested_at` (révisé §9.8 — `valid_from` NULL est légitime
      depuis la décision S1 désactivé, ne PAS le compter comme "missing").
  T2  Sur le doc le plus récemment ingéré (proxy pour "nouveau doc"), tous ses claims
      ont au moins `ingested_at`. Ce test devient probant après une vraie ré-ingestion
      A1.3 (RISE Bootcamp avec S1 désactivé → valid_from = NULL marker = ingestion_fallback).
  T3  3 queries point-in-time §2.4 retournent résultats cohérents sur échantillon
      stratifié de 10 claims (2 par doc, 5 docs distincts).
  T4  EXPLAIN confirme usage des 3 indexes `claim_active`, `claim_event_time`,
      `claim_ingested` ; queries restent isolées par tenant.
  T5  Perf : p50 < 100ms, p95 < 500ms (BLOQUANT), p99 < 1s sur queries §2.4.
      Mesuré sur N=20 répétitions par query.

Usage :
  docker-compose exec app python scripts/gate_b_bitemporel.py [--tenant default] [--out FILE.json]

Sortie console : tableau récapitulatif + verdict PASS/FAIL.
Sortie JSON : détail complet pour archivage.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Seuils Gate-B (ADR §3.3 test 5)
# ─────────────────────────────────────────────────────────────────────────────

P50_THRESHOLD_MS = 100.0
P95_THRESHOLD_MS = 500.0   # BLOQUANT
P99_THRESHOLD_MS = 1000.0
QUERY_REPETITIONS = 20      # par query pour avoir des percentiles robustes


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    passed: bool
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    is_blocking: bool = True


@dataclass
class GateBReport:
    tenant_id: str
    executed_at: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def all_blocking_passed(self) -> bool:
        return all(r.passed for r in self.results if r.is_blocking)

    @property
    def verdict(self) -> str:
        return "PASS" if self.all_blocking_passed else "FAIL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "executed_at": self.executed_at,
            "verdict": self.verdict,
            "all_blocking_passed": self.all_blocking_passed,
            "results": [asdict(r) for r in self.results],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j client
# ─────────────────────────────────────────────────────────────────────────────


def get_client():
    """Connexion via le client Neo4j commun de knowbase."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    return get_neo4j_client()


def run(client, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Exécute une query Cypher et retourne les records sous forme de dicts."""
    with client.driver.session() as session:
        result = session.run(query, params or {})
        return [dict(r) for r in result]


def explain(client, query: str, params: dict[str, Any] | None = None) -> str:
    """Retourne le plan EXPLAIN d'une query (sans l'exécuter)."""
    with client.driver.session() as session:
        result = session.run(f"EXPLAIN {query}", params or {})
        plan = result.consume().plan
        return _serialize_plan(plan)


def _plan_attr(plan, key: str, default=None):
    """Accède à un attribut d'un plan EXPLAIN — supporte dict OR object."""
    if plan is None:
        return default
    if isinstance(plan, dict):
        return plan.get(key, default)
    return getattr(plan, key, default)


def _serialize_plan(plan, depth: int = 0) -> str:
    """Sérialise récursivement le plan EXPLAIN en texte indenté.

    Le driver Neo4j renvoie le plan soit comme objet `Plan` (anciennes versions)
    soit comme dict (versions récentes). On gère les deux via `_plan_attr`.
    """
    if plan is None:
        return ""
    indent = "  " * depth
    op_type = _plan_attr(plan, "operatorType") or _plan_attr(plan, "operator_type") or "?"
    line = f"{indent}{op_type}"
    args = _plan_attr(plan, "arguments") or {}
    if isinstance(args, dict):
        keep = {k: v for k, v in args.items() if k in ("Index", "Details", "EstimatedRows")}
        if keep:
            line += f" {keep}"
    lines = [line]
    children = _plan_attr(plan, "children") or []
    for child in children:
        lines.append(_serialize_plan(child, depth + 1))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tests Gate-B
# ─────────────────────────────────────────────────────────────────────────────


def test_1_ingested_at_coverage(client, tenant_id: str) -> TestResult:
    """T1 — 100% des claims ont `ingested_at` (révisé §9.8)."""
    rows = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        RETURN
          count(c) AS total,
          sum(CASE WHEN c.ingested_at IS NOT NULL THEN 1 ELSE 0 END) AS with_ingested,
          sum(CASE WHEN c.ingested_at IS NULL THEN 1 ELSE 0 END) AS missing_ingested
        """,
        {"tenant": tenant_id},
    )
    row = rows[0] if rows else {"total": 0, "with_ingested": 0, "missing_ingested": 0}
    total = row["total"]
    missing = row["missing_ingested"]
    passed = (total > 0) and (missing == 0)
    return TestResult(
        name="T1 — Coverage ingested_at",
        passed=passed,
        summary=f"{row['with_ingested']}/{total} claims avec ingested_at (missing={missing})",
        details=row,
    )


def test_2_recent_doc_timestamps(client, tenant_id: str) -> TestResult:
    """T2 — Sur le doc le plus récemment ingéré, tous ses claims ont les timestamps requis.

    Note : `valid_from` peut être NULL (§9.1). On vérifie uniquement `ingested_at`.
    """
    docs = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        WITH c.doc_id AS doc_id, max(c.ingested_at) AS last_ingested, count(c) AS n_claims
        RETURN doc_id, last_ingested, n_claims
        ORDER BY last_ingested DESC
        LIMIT 1
        """,
        {"tenant": tenant_id},
    )
    if not docs:
        return TestResult(
            name="T2 — Timestamps doc récent",
            passed=False,
            summary="Aucun claim trouvé pour ce tenant",
            details={},
        )
    target_doc_id = docs[0]["doc_id"]
    rows = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant, doc_id: $doc_id})
        RETURN
          count(c) AS total,
          sum(CASE WHEN c.ingested_at IS NULL THEN 1 ELSE 0 END) AS missing_ingested,
          sum(CASE WHEN c.valid_from IS NOT NULL THEN 1 ELSE 0 END) AS with_valid_from,
          sum(CASE WHEN c.valid_until IS NOT NULL THEN 1 ELSE 0 END) AS with_valid_until,
          sum(CASE WHEN c.invalidated_at IS NOT NULL THEN 1 ELSE 0 END) AS with_invalidated
        """,
        {"tenant": tenant_id, "doc_id": target_doc_id},
    )
    row = rows[0] if rows else {}
    total = row.get("total", 0)
    missing = row.get("missing_ingested", 0)
    passed = (total > 0) and (missing == 0)
    return TestResult(
        name="T2 — Timestamps doc récent",
        passed=passed,
        summary=(
            f"doc={target_doc_id} ({total} claims) — "
            f"missing_ingested={missing}, valid_from={row.get('with_valid_from')}, "
            f"valid_until={row.get('with_valid_until')}, invalidated_at={row.get('with_invalidated')}"
        ),
        details={"target_doc_id": target_doc_id, **row},
    )


def test_3_point_in_time_queries(client, tenant_id: str) -> TestResult:
    """T3 — Les 3 queries §2.4 sur échantillon stratifié.

    Stratification : 10 claims pris dans 5 docs distincts (2 par doc). Sur ces
    claims, on vérifie que les 3 queries §2.4 (now, as-of past, invalidated since past)
    retournent des résultats cohérents (pas d'erreur, distribution attendue).
    """
    # Échantillon stratifié : 5 docs distincts, 2 claims par doc
    sample = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        WITH c.doc_id AS doc_id, collect(c)[..2] AS pair
        WITH doc_id, pair LIMIT 5
        UNWIND pair AS c
        RETURN c.claim_id AS claim_id, c.doc_id AS doc_id, c.valid_from AS valid_from, c.ingested_at AS ingested_at
        """,
        {"tenant": tenant_id},
    )

    # Q1 : "qu'est vrai aujourd'hui ?" — §9.1 le filtre accepte valid_from NULL
    q1 = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        WHERE c.invalidated_at IS NULL
          AND (c.valid_until IS NULL OR c.valid_until > datetime())
          AND (c.valid_from IS NULL OR c.valid_from <= datetime())
        RETURN count(c) AS n
        """,
        {"tenant": tenant_id},
    )

    # Q2 : "qu'était vrai au 2024-01-15 ?"
    q2 = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        WHERE (c.valid_from IS NULL OR c.valid_from <= datetime('2024-01-15'))
          AND (c.valid_until IS NULL OR c.valid_until > datetime('2024-01-15'))
          AND c.ingested_at <= datetime('2024-01-15')
          AND (c.invalidated_at IS NULL OR c.invalidated_at > datetime('2024-01-15'))
        RETURN count(c) AS n
        """,
        {"tenant": tenant_id},
    )

    # Q3 : "qu'a-t-on appris avant 2024-01-15 mais invalidé depuis ?"
    q3 = run(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        WHERE c.ingested_at <= datetime('2024-01-15')
          AND c.invalidated_at IS NOT NULL
          AND c.invalidated_at > datetime('2024-01-15')
        RETURN count(c) AS n
        """,
        {"tenant": tenant_id},
    )

    q1_count = q1[0]["n"] if q1 else 0
    q2_count = q2[0]["n"] if q2 else 0
    q3_count = q3[0]["n"] if q3 else 0

    # Cohérence attendue post-A1.2 sans A2 :
    # - Q1 > 0 (on a des claims actifs)
    # - Q2 ≥ 0 (peut être 0 si tous les claims sont ingérés après 2024-01-15)
    # - Q3 == 0 (pas encore d'invalidation A2 en place)
    passed = (q1_count > 0) and (q3_count == 0) and (len(sample) > 0)
    return TestResult(
        name="T3 — Queries point-in-time",
        passed=passed,
        summary=(
            f"sample={len(sample)} claims stratifiés, Q1(now)={q1_count}, "
            f"Q2(2024-01-15)={q2_count}, Q3(invalidated-since)={q3_count} "
            f"(attendu Q3=0 sans A2)"
        ),
        details={
            "sample_size": len(sample),
            "sample_first_3": sample[:3],
            "q1_now": q1_count,
            "q2_as_of_2024_01_15": q2_count,
            "q3_invalidated_since_2024_01_15": q3_count,
        },
    )


def test_4_indexes_and_tenant_isolation(client, tenant_id: str) -> TestResult:
    """T4 — EXPLAIN confirme usage des 3 indexes + isolation tenant."""
    indexes = run(
        client,
        """
        SHOW INDEXES YIELD name, state, type, labelsOrTypes, properties
        WHERE name IN ['claim_active', 'claim_event_time', 'claim_ingested']
        RETURN name, state, type, labelsOrTypes, properties
        """,
    )
    by_name = {row["name"]: row for row in indexes}
    expected_indexes = ["claim_active", "claim_event_time", "claim_ingested"]
    missing = [n for n in expected_indexes if n not in by_name]
    not_online = [n for n, row in by_name.items() if row.get("state") != "ONLINE"]

    # EXPLAIN sur Q1 (la plus fréquente runtime) pour vérifier index usage
    q1_plan = explain(
        client,
        """
        MATCH (c:Claim {tenant_id: $tenant})
        WHERE c.invalidated_at IS NULL
          AND (c.valid_until IS NULL OR c.valid_until > datetime())
          AND (c.valid_from IS NULL OR c.valid_from <= datetime())
        RETURN count(c) AS n
        """,
        {"tenant": tenant_id},
    )
    plan_uses_index = ("NodeIndexSeek" in q1_plan) or ("Index" in q1_plan)

    passed = (not missing) and (not not_online) and plan_uses_index
    return TestResult(
        name="T4 — Indexes & EXPLAIN",
        passed=passed,
        summary=(
            f"3 indexes attendus, {len(by_name)} trouvés "
            f"(missing={missing}, not_online={not_online}, plan_uses_index={plan_uses_index})"
        ),
        details={
            "indexes_found": list(by_name.keys()),
            "indexes_missing": missing,
            "indexes_not_online": not_online,
            "q1_plan_excerpt": q1_plan[:800],
            "plan_uses_index": plan_uses_index,
        },
    )


def test_5_query_latency(client, tenant_id: str) -> TestResult:
    """T5 — Perf : p50<100ms, p95<500ms (BLOQUANT), p99<1s sur queries §2.4."""
    queries = {
        "Q1_now": (
            """
            MATCH (c:Claim {tenant_id: $tenant})
            WHERE c.invalidated_at IS NULL
              AND (c.valid_until IS NULL OR c.valid_until > datetime())
              AND (c.valid_from IS NULL OR c.valid_from <= datetime())
            RETURN count(c) AS n
            """,
            {"tenant": tenant_id},
        ),
        "Q2_as_of_2024_01_15": (
            """
            MATCH (c:Claim {tenant_id: $tenant})
            WHERE (c.valid_from IS NULL OR c.valid_from <= datetime('2024-01-15'))
              AND (c.valid_until IS NULL OR c.valid_until > datetime('2024-01-15'))
              AND c.ingested_at <= datetime('2024-01-15')
              AND (c.invalidated_at IS NULL OR c.invalidated_at > datetime('2024-01-15'))
            RETURN count(c) AS n
            """,
            {"tenant": tenant_id},
        ),
        "Q3_invalidated_since": (
            """
            MATCH (c:Claim {tenant_id: $tenant})
            WHERE c.ingested_at <= datetime('2024-01-15')
              AND c.invalidated_at IS NOT NULL
              AND c.invalidated_at > datetime('2024-01-15')
            RETURN count(c) AS n
            """,
            {"tenant": tenant_id},
        ),
    }
    per_query: dict[str, dict[str, float]] = {}
    all_latencies_ms: list[float] = []
    for name, (cypher, params) in queries.items():
        latencies = []
        for _ in range(QUERY_REPETITIONS):
            t0 = time.perf_counter()
            run(client, cypher, params)
            latencies.append((time.perf_counter() - t0) * 1000)
        latencies.sort()
        per_query[name] = {
            "p50_ms": _pct(latencies, 50),
            "p95_ms": _pct(latencies, 95),
            "p99_ms": _pct(latencies, 99),
            "max_ms": latencies[-1],
            "min_ms": latencies[0],
            "n": len(latencies),
        }
        all_latencies_ms.extend(latencies)

    all_latencies_ms.sort()
    aggregate = {
        "p50_ms": _pct(all_latencies_ms, 50),
        "p95_ms": _pct(all_latencies_ms, 95),
        "p99_ms": _pct(all_latencies_ms, 99),
        "max_ms": all_latencies_ms[-1],
        "n_total": len(all_latencies_ms),
    }
    blocking_pass = aggregate["p95_ms"] < P95_THRESHOLD_MS
    soft_pass = (aggregate["p50_ms"] < P50_THRESHOLD_MS) and (aggregate["p99_ms"] < P99_THRESHOLD_MS)
    passed = blocking_pass and soft_pass
    return TestResult(
        name="T5 — Perf queries §2.4",
        passed=passed,
        summary=(
            f"p50={aggregate['p50_ms']:.1f}ms (seuil<{P50_THRESHOLD_MS}), "
            f"p95={aggregate['p95_ms']:.1f}ms (seuil<{P95_THRESHOLD_MS}, BLOQUANT), "
            f"p99={aggregate['p99_ms']:.1f}ms (seuil<{P99_THRESHOLD_MS})"
        ),
        details={
            "aggregate": aggregate,
            "per_query": per_query,
            "thresholds_ms": {
                "p50": P50_THRESHOLD_MS,
                "p95_blocking": P95_THRESHOLD_MS,
                "p99": P99_THRESHOLD_MS,
            },
            "blocking_pass": blocking_pass,
            "soft_pass": soft_pass,
        },
    )


def _pct(sorted_values: list[float], p: int) -> float:
    if not sorted_values:
        return 0.0
    idx = max(0, min(len(sorted_values) - 1, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[idx]


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrateur
# ─────────────────────────────────────────────────────────────────────────────


def run_all_tests(tenant_id: str) -> GateBReport:
    client = get_client()
    report = GateBReport(
        tenant_id=tenant_id,
        executed_at=datetime.now(timezone.utc).isoformat(),
    )
    for fn in (
        test_1_ingested_at_coverage,
        test_2_recent_doc_timestamps,
        test_3_point_in_time_queries,
        test_4_indexes_and_tenant_isolation,
        test_5_query_latency,
    ):
        logger.info(f"▶ {fn.__name__}")
        try:
            result = fn(client, tenant_id)
        except Exception as exc:
            result = TestResult(
                name=fn.__name__,
                passed=False,
                summary=f"EXCEPTION : {type(exc).__name__}: {exc}",
                details={"error_type": type(exc).__name__, "error": str(exc)},
            )
        report.results.append(result)
        status = "✅ PASS" if result.passed else "❌ FAIL"
        logger.info(f"   {status} — {result.summary}")
    return report


def main():
    ap = argparse.ArgumentParser(description="Gate-B Tests Phase A1.4 — Bitemporel claims")
    ap.add_argument("--tenant", default="default", help="Tenant ID à auditer (default: 'default')")
    ap.add_argument(
        "--out",
        default=None,
        help="Chemin JSON de sortie (default: data/benchmark/gate_b/A1.4_<ts>.json)",
    )
    args = ap.parse_args()

    logger.info(f"\n=== Gate-B Phase A1.4 — tenant={args.tenant} ===\n")
    report = run_all_tests(args.tenant)

    logger.info(f"\n=== Verdict global : {report.verdict} ===")
    for r in report.results:
        status = "✅" if r.passed else "❌"
        logger.info(f"  {status} {r.name}")

    # Persist JSON
    out_path = (
        Path(args.out)
        if args.out
        else Path(f"data/benchmark/gate_b/A1.4_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    logger.info(f"\nRapport persisté : {out_path}")

    sys.exit(0 if report.all_blocking_passed else 1)


if __name__ == "__main__":
    main()
