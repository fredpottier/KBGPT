#!/usr/bin/env python
"""
Script de verification de l'installation du Agent System.

Ce script verifie que tous les composants sont correctement installes et configurés.
"""
import sys
from pathlib import Path
from typing import List, Tuple

# Ajouter le chemin du projet
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


class InstallationVerifier:
    """Verifie l'installation du Agent System."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.passed: List[str] = []

    def check_imports(self) -> bool:
        """Verifie que tous les modules peuvent etre importes."""
        print("🔍 Verification des imports...")

        modules = [
            ("models", "Task, Plan, DevReport, ControlReport, AgentState"),
            ("tools", "FilesystemTool, ShellTool, GitTool, TestingTool, CodeAnalysisTool, DockerTool"),
            ("agents", "PlanningAgent, DevAgent, ControlAgent"),
            ("core", "AgentOrchestrator"),
            ("monitoring", "configure_langsmith"),
        ]

        all_ok = True
        for module, components in modules:
            try:
                __import__(module)
                self.passed.append(f"✓ Module '{module}' importe correctement")
            except ImportError as e:
                self.errors.append(f"✗ Erreur import '{module}': {e}")
                all_ok = False

        return all_ok

    def check_dependencies(self) -> bool:
        """Verifie les dependances externes."""
        print("\n🔍 Verification des dependances...")

        dependencies = [
            "langgraph",
            "langchain",
            "langchain_anthropic",
            "langsmith",
            "pydantic",
            "yaml",
            "git",  # GitPython
        ]

        all_ok = True
        for dep in dependencies:
            try:
                __import__(dep)
                self.passed.append(f"✓ Dependance '{dep}' installee")
            except ImportError:
                self.errors.append(f"✗ Dependance manquante: '{dep}'")
                all_ok = False

        return all_ok

    def check_config_files(self) -> bool:
        """Verifie la presence des fichiers de configuration."""
        print("\n🔍 Verification des fichiers de configuration...")

        config_files = [
            "config/agents_settings.yaml",
            "config/tools_permissions.yaml",
            "config/langsmith.yaml",
            "config/prompts/planning.yaml",
            "config/prompts/dev.yaml",
            "config/prompts/control.yaml",
        ]

        all_ok = True
        for config_file in config_files:
            file_path = project_root / config_file
            if file_path.exists():
                self.passed.append(f"✓ Config '{config_file}' presente")
            else:
                self.errors.append(f"✗ Config manquante: '{config_file}'")
                all_ok = False

        return all_ok

    def check_directories(self) -> bool:
        """Verifie la structure des repertoires."""
        print("\n🔍 Verification de la structure des repertoires...")

        required_dirs = [
            "src/models",
            "src/tools",
            "src/agents",
            "src/core",
            "src/monitoring",
            "config",
            "config/prompts",
            "scripts",
            "tests/unit",
            "tests/integration",
            "tests/e2e",
            "data",
            "plans",
            "reports",
        ]

        all_ok = True
        for dir_path in required_dirs:
            full_path = project_root / dir_path
            if full_path.exists() and full_path.is_dir():
                self.passed.append(f"✓ Repertoire '{dir_path}' present")
            else:
                self.warnings.append(f"⚠ Repertoire manquant: '{dir_path}' (peut etre cree automatiquement)")

        return all_ok

    def check_env_vars(self) -> bool:
        """Verifie les variables d'environnement."""
        print("\n🔍 Verification des variables d'environnement...")

        import os

        required_vars = {
            "ANTHROPIC_API_KEY": "Cle API Claude (OBLIGATOIRE)",
            "LANGSMITH_API_KEY": "Cle API LangSmith (recommande)",
        }

        all_ok = True
        for var, description in required_vars.items():
            if os.getenv(var):
                value = os.getenv(var)
                masked = f"{'*' * (len(value) - 8)}{value[-8:]}" if len(value) > 8 else "***"
                self.passed.append(f"✓ {var} definie ({masked})")
            else:
                if var == "ANTHROPIC_API_KEY":
                    self.errors.append(f"✗ {var} manquante - {description}")
                    all_ok = False
                else:
                    self.warnings.append(f"⚠ {var} manquante - {description}")

        return all_ok

    def test_basic_functionality(self) -> bool:
        """Test basique de fonctionnalite."""
        print("\n🔍 Test de fonctionnalite basique...")

        try:
            from models import Task, TaskPriority, create_initial_state

            # Creer une tache simple
            task = Task(
                task_id="test_001",
                title="Test Task",
                description="Test description",
                priority=TaskPriority.LOW,
            )

            # Creer l'etat initial
            state = create_initial_state(task)

            self.passed.append("✓ Creation de Task et AgentState fonctionne")
            return True

        except Exception as e:
            self.errors.append(f"✗ Erreur test basique: {e}")
            return False

    def run_all_checks(self) -> bool:
        """Execute toutes les verifications."""
        print("=" * 80)
        print("🤖 KnowWhere Agent System - Verification Installation")
        print("=" * 80)
        print()

        checks = [
            ("Imports", self.check_imports),
            ("Dependances", self.check_dependencies),
            ("Config Files", self.check_config_files),
            ("Directories", self.check_directories),
            ("Environment", self.check_env_vars),
            ("Functionality", self.test_basic_functionality),
        ]

        results = []
        for name, check_func in checks:
            result = check_func()
            results.append((name, result))

        # Afficher le resume
        print("\n" + "=" * 80)
        print("📊 RESUME DE LA VERIFICATION")
        print("=" * 80)

        print(f"\n✅ Tests Reussis: {len(self.passed)}")
        for msg in self.passed[:5]:  # Afficher les 5 premiers
            print(f"   {msg}")
        if len(self.passed) > 5:
            print(f"   ... et {len(self.passed) - 5} autres")

        if self.warnings:
            print(f"\n⚠️  Avertissements: {len(self.warnings)}")
            for msg in self.warnings:
                print(f"   {msg}")

        if self.errors:
            print(f"\n❌ Erreurs: {len(self.errors)}")
            for msg in self.errors:
                print(f"   {msg}")

        print("\n" + "=" * 80)

        all_passed = all(result for _, result in results)

        if all_passed and not self.errors:
            print("✅ VERIFICATION COMPLETE: Installation OK")
            print("\nPour demarrer:")
            print("  python scripts/run_orchestrator.py --task \"Votre tache\" --priority medium")
            return True
        else:
            print("❌ VERIFICATION ECHOUEE: Corriger les erreurs ci-dessus")
            print("\nActions recommandees:")
            if self.errors:
                if any("ANTHROPIC_API_KEY" in e for e in self.errors):
                    print("  1. Definir ANTHROPIC_API_KEY dans l'environnement")
                if any("import" in e.lower() for e in self.errors):
                    print("  2. Installer les dependances: pip install -r requirements.txt")
                if any("config" in e.lower() for e in self.errors):
                    print("  3. Verifier la presence des fichiers de configuration")
            return False

    def print_summary_stats(self):
        """Affiche les statistiques finales."""
        total_checks = len(self.passed) + len(self.warnings) + len(self.errors)

        print("\n" + "=" * 80)
        print("📈 STATISTIQUES")
        print("=" * 80)
        print(f"Total verifications: {total_checks}")
        print(f"Reussis: {len(self.passed)} ({len(self.passed)/total_checks*100:.1f}%)")
        print(f"Avertissements: {len(self.warnings)} ({len(self.warnings)/total_checks*100:.1f}%)")
        print(f"Erreurs: {len(self.errors)} ({len(self.errors)/total_checks*100:.1f}%)")
        print("=" * 80)


def main():
    """Point d'entree principal."""
    verifier = InstallationVerifier()
    success = verifier.run_all_checks()
    verifier.print_summary_stats()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
