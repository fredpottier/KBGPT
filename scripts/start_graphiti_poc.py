#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de démarrage et validation Graphiti POC
Phase 0 - Critère 1: Docker Compose Graphiti fonctionnel
"""

import subprocess
import time
import requests
import sys
import io
from pathlib import Path

# Fix encoding pour Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def run_command(cmd, description):
    """Execute une commande et affiche le résultat"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print(f"✅ {description} - SUCCESS")
            return True
        else:
            print(f"❌ {description} - FAILED")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"⏱️ {description} - TIMEOUT")
        return False
    except Exception as e:
        print(f"💥 {description} - ERROR: {e}")
        return False

def check_service_health(url, service_name, max_retries=20):
    """Vérifier la santé d'un service"""
    print(f"🩺 Vérification santé {service_name}...")

    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"✅ {service_name} - HEALTHY (tentative {attempt+1})")
                return True
        except requests.exceptions.RequestException:
            pass

        print(f"⏳ {service_name} - Tentative {attempt+1}/{max_retries}")
        time.sleep(5)

    print(f"❌ {service_name} - UNHEALTHY après {max_retries} tentatives")
    return False

def check_docker_compose_status():
    """Vérifier le statut des services Docker Compose"""
    print("📊 Statut services Docker Compose...")
    cmd = "docker-compose -f docker-compose.graphiti.yml ps"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    return "Up" in result.stdout

def main():
    """Fonction principale de démarrage et validation Graphiti"""
    print("🚀 GRAPHITI POC - Phase 0 Critère 1")
    print("=" * 50)

    project_root = Path(__file__).parent.parent
    print(f"📁 Répertoire projet: {project_root}")

    # Étape 1: Vérifier que docker-compose.graphiti.yml existe
    compose_file = project_root / "docker-compose.graphiti.yml"
    if not compose_file.exists():
        print(f"❌ Fichier {compose_file} non trouvé")
        return False
    print(f"✅ Fichier compose trouvé: {compose_file}")

    # Étape 2: Arrêter services existants si running
    print("\n🛑 Arrêt services Graphiti existants...")
    run_command("docker-compose -f docker-compose.graphiti.yml down",
                "Arrêt services existants")

    # Étape 3: Démarrer les services
    print("\n🚀 Démarrage services Graphiti...")
    if not run_command("docker-compose -f docker-compose.graphiti.yml up -d",
                      "Démarrage Docker Compose"):
        return False

    # Étape 4: Attendre que les services démarrent
    print("\n⏳ Attente démarrage services (60s)...")
    time.sleep(60)

    # Étape 5: Vérifier statut Docker Compose
    print("\n📊 Vérification statut services...")
    if not check_docker_compose_status():
        print("❌ Certains services ne sont pas UP")
        return False

    # Étape 6: Tests de santé des services
    services_health = []

    # Neo4j HTTP Interface
    services_health.append(
        check_service_health("http://localhost:7474", "Neo4j HTTP Interface")
    )

    # Graphiti API
    services_health.append(
        check_service_health("http://localhost:8300/health", "Graphiti API")
    )

    # Postgres (via Adminer)
    services_health.append(
        check_service_health("http://localhost:8080", "Postgres Adminer")
    )

    # Étape 7: Tests spécifiques Graphiti
    print("\n🔍 Tests API Graphiti spécifiques...")
    try:
        # Test API docs
        response = requests.get("http://localhost:8300/docs", timeout=10)
        if response.status_code == 200:
            print("✅ Documentation API Graphiti accessible")
        else:
            print(f"❌ Documentation API inaccessible: {response.status_code}")
            return False

        # Test API basic endpoint
        response = requests.get("http://localhost:8300/", timeout=10)
        if response.status_code in [200, 404]:  # 404 acceptable si pas de route root
            print("✅ API Graphiti répond")
        else:
            print(f"❌ API Graphiti ne répond pas: {response.status_code}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur test API Graphiti: {e}")
        return False

    # Étape 8: Résumé final
    print("\n" + "=" * 50)
    print("📊 RÉSUMÉ VALIDATION PHASE 0 CRITÈRE 1")
    print("=" * 50)

    all_healthy = all(services_health)

    if all_healthy:
        print("✅ Docker Compose Graphiti: FONCTIONNEL")
        print("✅ Neo4j: Accessible sur http://localhost:7474")
        print("✅ Graphiti API: Accessible sur http://localhost:8300")
        print("✅ Postgres Admin: Accessible sur http://localhost:8080")
        print("✅ Documentation: http://localhost:8300/docs")
        print("\n🎯 CRITÈRE 1 VALIDÉ: Docker Compose Graphiti fonctionnel")
        return True
    else:
        print("❌ CRITÈRE 1 ÉCHOUÉ: Services non fonctionnels")
        print("\n🔧 Debug: Vérifiez les logs avec:")
        print("docker-compose -f docker-compose.graphiti.yml logs")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)