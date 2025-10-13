# Phase 3 - Pipeline Ingestion & Détection Conflits - Tracking Détaillé

**Date début** : 2025-10-05
**Date fin** : -
**Durée estimée** : 3 jours
**Durée réelle** : -
**Statut** : ⏳ **EN COURS**
**Progression** : **0%** (0/6 tâches)

---

## 🎯 Objectifs Phase 3

Intégrer l'extraction automatique de facts structurés dans le pipeline d'ingestion PPTX existant, avec détection de conflits en temps réel et notifications pour les conflits critiques.

### Objectifs Spécifiques

1. ⏳ Intégrer extraction facts dans pipeline PPTX existant
2. ⏳ Implémenter appel LLM Vision pour extraction structurée (GPT-4 Vision)
3. ⏳ Insérer facts extraits dans Neo4j (status="proposed")
4. ⏳ Déclencher détection conflits automatique post-ingestion
5. ⏳ Implémenter notification conflits critiques (webhook/logs)
6. ⏳ Tests pipeline complet (end-to-end)

---

## 📋 Tâches Détaillées

### ⏳ 3.1 - Analyse Pipeline PPTX Existant

**Durée estimée** : 1h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Comprendre l'architecture actuelle du pipeline PPTX pour identifier les points d'intégration

**Actions** :
- [ ] Lire `src/knowbase/ingestion/pipelines/pptx_pipeline.py`
- [ ] Identifier étapes traitement slides (extraction texte, OCR, embeddings)
- [ ] Localiser appel LLM existant (si présent)
- [ ] Déterminer point injection extraction facts (après OCR, avant embeddings?)
- [ ] Vérifier métadonnées disponibles (source_document, chunk_id, page_num)

**Fichiers à analyser** :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py`
- `src/knowbase/ingestion/pipelines/pptx_pipeline_kg.py` (si existe)
- `src/knowbase/common/llm_router.py` (LLM provider)
- `src/knowbase/config/prompts.yaml` (prompts extraction)

**Critères validation** :
- ✅ Architecture pipeline PPTX documentée
- ✅ Point intégration extraction facts identifié
- ✅ Métadonnées traçabilité disponibles

---

### ⏳ 3.2 - Prompt LLM Vision Extraction Facts

**Durée estimée** : 2h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Créer prompt optimisé pour extraction facts structurés depuis slides PPTX (texte + images)

**Actions** :
- [ ] Créer prompt `extract_facts_pptx_v1` dans `config/prompts.yaml`
- [ ] Spécifier format JSON attendu (subject, predicate, object, value, unit, confidence)
- [ ] Inclure exemples SAP (SLA, capacité, pricing, features)
- [ ] Définir règles extraction (skip facts vagues, exiger valeur numérique si applicable)
- [ ] Tester prompt sur 3-5 slides types (RFP, proposal, documentation technique)

**Format JSON Attendu** :
```json
{
  "facts": [
    {
      "subject": "SAP S/4HANA Cloud, Private Edition",
      "predicate": "SLA_garantie",
      "object": "99.7%",
      "value": 99.7,
      "unit": "%",
      "value_type": "numeric",
      "fact_type": "SERVICE_LEVEL",
      "confidence": 0.95,
      "valid_from": "2024-01-01",
      "source_slide_number": 12,
      "extraction_context": "Tableau SLA page 12"
    }
  ]
}
```

**Prompt Template** :
```yaml
extract_facts_pptx_v1:
  system: |
    Tu es un expert en extraction de facts métier structurés depuis des slides SAP.

    **Objectif** : Extraire UNIQUEMENT les facts objectifs, vérifiables, avec valeurs numériques ou dates.

    **Types de facts prioritaires** :
    - SERVICE_LEVEL : SLA, uptime, performance guarantees
    - CAPACITY : Limites, quotas, tailles max (users, storage, transactions)
    - PRICING : Prix, coûts, tarifs (€, $, crédits)
    - FEATURE : Fonctionnalités activées/désactivées (boolean)
    - COMPLIANCE : Certifications, normes (ISO, SOC2, GDPR)

    **Règles strictes** :
    1. Ignorer opinions, estimations, promesses marketing
    2. Exiger valeur numérique pour SERVICE_LEVEL, CAPACITY, PRICING
    3. Indiquer confidence 0.9+ si fact explicite, 0.6-0.8 si inféré
    4. Capturer valid_from si date mentionnée (2024, Q1 2024, etc.)
    5. Référencer slide_number source pour traçabilité

  user: |
    Extrait les facts structurés depuis ce slide PPTX :

    **Slide {slide_number}**
    Texte : {slide_text}
    Image : {image_description}

    Réponds en JSON strict (array de facts).

  examples:
    - input: "Slide 5 : SAP S/4HANA garantit 99.7% SLA uptime"
      output: |
        {
          "facts": [{
            "subject": "SAP S/4HANA",
            "predicate": "SLA_uptime_garantie",
            "object": "99.7%",
            "value": 99.7,
            "unit": "%",
            "value_type": "numeric",
            "fact_type": "SERVICE_LEVEL",
            "confidence": 0.95,
            "source_slide_number": 5
          }]
        }
