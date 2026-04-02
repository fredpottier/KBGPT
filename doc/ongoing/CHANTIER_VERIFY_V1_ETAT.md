# Chantier Verify V1 — Etat au 2 avril 2026

## Ce qui est en place

### Backend (fonctionnel)
- `docx_processor.py` : extraction paragraphes, annotation Word, metriques (V3-ready)
- `POST /api/verify/upload-docx` : upload .docx → analyse → retourne .docx annote
- Structures de donnees V3 : AssertionVerdict, CorpusPosition, DocumentReviewResult
- `python-docx >= 1.2.0` installe (commentaires natifs Word)

### Frontend (fonctionnel)
- Page `/verify` avec deux modes : Texte et Document Word
- Drag & drop upload
- Download du document annote
- Proxy Next.js pour eviter CORS

## Ce qui ne fonctionne PAS

### Le moteur de verification (evidence_matcher) est defaillant

**Problemes constates** :
1. La recherche vectorielle trouve des claims vaguement lies au domaine, pas a l'assertion specifique
2. Le LLM de comparaison (Ollama Qwen 9B ou GPT-4o-mini) recoit des claims non pertinents et produit des verdicts absurdes
3. Exemples concrets :
   - "cout de licence 250K" → verdict "nuance" avec evidence "monthly budget billing" (hors sujet)
   - "Oracle Database" → verdict "nuance" au lieu de "contredit" avec evidence vague
   - 13/15 assertions classees "confirmed" alors que 6 contiennent des erreurs volontaires

### Cause racine

Le pipeline `assertion_splitter → evidence_matcher → comparison_engine` a ete ecrit en fevrier 2026 pour un corpus et un KG differents. Il utilise :
- Une recherche vectorielle dans Neo4j claims (pas dans Qdrant qui a de meilleurs chunks)
- Un prompt de comparaison generique (COMPARE_CLAIM_PROMPT) qui ne tire pas parti de C4/C6
- Le llm_router qui fallback sur Ollama au lieu de GPT-4o-mini

Ce pipeline est INDEPENDANT du pipeline search/synthesis qui, lui, fonctionne bien (faithfulness 79%, tension 100%, etc.).

## Plan de reprise

### Option recommandee : reutiliser le pipeline search au lieu de evidence_matcher

Le pipeline `search.py` + `synthesis.py` est optimise depuis 2 jours :
- Hybrid BM25 + dense retrieval
- KG procedural (findings, COMPLEMENTS, tensions)
- ContradictionEnvelope
- GPT-4o-mini via provider configure

**Idee** : Pour chaque assertion extraite, faire un appel au pipeline search existant (comme si c'etait une question) puis comparer la reponse avec l'assertion.

```
assertion → search(assertion_text) → synthese → comparer assertion vs synthese
```

Avantages :
- Reutilise tout ce qu'on a optimise (retrieval, KG, prompt)
- Pas besoin de refaire un evidence_matcher
- Qualite equivalent au chat (qui fonctionne bien)

Inconvenients :
- Plus lent (1 appel search complet par assertion, ~10s)
- Plus couteux (1 appel GPT-4o-mini par assertion)

### Effort estime
- Refactorer le verification_service pour utiliser search au lieu de evidence_matcher : 1 jour
- Tester et calibrer : 0.5 jour

## A ne PAS refaire
- Patcher l'evidence_matcher avec des fix incrementaux
- Changer juste le LLM (le probleme est la qualite des claims trouves, pas le LLM)
