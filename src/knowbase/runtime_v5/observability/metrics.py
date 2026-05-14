"""V5 MetricsRegistry — abstractions Counter + Histogram (CH-52.7.3 / S6.3).

ADR V1.5 §3g : low-cardinality SLO metrics séparés des traces.

Modèle Prometheus-compatible :
- Counter : valeur monotone croissante (incr-only). Ex : tool_call_total
- Histogram : distribution avec buckets (latence p50/p95/p99)
- Gauge : valeur point-in-time (ex : queue_depth)

Implémentation V1.5 : in-memory, exposable via /metrics endpoint.
Production : adaptateur Prometheus client (PrometheusMetricsRegistry, post-S6).
"""
from __future__ import annotations

import threading
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Optional


# ─── Histogram buckets (defaults Prometheus-like) ───────────────────────────


# Latence en secondes (cohérent gen_ai.client.operation.duration)
DEFAULT_LATENCY_BUCKETS_S = (
    0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 60.0, 90.0, 180.0,
)
# Tokens
DEFAULT_TOKEN_BUCKETS = (
    100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 200_000,
)
# Iterations
DEFAULT_ITER_BUCKETS = (1, 2, 3, 5, 8, 12)


# ─── Counter ─────────────────────────────────────────────────────────────────


class Counter:
    """Monotonic counter par label-set."""

    def __init__(self, name: str, help_text: str = "", label_keys: Optional[list[str]] = None):
        self.name = name
        self.help_text = help_text
        self.label_keys = sorted(label_keys or [])
        self._lock = threading.RLock()
        # key = tuple des valeurs labels dans l'ordre alphabétique des keys
        self._values: dict[tuple, float] = {}

    def _label_key(self, labels: Optional[dict[str, str]] = None) -> tuple:
        if not self.label_keys:
            return ()
        labels = labels or {}
        return tuple(str(labels.get(k, "")) for k in self.label_keys)

    def inc(self, amount: float = 1.0, labels: Optional[dict[str, str]] = None) -> None:
        if amount < 0:
            raise ValueError("Counter cannot decrease")
        with self._lock:
            key = self._label_key(labels)
            self._values[key] = self._values.get(key, 0.0) + amount

    def get(self, labels: Optional[dict[str, str]] = None) -> float:
        with self._lock:
            return self._values.get(self._label_key(labels), 0.0)

    def snapshot(self) -> dict[tuple, float]:
        with self._lock:
            return dict(self._values)


# ─── Gauge ───────────────────────────────────────────────────────────────────


class Gauge:
    """Valeur point-in-time, peut monter ou descendre."""

    def __init__(self, name: str, help_text: str = "", label_keys: Optional[list[str]] = None):
        self.name = name
        self.help_text = help_text
        self.label_keys = sorted(label_keys or [])
        self._lock = threading.RLock()
        self._values: dict[tuple, float] = {}

    def _label_key(self, labels: Optional[dict[str, str]] = None) -> tuple:
        if not self.label_keys:
            return ()
        labels = labels or {}
        return tuple(str(labels.get(k, "")) for k in self.label_keys)

    def set(self, value: float, labels: Optional[dict[str, str]] = None) -> None:
        with self._lock:
            self._values[self._label_key(labels)] = value

    def inc(self, amount: float = 1.0, labels: Optional[dict[str, str]] = None) -> None:
        with self._lock:
            key = self._label_key(labels)
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, labels: Optional[dict[str, str]] = None) -> None:
        with self._lock:
            key = self._label_key(labels)
            self._values[key] = self._values.get(key, 0.0) - amount

    def get(self, labels: Optional[dict[str, str]] = None) -> float:
        with self._lock:
            return self._values.get(self._label_key(labels), 0.0)


# ─── Histogram ───────────────────────────────────────────────────────────────


@dataclass
class HistogramData:
    """Stats agrégées d'un histogram pour 1 label-set."""
    count: int = 0
    sum: float = 0.0
    # buckets : dict[upper_bound, cumulative_count]
    buckets: dict[float, int] = field(default_factory=dict)


class Histogram:
    """Distribution avec buckets + sum + count + percentiles approximés."""

    def __init__(
        self,
        name: str,
        help_text: str = "",
        label_keys: Optional[list[str]] = None,
        buckets: tuple = DEFAULT_LATENCY_BUCKETS_S,
    ):
        self.name = name
        self.help_text = help_text
        self.label_keys = sorted(label_keys or [])
        self.buckets = tuple(sorted(buckets))
        self._lock = threading.RLock()
        self._data: dict[tuple, HistogramData] = {}

    def _label_key(self, labels: Optional[dict[str, str]] = None) -> tuple:
        if not self.label_keys:
            return ()
        labels = labels or {}
        return tuple(str(labels.get(k, "")) for k in self.label_keys)

    def observe(self, value: float, labels: Optional[dict[str, str]] = None) -> None:
        with self._lock:
            key = self._label_key(labels)
            data = self._data.setdefault(key, HistogramData())
            data.count += 1
            data.sum += value
            # incremente buckets : toutes les upper_bound >= value
            for ub in self.buckets:
                if value <= ub:
                    data.buckets[ub] = data.buckets.get(ub, 0) + 1

    def get_data(self, labels: Optional[dict[str, str]] = None) -> HistogramData:
        with self._lock:
            return self._data.get(self._label_key(labels), HistogramData())

    def percentile(self, p: float, labels: Optional[dict[str, str]] = None) -> Optional[float]:
        """Percentile approximé via buckets (interpolation linéaire entre buckets).

        p ∈ [0, 1]. Retourne None si pas d'observations.
        """
        with self._lock:
            data = self._data.get(self._label_key(labels))
            if data is None or data.count == 0:
                return None
            target = p * data.count
            # find smallest bucket where cumulative_count >= target
            sorted_buckets = sorted(data.buckets.items())
            for ub, cum in sorted_buckets:
                if cum >= target:
                    return ub
            return self.buckets[-1] if self.buckets else None

    def average(self, labels: Optional[dict[str, str]] = None) -> Optional[float]:
        d = self.get_data(labels)
        return (d.sum / d.count) if d.count > 0 else None


