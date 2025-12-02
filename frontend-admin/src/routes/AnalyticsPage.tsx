import React, { useState, useEffect } from 'react';
import { analyticsApi } from '../api/analytics';
import { ChatStats } from '../types/analytics';
import { ChatStatsCards } from '../components/analytics/ChatStatsCards';
import { Spinner } from '../components/common/Spinner';

export const AnalyticsPage: React.FC = () => {
    const [stats, setStats] = useState<ChatStats | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [period, setPeriod] = useState<'today' | 'week' | 'month' | 'all'>('week');

    const fetchStats = async () => {
        setIsLoading(true);
        try {
            const data = await analyticsApi.getChatStats(period);
            setStats(data);
        } catch (error) {
            console.error('Failed to fetch stats:', error);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchStats();
    }, [period]);

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Spinner size="lg" />
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">Analytics</h1>
                    <p className="mt-2 text-gray-600">
                        Monitor your chatbot performance and user interactions
                    </p>
                </div>

                {/* Period Selector */}
                <div className="flex gap-2 bg-white rounded-lg shadow-sm p-1">
                    {(['today', 'week', 'month', 'all'] as const).map((p) => (
                        <button
                            key={p}
                            onClick={() => setPeriod(p)}
                            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${period === p
                                    ? 'bg-primary-600 text-white'
                                    : 'text-gray-600 hover:bg-gray-100'
                                }`}
                        >
                            {p.charAt(0).toUpperCase() + p.slice(1)}
                        </button>
                    ))}
                </div>
            </div>

            {stats && <ChatStatsCards stats={stats} />}

            {/* Placeholder for charts */}
            <div className="bg-white rounded-xl shadow-sm p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Chat Activity</h3>
                <div className="h-64 flex items-center justify-center border-2 border-dashed border-gray-300 rounded-lg">
                    <p className="text-gray-500">Chart visualization coming soon</p>
                </div>
            </div>

            {/* Recent Chat Logs */}
            <div className="bg-white rounded-xl shadow-sm p-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Conversations</h3>
                <div className="h-64 flex items-center justify-center border-2 border-dashed border-gray-300 rounded-lg">
                    <p className="text-gray-500">Chat logs table coming soon</p>
                </div>
            </div>
        </div>
    );
};
