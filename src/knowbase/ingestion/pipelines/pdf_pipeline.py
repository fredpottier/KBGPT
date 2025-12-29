import base64
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from knowbase.common.logging import setup_logging

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from pdf2image import convert_from_path
from qdrant_client.models import PointStruct
from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_qdrant_client,
    get_sentence_transformer,
)
from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.ingestion.extraction_cache import get_cache_manager

from knowbase.config.paths import ensure_directories
from knowbase.config.settings import get_settings


# =========================
# Path resolution
# =========================
settings = get_settings()

DATA_ROOT = settings.data_dir
DOCS_IN = settings.docs_in_dir
DOCS_DONE = settings.docs_done_dir
SLIDES_PNG = settings.slides_dir / "pdf"
STATUS_DIR = settings.status_dir
LOGS_DIR = settings.logs_dir
MODELS_DIR = settings.models_dir


def ensure_dirs():
    ensure_directories([
        DOCS_IN,
        DOCS_DONE,
        SLIDES_PNG,
        STATUS_DIR,
        LOGS_DIR,
        MODELS_DIR,
    ])


ensure_dirs()

# =============================
# Configuration & initialisation
# =============================
COLLECTION_NAME = settings.qdrant_collection
GPT_MODEL = settings.gpt_model
MODEL_NAME = os.getenv("PDF_EMB_MODEL", settings.embeddings_model)
PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")


# ====================
# Logging
# ====================
logger = setup_logging(LOGS_DIR, "ingest_pdf_debug.log", enable_console=True)


def banner_paths():
    def exists_dir(p: Path) -> str:
        return f"{p}  (exists={p.exists()}, is_dir={p.is_dir()})"

    logger.info("=== PDF INGEST START ===")
    logger.info(f"DATA_ROOT:    {exists_dir(DATA_ROOT)}")
    logger.info(f"DOCS_IN:      {exists_dir(DOCS_IN)}")
    logger.info(f"DOCS_DONE:    {exists_dir(DOCS_DONE)}")
    logger.info(f"SLIDES_PNG:   {exists_dir(SLIDES_PNG)}")
    logger.info(f"STATUS_DIR:   {exists_dir(STATUS_DIR)}")
    logger.info(f"LOGS_DIR:     {exists_dir(LOGS_DIR)}")
    logger.info(f"MODELS_DIR:   {exists_dir(MODELS_DIR)}")
    logger.info(f"PUBLIC_URL:   {PUBLIC_URL}")


# Note: banner_paths() est appelé dans process_pdf() si nécessaire, pas au niveau module
# pour éviter la création du fichier de log au démarrage

# ===================
# Clients & Models
# ===================
# Note: get_llm_router() retourne le singleton avec support Burst Mode
qdrant_client = get_qdrant_client()
model = get_sentence_transformer(MODEL_NAME)
EMB_SIZE = model.get_sentence_embedding_dimension() or 1024
ensure_qdrant_collection(COLLECTION_NAME, int(EMB_SIZE))

# ==============
# Utilities
# ==============
def clean_gpt_response(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```json"):
        s = s[len("```json") :].strip()
    if s.startswith("```"):
        s = s[len("```") :].strip()
    if s.endswith("```"):
        s = s[:-3].strip()
    return s


def encode_image_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_text_from_pdf(pdf_path: Path) -> str:
    txt_output = pdf_path.with_suffix(".txt")
    logger.info(f"📑 pdftotext: {pdf_path.name}")
    try:
        import subprocess

        # Supprimer les warnings stderr (comme "Invalid Font Weight") qui polluent les logs
        subprocess.run(
            ["pdftotext", str(pdf_path), str(txt_output)],
            check=True,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        logger.error(f"❌ pdftotext failed: {e}")
        return ""
    text = ""
    try:
        text = txt_output.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"⚠️ Could not read {txt_output}: {e}")
    logger.debug(f"Extracted text length: {len(text)}")
    return text


# ==================
# Pipeline Steps
# ==================
def analyze_pdf_metadata(pdf_text: str, source_name: str) -> dict:
    logger.info(f"🔍 GPT: analyse des métadonnées — {source_name}")
    try:
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are a metadata extraction assistant.",
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": (
                f"You're analyzing a PDF document: '{source_name}'.\n"
                f"Below is the raw text extracted from it:\n\n{pdf_text[:8000]}\n\n"
                "Extract the following high-level metadata and return a single JSON object with fields:\n"
                "- title\n- objective\n- main_solution\n- supporting_solutions\n"
                "- mentioned_solutions\n- document_type\n- audience\n- source_date\n- language\n\n"
                "IMPORTANT: For the field 'main_solution', always use the official SAP canonical solution name as published on the SAP website or documentation. "
                "Do not use acronyms, abbreviations, or local variants. If the document uses a non-canonical name, map it to the official SAP name. "
                "If you are unsure, leave the field empty."
            ),
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        raw = get_llm_router().complete(TaskType.METADATA_EXTRACTION, messages)
        cleaned = clean_gpt_response(raw)
        meta = json.loads(cleaned) if cleaned else {}
        logger.debug(
            f"META (keys): {list(meta.keys()) if isinstance(meta, dict) else 'n/a'}"
        )
        return meta if isinstance(meta, dict) else {}
    except Exception as e:
        logger.error(f"❌ GPT metadata error: {e}")
        return {}