```

**Fichiers à modifier** :
- `config/prompts.yaml` (nouveau prompt)

**Critères validation** :
- ✅ Prompt créé et testé sur 5 slides
- ✅ Extraction facts JSON valide (Pydantic FactCreate)
- ✅ Taux succès > 80% (facts pertinents vs bruit)

---

### ⏳ 3.3 - Intégration LLM Vision dans Pipeline PPTX

**Durée estimée** : 4h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Modifier pipeline PPTX pour appeler LLM Vision et extraire facts structurés

**Actions** :
- [ ] Créer fonction `extract_facts_from_slide(slide_text, slide_image, slide_num, llm_client)`
- [ ] Appeler LLM Vision (GPT-4 Vision ou Claude 3.5 Sonnet) avec prompt
- [ ] Parser réponse JSON → liste `FactCreate` Pydantic
- [ ] Enrichir métadonnées : `source_document`, `source_chunk_id`, `extraction_method="llm_vision"`
- [ ] Gérer erreurs extraction (LLM timeout, JSON malformé, fact invalide)
- [ ] Logger facts extraits (INFO) et erreurs (WARNING)

**Code Exemple** :
```python
# Dans pptx_pipeline.py

from knowbase.api.schemas.facts import FactCreate, FactType
from knowbase.common.llm_router import get_llm_client
from knowbase.config.prompts_loader import get_prompt

async def extract_facts_from_slide(
    slide_text: str,
    slide_image_base64: Optional[str],
    slide_number: int,
    source_document: str,
    chunk_id: str,
    llm_client
) -> List[FactCreate]:
    """Extrait facts structurés depuis slide PPTX via LLM Vision."""

    prompt_template = get_prompt("extract_facts_pptx_v1")

    # Construire prompt avec contexte
    user_prompt = prompt_template["user"].format(
        slide_number=slide_number,
        slide_text=slide_text,
        image_description="[image attached]" if slide_image_base64 else "[no image]"
    )

    # Appel LLM Vision
    try:
        response = await llm_client.chat_completion(
            model="gpt-4-vision-preview",
            messages=[
                {"role": "system", "content": prompt_template["system"]},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{slide_image_base64}"}}
                    ] if slide_image_base64 else user_prompt
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2000,
        )

        # Parser JSON
        facts_raw = json.loads(response.choices[0].message.content)

        # Valider et enrichir facts
        facts = []
        for fact_data in facts_raw.get("facts", []):
            fact = FactCreate(
                subject=fact_data["subject"],
                predicate=fact_data["predicate"],
                object=fact_data["object"],
                value=fact_data["value"],
                unit=fact_data["unit"],
                value_type=fact_data.get("value_type", "numeric"),
                fact_type=fact_data.get("fact_type", "GENERAL"),
                confidence=fact_data.get("confidence", 0.7),
                source_chunk_id=chunk_id,
                source_document=source_document,
                extraction_method="llm_vision",
                extraction_model="gpt-4-vision-preview",
                extraction_prompt_id="extract_facts_pptx_v1",
            )
            facts.append(fact)

        logger.info(f"✅ Extracted {len(facts)} facts from slide {slide_number}")
        return facts

    except json.JSONDecodeError as e:
        logger.warning(f"⚠️ Failed to parse LLM response as JSON: {e}")
        return []
    except ValidationError as e:
        logger.warning(f"⚠️ Fact validation failed: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ LLM Vision extraction failed: {e}")
        return []
