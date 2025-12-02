export interface Document {
    id: string;
    filename: string;
    fileType: 'pdf' | 'doc' | 'docx' | 'csv';
    fileSize: number;
    uploadedAt: string;
    status: 'pending' | 'processing' | 'completed' | 'failed';
    errorMessage?: string;
}

export interface DocumentUploadResponse {
    id: string;
    filename: string;
    status: string;
}
