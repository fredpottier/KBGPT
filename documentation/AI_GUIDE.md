# Guide pour les IA génératives

Ce guide synthétise les conventions et garde-fous à respecter lorsqu’une IA modifie ou étend Knowbase.

## Principes généraux

1. **S’appuyer sur la documentation** :
   - `OVERVIEW.md` pour comprendre l’architecture avant de coder.
   - `BACKEND_APIS.md` pour identifier les endpoints existants et les services associés.
   - `MODULES.md` et `registry.json` pour localiser rapidement les fonctions et connaître leurs signatures/dépendances.
2. **Respect de la modularité** : chaque fonctionnalité doit passer par une couche service (dans `src/knowbase/api/services`) avant d’être exposée par un router.
3. **Éviter la duplication** : mutualiser les appels clients via `knowbase.common.clients.shared_clients` et réutiliser `LLMRouter`/`TokenTracker`.
4. **Observer les conventions de logging** : utiliser `knowbase.common.logging.setup_logging` ou `logging.getLogger(__name__)` selon le module.
5. **Protéger l’isolement multi-tenant** : toujours lire/écrire le `group_id` via `UserContextMiddleware` ou `GraphitiTenantManager` lorsque vous touchez au Knowledge Graph, aux facts ou aux utilisateurs.

## Nommage & structure

- **Endpoints** : nouveaux routers à créer dans `src/knowbase/api/routers`, avec préfixe explicite (`/api/...`). Nommer les fonctions en snake_case et retourner des modèles Pydantic lorsque c’est pertinent.
- **Services** : placer la logique métier dans `src/knowbase/api/services`. Préfixer les fonctions par le verbe (`create_`, `get_`, `update_`, `delete_`, `handle_`) pour refléter l’intention.
- **Pipelines** : centraliser dans `src/knowbase/ingestion/pipelines` et exposer des fonctions `process_*` ou `main`. Utiliser des callbacks de progression si le traitement dure.
- **Clients externes** : ajouter les initialisations dans `src/knowbase/common/clients` pour profiter du cache partagé.

## Variables d’environnement clés

| Variable | Usage | Fichier de référence |
| --- | --- | --- |
| `KNOWBASE_DATA_DIR` | Racine du dossier `data/` (docs, logs, modèles) | `config/settings.py` |
| `QDRANT_URL`, `QDRANT_API_KEY` | Connexion Qdrant | `common/clients/qdrant_client.py` |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Accès LLM | `common/clients/openai_client.py`, `common/clients/anthropic_client.py` |
| `GRAPHITI_URL`, `GRAPHITI_AUTH_TOKEN` | Connexion Graphiti store | `common/graphiti/config.py` |
| `REDIS_URL`, `INGESTION_QUEUE` | Workers RQ | `ingestion/queue/connection.py` |
| `PUBLIC_URL` | Génération de liens statiques | `services/search.py`, `services/status.py` |

## Entry points & démarrage

- **API FastAPI** : `app/main.py` instancie `create_app()`.
- **Workers ingestion** : `python -m knowbase.ingestion.queue` ou `ingestion/queue/worker.py:main()`.
- **UI Streamlit** : `ui/app.py` ou `src/knowbase/ui/streamlit_app.py`.
- **Scripts CLI** : `scripts/` contient des utilitaires (purge Qdrant, export Graphiti, validation). Toujours vérifier les options avant exécution.

## Ajouter un nouvel endpoint

1. Définir/étendre les schémas Pydantic dans `src/knowbase/api/schemas`.
2. Implémenter la logique métier dans un service (`src/knowbase/api/services`).
3. Créer la route dans `src/knowbase/api/routers/…` en important le service.
4. Mettre à jour `BACKEND_APIS.md`, `MODULES.md` et `registry.json` (section correspondante) pour garder la documentation synchronisée.
5. Ajouter des tests ciblés dans `tests/` (ou `app/tests/` pour la version conteneurisée).

## Gestion des dépendances & clients

- Utiliser `get_settings()` pour accéder aux chemins et secrets. Ne pas lire directement `os.environ` dans les modules applicatifs (sauf dans les settings).
- Pour Qdrant, embeddings et LLM : appeler les helpers (`get_qdrant_client()`, `get_sentence_transformer()`, `LLMRouter`) afin de bénéficier du cache et du warm-up.
- Les jobs RQ doivent toujours appeler `mark_job_as_processing()` au début et `update_job_progress()` régulièrement pour alimenter l’historique Redis.

## Sécurité & gouvernance des données

- Les fonctions Knowledge Graph et Facts doivent systématiquement appeler `UserKnowledgeGraphService.set_group` ou `FactsGovernanceService.set_group` via le contexte utilisateur.
- Lors de la suppression d’un import (`delete_import_completely`), veiller à nettoyer Qdrant, Redis et le filesystem pour éviter les orphelins.
- Les métadonnées utilisateur/tenant sont persistées dans des fichiers JSON ; utiliser les services dédiés pour garantir l’intégrité et éviter les conflits de verrouillage.

## Tests & validation

- Lancer `pytest` depuis la racine pour couvrir `src/knowbase`.
- Des tests d’intégration Graphiti/Qdrant sont fournis (`tests/integration/...`). Vérifiez que les environnements externes (Neo4j, Graphiti API, Qdrant) sont disponibles avant d’exécuter ces tests.
- Le script `test_phase2_validation.py` récapitule les checks phares de la phase 2 ; utilisez-le après de grosses refontes ingestion/KG.

En suivant ces conventions, une IA peut contribuer en toute sécurité sans casser les workflows critiques (ingestion, recherche, gouvernance, KG). Toute extension doit maintenir la cohérence de cette documentation.
