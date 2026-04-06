"""
OSMOSE Retrieval Layer — Re-chunker pour embeddings vectoriels.

Re-découpe les TypeAwareChunks en sous-chunks de ~target_chars caractères
pour optimiser la qualité des embeddings (fenêtre modèle ~512 tokens).

Inclut un pré-filtrage qualité pour éliminer les chunks vides, trop courts,
ou sans contenu sémantique exploitable avant embedding.

Spec: ADR_QDRANT_RETRIEVAL_PROJECTION_V2.md
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from knowbase.structural.models import ChunkKind, TypeAwareChunk

logger = logging.getLogger(__name__)

# --- Seuils de filtrage qualité ---
MIN_CHARS_MEANINGFUL = 30       # Sous ce seuil, un chunk n'a pas de valeur sémantique
MIN_CHARS_NON_NARRATIVE = 15    # Seuil minimal pour TABLE/FIGURE/CODE (plus permissif)
MIN_WORD_COUNT = 3              # Au moins 3 mots pour être exploitable

# Namespace UUID5 constant pour idempotence Qdrant (jamais re-généré)
OSMOSE_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


@dataclass
class SubChunk:
    """Sous-chunk pour embedding vectoriel dans Qdrant Layer R."""

    chunk_id: str           # ID du chunk parent
    sub_index: int          # Index du sous-chunk (0 si chunk non découpé)
    text: str               # Texte original (affiché/cité)
    parent_chunk_id: str    # = chunk_id
    section_id: Optional[str]
    doc_id: str
    tenant_id: str
    kind: str               # ChunkKind.value
    page_no: int
    page_span_min: Optional[int] = None
    page_span_max: Optional[int] = None
    item_ids: List[str] = field(default_factory=list)
    text_origin: Optional[str] = None
    section_title: Optional[str] = None

    def point_id(self) -> str:
        """UUID5 déterministe pour idempotence Qdrant."""
        key = f"{self.tenant_id}:{self.doc_id}:{self.chunk_id}:{self.sub_index}"
        return str(uuid.uuid5(OSMOSE_NAMESPACE, key))


# Regex pour vraie fin de phrase : "." suivi d'espace + majuscule.
# Exclut : numeros de section (15.3.5), abbreviations (e.g., i.e., vs.),
# URLs (sap.com), decimaux (3.14).
_SENTENCE_END_RE = re.compile(
    r'(?<!\d)'          # pas precede d'un chiffre (15.3.5)
    r'(?<!\b[a-z])'     # pas precede d'une lettre minuscule seule (e.g.)
    r'[.!?]'            # ponctuation de fin de phrase
    r'(?=\s+[A-Z])'     # suivi d'espace + majuscule
)


def _find_sentence_break(text: str, window_start: int, window_end: int) -> Optional[int]:
    """
    Cherche la derniere vraie fin de phrase dans la fenetre [window_start, window_end].

    Utilise une regex qui exclut les faux positifs :
    - Numeros de section (15.3.5.1)
    - Abbreviations (e.g., i.e., vs.)
    - URLs (help.sap.com)
    - Decimaux (3.14)

    Returns:
        Position apres le caractere de fin de phrase, ou None si aucun trouve.
    """
    window = text[window_start:window_end]
    matches = list(_SENTENCE_END_RE.finditer(window))
    if matches:
        # Prendre le dernier match (le plus proche de window_end)
        last = matches[-1]
        return window_start + last.end()
    return None


def _find_line_break(text: str, window_start: int, window_end: int) -> Optional[int]:
    """
    Cherche le dernier saut de ligne dans la fenêtre [window_start, window_end].

    Returns:
        Position après le \n, ou None si aucun trouvé.
    """
    best = None
    for i in range(window_end - 1, window_start - 1, -1):
        if text[i] == "\n":
            best = i + 1
            break
    return best


# --- Marqueurs visuels (invariant : jamais coupes par le rechunker) ---
VISUAL_BLOCK_START = "═══ VISUAL CONTENT (AI-interpreted, not author text) ═══"
VISUAL_BLOCK_END = "═══ END VISUAL CONTENT ═══"


def _find_visual_blocks(text: str) -> list[tuple[int, int]]:
    """
    Detecte les blocs visuels balises dans le texte.

    Returns:
        Liste de (start, end) pour chaque bloc visuel.
        start = debut de la ligne VISUAL_BLOCK_START
        end = fin de la ligne VISUAL_BLOCK_END (inclut le newline)
    """
    blocks: list[tuple[int, int]] = []
    search_from = 0
    while True:
        start = text.find(VISUAL_BLOCK_START, search_from)
        if start == -1:
            break
        # Reculer au debut de la ligne
        line_start = text.rfind("\n", 0, start)
        line_start = line_start + 1 if line_start != -1 else start

        end = text.find(VISUAL_BLOCK_END, start)
        if end == -1:
            # Bloc non ferme — proteger jusqu'a la fin
            blocks.append((line_start, len(text)))
            break
        # Avancer apres la fin du marqueur + newline eventuel
        block_end = end + len(VISUAL_BLOCK_END)
        if block_end < len(text) and text[block_end] == "\n":
            block_end += 1
        blocks.append((line_start, block_end))
        search_from = block_end
    return blocks


def _is_inside_visual_block(pos: int, visual_blocks: list[tuple[int, int]]) -> Optional[int]:
    """
    Verifie si une position est a l'interieur d'un bloc visuel.

    Returns:
        Le debut du bloc si pos est dedans, None sinon.
    """
    for block_start, block_end in visual_blocks:
        if block_start <= pos < block_end:
            return block_start
    return None


# --- Blocs atomiques : tables markdown et listes numerotees ---
# Seuil au-dela duquel on accepte de couper un tableau (avec header replay)
MAX_ATOMIC_TABLE_CHARS = 3000
# Regex pour ligne de tableau markdown
_TABLE_ROW_RE = re.compile(r'^\s*\|.+\|\s*$')
_TABLE_SEP_RE = re.compile(r'^\s*\|[\s\-:|]+\|\s*$')
# Regex pour liste numerotee consecutive
_NUMBERED_LIST_RE = re.compile(r'^\s*\d+[.)]\s')


def _find_protected_blocks(text: str) -> list[tuple[int, int, str]]:
    """
    Detecte tous les blocs protéges dans le texte : visuels, tables, listes.

    Returns:
        Liste de (start, end, type) tries par position.
        type = 'visual' | 'table' | 'list'
    """
    blocks: list[tuple[int, int, str]] = []

    # 1. Blocs visuels (deja existant)
    for start, end in _find_visual_blocks(text):
        blocks.append((start, end, "visual"))

    # 2. Blocs tableau markdown (lignes consecutives commencant par |)
    lines = text.split("\n")
    pos = 0
    table_start = None
    for i, line in enumerate(lines):
        line_start = pos
        line_end = pos + len(line)  # sans le \n

        is_table_line = bool(_TABLE_ROW_RE.match(line)) or bool(_TABLE_SEP_RE.match(line))

        if is_table_line and table_start is None:
            table_start = line_start
        elif not is_table_line and table_start is not None:
            table_end = pos  # debut de la ligne non-table (inclut le \n precedent)
            if table_end - table_start > 50:  # ignorer les "tables" d'1 ligne
                blocks.append((table_start, table_end, "table"))
            table_start = None

        pos = line_end + 1  # +1 pour le \n

    # Fermer un bloc table en fin de texte
    if table_start is not None and pos - table_start > 50:
        blocks.append((table_start, pos, "table"))

    # 3. Blocs liste numerotee (lignes consecutives 1. 2. 3.)
    pos = 0
    list_start = None
    list_count = 0
    for i, line in enumerate(lines):
        line_start = pos
        is_list = bool(_NUMBERED_LIST_RE.match(line))

        if is_list and list_start is None:
            list_start = line_start
            list_count = 1
        elif is_list:
            list_count += 1
        elif not is_list and list_start is not None:
            if list_count >= 3:  # Au moins 3 items pour etre une vraie liste
                blocks.append((list_start, pos, "list"))
            list_start = None
            list_count = 0

        pos = line_start + len(line) + 1

    if list_start is not None and list_count >= 3:
        blocks.append((list_start, len(text), "list"))

    # Trier par position et fusionner les chevauchements
    blocks.sort(key=lambda b: b[0])
    return blocks


def _is_inside_protected_block(
    pos: int, blocks: list[tuple[int, int, str]]
) -> Optional[tuple[int, int, str]]:
    """
    Verifie si une position est a l'interieur d'un bloc protege.

    Returns:
        (start, end, type) du bloc si pos est dedans, None sinon.
    """
    for start, end, btype in blocks:
        if start <= pos < end:
            return (start, end, btype)
    return None


def _extract_table_header(table_text: str) -> str:
    """
    Extrait le header markdown d'un tableau (premiere ligne + separateur).

    Returns:
        Les 2 premieres lignes (header + ---) ou '' si pas detecte.
    """
    lines = table_text.split("\n")
    header_lines = []
    for line in lines[:3]:  # Max 3 lignes (header, separator, optionnel)
        if _TABLE_ROW_RE.match(line) or _TABLE_SEP_RE.match(line):
            header_lines.append(line)
        else:
            break
    # On veut au moins header + separator
    if len(header_lines) >= 2:
        return "\n".join(header_lines) + "\n"
    return ""


def _split_table_with_header_replay(
    table_text: str,
    prefix: str,
    target_chars: int,
) -> list[str]:
    """
    Decoupe un tableau long en fragments, chacun avec le header replique.

    Args:
        table_text: Texte du tableau markdown (lignes |...|)
        prefix: Prefixe contextuel a ajouter avant chaque fragment
        target_chars: Taille cible par fragment

    Returns:
        Liste de textes autonomes (prefix + header + lignes de donnees)
    """
    header = _extract_table_header(table_text)
    if not header:
        # Pas de header detecte — retourner tel quel
        return [prefix + table_text if prefix else table_text]

    header_len = len(header)
    lines = table_text.split("\n")

    # Trouver ou commencent les donnees (apres header + separator)
    data_start_idx = 0
    for i, line in enumerate(lines):
        if not _TABLE_ROW_RE.match(line) and not _TABLE_SEP_RE.match(line):
            break
        if _TABLE_SEP_RE.match(line):
            data_start_idx = i + 1
            break
    if data_start_idx == 0:
        data_start_idx = min(2, len(lines))

    data_lines = lines[data_start_idx:]
    fragments: list[str] = []
    current_lines: list[str] = []
    current_len = len(prefix) + header_len

    for line in data_lines:
        line_len = len(line) + 1  # +1 pour \n
        if current_len + line_len > target_chars and current_lines:
            # Emettre le fragment courant
            fragment = prefix + header + "\n".join(current_lines)
            fragments.append(fragment)
            current_lines = []
            current_len = len(prefix) + header_len

        current_lines.append(line)
        current_len += line_len

    # Dernier fragment
    if current_lines:
        fragment = prefix + header + "\n".join(current_lines)
        fragments.append(fragment)

    return fragments if fragments else [prefix + table_text]


@dataclass
class FilterStats:
    """Statistiques de filtrage qualité pré-rechunking."""
    total_input: int = 0
    kept: int = 0
    dropped_empty: int = 0
    dropped_too_short: int = 0
    dropped_no_words: int = 0
    merged_into_next: int = 0


def _is_chunk_usable(chunk: TypeAwareChunk) -> bool:
    """
    Vérifie si un chunk a assez de contenu sémantique pour valoir un embedding.

    Critères :
    - Texte non vide après strip
    - Longueur minimale selon le type (NARRATIVE plus strict)
    - Au moins MIN_WORD_COUNT mots
    """
    text = chunk.text.strip()
    if not text:
        return False

    text_len = len(text)
    word_count = len(text.split())

    # Seuil adapté au type de chunk
    if chunk.kind == ChunkKind.NARRATIVE_TEXT:
        min_chars = MIN_CHARS_MEANINGFUL
    else:
        # TABLE/FIGURE/CODE : seuil plus bas (données structurées)
        min_chars = MIN_CHARS_NON_NARRATIVE

    if text_len < min_chars:
        return False

    if word_count < MIN_WORD_COUNT:
        return False

    return True


def _filter_chunks(chunks: List[TypeAwareChunk]) -> tuple[List[TypeAwareChunk], FilterStats]:
    """
    Filtre les chunks inutilisables avant rechunking.

    Stratégie :
    1. Exclure les chunks vides (texte vide ou whitespace-only)
    2. Exclure les chunks trop courts (< seuil selon type)
    3. Exclure les chunks avec moins de MIN_WORD_COUNT mots

    Les chunks NARRATIVE_TEXT courts (titres isolés) qui précèdent un autre
    NARRATIVE_TEXT sont fusionnés avec le chunk suivant plutôt que supprimés,
    pour préserver le contexte.

    Returns:
        (chunks filtrés, stats de filtrage)
    """
    stats = FilterStats(total_input=len(chunks))

    if not chunks:
        return [], stats

    # Phase 1 : Fusion des titres courts NARRATIVE dans le chunk NARRATIVE suivant
    merged: List[TypeAwareChunk] = []
    pending_prefix: Optional[str] = None  # texte d'un titre court à fusionner

    for i, chunk in enumerate(chunks):
        text = chunk.text.strip()

        # Chunk vide → drop immédiat
        if not text:
            stats.dropped_empty += 1
            continue

        # NARRATIVE court (titre isolé) → tenter fusion avec le suivant
        if (
            chunk.kind == ChunkKind.NARRATIVE_TEXT
            and len(text) < MIN_CHARS_MEANINGFUL
            and len(text.split()) < MIN_WORD_COUNT
        ):
            # Regarder si le prochain chunk est aussi NARRATIVE
            next_narrative = None
            for j in range(i + 1, len(chunks)):
                if chunks[j].text.strip():
                    if chunks[j].kind == ChunkKind.NARRATIVE_TEXT:
                        next_narrative = j
                    break

            if next_narrative is not None:
                # Accumuler comme préfixe pour le prochain NARRATIVE
                if pending_prefix:
                    pending_prefix = f"{pending_prefix}\n{text}"
                else:
                    pending_prefix = text
                stats.merged_into_next += 1
                continue

        # Si on a un préfixe en attente et que ce chunk est NARRATIVE, fusionner
        if pending_prefix and chunk.kind == ChunkKind.NARRATIVE_TEXT:
            # Créer un chunk modifié avec le préfixe
            merged_chunk = chunk.model_copy(
                update={"text": f"{pending_prefix}\n{text}"}
            )
            merged.append(merged_chunk)
            pending_prefix = None
            continue

        # Préfixe en attente mais chunk non-NARRATIVE → drop le préfixe
        if pending_prefix:
            # Le préfixe ne peut pas fusionner, on le compte comme trop court
            stats.dropped_too_short += 1
            pending_prefix = None

        merged.append(chunk)

    # Préfixe final non fusionné
    if pending_prefix:
        stats.dropped_too_short += 1

    # Phase 2 : Filtrage qualité sur les chunks restants
    result: List[TypeAwareChunk] = []
    for chunk in merged:
        if _is_chunk_usable(chunk):
            result.append(chunk)
        else:
            text = chunk.text.strip()
            if not text:
                stats.dropped_empty += 1
            elif len(text.split()) < MIN_WORD_COUNT:
                stats.dropped_no_words += 1
            else:
                stats.dropped_too_short += 1

    stats.kept = len(result)
    return result, stats


MIN_AUTONOMOUS_CHARS = 100
"""Seuil minimum de contenu pour qu'un chunk soit autonome (post-rechunking)."""


