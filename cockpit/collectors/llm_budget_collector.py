"""
Collecteur LLM Budget — coûts de session + soldes API.

- Session : compteur local reset au tap, delta depuis /api/tokens/stats
- OpenAI : dépenses via API admin org/costs
- Anthropic : saisie manuelle, persistée dans un fichier local
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cockpit.config import (
    OSMOSIS_API_URL, LLM_LOW_THRESHOLD, LLM_CRITICAL_THRESHOLD,
)
from cockpit.models import LLMSessionStatus, LLMBalanceStatus

# Modèles hébergés localement ou sur EC2 burst — pas de coût par token
LOCAL_MODEL_PREFIXES = ("burst/", "qwen", "llama", "phi", "ollama/", "sagemaker/")


def _is_paid_model(model_name: str) -> bool:
    """True si le modèle génère un coût API (OpenAI, Anthropic)."""
    lower = model_name.lower()
    return not any(lower.startswith(p) for p in LOCAL_MODEL_PREFIXES)

logger = logging.getLogger(__name__)

# Fichier de persistance des soldes manuels
BALANCES_FILE = Path(__file__).parent.parent / "db" / "manual_balances.json"


class LLMBudgetCollector:
    def __init__(self):
        self._session_started_at: str = datetime.now(timezone.utc).isoformat()
        self._session_cost: float = 0.0
        self._session_calls: int = 0
        self._session_breakdown: dict[str, float] = {}
        self._last_total_cost: Optional[float] = None
        self._cost_per_minute: float = 0.0
        self._cost_history: list[tuple[float, float]] = []

        # Admin API keys
        self._openai_admin_key: str = self._load_env_key("OPENAI_ADMIN_KEY")
        self._anthropic_admin_key: str = self._load_env_key("ANTHROPIC_ADMIN_KEY")
        self._openai_month_cost: Optional[float] = None
        self._anthropic_month_cost: Optional[float] = None
        self._openai_last_check: float = 0
        self._anthropic_last_check: float = 0

        # Soldes manuels persistés (fallback si pas d'admin key)
        self._manual_balances: dict[str, float] = self._load_manual_balances()
        self._manual_balances_at_reset: dict[str, float] = dict(self._manual_balances)

    def _load_env_key(self, var_name: str) -> str:
        """Charge une clé depuis l'env ou le .env local."""
        val = os.getenv(var_name, "")
        if val:
            return val
        # Fallback : lire .env
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{var_name}="):
                    return line.split("=", 1)[1].strip()
        return ""

    def _load_manual_balances(self) -> dict:
        """Charge les soldes manuels depuis le fichier."""
        if BALANCES_FILE.exists():
            try:
                return json.loads(BALANCES_FILE.read_text())
            except Exception:
                pass
        return {}

    def save_manual_balance(self, provider: str, value: float):
        """Sauvegarde un solde saisi manuellement + snapshot du coût mensuel actuel."""
        # Snapshot du coût mensuel au moment de la saisie
        # pour ne déduire que le DELTA depuis ce moment
        if provider == "openai":
            baseline = self._fetch_openai_monthly_cost()
        elif provider == "anthropic" and self._anthropic_admin_key:
            baseline = self._fetch_anthropic_monthly_cost()
        else:
            baseline = 0.0

        self._manual_balances[provider] = value
        self._manual_balances[f"{provider}_baseline"] = baseline
        self._manual_balances[f"{provider}_saved_at"] = time.time()

        BALANCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        BALANCES_FILE.write_text(json.dumps(self._manual_balances, indent=2))
        logger.info(
            f"[COCKPIT:LLM] Balance saved: {provider}=${value:.2f} "
            f"(baseline monthly cost=${baseline:.2f})"
        )

    def reset_session(self):
        """Remet le compteur de session à zéro."""
        self._session_started_at = datetime.now(timezone.utc).isoformat()
        self._session_cost = 0.0
        self._session_calls = 0
        self._session_breakdown = {}
        self._last_total_cost = None
        self._cost_history = []
        self._cost_per_minute = 0.0
        # Reset baseline admin API
        if hasattr(self, '_admin_baseline_cost'):
            del self._admin_baseline_cost
        # Snapshot des soldes manuels au moment du reset
        self._manual_balances_at_reset = dict(self._manual_balances)
        logger.info("[COCKPIT:LLM] Session reset")

    def collect_session(self) -> LLMSessionStatus:
        self._poll_osmosis_api()
        # Fallback : si l'API OSMOSIS ne répond pas, utiliser les admin APIs
        if self._session_cost == 0 and self._last_total_cost is None:
            self._poll_from_admin_apis()
        return LLMSessionStatus(
            session_cost_usd=round(self._session_cost, 4),
            session_started_at=self._session_started_at,
            session_calls=self._session_calls,
            session_breakdown=dict(self._session_breakdown),
            cost_per_minute=round(self._cost_per_minute, 4),
        )

    def collect_balances(self) -> LLMBalanceStatus:
        status = LLMBalanceStatus(
            low_threshold=LLM_LOW_THRESHOLD,
            critical_threshold=LLM_CRITICAL_THRESHOLD,
        )

        # OpenAI — via admin API (dépenses mensuelles)
        openai_bal = self._check_openai_balance()
        if openai_bal is not None:
            status.openai_balance = openai_bal
            status.openai_status = self._status_from_balance(openai_bal)

        # Anthropic — via admin API si clé dispo, sinon solde manuel - session cost
        anthropic_bal = self._check_anthropic_balance()
        if anthropic_bal is not None:
            status.anthropic_balance = anthropic_bal
            status.anthropic_status = self._status_from_balance(anthropic_bal)

        return status

    def _status_from_balance(self, bal: float) -> str:
        if bal < LLM_CRITICAL_THRESHOLD:
            return "critical"
        if bal < LLM_LOW_THRESHOLD:
            return "low"
        return "ok"

    def _poll_from_admin_apis(self):
        """Fallback : utilise les admin APIs pour le coût du jour en cours."""
        now = time.time()
        # Ne pas poller trop souvent (toutes les 60s max)
        if hasattr(self, '_last_admin_poll') and now - self._last_admin_poll < 60:
            return
        self._last_admin_poll = now

        today_openai = self._fetch_openai_today_cost()
        today_anthropic = self._fetch_anthropic_today_cost() if self._anthropic_admin_key else 0

        total_today = today_openai + today_anthropic

        if not hasattr(self, '_admin_baseline_cost'):
            # Premier appel après reset — c'est la baseline
            self._admin_baseline_cost = total_today

        self._session_cost = max(0, total_today - self._admin_baseline_cost)

        if today_openai > 0:
            self._session_breakdown["OpenAI (today)"] = today_openai
        if today_anthropic > 0:
            self._session_breakdown["Anthropic (today)"] = today_anthropic

        # Calculer $/min
        self._cost_history.append((now, self._session_cost))
        self._cost_history = [(t, c) for t, c in self._cost_history if now - t < 120]
        if len(self._cost_history) >= 2:
            oldest_t, oldest_c = self._cost_history[0]
            dt = now - oldest_t
            if dt > 0:
                self._cost_per_minute = ((self._session_cost - oldest_c) / dt) * 60

    def _fetch_openai_today_cost(self) -> float:
        """Coût OpenAI du jour via admin API."""
        if not self._openai_admin_key:
            return 0.0
        try:
            import httpx
            from datetime import datetime
            now = datetime.now(timezone.utc)
            start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())
            headers = {"Authorization": f"Bearer {self._openai_admin_key}"}
            resp = httpx.get(
                f"https://api.openai.com/v1/organization/costs?start_time={start}&limit=1&bucket_width=1d",
                headers=headers, timeout=15.0,
            )
            if resp.status_code != 200:
                return 0.0
            total = 0.0
            for bucket in resp.json().get("data", []):
                for result in bucket.get("results", []):
                    amount = result.get("amount", {})
                    if isinstance(amount, dict):
                        try:
                            total += float(amount.get("value", 0))
                        except (ValueError, TypeError):
                            pass
            return total
        except Exception as e:
            logger.debug(f"[COCKPIT:LLM] OpenAI today cost failed: {e}")
            return 0.0

    def _fetch_anthropic_today_cost(self) -> float:
        """Coût Anthropic du jour via admin API."""
        try:
            import httpx
            from datetime import datetime
            now = datetime.now(timezone.utc)
            start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            headers = {
                "anthropic-version": "2023-06-01",
                "x-api-key": self._anthropic_admin_key,
            }
            resp = httpx.get(
                f"https://api.anthropic.com/v1/organizations/cost_report"
                f"?starting_at={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f"&ending_at={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f"&bucket_width=1d",
                headers=headers, timeout=15.0,
            )
            if resp.status_code != 200:
                return 0.0
            total = 0.0
            for bucket in resp.json().get("data", []):
                for result in bucket.get("results", []):
                    try:
                        total += float(result.get("cost", 0))
                    except (ValueError, TypeError):
                        pass
            return total
        except Exception:
            return 0.0

    def _poll_osmosis_api(self):
        """Interroge l'API OSMOSIS pour les stats de tokens (endpoint sans auth)."""
        try:
            import httpx
            resp = httpx.get(
                f"{OSMOSIS_API_URL}/api/tokens/cockpit-costs",
                timeout=5.0,
            )
            if resp.status_code != 200:
                return

            data = resp.json()
            total_cost = data.get("total_cost", 0.0)
            total_calls = data.get("total_calls", 0)
            now = time.time()

            if self._last_total_cost is not None:
                delta_cost = total_cost - self._last_total_cost
                if delta_cost > 0:
                    by_model = data.get("by_model", {})

                    # Séparer coûts payants (API) et locaux (EC2/burst)
                    paid_cost = sum(
                        s.get("cost", 0) for m, s in by_model.items()
                        if _is_paid_model(m)
                    )
                    total_all = sum(s.get("cost", 0) for s in by_model.values())

                    # Seuls les coûts payants comptent dans le session cost
                    if total_all > 0:
                        paid_ratio = paid_cost / total_all
                        self._session_cost += delta_cost * paid_ratio
                    self._session_calls = total_calls

                    # Breakdown par modèle (tous, pour visibilité)
                    if by_model and total_all > 0:
                        for model, stats in by_model.items():
                            ratio = stats.get("cost", 0) / total_all
                            self._session_breakdown[model] = (
                                self._session_breakdown.get(model, 0)
                                + delta_cost * ratio
                            )

            self._last_total_cost = total_cost

            # $/min glissant
            self._cost_history.append((now, self._session_cost))
            self._cost_history = [(t, c) for t, c in self._cost_history if now - t < 120]
            if len(self._cost_history) >= 2:
                oldest_t, oldest_c = self._cost_history[0]
                dt = now - oldest_t
                if dt > 0:
                    self._cost_per_minute = ((self._session_cost - oldest_c) / dt) * 60

        except Exception as e:
            logger.debug(f"[COCKPIT:LLM] API poll failed: {e}")

    def _check_openai_balance(self) -> Optional[float]:
        """
        Calcule le solde OpenAI restant.

        Logique : solde_saisi - (coût_mensuel_actuel - coût_mensuel_au_moment_saisie)
        Ainsi seules les NOUVELLES dépenses sont déduites.
        """
        manual = self._manual_balances.get("openai")
        if manual is None:
            return None

        now = time.time()
        # Rafraîchir toutes les 5 minutes
        if now - self._openai_last_check < 300 and self._openai_month_cost is not None:
            pass
        elif self._openai_admin_key:
            self._openai_month_cost = self._fetch_openai_monthly_cost()
            self._openai_last_check = now

        baseline = self._manual_balances.get("openai_baseline", 0)
        current_month = self._openai_month_cost or 0
        delta = max(0, current_month - baseline)

        return round(manual - delta, 2)

    def _check_anthropic_balance(self) -> Optional[float]:
        """
        Calcule le solde Anthropic restant.

        Avec admin key : solde_saisi - delta_coût_mensuel
        Sans admin key : solde_saisi - coût_session_claude (via TokenTracker)
        """
        manual = self._manual_balances.get("anthropic")
        if manual is None:
            return None

        if self._anthropic_admin_key:
            # Avec admin API
            now = time.time()
            if now - self._anthropic_last_check < 300 and self._anthropic_month_cost is not None:
                pass
            else:
                self._anthropic_month_cost = self._fetch_anthropic_monthly_cost()
                self._anthropic_last_check = now

            baseline = self._manual_balances.get("anthropic_baseline", 0)
            current_month = self._anthropic_month_cost or 0
            delta = max(0, current_month - baseline)
            return round(manual - delta, 2)
        else:
            # Sans admin API : déduire les coûts Claude de la session
            claude_session_cost = sum(
                v for k, v in self._session_breakdown.items()
                if "claude" in k.lower() or "haiku" in k.lower() or "sonnet" in k.lower()
            )
            return round(manual - claude_session_cost, 2)

    def _fetch_anthropic_monthly_cost(self) -> float:
        """Récupère le coût Anthropic du mois en cours via l'Admin API."""
        try:
            import httpx
            from datetime import datetime

            now = datetime.now(timezone.utc)
            start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

            headers = {
                "anthropic-version": "2023-06-01",
                "x-api-key": self._anthropic_admin_key,
            }
            resp = httpx.get(
                f"https://api.anthropic.com/v1/organizations/cost_report"
                f"?starting_at={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f"&ending_at={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f"&bucket_width=1d",
                headers=headers,
                timeout=15.0,
            )

            if resp.status_code != 200:
                logger.warning(
                    f"[COCKPIT:LLM] Anthropic cost API: {resp.status_code} {resp.text[:200]}"
                )
                return 0.0

            data = resp.json()
            total = 0.0
            for bucket in data.get("data", []):
                for result in bucket.get("results", []):
                    # Le coût est en USD (string décimal en cents)
                    cost = result.get("cost", 0)
                    try:
                        total += float(cost)
                    except (ValueError, TypeError):
                        pass

            logger.info(f"[COCKPIT:LLM] Anthropic monthly cost: ${total:.2f}")
            return total

        except Exception as e:
            logger.warning(f"[COCKPIT:LLM] Anthropic cost fetch failed: {e}")
            return 0.0

    def _fetch_openai_monthly_cost(self) -> float:
        """Récupère le coût OpenAI du mois en cours via l'API admin."""
        try:
            import httpx
            from datetime import datetime

            # Premier jour du mois courant
            now = datetime.now(timezone.utc)
            start = int(datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp())

            headers = {"Authorization": f"Bearer {self._openai_admin_key}"}
            resp = httpx.get(
                f"https://api.openai.com/v1/organization/costs"
                f"?start_time={start}&limit=31&bucket_width=1d",
                headers=headers,
                timeout=15.0,
            )

            if resp.status_code != 200:
                logger.warning(f"[COCKPIT:LLM] OpenAI costs API: {resp.status_code}")
                return 0.0

            data = resp.json()
            total = 0.0
            for bucket in data.get("data", []):
                for result in bucket.get("results", []):
                    amount = result.get("amount", {})
                    if isinstance(amount, dict):
                        val = amount.get("value", 0)
                        try:
                            total += float(val)
                        except (ValueError, TypeError):
                            pass

            logger.info(f"[COCKPIT:LLM] OpenAI monthly cost: ${total:.2f}")
            return total

        except Exception as e:
            logger.warning(f"[COCKPIT:LLM] OpenAI cost fetch failed: {e}")
            return 0.0
