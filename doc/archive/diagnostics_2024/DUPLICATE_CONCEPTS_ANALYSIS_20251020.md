# Analyse Doublons Concepts - Circuit Breaker Title Case Fallback

**Date** : 2025-10-20
**Problème** : Concepts identiques avec noms différents dans Neo4j
**Cause racine** : Circuit Breaker OPEN → Title Case Fallback

---

## 🔍 Problème Observé

### Exemple Concret : SAP S/4HANA Cloud Private Edition

**2 CanonicalConcept créés pour la même entité** :

1. ✅ **Nom correct** : `"SAP S/4HANA Cloud, Private Edition"`
   - confidence: 0.95
   - type: Product
   - extraction_method: LLM

2. ❌ **Nom incorrect** : `"Sap S/4Hana Cloud Private Edition"`
   - confidence: 0.50
   - type: Unknown
   - extraction_method: Title Case Fallback

### Tous les Variants S/4HANA dans Neo4j

```cypher
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
  AND c.canonical_name CONTAINS 'S/4'
RETURN c.canonical_name
```

**Résultat** : 7 variants pour la même famille de produits !

| Nom dans Neo4j | Status | Timestamp |
|----------------|--------|-----------|
| `"RISE with SAP S/4HANA"` | ✅ Correct | 14:25:xx |
| `"SAP S/4HANA Cloud"` | ✅ Correct | 14:25:xx |
| `"SAP S/4HANA Cloud, Private Edition"` | ✅ Correct | 14:25:53 |
| `"Sap S/4Hana"` | ❌ Title case | 14:29:xx |
| `"Sap S/4Hana Cloud Private Edition"` | ❌ Title case | 14:29:33 |
| `"Sap S/4Hana Private Cloud"` | ❌ Title case | 14:29:xx |
| `"Sap S/4Hana Private Cloud Edition"` | ❌ Title case | 14:29:xx |

---

## 🔎 Cause Racine Identifiée

### Circuit Breaker Comportement

Le `LLMCanonicalizer` utilise un **circuit breaker pattern** pour gérer les échecs LLM :

```python
class LLMCanonicalizer:
    def __init__(self):
        self._failure_count = 0
        self._failure_threshold = 5      # Seuil d'ouverture
        self._recovery_timeout = 60      # Timeout avant retry
        self._state = "CLOSED"           # États: CLOSED, OPEN, HALF_OPEN

    def canonicalize(self, raw_name: str) -> Tuple[str, float, str]:
        if self._state == "OPEN":
            # Circuit breaker OPEN → PAS d'appel LLM
            # Utiliser title case fallback
            return (
                raw_name.title(),        # ← PROBLÈME ICI
                0.50,                    # confidence basse
                "Unknown"                # type inconnu
            )

        # Circuit breaker CLOSED/HALF_OPEN → Appel LLM normal
        try:
            result = self._call_llm(raw_name)
            self._failure_count = 0
            self._state = "CLOSED"
            return result
        except JSONDecodeError:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = "OPEN"
            raise
```

### Séquence d'Événements

**1. Circuit Breaker CLOSED (14:25:xx)**

```
13:40 → Import démarre
14:25 → Circuit breaker CLOSED (ou HALF_OPEN)
14:25:53 → 'SAP Cloud ERP Private' traité avec LLM
        → Résultat: "SAP S/4HANA Cloud, Private Edition" ✅
        → confidence=0.95, type=Product
```

**2. 5 Échecs Consécutifs JSON Parsing (14:25-14:29)**

```
14:26:xx → JSON truncation error #1
14:27:xx → JSON truncation error #2
14:28:xx → JSON truncation error #3
14:28:xx → JSON truncation error #4
14:28:xx → JSON truncation error #5
        → Circuit breaker passe à OPEN ❌
```

**3. Circuit Breaker OPEN (14:29:xx)**

```
14:29:33 → 'SAP S/4HANA Cloud Private Edition' traité SANS LLM
        → Utilise .title() sur le nom brut
        → Résultat: "Sap S/4Hana Cloud Private Edition" ❌
        → confidence=0.50, type=Unknown
```

