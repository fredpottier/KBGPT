"""
Service pour analyser des documents samples et suggérer entity types.

Phase 6 - Document Types Management
"""
import json
import base64
from typing import List, Dict, Optional
from fastapi import UploadFile
from pathlib import Path
import tempfile

from knowbase.common.llm_router import LLMRouter, TaskType, get_llm_router
from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

settings = get_settings()
logger = setup_logging(settings.logs_dir, "document_sample_analyzer.log")


class DocumentSampleAnalyzerService:
    """Service pour analyser documents samples et suggérer entity types."""

    def __init__(self, llm_router: Optional[LLMRouter] = None, db_session=None):
        """
        Initialize service.

        Args:
            llm_router: Router LLM (optionnel, créé si None)
            db_session: Session DB pour récupérer entity types existants
        """
        self.llm_router = llm_router or get_llm_router()
        self.db_session = db_session

    async def analyze_document_sample(
        self,
        file: UploadFile,
        context_prompt: Optional[str] = None,
        model_preference: str = "claude-sonnet",
        tenant_id: str = "default"
    ) -> Dict:
        """
        Analyser un document sample PDF pour suggérer entity types.

        Args:
            file: Fichier PDF uploadé
            context_prompt: Contexte additionnel pour guider le LLM
            model_preference: Modèle LLM à utiliser (doit être Claude)
            tenant_id: Tenant ID pour récupérer entity types existants

        Returns:
            Dict avec suggested_types, document_summary, pages_analyzed
        """
        logger.info(f"📄 Analyse document sample: {file.filename}")

        # Vérifier que c'est bien un PDF
        file_ext = Path(file.filename).suffix.lower()
        if file_ext != ".pdf":
            raise ValueError(f"Format non supporté: {file_ext}. Seul PDF est accepté.")

        # Récupérer entity types existants approuvés
        existing_types = self._get_existing_entity_types(tenant_id)
        logger.info(f"📋 {len(existing_types)} entity types existants trouvés")

        # Lire le PDF en base64
        pdf_content = await file.read()
        pdf_size_mb = len(pdf_content) / (1024 * 1024)

        # Validation basique du PDF
        if not pdf_content.startswith(b'%PDF-'):
            raise ValueError(
                f"Le fichier n'est pas un PDF valide (header manquant). "
                f"Veuillez vérifier que le fichier n'est pas corrompu."
            )

        # Vérifier taille fichier (Claude limite: 32 MB pour requête totale)
        # Recommandation: PDF < 10 MB pour laisser de la marge
        if pdf_size_mb > 10:
            raise ValueError(
                f"PDF trop volumineux: {pdf_size_mb:.2f} MB. "
                f"Limite recommandée: 10 MB (limite Claude: 32 MB pour requête totale). "
                f"Veuillez réduire le nombre de pages ou compresser le PDF."
            )

        pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
        logger.info(f"📦 PDF encodé: {pdf_size_mb:.2f} MB ({len(pdf_base64)} caractères base64)")

        # Construire prompt pour LLM
        prompt_text = self._build_analysis_prompt_for_pdf(context_prompt, existing_types)

        # Appeler Claude avec PDF natif
        # IMPORTANT: Le format 'document' PDF est spécifique à Anthropic Claude
        # On doit bypasser le router et appeler directement Claude
        try:
            from knowbase.common.clients import get_anthropic_client

            anthropic_client = get_anthropic_client()

            # Format Anthropic pour PDF natif
            # Utiliser le modèle long_text de settings (Claude Sonnet)
            model_name = settings.model_long_text
            logger.info(f"🤖 Utilisation modèle Claude: {model_name}")

            response = anthropic_client.messages.create(
                model=model_name,
                max_tokens=4000,
                temperature=0.3,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt_text
                            }
                        ]
                    }
                ]
            )

            # Extraire contenu de la réponse Claude
            llm_response = response.content[0].text if response.content else ""

            # Log tokens
            if response.usage:
                logger.info(f"[TOKENS] Claude PDF Analysis - Input: {response.usage.input_tokens}, Output: {response.usage.output_tokens}")
                try:
                    from knowbase.common.token_tracker import track_tokens
                    track_tokens(
                        model=model_name,
                        task_type="pdf_analysis",
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        context="document_sample_analyzer",
                    )
                except Exception:
                    pass

            # Parser réponse LLM
            result = self._parse_llm_response(llm_response, existing_types)

            logger.info(
                f"✅ Analyse terminée: {len(result['suggested_types'])} types suggérés"
            )

            return result

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Erreur analyse LLM: {e}")

            # Message d'erreur plus explicite pour erreurs courantes
            if "Could not process PDF" in error_msg:
                raise ValueError(
                    f"Claude n'a pas pu traiter le PDF. Causes possibles:\n"
                    f"1. PDF corrompu ou mal formé\n"
                    f"2. PDF trop complexe (trop d'images haute résolution)\n"
                    f"3. PDF protégé par mot de passe\n"
                    f"Suggestions:\n"
                    f"- Ré-exporter le PDF depuis l'original\n"
                    f"- Réduire la résolution des images\n"
                    f"- Limiter à 50-60 pages maximum\n"
                    f"- Essayer avec un PDF plus simple pour tester"
                ) from e
            elif "exceeds" in error_msg.lower() or "limit" in error_msg.lower():
                raise ValueError(
                    f"Le PDF dépasse les limites de Claude (max 100 pages, 32 MB total).\n"
                    f"Taille actuelle: {pdf_size_mb:.2f} MB\n"
                    f"Veuillez réduire le nombre de pages ou compresser le PDF."
                ) from e
            else:
                raise

    def _get_existing_entity_types(self, tenant_id: str = "default") -> List[str]:
        """
        Récupérer les entity types existants approuvés depuis la base.

        Args:
            tenant_id: Tenant ID

        Returns:
            Liste des noms de types approuvés
        """
        if not self.db_session:
            logger.warning("⚠️ Pas de session DB, impossible de récupérer entity types existants")
            return []

        try:
            from knowbase.db import EntityTypeRegistry

            # Requête pour récupérer types approuvés
            types = self.db_session.query(EntityTypeRegistry).filter(
                EntityTypeRegistry.tenant_id == tenant_id,
                EntityTypeRegistry.status == "approved"
            ).all()

            return [t.type_name for t in types]

        except Exception as e:
            logger.error(f"❌ Erreur récupération entity types existants: {e}")
            return []

    def _build_analysis_prompt_for_pdf(
        self,
        context_prompt: Optional[str] = None,
        existing_types: Optional[List[str]] = None
    ) -> str:
        """
        Construire prompt LLM pour analyse de PDF.

        Args:
            context_prompt: Contexte additionnel
            existing_types: Liste des entity types déjà existants en base

        Returns:
            Prompt formaté
        """
        # Formater liste types existants
        existing_types_section = ""
        if existing_types:
            types_list = ", ".join(existing_types)
            existing_types_section = f"""
**TYPES D'ENTITÉS DÉJÀ EXISTANTS** (à privilégier si pertinents):
{types_list}

IMPORTANT: Si un type existe déjà dans cette liste, utilise-le tel quel (même nom exact).
Propose de NOUVEAUX types uniquement si aucun type existant ne convient.
"""

        context_section = ""
        if context_prompt:
            context_section = f"**CONTEXTE ADDITIONNEL**:\n{context_prompt}\n\n"

        prompt = f"""Tu es un expert en analyse de documents et modélisation d'entités.

**TÂCHE**: Analyser le document PDF fourni et identifier les types d'entités pertinents pour l'extraction automatique.
{existing_types_section}
{context_section}
**INSTRUCTIONS**:
1. Analyse le document PDF complet (texte + images + mise en page)
2. **EN PRIORITÉ**: Vérifie si des types EXISTANTS (listés ci-dessus) sont pertinents
3. Propose de NOUVEAUX types uniquement si nécessaire
4. Pour chaque type identifié:
   - Donne un nom en MAJUSCULES (ex: SOLUTION, PRODUCT, INFRASTRUCTURE)
   - Estime une confidence (0.0 à 1.0) selon la fréquence et l'importance
   - Fournis 2-4 exemples concrets trouvés dans le document
   - Donne une brève description du type (1 phrase)
   - Indique "is_existing": true si le type est dans la liste existante, false sinon

5. **RÈGLES CRITIQUES**:
   - Réutilise les types existants EXACTEMENT (même nom, même casse)
   - Ne propose que des types **réellement présents** dans le document
   - Privilégie les types avec forte occurrence (confidence > 0.6)
   - Évite les types trop génériques (ex: "INFORMATION", "ELEMENT")
   - Maximum 15 types suggérés

6. **RÉSUMÉ**: Fournis aussi un résumé du document en 2-3 phrases

**FORMAT DE SORTIE JSON**:
{{
  "document_summary": "Ce document présente...",
  "suggested_types": [
    {{
      "name": "SOLUTION",
      "confidence": 0.95,
      "examples": ["SAP HANA", "SAP S/4HANA Cloud"],
      "description": "Solutions logicielles SAP mentionnées",
      "is_existing": true
    }},
    {{
      "name": "DEPLOYMENT_MODEL",
      "confidence": 0.85,
      "examples": ["Cloud Native", "Hybrid Deployment"],
      "description": "Modèles de déploiement mentionnés",
      "is_existing": false
    }}
  ],
  "suggested_context_prompt": "Prompt optimisé pour l'ingestion future de documents similaires"
}}

7. **PROMPT OPTIMISÉ GÉNÉRALISTE**: En te basant sur ton analyse approfondie du document:
   - Génère un prompt contextuel GÉNÉRALISTE pour l'analyse FUTURE de documents similaires
   - Ce prompt sera injecté lors de l'ingestion de TOUT document de ce type (pas seulement ce sample)
   - Il doit capturer la NATURE et la STRUCTURE du document, pas son contenu spécifique

   **RÈGLES CRITIQUES pour le prompt généraliste**:
   - ❌ NE PAS mentionner les sujets/thèmes spécifiques du document sample (ex: "sécurité", "AWS", "cloud")
   - ✅ Décrire la CATÉGORIE de document (ex: "documentation technique", "architecture", "processus métier")
   - ✅ Mentionner les TYPES D'ENTITÉS généraux attendus (SOLUTION, INFRASTRUCTURE, COMPONENT, etc.)
   - ✅ Décrire les PATTERNS VISUELS typiques (diagrammes, tableaux, workflows, etc.)
   - ✅ Indiquer les TYPES DE RELATIONS générales (INTEGRATES_WITH, PART_OF, USES, etc.)

   **EXEMPLE de prompt TROP SPÉCIFIQUE (à éviter)**:
   "Document sur sécurité cloud AWS. Extraire SOLUTION SAP, INFRASTRUCTURE AWS/Azure, SECURITY_CONTROL."

   **EXEMPLE de prompt GÉNÉRALISTE (à suivre)**:
   "Documentation technique présentant des architectures et infrastructures système. Extraire prioritairement les entités SOLUTION, INFRASTRUCTURE, COMPONENT, TECHNOLOGY, et leurs relations INTEGRATES_WITH, PART_OF, USES. Attention aux diagrammes d'architecture, spécifications techniques, et topologies réseau."

   - Format du prompt (3-5 phrases max):
     1. Nature/catégorie du document (technique/fonctionnel/marketing)
     2. Types d'entités généraux prioritaires
     3. Relations générales attendues
     4. Patterns visuels/structurels typiques

Retourne UNIQUEMENT le JSON, sans texte avant/après.
"""
        return prompt

    def _parse_llm_response(self, llm_response: str, existing_types: Optional[List[str]] = None) -> Dict:
        """
        Parser réponse LLM.

        Args:
            llm_response: Réponse brute LLM
            existing_types: Liste des types existants pour validation

        Returns:
            Dict avec suggested_types, document_summary, pages_analyzed
        """
        existing_types_set = set(existing_types) if existing_types else set()
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
            suggested_context_prompt = data.get("suggested_context_prompt", "")

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

                # Valider et forcer is_existing basé sur existing_types_set
                # (pour éviter que le LLM ne se trompe)
                if item["name"] in existing_types_set:
                    item["is_existing"] = True
                else:
                    item["is_existing"] = False

                validated_types.append(item)

            # Trier par confidence décroissant
            validated_types.sort(key=lambda x: x["confidence"], reverse=True)

            logger.info(f"✅ {len(validated_types)} types validés depuis réponse LLM")

            return {
                "suggested_types": validated_types,
                "document_summary": document_summary,
                "suggested_context_prompt": suggested_context_prompt,
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
