"""
Module Report Generator - Génération de rapports HTML/Markdown.

Fonctionnalités:
- Rapport HTML interactif
- Rapport Markdown pour documentation
- Graphiques et statistiques
- Export JSON pour intégration
"""
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import json


class ReportGenerator:
    """Générateur de rapports de revue nocturne."""

    def __init__(self, project_root: Path, output_dir: Path):
        """
        Initialise le générateur.

        Args:
            project_root: Racine du projet
            output_dir: Répertoire de sortie des rapports
        """
        self.project_root = project_root
        self.output_dir = output_dir
        self.timestamp = datetime.now()

    def generate_html_report(
        self,
        code_review: Dict[str, Any],
        architecture_analysis: Dict[str, Any],
        test_analysis: Dict[str, Any],
        frontend_validation: Dict[str, Any],
        db_safety: Dict[str, Any]
    ) -> str:
        """
        Génère un rapport HTML complet.

        Args:
            code_review: Résultats code review
            architecture_analysis: Résultats analyse architecture
            test_analysis: Résultats analyse tests
            frontend_validation: Résultats validation frontend
            db_safety: Résultats sécurité DB

        Returns:
            Chemin du fichier HTML généré
        """
        html = self._generate_html_content(
            code_review, architecture_analysis, test_analysis, frontend_validation, db_safety
        )

        output_file = self.output_dir / f"nightly_review_{self.timestamp.strftime('%Y%m%d_%H%M%S')}.html"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        return str(output_file)

    def _generate_html_content(
        self,
        code_review: Dict[str, Any],
        architecture_analysis: Dict[str, Any],
        test_analysis: Dict[str, Any],
        frontend_validation: Dict[str, Any],
        db_safety: Dict[str, Any]
    ) -> str:
        """Génère le contenu HTML."""

        return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Revue Nocturne - {self.timestamp.strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #f5f7fa;
            padding: 20px;
            color: #2c3e50;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }}

        h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        .timestamp {{
            opacity: 0.9;
            font-size: 1.1em;
        }}

        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .summary-card {{
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }}

        .summary-card:hover {{
            transform: translateY(-5px);
        }}

        .summary-card h3 {{
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.2em;
        }}

        .metric {{
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }}

        .metric.success {{ color: #27ae60; }}
        .metric.warning {{ color: #f39c12; }}
        .metric.error {{ color: #e74c3c; }}

        .section {{
            background: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 25px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}

        .section h2 {{
            color: #2c3e50;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
            font-size: 1.8em;
        }}

        .issue-list {{
            list-style: none;
        }}

        .issue-item {{
            padding: 15px;
            margin-bottom: 10px;
            border-left: 4px solid #3498db;
            background: #f8f9fa;
            border-radius: 4px;
        }}

        .issue-item.error {{ border-left-color: #e74c3c; }}
        .issue-item.warning {{ border-left-color: #f39c12; }}
        .issue-item.success {{ border-left-color: #27ae60; }}

        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            margin-right: 8px;
        }}

        .badge.error {{ background: #fee; color: #c00; }}
        .badge.warning {{ background: #fef3cd; color: #856404; }}
        .badge.success {{ background: #d4edda; color: #155724; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}

        th, td {{
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #ecf0f1;
        }}

        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #667eea;
        }}

        tr:hover {{
            background: #f8f9fa;
        }}

        .progress-bar {{
            width: 100%;
            height: 30px;
            background: #ecf0f1;
            border-radius: 15px;
            overflow: hidden;
            margin: 10px 0;
        }}

        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #27ae60, #2ecc71);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
        }}

        footer {{
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
            margin-top: 40px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🌙 Rapport de Revue Nocturne</h1>
            <div class="timestamp">
                Généré le {self.timestamp.strftime('%d/%m/%Y à %H:%M:%S')}
            </div>
        </header>

        <div class="summary">
            {self._generate_summary_cards(code_review, architecture_analysis, test_analysis, frontend_validation, db_safety)}
        </div>

        {self._generate_code_review_section(code_review)}
        {self._generate_architecture_analysis_section(architecture_analysis)}
        {self._generate_test_analysis_section(test_analysis)}
        {self._generate_frontend_validation_section(frontend_validation)}
        {self._generate_db_safety_section(db_safety)}

        <footer>
            <p>Rapport généré automatiquement par le système de revue nocturne SAP KB</p>
            <p>Projet: {self.project_root.name}</p>
        </footer>
    </div>
</body>
</html>
"""

    def _generate_summary_cards(
        self,
        code_review: Dict[str, Any],
        architecture_analysis: Dict[str, Any],
        test_analysis: Dict[str, Any],
        frontend_validation: Dict[str, Any],
        db_safety: Dict[str, Any]
    ) -> str:
        """Génère les cartes de résumé."""

        total_issues = code_review.get("total_issues", 0)
        arch_issues = architecture_analysis.get("total_issues", 0)
        coverage = test_analysis.get("coverage_percent", 0)
        api_health = frontend_validation.get("details", {}).get("summary", {}).get("api_health_rate", 0)
        snapshots = db_safety.get("total_snapshots", 0)

        return f"""
            <div class="summary-card">
                <h3>📋 Qualité du Code</h3>
                <div class="metric {'error' if total_issues > 50 else 'warning' if total_issues > 20 else 'success'}">
                    {total_issues}
                </div>
                <p>problèmes détectés</p>
            </div>

            <div class="summary-card">
                <h3>🏗️ Architecture</h3>
                <div class="metric {'error' if arch_issues > 30 else 'warning' if arch_issues > 10 else 'success'}">
                    {arch_issues}
                </div>
                <p>problèmes architecturaux</p>
            </div>

            <div class="summary-card">
                <h3>🧪 Couverture Tests</h3>
                <div class="metric {'success' if coverage > 70 else 'warning' if coverage > 50 else 'error'}">
                    {coverage:.1f}%
                </div>
                <p>du code couvert</p>
            </div>

            <div class="summary-card">
                <h3>🌐 Santé API</h3>
                <div class="metric {'success' if api_health > 90 else 'warning' if api_health > 70 else 'error'}">
                    {api_health:.1f}%
                </div>
                <p>endpoints fonctionnels</p>
            </div>

            <div class="summary-card">
                <h3>💾 Snapshots DB</h3>
                <div class="metric success">
                    {snapshots}
                </div>
                <p>sauvegardes créées</p>
            </div>
        """

    def _generate_code_review_section(self, code_review: Dict[str, Any]) -> str:
        """Génère la section code review."""

        details = code_review.get("details", {})
        dead_code = details.get("dead_code", [])
        quality_issues = details.get("quality_issues", [])
        complexity = details.get("complexity", [])

        return f"""
        <div class="section">
            <h2>📋 Revue de Code</h2>

            <h3>💀 Code Mort ({len(dead_code)} éléments)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item warning"><span class="badge warning">{item["type"]}</span><strong>{item["name"]}</strong> - {item["file"]}:{item["line"]}</li>' for item in dead_code[:10]])}
            </ul>

            <h3>⚠️ Problèmes de Qualité ({len(quality_issues)} problèmes)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item {item["severity"]}"><span class="badge {item["severity"]}">{item.get("code", "N/A")}</span>{item["message"]} - {item["file"]}:{item["line"]}</li>' for item in quality_issues[:15]])}
            </ul>

            <h3>🧮 Complexité Élevée ({len(complexity)} fonctions)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item {item["severity"]}"><strong>{item["function"]}</strong> - Complexité: {item["complexity"]} - {item["file"]}:{item["line"]}</li>' for item in complexity[:10]])}
            </ul>
        </div>
        """

    def _generate_architecture_analysis_section(self, architecture_analysis: Dict[str, Any]) -> str:
        """Génère la section analyse architecture."""

        details = architecture_analysis.get("details", {})
        circular_deps = details.get("circular_dependencies", [])
        god_objects = details.get("god_objects", [])
        layer_violations = details.get("layer_violations", [])
        anti_patterns = details.get("anti_patterns", [])
        performance_issues = details.get("performance_issues", [])
        recommendations = details.get("recommendations", [])

        return f"""
        <div class="section">
            <h2>🏗️ Analyse d'Architecture</h2>

            <h3>🔄 Dépendances Circulaires ({len(circular_deps)} cycles)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item error"><span class="badge error">CYCLE</span><strong>{cycle["cycle"]}</strong></li>' for cycle in circular_deps[:10]])}
            </ul>

            <h3>👹 God Objects ({len(god_objects)} classes)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item warning"><span class="badge warning">{obj["num_methods"]} méthodes</span><strong>{obj["class_name"]}</strong> - {obj["file"]}:{obj["line"]} ({obj["estimated_lines"]} lignes)</li>' for obj in god_objects[:10]])}
            </ul>

            <h3>🚫 Violations de Couches ({len(layer_violations)} violations)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item error"><span class="badge error">{v["current_layer"]} → {v["imports_from"]}</span>{v["violation"]} - {v["file"]}</li>' for v in layer_violations[:15]])}
            </ul>

            <h3>⚠️ Anti-Patterns ({len(anti_patterns)} détectés)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item warning"><span class="badge warning">{ap["type"]}</span>{ap["description"]} - {ap["file"]}:{ap.get("line", "N/A")}</li>' for ap in anti_patterns[:15]])}
            </ul>

            <h3>⚡ Problèmes de Performance ({len(performance_issues)} problèmes)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item {perf["severity"]}"><span class="badge {perf["severity"]}">{perf["type"]}</span>{perf["description"]} - {perf["file"]}:{perf["line"]}</li>' for perf in performance_issues[:15]])}
            </ul>

            <h3>💡 Recommandations ({len(recommendations)} recommandations)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item success"><span class="badge success">💡</span><strong>{rec["title"]}</strong> - {rec["description"]}</li>' for rec in recommendations[:10]])}
            </ul>
        </div>
        """

    def _generate_test_analysis_section(self, test_analysis: Dict[str, Any]) -> str:
        """Génère la section analyse tests."""

        total = test_analysis.get("total_tests", 0)
        passed = test_analysis.get("passed", 0)
        failed = test_analysis.get("failed", 0)
        coverage = test_analysis.get("coverage_percent", 0)
        missing_tests = test_analysis.get("details", {}).get("missing_tests", [])

        success_rate = (passed / total * 100) if total > 0 else 0

        return f"""
        <div class="section">
            <h2>🧪 Analyse des Tests</h2>

            <h3>Résultats d'Exécution</h3>
            <p><strong>{total}</strong> tests exécutés - <strong class="{'success' if failed == 0 else 'error'}">{passed} réussis</strong>, <strong class="{'error' if failed > 0 else 'success'}">{failed} échoués</strong></p>

            <div class="progress-bar">
                <div class="progress-fill" style="width: {success_rate}%">
                    {success_rate:.1f}%
                </div>
            </div>

            <h3>Couverture de Code</h3>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {coverage}%; background: linear-gradient(90deg, #3498db, #2980b9)">
                    {coverage:.1f}%
                </div>
            </div>

            <h3>Fonctions Sans Tests ({len(missing_tests)} fonctions)</h3>
            <ul class="issue-list">
                {"".join([f'<li class="issue-item warning"><span class="badge warning">{item["type"]}</span><strong>{item["function"]}</strong> - {item["file"]}:{item["line"]}</li>' for item in missing_tests[:20]])}
            </ul>
        </div>
        """

    def _generate_frontend_validation_section(self, frontend_validation: Dict[str, Any]) -> str:
        """Génère la section validation frontend."""

        details = frontend_validation.get("details", {})
        api_endpoints = details.get("api_endpoints", [])
        health_checks = details.get("health_checks", [])

        return f"""
        <div class="section">
            <h2>🌐 Validation Frontend & API</h2>

            <h3>Santé des Services</h3>
            <table>
                <thead>
                    <tr>
                        <th>Service</th>
                        <th>Statut</th>
                        <th>Temps de Réponse</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f'<tr><td>{check["service"]}</td><td><span class="badge {check["status"]}">{check["status"].upper()}</span></td><td>{check.get("response_time", "N/A")}</td></tr>' for check in health_checks])}
                </tbody>
            </table>

            <h3>Endpoints API</h3>
            <table>
                <thead>
                    <tr>
                        <th>Méthode</th>
                        <th>Endpoint</th>
                        <th>Statut</th>
                        <th>Code HTTP</th>
                        <th>Temps</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f'<tr><td>{ep["method"]}</td><td>{ep["endpoint"]}</td><td><span class="badge {ep["status"]}">{ep["status"].upper()}</span></td><td>{ep.get("status_code", "N/A")}</td><td>{ep.get("response_time", 0):.2f}s</td></tr>' for ep in api_endpoints])}
                </tbody>
            </table>
        </div>
        """

    def _generate_db_safety_section(self, db_safety: Dict[str, Any]) -> str:
        """Génère la section sécurité DB."""

        snapshots = db_safety.get("snapshots", [])

        return f"""
        <div class="section">
            <h2>💾 Sécurité des Données</h2>

            <h3>Snapshots Créés</h3>
            <table>
                <thead>
                    <tr>
                        <th>Base de Données</th>
                        <th>Taille (MB)</th>
                        <th>Statut</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f'<tr><td>{snap["database"]}</td><td>{snap.get("size_mb", "N/A")}</td><td><span class="badge {snap["status"]}">{snap["status"].upper()}</span></td></tr>' for snap in snapshots])}
                </tbody>
            </table>

            <p style="margin-top: 20px; color: #27ae60; font-weight: 600;">✓ Toutes les bases de données sont sauvegardées avant les tests</p>
        </div>
        """

    def generate_json_export(
        self,
        code_review: Dict[str, Any],
        architecture_analysis: Dict[str, Any],
        test_analysis: Dict[str, Any],
        frontend_validation: Dict[str, Any],
        db_safety: Dict[str, Any]
    ) -> str:
        """
        Génère un export JSON complet.

        Args:
            code_review: Résultats code review
            architecture_analysis: Résultats analyse architecture
            test_analysis: Résultats tests
            frontend_validation: Résultats frontend
            db_safety: Résultats DB safety

        Returns:
            Chemin du fichier JSON
        """
        output_file = self.output_dir / f"nightly_review_{self.timestamp.strftime('%Y%m%d_%H%M%S')}.json"

        data = {
            "timestamp": self.timestamp.isoformat(),
            "project": str(self.project_root),
            "code_review": code_review,
            "architecture_analysis": architecture_analysis,
            "test_analysis": test_analysis,
            "frontend_validation": frontend_validation,
            "db_safety": db_safety
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return str(output_file)
