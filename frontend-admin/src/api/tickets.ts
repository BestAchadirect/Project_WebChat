import apiClient from './client';
import { PaginatedResponse } from '../types/pagination';

export interface TicketReply {
    message: string;
    created_at?: string;
}

export interface Ticket {
    id: number;
    user_id: string;
    description: string;
    image_url?: string;
    image_urls?: string[];
    status: string;
    ai_summary?: string;
    admin_reply?: string;
    admin_replies?: TicketReply[];
    customer_last_activity_at?: string;
    admin_last_seen_at?: string;
    created_at: string;
    updated_at: string;
}

export const ticketsApi = {
    async listAll(params?: { page?: number; pageSize?: number }): Promise<PaginatedResponse<Ticket>> {
        const response = await apiClient.get<PaginatedResponse<Ticket>>('/tickets/all', {
            params: {
                page: params?.page ?? 1,
                pageSize: params?.pageSize ?? 20,
            },
        });
        return response.data;
    },

    async getUnreadCount(): Promise<{ count: number }> {
        const response = await apiClient.get<{ count: number }>('/tickets/unread/count');
        return response.data;
    },

    async markRead(ticketId: number): Promise<Ticket> {
        const response = await apiClient.post<Ticket>(`/tickets/${ticketId}/mark-read`);
        return response.data;
    },

    async update(ticketId: number, formData: FormData): Promise<Ticket> {
        const response = await apiClient.patch<Ticket>(`/tickets/${ticketId}`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },
};
