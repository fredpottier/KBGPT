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
- **scripts/** : Contient les scripts pour l'ingestion et la purge de données.
- **models/** : Emplacement des modèles de Hugging Face téléchargés.
- **data/** : Dossier utilisé pour le stockage de documents et logs.
- **docs_done/** & **docs_in/** : Répertoires pour gérer les documents traités et en attente.
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

- **`scripts/ingest_documents.py`** : Script pour ingérer des documents SAP dans Qdrant.
- **`scripts/ingest_excel_via_gpt.py`** : Ingestion de fichiers Excel avec GPT.
- **`scripts/ingest_pptx_via_gpt.py`** : Ingestion de présentations PPTX avec GPT.
- **`scripts/purge_Collection.py`** : Purge des données de la collection.

## Badges & Esthétique

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://www.docker.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-red)](https://www.streamlit.io/)

---

Ce projet est conçu pour offrir un système de recherche de connaissances robuste et flexible, spécialement adapté pour les données SAP. Les développeurs peuvent l'étendre selon leurs besoins spécifiques.