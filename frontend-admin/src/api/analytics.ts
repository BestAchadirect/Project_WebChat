import apiClient from './client';
import { ChatStats, ChatLog } from '../types/analytics';
import { PaginatedResponse } from '../types/pagination';

export interface ChatLogFilters {
    startDate?: string;
    endDate?: string;
    minSatisfaction?: number;
    page?: number;
    pageSize?: number;
}

const toNumber = (value: unknown, fallback = 0): number => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const normalizeSatisfaction = (value: unknown): number => {
    const n = toNumber(value, 0);
    // Backward compatibility: if backend sends ratio [0..1], convert to percent.
    if (n > 0 && n <= 1) return n * 100;
    return n;
};

const normalizeChatStats = (raw: any, period: ChatStats['period']): ChatStats => ({
    totalChats: toNumber(raw?.totalChats ?? raw?.total_chats, 0),
    totalMessages: toNumber(raw?.totalMessages ?? raw?.total_messages, 0),
    avgResponseTime: toNumber(raw?.avgResponseTime ?? raw?.avg_response_time, 0),
    userSatisfaction: normalizeSatisfaction(raw?.userSatisfaction ?? raw?.user_satisfaction),
    period: (raw?.period as ChatStats['period']) || period,
});

export const analyticsApi = {
    async getChatStats(period: 'today' | 'week' | 'month' | 'all' = 'week'): Promise<ChatStats> {
        const response = await apiClient.get('/analytics/stats', {
            params: { period },
        });
        return normalizeChatStats(response.data, period);
    },

    async getChatLogs(filters?: ChatLogFilters): Promise<PaginatedResponse<ChatLog>> {
        const response = await apiClient.get<PaginatedResponse<ChatLog>>('/analytics/logs', {
            params: filters,
        });
        return response.data;
    },

    async getChatLogDetails(sessionId: string): Promise<ChatLog> {
        const response = await apiClient.get<ChatLog>(`/analytics/logs/${sessionId}`);
        return response.data;
    },
};
