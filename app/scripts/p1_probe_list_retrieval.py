"""Probe diagnostique (read-only) : pourquoi les sous-buts list_enumeration abstiennent.

Rejoue le pipeline runtime_v6 sur les questions factual-liste abstenues au bench,
et dumpe pour chaque itération :
  - sous-buts (kind / subject_canonical / predicate_hint)
  - résolution du sujet (resolved / method / abstain_reason)
  - tool appelé + nb claims ramenés + échantillon de textes
  - verdict Evaluate + couvert/non-couvert

Objectif : confirmer si le tool kg_claims_list (exact-match subject_canonical, SANS
hybrid retrieval) est le point de rupture pour les réponses multi-items.

Read-only : aucune écriture KG. Quelques appels LLM (Parse/Evaluate/Synthesize).
"""
from __future__ import annotations

import os
import sys

from knowbase.runtime_a3.execute import Executor
from knowbase.runtime_a3.orchestrator import Orchestrator

QUESTIONS = [
    "Quels codes statut existent pour les print requests WWI dans EHS ?",
    "Quels outils SAP utilise-t-il pour le support client dans RISE with SAP ?",
    "Quels objets d'autorisation sont necessaires pour le scenario E-Recruiting Manager ?",
]


def _short(s, n=85):
    s = (s or "").replace("\n", " ")
    return s[:n]


def main() -> None:
    print(f"[ENV] V6_HYBRID_RETRIEVAL={os.getenv('V6_HYBRID_RETRIEVAL')} "
          f"V6_PARSE_LLM_DEEPSEEK={os.getenv('V6_PARSE_LLM_DEEPSEEK')}")
    for q in QUESTIONS:
        print("\n" + "=" * 100)
        print(f"Q: {q}")
        executor = Executor()  # injecté pour inspecter _last_resolutions
        orch = Orchestrator(executor=executor)
        res = orch.run(q, tenant_id="default")
        print(f"terminated_reason={res.terminated_reason} n_iter={len(res.iterations)} "
              f"answer_mode={res.synthesize_output.mode} "
              f"n_cited={len(res.synthesize_output.cited_claims)}")
        for it in res.iterations:
            po = it.parse_output
            print(f"\n  --- iter {it.iteration} | verdict={it.evaluate_output.verdict} "
                  f"| covered={it.evaluate_output.covered_sub_goals} "
                  f"uncovered={it.evaluate_output.uncovered_sub_goals}")
            for i, sg in enumerate(po.sub_goals):
                print(f"    sub_goal[{i}] kind={sg.kind} "
                      f"subject={sg.subject_canonical!r} predicate={sg.predicate_hint!r} "
                      f"object_hint={sg.object_hint!r}")
            for tc in it.plan_output.tool_calls:
                print(f"    toolcall sg={tc.sub_goal_idx} tool={tc.tool} "
                      f"params_subject={tc.params.get('subject') or tc.params.get('subject_filter')!r} "
                      f"params_pred={tc.params.get('predicate')!r}")
            for tr in it.execute_output.results:
                texts = []
                for c in tr.claims[:4]:
                    d = c.model_dump()
                    texts.append(_short(d.get("text") or d.get("value") or ""))
                print(f"    result sg={tr.sub_goal_idx} tool={tr.tool} "
                      f"n_claims={len(tr.claims)} coverage={tr.coverage_signal} "
                      f"err={tr.error}")
                for t in texts:
                    print(f"        · {t}")
        # Résolutions de sujet observées
        print("  [subject_resolutions]")
        for idx, rr in (executor._last_resolutions or {}).items():
            print(f"    sg={idx} resolved={rr.resolved!r} conf={rr.confidence:.2f} "
                  f"method={rr.method} abstain={rr.abstain_reason}")
            for cand in rr.candidates[:4]:
                print(f"        cand: name={cand.entity_name!r} subj={cand.subject_canonical!r} "
                      f"score={cand.score:.2f} src={cand.source} n_claims={cand.n_supporting_claims}")


if __name__ == "__main__":
    main()
