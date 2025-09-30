"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { WarningIcon, ArrowBackIcon, CheckCircleIcon, CloseIcon } from "@chakra-ui/icons";
import Link from "next/link";

interface ConflictDetail {
  type: string;
  severity: string;
  description: string;
  conflicting_facts: Array<{
    uuid: string;
    subject: string;
    predicate: string;
    object: string;
    confidence: number;
    created_at: string;
    created_by: string;
    status: string;
  }>;
  resolution_suggestions: string[];
}

interface ConflictsResponse {
  conflicts: ConflictDetail[];
  total_conflicts: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
}

export default function ConflictsPage() {
  const [conflicts, setConflicts] = useState<ConflictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConflicts();
  }, []);

  const fetchConflicts = async () => {
    try {
      setLoading(true);
      const response = await fetch("/api/facts/conflicts/list");
      if (!response.ok) {
        throw new Error("Erreur chargement conflits");
      }
      const data = await response.json();
      setConflicts(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity.toLowerCase()) {
      case "critical":
        return "bg-red-100 text-red-800 border-red-200";
      case "high":
        return "bg-orange-100 text-orange-800 border-orange-200";
      case "medium":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      case "low":
        return "bg-blue-100 text-blue-800 border-blue-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "value_mismatch":
        return "bg-purple-100 text-purple-800";
      case "temporal_overlap":
        return "bg-indigo-100 text-indigo-800";
      case "contradiction":
        return "bg-red-100 text-red-800";
      case "duplicate":
        return "bg-yellow-100 text-yellow-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  };

  const getTypeName = (type: string) => {
    const names: Record<string, string> = {
      value_mismatch: "Valeurs Contradictoires",
      temporal_overlap: "Chevauchement Temporel",
      contradiction: "Contradiction Logique",
      duplicate: "Duplication",
    };
    return names[type] || type;
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="text-lg">Chargement des conflits...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Card className="p-6 bg-red-50 border-red-200">
          <p className="text-red-800">Erreur: {error}</p>
        </Card>
      </div>
    );
  }

  if (!conflicts) {
    return null;
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <Link
          href="/governance"
          className="inline-flex items-center text-sm text-gray-600 hover:text-gray-900 mb-4"
        >
          <ArrowBackIcon mr={1} />
          Retour au dashboard
        </Link>
        <h1 className="text-3xl font-bold mb-2">Résolution des Conflits</h1>
        <p className="text-gray-600">
          {conflicts.total_conflicts} conflit(s) nécessitant une résolution
        </p>
      </div>

      {/* Statistiques conflits */}
      {conflicts.total_conflicts > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
          <Card className="p-6">
            <h3 className="font-semibold mb-4">Par Type</h3>
            <div className="space-y-2">
              {Object.entries(conflicts.by_type).map(([type, count]) => (
                <div key={type} className="flex items-center justify-between">
                  <Badge variant="outline" className={getTypeColor(type)}>
                    {getTypeName(type)}
                  </Badge>
                  <span className="font-semibold">{count}</span>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-6">
            <h3 className="font-semibold mb-4">Par Sévérité</h3>
            <div className="space-y-2">
              {Object.entries(conflicts.by_severity).map(([severity, count]) => (
                <div key={severity} className="flex items-center justify-between">
                  <Badge variant="outline" className={getSeverityColor(severity)}>
                    {severity.toUpperCase()}
                  </Badge>
                  <span className="font-semibold">{count}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* Liste des conflits */}
      {conflicts.conflicts.length === 0 ? (
        <Card className="p-8 text-center">
          <CheckCircleIcon boxSize={12} mx="auto" mb={4} color="green.500" />
          <p className="text-lg font-semibold text-gray-900 mb-2">
            Aucun conflit détecté
          </p>
          <p className="text-gray-600 mb-4">
            Tous les facts sont cohérents entre eux
          </p>
          <Link href="/governance">
            <Button variant="outline">Retour au dashboard</Button>
          </Link>
        </Card>
      ) : (
        <div className="space-y-6">
          {conflicts.conflicts.map((conflict, idx) => (
            <Card key={idx} className="p-6">
              <div className="mb-4">
                <div className="flex items-center gap-3 mb-2">
                  <Badge variant="outline" className={getTypeColor(conflict.type)}>
                    {getTypeName(conflict.type)}
                  </Badge>
                  <Badge variant="outline" className={getSeverityColor(conflict.severity)}>
                    {conflict.severity.toUpperCase()}
                  </Badge>
                </div>
                <p className="text-gray-700">{conflict.description}</p>
              </div>

              {/* Facts en conflit */}
              <div className="space-y-4 mb-6">
                <h4 className="font-semibold text-sm text-gray-700">
                  Facts en Conflit:
                </h4>
                {conflict.conflicting_facts.map((fact, factIdx) => (
                  <Alert key={fact.uuid} className="border-l-4 border-orange-500">
                    <WarningIcon className="h-4 w-4" />
                    <AlertTitle className="flex items-center gap-2">
                      Fact #{factIdx + 1}
                      <Badge variant="secondary" className="text-xs">
                        {fact.status}
                      </Badge>
                      <span className="text-xs text-gray-500">
                        Confiance: {(fact.confidence * 100).toFixed(0)}%
                      </span>
                    </AlertTitle>
                    <AlertDescription>
                      <div className="mt-2 text-sm space-y-1">
                        <div className="grid grid-cols-3 gap-2">
                          <div>
                            <span className="font-medium">Sujet:</span> {fact.subject}
                          </div>
                          <div>
                            <span className="font-medium">Prédicat:</span>{" "}
                            <span className="text-blue-600">{fact.predicate}</span>
                          </div>
                          <div>
                            <span className="font-medium">Objet:</span> {fact.object}
                          </div>
                        </div>
                        <div className="text-xs text-gray-500 mt-2">
                          Créé par {fact.created_by} le{" "}
                          {new Date(fact.created_at).toLocaleString("fr-FR")}
                        </div>
                      </div>
                    </AlertDescription>
                  </Alert>
                ))}
              </div>

              {/* Suggestions de résolution */}
              {conflict.resolution_suggestions.length > 0 && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold text-sm text-gray-700 mb-3">
                    Suggestions de Résolution:
                  </h4>
                  <ul className="space-y-2">
                    {conflict.resolution_suggestions.map((suggestion, sugIdx) => (
                      <li key={sugIdx} className="flex items-start gap-2 text-sm">
                        <span className="text-blue-600 mt-1">•</span>
                        <span>{suggestion}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 mt-6 pt-4 border-t">
                {conflict.conflicting_facts.map((fact, factIdx) => (
                  <div key={fact.uuid} className="flex gap-2">
                    <Button
                      size="sm"
                      variant="default"
                      className="bg-green-600 hover:bg-green-700"
                    >
                      <CheckCircleIcon mr={1} />
                      Approuver Fact #{factIdx + 1}
                    </Button>
                    <Button size="sm" variant="destructive">
                      <CloseIcon mr={1} />
                      Rejeter Fact #{factIdx + 1}
                    </Button>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}