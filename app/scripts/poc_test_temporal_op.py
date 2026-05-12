"""Test rapide TemporalActiveVersionOperator sur 5 questions."""
import os
from neo4j import GraphDatabase
from knowbase.runtime_v4_poc.operators import TemporalActiveVersionOperator

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")),
)
op = TemporalActiveVersionOperator(neo4j_driver=driver)

CASES = [
    ("TEMP_active_today",
     "Si une question est posée aujourd'hui sur les exigences CS 25.795, quelle version d'amdt faut-il citer ?"),
    ("TEMP_explicit_date",
     "Quelle était la version de CS-25 applicable en juin 2020 ?"),
    ("TEMP_at_publication",
     "Quel amendment CS-25 s'appliquait au moment de la publication du 2021/821 (juin 2021) ?"),
    ("TEMP_audit_2022",
     "Pour un audit retrospectif sur une transaction de septembre 2022, quelle Annex I est applicable ?"),
    ("NOT_TEMPORAL_factual",  # contrôle : doit retourner NOT_APPLICABLE
     "Quelle est la capitale de la France ?"),
]

for label, q in CASES:
    print(f"\n=== [{label}] ===")
    print(f"Q: {q[:140]}")
    r = op.execute(q)
    print(f"  triggered={r.triggered} decision={r.decision}")
    print(f"  intent: {r.intent}")
    if r.triggered:
        print(f"  query_date={r.query_date}")
        print(f"  cypher_hits={r.cypher_n_hits}")
        print(f"  latency_ms: {r.latency_breakdown_ms}")
        if r.active_doc_id:
            print(f"  active: {r.active_doc_id} ({r.active_publication_date})")
        if r.answer:
            print(f"  answer: {r.answer[:300]}")
        if r.abstention_reason:
            print(f"  abstention_reason: {r.abstention_reason}")

driver.close()
