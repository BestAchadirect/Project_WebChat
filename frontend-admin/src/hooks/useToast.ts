import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

interface Toast {
    id: string;
    message: string;
    type: ToastType;
}

interface ToastState {
    toasts: Toast[];
    showToast: (message: string, type: ToastType) => void;
    removeToast: (id: string) => void;
}

export const useToast = create<ToastState>((set) => ({
    toasts: [],

    showToast: (message, type) => {
        const id = Math.random().toString(36).substring(7);
        set((state) => ({
            toasts: [...state.toasts, { id, message, type }],
        }));

        // Auto-remove after 5 seconds
        setTimeout(() => {
            set((state) => ({
                toasts: state.toasts.filter((toast) => toast.id !== id),
            }));
        }, 5000);
    },

    removeToast: (id) => {
        set((state) => ({
            toasts: state.toasts.filter((toast) => toast.id !== id),
        }));
    },
}));
