"""
Service pour analyser des documents samples et suggérer entity types.

Phase 6 - Document Types Management
"""
import json
from typing import List, Dict, Optional
from fastapi import UploadFile
from pathlib import Path
import tempfile

from knowbase.common.llm_router import LLMRouter, TaskType
from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

settings = get_settings()
logger = setup_logging(settings.logs_dir, "document_sample_analyzer.log")


class DocumentSampleAnalyzerService:
    """Service pour analyser documents samples et suggérer entity types."""

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        """
        Initialize service.

        Args:
            llm_router: Router LLM (optionnel, créé si None)
        """
        self.llm_router = llm_router or LLMRouter()

    async def analyze_document_sample(
        self,
        file: UploadFile,
        context_prompt: Optional[str] = None,
        model_preference: str = "claude-sonnet"
    ) -> Dict:
        """
        Analyser un document sample pour suggérer entity types.

        Args:
            file: Fichier uploadé (PPTX ou PDF)
            context_prompt: Contexte additionnel pour guider le LLM
            model_preference: Modèle LLM à utiliser

        Returns:
            Dict avec suggested_types, document_summary, pages_analyzed
        """
        logger.info(f"📄 Analyse document sample: {file.filename}")

        # Extraire contenu du document
        content = await self._extract_document_content(file)

        if not content:
            logger.warning("⚠️ Aucun contenu extrait du document")
            return {
                "suggested_types": [],
                "document_summary": "Impossible d'extraire le contenu du document",
                "pages_analyzed": 0
            }

        # Construire prompt pour LLM
        prompt = self._build_analysis_prompt(content, context_prompt)

        # Appeler LLM
        try:
            messages = [
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            response = self.llm_router.complete(
                task_type=TaskType.METADATA_EXTRACTION,
                messages=messages,
                temperature=0.3,  # Température moyenne pour équilibre
                max_tokens=4000,
                model_preference=model_preference
            )

            # Parser réponse LLM
            result = self._parse_llm_response(response)

            logger.info(
                f"✅ Analyse terminée: {len(result['suggested_types'])} types suggérés"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Erreur analyse LLM: {e}")
            raise

    async def _extract_document_content(self, file: UploadFile) -> str:
        """
        Extraire contenu textuel du document.

        Args:
            file: Fichier uploadé

        Returns:
            Contenu textuel extrait
        """
        file_ext = Path(file.filename).suffix.lower()

        # Sauvegarder temporairement le fichier
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)

        try:
            if file_ext == ".pdf":
                return await self._extract_pdf_content(tmp_path)
            elif file_ext in [".pptx", ".ppt"]:
                return await self._extract_pptx_content(tmp_path)
            else:
                logger.warning(f"⚠️ Format non supporté: {file_ext}")
                return ""
        finally:
            # Nettoyer fichier temporaire
            if tmp_path.exists():
                tmp_path.unlink()

    async def _extract_pdf_content(self, pdf_path: Path) -> str:
        """Extraire contenu d'un PDF."""
        try:
            from knowbase.ingestion.pipelines.pdf_pipeline import extract_text_from_pdf

            # Extraire texte (limiter à 10 premières pages pour analyse)
            text_parts = []
            pages = extract_text_from_pdf(str(pdf_path), max_pages=10)

            for page_num, page_text in pages:
                if page_text.strip():
                    text_parts.append(f"--- Page {page_num} ---\n{page_text}")

            return "\n\n".join(text_parts)

        except Exception as e:
            logger.error(f"❌ Erreur extraction PDF: {e}")
            return ""

    async def _extract_pptx_content(self, pptx_path: Path) -> str:
        """Extraire contenu d'un PPTX."""
        try:
            from pptx import Presentation

            prs = Presentation(str(pptx_path))
            text_parts = []

            # Limiter à 10 premières slides
            for i, slide in enumerate(prs.slides[:10], start=1):
                slide_text_parts = []

                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text_parts.append(shape.text)

                if slide_text_parts:
                    text_parts.append(
                        f"--- Slide {i} ---\n" + "\n".join(slide_text_parts)
                    )

            return "\n\n".join(text_parts)

        except Exception as e:
            logger.error(f"❌ Erreur extraction PPTX: {e}")
            return ""

    def _build_analysis_prompt(
        self,
        document_content: str,
        context_prompt: Optional[str] = None
    ) -> str:
        """
        Construire prompt LLM pour analyse.

        Args:
            document_content: Contenu du document
            context_prompt: Contexte additionnel

        Returns:
            Prompt formaté
        """
        # Limiter taille du contenu (max 8000 chars)
        content_preview = document_content[:8000]
        if len(document_content) > 8000:
            content_preview += "\n\n[... contenu tronqué ...]"

        prompt = f"""Tu es un expert en analyse de documents et modélisation d'entités.

**TÂCHE**: Analyser ce document et identifier les types d'entités pertinents pour l'extraction automatique.

{"**CONTEXTE ADDITIONNEL**:\n" + context_prompt + "\n" if context_prompt else ""}
**DOCUMENT À ANALYSER**:
{content_preview}

**INSTRUCTIONS**:
1. Identifie les types d'entités principaux présents dans ce document
2. Pour chaque type identifié:
   - Donne un nom en MAJUSCULES et SNAKE_CASE (ex: SOLUTION, PRODUCT, INFRASTRUCTURE)
   - Estime une confidence (0.0 à 1.0) selon la fréquence et l'importance
   - Fournis 2-4 exemples concrets trouvés dans le document
   - Donne une brève description du type (1 phrase)

3. **RÈGLES CRITIQUES**:
   - Ne propose que des types d'entités **réellement présents** dans le document
   - Privilégie les types avec forte occurrence (confidence > 0.6)
   - Évite les types trop génériques (ex: "INFORMATION", "ELEMENT")
   - Utilise des noms descriptifs et métier (ex: "DATABASE" plutôt que "DATA")
   - Maximum 15 types suggérés

4. **RÉSUMÉ**: Fournis aussi un résumé du document en 2-3 phrases

**FORMAT DE SORTIE JSON**:
{{
  "document_summary": "Ce document présente...",
  "suggested_types": [
    {{
      "name": "SOLUTION",
      "confidence": 0.95,
      "examples": ["SAP HANA", "SAP S/4HANA Cloud", "SAP SuccessFactors"],
      "description": "Solutions logicielles SAP mentionnées dans le document"
    }},
    {{
      "name": "INFRASTRUCTURE",
      "confidence": 0.85,
      "examples": ["Cloud Platform", "On-Premise Server", "Hybrid Architecture"],
      "description": "Composants d'infrastructure technique"
    }}
  ]
}}

Retourne UNIQUEMENT le JSON, sans texte avant/après.
"""
        return prompt

    def _parse_llm_response(self, llm_response: str) -> Dict:
        """
        Parser réponse LLM.

        Args:
            llm_response: Réponse brute LLM

        Returns:
            Dict avec suggested_types, document_summary, pages_analyzed
        """
        try:
            # Nettoyer réponse (supprimer markdown code blocks si présents)
            clean_response = llm_response.strip()
            if clean_response.startswith("```json"):
                clean_response = clean_response[7:]
            if clean_response.startswith("```"):
                clean_response = clean_response[3:]
            if clean_response.endswith("```"):
                clean_response = clean_response[:-3]

            clean_response = clean_response.strip()

            # Parser JSON
            data = json.loads(clean_response)

            # Valider structure
            suggested_types = data.get("suggested_types", [])
            document_summary = data.get("document_summary", "")

            # Valider chaque type suggéré
            validated_types = []
            for item in suggested_types:
                if not isinstance(item, dict):
                    continue

                # Champs requis
                if "name" not in item or "confidence" not in item:
                    continue

                # Normaliser nom (UPPERCASE)
                item["name"] = item["name"].upper().strip()

                # Valider confidence
                try:
                    item["confidence"] = float(item["confidence"])
                    if not (0.0 <= item["confidence"] <= 1.0):
                        item["confidence"] = 0.5
                except (TypeError, ValueError):
                    item["confidence"] = 0.5

                # Assurer que examples est une liste
                if "examples" not in item or not isinstance(item["examples"], list):
                    item["examples"] = []

                # Assurer que description existe
                if "description" not in item:
                    item["description"] = ""

                validated_types.append(item)

            # Trier par confidence décroissant
            validated_types.sort(key=lambda x: x["confidence"], reverse=True)

            logger.info(f"✅ {len(validated_types)} types validés depuis réponse LLM")

            return {
                "suggested_types": validated_types,
                "document_summary": document_summary,
                "pages_analyzed": 10  # Max pages analysées
            }

        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur parsing JSON LLM: {e}")
            logger.error(f"Réponse LLM: {llm_response[:500]}")
            raise ValueError(f"LLM response is not valid JSON: {e}")

        except Exception as e:
            logger.error(f"❌ Erreur parsing réponse LLM: {e}")
            raise


__all__ = ["DocumentSampleAnalyzerService"]
