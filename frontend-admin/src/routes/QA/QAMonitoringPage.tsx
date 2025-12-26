import React, { useState, useEffect } from 'react';
import { trainingApi, QALog } from '../../api/training';
import apiClient from '../../api/client';

export const QAMonitoringPage: React.FC = () => {
    const [logs, setLogs] = useState<QALog[]>([]);
    const [loading, setLoading] = useState(true);
    const [filterStatus, setFilterStatus] = useState<string>('');
    const [testQuestion, setTestQuestion] = useState('');
    const [testResult, setTestResult] = useState<{ answer: string; sources: any[] } | null>(null);
    const [testing, setTesting] = useState(false);

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
            // Call chat endpoint for testing
            const response = await apiClient.post('/chat/message', {
                message: testQuestion,
                conversation_id: null,
            });
            setTestResult({
                answer: response.data.reply || response.data.message || 'No response',
                sources: response.data.sources || [],
            });
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

    // Calculate stats
    const totalLogs = logs.length;
    const successCount = logs.filter(l => l.status === 'success').length;
    const failedCount = logs.filter(l => l.status === 'failed' || l.status === 'no_answer' || l.status === 'fallback').length;
    const successRate = totalLogs > 0 ? ((successCount / totalLogs) * 100).toFixed(1) : '0';

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-gray-900">QA + Monitoring</h1>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-4 gap-4">
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="text-sm text-gray-500">Total Questions</div>
                    <div className="text-2xl font-bold text-gray-900">{totalLogs}</div>
                </div>
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="text-sm text-gray-500">Successful</div>
                    <div className="text-2xl font-bold text-green-600">{successCount}</div>
                </div>
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="text-sm text-gray-500">Failed/Fallback</div>
                    <div className="text-2xl font-bold text-red-600">{failedCount}</div>
                </div>
                <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-200">
                    <div className="text-sm text-gray-500">Success Rate</div>
                    <div className="text-2xl font-bold text-primary-600">{successRate}%</div>
                </div>
            </div>

            {/* Test Console */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
                <h2 className="text-lg font-semibold mb-4">Test Console</h2>
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
                                <div className="font-medium text-gray-700 mb-2">Sources:</div>
                                <div className="space-y-2">
                                    {testResult.sources.map((source, i) => (
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
                    <h2 className="text-lg font-semibold">Recent Questions</h2>
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

                {loading ? (
                    <div className="flex items-center justify-center py-12">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                    </div>
                ) : (
                    <div className="divide-y divide-gray-200">
                        {logs.map((log) => (
                            <div key={log.id} className="p-4 hover:bg-gray-50">
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`px-2 py-1 text-xs rounded-full ${getStatusColor(log.status)}`}>
                                                {log.status}
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
                                    </div>
                                </div>
                            </div>
                        ))}
                        {logs.length === 0 && (
                            <div className="text-center py-12 text-gray-500">
                                No QA logs found
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
