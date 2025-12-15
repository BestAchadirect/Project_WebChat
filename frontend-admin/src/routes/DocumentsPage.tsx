import React, { useEffect, useState } from 'react';
import { importApi } from '../api/import';
import { FileUploadForm } from '../components/documents/DocumentUploadForm';
import { Button } from '../components/common/Button';
import { KnowledgeUpload } from '../types/knowledge';
import { ProductUpload } from '../types/product';

type Tab = 'products' | 'knowledge';

export const DocumentsPage: React.FC = () => {
    const [activeTab, setActiveTab] = useState<Tab>('products');
    const [productUploads, setProductUploads] = useState<ProductUpload[]>([]);
    const [knowledgeUploads, setKnowledgeUploads] = useState<KnowledgeUpload[]>([]);
    const [loadingProducts, setLoadingProducts] = useState(false);
    const [loadingKnowledge, setLoadingKnowledge] = useState(false);
    const [deletingProductId, setDeletingProductId] = useState<string | null>(null);
    const [deletingKnowledgeId, setDeletingKnowledgeId] = useState<string | null>(null);

    const fetchProductUploads = async () => {
        try {
            setLoadingProducts(true);
            const data = await importApi.listProductUploads();
            setProductUploads(data);
        } catch (error) {
            console.error('Failed to load product uploads', error);
        } finally {
            setLoadingProducts(false);
        }
    };

    const fetchKnowledgeUploads = async () => {
        try {
            setLoadingKnowledge(true);
            const data = await importApi.listKnowledgeUploads();
            setKnowledgeUploads(data);
        } catch (error) {
            console.error('Failed to load knowledge uploads', error);
        } finally {
            setLoadingKnowledge(false);
        }
    };

    useEffect(() => {
        fetchProductUploads();
        fetchKnowledgeUploads();
    }, []);

    const handleDeleteProduct = async (uploadId: string) => {
        try {
            setDeletingProductId(uploadId);
            await importApi.deleteProductUpload(uploadId);
            setProductUploads((prev) => prev.filter((upload) => upload.id !== uploadId));
        } catch (error) {
            console.error('Failed to delete product upload', error);
        } finally {
            setDeletingProductId(null);
        }
    };

    const handleDeleteKnowledge = async (uploadId: string) => {
        try {
            setDeletingKnowledgeId(uploadId);
            await importApi.deleteKnowledgeUpload(uploadId);
            setKnowledgeUploads((prev) => prev.filter((upload) => upload.id !== uploadId));
        } catch (error) {
            console.error('Failed to delete knowledge upload', error);
        } finally {
            setDeletingKnowledgeId(null);
        }
    };

    const handleProductUploadSuccess = () => {
        fetchProductUploads();
    };

    const handleKnowledgeUploadSuccess = () => {
        fetchKnowledgeUploads();
    };

    const formatFileSize = (size?: number | null) => {
        if (!size) return '—';
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    };

    const renderStatusChip = (status: string) => (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary-50 text-primary-700">
            {status}
        </span>
    );

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold text-gray-900">Data Management</h1>
                <p className="mt-2 text-gray-600">
                    Manage your product catalog and knowledge base.
                </p>
            </div>

            {/* Tabs */}
            <div className="border-b border-gray-200">
                <nav className="-mb-px flex space-x-8">
                    <button
                        onClick={() => setActiveTab('products')}
                        className={`${activeTab === 'products'
                            ? 'border-primary-500 text-primary-600'
                            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
                    >
                        Products
                    </button>
                    <button
                        onClick={() => setActiveTab('knowledge')}
                        className={`${activeTab === 'knowledge'
                            ? 'border-primary-500 text-primary-600'
                            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
                    >
                        Knowledge Base
                    </button>
                </nav>
            </div>

            {/* Tab Content */}
            <div className="mt-6">
                {activeTab === 'products' && (
                    <div className="space-y-6">
                        <div className="flex justify-between items-center bg-gray-50 p-4 rounded-lg">
                            <div>
                                <h3 className="text-lg font-medium text-gray-900">Product Import</h3>
                                <p className="text-sm text-gray-500">Import products via CSV. 200k+ SKUs supported.</p>
                            </div>
                            <Button
                                variant="outline"
                                onClick={() => importApi.downloadTemplate('products')}
                            >
                                Download Template
                            </Button>
                        </div>

                        <FileUploadForm
                            onUploadSuccess={handleProductUploadSuccess}
                            uploadFunction={importApi.importProducts}
                            title="Import Products CSV"
                            description="Drag and drop Product CSV file"
                            accept=".csv"
                            acceptedDescription="CSV files only"
                        />
                    </div>
                )}

                {activeTab === 'knowledge' && (
                    <div className="space-y-6">
                        <div className="flex justify-between items-center bg-gray-50 p-4 rounded-lg">
                            <div>
                                <h3 className="text-lg font-medium text-gray-900">Knowledge Base Import</h3>
                                <p className="text-sm text-gray-500">Import structured FAQs and Articles via CSV, PDF, or DOCX files.</p>
                            </div>
                            <Button
                                variant="outline"
                                onClick={() => importApi.downloadTemplate('knowledge')}
                            >
                                Download Template
                            </Button>
                        </div>

                        <FileUploadForm
                            onUploadSuccess={handleKnowledgeUploadSuccess}
                            uploadFunction={importApi.importKnowledge}
                            title="Import Knowledge Base"
                            description="Drag and drop CSV, PDF, or DOCX files"
                            accept=".csv,.pdf,.doc,.docx"
                            acceptedDescription="CSV, PDF, or DOCX files"
                        />
                    </div>
                )}
            </div>

            {activeTab === 'products' && (
                <div className="bg-white rounded-xl shadow-sm p-6">
                    <div className="flex items-center justify-between">
                        <div>
                            <h2 className="text-xl font-semibold text-gray-900">Product Upload History</h2>
                            <p className="text-sm text-gray-500">Audit product CSV imports and remove outdated uploads.</p>
                        </div>
                        <Button variant="outline" onClick={fetchProductUploads}>
                            Refresh
                        </Button>
                    </div>

                    <div className="mt-6 overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Filename</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Imported</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Size</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded By</th>
                                    <th className="px-4 py-3" />
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {loadingProducts && (
                                    <tr>
                                        <td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                                            Loading uploads...
                                        </td>
                                    </tr>
                                )}

                                {!loadingProducts && productUploads.length === 0 && (
                                    <tr>
                                        <td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                                            No product uploads yet.
                                        </td>
                                    </tr>
                                )}

                                {productUploads.map((upload) => (
                                    <tr key={upload.id}>
                                        <td className="px-4 py-3 text-sm text-gray-900">{upload.filename}</td>
                                        <td className="px-4 py-3 text-sm text-gray-500">{upload.imported_products ?? 0}</td>
                                        <td className="px-4 py-3 text-sm text-gray-500">{formatFileSize(upload.file_size)}</td>
                                        <td className="px-4 py-3">{renderStatusChip(upload.status)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-500">
                                            {new Date(upload.created_at).toLocaleString()}
                                        </td>
                                        <td className="px-4 py-3 text-sm text-gray-500">
                                            {upload.uploaded_by || '—'}
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                disabled={deletingProductId === upload.id}
                                                onClick={() => handleDeleteProduct(upload.id)}
                                            >
                                                {deletingProductId === upload.id ? 'Deleting...' : 'Delete'}
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {activeTab === 'knowledge' && (
                <div className="bg-white rounded-xl shadow-sm p-6">
                    <div className="flex items-center justify-between">
                        <div>
                            <h2 className="text-xl font-semibold text-gray-900">Knowledge Upload History</h2>
                            <p className="text-sm text-gray-500">Track imported FAQ/knowledge files and remove outdated uploads.</p>
                        </div>
                        <Button variant="outline" onClick={fetchKnowledgeUploads}>
                            Refresh
                        </Button>
                    </div>

                    <div className="mt-6 overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Filename</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Size</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Uploaded By</th>
                                    <th className="px-4 py-3" />
                                </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-gray-200">
                                {loadingKnowledge && (
                                    <tr>
                                        <td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                                            Loading uploads...
                                        </td>
                                    </tr>
                                )}

                                {!loadingKnowledge && knowledgeUploads.length === 0 && (
                                    <tr>
                                        <td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                                            No knowledge uploads yet.
                                        </td>
                                    </tr>
                                )}

                                {knowledgeUploads.map((upload) => (
                                    <tr key={upload.id}>
                                        <td className="px-4 py-3 text-sm text-gray-900">{upload.filename}</td>
                                        <td className="px-4 py-3 text-sm text-gray-500">{formatFileSize(upload.file_size)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-500">{upload.content_type || '—'}</td>
                                        <td className="px-4 py-3">{renderStatusChip(upload.status)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-500">
                                            {new Date(upload.created_at).toLocaleString()}
                                        </td>
                                        <td className="px-4 py-3 text-sm text-gray-500">
                                            {upload.uploaded_by || '—'}
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                disabled={deletingKnowledgeId === upload.id}
                                                onClick={() => handleDeleteKnowledge(upload.id)}
                                            >
                                                {deletingKnowledgeId === upload.id ? 'Deleting...' : 'Delete'}
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};
