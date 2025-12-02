import React, { useState, useEffect } from 'react';
import { documentsApi } from '../api/documents';
import { Document } from '../types/document';
import { DocumentUploadForm } from '../components/documents/DocumentUploadForm';
import { DocumentList } from '../components/documents/DocumentList';
import { Spinner } from '../components/common/Spinner';

export const DocumentsPage: React.FC = () => {
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
                <h1 className="text-3xl font-bold text-gray-900">Documents</h1>
                <p className="mt-2 text-gray-600">
                    Upload and manage your knowledge base documents
                </p>
            </div>

            <DocumentUploadForm onUploadSuccess={fetchDocuments} />
            <DocumentList documents={documents} onDeleteSuccess={fetchDocuments} />
        </div>
    );
};
