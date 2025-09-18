from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from knowbase.common.clients import get_qdrant_client, get_sentence_transformer
from knowbase.config.settings import get_settings

settings = get_settings()
COLLECTION_NAME = settings.qdrant_collection
STATUS_DIR = settings.status_dir

qdrant_client = get_qdrant_client()
model = get_sentence_transformer()


def fetch_all_chunks(limit: int = 10000) -> pd.DataFrame:
    scroll = qdrant_client.scroll(
        collection_name=COLLECTION_NAME,
        with_payload=True,
        limit=limit,
    )
    payloads = [point.payload for point in scroll[0] if point.payload]
    return pd.DataFrame(payloads)


def read_status_files() -> pd.DataFrame:
    status_entries: list[dict[str, Any]] = []
    if STATUS_DIR.exists():
        for file in STATUS_DIR.glob('*.status'):
            status_entries.append({
                'file': file.stem,
                'status': file.read_text(encoding='utf-8', errors='ignore').strip(),
            })
    return pd.DataFrame(status_entries)


def main() -> None:
    st.set_page_config(page_title='Knowledge Base Dashboard', layout='wide')
    st.title('🔍 Knowledge Base Dashboard (Qdrant)')

    df = fetch_all_chunks()
    if df.empty:
        st.warning('Aucun chunk trouvé dans la collection.')
        st.stop()

    with st.sidebar:
        st.header('Filtres')
        main_solutions = sorted(df['main_solution'].dropna().unique()) if 'main_solution' in df else []
        document_types = sorted(df['document_type'].dropna().unique()) if 'document_type' in df else []

        selected_solution = st.selectbox('Main Solution', ['(toutes)'] + main_solutions)
        selected_type = st.selectbox('Document Type', ['(tous)'] + document_types)
        search_query = st.text_input('🔍 Recherche texte dans les chunks')

    filtered_df = df.copy()
    if selected_solution != '(toutes)':
        filtered_df = filtered_df[filtered_df['main_solution'] == selected_solution]
    if selected_type != '(tous)':
        filtered_df = filtered_df[filtered_df['document_type'] == selected_type]
    if search_query:
        filtered_df = filtered_df[
            filtered_df['text'].str.contains(search_query, case=False, na=False)
        ]

    st.subheader('📊 Vue globale')
    st.metric('Chunks indexés', len(df))
    st.metric('Documents uniques', df['title'].nunique() if 'title' in df else 'N/A')

    st.subheader('🛠 Suivi des fichiers en traitement')
    status_df = read_status_files()
    if not status_df.empty:
        st.dataframe(status_df, use_container_width=True)
    else:
        st.info('Aucun fichier en cours de traitement ou déjà traité.')

    if 'title' in df:
        st.subheader('📁 Nombre de documents analysés (titre unique)')
        doc_counts = df['title'].value_counts().reset_index()
        doc_counts.columns = ['Titre du document', 'Nb de chunks']
        st.dataframe(doc_counts, use_container_width=True)

    st.subheader('🎯 Objectifs détectés dans les documents')
    if 'title' in df and 'objective' in df:
        docs = df[['title', 'objective']].drop_duplicates().sort_values('title')
        st.dataframe(docs, use_container_width=True)

    st.subheader('🧬 Explorer les documents et chunks')
    if 'title' in filtered_df and not filtered_df.empty:
        unique_titles = filtered_df['title'].dropna().unique()
        selected_title = st.selectbox('📁 Sélectionner un document (title)', options=unique_titles)
        df_doc = filtered_df[filtered_df['title'] == selected_title]

        if not df_doc.empty:
            chunk_options = []
            for i, row in df_doc.iterrows():
                preview = (row.get('text', '') or '')[:100].replace('\n', ' ')
                chunk_options.append(f'[{i}] {preview}...')
            selected_chunk_label = st.selectbox('🔎 Choisir un chunk (aperçu)', options=chunk_options)
            selected_chunk_index = chunk_options.index(selected_chunk_label)
            selected_chunk = df_doc.iloc[selected_chunk_index].to_dict()

            st.markdown('#### 📄 Contenu du chunk sélectionné')
            st.json(selected_chunk)
        else:
            st.info('Aucun chunk disponible pour ce document.')
    else:
        st.info('Aucun titre de document disponible.')

    st.subheader('💬 Interroger la base vectorielle')
    user_question = st.text_input('Posez une question métier')

    if user_question:
        vector = model.encode([f"passage: Q: {user_question}"], normalize_embeddings=True)[0].tolist()
        results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=5,
            with_payload=True,
        )
        st.markdown('#### 🔎 Chunks les plus pertinents')
        for i, r in enumerate(results):
            st.markdown(f'**Chunk {i + 1}**')
            st.json(r.payload)


if __name__ == '__main__':
    main()
