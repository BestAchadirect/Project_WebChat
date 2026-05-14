import apiClient from './client';
import { PaginatedResponse } from '../types/pagination';

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

export interface ChatFailureAnalysis {
    bucket: string;
    confidence: number;
    reason: string;
    suggested_action: string;
    severity: string;
    signals: string[];
}

export interface ChatMetricsSummary {
    conversation_id?: number | null;
    question_length?: number;
    workflow?: string | null;
    response_workflow?: string | null;
    route?: string | null;
    status?: string | null;
    channel?: string | null;
    component_mode?: string | null;
    retrieval_source?: string | null;
    reply_mode?: string | null;
    action_kind?: string | null;
    action_completed?: boolean;
    has_products?: boolean;
    product_count?: number;
    has_sources?: boolean;
    source_count?: number;
    follow_up_count?: number;
    use_products?: boolean;
    use_knowledge?: boolean;
    is_policy_like?: boolean;
    grounding_status?: string | null;
    grounding_safe_action?: string | null;
    grounding_reason_count?: number;
    agentic_used_tools?: boolean;
    conversation_state_written?: boolean;
    conversation_state_enabled?: boolean;
    conversation_state_filter_merge_applied?: boolean;
    conversation_state_loaded_version?: number;
    tone_repeat_hit?: number;
    tone_filler_stripped?: number;
    external_call_count?: number;
    llm_call_count?: number;
    latency_total_ms?: number;
    failure_bucket?: string | null;
    failure_confidence?: number;
    failure_reason?: string | null;
    failure_suggested_action?: string | null;
    failure_severity?: string | null;
    failure_signals?: string[];
    failure_analysis?: ChatFailureAnalysis;
}

export interface TokenUsageSummary {
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
    cached_prompt_tokens?: number;
    by_call: TokenUsageCall[];
    chat_metrics?: ChatMetricsSummary;
}

export interface RegressionBundleTarget {
    dataset: string;
    reason: string;
}

export interface RegressionReviewBundle {
    qa_log_id: string;
    conversation_id?: number | null;
    question: string;
    answer: string;
    status: string;
    observed: {
        workflow?: string;
        route?: string;
        grounding_status?: string;
        grounding_safe_action?: string;
        product_count?: number;
        source_count?: number;
        failure_bucket?: string;
        failure_reason?: string;
        failure_suggested_action?: string;
        conversation_state_filter_merge_applied?: boolean;
        llm_call_count?: number;
    };
    recommended_targets: RegressionBundleTarget[];
    promotion_checklist: string[];
    coverage_case_template: Record<string, unknown>;
    response_contract_template: Record<string, unknown>;
}

export interface Product {
    id: string;
    klevu_id?: string;
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
    master_code?: string;

    // Extended attributes
    category?: string;
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

export type ProductListResponse = PaginatedResponse<Product>;
export type QALogListResponse = PaginatedResponse<QALog>;

export interface MasterCodeVariantListResponse extends PaginatedResponse<Product> {
    masterCode: string;
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
    async listQALogs(params?: {
        page?: number;
        pageSize?: number;
        status?: string;
        channel?: string;
        workflow?: string;
        groundingStatus?: string;
        failureBucket?: string;
        search?: string;
    }): Promise<QALogListResponse> {
        const searchParams = new URLSearchParams();
        searchParams.append('page', String(params?.page ?? 1));
        searchParams.append('pageSize', String(params?.pageSize ?? 20));
        if (params?.status) searchParams.append('status', params.status);
        if (params?.channel) searchParams.append('channel', params.channel);
        if (params?.workflow) searchParams.append('workflow', params.workflow);
        if (params?.groundingStatus) searchParams.append('groundingStatus', params.groundingStatus);
        if (params?.failureBucket) searchParams.append('failureBucket', params.failureBucket);
        if (params?.search) searchParams.append('search', params.search);
        const response = await apiClient.get(`/dashboard/qa/qa-logs?${searchParams.toString()}`);
        return response.data;
    },

    async getReviewBundle(qaLogId: string): Promise<RegressionReviewBundle> {
        const response = await apiClient.get(`/dashboard/qa/qa-logs/${encodeURIComponent(qaLogId)}/review-bundle`);
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
        page?: number;
        pageSize?: number;
        search?: string;
        visibility?: boolean;
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
        category_mode?: 'any' | 'all';
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
        category_mode?: 'any' | 'all';
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

    async listMasterCodeVariants(masterCode: string, params?: {
        page?: number;
        pageSize?: number;
        search?: string;
        in_stock?: boolean;
    }): Promise<MasterCodeVariantListResponse> {
        const searchParams = new URLSearchParams();
        if (params) {
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null && value !== '') {
                    searchParams.append(key, String(value));
                }
            });
        }
        const query = searchParams.toString();
        const response = await apiClient.get(`/products/master/${encodeURIComponent(masterCode)}/variants${query ? `?${query}` : ''}`);
        return response.data;
    },

    async hardDeleteBySku(sku: string): Promise<{ status: string; sku: string; deleted: boolean }> {
        const response = await apiClient.delete(`/products/sku/${encodeURIComponent(sku.trim())}`);
        return response.data;
    },

    async bulkDeleteBySku(skus: string[]): Promise<{
        status: string;
        requested: number;
        deleted: number;
        deleted_skus: string[];
        not_found_skus: string[];
    }> {
        const response = await apiClient.post('/products/bulk/delete-sku', skus);
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

export interface SynonymEntry {
    id: number;
    attribute: string;
    raw_value: string;
    canonical_value: string;
    is_active: boolean;
}

export interface SynonymAlias {
    id: number;
    raw_value: string;
    is_active: boolean;
}

export interface SynonymGroup {
    attribute: string;
    attribute_display_name: string;
    canonical_value: string;
    synonyms: SynonymAlias[];
}

export interface SynonymAttribute {
    name: string;
    display_name: string;
}

export const aliasesApi = {
    async listAliases(): Promise<SynonymGroup[]> {
        const response = await apiClient.get('/aliases');
        return response.data;
    },

    async createAlias(data: { attribute: string; raw_value: string; canonical_value: string }): Promise<SynonymEntry> {
        const response = await apiClient.post('/aliases', data);
        return response.data;
    },

    async updateAlias(id: number, data: { raw_value?: string; canonical_value?: string; is_active?: boolean }): Promise<SynonymEntry> {
        const response = await apiClient.put(`/aliases/${id}`, data);
        return response.data;
    },

    async deleteAlias(id: number): Promise<{ status: string }> {
        const response = await apiClient.delete(`/aliases/${id}`);
        return response.data;
    },

    async listAttributes(): Promise<SynonymAttribute[]> {
        const response = await apiClient.get('/aliases/attributes');
        return response.data;
    },
};

export const documentsApi = {
    async listDocuments(page = 1, pageSize = 20): Promise<PaginatedResponse<Document>> {
        const response = await apiClient.get(`/import/knowledge/uploads?page=${page}&pageSize=${pageSize}`);
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
