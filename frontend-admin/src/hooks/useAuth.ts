import { create } from 'zustand';
import { authApi, LoginCredentials } from '../api/auth';

interface User {
    id: string;
    email: string;
    name: string;
}

interface AuthState {
    user: User | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    error: string | null;
    login: (credentials: LoginCredentials) => Promise<void>;
    logout: () => Promise<void>;
    checkAuth: () => Promise<void>;
}

export const useAuth = create<AuthState>((set) => ({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    error: null,

    login: async (credentials) => {
        set({ isLoading: true, error: null });

        // DEMO MODE: Bypass authentication for testing
        // TODO: Remove this and use real auth when backend is ready
        const demoUser = {
            id: 'demo-user-123',
            email: credentials.email,
            name: 'Demo User',
        };

        localStorage.setItem('authToken', 'demo-token-' + Date.now());
        set({
            user: demoUser,
            isAuthenticated: true,
            isLoading: false,
        });
        return;

        /* Original auth code (commented out for demo)
        try {
            const response = await authApi.login(credentials);
            localStorage.setItem('authToken', response.token);
            set({
                user: response.user,
                isAuthenticated: true,
                isLoading: false,
            });
        } catch (error: any) {
            set({
                error: error.response?.data?.message || 'Login failed',
                isLoading: false,
            });
            throw error;
        }
        */
    },

    logout: async () => {
        try {
            await authApi.logout();
        } catch (error) {
            console.error('Logout error:', error);
        } finally {
            localStorage.removeItem('authToken');
            set({
                user: null,
                isAuthenticated: false,
            });
        }
    },

    checkAuth: async () => {
        const token = localStorage.getItem('authToken');
        if (!token) {
            set({ isAuthenticated: false, user: null, isLoading: false });
            return;
        }

        // DEMO MODE: Accept any token as valid
        // TODO: Remove this and use real auth when backend is ready
        const demoUser = {
            id: 'demo-user-123',
            email: 'demo@test.com',
            name: 'Demo User',
        };

        set({
            user: demoUser,
            isAuthenticated: true,
            isLoading: false,
        });
        return;

        /* Original auth check code (commented out for demo)
        set({ isLoading: true });
        try {
            const user = await authApi.getCurrentUser();
            set({
                user,
                isAuthenticated: true,
                isLoading: false,
            });
        } catch (error) {
            localStorage.removeItem('authToken');
            set({
                user: null,
                isAuthenticated: false,
                isLoading: false,
            });
        }
        */
    },
}));
