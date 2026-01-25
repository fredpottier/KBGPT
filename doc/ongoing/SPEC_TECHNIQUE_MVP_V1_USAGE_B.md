# Spec Technique MVP V1 - Usage B (Challenge de Texte)

**Status:** V1.0 - Prêt pour implémentation (après review ChatGPT)
**Date:** 2026-01-25
**Auteurs:** Fred, Claude
**Référence:** ADR North Star - Vérité Documentaire Contextualisée v7
**Objectif:** Rendre l'Usage B utilisable en 4-6 semaines

---

## 0. Périmètre MVP V1

### Objectif Unique

> **Permettre à un utilisateur de challenger un texte contre le corpus documentaire.**

### Inclus dans MVP V1

| Composant | Description |
|-----------|-------------|
| Pass 1.3 Information-First | Extraction avec `exact_quote` + `span` + `value` |
| ClaimKey minimal | Inference Niveau A (patterns lexicaux) |
| Value extraction bornée | `number`, `percent`, `enum`, `version` uniquement |
| Context propagation | `markers_strong` / `markers_weak` |
| API `challenge(text)` | Endpoint de challenge texte utilisateur |
| Logs exhaustifs | ACCEPT / REJECT / MISSING avec raisons |

### Exclu de MVP V1

- Concepts et Gates G1-G4
- Usage A (Composition)
- Usage C (Exploration UI riche)
- Normalisation cross-langue
- Fusion automatique ClaimKeys

---

## 0bis. Invariants Non-Négociables MVP V1

> Ces invariants DOIVENT être respectés par l'implémentation. Toute dérogation invalide la spec.

### Invariant 1 : PROMOTED_UNLINKED = État Transitoire

> **PROMOTED_UNLINKED est acceptable UNIQUEMENT comme état transitoire, jamais comme état final stable.**

**Conséquences :**
- Monitoring OBLIGATOIRE du taux UNLINKED
- Alerte si > 10% sur un document
- Alerte si > 5% sur le corpus global
- Backlog automatique des patterns manquants généré

**Pourquoi :** Une Information UNLINKED est une "connaissance fantôme" - stockée mais non interrogeable par Usage B.

### Invariant 2 : Tout Claim Utilisateur Produit une Réponse

> **Aucun claim utilisateur ne peut être silencieusement ignoré.**

**Statuts possibles (exhaustifs) :**
- `CONFIRMED` : Confirmé par le corpus
- `CONTRADICTED` : Contredit par le corpus
- `PARTIAL` : Trouvé mais non comparable
- `MISSING` : Sujet documenté, valeur absente
- `UNMAPPED` : **NOUVEAU** - Aucun pattern reconnu

**Pourquoi :** Le silence est dangereux - l'utilisateur pense que "tout va bien".

### Invariant 3 : Privilégier Faux Négatifs aux Faux Positifs

> **Le MVP V1 privilégie les faux négatifs (ne pas détecter) aux faux positifs (mal détecter).**

**Conséquences :**
- En cas de doute sur un conflit → `PARTIAL`, pas `CONTRADICTED`
- En cas de doute sur un match → `UNMAPPED`, pas faux `CONFIRMED`
- Mieux vaut dire "je ne sais pas" que mentir

**Pourquoi :** La crédibilité produit repose sur la précision, pas le rappel.

### Invariant 4 : Soft Conflict pour Sur-Respect

> **Une valeur utilisateur qui sur-respecte une contrainte corpus n'est pas une contradiction hard.**

**Exemple :**
- Corpus : "TLS minimum version is 1.2"
- User : "TLS 1.3 is used"
- Résultat : `soft` (compatible mais différent), **PAS** `hard`

**Règle :** `user_value >= corpus_min_value` → `tension_level: soft`

---

## 1. Pass 1.3 Information-First

### 1.1 Objectif

Extraire **toutes** les assertions factuelles explicites d'un chunk, sans rejet pour "no_concept_match".

### 1.2 Modèle Information (Neo4j)

```cypher
// Node Information
CREATE (i:Information {
  // Identifiants
  information_id: "info_xxx",
  tenant_id: "default",

  // Contenu obligatoire
  text: "TLS 1.2 is enforced for all connections",
  exact_quote: "TLS 1.2 is enforced for all connections",  // OBLIGATOIRE
  type: "PRESCRIPTIVE",  // PRESCRIPTIVE | DEFINITIONAL | CAUSAL | COMPARATIVE
  rhetorical_role: "fact",  // fact | example | definition | instruction | claim | caution

  // Span obligatoire
  span_page: 45,
  span_paragraph: 3,
  span_line: 12,

  // Value (si applicable)
  value_kind: "version",  // number | percent | boolean | enum | string | version
  value_raw: "TLS 1.2",
  value_normalized: "1.2",
  value_unit: "version",
  value_operator: ">=",  // = | >= | <= | > | < | approx | in
  value_comparable: "strict",  // strict | loose | non_comparable

  // Context (hérité ou asserted)
  context_edition: "Private",
  context_region: "Global",
  context_version: "2024",
  context_inheritance_mode: "inherited",  // inherited | asserted | mixed

  // Promotion status
  promotion_status: "PROMOTED_LINKED",  // PROMOTED_LINKED | PROMOTED_UNLINKED | REJECTED
  promotion_reason: "technical_fact",

  // Déduplication
  fingerprint: "hash_xxx",

  // Métadonnées
  confidence: 0.9,
  language: "en",
  extracted_at: datetime()
})
```

### 1.3 Relations Information

```cypher
// Liens obligatoires
(i:Information)-[:EXTRACTED_FROM]->(d:Document)
(i:Information)-[:ANCHORED_IN]->(di:DocItem)
(i:Information)-[:BELONGS_TO_THEME]->(t:Theme)

// Liens optionnels MVP V1
(i:Information)-[:ANSWERS]->(ck:ClaimKey)

// Liens POST-MVP (exclus V1)
// (i:Information)-[:BELONGS_TO_CONCEPT]->(c:Concept)
```

### 1.4 Prompt Pass 1.3 (révisé)

```yaml
pass1_3_extraction:
  system: |
    Tu es un extracteur de faits documentaires. Tu extrais TOUTES les assertions
    factuelles explicites du texte, sans interprétation ni inférence.

    RÈGLES ABSOLUES:
    1. Citation exacte OBLIGATOIRE (exact_quote = verbatim du texte)
    2. Position OBLIGATOIRE (page, paragraphe, ligne si disponible)
    3. Ne JAMAIS rejeter une assertion pour "pas de concept"
    4. Ne JAMAIS inférer ce qui n'est pas explicitement écrit
    5. Ne JAMAIS synthétiser plusieurs sources

    TYPES D'ASSERTIONS À EXTRAIRE:
    - PRESCRIPTIVE: Obligations, interdictions ("must", "shall", "required")
    - DEFINITIONAL: Définitions, descriptions ("is", "uses", "provides")
    - CAUSAL: Relations cause-effet ("because", "therefore", "results in")
    - COMPARATIVE: Comparaisons ("more than", "unlike", "vs")

    RHETORICAL ROLES:
    - fact: Assertion factuelle (génère ClaimKey)
    - example: Illustration, cas concret (PAS de ClaimKey)
    - definition: Définition de terme (génère ClaimKey)
    - instruction: Procédure, how-to (génère ClaimKey)
    - claim: Affirmation non vérifiée (ClaimKey conditionnel)
    - caution: Avertissement, disclaimer (ClaimKey conditionnel)

    VALUE EXTRACTION (si applicable):
    - Extraire la valeur brute (raw)
    - Identifier le type (number, percent, version, enum, boolean)
    - Identifier l'unité (%, TiB, hours, version, etc.)
    - Identifier l'opérateur (=, >=, <=, >, <, approx)

  user: |
    Document: {{document_title}}
    Page: {{page_number}}
    Context hérité: {{doc_context_frame}}

    Texte à analyser:
    """
    {{chunk_text}}
    """

    Extrais TOUTES les assertions factuelles. Format JSON:
    {
      "assertions": [
        {
          "text": "assertion reformulée clairement",
          "exact_quote": "verbatim exact du texte source",
          "type": "PRESCRIPTIVE|DEFINITIONAL|CAUSAL|COMPARATIVE",
          "rhetorical_role": "fact|example|definition|instruction|claim|caution",
          "span": {"page": int, "paragraph": int, "line": int},
          "value": {
            "kind": "number|percent|version|enum|boolean|null",
            "raw": "valeur brute",
            "normalized": "valeur normalisée",
            "unit": "unité",
            "operator": "=|>=|<=|>|<|approx"
          },
          "context_override": {
            "edition": "si différent du contexte hérité",
            "region": "si différent du contexte hérité"
          },
          "confidence": 0.0-1.0
        }
      ]
    }

  output_schema:
    type: object
    properties:
      assertions:
        type: array
        items:
          type: object
          required: [text, exact_quote, type, rhetorical_role, span, confidence]
```