def ask_gpt_page_analysis_text_only(
    page_text: str,
    source_name: str,
    page_index: int,
    custom_prompt: str | None = None,
):
    """
    Analyse une page PDF en utilisant uniquement le texte extrait, sans Vision.
    Plus rapide et moins coûteux que la version avec Vision.
    Retourne une structure unifiée avec concepts, facts, entities, relations (comme PPTX).
    """
    logger.info(f"🧠 GPT [TEXT-ONLY]: analyse page {page_index}")
    try:
        # Détecter la langue du contenu (simple heuristique basée sur mots courants)
        content_lower = page_text.lower()
        english_indicators = ['the ', ' and ', ' is ', ' are ', ' to ', ' of ', ' in ', ' for ', ' with ', ' that ']
        french_indicators = [' le ', ' la ', ' les ', ' et ', ' est ', ' sont ', ' de ', ' dans ', ' pour ', ' avec ', ' que ']

        english_count = sum(content_lower.count(word) for word in english_indicators)
        french_count = sum(content_lower.count(word) for word in french_indicators)

        detected_language = "ENGLISH" if english_count > french_count else "FRENCH"
        logger.debug(f"Page {page_index}: Langue détectée = {detected_language} (EN:{english_count} vs FR:{french_count})")

        # Instructions de langue (forcer anglais pour Neo4j)
        language_instructions = (
            f"⚠️ CRITICAL LANGUAGE INSTRUCTIONS (DETECTED CONTENT LANGUAGE: {detected_language}):\n"
            f"- For ENTITIES and RELATIONS: ALWAYS use ENGLISH for entity names, relation types, and entity descriptions (for Knowledge Graph consistency)\n"
            f"- For CONCEPTS and FACTS: Use {detected_language} (the language of the actual content below, NOT the context description)\n"
            f"- IMPORTANT: Ignore any French/English text in context descriptions above - only look at the ACTUAL CONTENT language below\n\n"
        )

        # Utiliser custom_prompt si fourni, sinon prompt par défaut
        if custom_prompt:
            analysis_text = language_instructions + custom_prompt.replace("{slide_content}", page_text).replace("{slide_index}", str(page_index)).replace("{source_name}", source_name)
        else:
            # Prompt étendu pour extraire concepts, facts, entities, relations (format unifié comme PPTX)
            analysis_text = (
                language_instructions +
                f"You are analyzing page {page_index} from '{source_name}'.\n"
                f"Page content:\n{page_text}\n\n"
                "Extract structured knowledge from this page and return a JSON object with 4 keys:\n"
                "- `concepts`: Array of concept blocks, each with:\n"
                "  - `full_explanation`: string (detailed description)\n"
                "  - `meta`: object with `type`, `level`, `topic`\n"
                "- `facts`: Array of factual statements, each with:\n"
                "  - `subject`: string\n"
                "  - `predicate`: string\n"
                "  - `value`: string/number\n"
                "  - `confidence`: number (0-1)\n"
                "  - `fact_type`: string (optional)\n"
                "- `entities`: Array of named entities, each with:\n"
                "  - `name`: string\n"
                "  - `entity_type`: string (e.g., 'Product', 'Company', 'Technology')\n"
                "  - `description`: string (optional)\n"
                "- `relations`: Array of relationships between entities, each with:\n"
                "  - `source`: string (entity name)\n"
                "  - `relation_type`: string\n"
                "  - `target`: string (entity name)\n"
                "  - `description`: string (optional)\n\n"
                "Return only valid JSON."
            )

        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You are an expert assistant that analyzes document content deeply. "
                "Extract concepts, facts, entities, and relations from text. "
                "CRITICAL: For entities/relations use ENGLISH. For concepts/facts use source document language."
            ),
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": analysis_text,
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]

        # Utiliser TaskType.LONG_TEXT_SUMMARY au lieu de VISION (LLM plus rapide et moins coûteux)
        raw = get_llm_router().complete(TaskType.LONG_TEXT_SUMMARY, messages, temperature=0.2, max_tokens=8000)
        logger.debug(f"Page {page_index} [TEXT-ONLY]: LLM raw response (first 500 chars): {raw[:500] if raw else 'EMPTY'}")

        cleaned = clean_gpt_response(raw)
        logger.debug(f"Page {page_index} [TEXT-ONLY]: cleaned response (first 500 chars): {cleaned[:500] if cleaned else 'EMPTY'}")

        # Parser la réponse JSON
        response_data = json.loads(cleaned) if cleaned else {}

        # Support format unifié 4 outputs
        if isinstance(response_data, dict):
            concepts = response_data.get("concepts", [])
            facts_data = response_data.get("facts", [])
            entities_data = response_data.get("entities", [])
            relations_data = response_data.get("relations", [])
        elif isinstance(response_data, list):
            # Fallback: ancien format (liste de chunks)
            concepts = response_data
            facts_data = []
            entities_data = []
            relations_data = []
        else:
            logger.warning(f"Page {page_index} [TEXT-ONLY]: Format JSON inattendu: {type(response_data)}")
            concepts = []
            facts_data = []
            entities_data = []
            relations_data = []

        logger.debug(f"Page {page_index} [TEXT-ONLY]: {len(concepts)} concepts + {len(facts_data)} facts + {len(entities_data)} entities + {len(relations_data)} relations")

        return {
            "concepts": concepts,
            "facts": facts_data,
            "entities": entities_data,
            "relations": relations_data,
        }
    except Exception as e:
        logger.error(f"❌ GPT page {page_index} [TEXT-ONLY] error: {e}")
        return {
            "concepts": [],
            "facts": [],
            "entities": [],
            "relations": [],
        }


