/**
 * Page Admin - Gestion Types d'Entités Dynamiques
 *
 * Phase 4 - Frontend UI
 *
 * Affiche les entity types découverts par le LLM avec workflow approve/reject.
 */

'use client';

import { useState, useEffect } from 'react';

interface EntityType {
  id: number;
  type_name: string;
  status: string;
  entity_count: number;
  pending_entity_count: number;
  first_seen: string;
  discovered_by: string;
}

export default function DynamicTypesPage() {
  const [types, setTypes] = useState<EntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    fetchTypes();
  }, [statusFilter]);

  const fetchTypes = async () => {
    setLoading(true);
    try {
      const url = statusFilter === 'all'
        ? '/api/entity-types'
        : `/api/entity-types?status=${statusFilter}`;

      const response = await fetch(url);
      const data = await response.json();
      setTypes(data.types || []);
    } catch (error) {
      console.error('Error fetching types:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (typeName: string) => {
    if (!confirm(`Approuver le type "${typeName}" ?`)) return;

    try {
      const response = await fetch(`/api/entity-types/${typeName}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({ admin_email: 'admin@example.com' })
      });

      if (response.ok) {
        alert('Type approuvé !');
        fetchTypes();
      } else {
        alert('Erreur lors de l\'approbation');
      }
    } catch (error) {
      console.error('Error approving type:', error);
      alert('Erreur réseau');
    }
  };

  const handleReject = async (typeName: string) => {
    const reason = prompt(`Rejeter le type "${typeName}". Raison ?`);
    if (!reason) return;

    try {
      const response = await fetch(`/api/entity-types/${typeName}/reject`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production'
        },
        body: JSON.stringify({
          admin_email: 'admin@example.com',
          reason
        })
      });

      if (response.ok) {
        alert('Type rejeté');
        fetchTypes();
      } else {
        alert('Erreur lors du rejet');
      }
    } catch (error) {
      console.error('Error rejecting type:', error);
    }
  };

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Types d'Entités Dynamiques</h1>

      <div className="mb-4 flex gap-2">
        <button
          onClick={() => setStatusFilter('all')}
          className={`px-4 py-2 rounded ${statusFilter === 'all' ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
        >
          Tous
        </button>
        <button
          onClick={() => setStatusFilter('pending')}
          className={`px-4 py-2 rounded ${statusFilter === 'pending' ? 'bg-yellow-600 text-white' : 'bg-gray-200'}`}
        >
          En attente
        </button>
        <button
          onClick={() => setStatusFilter('approved')}
          className={`px-4 py-2 rounded ${statusFilter === 'approved' ? 'bg-green-600 text-white' : 'bg-gray-200'}`}
        >
          Approuvés
        </button>
        <button
          onClick={() => setStatusFilter('rejected')}
          className={`px-4 py-2 rounded ${statusFilter === 'rejected' ? 'bg-red-600 text-white' : 'bg-gray-200'}`}
        >
          Rejetés
        </button>
      </div>

      {loading ? (
        <p>Chargement...</p>
      ) : (
        <table className="w-full border-collapse border border-gray-300">
          <thead className="bg-gray-100">
            <tr>
              <th className="border p-2">Type</th>
              <th className="border p-2">Status</th>
              <th className="border p-2">Entités</th>
              <th className="border p-2">Pending</th>
              <th className="border p-2">Découvert</th>
              <th className="border p-2">Source</th>
              <th className="border p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {types.map((type) => (
              <tr key={type.id}>
                <td className="border p-2 font-mono">{type.type_name}</td>
                <td className="border p-2">
                  <span className={`px-2 py-1 rounded text-sm ${
                    type.status === 'pending' ? 'bg-yellow-200' :
                    type.status === 'approved' ? 'bg-green-200' :
                    'bg-red-200'
                  }`}>
                    {type.status}
                  </span>
                </td>
                <td className="border p-2 text-center">{type.entity_count}</td>
                <td className="border p-2 text-center">{type.pending_entity_count}</td>
                <td className="border p-2 text-sm">{new Date(type.first_seen).toLocaleDateString()}</td>
                <td className="border p-2">{type.discovered_by}</td>
                <td className="border p-2">
                  {type.status === 'pending' && (
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleApprove(type.type_name)}
                        className="px-3 py-1 bg-green-500 text-white rounded hover:bg-green-600"
                      >
                        ✓ Approuver
                      </button>
                      <button
                        onClick={() => handleReject(type.type_name)}
                        className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600"
                      >
                        ✗ Rejeter
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {types.length === 0 && !loading && (
        <p className="text-gray-500 text-center py-8">Aucun type trouvé</p>
      )}
    </div>
  );
}