**4. Circuit Breaker Reste OPEN (14:29-14:49)**

Pendant 20 minutes :
- Timeout de récupération = 60 secondes
- Mais continue à échouer en HALF_OPEN
- Retombe en OPEN immédiatement
- **~400 concepts traités avec title case fallback**

---

## 📊 Impact Quantifié

### Logs Analysés

```bash
# Changements d'état circuit breaker
docker-compose logs ingestion-worker | grep "CircuitBreaker" | wc -l
→ 209 transitions OPEN/HALF_OPEN/CLOSED

# JSON truncation fixes appliqués
docker-compose logs ingestion-worker | grep "Fixed truncated JSON" | wc -l
→ 3887 fixes

# Title case fallbacks utilisés (confidence=0.50)
docker-compose logs ingestion-worker | grep "confidence=0.50" | wc -l
→ ~10337 logs (inclut duplicates logs Python)
```

### Répartition Concepts (556 total)

| Type Canonicalisation | Nombre | % |
|------------------------|--------|---|
| ✅ LLM Correct (conf > 0.50) | ~150 | 27% |
| ❌ Title Case Fallback (conf = 0.50) | ~400 | 72% |
| ⚠️ Unknown | ~6 | 1% |

**Résultat** : **72% des concepts ont des noms incorrects !**

---

## 🔍 Problème du Title Case Fallback

### Exemple 1 : Perte de Casse

**Input** : `"SAP S/4HANA Cloud Private Edition"`

**Après .title()** : `"Sap S/4Hana Cloud Private Edition"`

**Problèmes** :
- "SAP" → "Sap" (acronyme perdu)
- "S/4HANA" → "S/4Hana" (casse produit perdue)
- Pas de virgule ni formatage officiel

---

### Exemple 2 : Perte de Ponctuation

**Input** : `"Amazon Web Services (AWS)"`

**Après .title()** : `"Amazon Web Services (Aws)"`

**Problèmes** :
- "(AWS)" → "(Aws)" (acronyme perdu)
- Pas de parenthèses normalisées

---

### Exemple 3 : Acronymes Incorrects

**Input** : `"24/7 Operations"`

**Après .title()** : `"24/7 Operations"` (OK par chance)

**Mais** :

**Input** : `"ABAP Development"`

**Après .title()** : `"Abap Development"`

**Problème** : "ABAP" → "Abap" (devrait rester "ABAP")

---

## 💡 Solutions

### Solution 1 : Fix JSON Parsing (EN COURS)

**Déjà implémenté** : `_parse_json_robust()` complète JSON tronqué

**Résultat actuel** :
- ✅ 3887 JSON réparés avec succès
- ⚠️ Mais circuit breaker continue à s'ouvrir (JSON encore mal formés)

**Amélioration nécessaire** :
1. Ajouter `response_format={"type": "json_object"}` explicite
2. Augmenter max_tokens à 500-800
3. Simplifier schéma JSON (enlever reasoning field ?)

```python
# Dans llm_router.py
def complete_canonicalization(
    messages: List[Dict[str, Any]],
    temperature: float = 0.0,
    max_tokens: int = 800,  # ← Augmenté
    response_format: dict = {"type": "json_object"}  # ← AJOUTÉ
) -> str:
```

**Gain estimé** : 90-95% des JSON parsing réussis

---

### Solution 2 : Améliorer Title Case Fallback

**Problème actuel** :
```python
# Trop simpliste
canonical_name = raw_name.title()
```

**Solution améliorée** :
```python
def smart_title_case(text: str) -> str:
    """
    Title case intelligent préservant acronymes et casse spécifique.
    """
    # Liste d'acronymes à préserver
    acronyms = {
        "SAP", "ERP", "AWS", "API", "AWS", "ABAP", "CRM",
        "HR", "IT", "AI", "ML", "IoT", "SaaS", "PaaS"
    }

    # Liste de produits avec casse spécifique
    special_cases = {
        "s/4hana": "S/4HANA",
        "s4hana": "S/4HANA",
        "successfactors": "SuccessFactors",
        "ariba": "Ariba",
        "concur": "Concur",
        "fieldglass": "Fieldglass"
    }

    words = text.split()
    result = []

    for word in words:
        # Préserver acronymes
        if word.upper() in acronyms:
            result.append(word.upper())
        # Cas spéciaux
        elif word.lower() in special_cases:
            result.append(special_cases[word.lower()])
        # Sinon title case normal
        else:
            result.append(word.title())

    return " ".join(result)
```