def ask_gpt_block_analysis_text_only(
    block_content: str,
    block_type: str,
    block_title: str | None,
    source_name: str,
    block_index: int,
    custom_prompt: str | None = None,
):
    """
    Analyse un BLOC SÉMANTIQUE (section, paragraph, table, list) extrait par MegaParse.
    Plus intelligent que l'analyse page par page car travaille sur des unités cohérentes.

    Args:
        block_content: Texte du bloc sémantique
        block_type: Type du bloc ("section", "paragraph", "table", "list")
        block_title: Titre du bloc (si section)
        source_name: Nom du document source
        block_index: Index du bloc dans le document
        custom_prompt: Prompt personnalisé (optionnel)

    Returns:
        Dict avec 4 clés: concepts, facts, entities, relations
    """
    logger.info(f"🧠 LLM [KNOWLEDGE_EXTRACTION]: analyse bloc #{block_index} [{block_type}]")

    try:
        # Détecter la langue du contenu (simple heuristique basée sur mots courants)
        content_lower = block_content.lower()
        english_indicators = ['the ', ' and ', ' is ', ' are ', ' to ', ' of ', ' in ', ' for ', ' with ', ' that ']
        french_indicators = [' le ', ' la ', ' les ', ' et ', ' est ', ' sont ', ' de ', ' dans ', ' pour ', ' avec ', ' que ']

        english_count = sum(content_lower.count(word) for word in english_indicators)
        french_count = sum(content_lower.count(word) for word in french_indicators)

        detected_language = "ENGLISH" if english_count > french_count else "FRENCH"
        logger.debug(f"Bloc {block_index}: Langue détectée = {detected_language} (EN:{english_count} vs FR:{french_count})")

        # Instructions de langue (toujours appliquées, même avec custom_prompt)
        language_instructions = (
            f"⚠️ CRITICAL LANGUAGE INSTRUCTIONS (DETECTED CONTENT LANGUAGE: {detected_language}):\n"
            f"- For ENTITIES and RELATIONS: ALWAYS use ENGLISH for entity names, relation types, and entity descriptions (for Knowledge Graph consistency)\n"
            f"- For CONCEPTS and FACTS: Use {detected_language} (the language of the actual content below, NOT the context description)\n"
            f"- IMPORTANT: Ignore any French/English text in context descriptions above - only look at the ACTUAL CONTENT language below\n"
            f"- Example: If content is in English, write 'Security awareness training is essential...' NOT 'La formation à la sensibilisation...'\n\n"
        )

        # Prompt adapté au type de bloc
        if custom_prompt:
            # Utiliser le prompt personnalisé du document type avec préfixe langue
            analysis_text = (
                language_instructions +
                custom_prompt
                .replace("{slide_content}", block_content)
                .replace("{slide_index}", str(block_index))
                .replace("{source_name}", source_name)
            )
        else:
            # Prompt par défaut optimisé pour blocs sémantiques
            block_context = f"Block type: {block_type}"
            if block_title:
                block_context += f"\nBlock title: {block_title}"

            analysis_text = (
                language_instructions +
                f"You are analyzing a semantic block (block #{block_index}) from '{source_name}'.\n"
                f"{block_context}\n\n"
                f"Block content:\n{block_content}\n\n"
                "Extract structured knowledge from this semantic block and return a JSON object with 4 keys:\n\n"
                "1. `concepts`: Array of concept blocks (main ideas, explanations, definitions)\n"
                "   Each concept object:\n"
                "   - `full_explanation`: string (detailed description of the concept)\n"
                "   - `meta`: object with:\n"
                "     - `type`: string (e.g., 'definition', 'process', 'architecture', 'feature')\n"
                "     - `level`: number (importance: 1=critical, 2=important, 3=detail)\n"
                "     - `topic`: string (main topic/domain)\n\n"
                "2. `facts`: Array of factual statements\n"
                "   Each fact object:\n"
                "   - `subject`: string (what the fact is about)\n"
                "   - `predicate`: string (the relationship or property)\n"
                "   - `value`: string/number (the value or target)\n"
                "   - `confidence`: number (0-1, how certain is this fact)\n"
                "   - `fact_type`: string (e.g., 'specification', 'requirement', 'statistic')\n\n"
                "3. `entities`: Array of named entities (products, technologies, companies, etc.)\n"
                "   Each entity object:\n"
                "   - `name`: string (canonical name)\n"
                "   - `entity_type`: string (e.g., 'SOLUTION', 'COMPONENT', 'TECHNOLOGY', 'PRODUCT')\n"
                "   - `description`: string (brief description, optional)\n\n"
                "4. `relations`: Array of relationships between entities\n"
                "   Each relation object:\n"
                "   - `source`: string (MUST match exactly the 'name' of an entity in the 'entities' array above)\n"
                "   - `relation_type`: string (use semantic types like PART_OF, CONTAINS, USES, REQUIRES, IMPLEMENTS, SUPPORTS, EXTENDS, MENTIONS, INTEGRATES_WITH, DEPENDS_ON, REPLACES, PROVIDES)\n"
                "   - `target`: string (MUST match exactly the 'name' of an entity in the 'entities' array above)\n"
                "   - `description`: string (optional context explaining the relationship)\n\n"
                "CRITICAL INSTRUCTIONS FOR RELATIONS:\n"
                "- **ONLY create relations BETWEEN entities you listed in 'entities'** - both 'source' and 'target' must exist in your entities list\n"
                "- If two concepts are related but one is not an entity you identified, DO NOT create a relation\n"
                "- Extract ALL relationships that are **explicitly stated or clearly implied** in the text\n"
                "- Only create relations that you can justify from the source content - DO NOT invent connections\n"
                "- Common relation patterns to look for:\n"
                "  * If 'X is part of Y' or 'Y includes X' → create (X, PART_OF, Y)\n"
                "  * If 'X uses Y' or 'X requires Y' → create (X, USES/REQUIRES, Y)\n"
                "  * If 'X and Y' mentioned together in same context → create (X, MENTIONS, Y)\n"
                "  * If 'X replaces Y' or 'X is successor of Y' → create (X, REPLACES, Y)\n"
                "- It's OK if some entities have no relations if they're truly standalone mentions\n"
                "- Quality over quantity: 1 accurate relation is better than 3 invented ones\n"
                "- When in doubt, use MENTIONS for co-occurring entities rather than inventing a specific relation type\n\n"
                "IMPORTANT:\n"
                "- This is a SEMANTIC BLOCK, not just a random page. Extract knowledge that is COMPLETE within this block.\n"
                "- Focus on concepts that are fully explained in this block.\n"
                "- Extract all entities mentioned, even if they appear in relations.\n"
                "- Relations should connect entities that are both mentioned in this block or the broader document context.\n"
                "- Be thorough: extract ALL concepts, facts, entities, and relations present.\n"
                "- Remember: Accuracy is paramount. Only extract what you can verify from the text.\n\n"
                "Return ONLY valid JSON (no markdown, no code blocks)."
            )

        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You are an expert knowledge extraction assistant specialized in analyzing technical and business documents. "
                "Your task is to extract structured knowledge (concepts, facts, entities, relations) from semantic blocks. "
                "CRITICAL LANGUAGE RULE: For entities and relations, ALWAYS use ENGLISH (for Knowledge Graph consistency). "
                "For concepts and facts, use the source document's language (for semantic search accuracy). "
                "Focus on ACCURACY first, then completeness. Extract relationships that are clearly stated or logically implied in the text. "
                "IMPORTANT: Only create relations BETWEEN entities you identified - both source and target must exist in your entities list. "
                "Only create relations you can justify from the source content - never invent connections. "
                "When entities appear together in context, use MENTIONS relation as a safe default. "
                "Prefer quality over quantity: accurate extraction builds trust in the knowledge graph. "
                "Always return valid JSON with all 4 keys, even if some arrays are empty."
            ),
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": analysis_text,
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]

        # Log du prompt pour debug (uniquement les 600 premiers chars)
        logger.debug(f"Bloc {block_index} [PROMPT]: {analysis_text[:600]}")

        # Utiliser TaskType.KNOWLEDGE_EXTRACTION (les paramètres viennent du YAML)
        raw = get_llm_router().complete(
            TaskType.KNOWLEDGE_EXTRACTION,
            messages
            # temperature et max_tokens sont définis dans config/llm_models.yaml
        )

        logger.debug(f"Bloc {block_index} [KNOWLEDGE_EXTRACTION]: LLM raw response (first 500 chars): {raw[:500] if raw else 'EMPTY'}")

        cleaned = clean_gpt_response(raw)
        response_data = json.loads(cleaned) if cleaned else {}

        # Parser la réponse
        if isinstance(response_data, dict):
            concepts = response_data.get("concepts", [])
            facts_data = response_data.get("facts", [])
            entities_data = response_data.get("entities", [])
            relations_data = response_data.get("relations", [])
        else:
            logger.warning(f"Bloc {block_index} [KNOWLEDGE_EXTRACTION]: Format JSON inattendu: {type(response_data)}")
            concepts = []
            facts_data = []
            entities_data = []
            relations_data = []

        logger.info(
            f"Bloc {block_index} [KNOWLEDGE_EXTRACTION]: "
            f"{len(concepts)} concepts + {len(facts_data)} facts + "
            f"{len(entities_data)} entities + {len(relations_data)} relations"
        )

        # TODO: Implémenter l'ingestion des facts, entities, relations dans Neo4j/Graphiti si activé
        # Pour l'instant, on retourne juste les concepts pour Qdrant (comme avant)

        return {
            "concepts": concepts,
            "facts": facts_data,
            "entities": entities_data,
            "relations": relations_data,
        }

    except Exception as e:
        logger.error(f"❌ LLM bloc {block_index} [KNOWLEDGE_EXTRACTION] error: {e}")
        return {
            "concepts": [],
            "facts": [],
            "entities": [],
            "relations": [],
        }


