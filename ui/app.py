import streamlit as st
import pandas as pd
from pathlib import Path
import os
from utils.shared_clients import (
    get_qdrant_client,
    get_sentence_transformer,
)

# === CONFIGURATION ===
COLLECTION_NAME = "sap_kb"
STATUS_PATH = Path("C:/SAP_KB/status")

# === CONNEXION QDRANT ===
qdrant_client = get_qdrant_client()

# Ajoute le modèle d'embedding
# MODEL_NAME = "sentence-transformers/paraphrase-xlm-r-multilingual-v1"
MODEL_NAME = os.getenv("EMB_MODEL_NAME", "intfloat/multilingual-e5-base")
model = get_sentence_transformer(MODEL_NAME)


# === FONCTIONS ===
def fetch_all_chunks():
    """Récupère tous les points de la collection avec leur payload."""
    scroll = qdrant_client.scroll(
        collection_name=COLLECTION_NAME, with_payload=True, limit=10000
    )
    payloads = [point.payload for point in scroll[0] if point.payload]
    return pd.DataFrame(payloads)


def read_status_files():
    status_entries = []
    if STATUS_PATH.exists():
        for file in STATUS_PATH.glob("*.status"):
            status = file.read_text().strip()
            status_entries.append({"file": file.stem, "status": status})
    return pd.DataFrame(status_entries)


# === UI STREAMLIT ===
st.set_page_config(page_title="SAP KB Dashboard", layout="wide")
st.title("🔍 SAP Knowledge Base Dashboard (Qdrant)")

# Charger les données
df = fetch_all_chunks()

if df.empty:
    st.warning("Aucun chunk trouvé dans la collection.")
    st.stop()

# === Sidebar - Filtres ===
st.sidebar.header("Filtres")

main_solutions = (
    sorted(df["main_solution"].dropna().unique()) if "main_solution" in df else []
)
document_types = (
    sorted(df["document_type"].dropna().unique()) if "document_type" in df else []
)

selected_solution = st.sidebar.selectbox("Main Solution", ["(toutes)"] + main_solutions)
selected_type = st.sidebar.selectbox("Document Type", ["(tous)"] + document_types)
search_query = st.sidebar.text_input("🔍 Recherche texte dans les chunks")

# === Filtrage ===
filtered_df = df.copy()
if selected_solution != "(toutes)":
    filtered_df = filtered_df[filtered_df["main_solution"] == selected_solution]
if selected_type != "(tous)":
    filtered_df = filtered_df[filtered_df["document_type"] == selected_type]
if search_query:
    filtered_df = filtered_df[
        filtered_df["text"].str.contains(search_query, case=False, na=False)
    ]

# === Vue résumée ===
st.subheader("📊 Vue globale")
st.metric("Chunks indexés", len(df))
st.metric("Documents uniques", df["title"].nunique() if "title" in df else "N/A")

# === Suivi des fichiers en traitement ===
st.subheader("🛠 Suivi de l'état des fichiers en traitement")
status_df = read_status_files()
if not status_df.empty:
    st.dataframe(status_df, use_container_width=True)
else:
    st.info("Aucun fichier en cours de traitement ou déjà traité.")

# === Agrégation par fichier source ===
if "title" in df:
    st.subheader("📁 Nombre de documents analysés (titre unique)")
    doc_counts = df["title"].value_counts().reset_index()
    doc_counts.columns = ["Titre du document", "Nb de chunks"]
    st.dataframe(doc_counts, use_container_width=True)

# === Objectifs par document ===
st.subheader("🎯 Objectifs détectés dans les documents")
if "title" in df and "objective" in df:
    docs = df[["title", "objective"]].drop_duplicates().sort_values("title")
    st.dataframe(docs, use_container_width=True)

# === Détail interactif : Document → Chunk
st.subheader("🧬 Explorer les documents et chunks")

# Étape 1 : choisir un document
if "title" in filtered_df:
    unique_titles = filtered_df["title"].dropna().unique()
    selected_title = st.selectbox(
        "📁 Sélectionner un document (title)", options=unique_titles
    )

    df_doc = filtered_df[filtered_df["title"] == selected_title]

    # Étape 2 : choisir un chunk à afficher
    if not df_doc.empty:
        chunk_options = [
            "[{}] {}...".format(i, row.get("text", "")[:100].replace("\n", " "))
            for i, row in df_doc.iterrows()
        ]
        selected_chunk_label = st.selectbox(
            "🔎 Choisir un chunk (aperçu)", options=chunk_options
        )
        selected_chunk_index = chunk_options.index(selected_chunk_label)
        selected_chunk = df_doc.iloc[selected_chunk_index].to_dict()

        # Affichage du chunk sélectionné
        st.markdown("#### 📄 Contenu du chunk sélectionné")
        st.json(selected_chunk)
    else:
        st.info("Aucun chunk disponible pour ce document.")
else:
    st.info("Aucun titre de document disponible.")

# === Espace de question vectorielle ===
st.subheader("💬 Interroger la base vectorielle")

user_question = st.text_input("Posez une question métier SAP (vector search)")

if user_question:
    # Vectorisation de la question
    emb = model.encode([f"passage: Q: {user_question}"], normalize_embeddings=True)[
        0
    ].tolist()
    # Recherche dans Qdrant
    results = qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=emb,
        limit=5,
        with_payload=True,
    )
    st.markdown("#### 🔎 Chunks les plus pertinents")
    for i, r in enumerate(results):
        st.markdown(f"**Chunk {i+1}**")
        st.json(r.payload)
