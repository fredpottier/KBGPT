"""
contradiction_adjudicator.py — Adjudication EN CONTEXTE des paires CONTRADICTS (#446).

Déclencheur (filage démo 06/06, Fred) : le bandeau « Divergence entre autorités »
a affiché une fausse contradiction PERSUASIVE — deux clauses vraies répondant à
des questions différentes (« quelle preuve compte pour la démonstration ? » vs
« à quels contacts la limite s'applique-t-elle ? »), appariées car similaires et
d'apparence opposée. Un lecteur attentif en a tiré une conclusion opérationnelle
fausse. Vérification manuelle des passages : les DEUX documents contiennent les
DEUX règles. Deuxième famille de FP après l'équivalence d'unités (value_equivalence).

Principe : la similarité ne peut pas juger une contradiction — seule la lecture
EN CONTEXTE le peut. Pour chaque arête CONTRADICTS, un juge LLM reçoit les deux
claims AVEC LEURS PASSAGES SOURCES COMPLETS (claim.passage_text, doc, page) et
classe la paire :

  - CONFIRMED        : dans leurs contextes, réponses INCOMPATIBLES à la MÊME
                       question (mêmes conditions/portée) → vraie contradiction.
  - DIFFERENT_SCOPE  : les clauses s'appliquent à des conditions, cas d'essai,
                       objets ou questions DIFFÉRENTS → pas une contradiction.
  - COMPLEMENTARY    : compatibles — facettes du même cadre (règle + exception,
                       définition + application, les deux docs disent les deux).
  - EQUIVALENT       : même contenu (reformulation / conversion d'unités) —
                       pré-trié déterministiquement via value_equivalence.
  - UNCLEAR          : indécidable depuis les passages fournis.

Le verdict est posé SUR L'ARÊTE (r.adjudication, r.adjudication_reason,
r.adjudicated_at, r.adjudication_model) — réversible, n'efface rien. Le runtime
peut ensuite ne présenter en « divergence » que les arêtes confirmées (toggle).

TRAÇABILITÉ (exigence Fred) : chaque paire évaluée est journalisée dans un
rapport JSON complet (claims, passages, verdict, raison) pour relecture humaine
et mesure de précision sur les cas connus.

Domain-agnostic strict : aucun token corpus ; le prompt parle de « statements »,
« source passages », « documents ».
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VERDICTS = ("CONFIRMED", "DIFFERENT_SCOPE", "COMPLEMENTARY", "EQUIVALENT", "UNCLEAR")

_SYSTEM_PROMPT = """You are an adjudicator of POTENTIAL contradictions in a knowledge base.
You receive two statements extracted from documents, EACH WITH ITS FULL SOURCE PASSAGE.
An automatic detector flagged them as contradictory because they look similar and opposed —
but detectors compare sentences out of context and are often wrong.

Your job: decide, FROM THE PASSAGES, whether the two statements give INCOMPATIBLE answers
to the SAME question under the SAME conditions.

Classify as exactly ONE of:
- CONFIRMED: in their contexts, the statements answer the SAME question for the SAME
  scope/conditions with INCOMPATIBLE content. A reader following one would violate the other.
- DIFFERENT_SCOPE: the statements apply to DIFFERENT conditions, test cases, object types,
  configurations, or answer DIFFERENT questions (e.g. one defines what evidence is valid,
  the other defines where a limit applies). Not a contradiction.
- COMPLEMENTARY: the statements are compatible parts of the same framework (rule + exception,
  general principle + specific procedure), possibly both present in each document's context.
- EQUIVALENT: the statements say the same thing (paraphrase, unit conversion, rounding).
- UNCLEAR: the passages do not allow a confident decision.

Critical checks before answering CONFIRMED:
1. Do the surrounding passages show that each document ALSO contains the other statement's
   rule? (If yes → COMPLEMENTARY.)
2. Do the statements share the same applicability conditions (same test case, same object,
   same configuration, same timeframe)? (If no → DIFFERENT_SCOPE.)
3. Would an expert following document A actually DO something different than following
   document B in the same situation? (If no → not CONFIRMED.)

Return STRICT JSON: {"verdict": "<one of the five>", "reason": "<2-3 sentences, specific>"}"""


def _build_user_prompt(pair: Dict[str, Any], max_passage: int = 2200) -> str:
    def _block(side: str) -> str:
        return (
            f"STATEMENT {side} (document: {pair[f'doc_{side.lower()}']}, "
            f"page {pair.get(f'page_{side.lower()}')}):\n"
            f"\"{pair[f'text_{side.lower()}']}\"\n\n"
            f"FULL SOURCE PASSAGE {side}:\n"
            f"{(pair.get(f'passage_{side.lower()}') or '(passage unavailable)')[:max_passage]}\n"
        )
    return _block("A") + "\n" + _block("B") + "\nJSON:"


@dataclass
class AdjudicationRecord:
    """Trace complète d'une paire évaluée (rapport JSON)."""
    a_id: str
    b_id: str
    doc_a: str
    doc_b: str
    page_a: Optional[int]
    page_b: Optional[int]
    text_a: str
    text_b: str
    verdict: str
    reason: str
    method: str  # 'deterministic_equivalence' | 'llm' | 'error_fallback'
    duration_s: float = 0.0