def transform_fact_for_neo4j(fact_data: dict) -> dict:
    """
    Transforme un fact extrait par LLM vers le format FactCreate Neo4j.

    Le LLM génère: {subject, predicate, value (string/number), confidence, fact_type (texte libre)}
    FactCreate attend: {subject, predicate, object (string), value (float), unit, fact_type (enum), ...}

    Args:
        fact_data: Dictionnaire du fact extrait par LLM

    Returns:
        Dict compatible avec FactCreate ou None si transformation impossible
    """
    import re

    subject = fact_data.get("subject", "").strip()
    predicate = fact_data.get("predicate", "").strip()
    raw_value = fact_data.get("value", "")
    confidence = float(fact_data.get("confidence", 0.8))
    llm_fact_type = fact_data.get("fact_type", "general").lower()

    if not subject or not predicate or not raw_value:
        return None

    # Convertir raw_value en string si ce n'est pas déjà le cas
    value_str = str(raw_value).strip()

    # Parser la valeur pour extraire nombre + unité
    # Exemples: "99.7%", "100 users", "5 GB", "enabled", "SAP HANA"
    numeric_value = 0.0
    unit = ""
    object_str = value_str
    value_type = "text"  # Par défaut

    # Tentative d'extraction de valeur numérique
    # Pattern: nombre (entier ou décimal) suivi optionnellement d'une unité
    number_pattern = r'^\s*(-?[\d,]+\.?\d*)\s*([%\w\s/]*?)\s*$'
    match = re.match(number_pattern, value_str)

    if match:
        try:
            # Extraire le nombre (enlever les virgules de séparation de milliers)
            num_str = match.group(1).replace(',', '')
            numeric_value = float(num_str)
            unit = match.group(2).strip() if match.group(2) else ""
            value_type = "numeric"
        except (ValueError, AttributeError):
            # Si échec de conversion, garder les valeurs par défaut
            numeric_value = 0.0
            unit = ""
            value_type = "text"

    # Si pas d'unité mais valeur numérique trouvée, mettre unité vide
    if value_type == "numeric" and not unit:
        unit = ""

    # Si pas de valeur numérique, mettre unité vide
    if value_type == "text":
        unit = ""

    # Mapper fact_type texte libre vers enum FactType
    # LLM génère: specification, requirement, statistic, feature, etc.
    # FactType enum: SERVICE_LEVEL, CAPACITY, PRICING, FEATURE, COMPLIANCE, GENERAL
    fact_type_mapping = {
        "service": "SERVICE_LEVEL",
        "sla": "SERVICE_LEVEL",
        "availability": "SERVICE_LEVEL",
        "uptime": "SERVICE_LEVEL",
        "capacity": "CAPACITY",
        "performance": "CAPACITY",
        "limit": "CAPACITY",
        "size": "CAPACITY",
        "storage": "CAPACITY",
        "pricing": "PRICING",
        "cost": "PRICING",
        "price": "PRICING",
        "fee": "PRICING",
        "feature": "FEATURE",
        "capability": "FEATURE",
        "functionality": "FEATURE",
        "compliance": "COMPLIANCE",
        "regulation": "COMPLIANCE",
        "standard": "COMPLIANCE",
        "certification": "COMPLIANCE",
        "requirement": "FEATURE",  # Les requirements sont souvent des features
        "specification": "FEATURE",
        "statistic": "GENERAL",
        "integration": "FEATURE",
    }

    fact_type_enum = "GENERAL"  # Par défaut
    for keyword, enum_value in fact_type_mapping.items():
        if keyword in llm_fact_type:
            fact_type_enum = enum_value
            break

    return {
        "subject": subject[:200],
        "predicate": predicate[:100],
        "object": object_str[:500],
        "value": numeric_value,
        "unit": unit[:50] if unit else "",
        "value_type": value_type,
        "fact_type": fact_type_enum,
        "confidence": min(max(confidence, 0.0), 1.0),
    }


