"""
ContradictionClassifier — Classification evidence-locked des contradictions.

Axe épistémique (tension_nature) :
  VALUE_CONFLICT, SCOPE_CONFLICT, TEMPORAL_CONFLICT, METHODOLOGICAL, COMPLEMENTARY, UNKNOWN

Niveau de tension (tension_level) :
  HARD, SOFT, NONE, UNKNOWN

Le LLM qualifie, il ne décide pas. Les flags de diffusion sont déduits par code (table P1).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.clustering.contradiction_rules import apply_structural_rules
from knowbase.claimfirst.clustering.tension_enums import TensionLevel, TensionNature

logger = logging.getLogger("[OSMOSE] contradiction_classifier")


# ── Prompt template ──────────────────────────────────────────────────────

CLASSIFIER_SYSTEM = """You are OSMOSE, an evidence-locked contradiction classifier.

You classify pairs of contradicting claims. For each pair you receive:
- The exact quotes of both claims
- Document metadata (title, type, date if available)
- ValueFrame (NUMBER/VERSION/UNTYPED + value + unit)
- The common ClaimKey (subject|PREDICATE)
- Context signals (same_doc_type, doc_date_order) as informative features

Your job is to classify, NOT to decide. If evidence is insufficient, output "unknown".

Classification axes:

tension_nature:
- value_conflict: mutually exclusive values on the same scope
- scope_conflict: different values because different contexts/populations/conditions
- temporal_conflict: recommendation that evolved over time
- methodological: different measurement methods, results coherent on interpretation
- complementary: seem contradictory but answer different questions
- unknown: not enough evidence to classify

tension_level:
- hard: clear divergence, high impact
- soft: real divergence but explainable
- none: no real divergence (false positive)
- unknown: insufficient elements

Output JSON array. Each element:
{
  "pair_index": 0,
  "tension_nature": "scope_conflict",
  "tension_level": "soft",
  "explanation": "Short factual explanation based on quotes",
  "scope_a": "context of claim A",
  "scope_b": "context of claim B"
}
"""

CLASSIFIER_USER_TEMPLATE = """Classify these {count} contradiction pairs:

{pairs_json}

