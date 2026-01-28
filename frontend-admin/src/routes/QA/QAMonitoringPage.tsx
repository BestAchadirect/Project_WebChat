import React, { useState, useEffect } from 'react';
import { trainingApi, QALog } from '../../api/training';
import apiClient from '../../api/client';

export const QAMonitoringPage: React.FC = () => {
    const [logs, setLogs] = useState<QALog[]>([]);
    const [loading, setLoading] = useState(true);
    const [filterStatus, setFilterStatus] = useState<string>('');
    const [filterChannel, setFilterChannel] = useState<string>('all');
    const [testQuestion, setTestQuestion] = useState('');
    const [testResult, setTestResult] = useState<{ answer: string; sources: any[] } | null>(null);
    const [testing, setTesting] = useState(false);
    const [showAllSources, setShowAllSources] = useState(false);
    const [expandedUsage, setExpandedUsage] = useState<Record<string, boolean>>({});
    const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});

    useEffect(() => {
        loadLogs();
    }, [filterStatus]);

    const loadLogs = async () => {
        try {
            setLoading(true);
            const result = await trainingApi.listQALogs(50, 0, filterStatus || undefined);
            setLogs(result);
        } catch (error) {
            console.error('Failed to load QA logs:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleTestQuestion = async () => {
        if (!testQuestion.trim()) return;
        try {
            setTesting(true);
            setTestResult(null);
            setShowAllSources(false);
            // Call chat endpoint for testing
            const response = await apiClient.post('/dashboard/qa/test-chat', {
                user_id: 'qa-tester',
                message: testQuestion,
                conversation_id: null,
            });
            setTestResult({
                answer: response.data.reply_text || response.data.reply || response.data.message || 'No response',
                sources: response.data.sources || [],
            });
            // Refresh logs to show the new test in the table
            loadLogs();
        } catch (error) {
            console.error('Test failed:', error);
            setTestResult({ answer: 'Error: Failed to get response', sources: [] });
        } finally {
            setTesting(false);
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'success': return 'bg-green-100 text-green-800';
            case 'no_answer': return 'bg-yellow-100 text-yellow-800';
            case 'fallback': return 'bg-orange-100 text-orange-800';
            case 'failed': return 'bg-red-100 text-red-800';
            default: return 'bg-gray-100 text-gray-800';
        }
    };

    const formatNumber = (value?: number | null) => {
        if (value === null || value === undefined) return '-';
        return value.toLocaleString();
    };

    const formatPercent = (value: number) => `${value.toFixed(1)}%`;

    const toggleUsage = (id: string) => {
        setExpandedUsage((prev) => ({ ...prev, [id]: !prev[id] }));
    };

    const toggleSources = (id: string) => {
        setExpandedSources((prev) => ({ ...prev, [id]: !prev[id] }));
    };

    const getStats = (items: QALog[]) => {
        const total = items.length;
        const success = items.filter((log) => log.status === 'success').length;
        const failed = items.filter((log) => log.status === 'failed' || log.status === 'no_answer' || log.status === 'fallback').length;
        const successRate = total > 0 ? (success / total) * 100 : 0;
        return { total, success, failed, successRate };
    };

    const getChannelLabel = (channel?: string | null) => {
        if (channel === 'qa_console') return 'QA Console';
        if (channel === 'widget') return 'Widget';
        return 'Unlabeled';
    };

    const getChannelBadgeClass = (channel?: string | null) => {
        if (channel === 'qa_console') return 'bg-indigo-100 text-indigo-700';
        if (channel === 'widget') return 'bg-sky-100 text-sky-700';
        return 'bg-gray-100 text-gray-500';
    };

    // Calculate stats
    const widgetLogs = logs.filter((log) => log.channel === 'widget');
    const qaConsoleLogs = logs.filter((log) => log.channel === 'qa_console');
    const unlabeledLogs = logs.filter((log) => !log.channel);
    const allStats = getStats(logs);
    const widgetStats = getStats(widgetLogs);
    const qaConsoleStats = getStats(qaConsoleLogs);
    const unlabeledStats = getStats(unlabeledLogs);
    const channelFilteredLogs = logs.filter((log) => {
        if (filterChannel === 'customer') return log.channel === 'widget';
        if (filterChannel === 'internal') return log.channel === 'qa_console';
        if (filterChannel === 'unlabeled') return !log.channel;
        return true;
    });

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-gray-900">QA + Monitoring</h1>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="flex items-center justify-between">
                        <div className="text-sm text-gray-500">All Channels</div>
                        <span className="text-xs text-gray-400">Summary</span>
                    </div>
                    <div className="mt-2 text-2xl font-bold text-gray-900">{formatNumber(allStats.total)}</div>
                    <div className="mt-2 text-xs text-gray-500">
                        <span className="text-green-700 font-semibold">{formatNumber(allStats.success)}</span> success /{' '}
                        <span className="text-red-600 font-semibold">{formatNumber(allStats.failed)}</span> failed
                    </div>
                    <div className="mt-2 text-sm font-semibold text-primary-600">{formatPercent(allStats.successRate)}</div>
                </div>
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="flex items-center justify-between">
                        <div className="text-sm text-gray-500">Widget</div>
                        <span className="text-xs text-sky-600 bg-sky-100 px-2 py-0.5 rounded-full">Customer</span>
                    </div>
                    <div className="mt-2 text-2xl font-bold text-gray-900">{formatNumber(widgetStats.total)}</div>
                    <div className="mt-2 text-xs text-gray-500">
                        <span className="text-green-700 font-semibold">{formatNumber(widgetStats.success)}</span> success /{' '}
                        <span className="text-red-600 font-semibold">{formatNumber(widgetStats.failed)}</span> failed
                    </div>
                    <div className="mt-2 text-sm font-semibold text-sky-700">{formatPercent(widgetStats.successRate)}</div>
                </div>
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="flex items-center justify-between">
                        <div className="text-sm text-gray-500">QA Console</div>
                        <span className="text-xs text-indigo-600 bg-indigo-100 px-2 py-0.5 rounded-full">Internal</span>
                    </div>
                    <div className="mt-2 text-2xl font-bold text-gray-900">{formatNumber(qaConsoleStats.total)}</div>
                    <div className="mt-2 text-xs text-gray-500">
                        <span className="text-green-700 font-semibold">{formatNumber(qaConsoleStats.success)}</span> success /{' '}
                        <span className="text-red-600 font-semibold">{formatNumber(qaConsoleStats.failed)}</span> failed
                    </div>
                    <div className="mt-2 text-sm font-semibold text-indigo-700">{formatPercent(qaConsoleStats.successRate)}</div>
                </div>
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="flex items-center justify-between">
                        <div className="text-sm text-gray-500">Unlabeled</div>
                        <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">Legacy</span>
                    </div>
                    <div className="mt-2 text-2xl font-bold text-gray-900">{formatNumber(unlabeledStats.total)}</div>
                    <div className="mt-2 text-xs text-gray-500">
                        <span className="text-green-700 font-semibold">{formatNumber(unlabeledStats.success)}</span> success /{' '}
                        <span className="text-red-600 font-semibold">{formatNumber(unlabeledStats.failed)}</span> failed
                    </div>
                    <div className="mt-2 text-sm font-semibold text-gray-600">{formatPercent(unlabeledStats.successRate)}</div>
                </div>
            </div>

            {/* Test Console */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h2 className="text-lg font-semibold">QA Test Console</h2>
                        <p className="text-xs text-gray-500 mt-1">Runs with channel: QA Console</p>
                    </div>
                </div>
                <div className="flex gap-4">
                    <input
                        type="text"
                        value={testQuestion}
                        onChange={(e) => setTestQuestion(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleTestQuestion()}
                        placeholder="Enter a test question..."
                        className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500"
                    />
                    <button
                        onClick={handleTestQuestion}
                        disabled={testing || !testQuestion.trim()}
                        className="px-6 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
                    >
                        {testing ? 'Testing...' : 'Test'}
                    </button>
                </div>

                {testResult && (
                    <div className="mt-4 p-4 bg-gray-50 rounded-lg">
                        <div className="font-medium text-gray-700 mb-2">Answer:</div>
                        <div className="text-gray-900 whitespace-pre-wrap">{testResult.answer}</div>
                        {testResult.sources.length > 0 && (
                            <div className="mt-4">
                                <div className="flex items-center justify-between mb-2">
                                    <div className="font-medium text-gray-700">Sources:</div>
                                    {testResult.sources.length > 1 && (
                                        <button
                                            type="button"
                                            onClick={() => setShowAllSources((prev) => !prev)}
                                            className="text-xs font-semibold text-primary-600 hover:text-primary-700"
                                        >
                                            {showAllSources ? 'Collapse' : 'See more'}
                                        </button>
                                    )}
                                </div>
                                <div className="space-y-2">
                                    {(showAllSources ? testResult.sources : testResult.sources.slice(0, 1)).map((source, i) => (
                                        <div key={i} className="text-sm text-gray-600 bg-white p-2 rounded border">
                                            {JSON.stringify(source)}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Logs Table */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200">
                <div className="p-4 border-b border-gray-200 flex items-center justify-between">
                    <div>
                        <h2 className="text-lg font-semibold">Channel Logs</h2>
                        <p className="text-xs text-gray-500 mt-1">Separated by widget vs QA console traffic</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                        <select
                            value={filterChannel}
                            onChange={(e) => setFilterChannel(e.target.value)}
                            className="px-4 py-2 border border-gray-300 rounded-lg"
                        >
                            <option value="all">All Channels</option>
                            <option value="customer">Customer (Widget)</option>
                            <option value="internal">Internal (QA Console)</option>
                            <option value="unlabeled">Unlabeled</option>
                        </select>
                        <select
                            value={filterStatus}
                            onChange={(e) => setFilterStatus(e.target.value)}
                            className="px-4 py-2 border border-gray-300 rounded-lg"
                        >
                            <option value="">All Statuses</option>
                            <option value="success">Success</option>
                            <option value="no_answer">No Answer</option>
                            <option value="fallback">Fallback</option>
                            <option value="failed">Failed</option>
                        </select>
                    </div>
                </div>

                {loading ? (
                    <div className="flex items-center justify-center py-12">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                    </div>
                ) : (
                    <div className="divide-y divide-gray-200">
                        {channelFilteredLogs.map((log) => (
                            <div key={log.id} className="p-4 hover:bg-gray-50">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`px-2 py-1 text-xs rounded-full ${getStatusColor(log.status)}`}>
                                                {log.status}
                                            </span>
                                            <span className={`px-2 py-1 text-xs rounded-full ${getChannelBadgeClass(log.channel)}`}>
                                                {getChannelLabel(log.channel)}
                                            </span>
                                            <span className="text-xs text-gray-500">
                                                {new Date(log.created_at).toLocaleString()}
                                            </span>
                                        </div>
                                        <div className="font-medium text-gray-900">{log.question}</div>
                                        {log.answer && (
                                            <div className="text-sm text-gray-600 mt-1 line-clamp-2">{log.answer}</div>
                                        )}
                                        {log.error_message && (
                                            <div className="text-sm text-red-600 mt-1">{log.error_message}</div>
                                        )}
                                        {log.token_usage ? (
                                            <div className="mt-3">
                                                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-700">
                                                    <span className="rounded-full bg-slate-100 px-3 py-1">
                                                        Tokens {formatNumber(log.token_usage.total_tokens)}
                                                    </span>
                                                    <span className="rounded-full bg-slate-100 px-3 py-1">
                                                        Prompt {formatNumber(log.token_usage.total_prompt_tokens)}
                                                    </span>
                                                    <span className="rounded-full bg-slate-100 px-3 py-1">
                                                        Completion {formatNumber(log.token_usage.total_completion_tokens)}
                                                    </span>
                                                    {log.token_usage.cached_prompt_tokens ? (
                                                        <span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-700">
                                                            Cached {formatNumber(log.token_usage.cached_prompt_tokens)}
                                                        </span>
                                                    ) : null}
                                                    <button
                                                        type="button"
                                                        onClick={() => toggleUsage(log.id)}
                                                        className="rounded-full border border-gray-300 px-3 py-1 text-gray-700 hover:bg-white"
                                                    >
                                                        {expandedUsage[log.id] ? 'Hide breakdown' : 'View breakdown'}
                                                    </button>
                                                    {log.sources && log.sources.length > 0 ? (
                                                        <button
                                                            type="button"
                                                            onClick={() => toggleSources(log.id)}
                                                            className="rounded-full border border-gray-300 px-3 py-1 text-gray-700 hover:bg-white"
                                                        >
                                                            {expandedSources[log.id] ? 'Collapse' : 'View sources'}
                                                        </button>
                                                    ) : null}
                                                </div>
                                                {expandedUsage[log.id] && (
                                                    <div className="mt-3 rounded-lg border border-gray-200 bg-white shadow-sm">
                                                        <div className="grid grid-cols-5 gap-2 border-b border-gray-100 bg-gray-50 px-3 py-2 text-xs font-semibold text-gray-600">
                                                            <div>Kind</div>
                                                            <div>Model</div>
                                                            <div className="text-right">Prompt</div>
                                                            <div className="text-right">Completion</div>
                                                            <div className="text-right">Total</div>
                                                        </div>
                                                        <div className="divide-y divide-gray-100">
                                                            {(log.token_usage.by_call || []).length === 0 && (
                                                                <div className="px-3 py-2 text-xs text-gray-400">No per-call details recorded.</div>
                                                            )}
                                                            {(log.token_usage.by_call || []).map((call, index) => (
                                                                <div key={`${log.id}-${index}`} className="grid grid-cols-5 gap-2 px-3 py-2 text-xs text-gray-700">
                                                                    <div className="flex items-center gap-2">
                                                                        <span className="font-medium">{call.kind}</span>
                                                                        {call.cached ? (
                                                                            <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] text-emerald-700">
                                                                                cached
                                                                            </span>
                                                                        ) : null}
                                                                    </div>
                                                                    <div className="text-gray-500">{call.model}</div>
                                                                    <div className="text-right tabular-nums">{formatNumber(call.prompt_tokens)}</div>
                                                                    <div className="text-right tabular-nums">{formatNumber(call.completion_tokens)}</div>
                                                                    <div className="text-right tabular-nums font-semibold">{formatNumber(call.total_tokens)}</div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                                {expandedSources[log.id] && log.sources && log.sources.length > 0 && (
                                                    <div className="mt-3 rounded-lg border border-gray-200 bg-white shadow-sm">
                                                        <div className="border-b border-gray-100 bg-gray-50 px-3 py-2 text-xs font-semibold text-gray-600">
                                                            Sources
                                                        </div>
                                                        <ul className="divide-y divide-gray-100">
                                                            {log.sources.map((source, index) => (
                                                                <li key={`${log.id}-source-${index}`} className="px-3 py-2 text-xs text-gray-700">
                                                                    <div className="flex items-center justify-between gap-2">
                                                                        <div className="flex flex-col gap-1">
                                                                            <span className="font-medium">
                                                                                {typeof source?.title === 'string' && source.title.trim()
                                                                                    ? source.title
                                                                                    : 'Untitled source'}
                                                                            </span>
                                                                            {typeof source?.source_id === 'string' && source.source_id.trim() ? (
                                                                                <span className="text-[11px] text-gray-400">ID: {source.source_id}</span>
                                                                            ) : null}
                                                                        </div>
                                                                        {typeof source?.relevance === 'number' ? (
                                                                            <span className="text-gray-400">rel {source.relevance.toFixed(3)}</span>
                                                                        ) : null}
                                                                    </div>
                                                                </li>
                                                            ))}
                                                        </ul>
                                                    </div>
                                                )}
                                            </div>
                                        ) : (
                                            <div className="mt-3 text-xs text-gray-400">Token usage not available</div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        ))}
                        {channelFilteredLogs.length === 0 && (
                            <div className="text-center py-12 text-gray-500">
                                No logs found for the selected filters
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
