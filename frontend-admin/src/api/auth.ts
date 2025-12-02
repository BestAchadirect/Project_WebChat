import apiClient from './client';

export interface LoginCredentials {
    email: string;
    password: string;
}

export interface AuthResponse {
    token: string;
    user: {
        id: string;
        email: string;
        name: string;
    };
}

export const authApi = {
    async login(credentials: LoginCredentials): Promise<AuthResponse> {
        const response = await apiClient.post<AuthResponse>('/auth/login', credentials);
        return response.data;
    },

    async logout(): Promise<void> {
        await apiClient.post('/auth/logout');
        localStorage.removeItem('authToken');
    },

    async getCurrentUser() {
        const response = await apiClient.get('/auth/me');
        return response.data;
    },
};