def ingest_knowledge_to_neo4j(
    facts: list,
    entities: list,
    relations: list,
    document_id: str,
    source_name: str,
    tenant_id: str = "default"
) -> dict:
    """
    Ingère facts, entities et relations dans Neo4j.

    Args:
        facts: Liste des facts extraits
        entities: Liste des entities extraites
        relations: Liste des relations extraites
        document_id: ID du document source
        source_name: Nom du document source
        tenant_id: Tenant ID (défaut: "default")

    Returns:
        Dict avec statistiques d'ingestion
    """
    from knowbase.api.services.knowledge_graph_service import KnowledgeGraphService
    from knowbase.api.services.facts_service import FactsService
    from knowbase.api.schemas.knowledge_graph import EntityCreate, RelationCreate
    from knowbase.api.schemas.facts import FactCreate

    stats = {
        "entities_created": 0,
        "facts_created": 0,
        "relations_created": 0,
        "errors": 0
    }

    try:
        # Initialiser les services avec tenant_id
        kg_service = KnowledgeGraphService(tenant_id=tenant_id)
        facts_service = FactsService(tenant_id=tenant_id)

        # 1. Ingest entities
        for entity_data in entities:
            try:
                # Valider et normaliser les données
                name = entity_data.get("name", "").strip()
                entity_type = entity_data.get("entity_type", "UNKNOWN").strip().upper()
                description = entity_data.get("description", "")

                # Description min 10 chars requise par le schéma
                if not description or len(description) < 10:
                    description = f"{name} ({entity_type})"

                if not name or len(name) < 1:
                    logger.warning(f"⚠️ Entity skipped: name trop court")
                    continue

                entity_create = EntityCreate(
                    name=name,
                    entity_type=entity_type,
                    description=description[:500],  # Max 500 chars
                    source_document_id=document_id,
                    tenant_id=tenant_id
                )

                kg_service.create_entity(entity_create)
                stats["entities_created"] += 1

            except Exception as e:
                logger.debug(f"⚠️ Entity creation error: {e}")
                stats["errors"] += 1

        # 2. Ingest facts
        for fact_data in facts:
            try:
                # Transformer le fact du format LLM vers le format Neo4j
                transformed_fact = transform_fact_for_neo4j(fact_data)

                if not transformed_fact:
                    # Fact invalide, passer au suivant
                    continue

                fact_create = FactCreate(
                    subject=transformed_fact["subject"],
                    predicate=transformed_fact["predicate"],
                    object=transformed_fact["object"],
                    value=transformed_fact["value"],
                    unit=transformed_fact["unit"],
                    value_type=transformed_fact["value_type"],
                    fact_type=transformed_fact["fact_type"],
                    confidence=transformed_fact["confidence"],
                    source_document=source_name,
                    source_chunk_id=None,  # Peut être renseigné si disponible
                    extraction_method="llm_knowledge_extraction",
                    extraction_model="gpt-4o-mini"  # Correspond à la config
                )

                facts_service.create_fact(fact_create)
                stats["facts_created"] += 1

            except Exception as e:
                logger.debug(f"⚠️ Fact creation error: {e}")
                stats["errors"] += 1

        # 3. Ingest relations (filtrées : seulement entre entités identifiées)
        # Construire un set des noms d'entités pour vérification rapide
        entity_names_set = {e.get("name", "").strip() for e in entities if e.get("name")}

        for relation_data in relations:
            try:
                source = relation_data.get("source", "").strip()
                target = relation_data.get("target", "").strip()
                relation_type = relation_data.get("relation_type", "RELATED_TO").strip().upper()
                description = relation_data.get("description", "")

                if not source or not target:
                    continue

                # Vérifier que source ET target sont dans les entités identifiées
                # (le LLM devrait respecter cette règle grâce au prompt, mais on vérifie par sécurité)
                if source not in entity_names_set:
                    logger.debug(f"⚠️ Relation ignorée: source '{source}' n'est pas dans les entités identifiées")
                    stats["relations_skipped"] = stats.get("relations_skipped", 0) + 1
                    continue

                if target not in entity_names_set:
                    logger.debug(f"⚠️ Relation ignorée: target '{target}' n'est pas dans les entités identifiées")
                    stats["relations_skipped"] = stats.get("relations_skipped", 0) + 1
                    continue

                # Les deux entités existent dans la liste, créer la relation
                relation_create = RelationCreate(
                    source=source[:200],
                    target=target[:200],
                    relation_type=relation_type,
                    description=description[:500] if description else None,
                    source_document_id=document_id,
                    tenant_id=tenant_id
                )

                kg_service.create_relation(relation_create)
                stats["relations_created"] += 1

            except Exception as e:
                logger.debug(f"⚠️ Relation creation error: {e}")
                stats["errors"] += 1

        if stats["entities_created"] > 0 or stats["facts_created"] > 0 or stats["relations_created"] > 0:
            logger.info(
                f"📊 Neo4j: {stats['entities_created']} entities, "
                f"{stats['facts_created']} facts, {stats['relations_created']} relations "
                f"({stats['errors']} errors)"
            )

    except Exception as e:
        logger.error(f"❌ Neo4j ingestion error: {e}")
        stats["errors"] += 1

    return stats


