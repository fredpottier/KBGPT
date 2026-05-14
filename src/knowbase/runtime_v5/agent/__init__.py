"""V5 ReasoningAgent V5.1 — composants industrialisés (S4).

Modules :
- loop_signature : anti-thrash robuste (novelty_score)
- budgets : 4 budgets indépendants (iter, tool_calls, chars, tokens)
- execution_plan : Pydantic schema plan-then-execute
- cancellation : token cancellation async-aware
- workspace : Pydantic schema V1 versionné, replay-able
"""
