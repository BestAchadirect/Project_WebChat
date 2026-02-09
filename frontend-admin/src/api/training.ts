import apiClient from './client';

// Types
export interface QALog {
    id: string;
    question: string;
    answer?: string;
    sources: any[];
    status: 'success' | 'no_answer' | 'fallback' | 'failed';
    error_message?: string;
    token_usage?: TokenUsageSummary | null;
    channel?: string | null;
    created_at: string;
}

export interface TokenUsageCall {
    kind: string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cached?: boolean;
    cached_prompt_tokens?: number;
}

export interface TokenUsageSummary {
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
    cached_prompt_tokens?: number;
    by_call: TokenUsageCall[];
}

export interface Product {
    id: string;
    object_id?: string;
    sku: string;
    legacy_sku: string[];
    name: string;
    price: number;
    image_url?: string;
    url?: string;
    description?: string;
    in_stock: boolean;
    visibility: boolean;
    is_featured: boolean;
    priority: number;
    master_code?: string;

    // Extended attributes
    jewelry_type?: string;
    material?: string;
    length?: string;
    size?: string;
    cz_color?: string;
    design?: string;
    crystal_color?: string;
    color?: string;
    gauge?: string;
    size_in_pack?: string;
    rack?: string;
    height?: string;
    packing_option?: string;
    pincher_size?: string;
    ring_size?: string;
    quantity_in_bulk?: string;
    opal_color?: string;
    threading?: string;
    outer_diameter?: string;
    pearl_color?: string;
}

export interface ProductFilterValue {
    value: string;
    count: number;
}

export interface ProductFiltersResponse {
    total: number;
    filters: Record<string, ProductFilterValue[]>;
}

export interface ProductListResponse {
    items: Product[];
    total: number;
    offset: number;
    limit: number;
}

export interface Document {
    id: string;
    filename: string;
    content_type?: string;
    file_size?: number;
    status: string;
    error_message?: string;
    created_at: string;
    updated_at?: string;
    title?: string;
    tags: string[];
    category?: string;
    is_enabled: boolean;
}

export interface Chunk {
    id: string;
    article_id: string;
    version: number;
    chunk_index: number;
    chunk_text: string;
    chunk_hash?: string;
    created_at: string;
    article_title?: string;
    is_embedded: boolean;
    embedded_at?: string;
    char_count: number;
}

export interface ChunkListResponse {
    chunks: Chunk[];
    total: number;
}

export interface ArticleChunkGroup {
    article_id: string;
    article_title: string;
    category?: string;
    chunk_count: number;
    chunks: Chunk[];
}

export interface ArticleGroupedResponse {
    articles: ArticleChunkGroup[];
    total_articles: number;
    total_chunks: number;
}

export interface SimilarityResult {
    chunk_id: string;
    chunk_text: string;
    article_title?: string;
    similarity_score: number;
}

export interface SimilarityTestResponse {
    query: string;
    results: SimilarityResult[];
}

export interface BulkOperationResponse {
    status: string;
    processed: number;
    failed: number;
    message: string;
}

// API Functions
export const trainingApi = {
    // QA Logs
    async listQALogs(limit = 50, offset = 0, status?: string): Promise<QALog[]> {
        const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
        if (status) params.append('status', status);
        const response = await apiClient.get(`/dashboard/qa/qa-logs?${params.toString()}`);
        return response.data;
    },
};

export const chunksApi = {
    async listChunks(params?: {
        limit?: number;
        offset?: number;
        article_id?: string;
        search?: string;
    }): Promise<ChunkListResponse> {
        const searchParams = new URLSearchParams();
        if (params?.limit) searchParams.append('limit', String(params.limit));
        if (params?.offset) searchParams.append('offset', String(params.offset));
        if (params?.article_id) searchParams.append('article_id', params.article_id);
        if (params?.search) searchParams.append('search', params.search);
        const response = await apiClient.get(`/dashboard/knowledge/chunks?${searchParams.toString()}`);
        return response.data;
    },

    async listArticlesGrouped(search?: string): Promise<ArticleGroupedResponse> {
        const params = search ? `?search=${encodeURIComponent(search)}` : '';
        const response = await apiClient.get(`/dashboard/knowledge/articles-grouped${params}`);
        return response.data;
    },

    async renameArticle(id: string, title: string): Promise<{ status: string; new_title: string }> {
        const response = await apiClient.put(`/dashboard/knowledge/articles/${id}?title=${encodeURIComponent(title)}`);
        return response.data;
    },

    async getChunk(id: string): Promise<Chunk> {
        const response = await apiClient.get(`/dashboard/knowledge/chunks/${id}`);
        return response.data;
    },

    async updateChunk(id: string, data: { chunk_text: string }): Promise<Chunk> {
        const response = await apiClient.put(`/dashboard/knowledge/chunks/${id}`, data);
        return response.data;
    },

    async reembedChunk(id: string): Promise<{ status: string; message: string; chunk_id: string }> {
        const response = await apiClient.post(`/dashboard/knowledge/chunks/${id}/reembed`);
        return response.data;
    },

    async bulkReembed(chunkIds: string[]): Promise<BulkOperationResponse> {
        const response = await apiClient.post('/dashboard/knowledge/chunks/bulk/reembed', { chunk_ids: chunkIds });
        return response.data;
    },

    async bulkDelete(chunkIds: string[]): Promise<BulkOperationResponse> {
        const response = await apiClient.post('/dashboard/knowledge/chunks/bulk/delete', { chunk_ids: chunkIds });
        return response.data;
    },

    async testSimilarity(query: string, limit = 5): Promise<SimilarityTestResponse> {
        const response = await apiClient.post('/dashboard/knowledge/similarity-test', { query, limit });
        return response.data;
    },
};

