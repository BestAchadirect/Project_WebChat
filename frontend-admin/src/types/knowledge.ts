export type KnowledgeUploadStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface KnowledgeUpload {
    id: string;
    filename: string;
    content_type?: string | null;
    file_size?: number | null;
    uploaded_by?: string | null;
    status: KnowledgeUploadStatus;
    error_message?: string | null;
    created_at: string;
    updated_at?: string | null;
    completed_at?: string | null;
    articles_count: number;
}
