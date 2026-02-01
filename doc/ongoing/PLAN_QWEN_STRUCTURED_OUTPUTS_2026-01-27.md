# Plan: Qwen2.5-14B + vLLM Structured Outputs + Post-Validation

**Date:** 2026-01-27
**Statut:** ✅ IMPLÉMENTÉ (3 volets)
**Objectif:** Résoudre les problèmes de troncature JSON et reformulation avec Qwen

## Fichiers Créés/Modifiés

### Nouveaux Fichiers
- `src/knowbase/stratified/pass1/verbatim_validator.py` - Volet A: Validation post-LLM
- `src/knowbase/stratified/pass1/llm_schemas.py` - Volet B: Pydantic schemas pour vLLM
- `tests/stratified/test_verbatim_validator.py` - Tests unitaires (20 tests)

### Fichiers Modifiés
- `src/knowbase/common/llm_router.py` - Volet C: Support json_schema dans burst mode
- `src/knowbase/stratified/pass1/assertion_extractor.py` - Intégration validation
- `src/knowbase/stratified/models/__init__.py` - Export des nouveaux schemas

---

---

## 1. État Actuel

### Modèle utilisé
```python
# src/knowbase/ingestion/burst/types.py
vllm_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"  # ✅ Déjà la version récente
```

### Support response_format
```python
# src/knowbase/common/llm_router.py (ligne 1034-1038)
if 'response_format' in api_kwargs:
    # vLLM supporte response_format pour Qwen et Mistral
    if not any(x in actual_model.lower() for x in ['qwen', 'mistral']):
        api_kwargs.pop('response_format', None)
```

**Problème:** On utilise `response_format={"type": "json_object"}` mais PAS le vrai JSON schema enforcement.

---

## 2. Solution Proposée

### 2.1 vLLM Structured Outputs (JSON Schema)

**Avant (actuel):**
```python
response_format={"type": "json_object"}  # Mode basique, pas de validation schema
```

**Après (proposé):**
```python
response_format={
    "type": "json_schema",
    "json_schema": {
        "name": "assertion_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "assertions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "type": {"type": "string", "enum": ["definitional", "factual", "prescriptive", "permissive", "conditional", "causal", "procedural", "comparative"]},
                            "start_char": {"type": "integer"},
                            "end_char": {"type": "integer"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "language": {"type": "string", "enum": ["fr", "en", "de"]}
                        },
                        "required": ["text", "type", "start_char", "end_char", "confidence"]
                    }
                }
            },
            "required": ["assertions"]
        }
    }
}
```

**Alternative vLLM native:**
```python
# Utiliser guided_json (deprecated mais encore supporté)
extra_body={"guided_json": schema_dict}
```

### 2.2 Post-Validation "exact_quote must be substring"

**Fichier:** `src/knowbase/stratified/pass1/assertion_extractor.py`

```python
def validate_assertion_verbatim(assertion: Dict, source_text: str) -> Tuple[bool, str]:
    """
    Valide qu'une assertion est bien verbatim du texte source.

    Returns:
        (is_valid, reason)
    """
    text = assertion.get("text", "")
    start_char = assertion.get("start_char", -1)
    end_char = assertion.get("end_char", -1)

    # Vérification 1: Le texte doit être un substring exact
    if text not in source_text:
        # Tentative de match fuzzy (tolérance whitespace)
        normalized_text = " ".join(text.split())
        normalized_source = " ".join(source_text.split())
        if normalized_text not in normalized_source:
            return False, "text_not_substring"

    # Vérification 2: Les spans doivent être alignés
    if start_char >= 0 and end_char > start_char:
        expected_text = source_text[start_char:end_char]
        if text != expected_text:
            # Tolérance whitespace
            if " ".join(text.split()) != " ".join(expected_text.split()):
                return False, "span_misaligned"

    # Vérification 3: Longueur raisonnable
    if len(text) < 10:
        return False, "too_short"
    if len(text) > 500:
        return False, "too_long"

    return True, "valid"


async def extract_assertions_with_validation(
    chunk_text: str,
    chunk_id: str,
    llm_response: Dict
) -> List[Dict]:
    """
    Extrait les assertions et applique la post-validation.
    Les assertions invalides sont marquées ABSTAIN.
    """
    validated = []

    for assertion in llm_response.get("assertions", []):
        is_valid, reason = validate_assertion_verbatim(assertion, chunk_text)

        if is_valid:
            assertion["validation_status"] = "valid"
            validated.append(assertion)
        else:
            # Marquer comme ABSTAIN au lieu de rejeter silencieusement
            assertion["validation_status"] = "abstain"
            assertion["abstain_reason"] = reason
            validated.append(assertion)
            logger.warning(
                f"[OSMOSE:Pass1:1.3] Assertion ABSTAIN ({reason}): "
                f"{assertion.get('text', '')[:50]}..."
            )

    return validated
```