```

**Fichiers à modifier** :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py` (ou créer `pptx_pipeline_facts.py`)

**Critères validation** :
- ✅ Fonction extraction implémentée
- ✅ Appel LLM Vision fonctionnel (GPT-4 Vision)
- ✅ Parser JSON → FactCreate validé
- ✅ Métadonnées traçabilité complètes

---

### ⏳ 3.4 - Insertion Facts Neo4j (status="proposed")

**Durée estimée** : 2h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Insérer facts extraits dans Neo4j avec statut "proposed" pour workflow gouvernance

**Actions** :
- [ ] Utiliser `FactsService.create_fact()` pour chaque fact extrait
- [ ] Définir tenant_id (client RFP si disponible, sinon "default")
- [ ] Logger insertion (fact_uuid, subject, predicate, value)
- [ ] Gérer erreurs insertion (Neo4j indisponible, contrainte violée)
- [ ] Batch insertion si > 10 facts (optimisation performance)

**Code Exemple** :
```python
# Dans pptx_pipeline.py

from knowbase.api.services.facts_service import FactsService
from knowbase.neo4j_custom import get_neo4j_client

async def insert_facts_to_neo4j(
    facts: List[FactCreate],
    tenant_id: str = "default"
) -> List[str]:
    """Insère facts dans Neo4j, retourne UUIDs créés."""

    facts_service = FactsService(tenant_id=tenant_id)
    inserted_uuids = []

    for fact in facts:
        try:
            fact_response = facts_service.create_fact(fact)
            inserted_uuids.append(fact_response.uuid)
            logger.info(
                f"✅ Fact inserted: {fact_response.uuid} | "
                f"{fact.subject} {fact.predicate} {fact.value}{fact.unit}"
            )
        except Exception as e:
            logger.error(f"❌ Failed to insert fact: {e} | {fact.dict()}")

    logger.info(f"📊 Inserted {len(inserted_uuids)}/{len(facts)} facts to Neo4j")
    return inserted_uuids
```

**Fichiers à modifier** :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py`

**Critères validation** :
- ✅ Insertion facts Neo4j fonctionnelle
- ✅ Statut "proposed" par défaut
- ✅ Métadonnées traçabilité complètes (source_chunk_id, extraction_model)
- ✅ Logs insertion (success/failure)

---

### ⏳ 3.5 - Détection Conflits Post-Ingestion

**Durée estimée** : 3h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Déclencher détection conflits automatique après insertion facts, identifier CONTRADICTS/OVERRIDES

**Actions** :
- [ ] Appeler `FactsService.detect_conflicts()` après insertion batch
- [ ] Filtrer conflits critiques (value_diff_pct > 5%, CONTRADICTS avec fact approved)
- [ ] Logger conflits détectés (type, facts en conflit, différence valeur)
- [ ] Marquer facts conflictuels avec status="conflicted" (optionnel)
- [ ] Stocker conflits dans Redis cache (optimisation UI admin)

**Code Exemple** :
```python
# Dans pptx_pipeline.py

from knowbase.api.services.facts_service import FactsService

