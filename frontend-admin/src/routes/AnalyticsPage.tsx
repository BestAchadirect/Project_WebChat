import React, { useMemo, useState, useEffect } from 'react';
import { analyticsApi } from '../api/analytics';
import { ChatStats, ChatLog } from '../types/analytics';
import { ChatStatsCards } from '../components/analytics/ChatStatsCards';
import { Spinner } from '../components/common/Spinner';

type Period = 'today' | 'week' | 'month' | 'all';

type ActivityBucket = {
    label: string;
    count: number;
};

const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());

const formatDayLabel = (date: Date) =>
    date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

const formatHourLabel = (hour: number) =>
    new Date(2000, 0, 1, hour).toLocaleTimeString(undefined, { hour: 'numeric' });

const buildActivityBuckets = (logs: ChatLog[], period: Period): ActivityBucket[] => {
    const now = new Date();
    if (period === 'today') {
        const start = startOfDay(now);
        const buckets = Array.from({ length: 24 }, (_, hour) => ({
            label: formatHourLabel(hour),
            count: 0,
        }));
        logs.forEach((log) => {
            const ts = new Date(log.startedAt);
            if (ts < start || ts > now) return;
            const hour = ts.getHours();
            buckets[hour].count += 1;
        });
        return buckets;
    }

    const days = period === 'week' ? 7 : 30;
    const start = startOfDay(now);
    start.setDate(start.getDate() - (days - 1));
    const buckets = Array.from({ length: days }, (_, index) => {
        const day = new Date(start);
        day.setDate(start.getDate() + index);
        return {
            label: formatDayLabel(day),
            count: 0,
        };
    });

    logs.forEach((log) => {
        const ts = new Date(log.startedAt);
        if (ts < start || ts > now) return;
        const bucketIndex = Math.floor(
            (startOfDay(ts).getTime() - start.getTime()) / (24 * 60 * 60 * 1000)
        );
        if (bucketIndex >= 0 && bucketIndex < buckets.length) {
            buckets[bucketIndex].count += 1;
        }
    });

    return buckets;
};