### 1.5 Règles de Promotion

```python
class PromotionPolicy:
    """Politique de promotion Information-First."""

    # Toujours promouvoir
    ALWAYS_PROMOTE_TYPES = ["PRESCRIPTIVE", "DEFINITIONAL"]
    ALWAYS_PROMOTE_ROLES = ["fact", "definition", "instruction"]

    # Promouvoir si value présente
    PROMOTE_IF_VALUE = ["CAUSAL", "COMPARATIVE"]

    # Rejeter uniquement
    REJECT_PATTERNS = [
        r"^this (page|section|chapter) (describes|shows|presents)",
        r"^see also",
        r"^refer to",
        r"^for more information",
        r"^note:",
        r"^disclaimer:",
    ]

    def evaluate(self, assertion: dict) -> tuple[str, str]:
        """
        Retourne (status, reason).
        Status: PROMOTED_LINKED | PROMOTED_UNLINKED | REJECTED
        """
        text_lower = assertion["text"].lower()

        # Rejet explicite
        for pattern in self.REJECT_PATTERNS:
            if re.match(pattern, text_lower):
                return "REJECTED", f"meta_pattern:{pattern}"

        # Promotion automatique par type
        if assertion["type"] in self.ALWAYS_PROMOTE_TYPES:
            return "PROMOTED_LINKED", f"type:{assertion['type']}"

        # Promotion automatique par role
        if assertion["rhetorical_role"] in self.ALWAYS_PROMOTE_ROLES:
            return "PROMOTED_LINKED", f"role:{assertion['rhetorical_role']}"

        # Promotion si value présente
        if assertion.get("value", {}).get("kind"):
            return "PROMOTED_LINKED", "has_value"

        # Exemples/analogies: promouvoir mais marquer
        if assertion["rhetorical_role"] in ["example", "analogy"]:
            return "PROMOTED_UNLINKED", "example_no_claimkey"

        # Défaut: promouvoir avec alerte
        return "PROMOTED_UNLINKED", "no_clear_category"
```

### 1.6 Déduplication par Fingerprint

```python
def compute_fingerprint(
    claimkey_id: str | None,
    value_normalized: str | None,
    context_key: str,
    page: int
) -> str:
    """
    Calcule le fingerprint pour déduplication.

    Même fingerprint = même fait, merger les anchors.
    """
    components = [
        claimkey_id or "no_claimkey",
        value_normalized or "no_value",
        context_key,  # edition:version:region
        str(page)     # Page bucket (pas ligne exacte)
    ]
    return hashlib.sha256(":".join(components).encode()).hexdigest()[:16]
```

---

## 2. ClaimKey Minimal (Niveau A)

### 2.1 Objectif

Inférer des ClaimKeys via patterns lexicaux **sans LLM**, pour permettre le regroupement et la comparaison.

### 2.2 Modèle ClaimKey (Neo4j)

```cypher
CREATE (ck:ClaimKey {
  // Identifiants
  claimkey_id: "ck_tls_min_version",
  tenant_id: "default",

  // Question factuelle
  key: "tls_min_version",
  canonical_question: "Quelle est la version TLS minimum requise ?",

  // Domaine
  domain: "security.encryption",

  // Statut
  status: "emergent",  // emergent | comparable | deprecated | orphan

  // Métriques
  info_count: 3,
  doc_count: 2,
  has_contradiction: true,

  // Métadonnées
  created_at: datetime(),
  inference_method: "pattern_level_a"
})
```

### 2.3 Relations ClaimKey

```cypher
// Informations liées
(i:Information)-[:ANSWERS]->(ck:ClaimKey)

// Contradictions détectées
(ck:ClaimKey)-[:HAS_CONTRADICTION]->(contra:Contradiction)
```

### 2.4 Patterns Niveau A (déterministes)

```python
class ClaimKeyPatterns:
    """Patterns lexicaux pour inference ClaimKey Niveau A."""

    PATTERNS = [
        # SLA / Availability
        {
            "pattern": r"(\d+(?:\.\d+)?)\s*%\s*(sla|availability|uptime)",
            "claimkey": "sla_{context}_availability",
            "domain": "sla.availability",
            "value_kind": "percent"
        },

        # TLS / Encryption
        {
            "pattern": r"tls\s*(\d+(?:\.\d+)?)",
            "claimkey": "tls_min_version",
            "domain": "security.encryption",
            "value_kind": "version"
        },
        {
            "pattern": r"(encryption|encrypted)\s*(at\s*rest|in\s*transit)",
            "claimkey": "encryption_{match_group}",
            "domain": "security.encryption",
            "value_kind": "boolean"
        },

        # Backup / Retention
        {
            "pattern": r"backup[s]?\s*(daily|weekly|hourly|\d+\s*(hours?|days?))",
            "claimkey": "backup_frequency",
            "domain": "operations.backup",
            "value_kind": "enum"
        },
        {
            "pattern": r"retention\s*(\d+)\s*(days?|months?|years?)",
            "claimkey": "data_retention_period",
            "domain": "compliance.retention",
            "value_kind": "number"
        },

        # Data Residency
        {
            "pattern": r"data\s*(must|shall)?\s*(remain|stay|stored)\s*(in|within)\s*(\w+)",
            "claimkey": "data_residency_{country}",
            "domain": "compliance.residency",
            "value_kind": "enum"
        },

        # Size Thresholds
        {
            "pattern": r"(above|over|exceeds?)\s*(\d+)\s*(tib|tb|gb)",
            "claimkey": "{context}_size_threshold",
            "domain": "infrastructure.sizing",
            "value_kind": "number"
        },

        # Responsibility
        {
            "pattern": r"(customer|sap|vendor)\s*(responsible|responsibility|manages?)",
            "claimkey": "{topic}_responsibility",
            "domain": "operations.responsibility",
            "value_kind": "enum"
        },

        # Version Requirements
        {
            "pattern": r"(minimum|required|supported)\s*version\s*:?\s*(\d+(?:\.\d+)*)",
            "claimkey": "{product}_min_version",
            "domain": "compatibility.version",
            "value_kind": "version"
        }
    ]

    def infer_claimkey(self, text: str, context: dict) -> dict | None:
        """
        Tente d'inférer un ClaimKey depuis le texte.

        Returns:
            {claimkey_id, domain, value_kind, match} ou None
        """
        text_lower = text.lower()

        for pattern_def in self.PATTERNS:
            match = re.search(pattern_def["pattern"], text_lower, re.IGNORECASE)
            if match:
                claimkey_id = self._resolve_claimkey_id(
                    pattern_def["claimkey"],
                    match,
                    context
                )
                return {
                    "claimkey_id": claimkey_id,
                    "domain": pattern_def["domain"],
                    "value_kind": pattern_def["value_kind"],
                    "match": match.group(0),
                    "inference_method": "pattern_level_a"
                }

        return None

    def _resolve_claimkey_id(self, template: str, match, context: dict) -> str:
        """Résout le template de claimkey_id avec les variables."""
        result = template

        # Remplacer {context} par le contexte du document
        if "{context}" in result:
            ctx = context.get("product", "unknown").lower().replace(" ", "_")
            result = result.replace("{context}", ctx)

        # Remplacer {country} par le pays détecté
        if "{country}" in result and match.lastgroup:
            result = result.replace("{country}", match.group(match.lastindex).lower())

        # Remplacer {topic} par le topic détecté
        if "{topic}" in result:
            topic = context.get("current_theme", "general").lower()
            result = result.replace("{topic}", topic)

        # Remplacer {product} par le produit
        if "{product}" in result:
            product = context.get("product", "unknown").lower().replace(" ", "_")
            result = result.replace("{product}", product)

        return f"ck_{result}"
```

