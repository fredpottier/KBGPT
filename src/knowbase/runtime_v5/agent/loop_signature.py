"""V5 ReasoningAgent — Loop signature richer + novelty_score.

⚠️ DEPRECATED (A3.6, 2026-05-21) — Réf ADR_PARSE_EVALUATE_RUNTIME §10.2.

Ce module sera supprimé une fois :
- Bench A3.8 validé (gates GA3-5/6/7 atteints)
- Phase B cross-domain validée
- V5.1 retiré comme endpoint de référence

V6 (runtime_a3) utilise un Plan déterministe + boucle re-plan bornée
(orchestrator.py), sans agent loop. L'anti-thrash novelty_score n'est plus
nécessaire.

⚠️ NE PAS étendre. Pour nouveaux développements, voir runtime_a3/.

---

ADR V1.5 §3e (Sprint S4.1) : anti-thrash robuste.

Le POC actuel détecte la stagnation par `STAGNATION_MAX = 2 iter without new
section read` + `ANTI_LOOP_HARD = 3 identical calls`. Ces règles ratent les
patterns du type :
    iter 1 : read(A)        → nouvelle section
    iter 2 : read(B)        → nouvelle section
    iter 3 : expand(A)      → nouvelle section
    iter 4 : expand(B)      → nouvelle section
    iter 5 : read(A)        → DUPLICATE mais 3 iters intermédiaires ont passé
    ...
Le compteur stagnation reset à chaque nouvelle section, donc on tourne en rond
sans déclenchement.

Solution V1.5 ADR : `loop_signature = (tool, normalized_args, evidence_gain,
novelty_score)`. Calcul `novelty_score` = 1 - similarity_to_recent_evidence
(rolling window). Si `novelty_score_last3 < 0.1` → force conclude.

Implémentation domain-agnostic :
- normalized_args : ordre canonique des clés + str(value) (insensible à l'ordre LLM)
- evidence_gain : len(new_text_chars) / len(seen_text_chars) (universel)
- novelty_score : Jaccard(set(tokens_recent), set(tokens_new)) — métrique
  universelle, pas de vocabulaire métier
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Warning DEPRECATED (A3.6, 2026-05-21) — émis une fois par import
if not globals().get("_DEPRECATED_WARNED", False):
    logger.warning(
        "⚠️ DEPRECATED module loaded: runtime_v5.agent.loop_signature. "
        "Replaced by deterministic Plan + bounded re-plan in runtime_a3.orchestrator. "
        "Removal scheduled post-A3.8. "
        "See doc/ongoing/POST_A36_V51_SUPPRESSIONS_AUDIT_2026-05-21.md"
    )
    _DEPRECATED_WARNED = True


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _normalize_args(args: Any) -> str:
    """Sérialise args en chaîne canonique (clés triées, str values)."""
    if args is None:
        return ""
    if isinstance(args, dict):
        return json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return str(args)


def _tokenize(text: str) -> set[str]:
    """Tokenization minimaliste : lowercase + split sur non-alphanum.

    Universal : aucune liste de stopwords corpus-spécifique.
    """
    if not text:
        return set()
    return set(re.findall(r"\w+", text.lower()))


def _jaccard(a: set, b: set) -> float:
    """Similarité Jaccard : |A ∩ B| / |A ∪ B|."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ─── LoopSignature dataclass ────────────────────────────────────────────────


@dataclass
class LoopSignature:
    """Signature complète d'une itération agent.

    Fields :
        tool : nom du tool appelé (ex: "read", "find_in")
        normalized_args : args canonicalisés (string déterministe)
        evidence_gain : gain d'information (0-1) cette iter
        novelty_score : Jaccard moyen vs N derniers évidence_tokens (0-1)
        iter_idx : numéro itération (0-indexed)
    """
    tool: str
    normalized_args: str
    evidence_gain: float
    novelty_score: float
    iter_idx: int

    def signature_hash(self) -> str:
        """Hash compact (tool + args) pour détection duplicate exacte."""
        payload = f"{self.tool}|{self.normalized_args}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# ─── LoopSignatureTracker ────────────────────────────────────────────────────


