"""
OntologyGeneratorService - Génération d'ontologie via LLM.

Phase 5B - Solution 3 Hybride
Step 2 - Génération ontologie depuis entités existantes

Utilise Claude Sonnet (configurable) pour analyser entités d'un type
et proposer groupes sémantiques + aliases.
"""
import json
from typing import Dict, List, Optional
from datetime import datetime

from knowbase.common.llm_router import LLMRouter
from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

settings = get_settings()
logger = setup_logging(settings.logs_dir, "ontology_generator.log")


class OntologyGeneratorService:
    """Service de génération d'ontologie via LLM."""

    def __init__(self, llm_router: Optional[LLMRouter] = None):
        """
        Initialize service.

        Args:
            llm_router: Router LLM (optionnel, créé si None)
        """
        self.llm_router = llm_router or LLMRouter()

    async def generate_ontology_from_entities(
        self,
        entity_type: str,
        entities: List[Dict],
        model_preference: str = "claude-sonnet"
    ) -> Dict:
        """
        Génère ontologie depuis liste d'entités via LLM.

        Analyse les entités pour détecter:
        - Groupes sémantiquement identiques
        - Canonical name optimal pour chaque groupe
        - Aliases (variantes détectées)
        - Confidence score

        Args:
            entity_type: Type des entités (ex: "SOLUTION")
            entities: Liste dicts avec keys: uuid, name, description, etc.
            model_preference: Modèle LLM à utiliser (default: claude-sonnet)

        Returns:
            Dict avec structure:
            {
                "entity_type": "SOLUTION",
                "generated_at": "2025-10-06T...",
                "entities_analyzed": 47,
                "groups_proposed": 12,
                "ontology": {
                    "SAP_S4HANA_PRIVATE_CLOUD": {
                        "canonical_name": "SAP S/4HANA Private Cloud Edition",
                        "aliases": ["SAP S/4HANA PCE", "S/4HANA Private Cloud"],
                        "confidence": 0.95,
                        "entities_merged": ["uuid-1", "uuid-2", "uuid-3"],
                        "description": "SAP's private cloud ERP solution"
                    },
                    ...
                }
            }
        """
        logger.info(
            f"🤖 Génération ontologie pour type={entity_type}, "
            f"{len(entities)} entités, model={model_preference}"
        )

        if len(entities) == 0:
            logger.warning("Aucune entité fournie, ontologie vide")
            return {
                "entity_type": entity_type,
                "generated_at": datetime.utcnow().isoformat(),
                "entities_analyzed": 0,
                "groups_proposed": 0,
                "ontology": {}
            }

        # Construire prompt pour LLM
        prompt = self._build_clustering_prompt(entity_type, entities)

        # Appeler LLM
        try:
            response = await self.llm_router.complete(
                prompt=prompt,
                model_preference=model_preference,
                temperature=0.2,  # Faible température pour cohérence
                max_tokens=4000
            )

            # Parser réponse LLM
            ontology_data = self._parse_llm_response(response, entities)

            result = {
                "entity_type": entity_type,
                "generated_at": datetime.utcnow().isoformat(),
                "entities_analyzed": len(entities),
                "groups_proposed": len(ontology_data),
                "ontology": ontology_data
            }

            logger.info(
                f"✅ Ontologie générée: {len(ontology_data)} groupes "
                f"depuis {len(entities)} entités"
            )

            return result

        except Exception as e:
            logger.error(f"❌ Erreur génération ontologie: {e}")
            raise

    def _build_clustering_prompt(
        self,
        entity_type: str,
        entities: List[Dict]
    ) -> str:
        """
        Construit prompt LLM pour clustering.

        Args:
            entity_type: Type entités
            entities: Liste entités

        Returns:
            Prompt formaté
        """
        # Limiter à 100 entités max pour prompt (token limits)
        entities_sample = entities[:100]

        entities_text = "\n".join([
            f"- {i+1}. \"{e['name']}\" (uuid: {e['uuid']}, description: {e.get('description', 'N/A')})"
            for i, e in enumerate(entities_sample)
        ])

        prompt = f"""Tu es un expert en ontologies et classification sémantique.

**Tâche**: Analyser les entités de type "{entity_type}" ci-dessous et identifier les groupes sémantiquement identiques.

**Entités à analyser** ({len(entities_sample)} sur {len(entities)}):
{entities_text}

**Instructions**:
1. Identifie les entités qui représentent **exactement la même chose** (synonymes, variantes, typos)
2. Pour chaque groupe identifié:
   - Choisis le **canonical_name** (le nom le plus formel, complet, et couramment utilisé)
   - Liste tous les **aliases** (variantes détectées)
   - Donne un **confidence score** (0.0 à 1.0) selon ta certitude du regroupement
   - Liste les **UUIDs** des entités à merger
   - Ajoute une brève **description** du concept

3. **Règles importantes**:
   - Ne groupe que si tu es >75% sûr qu'elles sont identiques
   - Préserve les différences subtiles (ex: "SAP S/4HANA Cloud" ≠ "SAP S/4HANA Private Cloud")
   - Gère les typos courantes (ex: "S/4 HANA" vs "S/4HANA")
   - Respecte la casse pour acronymes (SAP, ERP, etc.)

**Format de sortie JSON attendu**:
```json
{{
  "CANONICAL_KEY_1": {{
    "canonical_name": "Nom Officiel Complet",
    "aliases": ["Variante 1", "Variante 2"],
    "confidence": 0.95,
    "entities_merged": ["uuid-1", "uuid-2"],
    "description": "Description courte du concept"
  }},
  "CANONICAL_KEY_2": {{
    ...
  }}
}}
```

**Important**: Retourne UNIQUEMENT le JSON, sans texte avant/après.
"""

        return prompt

    def _parse_llm_response(
        self,
        llm_response: str,
        original_entities: List[Dict]
    ) -> Dict:
        """
        Parse réponse LLM en structure ontologie.

        Args:
            llm_response: Réponse brute LLM
            original_entities: Entités originales (pour validation UUIDs)

        Returns:
            Dict ontologie parsée
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
            ontology_data = json.loads(clean_response)

            # Valider structure
            valid_uuids = {e['uuid'] for e in original_entities}

            for key, entry in ontology_data.items():
                # Vérifier champs requis
                required_fields = ["canonical_name", "aliases", "confidence", "entities_merged"]
                for field in required_fields:
                    if field not in entry:
                        logger.warning(f"Champ manquant '{field}' dans groupe {key}")
                        entry[field] = [] if field == "aliases" or field == "entities_merged" else 0.5

                # Filtrer UUIDs invalides
                entry["entities_merged"] = [
                    uuid for uuid in entry["entities_merged"]
                    if uuid in valid_uuids
                ]

                # S'assurer que confidence est float
                try:
                    entry["confidence"] = float(entry["confidence"])
                except (TypeError, ValueError):
                    entry["confidence"] = 0.5

            logger.info(f"✅ Ontologie parsée: {len(ontology_data)} groupes valides")

            return ontology_data

        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur parsing JSON LLM: {e}")
            logger.error(f"Réponse LLM: {llm_response[:500]}")
            raise ValueError(f"LLM response is not valid JSON: {e}")

        except Exception as e:
            logger.error(f"❌ Erreur parsing réponse LLM: {e}")
            raise

    def enrich_ontology_with_metadata(
        self,
        ontology: Dict,
        entity_type: str
    ) -> str:
        """
        Enrichit ontologie avec métadonnées et convertit en YAML.

        Args:
            ontology: Dict ontologie
            entity_type: Type entités

        Returns:
            Contenu YAML formaté
        """
        import yaml

        # Construire structure YAML
        yaml_data = {
            "entity_type_name": entity_type,
            "entity_type_status": "approved",
            "description": f"Ontologie générée automatiquement pour {entity_type}",
            "generated_at": datetime.utcnow().isoformat(),
            "entities": {}
        }

        for key, entry in ontology.items():
            yaml_data["entities"][key] = {
                "canonical_name": entry["canonical_name"],
                "aliases": entry.get("aliases", []),
                "description": entry.get("description", ""),
                "confidence": entry.get("confidence", 0.0)
            }

        yaml_output = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return yaml_output


__all__ = ["OntologyGeneratorService"]
