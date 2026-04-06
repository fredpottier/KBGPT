# Protocole Benchmark — OSMOSIS vs RAG Baselines

**Date** : 2026-03-22
**Statut** : Protocole valide (post Debate Gate)
**Methode** : Double Diamond multi-AI (Claude + Codex)

---

## 1. Objectif

Produire un document quasi-academique avec metriques tangibles prouvant (ou infirmant) la valeur differenciante d'OSMOSIS par rapport a des baselines RAG standard.

## 2. Corpus de test

Premier corpus : SAP Enterprise Documentation (28 documents, ~15 861 claims)
Architecture corpus-agnostic : rejouable sur biomedical, reglementaire, ou tout autre backup.

## 3. Questions (200 par tache)

### 3.1 Questions KG-derived (100/tache)
Generees automatiquement depuis Neo4j :
- T1 Provenance : question generee depuis un claim existant avec verbatim connu
- T2 Contradictions : question sur un sujet ou des relations CONTRADICTS existent
- T3 Temporal : question sur une entite avec plusieurs axis_release_id
- T4 Audit : requete d'export sur une entite avec claims/relations connues

### 3.2 Questions externes (100/tache)
Generees par Claude directement depuis les documents sources (cache .v4cache.json)
SANS consulter le KG — simulent un utilisateur reel.

## 4. Systemes compares

| Systeme | Description |
|---|---|
| **OSMOSIS** | Pipeline complet (KG + Qdrant + Neo4j traversal + contradictions + applicability) |
| **RAG-claim** | Meme Qdrant, meme embeddings, meme LLM. PAS de Neo4j. |
| **RAG-hybrid** | BM25 + vector search, meme corpus. PAS de Neo4j. |
| **ChatGPT+context** | Memes questions, meme contexte retrieval injecte. Evaluation manuelle. |

## 5. Metriques primaires (pre-enregistrees)

| # | Metrique | Tache | Source |
|---|---|---|---|
| P1 | Citation Recall (ALCE) | T1 | ALCE benchmark |
| P2 | Contradiction Detection F1 | T2 | Custom |
| P3 | Version-Mixing Detection F1 | T3 | Custom |
| P4 | Export Completeness | T4 | Custom |
| P5 | Faithfulness (RAGAS) | Cross | RAGAS framework |

## 6. Metriques secondaires (67)

Voir la liste complete des 72 metriques dans la section Discover.
Les 67 metriques secondaires sont rapportees mais ne font pas partie des conclusions principales.

## 7. Parametres fixes

- Embedding : intfloat/multilingual-e5-large
- LLM synthese : GPT-4o, temperature 0
- LLM evaluation : GPT-4o, temperature 0
- top_k retrieval : 10
- Score threshold : 0.5
- Max context tokens : 8000
- Seed : 42

## 8. Ground truth

### 8.1 Questions KG-derived
Le ground truth EST le KG :
- T1 : claim_id + verbatim_quote + doc_id + page_no
- T2 : paire de claims + tension_nature + tension_level
- T3 : axis_release_id par claim + temporal ordering
- T4 : liste complete claims/entites/contradictions/facettes pour l'entite

### 8.2 Questions externes
Le ground truth est construit par Claude depuis les documents :
- T1 : passage exact du document + page
- T2 : paire de passages contradictoires identifies par Claude
- T3 : passages avec dates/versions differentes
- T4 : checklist de completude attendue

## 9. RAG baseline — specification technique

### Ce qui est IDENTIQUE
- Meme collection Qdrant (knowbase_chunks_v2)
- Meme modele d'embedding (multilingual-e5-large)
- Meme LLM de synthese (GPT-4o)
- Memes questions et ground truth
- Meme format de reponse
- Meme budget de tokens contexte

### Ce qui est RETIRE
- Pas de Neo4j traversal
- Pas de relations CONTRADICTS
- Pas d'enrichissement entites
- Pas d'ApplicabilityFrame
- Pas de citations claim-level (seulement chunk-level)
- Pas d'insight hints

## 10. Protocole d'evaluation

### Automatique (metriques computables)
- ALCE citation P/R/F1
- RAGAS faithfulness, context recall, answer relevancy
- Latence, tokens, cout
- Export completeness (schema validation)

### LLM-as-judge (metriques necessitant jugement)
- BenchmarkQED assertion scores
- VeriTrail verdict class
- Contradiction typing accuracy
- Version attribution accuracy

### Humaine (evaluation manuelle blind)
- 2 annotateurs, blind (systemes anonymises)
- Cohen's Kappa inter-annotateur
- McNemar test pour significance statistique
- 95% confidence intervals

## 11. Structure des fichiers

```
benchmark/
  config.yaml
  questions/
    task1_provenance_kg.json
    task1_provenance_external.json
    task2_contradictions_kg.json
    task2_contradictions_external.json
    task3_temporal_kg.json
    task3_temporal_external.json
    task4_audit_kg.json
    task4_audit_external.json
  ground_truth/
    (meme structure, genere depuis KG et documents)
  baselines/
    rag_claim_baseline.py
    rag_hybrid_baseline.py
    chatgpt_baseline.py
  runners/
    run_osmosis.py
    run_rag.py
    run_chatgpt.py
  evaluators/
    provenance_eval.py
    contradiction_eval.py
    temporal_eval.py
    audit_eval.py
    cross_cutting_eval.py
  analysis/
    compare.py
    significance_tests.py
    generate_report.py
  results/
    (outputs par run)
```

## 12. Reproductibilite

Pour qu'un tiers puisse reproduire :
- Snapshot Neo4j (export JSON)
- Snapshot Qdrant (snapshot natif)
- Tous les prompts (system + user) version-controlles
- Code complet (Python, open-source)
- Seeds fixes pour generation de questions
- Versions exactes des modeles (GPT-4o date, embedding version)
- Config.yaml complete

## 13. Limites connues (pre-declarees)

1. Self-referencing partiel : 50% des questions viennent du KG
2. Pas de baseline GraphRAG (cout de construction trop eleve pour MVP)
3. 200 questions/tache donne un CI de ±7% (pas ±5% ideal)
4. Evaluation humaine limitee a un sous-ensemble (contrainte temps)
5. Corpus SAP = documentation technique enterprise (pas representatif de tous les domaines)