### 2.5 Gestion des Statuts ClaimKey

```python
class ClaimKeyStatusManager:
    """Gère le cycle de vie des statuts ClaimKey."""

    def update_status(self, claimkey_id: str, neo4j_driver) -> str:
        """
        Recalcule le statut d'un ClaimKey basé sur ses métriques.

        Returns: nouveau statut
        """
        with neo4j_driver.session() as session:
            result = session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id})
                OPTIONAL MATCH (i:Information)-[:ANSWERS]->(ck)
                OPTIONAL MATCH (i)-[:EXTRACTED_FROM]->(d:Document)
                WITH ck, count(DISTINCT i) as info_count, count(DISTINCT d) as doc_count
                RETURN info_count, doc_count
            """, ck_id=claimkey_id).single()

            info_count = result["info_count"]
            doc_count = result["doc_count"]

            # Déterminer le statut
            if info_count == 0:
                new_status = "orphan"
            elif doc_count < 2:
                new_status = "emergent"
            else:
                new_status = "comparable"

            # Mettre à jour
            session.run("""
                MATCH (ck:ClaimKey {claimkey_id: $ck_id})
                SET ck.status = $status,
                    ck.info_count = $info_count,
                    ck.doc_count = $doc_count
            """, ck_id=claimkey_id, status=new_status,
                info_count=info_count, doc_count=doc_count)

            return new_status
```

---

## 3. Value Extraction Bornée

### 3.1 Types de Valeurs MVP V1

| Kind | Description | Exemples | Normalisation |
|------|-------------|----------|---------------|
| `number` | Nombre entier ou décimal | "6 TiB", "24 hours" | Float |
| `percent` | Pourcentage | "99.7%", "80 percent" | Float 0-1 |
| `version` | Version logicielle | "TLS 1.2", "v2.3.1" | Tuple (major, minor, patch) |
| `enum` | Valeur énumérée | "daily", "customer", "mandatory" | String lowercase |
| `boolean` | Vrai/Faux | "enabled", "required", "not supported" | Boolean |

### 3.2 Extracteur de Valeurs

```python
class ValueExtractor:
    """Extracteur de valeurs bornées pour MVP V1."""

    def extract(self, text: str) -> dict | None:
        """
        Extrait et normalise une valeur depuis le texte.

        Returns:
            {kind, raw, normalized, unit, operator, comparable}
        """
        text_lower = text.lower().strip()

        # Tenter chaque extracteur dans l'ordre
        extractors = [
            self._extract_percent,
            self._extract_version,
            self._extract_number_with_unit,
            self._extract_boolean,
            self._extract_enum,
        ]

        for extractor in extractors:
            result = extractor(text_lower, text)
            if result:
                return result

        return None

    def _extract_percent(self, text_lower: str, text_raw: str) -> dict | None:
        """Extrait un pourcentage."""
        patterns = [
            r"(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*percent",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                raw_value = match.group(1)
                normalized = float(raw_value) / 100.0
                return {
                    "kind": "percent",
                    "raw": f"{raw_value}%",
                    "normalized": normalized,
                    "unit": "%",
                    "operator": "=",
                    "comparable": "strict"
                }
        return None

    def _extract_version(self, text_lower: str, text_raw: str) -> dict | None:
        """Extrait une version."""
        patterns = [
            r"(?:v|version\s*)(\d+(?:\.\d+)*)",
            r"(tls|ssl)\s*(\d+(?:\.\d+)?)",
            r"(\d+\.\d+(?:\.\d+)?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                # Récupérer la version (dernier groupe capturant)
                groups = [g for g in match.groups() if g and re.match(r'\d', g)]
                if groups:
                    version_str = groups[-1]
                    # Normaliser en tuple
                    parts = version_str.split(".")
                    normalized = ".".join(parts[:3])  # Max 3 niveaux

                    # Détecter opérateur
                    operator = "="
                    if "minimum" in text_lower or "at least" in text_lower:
                        operator = ">="
                    elif "maximum" in text_lower or "at most" in text_lower:
                        operator = "<="

                    return {
                        "kind": "version",
                        "raw": version_str,
                        "normalized": normalized,
                        "unit": "version",
                        "operator": operator,
                        "comparable": "strict"
                    }
        return None

    def _extract_number_with_unit(self, text_lower: str, text_raw: str) -> dict | None:
        """Extrait un nombre avec unité."""
        units = {
            "tib": ("TiB", 1),
            "tb": ("TB", 1),
            "gib": ("GiB", 1),
            "gb": ("GB", 1),
            "hours?": ("hours", 1),
            "days?": ("days", 1),
            "weeks?": ("weeks", 1),
            "months?": ("months", 1),
            "years?": ("years", 1),
        }

        for unit_pattern, (unit_name, multiplier) in units.items():
            pattern = rf"(\d+(?:\.\d+)?)\s*{unit_pattern}"
            match = re.search(pattern, text_lower)
            if match:
                raw_value = match.group(1)
                normalized = float(raw_value) * multiplier

                # Détecter opérateur
                operator = "="
                if "above" in text_lower or "over" in text_lower or "exceeds" in text_lower:
                    operator = ">"
                elif "below" in text_lower or "under" in text_lower:
                    operator = "<"
                elif "at least" in text_lower or "minimum" in text_lower:
                    operator = ">="

                return {
                    "kind": "number",
                    "raw": f"{raw_value} {unit_name}",
                    "normalized": normalized,
                    "unit": unit_name,
                    "operator": operator,
                    "comparable": "strict"
                }
        return None

    def _extract_boolean(self, text_lower: str, text_raw: str) -> dict | None:
        """Extrait un booléen."""
        true_patterns = [
            r"\b(enabled|required|mandatory|enforced|supported|available)\b",
            r"\b(must|shall)\b",
            r"\bis\s+(enabled|required|mandatory)\b",
        ]
        false_patterns = [
            r"\b(disabled|not required|optional|not supported|unavailable)\b",
            r"\bnot\s+(enabled|required|mandatory)\b",
        ]

        for pattern in true_patterns:
            if re.search(pattern, text_lower):
                return {
                    "kind": "boolean",
                    "raw": "true",
                    "normalized": True,
                    "unit": None,
                    "operator": "=",
                    "comparable": "strict"
                }

        for pattern in false_patterns:
            if re.search(pattern, text_lower):
                return {
                    "kind": "boolean",
                    "raw": "false",
                    "normalized": False,
                    "unit": None,
                    "operator": "=",
                    "comparable": "strict"
                }

        return None

    def _extract_enum(self, text_lower: str, text_raw: str) -> dict | None:
        """Extrait une valeur énumérée."""
        enums = {
            "frequency": ["daily", "weekly", "monthly", "hourly", "yearly", "continuous"],
            "responsibility": ["customer", "sap", "vendor", "shared", "third-party"],
            "severity": ["critical", "high", "medium", "low"],
            "edition": ["private", "public", "enterprise", "standard"],
        }

        for enum_type, values in enums.items():
            for value in values:
                if re.search(rf"\b{value}\b", text_lower):
                    return {
                        "kind": "enum",
                        "raw": value,
                        "normalized": value.lower(),
                        "unit": enum_type,
                        "operator": "=",
                        "comparable": "strict"
                    }

        return None
```

### 3.3 Comparaison de Valeurs

