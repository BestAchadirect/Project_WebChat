import React, { useState, useEffect } from 'react';
import { documentsApi } from '../api/documents';
import { importApi } from '../api/import';
import { Document } from '../types/document';
import { FileUploadForm } from '../components/documents/DocumentUploadForm';
import { DocumentList } from '../components/documents/DocumentList';
import { Spinner } from '../components/common/Spinner';
import { Button } from '../components/common/Button';

type Tab = 'documents' | 'products' | 'knowledge';

export const DocumentsPage: React.FC = () => {
    const [activeTab, setActiveTab] = useState<Tab>('documents');
    const [documents, setDocuments] = useState<Document[]>([]);
    const [isLoading, setIsLoading] = useState(true);

    const fetchDocuments = async () => {
        try {
            const docs = await documentsApi.listDocuments();
            setDocuments(docs);
        } catch (error) {
            console.error('Failed to fetch documents:', error);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchDocuments();
    }, []);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Spinner size="lg" />
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold text-gray-900">Data Management</h1>
                <p className="mt-2 text-gray-600">
                    Manage your documents, product catalog, and knowledge base.
                </p>
            </div>

            {/* Tabs */}
            <div className="border-b border-gray-200">
                <nav className="-mb-px flex space-x-8">
                    <button
                        onClick={() => setActiveTab('documents')}
                        className={`${activeTab === 'documents'
                            ? 'border-primary-500 text-primary-600'
                            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
                    >
                        Documents
                    </button>
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
                {activeTab === 'documents' && (
                    <div className="space-y-6">
                        <div className="bg-blue-50 border-l-4 border-blue-400 p-4">
                            <div className="flex">
                                <div className="ml-3">
                                    <p className="text-sm text-blue-700">
                                        Upload generic documents (PDF, DOCX, TXT) here. The AI will chunk and embed them for general knowledge retrieval.
                                    </p>
                                </div>
                            </div>
                        </div>
                        <FileUploadForm
                            onUploadSuccess={fetchDocuments}
                            uploadFunction={documentsApi.uploadDocument}
                            title="Upload Documents"
                        />
                        <DocumentList documents={documents} onDeleteSuccess={fetchDocuments} />
                    </div>
                )}

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
                            onUploadSuccess={() => { }} // No list refresh needed yet
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
                                <p className="text-sm text-gray-500">Import structured FAQs and Articles via CSV.</p>
                            </div>
                            <Button
                                variant="outline"
                                onClick={() => importApi.downloadTemplate('knowledge')}
                            >
                                Download Template
                            </Button>
                        </div>

                        <FileUploadForm
                            onUploadSuccess={() => { }}
                            uploadFunction={importApi.importKnowledge}
                            title="Import Knowledge CSV"
                            description="Drag and drop Knowledge CSV file"
                            accept=".csv"
                            acceptedDescription="CSV files only"
                        />
                    </div>
                )}
            </div>
        </div>
    );
};