def _consolidate_by_section(
    chunks: List[TypeAwareChunk],
    target_chars: int = 1500,
) -> List[TypeAwareChunk]:
    """
    Fusionne les chunks adjacents dans la meme section, quel que soit leur type.

    Resout le probleme des "orphan facts" : un chunk NARRATIVE de 52 chars
    ("SPAM/SAINT patch 71 required") suivi d'un chunk TABLE de 393 chars
    dans la meme section sont fusionnes en un seul chunk de 445 chars.

    Args:
        chunks: Chunks filtres, tries par ordre de lecture
        target_chars: Taille maximale d'un chunk consolide

    Returns:
        Liste de chunks consolides (potentiellement moins nombreux)
    """
    if not chunks:
        return []

    consolidated = []
    current = None

    for chunk in chunks:
        if current is None:
            current = chunk
            continue

        # Fusionner si :
        # 1. Meme section ET la somme reste sous target_chars
        # 2. OU un NARRATIVE court reference un tableau ("table below")
        #    et le chunk suivant est un TABLE (plafond 3000 chars)
        same_section = (
            current.section_id
            and chunk.section_id
            and current.section_id == chunk.section_id
        )
        combined_len = len(current.text) + len(chunk.text) + 2

        # Fix B : detecter un NARRATIVE qui reference un tableau suivi d'un TABLE
        narrative_refs_table = (
            current.kind == ChunkKind.NARRATIVE_TEXT
            and chunk.kind == ChunkKind.TABLE_TEXT
            and len(current.text) < 500
            and any(
                ref in current.text.lower()
                for ref in [
                    "table below", "following table", "table above",
                    "see the table", "shown in the table", "see table",
                    "tableau ci-dessous", "tableau suivant",
                    "as follows:", "listed below", "as shown below",
                ]
            )
            and combined_len <= MAX_ATOMIC_TABLE_CHARS
        )

        # Fix cross-page tables : deux TABLE_TEXT consecutifs sur pages adjacentes
        # avec meme structure de colonnes (meme nombre de | par ligne de donnees)
        cross_page_table = False
        if (
            current.kind == ChunkKind.TABLE_TEXT
            and chunk.kind == ChunkKind.TABLE_TEXT
            and combined_len <= MAX_ATOMIC_TABLE_CHARS
        ):
            cur_page = current.page_span_max or current.page_no
            next_page = chunk.page_span_min or chunk.page_no
            if next_page - cur_page <= 1:  # Pages adjacentes ou meme page
                # Verifier que le nombre de colonnes est compatible
                def _count_cols(text: str) -> int:
                    for line in text.split("\n"):
                        line = line.strip()
                        if line.startswith("|") and not _TABLE_SEP_RE.match(line):
                            return line.count("|") - 1
                    return 0
                cur_cols = _count_cols(current.text)
                next_cols = _count_cols(chunk.text)
                if cur_cols > 0 and cur_cols == next_cols:
                    cross_page_table = True

        if (
            (same_section and combined_len <= target_chars)
            or narrative_refs_table
            or cross_page_table
        ):
            # Fusionner : concatener les textes avec separateur
            separator = "\n\n" if current.kind != chunk.kind else "\n"
            next_text = chunk.text

            # Pour les tables cross-page, retirer le header duplique du second
            # fragment (le premier chunk a deja le header)
            if cross_page_table:
                lines = next_text.split("\n")
                # Retirer le prefixe contextuel [Document:...] s'il y en a un
                start_idx = 0
                for li, line in enumerate(lines):
                    if line.strip().startswith("[Document:"):
                        start_idx = li + 2  # skip prefix + blank line
                        continue
                    break
                # Retirer header + separator du second fragment
                cleaned_lines = []
                header_skipped = False
                for line in lines[start_idx:]:
                    if not header_skipped:
                        if _TABLE_SEP_RE.match(line.strip()):
                            header_skipped = True
                            continue
                        elif _TABLE_ROW_RE.match(line.strip()):
                            continue  # Skip header row
                        else:
                            header_skipped = True  # Pas de header, garder tout
                    cleaned_lines.append(line)
                next_text = "\n".join(cleaned_lines)

            merged_text = current.text + separator + next_text

            # Le kind du chunk fusionne = celui du plus long
            merged_kind = current.kind if len(current.text) >= len(chunk.text) else chunk.kind

            # Fusionner les item_ids
            merged_items = list(current.item_ids or []) + list(chunk.item_ids or [])

            # Page span
            page_min = min(
                current.page_span_min or current.page_no,
                chunk.page_span_min or chunk.page_no,
            )
            page_max = max(
                current.page_span_max or current.page_no,
                chunk.page_span_max or chunk.page_no,
            )

            current = current.model_copy(update={
                "text": merged_text,
                "kind": merged_kind,
                "item_ids": merged_items,
                "page_span_min": page_min,
                "page_span_max": page_max,
            })
        else:
            consolidated.append(current)
            current = chunk

    if current is not None:
        consolidated.append(current)

    merged_count = len(chunks) - len(consolidated)
    if merged_count > 0:
        logger.info(
            f"[OSMOSE:Rechunker] Section consolidation: {len(chunks)} → {len(consolidated)} "
            f"({merged_count} fusionne cross-type)"
        )

    return consolidated


