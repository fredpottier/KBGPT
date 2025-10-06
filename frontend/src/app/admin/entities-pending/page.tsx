/**
 * Page Admin - Entités Pending (non cataloguées)
 *
 * Phase 4 - Frontend UI
 *
 * Liste les entités avec status=pending pour validation admin.
 */

'use client';

import { useState, useEffect } from 'react';

interface PendingEntity {
  uuid: string;
  name: string;
  entity_type: string;
  description?: string;
  source_document?: string;
  created_at: string;
  confidence: number;
}

export default function EntitiesPendingPage() {
  const [entities, setEntities] = useState<PendingEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [selectedEntity, setSelectedEntity] = useState<PendingEntity | null>(null);
  const [mergeTarget, setMergeTarget] = useState<string>('');

  useEffect(() => {
    fetchEntities();
  }, [typeFilter]);

  const fetchEntities = async () => {
    setLoading(true);
    try {
      const url = typeFilter
        ? `/api/entities/pending?entity_type=${typeFilter}&limit=100`
        : '/api/entities/pending?limit=100';

      const response = await fetch(url);
      const data = await response.json();
      setEntities(data.entities || []);
    } catch (error) {
      console.error('Error fetching entities:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (entity: PendingEntity) => {
    const addToOntology = confirm(
      `Approuver "${entity.name}" (${entity.entity_type}).\n\nAjouter à l'ontologie YAML ?`
    );

    try {
      const response = await fetch(`/api/entities/${entity.uuid}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production',
          'X-Tenant-ID': 'default'
        },
        body: JSON.stringify({
          add_to_ontology: addToOntology,
          ontology_description: entity.description || `Entity ${entity.name}`
        })
      });

      if (response.ok) {
        alert('Entité approuvée !');
        fetchEntities();
      } else {
        const error = await response.json();
        alert(`Erreur: ${error.detail}`);
      }
    } catch (error) {
      console.error('Error approving entity:', error);
      alert('Erreur réseau');
    }
  };

  const handleMerge = async (sourceEntity: PendingEntity) => {
    const targetUuid = prompt(
      `Fusionner "${sourceEntity.name}" avec une autre entité.\n\nEntrez l'UUID de l'entité cible:`
    );

    if (!targetUuid) return;

    const canonicalName = prompt(
      'Nom final après fusion (laisser vide pour garder le nom de la cible):'
    );

    try {
      const response = await fetch(`/api/entities/${sourceEntity.uuid}/merge`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': 'admin-dev-key-change-in-production',
          'X-Tenant-ID': 'default'
        },
        body: JSON.stringify({
          target_uuid: targetUuid.trim(),
          canonical_name: canonicalName?.trim() || undefined
        })
      });

      if (response.ok) {
        const result = await response.json();
        alert(
          `Fusion réussie !\nRelations transférées: ${result.relations_transferred}`
        );
        fetchEntities();
      } else {
        const error = await response.json();
        alert(`Erreur: ${error.detail}`);
      }
    } catch (error) {
      console.error('Error merging entities:', error);
      alert('Erreur réseau');
    }
  };

  const handleDelete = async (entity: PendingEntity) => {
    if (
      !confirm(
        `ATTENTION: Supprimer définitivement "${entity.name}" ?\n\nCette action est irréversible.`
      )
    ) {
      return;
    }

    try {
      const response = await fetch(
        `/api/entities/${entity.uuid}?cascade=true`,
        {
          method: 'DELETE',
          headers: {
            'X-Admin-Key': 'admin-dev-key-change-in-production',
            'X-Tenant-ID': 'default'
          }
        }
      );

      if (response.ok) {
        const result = await response.json();
        alert(
          `Entité supprimée\nRelations supprimées: ${result.relations_deleted}`
        );
        fetchEntities();
      } else {
        const error = await response.json();
        alert(`Erreur: ${error.detail}`);
      }
    } catch (error) {
      console.error('Error deleting entity:', error);
      alert('Erreur réseau');
    }
  };

  // Extraire types uniques pour filtre
  const uniqueTypes = Array.from(
    new Set(entities.map((e) => e.entity_type))
  ).sort();

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">
        Entités Pending (Non Cataloguées)
      </h1>

      {/* Filtres */}
      <div className="mb-4 flex gap-4 items-center">
        <label className="font-medium">Filtrer par type:</label>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-4 py-2 border rounded"
        >
          <option value="">Tous les types</option>
          {uniqueTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>

        <button
          onClick={fetchEntities}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          🔄 Rafraîchir
        </button>

        <span className="ml-auto text-gray-600">
          {entities.length} entité(s) pending
        </span>
      </div>

      {/* Table */}
      {loading ? (
        <p>Chargement...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse border border-gray-300">
            <thead className="bg-gray-100">
              <tr>
                <th className="border p-2">Nom</th>
                <th className="border p-2">Type</th>
                <th className="border p-2">Description</th>
                <th className="border p-2">Source</th>
                <th className="border p-2">Confiance</th>
                <th className="border p-2">Créé</th>
                <th className="border p-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {entities.map((entity) => (
                <tr key={entity.uuid} className="hover:bg-gray-50">
                  <td className="border p-2 font-medium">{entity.name}</td>
                  <td className="border p-2">
                    <span className="px-2 py-1 bg-blue-100 rounded text-sm font-mono">
                      {entity.entity_type}
                    </span>
                  </td>
                  <td className="border p-2 text-sm text-gray-600 max-w-xs truncate">
                    {entity.description || '-'}
                  </td>
                  <td className="border p-2 text-sm text-gray-500">
                    {entity.source_document || '-'}
                  </td>
                  <td className="border p-2 text-center">
                    <span
                      className={`px-2 py-1 rounded text-sm ${
                        entity.confidence >= 0.8
                          ? 'bg-green-100 text-green-800'
                          : entity.confidence >= 0.5
                          ? 'bg-yellow-100 text-yellow-800'
                          : 'bg-red-100 text-red-800'
                      }`}
                    >
                      {(entity.confidence * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="border p-2 text-sm">
                    {new Date(entity.created_at).toLocaleDateString()}
                  </td>
                  <td className="border p-2">
                    <div className="flex flex-col gap-1">
                      <button
                        onClick={() => handleApprove(entity)}
                        className="px-3 py-1 bg-green-500 text-white rounded hover:bg-green-600 text-sm"
                      >
                        ✓ Approuver
                      </button>
                      <button
                        onClick={() => handleMerge(entity)}
                        className="px-3 py-1 bg-blue-500 text-white rounded hover:bg-blue-600 text-sm"
                      >
                        🔀 Fusionner
                      </button>
                      <button
                        onClick={() => handleDelete(entity)}
                        className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600 text-sm"
                      >
                        🗑️ Supprimer
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {entities.length === 0 && !loading && (
        <div className="text-center py-12">
          <p className="text-gray-500 text-lg">
            ✨ Aucune entité pending
          </p>
          <p className="text-gray-400 text-sm mt-2">
            Toutes les entités sont cataloguées ou validées
          </p>
        </div>
      )}
    </div>
  );
}
