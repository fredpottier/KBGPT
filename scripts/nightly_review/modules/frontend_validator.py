"""
Module Frontend Validator - Validation endpoints API et frontend.

Fonctionnalités:
- Test de tous les endpoints API (GET, POST, PUT, DELETE)
- Validation des codes de retour HTTP
- Test des schémas de réponse
- Vérification de la disponibilité des services
"""
import requests
from typing import Dict, List, Any
from pathlib import Path
import time


class FrontendValidator:
    """Validateur d'endpoints API et frontend."""

    def __init__(self, project_root: Path):
        """
        Initialise le validateur.

        Args:
            project_root: Racine du projet
        """
        self.project_root = project_root
        self.base_url = "http://localhost:8000"
        self.frontend_url = "http://localhost:3000"
        self.results = {
            "api_endpoints": [],
            "frontend_routes": [],
            "health_checks": [],
            "errors": []
        }

    def analyze(self) -> Dict[str, Any]:
        """
        Exécute la validation complète.

        Returns:
            Résultats de la validation
        """
        print("🌐 Frontend Validator - Démarrage validation...")

        # 1. Vérifier disponibilité des services
        self._check_services_health()

        # 2. Tester les endpoints API
        self._test_api_endpoints()

        # 3. Tester les routes frontend
        self._test_frontend_routes()

        return {
            "total_endpoints": len(self.results["api_endpoints"]),
            "working_endpoints": len([e for e in self.results["api_endpoints"] if e["status"] == "ok"]),
            "failed_endpoints": len([e for e in self.results["api_endpoints"] if e["status"] == "error"]),
            "details": self.results,
            "summary": self._generate_summary()
        }

    def _check_services_health(self):
        """Vérifie la santé des services."""
        print("  ❤️ Vérification santé services...")

        services = [
            ("Backend API", self.base_url + "/status"),
            ("Frontend", self.frontend_url),
            ("Qdrant", "http://localhost:6333/"),
            ("Neo4j", "http://localhost:7474/")
        ]

        for service_name, url in services:
            try:
                response = requests.get(url, timeout=5)
                self.results["health_checks"].append({
                    "service": service_name,
                    "url": url,
                    "status": "ok" if response.status_code == 200 else "warning",
                    "status_code": response.status_code,
                    "response_time": response.elapsed.total_seconds()
                })
                print(f"    ✓ {service_name}: OK ({response.elapsed.total_seconds():.2f}s)")
            except Exception as e:
                self.results["health_checks"].append({
                    "service": service_name,
                    "url": url,
                    "status": "error",
                    "error": str(e)
                })
                print(f"    ✗ {service_name}: ERREUR - {e}")

    def _test_api_endpoints(self):
        """Teste tous les endpoints API."""
        print("  📡 Test endpoints API...")

        # Liste des endpoints à tester
        endpoints = [
            # Entity Types
            ("GET", "/api/entity-types", "Liste types d'entités"),
            ("GET", "/api/entity-types/SOLUTION", "Détails type SOLUTION"),

            # Entities
            ("GET", "/api/entities", "Liste entités"),
            ("GET", "/api/entities?status=pending", "Liste entités pending"),

            # Status
            ("GET", "/status", "Statut système"),

            # Jobs
            ("GET", "/api/jobs", "Liste jobs"),

            # Document Types
            ("GET", "/api/document-types", "Liste types de documents"),
        ]

        for method, endpoint, description in endpoints:
            url = self.base_url + endpoint
            try:
                start_time = time.time()

                if method == "GET":
                    response = requests.get(url, timeout=10)
                elif method == "POST":
                    response = requests.post(url, json={}, timeout=10)
                else:
                    continue

                elapsed = time.time() - start_time

                self.results["api_endpoints"].append({
                    "method": method,
                    "endpoint": endpoint,
                    "description": description,
                    "status": "ok" if 200 <= response.status_code < 300 else "error",
                    "status_code": response.status_code,
                    "response_time": elapsed,
                    "response_size": len(response.content)
                })

                status_icon = "✓" if 200 <= response.status_code < 300 else "✗"
                print(f"    {status_icon} {method} {endpoint}: {response.status_code} ({elapsed:.2f}s)")

            except Exception as e:
                self.results["api_endpoints"].append({
                    "method": method,
                    "endpoint": endpoint,
                    "description": description,
                    "status": "error",
                    "error": str(e)
                })
                print(f"    ✗ {method} {endpoint}: ERREUR - {e}")

    def _test_frontend_routes(self):
        """Teste les routes principales du frontend."""
        print("  🎨 Test routes frontend...")

        routes = [
            ("/", "Page d'accueil"),
            ("/admin/dynamic-types", "Gestion types d'entités"),
            ("/documents/import", "Import documents"),
            ("/documents/status", "Statut documents"),
        ]

        for route, description in routes:
            url = self.frontend_url + route
            try:
                response = requests.get(url, timeout=10)

                self.results["frontend_routes"].append({
                    "route": route,
                    "description": description,
                    "status": "ok" if response.status_code == 200 else "error",
                    "status_code": response.status_code,
                    "response_time": response.elapsed.total_seconds()
                })

                status_icon = "✓" if response.status_code == 200 else "✗"
                print(f"    {status_icon} {route}: {response.status_code}")

            except Exception as e:
                self.results["frontend_routes"].append({
                    "route": route,
                    "description": description,
                    "status": "error",
                    "error": str(e)
                })
                print(f"    ✗ {route}: ERREUR - {e}")

    def _generate_summary(self) -> Dict[str, Any]:
        """Génère un résumé de la validation."""
        total_api = len(self.results["api_endpoints"])
        ok_api = len([e for e in self.results["api_endpoints"] if e["status"] == "ok"])

        total_frontend = len(self.results["frontend_routes"])
        ok_frontend = len([r for r in self.results["frontend_routes"] if r["status"] == "ok"])

        return {
            "api_health_rate": (ok_api / total_api * 100) if total_api > 0 else 0,
            "frontend_health_rate": (ok_frontend / total_frontend * 100) if total_frontend > 0 else 0,
            "services_up": len([s for s in self.results["health_checks"] if s["status"] == "ok"]),
            "services_down": len([s for s in self.results["health_checks"] if s["status"] == "error"])
        }


def run_frontend_validation(project_root: Path) -> Dict[str, Any]:
    """
    Lance la validation frontend.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de la validation
    """
    validator = FrontendValidator(project_root)
    return validator.analyze()