```python
class ValueComparator:
    """Compare deux valeurs pour détecter les contradictions."""

    def compare(self, value_a: dict, value_b: dict) -> dict:
        """
        Compare deux valeurs et retourne le résultat.

        Returns:
            {
                is_conflict: bool,
                conflict_type: str | None,
                tension_level: str,
                explanation: str
            }
        """
        # Pas de comparaison possible si kinds différents
        if value_a.get("kind") != value_b.get("kind"):
            return {
                "is_conflict": False,
                "conflict_type": None,
                "tension_level": "unknown",
                "explanation": "Different value kinds, not comparable"
            }

        kind = value_a["kind"]
        norm_a = value_a.get("normalized")
        norm_b = value_b.get("normalized")

        # Comparaison selon le type
        if kind == "percent" or kind == "number":
            return self._compare_numeric(norm_a, norm_b, value_a, value_b)
        elif kind == "version":
            return self._compare_version(norm_a, norm_b, value_a, value_b)
        elif kind == "boolean":
            return self._compare_boolean(norm_a, norm_b, value_a, value_b)
        elif kind == "enum":
            return self._compare_enum(norm_a, norm_b, value_a, value_b)

        return {
            "is_conflict": False,
            "conflict_type": None,
            "tension_level": "unknown",
            "explanation": "Unknown value kind"
        }

    def _compare_numeric(self, a, b, value_a, value_b) -> dict:
        """Compare des valeurs numériques."""
        if a is None or b is None:
            return {"is_conflict": False, "conflict_type": None,
                    "tension_level": "unknown", "explanation": "Missing normalized value"}

        # Tolérance de 0.1% pour les comparaisons
        tolerance = 0.001

        if abs(a - b) <= tolerance:
            return {"is_conflict": False, "conflict_type": None,
                    "tension_level": "none", "explanation": "Values match"}

        # INVARIANT 4: Soft conflict pour sur-respect
        # Si corpus a opérateur >= et user >= corpus → soft, pas hard
        corpus_op = value_a.get("operator", "=")
        user_val = b
        corpus_val = a

        if corpus_op in [">=", ">"] and user_val >= corpus_val:
            return {
                "is_conflict": False,
                "conflict_type": "value_exceeds_minimum",
                "tension_level": "soft",
                "explanation": f"User value {value_b['raw']} exceeds minimum {value_a['raw']} (compatible)"
            }

        if corpus_op in ["<=", "<"] and user_val <= corpus_val:
            return {
                "is_conflict": False,
                "conflict_type": "value_below_maximum",
                "tension_level": "soft",
                "explanation": f"User value {value_b['raw']} below maximum {value_a['raw']} (compatible)"
            }

        return {
            "is_conflict": True,
            "conflict_type": "value_conflict",
            "tension_level": "hard",
            "explanation": f"{value_a['raw']} vs {value_b['raw']}"
        }

    def _compare_version(self, a, b, value_a, value_b) -> dict:
        """Compare des versions."""
        if a is None or b is None:
            return {"is_conflict": False, "conflict_type": None,
                    "tension_level": "unknown", "explanation": "Missing version"}

        # Parser les versions
        def parse_version(v):
            parts = str(v).split(".")
            return tuple(int(p) for p in parts if p.isdigit())

        va = parse_version(a)
        vb = parse_version(b)

        if va == vb:
            return {"is_conflict": False, "conflict_type": None,
                    "tension_level": "none", "explanation": "Versions match"}

        # INVARIANT 4: Soft conflict pour sur-respect de version
        corpus_op = value_a.get("operator", "=")

        if corpus_op in [">=", ">"] and vb >= va:
            return {
                "is_conflict": False,
                "conflict_type": "version_exceeds_minimum",
                "tension_level": "soft",
                "explanation": f"User version {b} exceeds minimum {a} (compatible)"
            }

        return {
            "is_conflict": True,
            "conflict_type": "value_conflict",
            "tension_level": "hard",
            "explanation": f"Version {a} vs {b}"
        }

    def _compare_boolean(self, a, b, value_a, value_b) -> dict:
        """Compare des booléens."""
        if a == b:
            return {"is_conflict": False, "conflict_type": None,
                    "tension_level": "none", "explanation": "Values match"}

        return {
            "is_conflict": True,
            "conflict_type": "value_conflict",
            "tension_level": "hard",
            "explanation": f"{value_a['raw']} vs {value_b['raw']}"
        }

    def _compare_enum(self, a, b, value_a, value_b) -> dict:
        """Compare des enums."""
        if a == b:
            return {"is_conflict": False, "conflict_type": None,
                    "tension_level": "none", "explanation": "Values match"}

        return {
            "is_conflict": True,
            "conflict_type": "value_conflict",
            "tension_level": "hard",
            "explanation": f"{value_a['raw']} vs {value_b['raw']}"
        }
```

---

## 4. Context Propagation

### 4.1 DocContextFrame

```python
@dataclass
class DocContextFrame:
    """Contexte documentaire propagé aux Informations."""

    # Identifiants
    document_id: str
    document_title: str
    document_version: str | None

    # Markers forts (héritage automatique)
    markers_strong: list[str]  # ["RISE with SAP", "Private Edition"]

    # Markers faibles (héritage conditionnel)
    markers_weak: list[str]  # ["2024 version", "Cloud ERP"]

    # Contexte déduit
    product: str | None  # "SAP S/4HANA Cloud"
    edition: str | None  # "Private" | "Public"
    region: list[str]    # ["Global"] | ["China", "India"]
    deployment: str | None  # "Cloud" | "On-Premise" | "Hybrid"

    @classmethod
    def from_document(cls, doc: dict) -> "DocContextFrame":
        """Construit le contexte depuis les métadonnées document."""
        # Extraction des markers depuis le titre et les métadonnées
        title = doc.get("title", "").lower()

        markers_strong = []
        markers_weak = []

        # Détection markers forts
        strong_patterns = [
            ("RISE with SAP", r"rise\s+with\s+sap"),
            ("Private Edition", r"private\s+edition"),
            ("Public Edition", r"public\s+edition"),
            ("S/4HANA", r"s/4\s*hana"),
        ]
        for marker, pattern in strong_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                markers_strong.append(marker)

        # Détection edition
        edition = None
        if "private" in title:
            edition = "Private"
        elif "public" in title:
            edition = "Public"

        # Détection region
        region = ["Global"]
        region_patterns = [
            ("China", r"\bchina\b"),
            ("India", r"\bindia\b"),
            ("EU", r"\b(eu|europe)\b"),
            ("US", r"\b(us|united\s+states)\b"),
        ]
        for reg, pattern in region_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                region = [reg]
                break

        return cls(
            document_id=doc.get("doc_id", ""),
            document_title=doc.get("title", ""),
            document_version=doc.get("version"),
            markers_strong=markers_strong,
            markers_weak=markers_weak,
            product=doc.get("product"),
            edition=edition,
            region=region,
            deployment=doc.get("deployment", "Cloud")
        )
```

### 4.2 Propagation vers Information

```python
def propagate_context(
    assertion: dict,
    doc_context: DocContextFrame,
    section_context: dict | None
) -> dict:
    """
    Propage le contexte documentaire vers une Information.

    Args:
        assertion: Assertion extraite par LLM
        doc_context: Contexte du document
        section_context: Contexte de la section courante (optionnel)

    Returns:
        Context dict avec inheritance_mode
    """
    context = {
        "edition": doc_context.edition,
        "region": doc_context.region,
        "version": doc_context.document_version,
        "product": doc_context.product,
        "deployment": doc_context.deployment,
        "inheritance_mode": "inherited"
    }

    # Override par assertion locale
    if assertion.get("context_override"):
        override = assertion["context_override"]
        for key, value in override.items():
            if value:
                context[key] = value
                context["inheritance_mode"] = "mixed"

    # Markers weak seulement si même section
    if section_context:
        # Logique de propagation markers_weak selon scope
        pass

    return context
```

---

## 5. API challenge(text)

### 5.1 Endpoint