def ask_gpt_slide_analysis(
    image_path: Path,
    slide_text: str,
    source_name: str,
    slide_index: int,
    custom_prompt: str | None = None,
):
    logger.info(f"🧠 GPT [VISION]: analyse page {slide_index}")
    try:
        image_b64 = encode_image_base64(image_path)

        # Détecter la langue du contenu (simple heuristique basée sur mots courants)
        content_lower = slide_text.lower()
        english_indicators = ['the ', ' and ', ' is ', ' are ', ' to ', ' of ', ' in ', ' for ', ' with ', ' that ']
        french_indicators = [' le ', ' la ', ' les ', ' et ', ' est ', ' sont ', ' de ', ' dans ', ' pour ', ' avec ', ' que ']

        english_count = sum(content_lower.count(word) for word in english_indicators)
        french_count = sum(content_lower.count(word) for word in french_indicators)

        detected_language = "ENGLISH" if english_count > french_count else "FRENCH"
        logger.debug(f"Page {slide_index} [VISION]: Langue détectée = {detected_language} (EN:{english_count} vs FR:{french_count})")

        # Instructions de langue (forcer anglais pour Neo4j)
        language_instructions = (
            f"⚠️ CRITICAL LANGUAGE INSTRUCTIONS (DETECTED CONTENT LANGUAGE: {detected_language}):\n"
            f"- For ENTITIES and RELATIONS: ALWAYS use ENGLISH for entity names, relation types, and entity descriptions (for Knowledge Graph consistency)\n"
            f"- For CONCEPTS and FACTS: Use {detected_language} (the language of the actual content below, NOT the context description)\n"
            f"- IMPORTANT: Ignore any French/English text in context descriptions above - only look at the ACTUAL CONTENT language below\n\n"
        )

        # Utiliser custom_prompt si fourni, sinon prompt par défaut
        if custom_prompt:
            analysis_text = language_instructions + custom_prompt.replace("{slide_content}", slide_text).replace("{slide_index}", str(slide_index)).replace("{source_name}", source_name)
        else:
            analysis_text = (
                language_instructions +
                f"You are analyzing page {slide_index} from '{source_name}'.\n"
                f"Page content:\n{slide_text}\n\n"
                "Extract 1–5 standalone content blocks. For each, return:\n"
                "- `text`\n- `meta` with `type`, `level`, `topic`\n\n"
                "Return only a JSON array."
            )

        prompt: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
                {
                    "type": "text",
                    "text": analysis_text,
                },
            ],
        }
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": (
                "You are an expert assistant that analyzes PDF pages. "
                "CRITICAL: For entities/relations use ENGLISH. For concepts/facts use source document language."
            ),
        }
        messages: list[ChatCompletionMessageParam] = [system_message, prompt]
        raw = get_llm_router().complete(TaskType.VISION, messages)
        logger.debug(f"Page {slide_index}: LLM raw response (first 500 chars): {raw[:500] if raw else 'EMPTY'}")
        cleaned = clean_gpt_response(raw)
        logger.debug(f"Page {slide_index}: cleaned response (first 500 chars): {cleaned[:500] if cleaned else 'EMPTY'}")
        data = json.loads(cleaned) if cleaned else []
        if not isinstance(data, list):
            logger.warning(f"Page {slide_index}: LLM returned non-list data, type={type(data)}")
            data = []
        logger.debug(f"Page {slide_index}: chunks returned = {len(data)}")
        return data
    except Exception as e:
        logger.error(f"❌ GPT page {slide_index} error: {e}")
        return []


def ingest_chunks(chunks, doc_metadata, file_uid, page_index):
    points = []
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        meta = chunk.get("meta", {}) or {}
        if not text or len(text) < 20:
            continue
        try:
            emb = model.encode([f"passage: {text}"], normalize_embeddings=True)[
                0
            ].tolist()
            payload = {
                "text": text,
                "language": "en",
                "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "gpt_chunked": True,
                "page_index": page_index,
                "page_image_url": f"{PUBLIC_URL}/static/pdf_slides/{file_uid}_page_{page_index}.png",
                "source_file_url": f"{PUBLIC_URL}/static/pdfs/{file_uid}.pdf",
            }
            payload.update(doc_metadata)
            payload.update(meta)
            points.append(
                PointStruct(id=str(uuid.uuid4()), vector=emb, payload=payload)
            )
        except Exception as e:
            logger.warning(f"⚠️ Embedding error (page {page_index}): {e}")

    if points:
        try:
            qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
            logger.info(f"✅ Page {page_index}: {len(points)} chunk(s) ingérés")
        except Exception as e:
            logger.error(f"❌ Qdrant upsert failed (page {page_index}): {e}")