export const productsApi = {
    async listProducts(params?: {
        limit?: number;
        offset?: number;
        search?: string;
        visibility?: boolean;
        is_featured?: boolean;
        material?: string | string[];
        jewelry_type?: string | string[];
        color?: string | string[];
        gauge?: string | string[];
        threading?: string | string[];
        length?: string | string[];
        size?: string | string[];
        cz_color?: string | string[];
        opal_color?: string | string[];
        outer_diameter?: string | string[];
        design?: string | string[];
        crystal_color?: string | string[];
        pearl_color?: string | string[];
        rack?: string | string[];
        height?: string | string[];
        packing_option?: string | string[];
        pincher_size?: string | string[];
        ring_size?: string | string[];
        size_in_pack?: string | string[];
        quantity_in_bulk?: string | string[];
        category?: string | string[];
        master_code?: string;
        min_price?: number;
        max_price?: number;
    }): Promise<ProductListResponse> {
        const searchParams = new URLSearchParams();
        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null && value !== '') {
                    if (Array.isArray(value)) {
                        value.forEach((item) => {
                            if (item !== undefined && item !== null && String(item).trim() !== '') {
                                searchParams.append(key, String(item));
                            }
                        });
                    } else {
                        searchParams.append(key, String(value));
                    }
                }
            });
        }
        const response = await apiClient.get(`/products/?${searchParams.toString()}`);
        return response.data;
    },

    async listProductFilters(params?: {
        search?: string;
        visibility?: boolean;
        is_featured?: boolean;
        material?: string | string[];
        jewelry_type?: string | string[];
        color?: string | string[];
        gauge?: string | string[];
        threading?: string | string[];
        length?: string | string[];
        size?: string | string[];
        cz_color?: string | string[];
        opal_color?: string | string[];
        outer_diameter?: string | string[];
        design?: string | string[];
        crystal_color?: string | string[];
        pearl_color?: string | string[];
        rack?: string | string[];
        height?: string | string[];
        packing_option?: string | string[];
        pincher_size?: string | string[];
        ring_size?: string | string[];
        size_in_pack?: string | string[];
        quantity_in_bulk?: string | string[];
        category?: string | string[];
        master_code?: string;
        min_price?: number;
        max_price?: number;
    }): Promise<ProductFiltersResponse> {
        const searchParams = new URLSearchParams();
        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null && value !== '') {
                    if (Array.isArray(value)) {
                        value.forEach((item) => {
                            if (item !== undefined && item !== null && String(item).trim() !== '') {
                                searchParams.append(key, String(item));
                            }
                        });
                    } else {
                        searchParams.append(key, String(value));
                    }
                }
            });
        }
        const response = await apiClient.get(`/products/filters?${searchParams.toString()}`);
        return response.data;
    },

    async updateProduct(id: string, data: Partial<Product>): Promise<Product> {
        const response = await apiClient.put(`/products/${id}`, data);
        return response.data;
    },

    async bulkHide(productIds: string[]): Promise<{ status: string; count: number }> {
        const response = await apiClient.post('/products/bulk/hide', productIds);
        return response.data;
    },

    async bulkShow(productIds: string[]): Promise<{ status: string; count: number }> {
        const response = await apiClient.post('/products/bulk/show', productIds);
        return response.data;
    },

    async bulkUpdate(productIds: string[], updates: Partial<Product>): Promise<{ status: string; updated: number }> {
        const response = await apiClient.post('/products/bulk/update', {
            product_ids: productIds,
            updates
        });
        return response.data;
    },
};

export const documentsApi = {
    async listDocuments(skip = 0, limit = 50): Promise<{ items: Document[]; total: number }> {
        const response = await apiClient.get(`/import/knowledge/uploads?offset=${skip}&limit=${limit}`);
        return response.data;
    },

    async updateDocument(id: string, data: Partial<Document>): Promise<Document> {
        const response = await apiClient.put(`/documents/${id}`, data);
        return response.data;
    },

    async reprocessDocument(id: string): Promise<{ message: string; id: string }> {
        const response = await apiClient.post(`/documents/${id}/reprocess`);
        return response.data;
    },

    async deleteDocument(id: string): Promise<void> {
        await apiClient.delete(`/documents/${id}`);
    },
};
