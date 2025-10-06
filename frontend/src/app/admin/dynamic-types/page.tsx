/**
 * Page Admin - Gestion Types d'Entités Dynamiques
 *
 * Phase 4 - Frontend UI (Refactored with Cards)
 * Phase 5A - UX Refactoring: Cards groupées + drill-down
 *
 * Affiche les entity types découverts par le LLM avec workflow approve/reject.
 */

'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface EntityType {
  id: number;
  type_name: string;
  status: string;
  entity_count: number;
  pending_entity_count: number;
  validated_entity_count: number;
  first_seen: string;
  discovered_by: string;
  description?: string;
}

export default function DynamicTypesPage() {
  const [types, setTypes] = useState<EntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards');

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

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setUploadFile(file);
    }
  };

  const handleImportYAML = async () => {
    if (!uploadFile) {
      alert('Veuillez sélectionner un fichier YAML');
      return;
    }

    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', uploadFile);

      const response = await fetch('/api/entity-types/import-yaml?auto_approve=true&skip_existing=true', {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        const result = await response.json();
        alert(`Import réussi !\n\nCréés: ${result.created}\nIgnorés: ${result.skipped}\nErreurs: ${result.errors.length}`);
        setUploadFile(null);
        fetchTypes();
      } else {
        const error = await response.json();
        alert(`Erreur: ${error.detail}`);
      }
    } catch (error) {
      console.error('Error importing YAML:', error);
      alert('Erreur réseau');
    } finally {
      setUploading(false);
    }
  };

  const handleExportYAML = async (statusExport: string = 'approved') => {
    try {
      const url = `/api/entity-types/export-yaml?status=${statusExport}`;
      const response = await fetch(url);

      if (response.ok) {
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `entity_types_${statusExport}_default.yaml`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
      } else {
        alert('Erreur lors de l\'export');
      }
    } catch (error) {
      console.error('Error exporting YAML:', error);
      alert('Erreur réseau');
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'pending': return 'bg-yellow-100 text-yellow-800 border-yellow-300';
      case 'approved': return 'bg-green-100 text-green-800 border-green-300';
      case 'rejected': return 'bg-red-100 text-red-800 border-red-300';
      default: return 'bg-gray-100 text-gray-800 border-gray-300';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'pending': return '⏳';
      case 'approved': return '✅';
      case 'rejected': return '❌';
      default: return '❓';
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Types d'Entités Dynamiques</h1>

        {/* Toggle View Mode */}
        <div className="flex gap-2">
          <button
            onClick={() => setViewMode('cards')}
            className={`px-3 py-1 rounded ${viewMode === 'cards' ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
          >
            📇 Cards
          </button>
          <button
            onClick={() => setViewMode('table')}
            className={`px-3 py-1 rounded ${viewMode === 'table' ? 'bg-blue-600 text-white' : 'bg-gray-200'}`}
          >
            📊 Table
          </button>
        </div>
      </div>

      {/* Section Import/Export YAML */}
      <div className="mb-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
        <h2 className="text-lg font-semibold mb-3">Import / Export YAML</h2>

        <div className="flex flex-col md:flex-row gap-4">
          {/* Import YAML */}
          <div className="flex-1">
            <label className="block text-sm font-medium mb-2">📤 Importer Ontologie YAML</label>
            <div className="flex gap-2">
              <input
                type="file"
                accept=".yaml,.yml"
                onChange={handleFileUpload}
                className="flex-1 text-sm"
                disabled={uploading}
              />
              <button
                onClick={handleImportYAML}
                disabled={!uploadFile || uploading}
                className={`px-4 py-2 rounded font-medium ${
                  uploadFile && !uploading
                    ? 'bg-blue-600 text-white hover:bg-blue-700'
                    : 'bg-gray-300 text-gray-500 cursor-not-allowed'
                }`}
              >
                {uploading ? 'Import...' : 'Importer'}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Format: config/ontologies/*.yaml (auto-approve, skip existing)
            </p>
          </div>

          {/* Export YAML */}
          <div className="flex-1">
            <label className="block text-sm font-medium mb-2">📥 Exporter Types</label>
            <div className="flex gap-2">
              <button
                onClick={() => handleExportYAML('approved')}
                className="flex-1 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 font-medium"
              >
                Export Approuvés
              </button>
              <button
                onClick={() => handleExportYAML('all')}
                className="flex-1 px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700 font-medium"
              >
                Export Tous
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Télécharge fichier YAML réimportable
            </p>
          </div>
        </div>
      </div>

      {/* Filtres Status */}
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
      ) : viewMode === 'cards' ? (
        /* Vue Cards */
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {types.map((type) => (
            <div
              key={type.id}
              className={`border-2 rounded-lg p-4 hover:shadow-lg transition-shadow ${getStatusColor(type.status)}`}
            >
              {/* Header Card */}
              <div className="flex justify-between items-start mb-3">
                <div className="flex-1">
                  <h3 className="font-mono font-bold text-lg mb-1">{type.type_name}</h3>
                  <p className="text-xs text-gray-600">{type.description || 'Aucune description'}</p>
                </div>
                <span className="text-2xl ml-2">{getStatusIcon(type.status)}</span>
              </div>

              {/* Statistiques */}
              <div className="grid grid-cols-3 gap-2 mb-3 text-center">
                <div className="bg-white bg-opacity-50 rounded p-2">
                  <div className="text-xl font-bold">{type.entity_count}</div>
                  <div className="text-xs">Total</div>
                </div>
                <div className="bg-yellow-50 rounded p-2">
                  <div className="text-xl font-bold text-yellow-700">{type.pending_entity_count}</div>
                  <div className="text-xs text-yellow-700">Pending</div>
                </div>
                <div className="bg-green-50 rounded p-2">
                  <div className="text-xl font-bold text-green-700">{type.validated_entity_count || 0}</div>
                  <div className="text-xs text-green-700">Validées</div>
                </div>
              </div>

              {/* Métadonnées */}
              <div className="text-xs text-gray-600 mb-3 space-y-1">
                <div>📅 {new Date(type.first_seen).toLocaleDateString()}</div>
                <div>🔍 {type.discovered_by}</div>
              </div>

              {/* Actions */}
              <div className="space-y-2">
                {type.status === 'pending' && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApprove(type.type_name)}
                      className="flex-1 px-3 py-2 bg-green-500 text-white rounded hover:bg-green-600 text-sm font-medium"
                    >
                      ✓ Approuver
                    </button>
                    <button
                      onClick={() => handleReject(type.type_name)}
                      className="flex-1 px-3 py-2 bg-red-500 text-white rounded hover:bg-red-600 text-sm font-medium"
                    >
                      ✗ Rejeter
                    </button>
                  </div>
                )}

                <Link
                  href={`/admin/dynamic-types/${type.type_name}`}
                  className="block w-full px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-center text-sm font-medium"
                >
                  👁️ Voir entités ({type.entity_count})
                </Link>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Vue Table (ancienne) */
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
                  <div className="flex gap-2 flex-wrap">
                    {type.status === 'pending' && (
                      <>
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
                      </>
                    )}
                    <Link
                      href={`/admin/dynamic-types/${type.type_name}`}
                      className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                      Voir
                    </Link>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {types.length === 0 && !loading && (
        <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <p className="text-gray-500 text-lg mb-2">Aucun type trouvé</p>
          <p className="text-gray-400 text-sm">Importez un document pour découvrir des types automatiquement</p>
        </div>
      )}
    </div>
  );
}
