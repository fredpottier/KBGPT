#!/usr/bin/env python3
"""
Script CLI pour executer un projet complet depuis un document.

Usage:
    python scripts/run_project.py \\
        --document "specs/my_project.md" \\
        --project-id "project_001" \\
        [--output-dir "data/projects/project_001"] \\
        [--resume] \\
        [--base-branch "main"]
"""
import argparse
import sys
import os
from pathlib import Path
from datetime import datetime

# Ajouter src/ au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.project_orchestrator import ProjectOrchestrator
from models import ProjectStatus
from monitoring import configure_langsmith


def parse_args():
    """Parse les arguments de la ligne de commande."""
    parser = argparse.ArgumentParser(
        description="Execute un projet complet depuis un document markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Executer un nouveau projet
  python scripts/run_project.py --document specs/auth_system.md --project-id auth_v1

  # Reprendre un projet interrompu
  python scripts/run_project.py --document specs/auth_system.md --project-id auth_v1 --resume

  # Specifier un repertoire de sortie custom
  python scripts/run_project.py \\
      --document specs/dashboard.md \\
      --project-id dashboard_v2 \\
      --output-dir /custom/path/output
        """
    )

    parser.add_argument(
        "--document",
        required=True,
        help="Chemin vers le document projet (markdown)",
    )

    parser.add_argument(
        "--project-id",
        required=True,
        help="ID unique du projet (ex: auth_v1, dashboard_v2)",
    )

    parser.add_argument(
        "--output-dir",
        help="Repertoire de sortie (defaut: data/projects/<project-id>)",
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reprendre l'execution depuis un checkpoint existant",
    )

    parser.add_argument(
        "--base-branch",
        default="main",
        help="Branche git de base (defaut: main)",
    )

    parser.add_argument(
        "--config",
        help="Chemin vers fichier de configuration custom",
    )

    parser.add_argument(
        "--no-langsmith",
        action="store_true",
        help="Desactiver LangSmith tracing",
    )

    return parser.parse_args()


def print_header():
    """Affiche le header du script."""
    print("=" * 80)
    print("🤖 KnowWhere Agent System - Project Orchestrator")
    print("=" * 80)
    print()


def print_summary(args):
    """Affiche un resume de la configuration."""
    print("📋 Configuration:")
    print(f"   Document: {args.document}")
    print(f"   Project ID: {args.project_id}")
    print(f"   Output Dir: {args.output_dir or f'data/projects/{args.project_id}'}")
    print(f"   Base Branch: {args.base_branch}")
    print(f"   Resume: {'Oui' if args.resume else 'Non'}")
    print()


def validate_document(document_path: str) -> None:
    """Valide que le document existe."""
    if not Path(document_path).exists():
        print(f"❌ Erreur: Document non trouve: {document_path}")
        sys.exit(1)

    if not document_path.endswith(".md"):
        print(f"⚠️  Avertissement: Le document n'est pas un fichier .md")


def main():
    """Point d'entree principal."""
    args = parse_args()

    print_header()
    print_summary(args)

    # Valider le document
    validate_document(args.document)

    # Configurer LangSmith (optionnel)
    if not args.no_langsmith:
        try:
            configure_langsmith()
            print("✅ LangSmith tracing active")
        except Exception as e:
            print(f"⚠️  LangSmith non disponible: {str(e)}")
    print()

    # Initialiser l'orchestrateur
    print("🔧 Initialisation du Project Orchestrator...")
    orchestrator = ProjectOrchestrator(
        workspace_root=os.environ.get("WORKSPACE_ROOT", "/app"),
        config_path=args.config,
    )
    print("✅ Orchestrateur initialise")

    # Executer le projet
    print()
    print("⚙️  Debut de l'execution du projet...")
    print("-" * 80)

    start_time = datetime.now()

    try:
        report = orchestrator.execute_project(
            document_path=args.document,
            project_id=args.project_id,
            output_dir=args.output_dir,
            resume_from_checkpoint=args.resume,
            base_branch=args.base_branch,
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print("-" * 80)
        print()
        print("=" * 80)
        print("📊 RAPPORT FINAL")
        print("=" * 80)
        print()
        print(f"Project ID: {report.project_id}")
        print(f"Titre: {report.project_title}")
        print(f"Status: {report.status.value.upper()}")
        print()
        print("Statistiques:")
        print(f"  - Total taches: {report.total_tasks}")
        print(f"  - Completees: {report.completed_tasks}")
        print(f"  - Echouees: {report.failed_tasks}")
        print(f"  - Sautees: {report.skipped_tasks}")
        print()
        print(f"Duree totale: {duration:.1f}s")
        print(f"Branche Git: {report.git_branch}")
        print()

        if report.status == ProjectStatus.COMPLETED:
            print("✅ PROJET COMPLETE AVEC SUCCES!")
            print()
            print(f"La branche '{report.git_branch}' contient toutes les modifications.")
            print(f"Pour merge: git checkout {args.base_branch} && git merge {report.git_branch}")
            return 0
        elif report.status == ProjectStatus.ROLLED_BACK:
            print("❌ PROJET ECHOUE - ROLLBACK EFFECTUE")
            print()
            print(f"La branche '{report.git_branch}' a ete supprimee.")
            print("Consultez le rapport pour plus de details.")
            return 1
        else:
            print(f"⚠️  PROJET TERMINE AVEC STATUS: {report.status.value}")
            return 1

    except KeyboardInterrupt:
        print()
        print()
        print("⏸️  Execution interrompue par l'utilisateur")
        print()
        print("💡 Utilisez --resume pour reprendre l'execution:")
        print(f"   python scripts/run_project.py \\")
        print(f"       --document {args.document} \\")
        print(f"       --project-id {args.project_id} \\")
        print(f"       --resume")
        return 130

    except Exception as e:
        print()
        print("=" * 80)
        print("❌ ERREUR FATALE")
        print("=" * 80)
        print()
        print(f"Type: {type(e).__name__}")
        print(f"Message: {str(e)}")
        print()
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