```python
# src/knowbase/api/routers/challenge.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/v2/challenge", tags=["Challenge"])

class ChallengeRequest(BaseModel):
    """Requête de challenge d'un texte utilisateur."""
    text: str = Field(..., description="Texte à challenger")
    tenant_id: str = Field(default="default")
    context: Optional[dict] = Field(default=None, description="Contexte optionnel (edition, region)")
    include_missing: bool = Field(default=True, description="Inclure les claims non documentés")

class ChallengeMatch(BaseModel):
    """Un match trouvé dans le corpus."""
    claimkey_id: Optional[str]  # Peut être None si UNMAPPED
    claimkey_question: Optional[str]
    user_claim: str
    user_value: Optional[dict]

    # Sources documentaires
    corpus_sources: list[dict]  # [{doc, info_id, value, context}]

    # Résultat (INVARIANT 2 : tous les statuts possibles)
    status: str  # CONFIRMED | CONTRADICTED | PARTIAL | MISSING | UNMAPPED
    tension_level: Optional[str]  # none | soft | hard (INVARIANT 4)
    contradiction: Optional[dict]  # Si CONTRADICTED
    explanation: str

class ChallengeResponse(BaseModel):
    """Réponse de challenge."""
    text_analyzed: str
    claims_found: int
    matches: list[ChallengeMatch]

    # Statistiques (INVARIANT 2 : tous les statuts)
    confirmed: int
    contradicted: int
    partial: int
    missing: int
    unmapped: int  # NOUVEAU - claims sans pattern reconnu

    # Alertes
    high_unmapped_rate: bool  # Alerte si unmapped > 30%

    # Log ID pour traçabilité
    challenge_log_id: str

@router.post("/", response_model=ChallengeResponse)
async def challenge_text(
    request: ChallengeRequest,
    neo4j_driver = Depends(get_neo4j_driver)
):
    """
    Challenge un texte utilisateur contre le corpus documentaire.

    1. Extrait les claims du texte utilisateur
    2. Mappe chaque claim vers un ClaimKey existant
    3. Compare avec les Informations du corpus
    4. Retourne les confirmations, contradictions et absences
    """
    challenger = TextChallenger(neo4j_driver, request.tenant_id)

    result = await challenger.challenge(
        text=request.text,
        context=request.context,
        include_missing=request.include_missing
    )

    return result
```

### 5.2 Service TextChallenger

```python
# src/knowbase/api/services/challenge_service.py

class TextChallenger:
    """Service de challenge de texte contre le corpus."""

    def __init__(self, neo4j_driver, tenant_id: str):
        self.neo4j_driver = neo4j_driver
        self.tenant_id = tenant_id
        self.claimkey_patterns = ClaimKeyPatterns()
        self.value_extractor = ValueExtractor()
        self.value_comparator = ValueComparator()

    async def challenge(
        self,
        text: str,
        context: dict | None = None,
        include_missing: bool = True
    ) -> ChallengeResponse:
        """
        Challenge un texte contre le corpus.

        Returns:
            ChallengeResponse avec tous les matches
        """
        # 1. Segmenter le texte en phrases/claims
        claims = self._segment_text(text)

        # 2. Pour chaque claim, tenter de mapper vers un ClaimKey
        # INVARIANT 2: Tout claim produit une réponse
        matches = []
        for claim in claims:
            match = await self._process_claim(claim, context)
            matches.append(match)  # _process_claim retourne TOUJOURS un match (jamais None)

        # FIX 3: Assertion anti-régression pour INVARIANT 2
        assert len(matches) == len(claims), \
            f"INVARIANT 2 VIOLATION: {len(matches)} matches for {len(claims)} claims"

        # 3. Calculer les statistiques
        confirmed = sum(1 for m in matches if m.status == "CONFIRMED")
        contradicted = sum(1 for m in matches if m.status == "CONTRADICTED")
        partial = sum(1 for m in matches if m.status == "PARTIAL")
        missing = sum(1 for m in matches if m.status == "MISSING")
        unmapped = sum(1 for m in matches if m.status == "UNMAPPED")

        # FIX 3: Calculer avec claims_found (cohérence)
        # Alerte si trop de claims non mappés (INVARIANT 2)
        claims_found = len(claims)
        unmapped_rate = unmapped / claims_found if claims_found > 0 else 0
        high_unmapped_rate = unmapped_rate > 0.30

        if high_unmapped_rate:
            logger.warning(
                f"[CHALLENGE] High unmapped rate: {unmapped_rate:.1%} "
                f"({unmapped}/{len(matches)} claims)"
            )

        # 4. Logger
        log_id = self._log_challenge(text, matches)

        return ChallengeResponse(
            text_analyzed=text,
            claims_found=len(claims),
            matches=matches,
            confirmed=confirmed,
            contradicted=contradicted,
            partial=partial,
            missing=missing,
            unmapped=unmapped,
            high_unmapped_rate=high_unmapped_rate,
            challenge_log_id=log_id
        )

    def _segment_text(self, text: str) -> list[str]:
        """
        Segmente le texte en claims individuels.

        1. Split par phrase (. ! ?)
        2. Split secondaire par conjonctions (and, or, but)
        """
        # 1. Split par phrase
        sentences = re.split(r'[.!?]\s+', text)

        # 2. Split secondaire par conjonctions
        claims = []
        for sentence in sentences:
            if not sentence.strip():
                continue

            # Détecter les conjonctions qui séparent des claims
            # Ex: "TLS 1.2 and encryption at rest are required"
            sub_claims = re.split(r'\s+(?:and|or|but|as well as)\s+', sentence, flags=re.IGNORECASE)

            for sub in sub_claims:
                sub = sub.strip()
                if sub and len(sub) > 10:  # Ignorer fragments trop courts
                    claims.append(sub)

        return claims

    async def _process_claim(
        self,
        claim: str,
        context: dict | None
    ) -> ChallengeMatch:
        """
        Traite un claim individuel.

        INVARIANT 2: Tout claim produit une réponse (jamais None).

        1. Tente d'inférer un ClaimKey
        2. Cherche les Informations correspondantes
        3. Compare les valeurs
        """
        # 1. Tenter d'inférer un ClaimKey
        claimkey_info = self.claimkey_patterns.infer_claimkey(claim, context or {})

        if not claimkey_info:
            # INVARIANT 2: Retourner UNMAPPED, jamais None
            return ChallengeMatch(
                claimkey_id=None,
                claimkey_question=None,
                user_claim=claim,
                user_value=None,
                corpus_sources=[],
                status="UNMAPPED",
                tension_level=None,
                contradiction=None,
                explanation="No pattern recognized for this claim. Consider adding a pattern or rephrasing."
            )

        # 2. Extraire la valeur du claim utilisateur
        user_value = self.value_extractor.extract(claim)

        # 3. Chercher les Informations dans le corpus
        corpus_infos = await self._find_corpus_informations(
            claimkey_info["claimkey_id"],
            context
        )

        if not corpus_infos:
            # Aucune info dans le corpus
            return ChallengeMatch(
                claimkey_id=claimkey_info["claimkey_id"],
                claimkey_question=self._get_canonical_question(claimkey_info["claimkey_id"]),
                user_claim=claim,
                user_value=user_value,
                corpus_sources=[],
                status="MISSING",
                tension_level=None,
                contradiction=None,
                explanation="No documentation found for this claim"
            )

        # 4. Comparer les valeurs
        return self._compare_with_corpus(
            claim,
            user_value,
            claimkey_info,
            corpus_infos
        )

    async def _find_corpus_informations(
        self,
        claimkey_id: str,
        context: dict | None
    ) -> list[dict]:
        """Trouve les Informations du corpus pour un ClaimKey."""
        with self.neo4j_driver.session() as session:
            # Chercher par ClaimKey exact ou pattern similaire
            # FIX 1: Parenthèses pour priorité AND/OR
            # FIX 2: Seulement PROMOTED_LINKED (UNLINKED = pas de ClaimKey par définition)
            result = session.run("""
                MATCH (i:Information)-[:ANSWERS]->(ck:ClaimKey)
                WHERE (ck.claimkey_id = $ck_id OR ck.key CONTAINS $key_part)
                  AND i.tenant_id = $tenant_id
                  AND i.promotion_status = 'PROMOTED_LINKED'
                MATCH (i)-[:EXTRACTED_FROM]->(d:Document)
                RETURN i, d, ck
                ORDER BY d.created_at DESC
                LIMIT 10
            """, ck_id=claimkey_id,
                key_part=claimkey_id.replace("ck_", ""),
                tenant_id=self.tenant_id)

            infos = []
            for record in result:
                info = dict(record["i"])
                doc = dict(record["d"])
                infos.append({
                    "information_id": info["information_id"],
                    "text": info["text"],
                    "exact_quote": info.get("exact_quote"),
                    "value": {
                        "kind": info.get("value_kind"),
                        "raw": info.get("value_raw"),
                        "normalized": info.get("value_normalized"),
                        "unit": info.get("value_unit"),
                        "operator": info.get("value_operator"),
                    },
                    "context": {
                        "edition": info.get("context_edition"),
                        "region": info.get("context_region"),
                        "version": info.get("context_version"),
                    },
                    "document": {
                        "doc_id": doc["doc_id"],
                        "title": doc.get("title"),
                        "page": info.get("span_page"),
                    }
                })

            return infos

    def _compare_with_corpus(
        self,
        claim: str,
        user_value: dict | None,
        claimkey_info: dict,
        corpus_infos: list[dict]
    ) -> ChallengeMatch:
        """Compare le claim utilisateur avec le corpus."""

        # Si pas de valeur utilisateur, on peut seulement dire "documenté"
        if not user_value:
            return ChallengeMatch(
                claimkey_id=claimkey_info["claimkey_id"],
                claimkey_question=self._get_canonical_question(claimkey_info["claimkey_id"]),
                user_claim=claim,
                user_value=None,
                corpus_sources=[self._format_source(i) for i in corpus_infos],
                status="PARTIAL",
                tension_level=None,
                contradiction=None,
                explanation="Claim found in corpus but no specific value to compare"
            )

        # Comparer avec chaque source
        hard_conflicts = []
        soft_conflicts = []
        confirmations = []

        for info in corpus_infos:
            corpus_value = info.get("value", {})
            if corpus_value.get("normalized"):
                comparison = self.value_comparator.compare(user_value, corpus_value)
                if comparison["is_conflict"]:
                    hard_conflicts.append({
                        "info": info,
                        "comparison": comparison
                    })
                elif comparison["tension_level"] == "soft":
                    # INVARIANT 4: Soft conflict (sur-respect)
                    soft_conflicts.append({
                        "info": info,
                        "comparison": comparison
                    })
                else:
                    confirmations.append(info)

        # Déterminer le statut selon INVARIANT 3 (privilégier faux négatifs)
        if hard_conflicts and not confirmations and not soft_conflicts:
            return ChallengeMatch(
                claimkey_id=claimkey_info["claimkey_id"],
                claimkey_question=self._get_canonical_question(claimkey_info["claimkey_id"]),
                user_claim=claim,
                user_value=user_value,
                corpus_sources=[self._format_source(i) for i in corpus_infos],
                status="CONTRADICTED",
                tension_level="hard",
                contradiction={
                    "nature": "value_conflict",
                    "tension_level": "hard",
                    "user_value": user_value["raw"],
                    "corpus_values": [c["info"]["value"]["raw"] for c in hard_conflicts],
                    "explanation": hard_conflicts[0]["comparison"]["explanation"]
                },
                explanation=f"Your claim contradicts {len(hard_conflicts)} document(s)"
            )

        elif soft_conflicts and not hard_conflicts:
            # INVARIANT 4: Soft conflict = CONFIRMED avec note
            return ChallengeMatch(
                claimkey_id=claimkey_info["claimkey_id"],
                claimkey_question=self._get_canonical_question(claimkey_info["claimkey_id"]),
                user_claim=claim,
                user_value=user_value,
                corpus_sources=[self._format_source(s["info"]) for s in soft_conflicts],
                status="CONFIRMED",
                tension_level="soft",
                contradiction=None,
                explanation=f"Your claim exceeds minimum requirements ({soft_conflicts[0]['comparison']['explanation']})"
            )

        elif confirmations:
            return ChallengeMatch(
                claimkey_id=claimkey_info["claimkey_id"],
                claimkey_question=self._get_canonical_question(claimkey_info["claimkey_id"]),
                user_claim=claim,
                user_value=user_value,
                corpus_sources=[self._format_source(i) for i in confirmations],
                status="CONFIRMED",
                tension_level="none",
                contradiction=None,
                explanation=f"Your claim is confirmed by {len(confirmations)} document(s)"
            )

        else:
            # INVARIANT 3: En cas de doute → PARTIAL
            return ChallengeMatch(
                claimkey_id=claimkey_info["claimkey_id"],
                claimkey_question=self._get_canonical_question(claimkey_info["claimkey_id"]),
                user_claim=claim,
                user_value=user_value,
                corpus_sources=[self._format_source(i) for i in corpus_infos],
                status="PARTIAL",
                tension_level=None,
                contradiction=None,
                explanation="Found in corpus but values not directly comparable"
            )

    def _format_source(self, info: dict) -> dict:
        """Formate une source pour la réponse."""
        return {
            "document": info["document"]["title"],
            "page": info["document"]["page"],
            "quote": info.get("exact_quote"),
            "value": info.get("value", {}).get("raw"),
            "context": info.get("context", {})
        }

    def _get_canonical_question(self, claimkey_id: str) -> str:
        """Retourne la question canonique pour un ClaimKey."""
        # Mapping simple pour MVP
        mappings = {
            "ck_tls_min_version": "What is the minimum TLS version required?",
            "ck_sla_availability": "What is the SLA availability percentage?",
            "ck_backup_frequency": "How often are backups performed?",
            "ck_data_residency": "Where must data be stored?",
        }
        return mappings.get(claimkey_id, f"Question for {claimkey_id}")

    def _log_challenge(self, text: str, matches: list) -> str:
        """Log le challenge pour traçabilité."""
        log_id = f"chal_{uuid.uuid4().hex[:12]}"
        # TODO: Persister dans Neo4j ou autre store
        logger.info(f"[CHALLENGE:{log_id}] text={text[:100]}... matches={len(matches)}")
        return log_id
```