# ─── MetricsRegistry ─────────────────────────────────────────────────────────


class MetricsRegistry:
    """Registry centralisé pour Counter / Gauge / Histogram.

    Args:
        name_prefix : préfixe ajouté aux noms (default "v5_")
    """

    def __init__(self, name_prefix: str = "v5_"):
        self.name_prefix = name_prefix
        self._lock = threading.RLock()
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(
        self,
        name: str,
        help_text: str = "",
        label_keys: Optional[list[str]] = None,
    ) -> Counter:
        full_name = self.name_prefix + name
        with self._lock:
            c = self._counters.get(full_name)
            if c is None:
                c = Counter(full_name, help_text=help_text, label_keys=label_keys)
                self._counters[full_name] = c
            return c

    def gauge(
        self,
        name: str,
        help_text: str = "",
        label_keys: Optional[list[str]] = None,
    ) -> Gauge:
        full_name = self.name_prefix + name
        with self._lock:
            g = self._gauges.get(full_name)
            if g is None:
                g = Gauge(full_name, help_text=help_text, label_keys=label_keys)
                self._gauges[full_name] = g
            return g

    def histogram(
        self,
        name: str,
        help_text: str = "",
        label_keys: Optional[list[str]] = None,
        buckets: tuple = DEFAULT_LATENCY_BUCKETS_S,
    ) -> Histogram:
        full_name = self.name_prefix + name
        with self._lock:
            h = self._histograms.get(full_name)
            if h is None:
                h = Histogram(
                    full_name, help_text=help_text,
                    label_keys=label_keys, buckets=buckets,
                )
                self._histograms[full_name] = h
            return h

    def snapshot(self) -> dict:
        """Snapshot complet pour debugging / cockpit."""
        with self._lock:
            return {
                "counters": {
                    name: c.snapshot() for name, c in self._counters.items()
                },
                "gauges": {
                    name: dict(g._values) for name, g in self._gauges.items()
                },
                "histograms": {
                    name: {
                        str(key): {
                            "count": d.count,
                            "sum": d.sum,
                            "p50": h.percentile(0.50, dict(zip(h.label_keys, key))),
                            "p95": h.percentile(0.95, dict(zip(h.label_keys, key))),
                            "p99": h.percentile(0.99, dict(zip(h.label_keys, key))),
                            "avg": h.average(dict(zip(h.label_keys, key))),
                        }
                        for key, d in h._data.items()
                    }
                    for name, h in self._histograms.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# ─── Sampling Tier (S6.4) ────────────────────────────────────────────────────


from enum import Enum


class SamplingTier(str, Enum):
    """Tiers ADR §3g §Y9."""
    TIER1_SLO = "tier1_slo"  # 100% counters/histograms (low cardinality)
    TIER2_TRACE = "tier2_trace"  # sampled : 100% errors + 10% success > 5 iter
    TIER3_FULL_CONTENT = "tier3_full_content"  # opt-in tenant only, 7j retention


@dataclass
class SamplingDecision:
    """Décision sampling pour un run agent."""
    tier1_recorded: bool = True  # toujours
    tier2_trace_captured: bool = False
    tier3_full_content_captured: bool = False
    reason: str = ""


class SamplingPolicy:
    """Politique de sampling déterministe.

    Tier 2 :
        - 100% des runs avec error
        - 100% des runs avec n_iterations >= threshold_high_iter (default 5)
        - 10% sample sur les autres (sample par hash request_id)
    Tier 3 :
        - Uniquement si tenant.opt_in_full_content_tracing = True
    """

    def __init__(
        self,
        success_sample_rate: float = 0.10,
        threshold_high_iter: int = 5,
    ):
        if not (0.0 <= success_sample_rate <= 1.0):
            raise ValueError("success_sample_rate must be in [0, 1]")
        self.success_sample_rate = success_sample_rate
        self.threshold_high_iter = threshold_high_iter

    def decide(
        self,
        request_id: str,
        has_error: bool,
        n_iterations: int,
        tenant_opt_in_full_content: bool = False,
    ) -> SamplingDecision:
        # Tier 1 always
        decision = SamplingDecision(tier1_recorded=True)

        # Tier 2 logic
        if has_error:
            decision.tier2_trace_captured = True
            decision.reason = "error"
        elif n_iterations >= self.threshold_high_iter:
            decision.tier2_trace_captured = True
            decision.reason = f"high_iter_{n_iterations}"
        else:
            # Hash-based deterministic sampling (cohérent multi-instances)
            import hashlib
            h = int(hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:8], 16)
            bucket = (h % 10_000) / 10_000.0  # [0, 1)
            if bucket < self.success_sample_rate:
                decision.tier2_trace_captured = True
                decision.reason = "sampled_success"

        # Tier 3 only if tenant opt-in AND tier2 captured (sinon pas de trace)
        if tenant_opt_in_full_content and decision.tier2_trace_captured:
            decision.tier3_full_content_captured = True

        return decision


# ─── Singletons ──────────────────────────────────────────────────────────────


_default_registry: Optional[MetricsRegistry] = None


def get_default_metrics() -> MetricsRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = MetricsRegistry()
    return _default_registry


def reset_default_metrics() -> None:
    global _default_registry
    _default_registry = None
