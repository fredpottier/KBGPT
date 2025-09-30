"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ArrowBackIcon, Icon } from "@chakra-ui/icons";
import { FiFilter, FiSearch } from "react-icons/fi";
import Link from "next/link";

interface Fact {
  uuid: string;
  subject: string;
  predicate: string;
  object: string;
  confidence: number;
  status: string;
  created_at: string;
  created_by: string;
  source?: string;
  tags: string[];
  version: number;
  group_id: string;
  approved_by?: string;
  approved_at?: string;
  rejected_by?: string;
  rejected_at?: string;
  rejection_reason?: string;
}

export default function AllFactsPage() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filtres
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [subjectFilter, setSubjectFilter] = useState("");
  const [predicateFilter, setPredicateFilter] = useState("");
  const [creatorFilter, setCreatorFilter] = useState("");

  // Pagination
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const limit = 20;

  useEffect(() => {
    fetchFacts();
  }, [statusFilter, page]);

  const fetchFacts = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        limit: limit.toString(),
        offset: (page * limit).toString(),
      });

      if (statusFilter !== "all") {
        params.append("status", statusFilter);
      }
      if (subjectFilter) {
        params.append("subject", subjectFilter);
      }
      if (predicateFilter) {
        params.append("predicate", predicateFilter);
      }
      if (creatorFilter) {
        params.append("created_by", creatorFilter);
      }

      const response = await fetch(`/api/facts?${params}`);
      if (!response.ok) {
        throw new Error("Erreur chargement facts");
      }
      const data = await response.json();
      setFacts(data.facts || []);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => {
    setPage(0);
    fetchFacts();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "approved":
        return "bg-green-100 text-green-800 border-green-200";
      case "rejected":
        return "bg-red-100 text-red-800 border-red-200";
      case "proposed":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      case "conflicted":
        return "bg-orange-100 text-orange-800 border-orange-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const totalPages = Math.ceil(total / limit);

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Card className="p-6 bg-red-50 border-red-200">
          <p className="text-red-800">Erreur: {error}</p>
        </Card>
      </div>
    );
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
        <h1 className="text-3xl font-bold mb-2">Tous les Facts</h1>
        <p className="text-gray-600">{total} fact(s) au total</p>
      </div>

      {/* Filtres */}
      <Card className="p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Icon as={FiFilter} boxSize={5} color="gray.600" />
          <h3 className="font-semibold">Filtres</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
          <div>
            <label className="text-sm font-medium mb-1 block">Statut</label>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                <SelectItem value="proposed">Proposés</SelectItem>
                <SelectItem value="approved">Approuvés</SelectItem>
                <SelectItem value="rejected">Rejetés</SelectItem>
                <SelectItem value="conflicted">Conflits</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">Sujet</label>
            <Input
              value={subjectFilter}
              onChange={(e) => setSubjectFilter(e.target.value)}
              placeholder="Filtrer par sujet..."
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">Prédicat</label>
            <Input
              value={predicateFilter}
              onChange={(e) => setPredicateFilter(e.target.value)}
              placeholder="Filtrer par prédicat..."
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">Créateur</label>
            <Input
              value={creatorFilter}
              onChange={(e) => setCreatorFilter(e.target.value)}
              placeholder="Filtrer par créateur..."
            />
          </div>
        </div>

        <Button onClick={handleSearch} className="w-full md:w-auto">
          <Icon as={FiSearch} className="h-4 w-4 mr-2" />
          Rechercher
        </Button>
      </Card>

      {/* Liste des facts */}
      {loading ? (
        <div className="text-center py-8">Chargement...</div>
      ) : facts.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-lg text-gray-600">Aucun fact trouvé</p>
        </Card>
      ) : (
        <>
          <div className="space-y-4 mb-6">
            {facts.map((fact) => (
              <Card key={fact.uuid} className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-3">
                      <Badge variant="outline" className={getStatusColor(fact.status)}>
                        {fact.status}
                      </Badge>
                      <Badge variant="secondary">v{fact.version}</Badge>
                      <span className="text-sm text-gray-500">
                        Confiance: {(fact.confidence * 100).toFixed(0)}%
                      </span>
                      <span className="text-xs text-gray-400">ID: {fact.uuid.substring(0, 8)}...</span>
                    </div>

                    <div className="mb-4">
                      <div className="grid grid-cols-3 gap-2 text-sm">
                        <div>
                          <span className="font-medium text-gray-700">Sujet:</span>
                          <p className="font-semibold">{fact.subject}</p>
                        </div>
                        <div>
                          <span className="font-medium text-gray-700">Prédicat:</span>
                          <p className="font-medium text-blue-600">{fact.predicate}</p>
                        </div>
                        <div>
                          <span className="font-medium text-gray-700">Objet:</span>
                          <p className="font-semibold">{fact.object}</p>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-4 text-sm text-gray-600">
                      <span>Créé par: {fact.created_by}</span>
                      <span>•</span>
                      <span>{new Date(fact.created_at).toLocaleString("fr-FR")}</span>
                      {fact.source && (
                        <>
                          <span>•</span>
                          <span>Source: {fact.source}</span>
                        </>
                      )}
                    </div>

                    {fact.approved_by && (
                      <div className="mt-2 text-sm text-green-600">
                        ✓ Approuvé par {fact.approved_by} le{" "}
                        {fact.approved_at && new Date(fact.approved_at).toLocaleString("fr-FR")}
                      </div>
                    )}

                    {fact.rejected_by && (
                      <div className="mt-2 text-sm text-red-600">
                        ✗ Rejeté par {fact.rejected_by} le{" "}
                        {fact.rejected_at && new Date(fact.rejected_at).toLocaleString("fr-FR")}
                        {fact.rejection_reason && (
                          <span className="block mt-1">Raison: {fact.rejection_reason}</span>
                        )}
                      </div>
                    )}

                    {fact.tags.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {fact.tags.map((tag, idx) => (
                          <Badge key={idx} variant="secondary" className="text-xs">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button
                variant="outline"
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
              >
                Précédent
              </Button>
              <span className="text-sm text-gray-600">
                Page {page + 1} sur {totalPages}
              </span>
              <Button
                variant="outline"
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page === totalPages - 1}
              >
                Suivant
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}