---

## 6. Logs Exhaustifs

### 6.1 Structure de Log

```python
@dataclass
class ExtractionLog:
    """Log exhaustif d'extraction."""

    log_id: str
    timestamp: datetime
    document_id: str
    chunk_id: str
    tenant_id: str

    # Résultat
    action: str  # ACCEPT | REJECT | SKIP
    reason: str

    # Détails
    assertion_text: str
    assertion_type: str
    rhetorical_role: str

    # Valeur (si applicable)
    value_extracted: dict | None
    claimkey_inferred: str | None

    # Contexte
    context_inherited: dict
    context_override: dict | None

    # Métadonnées LLM
    llm_model: str
    llm_confidence: float
    llm_latency_ms: int

    # Promotion
    promotion_status: str  # PROMOTED_LINKED | PROMOTED_UNLINKED | REJECTED
    promotion_reason: str

class ExtractionLogger:
    """Logger exhaustif pour les extractions."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.logs: list[ExtractionLog] = []

    def log_accept(
        self,
        document_id: str,
        chunk_id: str,
        assertion: dict,
        value: dict | None,
        claimkey_id: str | None,
        context: dict,
        promotion_status: str,
        promotion_reason: str,
        llm_metadata: dict
    ):
        """Log une assertion acceptée."""
        log = ExtractionLog(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.utcnow(),
            document_id=document_id,
            chunk_id=chunk_id,
            tenant_id=self.tenant_id,
            action="ACCEPT",
            reason=promotion_reason,
            assertion_text=assertion["text"],
            assertion_type=assertion["type"],
            rhetorical_role=assertion.get("rhetorical_role", "unknown"),
            value_extracted=value,
            claimkey_inferred=claimkey_id,
            context_inherited=context,
            context_override=assertion.get("context_override"),
            llm_model=llm_metadata.get("model", "unknown"),
            llm_confidence=assertion.get("confidence", 0.0),
            llm_latency_ms=llm_metadata.get("latency_ms", 0),
            promotion_status=promotion_status,
            promotion_reason=promotion_reason
        )
        self.logs.append(log)
        self._persist(log)

        logger.info(
            f"[EXTRACT:ACCEPT] doc={document_id} "
            f"type={assertion['type']} role={assertion.get('rhetorical_role')} "
            f"claimkey={claimkey_id} status={promotion_status}"
        )

    def log_reject(
        self,
        document_id: str,
        chunk_id: str,
        assertion: dict,
        reason: str,
        llm_metadata: dict
    ):
        """Log une assertion rejetée."""
        log = ExtractionLog(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.utcnow(),
            document_id=document_id,
            chunk_id=chunk_id,
            tenant_id=self.tenant_id,
            action="REJECT",
            reason=reason,
            assertion_text=assertion["text"],
            assertion_type=assertion.get("type", "unknown"),
            rhetorical_role=assertion.get("rhetorical_role", "unknown"),
            value_extracted=None,
            claimkey_inferred=None,
            context_inherited={},
            context_override=None,
            llm_model=llm_metadata.get("model", "unknown"),
            llm_confidence=assertion.get("confidence", 0.0),
            llm_latency_ms=llm_metadata.get("latency_ms", 0),
            promotion_status="REJECTED",
            promotion_reason=reason
        )
        self.logs.append(log)
        self._persist(log)

        logger.warning(
            f"[EXTRACT:REJECT] doc={document_id} "
            f"reason={reason} text={assertion['text'][:50]}..."
        )

    def log_missing_claimkey(
        self,
        document_id: str,
        chunk_id: str,
        assertion: dict,
        context: dict,
        llm_metadata: dict
    ):
        """Log une assertion sans ClaimKey (PROMOTED_UNLINKED)."""
        log = ExtractionLog(
            log_id=f"log_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.utcnow(),
            document_id=document_id,
            chunk_id=chunk_id,
            tenant_id=self.tenant_id,
            action="ACCEPT",
            reason="no_claimkey_match",
            assertion_text=assertion["text"],
            assertion_type=assertion["type"],
            rhetorical_role=assertion.get("rhetorical_role", "unknown"),
            value_extracted=None,
            claimkey_inferred=None,
            context_inherited=context,
            context_override=assertion.get("context_override"),
            llm_model=llm_metadata.get("model", "unknown"),
            llm_confidence=assertion.get("confidence", 0.0),
            llm_latency_ms=llm_metadata.get("latency_ms", 0),
            promotion_status="PROMOTED_UNLINKED",
            promotion_reason="no_claimkey_match"
        )
        self.logs.append(log)
        self._persist(log)

        logger.warning(
            f"[EXTRACT:MISSING_CK] doc={document_id} "
            f"text={assertion['text'][:50]}... (promoted but unlinked)"
        )

    def _persist(self, log: ExtractionLog):
        """Persiste le log (Neo4j ou fichier)."""
        # MVP: fichier JSON
        log_file = f"data/logs/extraction_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(log), default=str) + "\n")

    def get_statistics(self) -> dict:
        """Retourne les statistiques des logs."""
        total = len(self.logs)
        accepted = sum(1 for l in self.logs if l.action == "ACCEPT")
        rejected = sum(1 for l in self.logs if l.action == "REJECT")
        linked = sum(1 for l in self.logs if l.promotion_status == "PROMOTED_LINKED")
        unlinked = sum(1 for l in self.logs if l.promotion_status == "PROMOTED_UNLINKED")

        # INVARIANT 1: Calculer le taux UNLINKED et alerter si > seuil
        unlinked_rate = unlinked / accepted if accepted > 0 else 0
        unlinked_alert = unlinked_rate > 0.10  # >10% = alerte

        stats = {
            "total_assertions": total,
            "accepted": accepted,
            "rejected": rejected,
            "promoted_linked": linked,
            "promoted_unlinked": unlinked,
            "acceptance_rate": accepted / total if total > 0 else 0,
            "linked_rate": linked / accepted if accepted > 0 else 0,
            "unlinked_rate": unlinked_rate,
            "unlinked_alert": unlinked_alert
        }

        # INVARIANT 1: Logger l'alerte si nécessaire
        if unlinked_alert:
            logger.warning(
                f"[EXTRACT:ALERT] High UNLINKED rate: {unlinked_rate:.1%} "
                f"({unlinked}/{accepted} assertions). "
                f"Review missing ClaimKey patterns."
            )

            # Générer le backlog des patterns manquants
            self._generate_missing_patterns_backlog()

        return stats

    def _generate_missing_patterns_backlog(self):
        """
        INVARIANT 1: Génère un backlog des patterns ClaimKey manquants.

        Analyse les assertions UNLINKED pour identifier les patterns
        qui devraient être ajoutés.
        """
        unlinked_logs = [l for l in self.logs if l.promotion_status == "PROMOTED_UNLINKED"]

        # Grouper par mots-clés fréquents
        keywords = {}
        for log in unlinked_logs:
            text_lower = log.assertion_text.lower()
            # Extraire les mots significatifs
            words = re.findall(r'\b[a-z]{4,}\b', text_lower)
            for word in words:
                if word not in ["that", "this", "with", "from", "have", "been"]:
                    keywords[word] = keywords.get(word, 0) + 1

        # Trier par fréquence
        top_keywords = sorted(keywords.items(), key=lambda x: -x[1])[:10]

        logger.info(
            f"[EXTRACT:BACKLOG] Top missing pattern keywords: {top_keywords}"
        )

        # Persister le backlog
        backlog_file = f"data/logs/missing_patterns_{datetime.utcnow().strftime('%Y%m%d')}.json"
        os.makedirs(os.path.dirname(backlog_file), exist_ok=True)

        with open(backlog_file, "w") as f:
            json.dump({
                "generated_at": datetime.utcnow().isoformat(),
                "unlinked_count": len(unlinked_logs),
                "top_keywords": dict(top_keywords),
                "samples": [l.assertion_text for l in unlinked_logs[:20]]
            }, f, indent=2)
```

