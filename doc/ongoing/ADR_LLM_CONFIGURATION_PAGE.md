# ADR : Page Admin Configuration LLM — Mapping tache-par-tache

*Date : 16 avril 2026*
*Statut : Propose*

## Contexte

La gestion des LLM dans OSMOSIS est devenue trop complexe :
- 4 providers (OpenAI, Anthropic, Ollama, DeepInfra)
- 3 modes globaux (Normal, Partial Local, Burst Local) qui ne refletent pas la realite des usages
- Des fallbacks en cascade (Ollama → OpenAI → erreur)
- Config dispersee entre YAML, env vars, Redis, PostgreSQL

Le retour d'experience des 14-16 avril 2026 montre que :
- DeepInfra offre le meilleur rapport qualite/prix pour les taches cloud
- Le GPU local (RTX 5070 Ti) est suffisant pour Ollama (synthese simple) et embeddings
- M-Prometheus local est le meilleur juge benchmark
- Le burst EC2 reste utile comme override temporaire
- La concurrence Ollama (sequentielle) impose des adaptations differentes du cloud (parallele)

## Proposition : Page Admin "Configuration LLM"

### Principe

Remplacer les 3 modes globaux par un **mapping tache-par-tache** configurable dans l'UI. Chaque "grande utilisation" a un switch Local / Cloud avec choix de modele.

### Les grandes utilisations

| Usage | Description | Defaut |
|-------|------------|--------|
| **Synthese search** | Reponse aux questions utilisateur | Cloud: Qwen3-235B (DeepInfra) |
| **Extraction claims** | ClaimFirst batch sur les documents | Cloud: Qwen2.5-72B (DeepInfra) |
| **Canonicalisation** | Normalisation entites cross-doc | Cloud: Qwen2.5-72B (DeepInfra) |
| **Post-import LLM** | C4/C6 relations, perspectives | Cloud: Qwen3-235B (DeepInfra) |
| **Juge benchmark** | Evaluation T2/T5, RAGAS, robustesse | Local: M-Prometheus (Ollama) |
| **Embeddings** | Vectorisation chunks et claims | Local: e5-large (GPU) |
| **Vision** | Analyse images PDF/PPTX | Cloud: GPT-4o (OpenAI) |
| **Classification** | Taches simples (oui/non) | Local: qwen3.5:9b (Ollama) |

### UI proposee

Pour chaque usage, une ligne avec :
- **Nom de l'usage** + description
- **Switch** : Local / Cloud
- **Selecteur modele** :
  - Si Local : liste des modeles Ollama installes (detection auto via /api/tags)
  - Si Cloud : liste des modeles DeepInfra disponibles + GPT-4o pour vision
- **Indicateur** : cout estime/1000 appels, latence moyenne
- **Alertes** :
  - Changer l'embedding declencherait : "Ce changement impose une re-indexation complete de Qdrant"
  - Choisir un modele local trop gros : "Ce modele requiert X GB VRAM, votre GPU a 16 GB"

### Override EC2 Burst

Un toggle separe "EC2 Burst Override" qui, quand une EC2 est attachee et UP, prend le pas sur TOUS les usages (sauf vision GPT-4o et juge local). C'est un etat temporaire d'import, pas un mode permanent.

### Persistance

- Table PostgreSQL `system_settings` (deja creee) avec cle `llm_config`
- Valeur JSON : mapping usage → {provider, model, local_model}
- Cache Redis 5s (pattern existant dans llm_router)
- Le llm_router lit ce mapping au lieu de la config YAML

### Impact sur le code

- `llm_router.py` : remplacer `_get_model_for_task()` par lecture du mapping PostgreSQL
- Supprimer les 3 modes (NORMAL, PARTIAL_LOCAL, FULL_LOCAL)
- Supprimer les fallbacks OpenAI/Anthropic
- Garder le gate burst EC2 (override temporaire)
- Supprimer `_ensure_vllm_for_full_local()` (plus de vLLM auto-start)
- Frontend : nouvelle page admin, supprimer le selecteur tri-mode

### Modeles disponibles

**Cloud (DeepInfra) :**
- Qwen3-235B-A22B-Instruct-2507 ($0.071/$0.10) — synthese, post-import
- Qwen2.5-72B-Instruct ($0.12/$0.39) — extraction, canonicalisation
- Qwen3-32B ($0.08/$0.28) — alternative medium
- Qwen3-14B ($0.12/$0.24) — taches legeres
- Qwen3-Embedding-8B ($0.006/M tok) — embeddings cloud

**Local (Ollama) :**
- qwen2.5:14b (9 GB) — extraction, synthese simple
- m-prometheus-14b (9 GB) — juge benchmark
- qwen3.5:9b (6.6 GB) — classification, enrichment

**Local (GPU direct) :**
- e5-large (1.2 GB VRAM) — embeddings
- Futur : Jina v3, BGE-M3 (au prochain re-import)

**Cloud (OpenAI) — legacy, cas unique :**
- GPT-4o — vision uniquement

## Migration

1. Creer la page admin frontend
2. Migrer le llm_router pour lire le mapping PostgreSQL
3. Supprimer les modes globaux + fallbacks
4. Tests end-to-end sur chaque usage
5. Documenter le nouveau systeme