@dataclass
class AdjudicationSummary:
    n_total: int = 0
    n_skipped_already: int = 0
    by_verdict: Dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    model: str = ""
    report_path: str = ""


_FETCH_CYPHER = """
MATCH (a:Claim {tenant_id: $tenant_id})-[r:CONTRADICTS]->(b:Claim {tenant_id: $tenant_id})
WHERE $force OR r.adjudication IS NULL
RETURN a.claim_id AS a_id, a.text AS text_a, a.passage_text AS passage_a,
       a.doc_id AS doc_a, a.page_no AS page_a,
       b.claim_id AS b_id, b.text AS text_b, b.passage_text AS passage_b,
       b.doc_id AS doc_b, b.page_no AS page_b
"""

_WRITE_CYPHER = """
MATCH (a:Claim {tenant_id: $tenant_id, claim_id: $a_id})
      -[r:CONTRADICTS]->
      (b:Claim {tenant_id: $tenant_id, claim_id: $b_id})
SET r.adjudication = $verdict,
    r.adjudication_reason = $reason,
    r.adjudicated_at = datetime(),
    r.adjudication_model = $model
"""


def _parse_verdict(raw: str) -> Optional[Dict[str, str]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    verdict = str(data.get("verdict", "")).upper().strip()
    if verdict not in VERDICTS:
        return None
    return {"verdict": verdict, "reason": str(data.get("reason", ""))[:600]}


class ContradictionAdjudicator:
    """Adjudique les arêtes CONTRADICTS d'un tenant, en contexte (passages).

    `llm_call(system, user) -> str` injectable (tests). Par défaut : llm_router
    temperature=0 (déterminisme au mieux des capacités provider).
    """

    def __init__(self, llm_call=None, model_label: str = ""):
        self._llm_call = llm_call
        self._model_label = model_label or "router/knowledge_extraction"

    def _get_llm(self):
        if self._llm_call is None:
            from knowbase.common.llm_router import get_llm_router, TaskType
            router = get_llm_router()

            def _call(system: str, user: str) -> str:
                # LONG_TEXT_SUMMARY (DeepSeek) : fiable sur les prompts longs à
                # 2 passages — KNOWLEDGE_EXTRACTION (Qwen3-235B) dégénérait en
                # répétition (« The The The… ») sur ce prompt (smoke 06/06).
                return router.complete(
                    task_type=TaskType.LONG_TEXT_SUMMARY,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.0,
                    max_tokens=400,
                )
            self._llm_call = _call
        return self._llm_call

    def adjudicate_pair(self, pair: Dict[str, Any]) -> AdjudicationRecord:
        t0 = time.perf_counter()
        base = dict(
            a_id=pair["a_id"], b_id=pair["b_id"],
            doc_a=pair.get("doc_a") or "", doc_b=pair.get("doc_b") or "",
            page_a=pair.get("page_a"), page_b=pair.get("page_b"),
            text_a=(pair.get("text_a") or "")[:400],
            text_b=(pair.get("text_b") or "")[:400],
        )
        # Pré-passe DÉTERMINISTE : équivalence d'unités/valeurs (gratuite, sûre)
        try:
            from knowbase.relations.value_equivalence import quantities_equivalent
            if quantities_equivalent(pair.get("text_a") or "", pair.get("text_b") or ""):
                return AdjudicationRecord(
                    **base, verdict="EQUIVALENT",
                    reason="Mêmes valeurs numériques (conversion d'unités/arrondi) — value_equivalence.",
                    method="deterministic_equivalence",
                    duration_s=time.perf_counter() - t0,
                )
        except Exception:
            pass
        # Juge LLM en contexte (1 retry sur sortie inparsable — dégénérescence
        # provider observée au smoke)
        try:
            parsed = None
            last_raw = ""
            for _attempt in range(2):
                last_raw = self._get_llm()(_SYSTEM_PROMPT, _build_user_prompt(pair))
                parsed = _parse_verdict(last_raw)
                if parsed is not None:
                    break
            if parsed is None:
                raise ValueError(f"unparseable verdict: {last_raw[:120]!r}")
            return AdjudicationRecord(
                **base, verdict=parsed["verdict"], reason=parsed["reason"],
                method="llm", duration_s=time.perf_counter() - t0,
            )
        except Exception as exc:  # fail-safe : UNCLEAR, jamais de crash de pipeline
            logger.warning("adjudication failed for %s↔%s: %s",
                           pair["a_id"], pair["b_id"], exc)
            return AdjudicationRecord(
                **base, verdict="UNCLEAR",
                reason=f"adjudication error: {str(exc)[:150]}",
                method="error_fallback", duration_s=time.perf_counter() - t0,
            )

    def run(
        self,
        tenant_id: str = "default",
        force: bool = False,
        limit: Optional[int] = None,
        report_path: Optional[str] = None,
        max_workers: int = 4,
        confirm_double_check: bool = True,
    ) -> AdjudicationSummary:
        from concurrent.futures import ThreadPoolExecutor
        from knowbase.common.clients.neo4j_client import get_neo4j_client

        driver = get_neo4j_client().driver
        t0 = time.perf_counter()
        with driver.session() as s:
            pairs = [dict(r) for r in s.run(_FETCH_CYPHER, tenant_id=tenant_id, force=force)]
        n_already = 0
        if not force:
            # _FETCH_CYPHER exclut déjà les adjugées ; compter pour la trace
            with driver.session() as s:
                n_already = s.run(
                    "MATCH (:Claim {tenant_id:$t})-[r:CONTRADICTS]->(:Claim {tenant_id:$t}) "
                    "WHERE r.adjudication IS NOT NULL RETURN count(r) AS n",
                    t=tenant_id,
                ).single()["n"]
        if limit:
            pairs = pairs[:limit]
        logger.info("[ADJUDICATION] %d paires à évaluer (déjà faites: %d, force=%s)",
                    len(pairs), n_already, force)

        records: List[AdjudicationRecord] = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for i, rec in enumerate(ex.map(self.adjudicate_pair, pairs), 1):
                records.append(rec)
                if i % 20 == 0 or i == len(pairs):
                    logger.info("[ADJUDICATION] %d/%d (%s)", i, len(pairs), rec.verdict)

        # DOUBLE-CHECK des CONFIRMED (éval qualité 06/06) : CONFIRMED est le
        # verdict à enjeu (il porte le bandeau divergence) ET le plus exposé à
        # l'inconstance provider (constaté : 2 paires jumelles de 0.09/0.08
        # jugées différemment). On re-juge chaque CONFIRMED une 2e fois ; il ne
        # reste CONFIRMED que s'il l'est 2/2, sinon il prend le verdict du
        # 2e passage (method='llm_doublecheck_demoted'). Coût : n_confirmed appels.
        if confirm_double_check:
            pair_by_key = {(p["a_id"], p["b_id"]): p for p in pairs}
            for idx, rec in enumerate(records):
                if rec.verdict != "CONFIRMED" or rec.method != "llm":
                    continue
                pair = pair_by_key.get((rec.a_id, rec.b_id))
                if pair is None:
                    continue
                second = self.adjudicate_pair(pair)
                if second.verdict != "CONFIRMED":
                    logger.info(
                        "[ADJUDICATION] double-check démote %s↔%s : CONFIRMED → %s",
                        rec.a_id, rec.b_id, second.verdict,
                    )
                    second.method = "llm_doublecheck_demoted"
                    records[idx] = second

        # Écriture des verdicts sur les arêtes
        with driver.session() as s:
            for rec in records:
                s.run(_WRITE_CYPHER, tenant_id=tenant_id, a_id=rec.a_id,
                      b_id=rec.b_id, verdict=rec.verdict, reason=rec.reason,
                      model=self._model_label if rec.method == "llm" else rec.method)

        # Rapport JSON complet (traçabilité / relecture humaine / précision)
        summary = AdjudicationSummary(
            n_total=len(records),
            n_skipped_already=n_already,
            duration_s=time.perf_counter() - t0,
            model=self._model_label,
        )
        for rec in records:
            summary.by_verdict[rec.verdict] = summary.by_verdict.get(rec.verdict, 0) + 1
        if report_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            report_path = f"/data/staging_new_docs/contradiction_adjudication_{ts}.json"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "tenant_id": tenant_id,
                    "summary": asdict(summary),
                    "records": [asdict(r) for r in records],
                }, f, ensure_ascii=False, indent=1)
            summary.report_path = report_path
            logger.info("[ADJUDICATION] rapport → %s", report_path)
        except Exception:
            logger.exception("[ADJUDICATION] écriture rapport échouée (verdicts en base OK)")
        logger.info("[ADJUDICATION] terminé en %.0fs — %s",
                    summary.duration_s, summary.by_verdict)
        return summary
