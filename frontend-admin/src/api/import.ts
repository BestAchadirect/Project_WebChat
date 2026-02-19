import apiClient from './client';
import { KnowledgeUpload } from '../types/knowledge';
import { ProductUpload } from '../types/product';
import { PaginatedResponse } from '../types/pagination';

export const importApi = {
    async downloadTemplate(type: 'products' | 'knowledge'): Promise<void> {
        const response = await apiClient.get(`/import/template/${type}`, {
            responseType: 'blob',
        });

        // Create download link
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', `${type}_import_template.csv`);
        document.body.appendChild(link);
        link.click();
        link.remove();
    },

    async importProducts(file: File): Promise<{ message: string; stats: any; upload_id: string; status: string }> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await apiClient.post('/import/products', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },

    async listProductUploads(params?: { page?: number; pageSize?: number }): Promise<PaginatedResponse<ProductUpload>> {
        const response = await apiClient.get('/import/products/uploads', {
            params: {
                page: params?.page ?? 1,
                pageSize: params?.pageSize ?? 20,
            },
        });
        return response.data;
    },

    async downloadProductUpload(uploadId: string, filename: string): Promise<void> {
        const response = await apiClient.get(`/import/products/uploads/${uploadId}/download`, {
            responseType: 'blob',
        });
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        link.remove();
    },

    async deleteProductUpload(uploadId: string): Promise<void> {
        await apiClient.delete(`/import/products/uploads/${uploadId}`);
    },

    async importKnowledge(file: File, uploadedBy?: string): Promise<{ message: string; stats: any; upload_id: string; status: string }> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await apiClient.post('/import/knowledge', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
                ...(uploadedBy ? { 'X-Uploaded-By': uploadedBy } : {}),
            },
        });
        return response.data;
    },

    async listKnowledgeUploads(params?: { page?: number; pageSize?: number }): Promise<PaginatedResponse<KnowledgeUpload>> {
        const response = await apiClient.get('/import/knowledge/uploads', {
            params: {
                page: params?.page ?? 1,
                pageSize: params?.pageSize ?? 20,
            },
        });
        return response.data;
    },

    async downloadKnowledgeUpload(uploadId: string, filename: string): Promise<void> {
        const response = await apiClient.get(`/import/knowledge/uploads/${uploadId}/download`, {
            responseType: 'blob',
        });
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', filename);
        document.body.appendChild(link);
        link.click();
        link.remove();
    },

    async deleteKnowledgeUpload(uploadId: string): Promise<void> {
        await apiClient.delete(`/import/knowledge/uploads/${uploadId}`);
    },
};
