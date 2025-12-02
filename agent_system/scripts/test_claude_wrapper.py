#!/usr/bin/env python3
"""
Test du wrapper Claude Code CLI avec tracing LangSmith.
"""
import sys
sys.path.insert(0, "/app/agent_system/src")

from core.claude_code_wrapper import ClaudeCodeWrapper


def main():
    print("=" * 60)
    print("Test ClaudeCodeWrapper avec OAuth + LangSmith")
    print("=" * 60)

    # Initialiser le wrapper
    wrapper = ClaudeCodeWrapper(
        project_name="knowwhere-agents-test",
        enable_tracing=True,
        working_directory="/app",
    )

    # Test simple
    print("\n[TEST] Execution tache simple...")
    result = wrapper.execute_task(
        task_description="Réponds juste 'OK' si tu fonctionnes correctement.",
        task_id="test_001",
        timeout_seconds=60,
    )

    print(f"\n[RESULT]")
    print(f"  Status: {result['status']}")
    print(f"  Duration: {result['duration_seconds']:.2f}s")
    print(f"  Output: {result['output'][:200] if result['output'] else 'None'}...")

    if result["status"] == "success":
        print("\n✅ Test réussi!")
        print("   - Claude CLI fonctionne via OAuth")
        if wrapper.langsmith_client:
            print("   - LangSmith tracing actif")
        else:
            print("   - LangSmith non configuré (pas d'API key)")
    else:
        print(f"\n❌ Test échoué: {result.get('error')}")

    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
