import React, { useState, useCallback } from 'react';
import { useToast } from '../../hooks/useToast';
import { Button } from '../common/Button';

interface FileUploadFormProps {
    onUploadSuccess: () => void;
    uploadFunction: (file: File) => Promise<any>;
    title?: string;
    description?: string;
    accept?: string;
    acceptedDescription?: string;
}

export const FileUploadForm: React.FC<FileUploadFormProps> = ({
    onUploadSuccess,
    uploadFunction,
    title = "Upload Documents",
    description = "Drag and drop files here",
    accept = ".pdf,.doc,.docx,.csv",
    acceptedDescription = "PDF, DOC, DOCX, CSV up to 10MB"
}) => {
    const [isDragging, setIsDragging] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
    const { showToast } = useToast();

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const files = Array.from(e.dataTransfer.files);
        setSelectedFiles(files);
    }, []);

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            const files = Array.from(e.target.files);
            setSelectedFiles(files);
        }
    };

    const handleUpload = async () => {
        if (selectedFiles.length === 0) {
            showToast('Please select files to upload', 'warning');
            return;
        }

        setIsUploading(true);
        try {
            for (const file of selectedFiles) {
                await uploadFunction(file);
            }
            showToast(`Successfully uploaded ${selectedFiles.length} file(s)`, 'success');
            setSelectedFiles([]);
            onUploadSuccess();
        } catch (error: any) {
            console.error(error);
            showToast(error.response?.data?.detail || error.message || 'Upload failed', 'error');
        } finally {
            setIsUploading(false);
        }
    };

    return (
        <div className="bg-white rounded-xl shadow-sm p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">{title}</h3>

            {/* Drag and Drop Area */}
            <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${isDragging
                    ? 'border-primary-500 bg-primary-50'
                    : 'border-gray-300 hover:border-primary-400'
                    }`}
            >
                <svg
                    className="mx-auto h-12 w-12 text-gray-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                </svg>
                <p className="mt-2 text-sm text-gray-600">
                    {description}, or{' '}
                    <label className="text-primary-600 hover:text-primary-700 cursor-pointer font-medium">
                        browse
                        <input
                            type="file"
                            multiple
                            accept={accept}
                            onChange={handleFileSelect}
                            className="hidden"
                        />
                    </label>
                </p>
                <p className="mt-1 text-xs text-gray-500">{acceptedDescription}</p>
            </div>

            {/* Selected Files */}
            {selectedFiles.length > 0 && (
                <div className="mt-4 space-y-2">
                    <h4 className="text-sm font-medium text-gray-700">Selected Files:</h4>
                    {selectedFiles.map((file, index) => (
                        <div
                            key={index}
                            className="flex items-center justify-between p-2 bg-gray-50 rounded-lg"
                        >
                            <span className="text-sm text-gray-700">{file.name}</span>
                            <span className="text-xs text-gray-500">
                                {(file.size / 1024 / 1024).toFixed(2)} MB
                            </span>
                        </div>
                    ))}
                </div>
            )}

            {/* Upload Button */}
            <div className="mt-4">
                <Button
                    onClick={handleUpload}
                    isLoading={isUploading}
                    disabled={selectedFiles.length === 0}
                    fullWidth
                >
                    Upload {selectedFiles.length > 0 && `(${selectedFiles.length})`}
                </Button>
            </div>
        </div>
    );
};
