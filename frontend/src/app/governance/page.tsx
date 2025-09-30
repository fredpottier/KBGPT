"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import {
  CheckCircleIcon,
  CloseIcon,
  TimeIcon,
  WarningIcon,
  ArrowUpIcon,
  Icon,
} from "@chakra-ui/icons";
import { FiFileText } from "react-icons/fi";

interface FactStats {
  total_facts: number;
  by_status: {
    proposed: number;
    approved: number;
    rejected: number;
    conflicted: number;
  };
  pending_approval: number;
  conflicts_count: number;
  group_id: string;
}

export default function GovernanceDashboard() {
  const [stats, setStats] = useState<FactStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      setLoading(true);
      const response = await fetch("/api/facts/stats/overview");
      if (!response.ok) {
        throw new Error("Erreur chargement statistiques");
      }
      const data = await response.json();
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-lg">Chargement des statistiques...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="p-6 bg-red-50 border-red-200">
          <p className="text-red-800">Erreur: {error}</p>
        </Card>
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  const statCards = [
    {
      title: "Total Facts",
      value: stats.total_facts,
      icon: FiFileText,
      color: "blue.600",
      bgColor: "blue.50",
    },
    {
      title: "En Attente",
      value: stats.pending_approval,
      icon: TimeIcon,
      color: "yellow.600",
      bgColor: "yellow.50",
      link: "/governance/pending",
    },
    {
      title: "Approuvés",
      value: stats.by_status.approved,
      icon: CheckCircleIcon,
      color: "green.600",
      bgColor: "green.50",
    },
    {
      title: "Conflits",
      value: stats.conflicts_count,
      icon: WarningIcon,
      color: "red.600",
      bgColor: "red.50",
      link: "/governance/conflicts",
    },
    {
      title: "Rejetés",
      value: stats.by_status.rejected,
      icon: CloseIcon,
      color: "gray.600",
      bgColor: "gray.50",
    },
    {
      title: "Proposés",
      value: stats.by_status.proposed,
      icon: ArrowUpIcon,
      color: "purple.600",
      bgColor: "purple.50",
    },
  ];

  const approvalRate = stats.total_facts > 0
    ? ((stats.by_status.approved / stats.total_facts) * 100).toFixed(1)
    : "0";

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">Gouvernance des Facts</h1>
        <p className="text-gray-600">
          Dashboard de validation et gestion des connaissances
        </p>
        <div className="mt-2">
          <Badge variant="outline">{stats.group_id}</Badge>
        </div>
      </div>

      {/* Statistiques principales */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        {statCards.map((stat) => {
          const IconComponent = stat.icon;
          const CardContent = (
            <Card
              p={6}
              _hover={{ shadow: "lg" }}
              transition="all 0.2s"
              cursor={stat.link ? "pointer" : "default"}
            >
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
                <div>
                  <p style={{ fontSize: "0.875rem", color: "#718096", marginBottom: "0.25rem" }}>{stat.title}</p>
                  <p style={{ fontSize: "1.875rem", fontWeight: "bold" }}>{stat.value}</p>
                </div>
                <div style={{ padding: "0.75rem", borderRadius: "0.5rem", backgroundColor: stat.bgColor }}>
                  <Icon as={IconComponent} boxSize={6} color={stat.color} />
                </div>
              </div>
            </Card>
          );

          return stat.link ? (
            <Link key={stat.title} href={stat.link}>
              {CardContent}
            </Link>
          ) : (
            <div key={stat.title}>{CardContent}</div>
          );
        })}
      </div>

      {/* Métriques de qualité */}
      <Card className="p-6 mb-8">
        <h2 className="text-xl font-semibold mb-4">Métriques de Qualité</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <p className="text-sm text-gray-600 mb-1">Taux d'Approbation</p>
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold">{approvalRate}%</p>
              <p className="text-sm text-gray-500">
                ({stats.by_status.approved}/{stats.total_facts})
              </p>
            </div>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">Taux de Conflits</p>
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold">
                {stats.total_facts > 0
                  ? ((stats.conflicts_count / stats.total_facts) * 100).toFixed(1)
                  : "0"}
                %
              </p>
              <p className="text-sm text-gray-500">
                ({stats.conflicts_count} conflits)
              </p>
            </div>
          </div>
          <div>
            <p className="text-sm text-gray-600 mb-1">En Attente Validation</p>
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold">{stats.pending_approval}</p>
              <p className="text-sm text-gray-500">facts</p>
            </div>
          </div>
        </div>
      </Card>

      {/* Actions rapides */}
      <Card className="p-6">
        <h2 className="text-xl font-semibold mb-4">Actions Rapides</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Link href="/governance/pending">
            <Button className="w-full" variant="default">
              <TimeIcon mr={2} boxSize={4} />
              Valider Facts
            </Button>
          </Link>
          <Link href="/governance/conflicts">
            <Button className="w-full" variant="outline">
              <WarningIcon mr={2} boxSize={4} />
              Résoudre Conflits
            </Button>
          </Link>
          <Link href="/governance/facts">
            <Button className="w-full" variant="outline">
              <Icon as={FiFileText} mr={2} boxSize={4} />
              Tous les Facts
            </Button>
          </Link>
          <Link href="/governance/timeline">
            <Button className="w-full" variant="outline">
              <ArrowUpIcon mr={2} boxSize={4} />
              Timeline
            </Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}