Return a JSON array with {count} elements. No markdown fences, just JSON.
"""


class ContradictionClassifier:
    """Classifie les contradictions CONTRADICTS existantes dans Neo4j."""

    def __init__(self, neo4j_driver, batch_size: int = 5):
        self._driver = neo4j_driver
        self._batch_size = batch_size

    def load_unreviewed_pairs(
        self, tenant_id: str = "default", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Charge les paires CONTRADICTS sans reviewed=true."""
        query = """
        MATCH (c1:Claim)-[r:CONTRADICTS]->(c2:Claim)
        WHERE c1.tenant_id = $tenant_id
              AND (r.reviewed IS NULL OR r.reviewed = false)
        OPTIONAL MATCH (c1)-[:EXTRACTED_FROM]->(d1:DocumentContext)
        OPTIONAL MATCH (c2)-[:EXTRACTED_FROM]->(d2:DocumentContext)
        RETURN c1.claim_id AS id_a, c1.text AS text_a,
               c1.structured_form AS sf_a, c1.doc_id AS doc_id_a,
               c2.claim_id AS id_b, c2.text AS text_b,
               c2.structured_form AS sf_b, c2.doc_id AS doc_id_b,
               d1.primary_subject AS doc_title_a,
               d1.document_type AS doc_type_a,
               d1.temporal_scope AS doc_date_a,
               d2.primary_subject AS doc_title_b,
               d2.document_type AS doc_type_b,
               d2.temporal_scope AS doc_date_b
        LIMIT $limit
        """
        pairs = []
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, limit=limit)
            for r in result:
                pairs.append(dict(r))
        logger.info(f"[OSMOSE:ContradictionClassifier] {len(pairs)} paires non classifiées chargées")
        return pairs

    def build_llm_input(self, pair: Dict[str, Any]) -> Dict[str, Any]:
        """Construit l'input evidence-locked pour une paire."""
        sf_a = self._parse_sf(pair.get("sf_a"))
        sf_b = self._parse_sf(pair.get("sf_b"))

        # Construire claim_key
        claim_key = self._build_claim_key_from_sf(sf_a)

        # ValueFrame
        vf_a = self._build_value_frame(sf_a)
        vf_b = self._build_value_frame(sf_b)

        # Context signals
        doc_type_a = pair.get("doc_type_a") or ""
        doc_type_b = pair.get("doc_type_b") or ""
        doc_date_a = pair.get("doc_date_a") or ""
        doc_date_b = pair.get("doc_date_b") or ""

        doc_date_order = "unknown"
        if doc_date_a and doc_date_b:
            doc_date_order = "a_older" if doc_date_a < doc_date_b else "b_older"

        return {
            "claim_key": claim_key,
            "claim_a": {
                "text": (pair.get("text_a") or "")[:500],
                "doc_title": pair.get("doc_title_a") or "",
                "doc_type": doc_type_a,
                "value_frame": vf_a,
            },
            "claim_b": {
                "text": (pair.get("text_b") or "")[:500],
                "doc_title": pair.get("doc_title_b") or "",
                "doc_type": doc_type_b,
                "value_frame": vf_b,
            },
            "context_signals": {
                "same_doc_type": doc_type_a == doc_type_b and doc_type_a != "",
                "doc_date_order": doc_date_order,
            },
        }

    def _try_structural_rules(self, pair: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Tente de classifier une paire via les règles structurelles pré-LLM."""
        sf_a = self._parse_sf(pair.get("sf_a"))
        sf_b = self._parse_sf(pair.get("sf_b"))
        text_a = pair.get("text_a") or ""
        text_b = pair.get("text_b") or ""

        result = apply_structural_rules(sf_a, sf_b, text_a, text_b)
        if result:
            nature, level, explanation = result
            return {
                "tension_nature": nature.value,
                "tension_level": level.value,
                "explanation": explanation,
                "scope_a": "",
                "scope_b": "",
            }
        return None

    def classify_batch(
        self, pairs: List[Dict[str, Any]], dry_run: bool = False
    ) -> List[Dict[str, Any]]:
        """Classifie un batch de paires via règles structurelles puis LLM."""
        if not pairs:
            return []

        # Phase D : appliquer les règles structurelles pré-LLM
        rule_results: Dict[int, Dict[str, Any]] = {}
        llm_pairs: List[Tuple[int, Dict[str, Any]]] = []

        for i, pair in enumerate(pairs):
            rule_result = self._try_structural_rules(pair)
            if rule_result:
                rule_results[i] = rule_result
                logger.info(
                    f"[OSMOSE:ContradictionClassifier] Paire {i} classifiée par règle: "
                    f"{rule_result['tension_nature']}/{rule_result['tension_level']}"
                )
            else:
                llm_pairs.append((i, pair))

        if dry_run:
            logger.info(
                f"[DRY-RUN] {len(pairs)} paires: "
                f"{len(rule_results)} par règles, {len(llm_pairs)} pour LLM"
            )
            results = []
            for i in range(len(pairs)):
                if i in rule_results:
                    results.append({**rule_results[i], "pair_index": i, "source": "rule"})
                else:
                    results.append({"pair_index": i, "dry_run": True, "source": "llm"})
            return results

        # Construire inputs LLM pour les paires non résolues par règles
        llm_results: Dict[int, Dict[str, Any]] = {}
        if llm_pairs:
            llm_inputs = []
            index_map: Dict[int, int] = {}  # llm_index → original_index
            for llm_idx, (orig_idx, pair) in enumerate(llm_pairs):
                inp = self.build_llm_input(pair)
                inp["pair_index"] = llm_idx
                llm_inputs.append(inp)
                index_map[llm_idx] = orig_idx

            pairs_json = json.dumps(llm_inputs, ensure_ascii=False, indent=2)
            user_prompt = CLASSIFIER_USER_TEMPLATE.format(
                count=len(llm_inputs), pairs_json=pairs_json
            )

            from knowbase.common.llm_router import complete_metadata_extraction

            messages = [
                {"role": "system", "content": CLASSIFIER_SYSTEM.strip()},
                {"role": "user", "content": user_prompt.strip()},
            ]

            try:
                response = complete_metadata_extraction(
                    messages=messages,
                    max_tokens=2000,
                )
                parsed = self._parse_response(response, len(llm_pairs))
            except Exception as e:
                logger.error(f"[OSMOSE:ContradictionClassifier] Erreur LLM: {e}")
                parsed = [
                    {
                        "pair_index": i,
                        "tension_nature": "unknown",
                        "tension_level": "unknown",
                        "explanation": f"LLM error: {e}",
                    }
                    for i in range(len(llm_pairs))
                ]

            for r in parsed:
                llm_idx = r.get("pair_index", 0)
                orig_idx = index_map.get(llm_idx, llm_idx)
                llm_results[orig_idx] = r

        # Fusionner et persister
        all_results = []
        for i in range(len(pairs)):
            if i in rule_results:
                result = {**rule_results[i], "pair_index": i, "source": "rule"}
            elif i in llm_results:
                result = {**llm_results[i], "pair_index": i, "source": "llm"}
            else:
                result = {
                    "pair_index": i,
                    "tension_nature": "unknown",
                    "tension_level": "unknown",
                    "explanation": "Aucune classification disponible",
                }

            self._persist_classification(
                pairs[i]["id_a"], pairs[i]["id_b"], result
            )
            all_results.append(result)

        return all_results

    def classify_all(
        self, tenant_id: str = "default", dry_run: bool = False
    ) -> Dict[str, Any]:
        """Classifie toutes les contradictions non classifiées par batches."""
        all_pairs = self.load_unreviewed_pairs(tenant_id, limit=200)
        if not all_pairs:
            return {"total": 0, "classified": 0, "batches": 0}

        all_results = []
        batch_count = 0
        for i in range(0, len(all_pairs), self._batch_size):
            batch = all_pairs[i : i + self._batch_size]
            results = self.classify_batch(batch, dry_run=dry_run)
            all_results.extend(results)
            batch_count += 1
            logger.info(
                f"[OSMOSE:ContradictionClassifier] Batch {batch_count}: "
                f"{len(results)} paires classifiées"
            )

        # Stats
        stats = self._compute_stats(all_results)
        stats["total"] = len(all_pairs)
        stats["classified"] = len(all_results)
        stats["batches"] = batch_count
        return stats

    def get_stats(self, tenant_id: str = "default") -> Dict[str, Any]:
        """Statistiques des contradictions classifiées."""
        query = """
        MATCH (c1:Claim)-[r:CONTRADICTS]->(c2:Claim)
        WHERE c1.tenant_id = $tenant_id
        RETURN r.reviewed AS reviewed,
               r.tension_nature AS tension_nature,
               r.tension_level AS tension_level,
               count(r) AS cnt
        """
        stats: Dict[str, Any] = {
            "total": 0,
            "reviewed": 0,
            "unreviewed": 0,
            "by_nature": {},
            "by_level": {},
        }
        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            for r in result:
                cnt = r["cnt"]
                stats["total"] += cnt
                if r["reviewed"]:
                    stats["reviewed"] += cnt
                else:
                    stats["unreviewed"] += cnt

                nature = r["tension_nature"] or "unclassified"
                level = r["tension_level"] or "unclassified"
                stats["by_nature"][nature] = stats["by_nature"].get(nature, 0) + cnt
                stats["by_level"][level] = stats["by_level"].get(level, 0) + cnt

        return stats

    # ── Helpers privés ────────────────────────────────────────────────────

    def _parse_sf(self, sf: Any) -> Dict[str, str]:
        """Parse structured_form (str ou dict)."""
        if isinstance(sf, str):
            try:
                return json.loads(sf)
            except (json.JSONDecodeError, TypeError):
                return {}
        return sf or {}

    def _build_claim_key_from_sf(self, sf: Dict[str, str]) -> str:
        """Construit un claim_key simplifié depuis structured_form."""
        subject = sf.get("subject", "?")
        predicate = sf.get("predicate", "?")
        return f"{subject}|{predicate.upper()}"

    def _build_value_frame(self, sf: Dict[str, str]) -> Dict[str, Any]:
        """Construit un ValueFrame simplifié pour le prompt LLM."""
        object_text = sf.get("object", "")
        if not object_text:
            return {"type": "UNTYPED", "value": None, "unit": None}

        try:
            from knowbase.claimfirst.clustering.value_contradicts import (
                parse_value_frame,
            )
            vf = parse_value_frame(object_text)
            return {
                "type": vf.value_type.value.upper(),
                "value": vf.parsed_value if vf.value_type.value != "untyped" else object_text,
                "unit": vf.unit,
            }
        except ImportError:
            return {"type": "UNTYPED", "value": object_text, "unit": None}

    def _parse_response(
        self, response: str, expected_count: int
    ) -> List[Dict[str, Any]]:
        """Parse la réponse JSON du LLM."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"[OSMOSE:ContradictionClassifier] Parse JSON échoué: {e}")
            return [
                {
                    "pair_index": i,
                    "tension_nature": "unknown",
                    "tension_level": "unknown",
                    "explanation": f"JSON parse error: {e}",
                }
                for i in range(expected_count)
            ]

        if not isinstance(data, list):
            data = [data]

        # Valider et normaliser
        results = []
        for item in data:
            nature = item.get("tension_nature", "unknown")
            level = item.get("tension_level", "unknown")
            # Valider les valeurs
            try:
                TensionNature(nature)
            except ValueError:
                nature = "unknown"
            try:
                TensionLevel(level)
            except ValueError:
                level = "unknown"

            results.append({
                "pair_index": item.get("pair_index", len(results)),
                "tension_nature": nature,
                "tension_level": level,
                "explanation": item.get("explanation", ""),
                "scope_a": item.get("scope_a", ""),
                "scope_b": item.get("scope_b", ""),
            })

        return results

    def _persist_classification(
        self,
        claim_id_a: str,
        claim_id_b: str,
        classification: Dict[str, Any],
    ) -> None:
        """Persiste la classification sur la relation CONTRADICTS."""
        from knowbase.wiki.diffusion_flags import derive_full_diffusion_flags

        nature = classification.get("tension_nature", "unknown")
        level = classification.get("tension_level", "unknown")
        flags = derive_full_diffusion_flags(nature, level)

        query = """
        MATCH (c1:Claim {claim_id: $id_a})-[r:CONTRADICTS]->(c2:Claim {claim_id: $id_b})
        SET r.tension_nature = $tension_nature,
            r.tension_level = $tension_level,
            r.explanation = $explanation,
            r.scope_a = $scope_a,
            r.scope_b = $scope_b,
            r.show_in_article = $show_in_article,
            r.show_in_chat = $show_in_chat,
            r.show_in_homepage = $show_in_homepage,
            r.requires_review = $requires_review,
            r.reviewed = true,
            r.reviewed_at = datetime()
        """
        with self._driver.session() as session:
            session.run(
                query,
                id_a=claim_id_a,
                id_b=claim_id_b,
                tension_nature=nature,
                tension_level=level,
                explanation=classification.get("explanation", ""),
                scope_a=classification.get("scope_a", ""),
                scope_b=classification.get("scope_b", ""),
                **flags,
            )

    @staticmethod
    def _compute_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calcule les statistiques d'un batch de résultats."""
        by_nature: Dict[str, int] = {}
        by_level: Dict[str, int] = {}
        for r in results:
            nature = r.get("tension_nature", "unknown")
            level = r.get("tension_level", "unknown")
            by_nature[nature] = by_nature.get(nature, 0) + 1
            by_level[level] = by_level.get(level, 0) + 1
        return {"by_nature": by_nature, "by_level": by_level}
