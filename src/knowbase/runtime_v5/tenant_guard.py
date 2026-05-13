"""V5 DSG TenantQueryGuard — défense en profondeur multi-tenant.

ADR V1.5 §3b/§3i.3 : protège contre les fuites cross-tenant qui résulteraient d'un bug
Cypher oubliant le filter tenant_id. Couche de validation **runtime** complémentaire
aux composite keys au niveau schéma.

Politique :
- Tout Cypher SELECT/MATCH/MERGE/UPDATE/DELETE sur les labels V5* DOIT inclure une
  contrainte `tenant_id = $tenant_id` (ou équivalent) dans la requête.
- Exception levée si la garde détecte un Cypher non-conforme.
- Audit log : chaque tentative de bypass est loggée + métrique OTel.

Limites du parser regex (vs AST Cypher complet) :
- Peut accepter des Cypher mal formés où `tenant_id` apparaît mais pas dans le bon
  contexte (ex: dans un commentaire). Atténué par : (1) tests cross-tenant leak e2e,
  (2) revues PR obligatoires pour Cypher V5, (3) impossible d'écrire sans tenant_id
  dans le schéma vu les composite keys.
- Faux positifs possibles : Cypher légitimes admin (purge full) qui n'ont pas de
  tenant_id par design — utiliser `allow_bypass=True` explicite avec audit.

Usage :
    from knowbase.runtime_v5.tenant_guard import TenantQueryGuard, TenantIsolationError

    guard = TenantQueryGuard(strict=True)
    guard.validate("MATCH (s:V5Section) RETURN s", tenant_id="default")
    # → raises TenantIsolationError car pas de filter tenant_id

    guard.validate("MATCH (s:V5Section {tenant_id: $tenant_id}) RETURN s", tenant_id="default")
    # → OK

Implémentation : wrapper léger autour de execute_query/execute_write qui valide
le Cypher AVANT exécution.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Labels V5 surveillés (extensible)
V5_LABELS = {"V5Document", "V5Section", "V5Table"}

# Patterns qui établissent une contrainte tenant_id (regex non-greedy, multi-ligne)
# Forme 1 : `{tenant_id: $tenant_id}` ou `{tenant_id: "..."}`  dans MATCH/MERGE
_TENANT_INLINE_PROP = re.compile(
    r"\{[^{}]*\btenant_id\s*:\s*(\$\w+|['\"][^'\"]+['\"])[^{}]*\}", re.IGNORECASE
)
# Forme 2 : `WHERE ... tenant_id = $tenant_id ...` (ou IN [..])
_TENANT_WHERE = re.compile(
    r"\btenant_id\s*(=|IN|=~)\s*[^\s,)]+", re.IGNORECASE
)
# Forme 3 : `SET n.tenant_id = $tenant_id` (uniquement valide pour CREATE+SET)
_TENANT_SET = re.compile(
    r"\bSET\b[^;]*?\.tenant_id\s*=\s*[^\s,;]+", re.IGNORECASE
)

# Détection labels V5 dans la requête (presence) OU procédures fulltext V5 OU index V5
_V5_SCOPE_PATTERN = re.compile(
    r":\s*(" + "|".join(sorted(V5_LABELS)) + r")\b"
    r"|['\"]v5_\w+_fulltext['\"]",
    re.IGNORECASE,
)

# DDL Neo4j (schema operations) — bypass validation : pas de tenant_id requis
_DDL_PATTERN = re.compile(
    r"^\s*(CREATE\s+(CONSTRAINT|INDEX|FULLTEXT\s+INDEX)|"
    r"DROP\s+(CONSTRAINT|INDEX)|"
    r"SHOW\s+(CONSTRAINTS|INDEXES))",
    re.IGNORECASE,
)


class TenantIsolationError(Exception):
    """Levée quand un Cypher V5 ne respecte pas l'isolation multi-tenant."""

    pass


class TenantQueryGuard:
    """Garde runtime qui valide les Cypher V5 pour éviter cross-tenant leaks.

    Args:
        strict: si True, lève TenantIsolationError sur violation.
                Si False, log warning seulement (mode dev).
        audit_logger: logger optionnel pour audit trail (default = module logger).
    """

    def __init__(self, strict: bool = True, audit_logger: Optional[logging.Logger] = None):
        self.strict = strict
        self.audit = audit_logger or logger
        # Compteurs internes (peut être exposé en métriques OTel plus tard)
        self._n_validated = 0
        self._n_violations = 0
        self._n_bypass = 0

    def validate(
        self,
        cypher: str,
        tenant_id: Optional[str] = None,
        allow_bypass: bool = False,
        reason: str = "",
    ) -> None:
        """Valide qu'un Cypher V5 respecte la politique multi-tenant.

        Args:
            cypher: requête à valider
            tenant_id: tenant attendu (pour log audit)
            allow_bypass: si True, skip validation (admin only, ex: tenant_purge global)
            reason: justification du bypass (audit trail)

        Raises:
            TenantIsolationError si strict=True et Cypher non-conforme.
        """
        self._n_validated += 1

        if allow_bypass:
            self._n_bypass += 1
            self.audit.warning(
                f"[TenantGuard BYPASS] tenant_id={tenant_id} reason={reason!r} "
                f"cypher_preview={cypher[:120]}..."
            )
            return

        # Skip validation si DDL (CREATE/DROP/SHOW constraints/indexes)
        if _DDL_PATTERN.search(cypher):
            return

        # Skip validation si pas de labels V5 ni d'index fulltext V5
        if not _V5_SCOPE_PATTERN.search(cypher):
            return

        # Cherche une contrainte tenant_id
        if (
            _TENANT_INLINE_PROP.search(cypher)
            or _TENANT_WHERE.search(cypher)
            or _TENANT_SET.search(cypher)
        ):
            return  # OK

        # Violation détectée
        self._n_violations += 1
        msg = (
            f"V5 Cypher missing tenant_id filter (cross-tenant leak risk). "
            f"Required: inline {{tenant_id: $tenant_id}} or WHERE tenant_id = ... clause. "
            f"Cypher: {cypher[:300]}..."
        )
        self.audit.error(f"[TenantGuard VIOLATION] tenant_id={tenant_id} {msg}")

        if self.strict:
            raise TenantIsolationError(msg)
        else:
            logger.warning(f"[TenantGuard WARN] {msg}")

    def stats(self) -> dict:
        """Retourne stats de la garde (audit + monitoring)."""
        return {
            "n_validated": self._n_validated,
            "n_violations": self._n_violations,
            "n_bypass": self._n_bypass,
        }

    def reset_stats(self) -> None:
        """Reset compteurs (utile pour tests)."""
        self._n_validated = 0
        self._n_violations = 0
        self._n_bypass = 0


# Singleton global pour usage rapide
_default_guard: Optional[TenantQueryGuard] = None


def get_tenant_guard(strict: bool = True) -> TenantQueryGuard:
    """Factory singleton."""
    global _default_guard
    if _default_guard is None:
        _default_guard = TenantQueryGuard(strict=strict)
    return _default_guard


def reset_tenant_guard() -> None:
    """Reset singleton (utile pour tests)."""
    global _default_guard
    _default_guard = None
