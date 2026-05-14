"""Tests Observability : tracer + metrics + sampling (CH-52.7.2 + 7.3 + 7.4)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.observability.metrics import (
    DEFAULT_LATENCY_BUCKETS_S,
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    SamplingDecision,
    SamplingPolicy,
    SamplingTier,
    get_default_metrics,
    reset_default_metrics,
)
from knowbase.runtime_v5.observability.pii import PIIRedactor
from knowbase.runtime_v5.observability.tracer import (
    InMemoryTracer,
    NoOpTracer,
    Span,
    SpanContext,
    SpanStatus,
    get_default_tracer,
    reset_default_tracer,
    set_default_tracer,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_default_tracer()
    reset_default_metrics()
    yield
    reset_default_tracer()
    reset_default_metrics()


# ════════════════════════════════════════════════════════════════════════════
# TRACER (S6.2)
# ════════════════════════════════════════════════════════════════════════════


class TestNoOpTracer:
    def test_start_end_span(self):
        t = NoOpTracer()
        s = t.start_span("test")
        assert s.name == "test"
        assert s.span_id.startswith("sp_")
        assert s.trace_id.startswith("tr_")
        t.end_span(s)
        assert s.end_time is not None

    def test_child_span_inherits_trace(self):
        t = NoOpTracer()
        parent = t.start_span("parent")
        child = t.start_span("child", parent_span=parent)
        assert child.trace_id == parent.trace_id
        assert child.parent_id == parent.span_id

    def test_attributes_on_create(self):
        t = NoOpTracer()
        s = t.start_span("test", attributes={"k": "v", "n": 42})
        assert s.attributes == {"k": "v", "n": 42}


class TestInMemoryTracer:
    def test_captures_spans(self):
        t = InMemoryTracer()
        s = t.start_span("root", attributes={"foo": "bar"})
        t.end_span(s)
        assert len(t.spans) == 1
        assert t.spans[0].name == "root"
        assert t.spans[0].attributes["foo"] == "bar"

    def test_get_spans_by_name(self):
        t = InMemoryTracer()
        for _ in range(3):
            s = t.start_span("foo")
            t.end_span(s)
        s = t.start_span("bar")
        t.end_span(s)
        assert len(t.get_spans_by_name("foo")) == 3
        assert len(t.get_spans_by_name("bar")) == 1

    def test_hierarchy(self):
        t = InMemoryTracer()
        root = t.start_span("root")
        c1 = t.start_span("child_1", parent_span=root)
        t.end_span(c1)
        c2 = t.start_span("child_2", parent_span=root)
        t.end_span(c2)
        t.end_span(root)
        assert len(t.get_root_spans()) == 1
        children = t.get_children(root)
        assert len(children) == 2

    def test_pii_redaction_in_attributes(self):
        redactor = PIIRedactor()
        t = InMemoryTracer(redactor=redactor)
        s = t.start_span("test", attributes={
            "user_email": "fred@example.com",
            "ip": "192.168.1.1",
            "clean": "no PII here",
        })
        t.end_span(s)
        # Attributs redacted post-end
        assert "fred@example.com" not in s.attributes["user_email"]
        assert "192.168.1.1" not in s.attributes["ip"]
        assert s.attributes["clean"] == "no PII here"

    def test_pii_redaction_in_events(self):
        redactor = PIIRedactor()
        t = InMemoryTracer(redactor=redactor)
        s = t.start_span("test")
        s.add_event("user_query", {"text": "Contact me at a@b.com"})
        t.end_span(s)
        assert "a@b.com" not in s.events[0].attributes["text"]


class TestSpanMethods:
    def test_set_attribute(self):
        t = NoOpTracer()
        s = t.start_span("test")
        s.set_attribute("k", "v")
        assert s.attributes["k"] == "v"

    def test_set_attributes_batch(self):
        t = NoOpTracer()
        s = t.start_span("test")
        s.set_attributes({"a": 1, "b": 2})
        assert s.attributes == {"a": 1, "b": 2}

    def test_add_event(self):
        t = NoOpTracer()
        s = t.start_span("test")
        s.add_event("important_step", {"detail": "X"})
        assert len(s.events) == 1
        assert s.events[0].name == "important_step"

    def test_set_status(self):
        t = NoOpTracer()
        s = t.start_span("test")
        s.set_status(SpanStatus.ERROR, "boom")
        assert s.status == SpanStatus.ERROR
        assert s.status_message == "boom"

    def test_record_exception(self):
        t = NoOpTracer()
        s = t.start_span("test")
        try:
            raise ValueError("test error")
        except ValueError as e:
            s.record_exception(e)
        assert s.status == SpanStatus.ERROR
        assert s.events[-1].name == "exception"
        assert s.events[-1].attributes["exception.type"] == "ValueError"

    def test_duration_ms_none_before_end(self):
        t = NoOpTracer()
        s = t.start_span("test")
        assert s.duration_ms() is None

    def test_duration_ms_set_after_end(self):
        import time
        t = NoOpTracer()
        s = t.start_span("test")
        time.sleep(0.01)
        t.end_span(s)
        assert s.duration_ms() is not None
        assert s.duration_ms() > 0


class TestSpanContext:
    def test_context_manager_basic(self):
        t = InMemoryTracer()
        with SpanContext(t, "test") as span:
            span.set_attribute("k", "v")
        assert len(t.spans) == 1
        assert t.spans[0].status == SpanStatus.OK
        assert t.spans[0].attributes["k"] == "v"

    def test_context_manager_on_exception(self):
        t = InMemoryTracer()
        with pytest.raises(ValueError):
            with SpanContext(t, "test") as span:
                raise ValueError("boom")
        # Span end + status=ERROR
        assert t.spans[0].status == SpanStatus.ERROR
        assert any(e.name == "exception" for e in t.spans[0].events)

    def test_nested_spans(self):
        t = InMemoryTracer()
        with SpanContext(t, "parent") as parent:
            with SpanContext(t, "child", parent_span=parent) as child:
                child.set_attribute("level", 1)
        assert len(t.spans) == 2
        child_span = next(s for s in t.spans if s.name == "child")
        parent_span = next(s for s in t.spans if s.name == "parent")
        assert child_span.parent_id == parent_span.span_id


class TestSingleton:
    def test_default_is_noop(self):
        d = get_default_tracer()
        assert isinstance(d, NoOpTracer)

    def test_set_default(self):
        t = InMemoryTracer()
        set_default_tracer(t)
        assert get_default_tracer() is t


# ════════════════════════════════════════════════════════════════════════════
# METRICS (S6.3)
# ════════════════════════════════════════════════════════════════════════════


class TestCounter:
    def test_inc_basic(self):
        c = Counter("test_counter")
        c.inc()
        c.inc(2.5)
        assert c.get() == 3.5

    def test_inc_with_labels(self):
        c = Counter("test", label_keys=["tenant"])
        c.inc(labels={"tenant": "a"})
        c.inc(labels={"tenant": "a"})
        c.inc(labels={"tenant": "b"})
        assert c.get(labels={"tenant": "a"}) == 2
        assert c.get(labels={"tenant": "b"}) == 1

    def test_negative_inc_rejected(self):
        c = Counter("test")
        with pytest.raises(ValueError):
            c.inc(-1.0)


class TestGauge:
    def test_set(self):
        g = Gauge("queue_depth")
        g.set(42)
        assert g.get() == 42

    def test_inc_dec(self):
        g = Gauge("active_jobs")
        g.inc(3)
        g.dec(1)
        assert g.get() == 2

    def test_negative_via_dec(self):
        g = Gauge("net")
        g.dec(5)  # autorisé pour Gauge
        assert g.get() == -5


class TestHistogram:
    def test_observe_count_sum(self):
        h = Histogram("latency", buckets=(1.0, 5.0, 10.0))
        h.observe(0.5)
        h.observe(2.0)
        h.observe(7.5)
        d = h.get_data()
        assert d.count == 3
        assert d.sum == 10.0
        # Bucket 1.0 : seul 0.5 → count=1
        assert d.buckets[1.0] == 1
        # Bucket 5.0 : 0.5 + 2.0 → count=2
        assert d.buckets[5.0] == 2
        # Bucket 10.0 : all 3
        assert d.buckets[10.0] == 3

    def test_percentile_approx(self):
        h = Histogram("latency", buckets=(1.0, 5.0, 10.0, 50.0))
        # Distribution skewed : many small values
        for _ in range(80):
            h.observe(0.5)
        for _ in range(15):
            h.observe(3.0)
        for _ in range(5):
            h.observe(20.0)
        # p50 should be in bucket 1.0
        assert h.percentile(0.50) == 1.0
        # p95 should be in bucket 5.0 (80+15=95) or higher
        p95 = h.percentile(0.95)
        assert p95 in (5.0, 10.0)

    def test_average(self):
        h = Histogram("test")
        h.observe(2.0)
        h.observe(4.0)
        assert h.average() == 3.0

    def test_with_labels(self):
        h = Histogram("latency", label_keys=["shape"])
        h.observe(1.0, labels={"shape": "factual"})
        h.observe(5.0, labels={"shape": "multi_hop"})
        assert h.get_data(labels={"shape": "factual"}).count == 1
        assert h.get_data(labels={"shape": "multi_hop"}).count == 1
        assert h.get_data(labels={"shape": "factual"}).sum == 1.0


class TestMetricsRegistry:
    def test_counter_singleton_per_name(self):
        reg = MetricsRegistry()
        c1 = reg.counter("tool_calls")
        c2 = reg.counter("tool_calls")
        assert c1 is c2

    def test_prefix_applied(self):
        reg = MetricsRegistry(name_prefix="myapp_")
        c = reg.counter("foo")
        assert c.name == "myapp_foo"

    def test_snapshot_structure(self):
        reg = MetricsRegistry()
        c = reg.counter("calls")
        c.inc(2)
        g = reg.gauge("active")
        g.set(5)
        h = reg.histogram("latency")
        h.observe(1.5)
        snap = reg.snapshot()
        assert "counters" in snap
        assert "gauges" in snap
        assert "histograms" in snap
        assert any("calls" in name for name in snap["counters"])


# ════════════════════════════════════════════════════════════════════════════
# SAMPLING (S6.4)
# ════════════════════════════════════════════════════════════════════════════


class TestSamplingPolicy:
    def test_error_always_captured(self):
        policy = SamplingPolicy()
        d = policy.decide(
            request_id="req_x", has_error=True, n_iterations=1,
        )
        assert d.tier1_recorded is True
        assert d.tier2_trace_captured is True
        assert d.reason == "error"

    def test_high_iter_captured(self):
        policy = SamplingPolicy(threshold_high_iter=5)
        d = policy.decide(
            request_id="req_x", has_error=False, n_iterations=7,
        )
        assert d.tier2_trace_captured is True
        assert "high_iter" in d.reason

    def test_low_iter_success_sampled(self):
        """Sur 10000 runs success+low_iter, ~10% sont sampled (rate=0.10)."""
        policy = SamplingPolicy(success_sample_rate=0.10, threshold_high_iter=5)
        captured = 0
        n_total = 1000
        for i in range(n_total):
            d = policy.decide(
                request_id=f"req_{i}", has_error=False, n_iterations=2,
            )
            if d.tier2_trace_captured:
                captured += 1
        # Doit être proche de 10% (intervalle large pour stochastique)
        assert 50 <= captured <= 150, f"expected ~100, got {captured}"

    def test_sampling_deterministic(self):
        """Même request_id → même décision (deterministic hash)."""
        policy = SamplingPolicy(success_sample_rate=0.10)
        d1 = policy.decide("req_x", has_error=False, n_iterations=2)
        d2 = policy.decide("req_x", has_error=False, n_iterations=2)
        assert d1.tier2_trace_captured == d2.tier2_trace_captured

    def test_tier3_requires_opt_in(self):
        policy = SamplingPolicy()
        # No opt-in
        d = policy.decide(
            "req_x", has_error=True, n_iterations=1,
            tenant_opt_in_full_content=False,
        )
        assert d.tier3_full_content_captured is False
        # With opt-in AND tier2 captured
        d = policy.decide(
            "req_y", has_error=True, n_iterations=1,
            tenant_opt_in_full_content=True,
        )
        assert d.tier3_full_content_captured is True

    def test_tier3_requires_tier2(self):
        """Si tier2 pas captured, tier3 pas captured non plus."""
        policy = SamplingPolicy(success_sample_rate=0.0, threshold_high_iter=100)
        d = policy.decide(
            "req_z", has_error=False, n_iterations=1,
            tenant_opt_in_full_content=True,
        )
        # tier2 not captured (rate=0%) → tier3 pas captured
        assert d.tier2_trace_captured is False
        assert d.tier3_full_content_captured is False

    def test_invalid_rate_rejected(self):
        with pytest.raises(ValueError):
            SamplingPolicy(success_sample_rate=1.5)
        with pytest.raises(ValueError):
            SamplingPolicy(success_sample_rate=-0.1)