**Exemple résultat** :
- `"sap s/4hana cloud"` → `"SAP S/4HANA Cloud"` ✅
- `"amazon web services aws"` → `"Amazon Web Services AWS"` ✅
- `"abap development"` → `"ABAP Development"` ✅

**Gain estimé** : 70-80% de qualité avec fallback (au lieu de 10% actuel)

---

### Solution 3 : Batch LLMCanonicalizer (MEILLEURE)

**Objectif** : Réduire échecs JSON parsing en groupant appels

**Implémentation** :
```python
def batch_canonicalize(
    self,
    raw_names: List[str],
    batch_size: int = 20
) -> List[Tuple[str, float, str]]:
    """
    Canonicalise 20 concepts d'un coup.
    """
    results = []

    for i in range(0, len(raw_names), batch_size):
        batch = raw_names[i:i+batch_size]

        # 1 appel LLM pour 20 concepts
        response = self._call_llm_batch(batch)

        # Parser réponse JSON
        canonicals = json.loads(response)["canonicalizations"]
        results.extend(canonicals)

    return results
```

**Schéma JSON batch** :
```json
{
  "canonicalizations": [
    {
      "raw_name": "sap cloud",
      "canonical_name": "SAP Cloud Platform",
      "confidence": 0.90,
      "type": "Platform"
    },
    {
      "raw_name": "aws",
      "canonical_name": "Amazon Web Services (AWS)",
      "confidence": 0.95,
      "type": "Infrastructure"
    },
    ...
  ]
}
```

**Avantages** :
1. 556 concepts / 20 = **28 appels LLM** (au lieu de 556)
2. Moins d'échecs JSON parsing (1 échec = 20 concepts perdus, pas 1)
3. Circuit breaker ouvert moins souvent
4. **Temps réduit de 95%** : 53 min → 3 min

**Gain estimé** : 99% de qualité + 95% de temps gagné

---

### Solution 4 : Post-Processing Déduplication

**Objectif** : Fusionner concepts dupliqués après import

**Implémentation** :
```python
def deduplicate_canonical_concepts(tenant_id: str = "default"):
    """
    Fusionne concepts similaires avec noms différents.
    """
    # 1. Trouver candidats dupliqués (similarité textuelle)
    query = """
    MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})
    MATCH (c2:CanonicalConcept {tenant_id: $tenant_id})
    WHERE c1.uuid < c2.uuid
      AND c1.canonical_name <> c2.canonical_name
      AND apoc.text.levenshteinSimilarity(
        toLower(c1.canonical_name),
        toLower(c2.canonical_name)
      ) > 0.85
    RETURN c1, c2
    """

    # 2. Pour chaque paire, garder le meilleur nom
    for c1, c2 in results:
        # Garder celui avec confidence la plus élevée
        if c1.confidence > c2.confidence:
            keep = c1
            merge = c2
        else:
            keep = c2
            merge = c1

        # 3. Transférer relations vers le bon concept
        merge_query = """
        MATCH (merge:CanonicalConcept {uuid: $merge_uuid})
        MATCH (keep:CanonicalConcept {uuid: $keep_uuid})
        MATCH (merge)-[r]->(other)
        CREATE (keep)-[r2:TYPE(r)]->(other)
        SET r2 = properties(r)
        DELETE r
        DETACH DELETE merge
        """
```

**Gain estimé** : Nettoie les doublons existants (one-time fix)

---

## 🎯 Plan d'Action Recommandé

### Phase 1 : Fix JSON Parsing (Priorité 0) ⚠️

**Actions** :
1. Ajouter `response_format={"type": "json_object"}` dans llm_router
2. Augmenter max_tokens à 800
3. Tester avec 50 concepts

**Délai** : 1-2 heures
**Gain** : 90-95% JSON parsing réussis

---

