#!/usr/bin/env python
"""
Script principal pour exécuter l'orchestrateur d'agents.

Usage:
    python scripts/run_orchestrator.py --task "Implémenter feature X" --requirements "REQ-001,REQ-002"
"""
import argparse
import sys
from pathlib import Path

# Ajouter le chemin du projet au PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from models import Task, TaskPriority
from core.orchestrator import AgentOrchestrator
from monitoring import configure_langsmith


def parse_args() -> argparse.Namespace:
    """Parse les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description="KnowWhere Agent System - Orchestrateur Principal"
    )

    parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="Description de la tâche à exécuter"
    )

    parser.add_argument(
        "--requirements",
        type=str,
        default="",
        help="Requirements séparées par des virgules (ex: REQ-001,REQ-002)"
    )

    parser.add_argument(
        "--priority",
        type=str,
        choices=["low", "medium", "high", "critical"],
        default="medium",
        help="Priorité de la tâche"
    )

    parser.add_argument(
        "--config",
        type=str,
        default="agent_system/config/",
        help="Chemin vers le dossier de configuration"
    )

    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Exécuter en mode daemon (pour Docker)"
    )

    return parser.parse_args()


def create_task_from_args(args: argparse.Namespace) -> Task:
    """Crée un objet Task depuis les arguments."""
    requirements = [r.strip() for r in args.requirements.split(",")] if args.requirements else []

    task = Task(
        task_id=f"task_{hash(args.task) % 10000:04d}",
        title=args.task[:50],
        description=args.task,
        requirements=requirements,
        priority=TaskPriority[args.priority.upper()],
    )

    return task


def main() -> None:
    """Point d'entrée principal."""
    args = parse_args()

    print("=" * 80)
    print("🤖 KnowWhere Agent System - Orchestrateur")
    print("=" * 80)
    print()

    # Configurer LangSmith
    print("🔧 Configuration LangSmith...")
    try:
        configure_langsmith(config_path=f"{args.config}/langsmith.yaml")
    except Exception as e:
        print(f"⚠️  Erreur configuration LangSmith: {e}")
    print()

    # Créer la tâche
    task = create_task_from_args(args)
    print(f"📋 Tâche: {task.title}")
    print(f"🔑 Task ID: {task.task_id}")
    print(f"⚡ Priorité: {task.priority.value}")
    print(f"📝 Requirements: {len(task.requirements)}")
    print()

    # Initialiser l'orchestrateur
    print("🚀 Initialisation de l'orchestrateur...")
    try:
        orchestrator = AgentOrchestrator(config_path=args.config)
        print("✅ Orchestrateur initialisé")
        print()

        # Exécuter l'orchestration
        print("⚙️  Début de l'orchestration...")
        print("-" * 80)
        result = orchestrator.run(task=task)
        print("-" * 80)
        print()

        # Afficher les résultats
        print("✅ Orchestration terminée!")
        print(f"📊 Status: {result['status']}")
        print(f"📋 Plan ID: {result.get('plan_id', 'N/A')}")
        print(f"🔧 Dev Reports: {len(result.get('dev_reports', []))}")
        print(f"🔍 Control Reports: {len(result.get('control_reports', []))}")
        print(f"🔄 Iterations: {result.get('iterations', 0)}")
        print(f"✓  Validation: {'PASSED ✅' if result['validation_passed'] else 'FAILED ❌'}")
        print()

        # Afficher les détails des rapports
        if result.get('dev_reports'):
            print("📝 Dev Reports:")
            for i, report in enumerate(result['dev_reports'], 1):
                print(f"   {i}. {report.get('subtask_id', 'N/A')} - {report.get('status', 'N/A')}")

        if result.get('control_reports'):
            print("🔍 Control Reports:")
            for i, report in enumerate(result['control_reports'], 1):
                print(f"   {i}. Score: {report.get('overall_score', 0):.2f} - {report.get('decision', 'N/A')}")

        print()

    except Exception as e:
        print(f"❌ Erreur lors de l'orchestration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if args.daemon:
        print("🔄 Mode daemon activé - en attente...")
        import time
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
