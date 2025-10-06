/**
 * Page Drill-Down - Entités d'un Type Spécifique
 *
 * Phase 5A - UX Refactoring
 *
 * Affiche toutes les entités d'un type donné avec actions:
 * - Approve individuel
 * - Merge similaires
 * - Delete
 * - Génération ontologie (si type approved)
 */

'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';

interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  status: string;
  description?: string;
  confidence?: number;
  source_document?: string;
  created_at: string;
  validated_at?: string;
  validated_by?: string;
}

interface TypeInfo {
  type_name: string;
  status: string;
  entity_count: number;
  pending_entity_count: number;
  validated_entity_count: number;
  description?: string;
}

export default function TypeEntitiesPage() {
  const params = useParams();
  const router = useRouter();
  const typeName = params.typeName as string;

  const [entities, setEntities] = useState<Entity[]>([]);
  const [typeInfo, setTypeInfo] = useState<TypeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedEntities, setSelectedEntities] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchTypeInfo();
    fetchEntities();
  }, [typeName, statusFilter]);

  const fetchTypeInfo = async () => {
    try {
      const response = await fetch(`/api/entity-types/${typeName}`);
      if (response.ok) {
        const data = await response.json();
        setTypeInfo(data);
      }
    } catch (error) {
      console.error('Error fetching type info:', error);
    }
  };

  const fetchEntities = async () => {
    setLoading(true);
    try {
      let url = `/api/entities?entity_type=${typeName}`;
      if (statusFilter !== 'all') {
        url += `&status=${statusFilter}`;
      }

      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        setEntities(data.entities || []);
      }
    } catch (error) {
      console.error('Error fetching entities:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveEntity = async (uuid: string) => {
    try {
      const response = await fetch(`/api/entities/${uuid}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({
          add_to_ontology: false,
          admin_email: 'admin@example.com'
        })
      });

      if (response.ok) {
        alert('Entité approuvée');
        fetchEntities();
        fetchTypeInfo();
      } else {
        alert('Erreur lors de l\'approbation');
      }
    } catch (error) {
      console.error('Error approving entity:', error);
    }
  };

  const handleDeleteEntity = async (uuid: string) => {
    if (!confirm('Supprimer cette entité ?')) return;

    try {
      const response = await fetch(`/api/entities/${uuid}`, {
        method: 'DELETE',
        headers: {
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        }
      });

      if (response.ok) {
        alert('Entité supprimée');
        fetchEntities();
        fetchTypeInfo();
      } else {
        alert('Erreur lors de la suppression');
      }
    } catch (error) {
      console.error('Error deleting entity:', error);
    }
  };

  const handleToggleSelect = (uuid: string) => {
    const newSelected = new Set(selectedEntities);
    if (newSelected.has(uuid)) {
      newSelected.delete(uuid);
    } else {
      newSelected.add(uuid);
    }
    setSelectedEntities(newSelected);
  };

  const handleSelectAll = () => {
    if (selectedEntities.size === entities.length) {
      setSelectedEntities(new Set());
    } else {
      setSelectedEntities(new Set(entities.map(e => e.uuid)));
    }
  };

  const handleBulkApprove = async () => {
    if (selectedEntities.size === 0) {
      alert('Aucune entité sélectionnée');
      return;
    }

    if (!confirm(`Approuver ${selectedEntities.size} entités ?`)) return;

    let approved = 0;
    for (const uuid of selectedEntities) {
      try {
        const response = await fetch(`/api/entities/${uuid}/approve`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Admin-Key': 'admin-dev-key-change-in-production'
          },
          body: JSON.stringify({
            add_to_ontology: false,
            admin_email: 'admin@example.com'
          })
        });
        if (response.ok) approved++;
      } catch (error) {
        console.error('Error approving entity:', error);
      }
    }

    alert(`${approved}/${selectedEntities.size} entités approuvées`);
    setSelectedEntities(new Set());
    fetchEntities();
    fetchTypeInfo();
  };

  const handleGenerateOntology = async () => {
    alert('🤖 Génération ontologie avec LLM (Step 2 à venir)');
    // TODO: Step 2 - Appel endpoint génération ontologie
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'bg-yellow-100 text-yellow-800';
      case 'validated': return 'bg-green-100 text-green-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  };

  if (!typeInfo) {
    return <div className="p-6">Chargement...</div>;
  }

  return (
    <div className="p-6">
      {/* Header avec breadcrumb */}
      <div className="mb-6">
        <div className="text-sm text-gray-500 mb-2">
          <Link href="/admin/dynamic-types" className="hover:underline">
            Types Dynamiques
          </Link>
          {' '}/{' '}
          <span className="font-semibold">{typeName}</span>
        </div>
        <h1 className="text-2xl font-bold mb-2">{typeName}</h1>
        <p className="text-gray-600">{typeInfo.description || 'Aucune description'}</p>
      </div>

      {/* Statistiques */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white border rounded-lg p-4">
          <div className="text-2xl font-bold">{typeInfo.entity_count}</div>
          <div className="text-sm text-gray-600">Total Entités</div>
        </div>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="text-2xl font-bold text-yellow-700">{typeInfo.pending_entity_count}</div>
          <div className="text-sm text-yellow-700">En attente</div>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="text-2xl font-bold text-green-700">{typeInfo.validated_entity_count}</div>
          <div className="text-sm text-green-700">Validées</div>
        </div>
        <div className={`border rounded-lg p-4 ${
          typeInfo.status === 'pending' ? 'bg-yellow-50 border-yellow-200' : 'bg-green-50 border-green-200'
        }`}>
          <div className="text-2xl font-bold">
            {typeInfo.status === 'pending' ? '⏳' : '✅'}
          </div>
          <div className="text-sm">Type {typeInfo.status}</div>
        </div>
      </div>

      {/* Actions Globales */}
      <div className="mb-4 flex flex-wrap gap-2">
        {typeInfo.status === 'approved' && (
          <button
            onClick={handleGenerateOntology}
            className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 font-medium"
          >
            🤖 Générer Ontologie (LLM)
          </button>
        )}

        {selectedEntities.size > 0 && (
          <>
            <button
              onClick={handleBulkApprove}
              className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 font-medium"
            >
              ✓ Approuver sélection ({selectedEntities.size})
            </button>
            <button
              onClick={() => setSelectedEntities(new Set())}
              className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 font-medium"
            >
              Désélectionner
            </button>
          </>
        )}
      </div>

      {/* Filtres Status */}
      <div className="mb-4 flex gap-2">
        <button
          onClick={() => setStatusFilter('all')}
          className={`px-4 py-2 rounded ${statusFilter === 'all' ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
        >
          Toutes
        </button>
        <button
          onClick={() => setStatusFilter('pending')}
          className={`px-4 py-2 rounded ${statusFilter === 'pending' ? 'bg-yellow-600 text-white' : 'bg-gray-200'}`}
        >
          En attente
        </button>
        <button
          onClick={() => setStatusFilter('validated')}
          className={`px-4 py-2 rounded ${statusFilter === 'validated' ? 'bg-green-600 text-white' : 'bg-gray-200'}`}
        >
          Validées
        </button>
      </div>

      {/* Liste Entités */}
      {loading ? (
        <p>Chargement...</p>
      ) : (
        <div className="bg-white rounded-lg border">
          <table className="w-full">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="p-3 text-left">
                  <input
                    type="checkbox"
                    checked={selectedEntities.size === entities.length && entities.length > 0}
                    onChange={handleSelectAll}
                    className="w-4 h-4"
                  />
                </th>
                <th className="p-3 text-left font-semibold">Nom</th>
                <th className="p-3 text-left font-semibold">Status</th>
                <th className="p-3 text-left font-semibold">Description</th>
                <th className="p-3 text-left font-semibold">Confiance</th>
                <th className="p-3 text-left font-semibold">Créé le</th>
                <th className="p-3 text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {entities.map((entity) => (
                <tr key={entity.uuid} className="border-b hover:bg-gray-50">
                  <td className="p-3">
                    <input
                      type="checkbox"
                      checked={selectedEntities.has(entity.uuid)}
                      onChange={() => handleToggleSelect(entity.uuid)}
                      className="w-4 h-4"
                    />
                  </td>
                  <td className="p-3 font-medium">{entity.name}</td>
                  <td className="p-3">
                    <span className={`px-2 py-1 rounded text-sm ${getStatusColor(entity.status)}`}>
                      {entity.status}
                    </span>
                  </td>
                  <td className="p-3 text-sm text-gray-600">
                    {entity.description || '-'}
                  </td>
                  <td className="p-3 text-sm">
                    {entity.confidence ? `${(entity.confidence * 100).toFixed(0)}%` : '-'}
                  </td>
                  <td className="p-3 text-sm text-gray-600">
                    {new Date(entity.created_at).toLocaleDateString()}
                  </td>
                  <td className="p-3">
                    <div className="flex gap-2">
                      {entity.status === 'pending' && (
                        <button
                          onClick={() => handleApproveEntity(entity.uuid)}
                          className="px-2 py-1 bg-green-500 text-white rounded hover:bg-green-600 text-sm"
                          title="Approuver"
                        >
                          ✓
                        </button>
                      )}
                      <button
                        onClick={() => handleDeleteEntity(entity.uuid)}
                        className="px-2 py-1 bg-red-500 text-white rounded hover:bg-red-600 text-sm"
                        title="Supprimer"
                      >
                        🗑️
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {entities.length === 0 && (
            <div className="text-center py-12 text-gray-500">
              Aucune entité trouvée pour ce type
            </div>
          )}
        </div>
      )}
    </div>
  );
}