@dataclass
class LoopSignatureTracker:
    """Suit les signatures itération par itération, déclenche stop si thrash.

    Args (configurable) :
        novelty_window : N dernières iter sur lesquelles on calcule novelty
        novelty_threshold : si novelty_score moyen sur window < ce seuil → force conclude
        duplicate_signatures_threshold : N signatures identiques consécutives → break

    Fields runtime :
        history : deque de toutes les LoopSignature (FIFO bounded)
        evidence_tokens_history : deque de set[token] (rolling window)
    """
    novelty_window: int = 3
    novelty_threshold: float = 0.10
    duplicate_signatures_threshold: int = 3
    history: deque[LoopSignature] = field(default_factory=lambda: deque(maxlen=64))
    evidence_tokens_history: deque[set[str]] = field(default_factory=lambda: deque(maxlen=10))
    _seen_signature_hashes: dict[str, int] = field(default_factory=dict)

    def record(
        self,
        tool: str,
        args: Any,
        new_evidence_text: str,
        prior_evidence_chars: int,
        iter_idx: int,
    ) -> LoopSignature:
        """Enregistre une itération et retourne sa signature.

        Args:
            tool : tool appelé
            args : args du call
            new_evidence_text : texte retourné par le tool (string concaténée)
            prior_evidence_chars : nombre de chars déjà vus avant cette iter
            iter_idx : numéro iter
        """
        normalized = _normalize_args(args)
        # evidence_gain : ratio chars nouveau vs vu (capé 0-1)
        new_chars = len(new_evidence_text or "")
        # Si prior_evidence_chars=0 et new_chars>0 → gain=1.0
        # Si new_chars=0 → gain=0
        if new_chars == 0:
            evidence_gain = 0.0
        elif prior_evidence_chars == 0:
            evidence_gain = 1.0
        else:
            evidence_gain = min(1.0, new_chars / (prior_evidence_chars + new_chars))

        # novelty_score : Jaccard min vs N derniers tokens
        new_tokens = _tokenize(new_evidence_text)
        if not self.evidence_tokens_history:
            novelty = 1.0  # première observation
        else:
            sims = [_jaccard(new_tokens, prev) for prev in self.evidence_tokens_history]
            avg_sim = sum(sims) / len(sims) if sims else 0.0
            novelty = 1.0 - avg_sim  # plus c'est similaire, moins c'est novel

        sig = LoopSignature(
            tool=tool,
            normalized_args=normalized,
            evidence_gain=evidence_gain,
            novelty_score=novelty,
            iter_idx=iter_idx,
        )

        # Update history
        self.history.append(sig)
        self.evidence_tokens_history.append(new_tokens)
        h = sig.signature_hash()
        self._seen_signature_hashes[h] = self._seen_signature_hashes.get(h, 0) + 1
        return sig

    # ─── Stop conditions ─────────────────────────────────────────────────────

    def should_stop_for_low_novelty(self) -> tuple[bool, str]:
        """Returns (should_stop, reason).

        Stop si novelty_score_last_window < threshold.
        """
        if len(self.history) < self.novelty_window:
            return False, ""
        recent = list(self.history)[-self.novelty_window:]
        avg_novelty = sum(s.novelty_score for s in recent) / len(recent)
        if avg_novelty < self.novelty_threshold:
            return True, (
                f"novelty_score_avg_last_{self.novelty_window}={avg_novelty:.3f} "
                f"< threshold={self.novelty_threshold}"
            )
        return False, ""

    def should_stop_for_duplicate_calls(self) -> tuple[bool, str]:
        """Returns (should_stop, reason).

        Stop si même (tool, args) appelé `duplicate_signatures_threshold` fois.
        """
        for h, count in self._seen_signature_hashes.items():
            if count >= self.duplicate_signatures_threshold:
                # Retrouve la signature pour debug
                sample = next(
                    (s for s in self.history if s.signature_hash() == h), None
                )
                tool = sample.tool if sample else "?"
                args = sample.normalized_args[:80] if sample else "?"
                return True, (
                    f"duplicate_signature {tool}({args}...) called {count}x "
                    f">= threshold {self.duplicate_signatures_threshold}"
                )
        return False, ""

    def should_stop(self) -> tuple[bool, str]:
        """Évalue toutes les stop conditions et retourne la première qui trigger."""
        for check in (
            self.should_stop_for_duplicate_calls,
            self.should_stop_for_low_novelty,
        ):
            ok, reason = check()
            if ok:
                return True, reason
        return False, ""

    # ─── Stats ───────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        if not self.history:
            return {
                "n_iter": 0,
                "n_unique_signatures": 0,
                "avg_novelty": 0.0,
                "avg_evidence_gain": 0.0,
                "duplicate_max_count": 0,
            }
        return {
            "n_iter": len(self.history),
            "n_unique_signatures": len(self._seen_signature_hashes),
            "avg_novelty": sum(s.novelty_score for s in self.history) / len(self.history),
            "avg_evidence_gain": sum(s.evidence_gain for s in self.history) / len(self.history),
            "duplicate_max_count": max(self._seen_signature_hashes.values()) if self._seen_signature_hashes else 0,
        }
