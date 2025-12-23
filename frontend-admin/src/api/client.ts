import axios, { AxiosInstance, AxiosError } from 'axios';

const envBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').trim();
const API_BASE_URL = (envBaseUrl ? envBaseUrl : '/api/v1').replace(/\/+$/, '');

// Create axios instance
const apiClient: AxiosInstance = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('authToken');
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor for error handling
apiClient.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
        // Log error for debugging
        console.error('API Error:', error);
        return Promise.reject(error);
    }
);

export default apiClient;