def _force_merge_tiny(
    sub_chunks: List[SubChunk],
    min_autonomous: int = MIN_AUTONOMOUS_CHARS,
) -> List[SubChunk]:
    """
    Post-pass : fusionne tout SubChunk < min_autonomous chars avec son voisin le plus proche.

    Filet de securite pour les chunks qui passent entre les mailles du rechunker.

    Args:
        sub_chunks: SubChunks issus de la decoupe
        min_autonomous: Seuil minimum de contenu (defaut 100 chars)

    Returns:
        Liste de SubChunks tous >= min_autonomous (sauf si aucun voisin)
    """
    if len(sub_chunks) <= 1:
        return sub_chunks

    result = []
    i = 0
    while i < len(sub_chunks):
        sc = sub_chunks[i]

        if len(sc.text.strip()) < min_autonomous and i + 1 < len(sub_chunks):
            # Fusionner avec le chunk suivant
            next_sc = sub_chunks[i + 1]
            merged_text = sc.text.strip() + "\n" + next_sc.text
            merged_items = list(sc.item_ids or []) + list(next_sc.item_ids or [])

            merged = SubChunk(
                chunk_id=next_sc.chunk_id,
                sub_index=next_sc.sub_index,
                text=merged_text,
                parent_chunk_id=next_sc.parent_chunk_id,
                section_id=next_sc.section_id or sc.section_id,
                doc_id=sc.doc_id,
                tenant_id=sc.tenant_id,
                kind=next_sc.kind if len(next_sc.text) > len(sc.text) else sc.kind,
                page_no=sc.page_no,
                page_span_min=min(sc.page_span_min or sc.page_no, next_sc.page_span_min or next_sc.page_no),
                page_span_max=max(sc.page_span_max or sc.page_no, next_sc.page_span_max or next_sc.page_no),
                item_ids=merged_items,
                text_origin=next_sc.text_origin or sc.text_origin,
            )
            result.append(merged)
            i += 2  # Skip both
        else:
            result.append(sc)
            i += 1

    merged_count = len(sub_chunks) - len(result)
    if merged_count > 0:
        logger.info(
            f"[OSMOSE:Rechunker] Force-merge tiny: {len(sub_chunks)} → {len(result)} "
            f"({merged_count} chunks < {min_autonomous} chars fusionne)"
        )

    return result