### 6.2 Format de Log Structuré

```json
{
  "log_id": "log_abc123def456",
  "timestamp": "2026-01-25T14:30:00Z",
  "document_id": "doc_rise_security_2024",
  "chunk_id": "chunk_045_003",
  "tenant_id": "default",

  "action": "ACCEPT",
  "reason": "type:PRESCRIPTIVE",

  "assertion": {
    "text": "TLS 1.2 is enforced for all connections",
    "type": "PRESCRIPTIVE",
    "rhetorical_role": "fact",
    "confidence": 0.95
  },

  "value": {
    "kind": "version",
    "raw": "TLS 1.2",
    "normalized": "1.2",
    "unit": "version",
    "operator": ">="
  },

  "claimkey": {
    "id": "ck_tls_min_version",
    "inference_method": "pattern_level_a"
  },

  "context": {
    "edition": "Private",
    "region": "Global",
    "inheritance_mode": "inherited"
  },

  "promotion": {
    "status": "PROMOTED_LINKED",
    "reason": "type:PRESCRIPTIVE"
  },

  "llm": {
    "model": "gpt-4o-mini",
    "latency_ms": 234
  }
}
```

### 6.3 Requêtes d'Analyse des Logs

```python
class LogAnalyzer:
    """Analyseur de logs d'extraction."""

    def analyze_document(self, document_id: str) -> dict:
        """Analyse les logs pour un document."""
        logs = self._load_logs(document_id)

        return {
            "document_id": document_id,
            "total_assertions": len(logs),
            "accepted": len([l for l in logs if l["action"] == "ACCEPT"]),
            "rejected": len([l for l in logs if l["action"] == "REJECT"]),

            "by_type": self._group_by(logs, "assertion.type"),
            "by_role": self._group_by(logs, "assertion.rhetorical_role"),
            "by_promotion": self._group_by(logs, "promotion.status"),

            "claimkeys_inferred": len(set(
                l.get("claimkey", {}).get("id")
                for l in logs
                if l.get("claimkey", {}).get("id")
            )),

            "rejection_reasons": self._group_by(
                [l for l in logs if l["action"] == "REJECT"],
                "reason"
            ),

            "unlinked_reasons": self._group_by(
                [l for l in logs if l.get("promotion", {}).get("status") == "PROMOTED_UNLINKED"],
                "reason"
            )
        }

    def get_unlinked_report(self, tenant_id: str) -> list[dict]:
        """Rapport des assertions PROMOTED_UNLINKED (alerte si >5%)."""
        logs = self._load_all_logs(tenant_id)

        unlinked = [
            l for l in logs
            if l.get("promotion", {}).get("status") == "PROMOTED_UNLINKED"
        ]

        total_accepted = len([l for l in logs if l["action"] == "ACCEPT"])
        unlinked_rate = len(unlinked) / total_accepted if total_accepted > 0 else 0

        return {
            "total_unlinked": len(unlinked),
            "total_accepted": total_accepted,
            "unlinked_rate": unlinked_rate,
            "alert": unlinked_rate > 0.05,
            "samples": unlinked[:10]  # 10 premiers exemples
        }
```

---

## 7. Plan d'Implémentation

### 7.1 Ordre des Tâches

