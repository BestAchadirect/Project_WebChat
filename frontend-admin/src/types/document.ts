export interface Document {
    id: string;
    filename: string;
    content_type: string;
    file_size: number;
    created_at: string;
    status: 'pending' | 'processing' | 'completed' | 'failed';
    error_message?: string;
}

export interface DocumentUploadResponse {
    id: string;
    filename: string;
    status: string;
}
