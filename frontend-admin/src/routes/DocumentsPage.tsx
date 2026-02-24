import React, { useEffect, useState } from 'react';
import { importApi } from '../api/import';
import { FileUploadForm } from '../components/documents/DocumentUploadForm';
import { Button } from '../components/common/Button';
import { PaginationControls } from '../components/common/PaginationControls';
import { defaultPageSize } from '../constants/pagination';
import { KnowledgeUpload } from '../types/knowledge';
import { ProductUpload } from '../types/product';

type Tab = 'products' | 'knowledge';

export const DocumentsPage: React.FC = () => {
    const [activeTab, setActiveTab] = useState<Tab>('products');
    const [productUploads, setProductUploads] = useState<ProductUpload[]>([]);
    const [knowledgeUploads, setKnowledgeUploads] = useState<KnowledgeUpload[]>([]);
    const [productPage, setProductPage] = useState(1);
    const [productPageSize, setProductPageSize] = useState(defaultPageSize);
    const [productTotalItems, setProductTotalItems] = useState(0);
    const [productTotalPages, setProductTotalPages] = useState(1);
    const [knowledgePage, setKnowledgePage] = useState(1);
    const [knowledgePageSize, setKnowledgePageSize] = useState(defaultPageSize);
    const [knowledgeTotalItems, setKnowledgeTotalItems] = useState(0);
    const [knowledgeTotalPages, setKnowledgeTotalPages] = useState(1);
    const [loadingProducts, setLoadingProducts] = useState(false);
    const [loadingKnowledge, setLoadingKnowledge] = useState(false);
    const [deletingProductId, setDeletingProductId] = useState<string | null>(null);
    const [deletingKnowledgeId, setDeletingKnowledgeId] = useState<string | null>(null);

    const fetchProductUploads = async (page: number = productPage, pageSize: number = productPageSize) => {
        try {
            setLoadingProducts(true);
            const data = await importApi.listProductUploads({ page, pageSize });
            setProductUploads(data.items);
            setProductTotalItems(data.totalItems);
            setProductTotalPages(data.totalPages);
            setProductPage(data.page);
            setProductPageSize(data.pageSize);
        } catch (error) {
            console.error('Failed to load product uploads', error);
        } finally {
            setLoadingProducts(false);
        }
    };

    const fetchKnowledgeUploads = async (page: number = knowledgePage, pageSize: number = knowledgePageSize) => {
        try {
            setLoadingKnowledge(true);
            const data = await importApi.listKnowledgeUploads({ page, pageSize });
            setKnowledgeUploads(data.items);
            setKnowledgeTotalItems(data.totalItems);
            setKnowledgeTotalPages(data.totalPages);
            setKnowledgePage(data.page);
            setKnowledgePageSize(data.pageSize);
        } catch (error) {
            console.error('Failed to load knowledge uploads', error);
        } finally {
            setLoadingKnowledge(false);
        }
    };

    useEffect(() => {
        void fetchProductUploads(1, productPageSize);
        void fetchKnowledgeUploads(1, knowledgePageSize);
    }, []);

    const handleProductPaginationChange = ({ currentPage, pageSize }: { currentPage: number; pageSize: number }) => {
        if (currentPage === productPage && pageSize === productPageSize) return;
        setProductPage(currentPage);
        setProductPageSize(pageSize);
        void fetchProductUploads(currentPage, pageSize);
    };

    const handleKnowledgePaginationChange = ({ currentPage, pageSize }: { currentPage: number; pageSize: number }) => {
        if (currentPage === knowledgePage && pageSize === knowledgePageSize) return;
        setKnowledgePage(currentPage);
        setKnowledgePageSize(pageSize);
        void fetchKnowledgeUploads(currentPage, pageSize);
    };

    const handleDeleteProduct = async (uploadId: string) => {
        try {
            setDeletingProductId(uploadId);
            await importApi.deleteProductUpload(uploadId);
            const targetPage = productUploads.length <= 1 && productPage > 1 ? productPage - 1 : productPage;
            setProductPage(targetPage);
            await fetchProductUploads(targetPage, productPageSize);
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
            const targetPage = knowledgeUploads.length <= 1 && knowledgePage > 1 ? knowledgePage - 1 : knowledgePage;
            setKnowledgePage(targetPage);
            await fetchKnowledgeUploads(targetPage, knowledgePageSize);
        } catch (error) {
            console.error('Failed to delete knowledge upload', error);
        } finally {
            setDeletingKnowledgeId(null);
        }
    };

    const handleProductUploadSuccess = () => {
        setProductPage(1);
        void fetchProductUploads(1, productPageSize);
    };

    const handleKnowledgeUploadSuccess = () => {
        setKnowledgePage(1);
        void fetchKnowledgeUploads(1, knowledgePageSize);
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
                                <p className="text-sm text-gray-500">Import structured FAQs and Articles via CSV or DOCX files.</p>
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
                            description="Drag and drop CSV or DOCX files"
                            accept=".csv,.docx"
                            acceptedDescription="CSV or DOCX files"
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
                        <Button variant="outline" onClick={() => void fetchProductUploads(productPage, productPageSize)}>
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
                    <PaginationControls
                        currentPage={productPage}
                        pageSize={productPageSize}
                        totalItems={productTotalItems}
                        totalPages={productTotalPages}
                        isLoading={loadingProducts}
                        onChange={handleProductPaginationChange}
                    />
                </div>
            )}

            {activeTab === 'knowledge' && (
                <div className="bg-white rounded-xl shadow-sm p-6">
                    <div className="flex items-center justify-between">
                        <div>
                            <h2 className="text-xl font-semibold text-gray-900">Knowledge Upload History</h2>
                            <p className="text-sm text-gray-500">Track imported FAQ/knowledge files and remove outdated uploads.</p>
                        </div>
                        <Button variant="outline" onClick={() => void fetchKnowledgeUploads(knowledgePage, knowledgePageSize)}>
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
                    <PaginationControls
                        currentPage={knowledgePage}
                        pageSize={knowledgePageSize}
                        totalItems={knowledgeTotalItems}
                        totalPages={knowledgeTotalPages}
                        isLoading={loadingKnowledge}
                        onChange={handleKnowledgePaginationChange}
                    />
                </div>
            )}
        </div>
    );
};
