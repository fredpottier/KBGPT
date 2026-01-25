"""
Chunker Simple pour le POC

Decoupe le texte en chunks avec chevauchement.
Version simplifiee pour le POC (pas de semantique).
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass
import re


@dataclass
class Chunk:
    """Un chunk de texte avec metadata"""
    id: str
    text: str
    start_char: int
    end_char: int
    page_hint: int = 0  # Estimation de la page


class SimpleChunker:
    """
    Chunker simple base sur la taille.
    Respecte les limites de phrases.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        overlap: int = 200,
        min_chunk_size: int = 100
    ):
        """
        Args:
            chunk_size: Taille cible des chunks (caracteres)
            overlap: Chevauchement entre chunks
            min_chunk_size: Taille minimale d'un chunk
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_chunk_size = min_chunk_size

    def chunk(self, text: str, doc_id: str = "doc") -> Tuple[List[Chunk], Dict[str, str]]:
        """
        Decoupe le texte en chunks.

        Args:
            text: Texte a decouper
            doc_id: Identifiant du document

        Returns:
            (list_of_chunks, chunks_dict)
            chunks_dict: mapping chunk_id -> text pour validation anchors
        """
        if not text.strip():
            return [], {}

        # Decouper en phrases
        sentences = self._split_into_sentences(text)

        chunks = []
        chunks_dict = {}
        current_text = ""
        current_start = 0
        chunk_idx = 0
        char_pos = 0

        for sentence in sentences:
            if len(current_text) + len(sentence) <= self.chunk_size:
                current_text += sentence
            else:
                # Sauvegarder le chunk actuel
                if len(current_text) >= self.min_chunk_size:
                    chunk_id = f"{doc_id}_chunk_{chunk_idx:03d}"
                    chunk = Chunk(
                        id=chunk_id,
                        text=current_text,
                        start_char=current_start,
                        end_char=current_start + len(current_text),
                        page_hint=self._estimate_page(current_start, len(text))
                    )
                    chunks.append(chunk)
                    chunks_dict[chunk_id] = current_text
                    chunk_idx += 1

                # Nouveau chunk avec overlap
                overlap_text = self._get_overlap(current_text)
                current_start = current_start + len(current_text) - len(overlap_text)
                current_text = overlap_text + sentence

        # Dernier chunk
        if len(current_text) >= self.min_chunk_size:
            chunk_id = f"{doc_id}_chunk_{chunk_idx:03d}"
            chunk = Chunk(
                id=chunk_id,
                text=current_text,
                start_char=current_start,
                end_char=current_start + len(current_text),
                page_hint=self._estimate_page(current_start, len(text))
            )
            chunks.append(chunk)
            chunks_dict[chunk_id] = current_text

        return chunks, chunks_dict

    def _split_into_sentences(self, text: str) -> List[str]:
        """Decoupe le texte en phrases"""
        # Pattern simple pour fin de phrase
        pattern = r'(?<=[.!?])\s+'
        sentences = re.split(pattern, text)

        # Garder les espaces
        result = []
        for s in sentences:
            if s.strip():
                result.append(s + ' ')

        return result

    def _get_overlap(self, text: str) -> str:
        """Retourne les derniers caracteres pour overlap"""
        if len(text) <= self.overlap:
            return text

        # Essayer de couper sur une fin de phrase
        overlap_zone = text[-self.overlap * 2:]
        sentences = self._split_into_sentences(overlap_zone)

        if len(sentences) > 1:
            # Prendre la derniere phrase complete
            return sentences[-1]

        return text[-self.overlap:]

    def _estimate_page(self, char_pos: int, total_chars: int) -> int:
        """Estime le numero de page (approx 3000 chars/page)"""
        chars_per_page = 3000
        return char_pos // chars_per_page + 1

    def get_text_for_anchor(
        self,
        chunks_dict: Dict[str, str],
        chunk_id: str,
        start_char: int,
        end_char: int
    ) -> str:
        """
        Recupere le texte pour un anchor.

        Args:
            chunks_dict: Mapping chunk_id -> text
            chunk_id: ID du chunk
            start_char: Position debut dans le chunk
            end_char: Position fin dans le chunk

        Returns:
            Le texte extrait ou chaine vide si invalide
        """
        if chunk_id not in chunks_dict:
            return ""

        text = chunks_dict[chunk_id]
        if start_char < 0 or end_char > len(text) or start_char >= end_char:
            return ""

        return text[start_char:end_char]