async def detect_and_log_conflicts(
    inserted_fact_uuids: List[str],
    tenant_id: str = "default"
):
    """Détecte conflits post-ingestion et log résultats."""

    facts_service = FactsService(tenant_id=tenant_id)

    # Détection globale conflits
    conflicts = facts_service.detect_conflicts()

    # Filtrer conflits impliquant facts nouvellement insérés
    relevant_conflicts = [
        c for c in conflicts
        if c.fact_proposed.uuid in inserted_fact_uuids
    ]

    if not relevant_conflicts:
        logger.info("✅ No conflicts detected for new facts")
        return

    # Logger conflits critiques
    critical_conflicts = [
        c for c in relevant_conflicts
        if c.value_diff_pct > 0.05  # > 5% différence
    ]

    for conflict in critical_conflicts:
        logger.warning(
            f"⚠️ CONFLICT {conflict.conflict_type} | "
            f"{conflict.fact_proposed.subject} {conflict.fact_proposed.predicate} | "
            f"Proposed: {conflict.fact_proposed.value} | "
            f"Approved: {conflict.fact_approved.value} | "
            f"Diff: {conflict.value_diff_pct * 100:.1f}%"
        )

    logger.info(
        f"📊 Conflicts detected: {len(relevant_conflicts)} "
        f"({len(critical_conflicts)} critical > 5%)"
    )

    # TODO: Notification webhook si critical_conflicts
```

**Fichiers à modifier** :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py`

**Critères validation** :
- ✅ Détection conflits post-ingestion fonctionnelle
- ✅ Filtrage conflits critiques (> 5% différence)
- ✅ Logs warning pour conflits CONTRADICTS
- ✅ Performance < 100ms pour détection

---

### ⏳ 3.6 - Notification Conflits Critiques

**Durée estimée** : 2h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Notifier équipe gouvernance des conflits critiques détectés (webhook, email, Slack)

**Actions** :
- [ ] Créer fonction `notify_critical_conflicts(conflicts, webhook_url)`
- [ ] Format message JSON/Slack (fact proposé vs approuvé, diff %, lien UI admin)
- [ ] Configurer webhook URL dans `.env` (`CONFLICT_WEBHOOK_URL`)
- [ ] Implémenter retry 3x si webhook échoue
- [ ] Logger notification (success/failure)

**Code Exemple** :
```python
# Nouveau fichier: src/knowbase/ingestion/notifications.py

import httpx
from typing import List
from knowbase.api.schemas.facts import ConflictResponse

async def notify_critical_conflicts(
    conflicts: List[ConflictResponse],
    webhook_url: str,
    threshold_pct: float = 0.05
):
    """Notifie conflits critiques via webhook (Slack, Teams, email)."""

    critical = [c for c in conflicts if c.value_diff_pct > threshold_pct]

    if not critical:
        return

    # Format message Slack
    message = {
        "text": f"🚨 {len(critical)} conflits critiques détectés",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{len(critical)} conflits critiques* (différence > {threshold_pct*100}%)"
                }
            }
        ]
    }

    for conflict in critical[:5]:  # Top 5
        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"• *{conflict.fact_proposed.subject}* - {conflict.fact_proposed.predicate}\n"
                    f"  Proposé: `{conflict.fact_proposed.value}` | "
                    f"Approuvé: `{conflict.fact_approved.value}` | "
                    f"Diff: *{conflict.value_diff_pct*100:.1f}%*"
                )
            }
        })

    # Envoi webhook avec retry
    async with httpx.AsyncClient() as client:
        for attempt in range(3):
            try:
                response = await client.post(
                    webhook_url,
                    json=message,
                    timeout=10.0
                )
                if response.status_code == 200:
                    logger.info(f"✅ Webhook notification sent ({len(critical)} conflicts)")
                    return
            except Exception as e:
                logger.warning(f"⚠️ Webhook attempt {attempt+1}/3 failed: {e}")

        logger.error(f"❌ Failed to send webhook notification after 3 attempts")
```

