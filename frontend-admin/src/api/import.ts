import apiClient from './client';

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

    async importProducts(file: File): Promise<{ message: string; stats: any }> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await apiClient.post('/import/products', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },

    async importKnowledge(file: File): Promise<{ message: string; stats: any }> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await apiClient.post('/import/knowledge', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },
};
