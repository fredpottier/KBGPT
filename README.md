# SAP_KB Project

SAP_KB est un projet local, entièrement dockerisé, destiné à indexer, structurer et interroger une base de connaissance SAP. Cette base peut comprendre des documents aux formats PDF, PPTX, DOCX et Excel.

## Contexte Fonctionnel

- **Embeddings & ReRanker** :
  - Utilise `intfloat/multilingual-e5-base` pour les embeddings.
  - Utilise `cross-encoder/ms-marco-MiniLM-L-6-v2` pour le reranking des résultats de recherche.
- **Stockage** :
  - Les documents sont stockés localement et ingérés via des scripts Python, puis envoyés dans une base de données Qdrant.
- **API Backend** :
  - Expose une API FastAPI via `app/main.py` permettant d’interroger la base de données.
- **Interface Utilisateur** :
  - Une interface Streamlit (située dans `ui/app.py`) permet de visualiser les chunks indexés, de rechercher par mot-clé, de filtrer et de suivre le statut des fichiers.
- **Exposition Publique** :
  - Un tunnel ngrok expose l’API localement sous une URL fixe pour connecter un GPT personnalisé via OpenAPI.
- **Modèles Machine Learning** :
  - Les modèles de Hugging Face sont automatiquement téléchargés dans un répertoire monté (`/models`) via la variable `HF_HOME`.

## Architecture du Projet

- **app/** : Contient les composants backend, y compris FastAPI.
- **ui/** : Gère l'interface utilisateur avec Streamlit.
- **src/knowbase/ingestion/cli/** : regroupe les utilitaires CLI (purge, tests,
  maintenance) utilisés pendant l'ingestion.
- **scripts/** : contient désormais uniquement des wrappers de compatibilité qui
  redirigent vers les nouvelles commandes CLI.
- **data/** : Dossier racine pour toutes les données runtime. Il contient
  notamment `docs_in/`, `docs_done/`, `logs/`, `models/`, `status/` ainsi que les
  ressources publiques (`public/`).
- 🔁 Des liens symboliques sont automatiquement créés vers les anciens chemins
  (`docs_in/`, `docs_done/`, `logs/`, etc.) pour assurer une transition douce.
- **openapi.json** : Description de l'API.

## Lancement du Projet

1. **Prérequis** :
   - Avoir Docker et Docker Compose installés sur votre machine.
   - Configurer les variables d'environnement nécessaires dans `.env`.

2. **Démarrer le projet** :
   ```bash
   docker-compose up --build
   ```

3. **Accéder aux services** :
   - **API FastAPI** : Ouvrez `http://localhost:5173/docs` pour interagir avec l'API via l'interface Swagger.
   - **UI Streamlit** : Disponible à `http://localhost:8501`.
   - **URL Public ngrok** : Vérifiez les logs de ngrok pour l'URL attribuée.

## Scripts Disponibles

Les utilitaires historiques restent accessibles via le dossier `scripts/`, mais
les implémentations principales se trouvent désormais dans
`src/knowbase/ingestion/cli/`.  Chaque outil peut être exécuté directement via
les wrappers existants ou via le module Python correspondant, par exemple :

```bash
python scripts/generate_thumbnails.py
python -m knowbase.ingestion.cli.purge_collection --yes
```

## Tests

Une base de tests `pytest` est fournie pour sécuriser les refactorings
successifs. Après avoir installé les dépendances de développement :

```bash
pip install -r requirements.txt
pytest
```

Les tests configurent automatiquement `KNOWBASE_DATA_DIR` vers un dossier
temporaire ; l’exécution de `pytest` ne modifie donc pas vos données locales.
Vous pouvez lancer un fichier ou un répertoire spécifique, par exemple :

```bash
pytest tests/config/test_paths.py
pytest tests/ingestion -k thumbnail
```

## Gestion des prompts LLM paramétrables

Les prompts utilisés pour l’analyse des decks et des slides sont définis dans `config/prompts.yaml`.
Chaque famille (`default`, `technical`, `functional`, etc.) contient un template pour le deck et pour les slides.

Pour forcer un type de prompt à l’ingestion :
```bash
python scripts/ingest_pptx_via_gpt.py chemin/vers/fichier.pptx --document-type functional
```

Pour ajouter ou modifier une famille de prompts :
- Éditez `config/prompts.yaml` et ajoutez une nouvelle entrée sous `families`.
- Chaque famille doit contenir un champ `deck` et un champ `slide` avec un `id` et un `template`.

Les points ingérés dans Qdrant incluent un champ `prompt_meta` pour la traçabilité :
```json
{
  "prompt_meta": {
    "document_type": "functional",
    "deck_prompt_id": "deck_functional_v1",
    "slide_prompt_id": "slide_functional_v1",
    "prompts_version": "2024-09-06"
  }
}
```

## Prochaines évolutions à prendre en compte
 - centraliser l'instantiation du modèle afin qu'il ne soit chargé qu'une seule fois
 - ajouter la gestion des claims pour le controle d'incohérence sur les informations uploadée (chunk : valid / pending : retired)
 - mise en place d'un reranker type cross-encoder/ms-marco-MiniLM-L-6-v2

## Badges & Esthétique

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://www.docker.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-red)](https://www.streamlit.io/)

---

Ce projet est conçu pour offrir un système de recherche de connaissances robuste et flexible, spécialement adapté pour les données SAP. Les développeurs peuvent l'étendre selon leurs besoins spécifiques.