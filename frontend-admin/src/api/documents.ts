import apiClient from './client';
import { Document, DocumentUploadResponse } from '../types/document';

export const documentsApi = {
    async uploadDocument(file: File): Promise<DocumentUploadResponse> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await apiClient.post<DocumentUploadResponse>(
            '/documents/upload',
            formData,
            {
                headers: {
                    'Content-Type': 'multipart/form-data',
                },
            }
        );
        return response.data;
    },

    async listDocuments(): Promise<Document[]> {
        const response = await apiClient.get<Document[]>('/documents');
        return response.data;
    },

    async deleteDocument(id: string): Promise<void> {
        await apiClient.delete(`/documents/${id}`);
    },

    async getDocumentStatus(id: string): Promise<{ status: string; error_message?: string }> {
        const response = await apiClient.get(`/documents/${id}/status`);
        return response.data;
    },
};