### 2.3 Schema Pydantic pour vLLM

**Fichier:** `src/knowbase/stratified/pass1/schemas.py` (nouveau)

```python
from pydantic import BaseModel, Field
from typing import List, Literal
from enum import Enum

class AssertionType(str, Enum):
    definitional = "definitional"
    factual = "factual"
    prescriptive = "prescriptive"
    permissive = "permissive"
    conditional = "conditional"
    causal = "causal"
    procedural = "procedural"
    comparative = "comparative"

class ExtractedAssertion(BaseModel):
    text: str = Field(..., description="Texte EXACT copié du source")
    type: AssertionType
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., gt=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    language: Literal["fr", "en", "de"] = "en"

class AssertionExtractionResponse(BaseModel):
    assertions: List[ExtractedAssertion]

# Extraction du schema pour vLLM
ASSERTION_SCHEMA = AssertionExtractionResponse.model_json_schema()
```

---

## 3. Modifications LLMRouter

**Fichier:** `src/knowbase/common/llm_router.py`

```python
async def _call_vllm_with_schema(
    self,
    model: str,
    messages: List[Dict],
    temperature: float,
    max_tokens: int,
    task_type: TaskType,
    json_schema: Optional[Dict] = None,  # NOUVEAU
    **kwargs
) -> str:
    """Appel vLLM avec JSON schema enforcement."""

    api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference']}

    # Utiliser structured output si schema fourni
    if json_schema:
        api_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": task_type.value,
                "strict": True,
                "schema": json_schema
            }
        }
        # Alternative: guided_json (fallback)
        # api_kwargs["extra_body"] = {"guided_json": json_schema}

    response = await self.async_vllm_client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **api_kwargs
    )

    return response.choices[0].message.content or ""
```

---

## 4. Ordre d'Implémentation

### Phase A: Validation sans modifier vLLM (rapide, low-risk)

1. **Créer `validate_assertion_verbatim()`** dans assertion_extractor.py
2. **Appliquer post-validation** à toutes les assertions extraites
3. **Logger les ABSTAIN** pour mesurer le taux de reformulation

### Phase B: vLLM Structured Outputs (medium-risk)

1. **Créer schemas.py** avec Pydantic models
2. **Modifier llm_router.py** pour supporter `json_schema` param
3. **Tester avec EC2 Spot** en mode standalone

### Phase C: Métriques et Tuning

1. **Comparer** taux d'ancrage avant/après
2. **Ajuster** prompts si nécessaire
3. **Documenter** les résultats

---

## 5. Métriques de Succès

| Métrique | Avant | Cible |
|----------|-------|-------|
| JSON truncation rate | ~10% | 0% |
| Verbatim accuracy | ~60% | >95% |
| Anchor rate | 15% | >50% |
| ABSTAIN (reformulation) | - | <10% |

---

## 6. Risques et Mitigations

| Risque | Mitigation |
|--------|------------|
| vLLM ne supporte pas JSON schema pour Qwen-AWQ | Fallback `guided_json` ou `response_format: json_object` |
| Latence accrue avec structured output | Benchmark avant déploiement |
| Moins d'assertions extraites (contrainte trop forte) | Ajuster schema pour être plus permissif |

---

## 7. Commandes de Test

```bash
# Test standalone EC2 avec nouveau code
curl -X POST http://localhost:8000/api/burst/standalone/start \
  -H "Content-Type: application/json" \
  -d '{"instance_type": "g5.xlarge"}'

# Vérifier support structured output
curl http://<EC2_IP>:8000/v1/models

# Test extraction avec schema
python -c "
from knowbase.stratified.pass1.schemas import ASSERTION_SCHEMA
import json
print(json.dumps(ASSERTION_SCHEMA, indent=2))
"
```

---

## 8. Sources

- [vLLM Structured Outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)
- [Red Hat: Structured outputs in vLLM](https://developers.redhat.com/articles/2025/06/03/structured-outputs-vllm-guiding-ai-responses)
- [BentoML: Structured Decoding in vLLM](https://www.bentoml.com/blog/structured-decoding-in-vllm-a-gentle-introduction)