**Fichiers à créer** :
- `src/knowbase/ingestion/notifications.py`

**Configuration `.env`** :
```bash
# Webhook notification conflits
CONFLICT_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
CONFLICT_THRESHOLD_PCT=0.05  # 5%
```

**Critères validation** :
- ✅ Webhook notification implémentée
- ✅ Format message Slack/Teams compatible
- ✅ Retry 3x si échec
- ✅ Logs notification (success/failure)

---

### ⏳ 3.7 - Tests Pipeline Ingestion Facts

**Durée estimée** : 3h
**Durée réelle** : -
**Statut** : ⏳ En attente
**Progression** : 0%

**Objectif** : Tests end-to-end pipeline ingestion PPTX → extraction facts → Neo4j → conflits

**Actions** :
- [ ] Créer `tests/ingestion/test_pptx_facts_pipeline.py`
- [ ] Test 1 : Extraction facts slide simple (texte seul)
- [ ] Test 2 : Extraction facts slide complexe (texte + image)
- [ ] Test 3 : Insertion facts Neo4j (vérifier tenant_id, status="proposed")
- [ ] Test 4 : Détection conflit CONTRADICTS
- [ ] Test 5 : Notification webhook (mock httpx)
- [ ] Test 6 : Pipeline complet (PPTX → facts → conflits → webhook)

**Fichiers à créer** :
- `tests/ingestion/test_pptx_facts_pipeline.py` (300+ lignes)
- `tests/ingestion/fixtures/sample_rfp.pptx` (document test)

**Critères validation** :
- ✅ 6+ tests pipeline E2E passés
- ✅ Couverture > 80% code extraction/insertion
- ✅ Performance < 5s pour pipeline complet (1 PPTX, 20 slides)

---

## 🎯 Gate Phase 3 → Phase 4

### Critères Validation (4/4 requis)

- [ ] **Pipeline PPTX fonctionnel** : Extraction facts + insertion Neo4j
- [ ] **Détection conflits post-ingestion** : Conflits CONTRADICTS/OVERRIDES identifiés
- [ ] **Tests E2E passés** : 6+ tests pipeline complet (100%)
- [ ] **Performance validée** : < 5s pour ingestion PPTX (20 slides)

### Métriques Attendues

| Métrique | Cible | Moyen Mesure |
|----------|-------|--------------|
| Taux extraction facts | > 70% slides | Logs extraction LLM |
| Précision facts (confidence) | > 0.8 moyenne | Moyenne confidence extraite |
| Conflits détectés | > 50% si présents | Logs détection conflits |
| Performance ingestion | < 5s (20 slides) | Timer pipeline E2E |
| Tests passés | 100% (6/6) | pytest |

---

## 📊 Métriques & KPIs

### Performance

| Métrique | Cible | Actuel | Statut |
|----------|-------|--------|--------|
| Temps extraction 1 slide | < 2s | - | ⏳ |
| Temps insertion 10 facts | < 500ms | - | ⏳ |
| Temps détection conflits | < 100ms | - | ⏳ |
| Pipeline complet (20 slides) | < 5s | - | ⏳ |

### Qualité

| Métrique | Cible | Actuel | Statut |
|----------|-------|--------|--------|
| Taux extraction facts | > 70% | - | ⏳ |
| Confidence moyenne | > 0.8 | - | ⏳ |
| Facts valides (Pydantic) | 100% | - | ⏳ |
| Conflits détectés | > 50% présents | - | ⏳ |

### Tests

| Métrique | Cible | Actuel | Statut |
|----------|-------|--------|--------|
| Tests unitaires | 6+ | 0 | ⏳ |
| Couverture code | > 80% | - | ⏳ |
| Tests E2E passés | 100% | - | ⏳ |

---

## 🔍 Dépendances & Prérequis