def process_pdf(pdf_path: Path, document_type_id: str | None = None, use_vision: bool = False):
    # Reconfigurer logger pour le contexte RQ worker avec lazy file creation
    global logger
    logger = setup_logging(LOGS_DIR, "ingest_pdf_debug.log", enable_console=True)

    # Premier log réel - c'est ici que le fichier sera créé
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"🚀 Traitement: {pdf_path.name}")
    logger.info(f"📋 Document Type ID: {document_type_id or 'default'}")
    logger.info(f"🔍 Mode extraction: {'VISION (GPT-4 avec images)' if use_vision else 'TEXT-ONLY (LLM rapide)'}")
    status_file = STATUS_DIR / f"{pdf_path.stem}.status"
    try:
        status_file.write_text("processing")

        meta_path = pdf_path.with_suffix(".meta.json")
        user_meta = {}
        if meta_path.exists():
            try:
                user_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                logger.info("📎 Meta utilisateur détectée")
            except Exception as e:
                logger.warning(f"⚠️ Meta invalide: {e}")

        # Ajouter document_type_id aux métadonnées si fourni
        if document_type_id:
            user_meta["document_type_id"] = document_type_id

        # ===== V2.2: EXTRACTION CACHE SYSTEM =====
        # Détecter si fichier est un cache (.knowcache.json)
        cache_manager = get_cache_manager()
        loaded_from_cache = False
        extraction_start_time = datetime.now()

        if pdf_path.suffix == ".json" and pdf_path.name.endswith(".knowcache.json"):
            # Fichier est un cache → charger et skip extraction
            logger.info("🔄 [CACHE] Fichier .knowcache.json détecté, tentative chargement...")

            cache = cache_manager.load_cache(pdf_path)

            if cache:
                # Cache valide → utiliser texte cached
                full_text = cache.extracted_text.full_text
                doc_meta = {**user_meta, **{
                    "title": cache.document_metadata.title,
                    "pages": cache.document_metadata.pages,
                    "language": cache.document_metadata.language,
                    "author": cache.document_metadata.author,
                    "keywords": cache.document_metadata.keywords,
                    **cache.document_metadata.custom_metadata
                }}

                loaded_from_cache = True

                logger.info(
                    f"✅ [CACHE] Cache chargé: {len(full_text)} chars "
                    f"(économie: {cache.extraction_stats.duration_seconds:.1f}s, "
                    f"${cache.extraction_stats.cost_usd:.3f})"
                )

                # Skip toute la section extraction ci-dessous
            else:
                # Cache invalide/expiré
                logger.error("❌ [CACHE] Cache invalide ou expiré, import annulé")
                status_file.write_text("error")
                raise Exception("Cache invalide ou expiré")

        # Si pas de cache, continuer extraction normale
        if not loaded_from_cache:
            logger.info("📄 [EXTRACTION] Mode normal (pas de cache)")

            # En mode TEXT-ONLY, MegaParse extrait le texte (comme PPTX)
            # En mode VISION, on utilise pdftotext pour avoir le texte complet
            pdf_text = None
            if use_vision:
                pdf_text = extract_text_from_pdf(pdf_path)
                gpt_meta = analyze_pdf_metadata(pdf_text, pdf_path.name)
                doc_meta = {**user_meta, **gpt_meta}
            else:
                # En TEXT-ONLY, on extrait les métadonnées après MegaParse
                doc_meta = user_meta

        # Générer prompt contextualisé si document_type_id fourni
        custom_prompt = None
        if document_type_id:
            try:
                from knowbase.api.services.document_type_service import DocumentTypeService
                from knowbase.db import SessionLocal

                logger.info(f"🎯 Génération du prompt contextualisé pour document_type_id: {document_type_id}")
                session = SessionLocal()
                try:
                    doc_type_service = DocumentTypeService(session)
                    custom_prompt = doc_type_service.generate_extraction_prompt(
                        document_type_id=document_type_id,
                        slide_content="{slide_content}"
                    )
                    logger.info(f"✅ Prompt contextualisé généré ({len(custom_prompt)} caractères)")
                finally:
                    session.close()
            except Exception as e:
                logger.warning(f"⚠️ Impossible de générer le prompt contextualisé: {e}")
                custom_prompt = None

        # ===== OSMOSE PURE : Extraction texte UNIQUEMENT (pas d'analyse LLM) =====
        # Comme PPTX : Texte brut → OSMOSE fait toute l'analyse sémantique

        # FIX Phase 2.9: Ne pas écraser full_text si chargé depuis cache
        if not loaded_from_cache:
            full_text = None

        if not loaded_from_cache and use_vision:
            # ===== MODE VISION : Génération PNG + extraction texte basique =====
            logger.info("🖼️ [OSMOSE PURE] Mode VISION: Génération PNG des pages")
            images = convert_from_path(str(pdf_path))
            logger.info(f"✅ {len(images)} pages converties en images")

            # Sauvegarder images (pour futur usage Vision si nécessaire)
            for i, img in enumerate(images, start=1):
                img_path = SLIDES_PNG / f"{pdf_path.stem}_page_{i}.png"
                img.save(img_path, "PNG")

                if i % 10 == 0:
                    try:
                        from knowbase.ingestion.queue.jobs import send_worker_heartbeat
                        send_worker_heartbeat()
                    except Exception:
                        pass

            # Extraire texte complet via pdftotext (sans analyse LLM)
            if not pdf_text:
                pdf_text = extract_text_from_pdf(pdf_path)

            full_text = pdf_text

            # Extraction métadonnées uniquement
            if full_text and len(full_text) > 100:
                gpt_meta = analyze_pdf_metadata(full_text[:8000], pdf_path.name)
                doc_meta = {**user_meta, **gpt_meta}
            else:
                doc_meta = user_meta

            logger.info(f"✅ [OSMOSE PURE] Texte extrait: {len(full_text) if full_text else 0} chars (AUCUNE analyse LLM)")

        elif not loaded_from_cache:
            # ===== MODE TEXT-ONLY : MegaParse extraction uniquement =====
            from knowbase.ingestion.parsers.megaparse_pdf import parse_pdf_with_megaparse

            logger.info("📚 [OSMOSE PURE] Mode TEXT-ONLY: MegaParse extraction (pas d'analyse LLM)")

            try:
                semantic_blocks = parse_pdf_with_megaparse(pdf_path, use_vision=False)
                logger.info(f"✅ MegaParse: {len(semantic_blocks)} blocs sémantiques extraits")

                # Extraire le texte complet depuis les blocs (SANS analyse LLM)
                full_text = "\n\n".join(
                    f"--- {block.get('block_type', 'text')} ---\n{block.get('content', '')}"
                    for block in semantic_blocks
                    if block.get('content')
                )

                # Extraction métadonnées uniquement
                gpt_meta = analyze_pdf_metadata(full_text[:8000], pdf_path.name)
                doc_meta = {**user_meta, **gpt_meta}
                logger.info(f"✅ [OSMOSE PURE] Texte structuré extrait: {len(full_text)} chars (AUCUNE analyse LLM)")

            except Exception as e:
                logger.error(f"❌ MegaParse échoué: {e}")
                logger.warning("⚠️ Fallback: extraction texte via pdftotext")

                # Fallback pdftotext
                full_text = extract_text_from_pdf(pdf_path)
                if full_text and len(full_text) > 100:
                    gpt_meta = analyze_pdf_metadata(full_text[:8000], pdf_path.name)
                    doc_meta = {**user_meta, **gpt_meta}
                else:
                    doc_meta = user_meta

        # ===== V2.2: SAUVEGARDE CACHE (si extraction normale) =====
        if not loaded_from_cache and cache_manager.enabled:
            try:
                extraction_duration = (datetime.now() - extraction_start_time).total_seconds()

                # Estimer coût (approximation: Vision calls ou 0)
                vision_calls = doc_meta.get("pages", 0) if use_vision else 0
                estimated_cost = vision_calls * 0.015  # ~$0.015 par appel Vision

                cache_path = cache_manager.save_cache(
                    source_file_path=pdf_path,
                    extracted_text=full_text or "",
                    document_metadata=doc_meta,
                    extraction_config={
                        "use_vision": use_vision,
                        "vision_model": GPT_MODEL if use_vision else None,
                        "megaparse_version": "0.3.1"
                    },
                    extraction_stats={
                        "duration_seconds": extraction_duration,
                        "vision_calls": vision_calls,
                        "cost_usd": estimated_cost,
                        "megaparse_blocks": 0  # À enrichir si besoin
                    },
                    page_texts=None  # À enrichir avec page_texts si disponibles
                )

                if cache_path:
                    logger.info(
                        f"💾 [CACHE] Cache sauvegardé: {cache_path.name} "
                        f"(économisera {extraction_duration:.1f}s, ${estimated_cost:.3f} aux prochains imports)"
                    )
            except Exception as e:
                logger.warning(f"⚠️ [CACHE] Échec sauvegarde cache: {e}")

        # ===== OSMOSE Pure Agentique - Traitement sémantique UNIQUEMENT =====
        # REMPLACE l'ingestion legacy (Qdrant "knowbase" + Neo4j entities/relations)
        # Tout passe maintenant par le Proto-KG (concepts canoniques cross-linguals)
        # Utilise osmose_agentique (SupervisorAgent FSM) comme PPTX
        logger.info("=" * 80)
        logger.info("[OSMOSE PURE] Lancement du traitement sémantique Agentique (remplace ingestion legacy)")
        logger.info("=" * 80)

        try:
            from knowbase.ingestion.osmose_agentique import process_document_with_osmose_agentique
            import asyncio

            if full_text and len(full_text) >= 100:
                # Appeler OSMOSE Agentique (SupervisorAgent FSM) de manière asynchrone
                # Même pipeline que PPTX pour uniformité
                osmose_result = asyncio.run(
                    process_document_with_osmose_agentique(
                        document_id=pdf_path.stem,
                        document_title=pdf_path.name,
                        document_path=pdf_path,
                        text_content=full_text,
                        tenant_id="default"
                    )
                )

                if osmose_result.osmose_success:
                    logger.info("=" * 80)
                    logger.info(
                        f"[OSMOSE PURE] ✅ Traitement réussi:\n"
                        f"  - {osmose_result.canonical_concepts} concepts canoniques\n"
                        f"  - {osmose_result.concept_connections} connexions cross-documents\n"
                        f"  - {osmose_result.topics_segmented} topics segmentés\n"
                        f"  - Proto-KG: {osmose_result.proto_kg_concepts_stored} concepts + "
                        f"{osmose_result.proto_kg_relations_stored} relations + "
                        f"{osmose_result.proto_kg_embeddings_stored} embeddings\n"
                        f"  - Durée: {osmose_result.osmose_duration_seconds:.1f}s"
                    )
                    logger.info("=" * 80)
                else:
                    error_msg = f"OSMOSE processing failed: {osmose_result.osmose_error}"
                    logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
                    raise Exception(error_msg)

            else:
                error_msg = f"Text too short ({len(full_text) if full_text else 0} chars)"
                logger.error(f"[OSMOSE PURE] ❌ {error_msg}")
                raise Exception(error_msg)

        except Exception as e:
            # En mode OSMOSE Pure, une erreur OSMOSE = échec complet de l'ingestion
            logger.error(f"[OSMOSE PURE] ❌ Erreur traitement sémantique: {e}", exc_info=True)
            status_file.write_text("error")
            raise  # Re-raise pour arrêter le traitement

        # ===== Fin OSMOSE Pure =====

        try:
            DOCS_DONE.mkdir(parents=True, exist_ok=True)
            shutil.move(str(pdf_path), str(DOCS_DONE / f"{pdf_path.stem}.pdf"))
            if meta_path.exists():
                shutil.move(
                    str(meta_path), str(DOCS_DONE / f"{pdf_path.stem}.meta.json")
                )
        except Exception as e:
            logger.warning(f"⚠️ Déplacement terminé avec avertissement: {e}")

        status_file.write_text("done")
        logger.info(f"🎉 INGESTION TERMINÉE - {pdf_path.name} - OSMOSE Pure")
        logger.info(
            f"📊 Métriques: {osmose_result.canonical_concepts} concepts canoniques, "
            f"{osmose_result.proto_kg_concepts_stored} stockés dans Proto-KG"
        )
        logger.info(f"Done {pdf_path.name} — OSMOSE Pure mode")

        return {
            "osmose_pure": True,
            "canonical_concepts": osmose_result.canonical_concepts,
            "concept_connections": osmose_result.concept_connections,
            "proto_kg_concepts_stored": osmose_result.proto_kg_concepts_stored,
            "proto_kg_relations_stored": osmose_result.proto_kg_relations_stored,
            "proto_kg_embeddings_stored": osmose_result.proto_kg_embeddings_stored
        }

    except Exception as e:
        logger.error(f"❌ Erreur durant {pdf_path.name}: {e}")
        try:
            status_file.write_text("error")
        except Exception:
            pass
        raise  # Re-raise pour propager l'erreur


def main():
    ensure_dirs()
    logger.info("🔎 Scan du dossier DOCS_IN")
    if not DOCS_IN.exists():
        logger.error(f"❌ DOCS_IN n'existe pas: {DOCS_IN}")
        return

    files = list(DOCS_IN.glob("*.pdf"))
    logger.info(f"📦 Fichiers .pdf détectés: {len(files)}")
    if not files:
        logger.info("ℹ️ Aucun .pdf à traiter")
        return

    for file in files:
        logger.info(f"➡️ Fichier détecté: {file.name}")
        process_pdf(file)


if __name__ == "__main__":
    main()
