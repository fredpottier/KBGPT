# Bilan Session 30 mars 2026

## Rationalization documentation

- 232 fichiers archives dans `doc/archive/pre-rationalization-2026-03/`
- 15 documents reconstruits + matrice de tracabilite
- 10 corrections ChatGPT appliquees (Graph-First vs RAG, taxonomie tensions, pivots, etc.)
- Badges "niveau de fiabilite" sur chaque document

## Phase 1 — Retrieval

### Chunking ✅
- 23 docs uniques dans Qdrant (7629 chunks, median 957 chars)
- 3 doublons identifies et documentes (009=010, 016=017, 026=027)
- 028 ingere avec succes (2933 TypeAwareChunks)
- 029/030 : bug non resolu — process meurt silencieusement apres Docling "Finished Converting"

### Hybrid BM25+dense ⚠️
- Code ecrit et deploye (`retriever.py`)
- Text index Qdrant cree
- **MAIS** : l'implementation actuelle fait un dense + filtre text, PAS une vraie fusion RRF
- Le 2e prefetch utilise le meme vecteur dense avec un filtre text en plus → sous-ensemble du dense, pas des resultats BM25 independants
- **A refactorer** : scroll BM25 separe + dense separe + fusion manuelle RRF

### RAGAS Diagnostic ✅
- Script `benchmark/evaluators/ragas_diagnostic.py` operationnel
- Widget cockpit RAGAS (barres horizontales, diagnostic, worst samples)
- API endpoints : `/api/benchmarks/ragas`, `/ragas/run`, `/ragas/progress`, `/ragas/compare`
- Page frontend `/admin/benchmarks` onglet RAGAS avec lancement, progression, comparaison
- Execution via RQ worker (plus de crash BackgroundTasks)
- Proxy Next.js routes crees (`frontend/src/app/api/benchmarks/ragas/...`)
- Fallback GPT-4o pour les reponses longues (max_tokens)
- Troncation reponses 2000 chars / contexte 1500 chars

### Premier benchmark RAGAS complet (100q T1 Human, OSMOSIS vs RAG)

```
                    OSMOSIS    RAG       Delta
  Faithfulness       0.743      0.762     -0.019 (RAG meilleur)
  Context Relevance  0.580      0.513     +0.067 (OSMOSIS meilleur)
```

### Analyse detaillee

**Faithfulness (0.74)** :
- 62% bon/excellent (>=0.7)
- 26% moyen (0.5-0.7)
- 11% mauvais (<0.5) — LLM hallucine sur ~10 questions
- Cause : le LLM extrapole au-dela du contexte fourni

**Context Relevance (0.58)** — LE vrai probleme :
- Distribution en U : 33% excellent (>=0.9) vs 27% tres mauvais (<0.3)
- Les 27 questions en echec sont des termes specifiques : SAP Notes, transactions, codes, tables
- C'est exactement le cas d'usage du hybrid BM25 — le dense rate les termes exacts
- **Le vrai hybrid RRF est le levier #1** pour ameliorer context_relevance

## Bugs identifies et fixes

### Fixes deployes
- Bug compteur burst cockpit (`burst.py` — `_add_event` manquant dans `process_single_doc`)
- Bug hierarchical postprocessor (`docling_extractor.py` — `source_path` pas passe)
- Bug silent exception burst (`burst.py` — `asyncio.gather` exceptions loggees)
- Bug EC2 fantome (`burst.py` — health check vLLM dans `get_burst_status`)
- Bug jauges vLLM cockpit (`burst_collector.py` — tok/s + prefix `vllm:`)
- Bug RAGAS widget cockpit (`ragas_collector.py` — tri par mtime au lieu de nom)
- Bug RAGAS crash BackgroundTasks → migration vers RQ worker
- Bug RAGAS max_tokens → troncation 2000 chars + fallback GPT-4o
- Bug RAGAS rate limiting → concurrence reduite a 3 + stagger
- Bug frontend RAGAS → proxy Next.js routes creees
- Bug frontend comparaison → types adaptes au format API reel
- Volume `benchmark/` ajoute au worker docker-compose
- `OSMOSIS_API_URL=http://app:8000` ajoute au worker env

### Bugs non resolus
- 029/030 crash post-Docling : process meurt sans erreur apres "Finished Converting". Pas OOM, pas exception. A investiguer.
- Frontend RAGAS : le bouton "Lancer" ne fonctionne pas (l'API fonctionne quand appelee en CLI). Probablement un probleme d'auth dans le fetch.
- Pipeline cockpit : animation de transition entre etapes trop rapide ou invisible

## Infra realise

- `ragas>=0.4.0` ajoute dans `app/requirements.txt`
- Queue "benchmark" ajoutee au worker (`worker.py`)
- Volume `./benchmark:/app/benchmark` ajoute au worker dans docker-compose
- `OSMOSIS_API_URL: http://app:8000` ajoute au worker env dans docker-compose
- Text index Qdrant `text` (word tokenizer) cree sur `knowbase_chunks_v2`
- Pipeline definition `benchmark-ragas` ajoutee dans `cockpit/pipeline_defs.yaml`

## Priorites pour la prochaine session

1. **Refactorer hybrid BM25+dense** — vrai RRF avec scroll BM25 separe. C'est le levier #1.
2. **Relancer benchmark RAGAS** apres hybrid fix — mesurer l'impact sur les 27% de misses.
3. **Phase 2 C1 Canonicalisation** — si hybrid resout le retrieval, attaquer le KG quality.
4. **Fix frontend bouton Lancer RAGAS** — debugger le fetch (auth? CORS?).
5. **Investiguer crash 029/030** — optionnel, 2 docs secondaires.