def _filter_noise_chunks(sub_chunks: List[SubChunk]) -> List[SubChunk]:
    """
    Etape 5 (Fix C) : supprime les sub-chunks sans valeur semantique.

    Criteres d'exclusion :
    - Contenu reel < 80 chars (apres retrait du prefixe contextuel)
    - Ratio alphanumerique < 50% (flowcharts ASCII, separateurs)
    - Tables vides (header markdown sans donnees)
    - Metadata-only (uniquement des numeros de section)
    """
    result: List[SubChunk] = []
    for sc in sub_chunks:
        text = sc.text
        # Retirer le prefixe contextuel pour evaluer le contenu reel
        content = text
        if content.startswith("[Document:"):
            bracket_end = content.find("]\n\n")
            if bracket_end > 0:
                content = content[bracket_end + 3:]
        content = content.strip()

        # 1. Contenu trop court
        if len(content) < 80:
            continue

        # 2. Ratio alphanumerique trop bas (flowcharts ASCII, bruit)
        alnum = sum(1 for c in content if c.isalnum())
        if len(content) > 0 and alnum / len(content) < 0.35:
            continue

        # 3. Table vide (header + separator sans donnees)
        if sc.kind == "TABLE_TEXT" or ("|" in content and content.count("|") > 4):
            data_lines = [
                l for l in content.split("\n")
                if l.strip()
                and "|" in l
                and not _TABLE_SEP_RE.match(l)
            ]
            if len(data_lines) <= 1:
                continue

        # 4. Metadata-only (uniquement des numeros de section)
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if lines and all(
            re.match(r'^(\d+\.)+\d*\s', l) or len(l) < 25
            for l in lines
        ):
            continue

        result.append(sc)

    return result


