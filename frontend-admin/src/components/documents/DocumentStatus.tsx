import React, { useEffect, useState } from 'react';
import { documentsApi } from '../../api/documents';
import { Document } from '../../types/document';

interface DocumentStatusProps {
    document: Document;
}

export const DocumentStatus: React.FC<DocumentStatusProps> = ({ document }) => {
    const [status, setStatus] = useState(document.status);
    const [error, setError] = useState<string | undefined>(undefined);

    useEffect(() => {
        // Only poll if processing or pending
        if (status === 'completed' || status === 'failed') {
            return;
        }

        const pollInterval = setInterval(async () => {
            try {
                const result = await documentsApi.getDocumentStatus(document.id);
                setStatus(result.status as Document['status']);
                if (result.error_message) {
                    setError(result.error_message);
                }
            } catch (err) {
                console.error('Failed to poll status', err);
            }
        }, 2000); // Poll every 2 seconds

        return () => clearInterval(pollInterval);
    }, [document.id, status]);

    const styles = {
        pending: 'bg-gray-100 text-gray-800',
        processing: 'bg-yellow-100 text-yellow-800 animate-pulse',
        completed: 'bg-green-100 text-green-800',
        failed: 'bg-red-100 text-red-800',
    };

    return (
        <div className="flex flex-col">
            <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium w-fit ${styles[status] || styles.pending}`}
            >
                {status.charAt(0).toUpperCase() + status.slice(1)}
            </span>
            {status === 'failed' && error && (
                <span className="text-xs text-red-600 mt-1 max-w-[200px] truncate" title={error}>
                    {error}
                </span>
            )}
        </div>
    );
};
