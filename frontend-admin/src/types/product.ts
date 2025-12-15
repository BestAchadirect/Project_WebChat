export type ProductUploadStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface ProductUpload {
    id: string;
    filename: string;
    content_type?: string | null;
    file_size?: number | null;
    uploaded_by?: string | null;
    status: ProductUploadStatus;
    error_message?: string | null;
    imported_products: number;
    created_at: string;
    updated_at?: string | null;
    completed_at?: string | null;
}