def rechunk_for_retrieval(
    chunks: List[TypeAwareChunk],
    tenant_id: str,
    doc_id: str,
    target_chars: int = 1500,
    overlap_chars: int = 200,
    section_titles: Optional[dict] = None,
) -> List[SubChunk]:
    """
    Re-découpe les TypeAwareChunks en sous-chunks pour embeddings vectoriels.

    Pipeline V2 (4 etapes) :
    1. Filtrage qualite (existant) — supprime vides, trop courts, fusionne titres
    2. Consolidation par section (NOUVEAU) — fusionne cross-type dans meme section
    3. Decoupe avec overlap (existant) — sliding window target_chars avec overlap
    4. Force-merge tiny (NOUVEAU) — filet securite pour chunks < 100 chars

    Stratégie de coupe (3 niveaux):
    1. Fin de phrase (. ! ?) dans les 200 derniers chars de la fenêtre
    2. Fin de ligne (\\n) dans les 200 derniers chars
    3. Hard cut à target_chars (garantit terminaison)

    Args:
        chunks: Liste de TypeAwareChunks à re-découper
        tenant_id: ID du tenant
        doc_id: ID du document
        target_chars: Taille cible par sous-chunk
        overlap_chars: Chevauchement entre sous-chunks consécutifs
        section_titles: Dict section_id → titre lisible (optionnel)

    Returns:
        Liste de SubChunks prêts pour embedding
    """
    # --- Etape 1: Pré-filtrage qualité ---
    filtered_chunks, fstats = _filter_chunks(chunks)

    # --- Etape 2: Consolidation par section (cross-type merge) ---
    filtered_chunks = _consolidate_by_section(filtered_chunks, target_chars)

    dropped_total = fstats.total_input - fstats.kept
    if dropped_total > 0:
        logger.info(
            f"[OSMOSE:Rechunker] Filtrage qualité: {fstats.total_input} → {fstats.kept} chunks "
            f"(dropped: {fstats.dropped_empty} vides, {fstats.dropped_too_short} trop courts, "
            f"{fstats.dropped_no_words} sans mots, {fstats.merged_into_next} fusionnés)"
        )

    sub_chunks: List[SubChunk] = []

    for chunk in filtered_chunks:
        text = chunk.text
        text_len = len(text)

        # Chunk suffisamment court → 1 seul SubChunk
        if text_len <= target_chars:
            sub_chunks.append(SubChunk(
                chunk_id=chunk.chunk_id,
                sub_index=0,
                text=text,
                parent_chunk_id=chunk.chunk_id,
                section_id=chunk.section_id,
                doc_id=doc_id,
                tenant_id=tenant_id,
                kind=chunk.kind.value,
                page_no=chunk.page_no,
                page_span_min=chunk.page_span_min,
                page_span_max=chunk.page_span_max,
                item_ids=chunk.item_ids,
                text_origin=chunk.text_origin.value if chunk.text_origin else None,
            ))
            continue

        # Découpe en sous-chunks avec overlap
        # Detecter tous les blocs proteges (visuels, tables, listes)
        protected_blocks = _find_protected_blocks(text)
        sub_index = 0
        pos = 0

        def _emit_sub(sub_text: str):
            """Helper : emettre un sub-chunk."""
            nonlocal sub_index
            if sub_text.strip():
                sub_chunks.append(SubChunk(
                    chunk_id=chunk.chunk_id,
                    sub_index=sub_index,
                    text=sub_text,
                    parent_chunk_id=chunk.chunk_id,
                    section_id=chunk.section_id,
                    doc_id=doc_id,
                    tenant_id=tenant_id,
                    kind=chunk.kind.value,
                    page_no=chunk.page_no,
                    page_span_min=chunk.page_span_min,
                    page_span_max=chunk.page_span_max,
                    item_ids=chunk.item_ids,
                    text_origin=chunk.text_origin.value if chunk.text_origin else None,
                ))
                sub_index += 1

        while pos < text_len:
            # Fin de la fenêtre courante
            window_end = min(pos + target_chars, text_len)

            # Si on couvre le reste du texte, prendre tout
            if window_end >= text_len:
                sub_text = text[pos:]
                _emit_sub(sub_text)
                break

            # Stratégie de coupe à 3 niveaux
            search_start = max(pos, window_end - overlap_chars)

            # 1. Chercher une fin de phrase
            cut_pos = _find_sentence_break(text, search_start, window_end)

            # 2. Sinon, chercher un saut de ligne
            if cut_pos is None:
                cut_pos = _find_line_break(text, search_start, window_end)

            # 3. Hard cut fallback (garantit la terminaison)
            if cut_pos is None:
                cut_pos = window_end

            # INVARIANT : ne jamais couper a l'interieur d'un bloc protege
            block_skipped = False
            if protected_blocks:
                hit = _is_inside_protected_block(cut_pos, protected_blocks)
                if hit is not None:
                    block_start, block_end, block_type = hit
                    block_size = block_end - block_start

                    if block_type == "table" and block_size > MAX_ATOMIC_TABLE_CHARS:
                        # Table trop grande : couper AVANT, puis emettre
                        # le table avec header replay
                        if block_start > pos + MIN_CHARS_MEANINGFUL:
                            # Emettre le texte avant le tableau
                            _emit_sub(text[pos:block_start])
                        # Extraire le prefixe contextuel du chunk pour le replay
                        ctx_prefix = ""
                        if text.startswith("[Document:"):
                            pfx_end = text.find("]\n\n")
                            if pfx_end > 0:
                                ctx_prefix = text[:pfx_end + 3]
                        # Emettre les fragments du tableau avec header replay
                        table_text = text[block_start:block_end]
                        fragments = _split_table_with_header_replay(
                            table_text, ctx_prefix, target_chars
                        )
                        for frag in fragments:
                            _emit_sub(frag)
                        pos = block_end
                        continue

                    elif block_start > pos + MIN_CHARS_MEANINGFUL:
                        # Couper AVANT le bloc protege
                        cut_pos = block_start
                        block_skipped = True
                    else:
                        # Le bloc commence trop pres — l'inclure entier
                        cut_pos = block_end

            sub_text = text[pos:cut_pos]
            _emit_sub(sub_text)

            # Avancer
            new_pos = pos + len(sub_text)
            if new_pos <= pos:
                new_pos = pos + 1

            if block_skipped:
                # Pas d'overlap arriere apres une coupe forcee par bloc protege
                pos = new_pos
            elif new_pos < text_len:
                pos = max(new_pos - overlap_chars, pos + 1)
            else:
                pos = new_pos

    # --- Etape 4: Force-merge tiny (filet de securite) ---
    sub_chunks = _force_merge_tiny(sub_chunks, min_autonomous=MIN_AUTONOMOUS_CHARS)

    # --- Etape 5: Filtre post-rechunking (Fix C) ---
    # Eliminer les chunks sans valeur semantique :
    # - ASCII flowcharts / diagrammes textuels (ratio alphanum < 50%)
    # - Tables vides (header sans donnees)
    # - Metadata-only (uniquement des numeros de section)
    before_filter = len(sub_chunks)
    sub_chunks = _filter_noise_chunks(sub_chunks)
    noise_removed = before_filter - len(sub_chunks)

    # --- Propager section_title si disponible ---
    if section_titles:
        for sc in sub_chunks:
            if sc.section_id and sc.section_id in section_titles:
                sc.section_title = section_titles[sc.section_id]

    logger.info(
        f"[OSMOSE:Rechunker] {len(chunks)} chunks (→ {fstats.kept} après filtrage) "
        f"→ {len(sub_chunks)} sub-chunks (target={target_chars}, overlap={overlap_chars})"
        + (f", {noise_removed} noise removed" if noise_removed else "")
    )

    return sub_chunks
