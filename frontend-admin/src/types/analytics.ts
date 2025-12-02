export interface ChatStats {
    totalChats: number;
    totalMessages: number;
    avgResponseTime: number;
    userSatisfaction: number;
    period: 'today' | 'week' | 'month' | 'all';
}

export interface ChatLog {
    id: string;
    sessionId: string;
    userId?: string;
    startedAt: string;
    endedAt?: string;
    messageCount: number;
    userSatisfaction?: number;
    messages: ChatMessage[];
}

export interface ChatMessage {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    metadata?: {
        products?: any[];
        responseTime?: number;
    };
}
