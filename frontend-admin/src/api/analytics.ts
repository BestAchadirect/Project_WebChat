import apiClient from './client';
import { ChatStats, ChatLog } from '../types/analytics';

export interface ChatLogFilters {
    startDate?: string;
    endDate?: string;
    minSatisfaction?: number;
    limit?: number;
    offset?: number;
}

export const analyticsApi = {
    async getChatStats(period: 'today' | 'week' | 'month' | 'all' = 'week'): Promise<ChatStats> {
        const response = await apiClient.get<ChatStats>('/analytics/stats', {
            params: { period },
        });
        return response.data;
    },

    async getChatLogs(filters?: ChatLogFilters): Promise<ChatLog[]> {
        const response = await apiClient.get<ChatLog[]>('/analytics/logs', {
            params: filters,
        });
        return response.data;
    },

    async getChatLogDetails(sessionId: string): Promise<ChatLog> {
        const response = await apiClient.get<ChatLog>(`/analytics/logs/${sessionId}`);
        return response.data;
    },
};
