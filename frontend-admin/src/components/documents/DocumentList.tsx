import React from 'react';
import { Document } from '../../types/document';
import { documentsApi } from '../../api/documents';
import { useToast } from '../../hooks/useToast';
import { Button } from '../common/Button';

interface DocumentListProps {
    documents: Document[];
    onDeleteSuccess: () => void;
}

export const DocumentList: React.FC<DocumentListProps> = ({
    documents,
    onDeleteSuccess,
}) => {
    const { showToast } = useToast();

    const handleDelete = async (id: string, filename: string) => {
        if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
            return;
        }

        try {
            await documentsApi.deleteDocument(id);
            showToast('Document deleted successfully', 'success');
            onDeleteSuccess();
        } catch (error: any) {
            showToast(error.response?.data?.message || 'Delete failed', 'error');
        }
    };



    if (documents.length === 0) {
        return (
            <div className="bg-white rounded-xl shadow-sm p-12 text-center">
                <svg
                    className="mx-auto h-12 w-12 text-gray-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                </svg>
                <h3 className="mt-2 text-sm font-medium text-gray-900">No documents</h3>
                <p className="mt-1 text-sm text-gray-500">Get started by uploading a document.</p>
            </div>
        );
    }

    return (
        <div className="bg-white rounded-xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Filename
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Type
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Size
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Status
                            </th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Uploaded
                            </th>
                            <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Actions
                            </th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {documents.map((doc) => (
                            <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                                    {doc.filename}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                    {doc.fileType.toUpperCase()}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                    {(doc.fileSize / 1024 / 1024).toFixed(2)} MB
                                </td>
                                import {DocumentStatus} from './DocumentStatus';

                                // ... (inside DocumentList component)

                                <td className="px-6 py-4 whitespace-nowrap">
                                    <DocumentStatus document={doc} />
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                    {new Date(doc.uploadedAt).toLocaleDateString()}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                    <Button
                                        variant="danger"
                                        size="sm"
                                        onClick={() => handleDelete(doc.id, doc.filename)}
                                    >
                                        Delete
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};