| # | Tâche | Dépendances | Estimation |
|---|-------|-------------|------------|
| 1 | Modèle Information Neo4j | - | 2h |
| 2 | Prompt Pass 1.3 révisé | 1 | 4h |
| 3 | PromotionPolicy | 2 | 2h |
| 4 | ValueExtractor | - | 4h |
| 5 | ClaimKeyPatterns (Niveau A) | - | 4h |
| 6 | Context Propagation | 1 | 2h |
| 7 | Modèle ClaimKey Neo4j | 5 | 2h |
| 8 | Intégration Pass 1.3 | 1-7 | 8h |
| 9 | ExtractionLogger | 8 | 4h |
| 10 | TextChallenger service | 4, 5, 7 | 8h |
| 11 | API challenge endpoint | 10 | 4h |
| 12 | Tests e2e | 1-11 | 8h |

**Total estimé : ~50h de développement**

### 7.2 Fichiers à Créer/Modifier

```
src/knowbase/
├── stratified/
│   ├── models/
│   │   ├── information.py      # Modèle Information (CRÉER)
│   │   └── claimkey.py         # Modèle ClaimKey (CRÉER)
│   ├── pass1/
│   │   ├── assertion_extractor.py  # MODIFIER - nouveau prompt
│   │   ├── promotion_policy.py     # CRÉER
│   │   └── value_extractor.py      # CRÉER
│   ├── claimkey/
│   │   ├── patterns.py         # CRÉER - patterns Niveau A
│   │   └── status_manager.py   # CRÉER
│   └── context/
│       └── propagation.py      # CRÉER
├── api/
│   ├── routers/
│   │   └── challenge.py        # CRÉER - endpoint
│   └── services/
│       └── challenge_service.py  # CRÉER
└── logging/
    └── extraction_logger.py    # CRÉER

config/
└── prompts.yaml                # MODIFIER - nouveau prompt Pass 1.3
```

### 7.3 Tests Requis

```python
# tests/stratified/test_mvp_v1.py

class TestValueExtractor:
    def test_extract_percent(self):
        assert extract("99.7% SLA")["normalized"] == 0.997

    def test_extract_version(self):
        assert extract("TLS 1.2")["normalized"] == "1.2"

    def test_extract_number_with_unit(self):
        assert extract("6 TiB")["normalized"] == 6.0

class TestClaimKeyPatterns:
    def test_tls_pattern(self):
        result = infer("TLS 1.2 is enforced", {})
        assert result["claimkey_id"] == "ck_tls_min_version"

    def test_sla_pattern(self):
        result = infer("99.7% availability SLA", {})
        assert "sla" in result["claimkey_id"]

class TestPromotionPolicy:
    def test_prescriptive_always_promoted(self):
        status, _ = policy.evaluate({"type": "PRESCRIPTIVE", "text": "must use TLS"})
        assert status == "PROMOTED_LINKED"

    def test_meta_rejected(self):
        status, _ = policy.evaluate({"type": "DEFINITIONAL", "text": "This page describes..."})
        assert status == "REJECTED"

class TestChallengeAPI:
    async def test_confirmed_claim(self):
        response = await client.post("/api/v2/challenge/", json={
            "text": "TLS 1.2 is required",
            "tenant_id": "default"
        })
        assert response.json()["matches"][0]["status"] == "CONFIRMED"
        assert response.json()["matches"][0]["tension_level"] == "none"

    async def test_confirmed_soft_surrespect(self):
        """INVARIANT 4: Sur-respect = soft, pas contradiction."""
        # Corpus: "TLS minimum 1.2"
        # User: "TLS 1.3"
        response = await client.post("/api/v2/challenge/", json={
            "text": "TLS 1.3 is used",
            "tenant_id": "default"
        })
        assert response.json()["matches"][0]["status"] == "CONFIRMED"
        assert response.json()["matches"][0]["tension_level"] == "soft"

    async def test_contradicted_claim(self):
        # Corpus: "TLS minimum 1.2"
        # User: "TLS 1.0"
        response = await client.post("/api/v2/challenge/", json={
            "text": "TLS 1.0 is sufficient",
            "tenant_id": "default"
        })
        assert response.json()["matches"][0]["status"] == "CONTRADICTED"
        assert response.json()["matches"][0]["tension_level"] == "hard"

    async def test_unmapped_claim(self):
        """INVARIANT 2: Claims sans pattern retournent UNMAPPED."""
        response = await client.post("/api/v2/challenge/", json={
            "text": "The sky is blue",
            "tenant_id": "default"
        })
        assert response.json()["matches"][0]["status"] == "UNMAPPED"
        assert response.json()["unmapped"] == 1

    async def test_multiple_claims_split(self):
        """Test segmentation par conjonctions."""
        response = await client.post("/api/v2/challenge/", json={
            "text": "TLS 1.2 is required and backups are daily",
            "tenant_id": "default"
        })
        # Devrait détecter 2 claims
        assert len(response.json()["matches"]) == 2


class TestInvariant1Monitoring:
    def test_unlinked_alert_triggered(self):
        """INVARIANT 1: Alerte si UNLINKED > 10%."""
        logger = ExtractionLogger("test")
        # Simuler 15% UNLINKED
        for i in range(85):
            logger.log_accept(..., promotion_status="PROMOTED_LINKED", ...)
        for i in range(15):
            logger.log_missing_claimkey(...)

        stats = logger.get_statistics()
        assert stats["unlinked_alert"] == True
        assert stats["unlinked_rate"] > 0.10
```

---

## 8. Critères de Succès MVP V1

### 8.1 Critères Fonctionnels

- [ ] API `challenge(text)` opérationnelle
- [ ] Détection de contradictions `value_conflict` fonctionne (hard + soft)
- [ ] Détection `missing_claim` fonctionne
- [ ] Détection `UNMAPPED` pour claims sans pattern (INVARIANT 2)
- [ ] Logs exhaustifs ACCEPT/REJECT/MISSING/UNLINKED générés
- [ ] ClaimKeys inférés par patterns Niveau A
- [ ] Monitoring UNLINKED avec alertes (INVARIANT 1)
- [ ] Backlog auto-généré pour patterns manquants

### 8.2 Critères Quantitatifs

| Métrique | Cible MVP V1 | Alerte si |
|----------|--------------|-----------|
| Temps de réponse API challenge | < 2s | > 5s |
| % Informations avec value.normalized | > 50% | < 30% |
| % PROMOTED_UNLINKED | < 10% | > 10% (INVARIANT 1) |
| % Claims UNMAPPED (challenge) | < 30% | > 30% |
| Couverture patterns ClaimKey | > 70% | < 50% |

### 8.3 Critères Qualitatifs

- [ ] Un utilisateur peut challenger "TLS 1.3 is used" et obtenir CONFIRMED soft (sur-respect)
- [ ] Un utilisateur peut challenger "TLS 1.0 is used" et obtenir CONTRADICTED hard
- [ ] Un claim sans pattern retourne UNMAPPED (jamais silencieux)
- [ ] Les logs permettent de comprendre pourquoi une assertion a été acceptée/rejetée
- [ ] Aucune hallucination possible (tout est sourcé)
- [ ] Les patterns manquants sont automatiquement identifiés et backlogués

### 8.4 Validation des Invariants

| Invariant | Test | Critère |
|-----------|------|---------|
| **1. UNLINKED transitoire** | Monitoring automatique | Alerte si > 10%, backlog généré |
| **2. Tout claim répond** | Aucun `return None` | Tous les statuts présents dans response |
| **3. Faux négatifs > faux positifs** | Tests manuels | Pas de CONTRADICTED erroné |
| **4. Soft pour sur-respect** | Test TLS 1.3 vs min 1.2 | CONFIRMED soft, pas CONTRADICTED |

---

## 9. Changelog

| Version | Date | Changements |
|---------|------|-------------|
| V0.9 | 2026-01-25 | Draft initial |
| V1.0 | 2026-01-25 | Intégration review ChatGPT : 4 invariants, statut UNMAPPED, soft conflicts, monitoring UNLINKED |

---

*Document de spécification technique MVP V1 - Usage B (Challenge de Texte)*
*Référence : ADR North Star v7*
*Date : 2026-01-25*
*Statut : V1.0 - Prêt pour implémentation*