### Code Phase 2 (Complété ✅)
- ✅ Module `neo4j_custom` (client, schemas, queries, migrations)
- ✅ API `/api/facts` (CRUD complet)
- ✅ `FactsService` (create_fact, detect_conflicts)
- ✅ Schémas Pydantic `FactCreate`, `ConflictResponse`

### Configuration
- ✅ Prompts YAML (`config/prompts.yaml`)
- ✅ LLM Router (`src/knowbase/common/llm_router.py`)
- ✅ Neo4j connexion (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`)
- ⏳ Webhook URL (`.env`: `CONFLICT_WEBHOOK_URL`)

### LLM Models
- ✅ GPT-4 Vision (OpenAI API) ou Claude 3.5 Sonnet (Anthropic)
- ✅ Token budget : ~2000 tokens/slide (estimation)
- ✅ Coût estimé : $0.01/slide (GPT-4 Vision)

---

## 🚨 Risques & Mitigation

### Risques Techniques

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| LLM Vision timeout (> 30s) | 🔴 High | Medium | Retry 3x + timeout 60s + fallback texte seul |
| Extraction facts imprécise (< 70%) | 🟠 Medium | High | Itération prompt + exemples supplémentaires |
| Conflits non détectés (faux négatifs) | 🟠 Medium | Medium | Tests regression + seuil confidence |
| Neo4j insertion lente (> 1s/fact) | 🟡 Low | Low | Batch insert 10 facts simultanés |
| Webhook notification échoue | 🟡 Low | Medium | Retry 3x + fallback logs |

### Risques Fonctionnels

| Risque | Impact | Probabilité | Mitigation |
|--------|--------|-------------|------------|
| Facts extraits non pertinents (bruit) | 🟠 Medium | High | Règles strictes prompt (valeurs numériques requises) |
| Doublons facts (même subject+predicate) | 🟡 Low | Medium | Déduplication avant insertion (query Neo4j) |
| Faux conflits (variations mineures) | 🟡 Low | Medium | Seuil 5% différence + normalisation unités |

---

## 📝 Documentation Attendue

### Fichiers à Créer/Modifier

**Code** :
- `src/knowbase/ingestion/pipelines/pptx_pipeline.py` (modifié)
- `src/knowbase/ingestion/notifications.py` (nouveau)
- `config/prompts.yaml` (ajout prompt `extract_facts_pptx_v1`)

**Tests** :
- `tests/ingestion/test_pptx_facts_pipeline.py` (nouveau)
- `tests/ingestion/fixtures/sample_rfp.pptx` (nouveau)

**Documentation** :
- `doc/phase3/TRACKING_PHASE3.md` (ce fichier)
- `doc/phase3/PHASE3_VALIDATION.md` (à créer après tests)

---

## ✅ Checklist Complétude Phase 3

### Code
- [ ] Pipeline PPTX modifié (extraction facts)
- [ ] Prompt LLM Vision créé (`extract_facts_pptx_v1`)
- [ ] Fonction extraction facts implémentée
- [ ] Insertion facts Neo4j (status="proposed")
- [ ] Détection conflits post-ingestion
- [ ] Notification webhook conflits critiques

### Tests
- [ ] Tests extraction facts (2+)
- [ ] Tests insertion Neo4j (1+)
- [ ] Tests détection conflits (1+)
- [ ] Tests notification webhook (1+)
- [ ] Test E2E pipeline complet (1+)

### Documentation
- [ ] TRACKING_PHASE3.md (ce fichier)
- [ ] PHASE3_VALIDATION.md (résultats tests)
- [ ] README pipeline facts (usage, config)

### Gate Validation
- [ ] 4/4 critères gate passés
- [ ] Métriques performance validées
- [ ] Tests E2E 100% passés
- [ ] Documentation complète

---

**Créé le** : 2025-10-05
**Dernière mise à jour** : 2025-10-05
**Version** : 1.0
**Statut** : ⏳ **EN COURS**
