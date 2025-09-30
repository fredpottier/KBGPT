"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { CheckCircleIcon, CloseIcon, ViewIcon, TimeIcon, ArrowBackIcon } from "@chakra-ui/icons";
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
}

export default function PendingFactsPage() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFact, setSelectedFact] = useState<Fact | null>(null);
  const [actionDialog, setActionDialog] = useState<{
    open: boolean;
    type: "approve" | "reject" | null;
  }>({ open: false, type: null });
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    fetchPendingFacts();
  }, []);

  const fetchPendingFacts = async () => {
    try {
      setLoading(true);
      const response = await fetch("/api/facts?status=proposed&limit=100");
      if (!response.ok) {
        throw new Error("Erreur chargement facts");
      }
      const data = await response.json();
      setFacts(data.facts || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!selectedFact) return;

    try {
      setProcessing(true);
      const response = await fetch(`/api/facts/${selectedFact.uuid}/approve`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approver_id: "current_user", // À remplacer par user ID réel
          comment: comment,
        }),
      });

      if (!response.ok) {
        throw new Error("Erreur approbation fact");
      }

      // Rafraîchir la liste
      await fetchPendingFacts();
      closeActionDialog();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setProcessing(false);
    }
  };

  const handleReject = async () => {
    if (!selectedFact || !reason) {
      alert("Veuillez fournir un motif de rejet");
      return;
    }

    try {
      setProcessing(true);
      const response = await fetch(`/api/facts/${selectedFact.uuid}/reject`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rejector_id: "current_user", // À remplacer par user ID réel
          reason: reason,
          comment: comment,
        }),
      });

      if (!response.ok) {
        throw new Error("Erreur rejet fact");
      }

      // Rafraîchir la liste
      await fetchPendingFacts();
      closeActionDialog();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setProcessing(false);
    }
  };

  const openActionDialog = (fact: Fact, type: "approve" | "reject") => {
    setSelectedFact(fact);
    setActionDialog({ open: true, type });
    setComment("");
    setReason("");
  };

  const closeActionDialog = () => {
    setActionDialog({ open: false, type: null });
    setSelectedFact(null);
    setComment("");
    setReason("");
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="text-lg">Chargement des facts en attente...</div>
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
        <h1 className="text-3xl font-bold mb-2">Facts en Attente de Validation</h1>
        <p className="text-gray-600">{facts.length} fact(s) à valider</p>
      </div>

      {/* Liste des facts */}
      {facts.length === 0 ? (
        <Card className="p-8 text-center">
          <TimeIcon boxSize={12} mx="auto" mb={4} color="gray.400" />
          <p className="text-lg text-gray-600">Aucun fact en attente de validation</p>
          <Link href="/governance">
            <Button className="mt-4" variant="outline">
              Retour au dashboard
            </Button>
          </Link>
        </Card>
      ) : (
        <div className="space-y-4">
          {facts.map((fact) => (
            <Card key={fact.uuid} className="p-6">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-3">
                    <Badge variant="outline" className="bg-yellow-50 text-yellow-700 border-yellow-200">
                      {fact.status}
                    </Badge>
                    <Badge variant="secondary">v{fact.version}</Badge>
                    <span className="text-sm text-gray-500">
                      Confiance: {(fact.confidence * 100).toFixed(0)}%
                    </span>
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

                <div className="flex gap-2 ml-4">
                  <Button
                    size="sm"
                    variant="default"
                    onClick={() => openActionDialog(fact, "approve")}
                    className="bg-green-600 hover:bg-green-700"
                  >
                    <CheckCircleIcon mr={1} />
                    Approuver
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => openActionDialog(fact, "reject")}
                  >
                    <CloseIcon mr={1} />
                    Rejeter
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Dialog Approve/Reject */}
      <Dialog open={actionDialog.open} onOpenChange={(open) => !open && closeActionDialog()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {actionDialog.type === "approve" ? "Approuver" : "Rejeter"} le Fact
            </DialogTitle>
            <DialogDescription>
              {selectedFact && (
                <div className="mt-4 p-4 bg-gray-50 rounded">
                  <div className="text-sm">
                    <p className="font-semibold">{selectedFact.subject}</p>
                    <p className="text-blue-600">{selectedFact.predicate}</p>
                    <p className="font-semibold">{selectedFact.object}</p>
                  </div>
                </div>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {actionDialog.type === "reject" && (
              <div>
                <label className="text-sm font-medium">Motif de rejet *</label>
                <Input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Information incorrecte, source non fiable, etc."
                  className="mt-1"
                />
              </div>
            )}

            <div>
              <label className="text-sm font-medium">Commentaire (optionnel)</label>
              <Textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Ajoutez un commentaire..."
                className="mt-1"
                rows={3}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeActionDialog} disabled={processing}>
              Annuler
            </Button>
            {actionDialog.type === "approve" ? (
              <Button onClick={handleApprove} disabled={processing} className="bg-green-600 hover:bg-green-700">
                {processing ? "Traitement..." : "Approuver"}
              </Button>
            ) : (
              <Button variant="destructive" onClick={handleReject} disabled={processing || !reason}>
                {processing ? "Traitement..." : "Rejeter"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}