export const AnalyticsPage: React.FC = () => {
    const [stats, setStats] = useState<ChatStats | null>(null);
    const [logs, setLogs] = useState<ChatLog[]>([]);
    const [isStatsLoading, setIsStatsLoading] = useState(true);
    const [isLogsLoading, setIsLogsLoading] = useState(true);
    const [period, setPeriod] = useState<Period>('week');
    const [expandedConversations, setExpandedConversations] = useState<Record<string, boolean>>({});

    const dateRange = useMemo(() => {
        if (period === 'all') return { start: undefined, end: undefined };
        const now = new Date();
        if (period === 'today') {
            return { start: startOfDay(now), end: now };
        }
        const start = new Date(now);
        const daysBack = period === 'week' ? 6 : 29;
        start.setDate(start.getDate() - daysBack);
        return { start: startOfDay(start), end: now };
    }, [period]);

    const fetchStats = async () => {
        setIsStatsLoading(true);
        try {
            const data = await analyticsApi.getChatStats(period);
            setStats(data);
        } catch (error) {
            console.error('Failed to fetch stats:', error);
        } finally {
            setIsStatsLoading(false);
        }
    };

    const fetchLogs = async () => {
        setIsLogsLoading(true);
        try {
            const data = await analyticsApi.getChatLogs({
                startDate: dateRange.start ? dateRange.start.toISOString() : undefined,
                endDate: dateRange.end ? dateRange.end.toISOString() : undefined,
                limit: 120,
                offset: 0,
            });
            setLogs(data || []);
        } catch (error) {
            console.error('Failed to fetch chat logs:', error);
        } finally {
            setIsLogsLoading(false);
        }
    };

    useEffect(() => {
        fetchStats();
        fetchLogs();
    }, [period]);

    const toggleConversation = (id: string) => {
        setExpandedConversations((prev) => ({ ...prev, [id]: !prev[id] }));
    };

    const activityBuckets = useMemo(() => buildActivityBuckets(logs, period), [logs, period]);
    const maxActivity = Math.max(...activityBuckets.map((bucket) => bucket.count), 0);
    const recentLogs = logs.slice(0, 12);

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

            {isStatsLoading ? (
                <div className="flex items-center justify-center h-40">
                    <Spinner size="lg" />
                </div>
            ) : (
                stats && <ChatStatsCards stats={stats} />
            )}

            {/* Chat Activity */}
            <div className="bg-white rounded-xl shadow-sm p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="text-lg font-semibold text-gray-900">Chat Activity</h3>
                        <p className="text-xs text-gray-500 mt-1">
                            Conversations started per {period === 'today' ? 'hour' : 'day'}
                        </p>
                    </div>
                    <div className="text-xs text-gray-500">
                        {logs.length.toLocaleString()} conversations loaded
                    </div>
                </div>

                {isLogsLoading ? (
                    <div className="h-64 flex items-center justify-center">
                        <Spinner size="lg" />
                    </div>
                ) : (
                    <div className="h-64 flex items-end gap-2">
                        {activityBuckets.map((bucket, index) => {
                            const heightPercent = maxActivity ? (bucket.count / maxActivity) * 100 : 0;
                            return (
                                <div
                                    key={`${bucket.label}-${index}`}
                                    className="flex flex-1 flex-col items-center justify-end gap-2"
                                >
                                    <div className="w-full flex items-end justify-center h-52">
                                        <div
                                            className="w-full rounded-t-lg bg-primary-500/80 transition-all"
                                            style={{ height: `${heightPercent}%` }}
                                            title={`${bucket.count} conversations`}
                                        />
                                    </div>
                                    <div className="text-[10px] text-gray-500 whitespace-nowrap">
                                        {bucket.label}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Recent Chat Logs */}
            <div className="bg-white rounded-xl shadow-sm p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h3 className="text-lg font-semibold text-gray-900">Recent Conversations</h3>
                        <p className="text-xs text-gray-500 mt-1">Latest sessions with message previews</p>
                    </div>
                </div>

                {isLogsLoading ? (
                    <div className="h-40 flex items-center justify-center">
                        <Spinner size="lg" />
                    </div>
                ) : (
                    <div className="divide-y divide-gray-200">
                        {recentLogs.map((log) => {
                            const messages = Array.isArray(log.messages) ? log.messages : [];
                            const lastMessage = messages[messages.length - 1];
                            const isExpanded = Boolean(expandedConversations[log.id]);
                            return (
                                <div key={log.id} className="py-4 hover:bg-gray-50">
                                    <div className="flex items-start justify-between gap-4 px-2">
                                        <div className="flex-1 select-text">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-semibold text-gray-900">
                                                    Session {log.sessionId}
                                                </span>
                                                {log.userId && (
                                                    <span className="text-xs text-gray-500">User {log.userId}</span>
                                                )}
                                            </div>
                                            <div className="text-xs text-gray-500 mt-1">
                                                {new Date(log.startedAt).toLocaleString()}
                                            </div>
                                            {lastMessage && (
                                                <div className="mt-2 text-sm text-gray-700 line-clamp-2">
                                                    <span className="font-medium capitalize">{lastMessage.role}:</span>{' '}
                                                    {lastMessage.content}
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-3 text-right">
                                            <div>
                                                <div className="text-lg font-semibold text-gray-900">
                                                    {log.messageCount}
                                                </div>
                                                <div className="text-xs text-gray-500">messages</div>
                                            </div>
                                            <button
                                                type="button"
                                                onClick={() => toggleConversation(log.id)}
                                                aria-expanded={isExpanded}
                                                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-white hover:text-gray-700"
                                                title={isExpanded ? 'Collapse conversation' : 'Expand conversation'}
                                            >
                                                <svg
                                                    className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                                    viewBox="0 0 20 20"
                                                    fill="currentColor"
                                                    aria-hidden="true"
                                                >
                                                    <path d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
                                                </svg>
                                            </button>
                                        </div>
                                    </div>

                                    {isExpanded && (
                                        <div className="pb-4 px-2">
                                            <div className="rounded-lg border border-gray-200 bg-gray-50">
                                                <div className="divide-y divide-gray-200">
                                                    {messages.map((msg) => (
                                                        <div key={msg.id} className="px-3 py-2">
                                                            <div className="text-[11px] uppercase text-gray-400">
                                                                {msg.role} | {new Date(msg.timestamp).toLocaleString()}
                                                            </div>
                                                            <div className="text-sm text-gray-700 whitespace-pre-wrap mt-1">
                                                                {msg.content}
                                                            </div>
                                                        </div>
                                                    ))}
                                                    {messages.length === 0 && (
                                                        <div className="px-3 py-3 text-sm text-gray-500">
                                                            No messages available for this session.
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                        {recentLogs.length === 0 && (
                            <div className="py-10 text-center text-gray-500">
                                No conversations found for this period.
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