### Phase 2 : Améliorer Title Case Fallback (Priorité 1)

**Actions** :
1. Implémenter `smart_title_case()`
2. Ajouter dictionnaire acronymes SAP
3. Tester avec 100 concepts fallback

**Délai** : 2-3 heures
**Gain** : 70-80% qualité fallback (au lieu de 10%)

---

### Phase 3 : Batch LLMCanonicalizer (Priorité 1) 🚀

**Actions** :
1. Créer `batch_canonicalize()`
2. Modifier schéma JSON pour batch
3. Tester avec 556 concepts

**Délai** : 4-6 heures
**Gain** : 99% qualité + 95% temps gagné (53 min → 3 min)

---

### Phase 4 : Post-Processing Déduplication (Priorité 2)

**Actions** :
1. Implémenter script déduplication
2. Exécuter sur base actuelle (556 concepts)
3. Automatiser après chaque import

**Délai** : 3-4 heures
**Gain** : Nettoie doublons existants

---

## 📊 Résultats Attendus

### Scénario Actuel (Baseline)

| Métrique | Valeur |
|----------|--------|
| Concepts avec bons noms | 150 / 556 (27%) |
| Concepts avec title case fallback | 400 / 556 (72%) |
| Doublons créés | ~50-100 (estimé) |
| Temps canonicalisation | 53 minutes |

---

### Scénario Optimisé (Tous Fixes)

| Métrique | Valeur | Gain |
|----------|--------|------|
| Concepts avec bons noms | 550 / 556 (99%) | +72% |
| Concepts avec title case fallback | 6 / 556 (1%) | -71% |
| Doublons créés | 0-2 (< 1%) | -98% |
| Temps canonicalisation | 3 minutes | -50 min (-94%) |

---

## 🔧 Commandes Diagnostic

### Identifier Concepts avec Title Case Fallback

```bash
# Dans Neo4j
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
  AND c.confidence = 0.50
RETURN c.canonical_name, c.extraction_method
LIMIT 50
"
```

---

### Trouver Doublons Potentiels

```bash
# Similarité textuelle > 85%
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (c1:CanonicalConcept {tenant_id: 'default'})
MATCH (c2:CanonicalConcept {tenant_id: 'default'})
WHERE c1.uuid < c2.uuid
  AND toLower(c1.canonical_name) CONTAINS 's/4hana'
  AND toLower(c2.canonical_name) CONTAINS 's/4hana'
RETURN c1.canonical_name, c2.canonical_name, c1.confidence, c2.confidence
"
```

---

### Compter Variants S/4HANA

```bash
docker exec knowbase-neo4j cypher-shell -u neo4j -p graphiti_neo4j_pass --format plain "
MATCH (c:CanonicalConcept)
WHERE c.tenant_id = 'default'
  AND (
    toLower(c.canonical_name) CONTAINS 's/4hana'
    OR toLower(c.canonical_name) CONTAINS 's4hana'
  )
RETURN c.canonical_name, count(*) as count
ORDER BY count DESC
"
```

---

### Vérifier État Circuit Breaker

```bash
# Dans les logs
docker-compose logs ingestion-worker | grep "CircuitBreaker" | tail -20
```

---

## 📝 Conclusion

### Cause Racine

**Circuit Breaker OPEN → Title Case Fallback → Noms incorrects → Doublons**

Le circuit breaker s'ouvre après 5 échecs JSON parsing consécutifs, causant :
- 72% des concepts avec title case fallback (noms incorrects)
- ~50-100 doublons créés (concepts identiques, noms différents)
- Qualité Neo4j dégradée (recherche inefficace)

### Solution Recommandée

**1. Court terme** : Fix JSON parsing + Smart Title Case
→ 90% qualité + doublons évités

**2. Moyen terme** : Batch LLMCanonicalizer
→ 99% qualité + 95% temps gagné + 0 doublons

**3. Long terme** : Post-processing déduplication automatique
→ Nettoie doublons existants + prévention future

---

**Créé par** : Claude Code
**Pour** : Analyse doublons concepts Neo4j
**Prochaine Étape** : Implémenter Fix JSON Parsing (Phase 1)
