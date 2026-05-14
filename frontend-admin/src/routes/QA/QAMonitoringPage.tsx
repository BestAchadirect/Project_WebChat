import { useEffect, useMemo, useState } from 'react';

import apiClient from '../../api/client';
import {
    ChatFailureAnalysis,
    ChatMetricsSummary,
    QALog,
    RegressionReviewBundle,
    trainingApi,
} from '../../api/training';
import { PaginationControls } from '../../components/common/PaginationControls';
import { defaultPageSize } from '../../constants/pagination';
import { getAssistantMessageText, normalizeChatComponents } from '../../utils/chatComponentContract';

type ChannelFilter = 'all' | 'customer' | 'internal' | 'unlabeled';

type LoadLogsParams = {
    page?: number;
    pageSize?: number;
    status?: string;
    channel?: ChannelFilter;
    workflow?: string;
    groundingStatus?: string;
    failureBucket?: string;
    search?: string;
};

const FAILURE_BUCKET_LABELS: Record<string, string> = {
    no_answer: 'No answer',
    clarification_loop: 'Clarification loop',
    mixed_intent_clarification: 'Mixed intent',
    hard_constraint_no_match: 'Hard no-match',
    related_product_anchor_reuse: 'Related reuse',
    context_leak: 'Context leak',
    routing_mismatch: 'Routing mismatch',
    catalog_unrelated_match: 'Weak grounding',
    other: 'Other',
};

const GROUNDING_LABELS: Record<string, string> = {
    grounded: 'Grounded',
    needs_clarification: 'Clarify',
    unrelated: 'Unrelated',
    weak: 'Weak',
};

const WORKFLOW_OPTIONS = ['', 'catalog', 'knowledge', 'fallback', 'general_talking', 'store_overview'];
const FAILURE_BUCKET_OPTIONS = [
    '',
    'hard_constraint_no_match',
    'mixed_intent_clarification',
    'clarification_loop',
    'related_product_anchor_reuse',
    'context_leak',
    'routing_mismatch',
    'catalog_unrelated_match',
    'no_answer',
    'other',
];
const GROUNDING_OPTIONS = ['', 'grounded', 'needs_clarification', 'unrelated', 'weak'];
const STATUS_OPTIONS = ['', 'success', 'no_answer', 'fallback', 'failed'];

const mapChannelParam = (channel: ChannelFilter): string | undefined => {
    switch (channel) {
        case 'customer':
            return 'widget';
        case 'internal':
            return 'qa_console';
        case 'unlabeled':
            return 'unlabeled';
        default:
            return undefined;
    }
};

const formatNumber = (value?: number | null) => {
    if (value === null || value === undefined || Number.isNaN(value)) return '-';
    return value.toLocaleString();
};

const truncate = (value: string, maxLength: number) => {
    const text = String(value || '').trim();
    if (text.length <= maxLength) return text;
    return `${text.slice(0, maxLength - 1)}…`;
};

const formatJson = (value: unknown) => JSON.stringify(value, null, 2);

const getChannelLabel = (channel?: string | null) => {
    if (channel === 'qa_console') return 'QA Console';
    if (channel === 'widget') return 'Widget';
    return 'Unlabeled';
};

const getChannelBadgeClass = (channel?: string | null) => {
    if (channel === 'qa_console') return 'bg-indigo-100 text-indigo-700 ring-indigo-200';
    if (channel === 'widget') return 'bg-sky-100 text-sky-700 ring-sky-200';
    return 'bg-slate-100 text-slate-500 ring-slate-200';
};

const getStatusBadgeClass = (status: string) => {
    switch (status) {
        case 'success':
            return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
        case 'no_answer':
            return 'bg-amber-100 text-amber-800 ring-amber-200';
        case 'fallback':
            return 'bg-orange-100 text-orange-800 ring-orange-200';
        case 'failed':
            return 'bg-red-100 text-red-700 ring-red-200';
        default:
            return 'bg-slate-100 text-slate-600 ring-slate-200';
    }
};

const getFailureBadgeClass = (bucket: string) => {
    switch (bucket) {
        case 'hard_constraint_no_match':
        case 'context_leak':
        case 'clarification_loop':
        case 'routing_mismatch':
        case 'related_product_anchor_reuse':
            return 'bg-rose-100 text-rose-700 ring-rose-200';
        case 'mixed_intent_clarification':
        case 'catalog_unrelated_match':
        case 'no_answer':
            return 'bg-amber-100 text-amber-800 ring-amber-200';
        default:
            return 'bg-slate-100 text-slate-600 ring-slate-200';
    }
};

const getGroundingBadgeClass = (status: string) => {
    switch (status) {
        case 'grounded':
            return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
        case 'needs_clarification':
            return 'bg-amber-100 text-amber-800 ring-amber-200';
        case 'weak':
        case 'unrelated':
            return 'bg-rose-100 text-rose-700 ring-rose-200';
        default:
            return 'bg-slate-100 text-slate-600 ring-slate-200';
    }
};

const getFailureTitle = (bucket: string) => FAILURE_BUCKET_LABELS[bucket] || bucket || 'Other';

const getMetrics = (log: QALog): ChatMetricsSummary => {
    return log.token_usage?.chat_metrics ?? {};
};

const getFailureAnalysis = (log: QALog): ChatFailureAnalysis | null => {
    const metrics = getMetrics(log);
    if (metrics.failure_analysis) return metrics.failure_analysis;
    if (!metrics.failure_bucket && !metrics.failure_reason && !metrics.failure_suggested_action) return null;
    return {
        bucket: metrics.failure_bucket || 'other',
        confidence: metrics.failure_confidence ?? 0,
        reason: metrics.failure_reason || 'No reason provided.',
        suggested_action: metrics.failure_suggested_action || 'Review manually.',
        severity: metrics.failure_severity || 'review',
        signals: metrics.failure_signals || [],
    };
};

const getRowSummary = (log: QALog) => {
    const metrics = getMetrics(log);
    const analysis = getFailureAnalysis(log);
    const failureBucket = String(analysis?.bucket || metrics.failure_bucket || '').trim();
    const groundingStatus = String(metrics.grounding_status || '').trim();
    const failureSeverity = String(analysis?.severity || metrics.failure_severity || '').trim();
    const isFlagged = Boolean(
        failureBucket && failureBucket !== 'other' ||
        groundingStatus && groundingStatus !== 'grounded' ||
        log.status !== 'success'
    );

    return {
        failureBucket,
        groundingStatus,
        failureSeverity,
        isFlagged,
        failureTitle: getFailureTitle(failureBucket),
    };
};

export const QAMonitoringPage = (): JSX.Element => {
    const [logs, setLogs] = useState<QALog[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(defaultPageSize);
    const [totalItems, setTotalItems] = useState(0);
    const [totalPages, setTotalPages] = useState(1);
    const [loading, setLoading] = useState(true);
    const [filterStatus, setFilterStatus] = useState('');
    const [filterChannel, setFilterChannel] = useState<ChannelFilter>('all');
    const [filterWorkflow, setFilterWorkflow] = useState('');
    const [filterGroundingStatus, setFilterGroundingStatus] = useState('');
    const [filterFailureBucket, setFilterFailureBucket] = useState('');
    const [searchInput, setSearchInput] = useState('');
    const [appliedSearch, setAppliedSearch] = useState('');
    const [selectedLogId, setSelectedLogId] = useState<string | null>(null);
    const [testQuestion, setTestQuestion] = useState('');
    const [testResult, setTestResult] = useState<{ answer: string; sources: any[] } | null>(null);
    const [testing, setTesting] = useState(false);
    const [showAllSources, setShowAllSources] = useState(false);
    const [reviewBundle, setReviewBundle] = useState<RegressionReviewBundle | null>(null);
    const [reviewBundleLoading, setReviewBundleLoading] = useState(false);
    const [reviewBundleError, setReviewBundleError] = useState('');
    const [reviewBundleCopied, setReviewBundleCopied] = useState('');

    const loadLogs = async (params: LoadLogsParams = {}) => {
        const page = params.page ?? currentPage;
        const nextPageSize = params.pageSize ?? pageSize;
        const status = params.status ?? filterStatus;
        const channel = params.channel ?? filterChannel;
        const workflow = params.workflow ?? filterWorkflow;
        const groundingStatus = params.groundingStatus ?? filterGroundingStatus;
        const failureBucket = params.failureBucket ?? filterFailureBucket;
        const search = params.search ?? appliedSearch;

        try {
            setLoading(true);
            const result = await trainingApi.listQALogs({
                page,
                pageSize: nextPageSize,
                status: status || undefined,
                channel: mapChannelParam(channel),
                workflow: workflow || undefined,
                groundingStatus: groundingStatus || undefined,
                failureBucket: failureBucket || undefined,
                search: search || undefined,
            });
            setLogs(result.items);
            setCurrentPage(result.page);
            setPageSize(result.pageSize);
            setTotalItems(result.totalItems);
            setTotalPages(result.totalPages);
            setSelectedLogId((current) => {
                if (current && result.items.some((item) => item.id === current)) {
                    return current;
                }
                return result.items[0]?.id ?? null;
            });
        } catch (error) {
            console.error('Failed to load QA logs:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        setCurrentPage(1);
        void loadLogs({ page: 1 });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterStatus, filterChannel, filterWorkflow, filterGroundingStatus, filterFailureBucket, appliedSearch]);

    useEffect(() => {
        if (logs.length === 0) {
            setSelectedLogId(null);
            return;
        }
        if (!selectedLogId || !logs.some((item) => item.id === selectedLogId)) {
            setSelectedLogId(logs[0].id);
        }
    }, [logs, selectedLogId]);

    useEffect(() => {
        setReviewBundle(null);
        setReviewBundleError('');
        setReviewBundleCopied('');
    }, [selectedLogId]);

    const handleTestQuestion = async () => {
        if (!testQuestion.trim()) return;
        try {
            setTesting(true);
            setTestResult(null);
            setShowAllSources(false);
            const response = await apiClient.post('/dashboard/qa/test-chat', {
                user_id: 'qa-tester',
                message: testQuestion,
                conversation_id: null,
            });
            const components = normalizeChatComponents(response.data.components);
            setTestResult({
                answer: getAssistantMessageText(components) || 'No response',
                sources: response.data.sources || [],
            });
            void loadLogs({ page: currentPage, pageSize });
        } catch (error) {
            console.error('Test failed:', error);
            setTestResult({ answer: 'Error: Failed to get response', sources: [] });
        } finally {
            setTesting(false);
        }
    };

    const handleExportReviewBundle = async () => {
        if (!selectedLog) return;
        try {
            setReviewBundleLoading(true);
            setReviewBundleError('');
            setReviewBundleCopied('');
            setReviewBundle(null);
            const bundle = await trainingApi.getReviewBundle(selectedLog.id);
            setReviewBundle(bundle);
        } catch (error) {
            console.error('Failed to export review bundle:', error);
            setReviewBundleError('Failed to export the review bundle for this QA log.');
        } finally {
            setReviewBundleLoading(false);
        }
    };

    const copyReviewBundleJson = async (section: 'full' | 'coverage' | 'response') => {
        if (!reviewBundle) return;
        let payload: unknown = reviewBundle;
        let label = 'Bundle JSON';
        if (section === 'coverage') {
            payload = reviewBundle.coverage_case_template;
            label = 'Coverage template';
        } else if (section === 'response') {
            payload = reviewBundle.response_contract_template;
            label = 'Response template';
        }
        try {
            await window.navigator.clipboard.writeText(formatJson(payload));
            setReviewBundleCopied(`${label} copied`);
        } catch (error) {
            console.error('Failed to copy review bundle JSON:', error);
            setReviewBundleCopied(`Could not copy ${label.toLowerCase()}`);
        }
    };

    const selectedLog = useMemo(() => {
        if (!logs.length) return null;
        if (selectedLogId) {
            const found = logs.find((item) => item.id === selectedLogId);
            if (found) return found;
        }
        return logs[0] || null;
    }, [logs, selectedLogId]);

    const visibleStats = useMemo(() => {
        const total = logs.length;
        const successful = logs.filter((log) => log.status === 'success').length;
        const flagged = logs.filter((log) => getRowSummary(log).isFlagged).length;
        const hardNoMatch = logs.filter((log) => getRowSummary(log).failureBucket === 'hard_constraint_no_match').length;
        const relatedReuse = logs.filter((log) => getRowSummary(log).failureBucket === 'related_product_anchor_reuse').length;
        const contextLeak = logs.filter((log) => getRowSummary(log).failureBucket === 'context_leak').length;
        const clarificationLoop = logs.filter((log) => getRowSummary(log).failureBucket === 'clarification_loop').length;
        const mixedIntent = logs.filter((log) => getRowSummary(log).failureBucket === 'mixed_intent_clarification').length;
        const groundingIssues = logs.filter((log) => {
            const status = String(getMetrics(log).grounding_status || '').trim();
            return status && status !== 'grounded';
        }).length;

        const bucketCounts = logs.reduce<Record<string, number>>((acc, log) => {
            const bucket = getRowSummary(log).failureBucket || 'other';
            acc[bucket] = (acc[bucket] || 0) + 1;
            return acc;
        }, {});

        const topBuckets = Object.entries(bucketCounts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5);

        return {
            total,
            successful,
            flagged,
            hardNoMatch,
            relatedReuse,
            contextLeak,
            clarificationLoop,
            mixedIntent,
            groundingIssues,
            topBuckets,
        };
    }, [logs]);

    const selectedMetrics = selectedLog ? getMetrics(selectedLog) : null;
    const selectedAnalysis = selectedLog ? getFailureAnalysis(selectedLog) : null;
    const selectedSources = selectedLog?.sources || [];
    const selectedByCall = selectedLog?.token_usage?.by_call || [];
    const selectedWorkflow = selectedMetrics?.workflow || selectedMetrics?.response_workflow || '-';
    const selectedGrounding = String(selectedMetrics?.grounding_status || '').trim();
    const selectedFailureBucket = String(selectedAnalysis?.bucket || selectedMetrics?.failure_bucket || '').trim();
    const selectedFailureTitle = getFailureTitle(selectedFailureBucket);

    const workflowLabel = (value: string) => {
        switch (value) {
            case 'catalog':
                return 'Catalog';
            case 'knowledge':
                return 'Knowledge';
            case 'fallback':
                return 'Fallback';
            case 'general_talking':
                return 'General';
            case 'store_overview':
                return 'Store overview';
            default:
                return value || 'All';
        }
    };

    const clearFilters = () => {
        setFilterStatus('');
        setFilterChannel('all');
        setFilterWorkflow('');
        setFilterGroundingStatus('');
        setFilterFailureBucket('');
        setSearchInput('');
        setAppliedSearch('');
    };

    const handlePaginationChange = async ({ currentPage: nextPage, pageSize: nextPageSize }: { currentPage: number; pageSize: number }) => {
        if (nextPage === currentPage && nextPageSize === pageSize) return;
        await loadLogs({ page: nextPage, pageSize: nextPageSize });
    };

    const setSearchFilter = () => {
        setAppliedSearch(searchInput.trim());
    };

    return (
        <div className="space-y-6">
            <section className="relative overflow-hidden rounded-3xl border border-slate-200 bg-slate-950 px-6 py-6 text-white shadow-xl">
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(56,189,248,0.2),_transparent_35%),radial-gradient(circle_at_bottom_left,_rgba(244,114,182,0.18),_transparent_40%)]" />
                <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
                    <div className="max-w-3xl">
                        <div className="text-xs uppercase tracking-[0.28em] text-slate-400">Quality / Monitoring</div>
                        <h1 className="mt-2 text-3xl font-semibold tracking-tight">QA Monitoring</h1>
                        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                            Triage chat failures by bucket, grounding status, and workflow before opening the raw log.
                            This view is tuned to expose routing mistakes, hard no-matches, context leaks, and repeated clarification loops fast.
                        </p>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        {visibleStats.topBuckets.length > 0 ? (
                            visibleStats.topBuckets.map(([bucket, count]) => (
                                <button
                                    key={bucket}
                                    type="button"
                                    onClick={() => setFilterFailureBucket(bucket)}
                                    className={`rounded-full border px-3 py-1 text-xs font-semibold transition ${
                                        filterFailureBucket === bucket
                                            ? 'border-white bg-white text-slate-950'
                                            : 'border-white/20 bg-white/10 text-white hover:bg-white/15'
                                    }`}
                                    title="Filter to this failure bucket"
                                >
                                    {getFailureTitle(bucket)} {count}
                                </button>
                            ))
                        ) : (
                            <span className="rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs text-slate-300">
                                No failures on this page
                            </span>
                        )}
                    </div>
                </div>
            </section>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-6">
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-1">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Loaded rows</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">{formatNumber(visibleStats.total)}</div>
                    <div className="mt-2 text-sm text-slate-500">{formatNumber(totalItems)} total across the current server filter</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-1">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Flagged turns</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">{formatNumber(visibleStats.flagged)}</div>
                    <div className="mt-2 text-sm text-slate-500">Rows that are likely worth opening first</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-1">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Hard no-match</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">{formatNumber(visibleStats.hardNoMatch)}</div>
                    <div className="mt-2 text-sm text-slate-500">Exact constraint misses that need grounding discipline</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-1">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Context leaks</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">{formatNumber(visibleStats.contextLeak)}</div>
                    <div className="mt-2 text-sm text-slate-500">Stale filters or reused anchors that should have reset</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-1">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Related reuse</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">{formatNumber(visibleStats.relatedReuse)}</div>
                    <div className="mt-2 text-sm text-slate-500">Similar-product searches that repeated the anchor</div>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-1">
                    <div className="text-xs uppercase tracking-wide text-slate-500">Grounding issues</div>
                    <div className="mt-2 text-3xl font-semibold text-slate-900">{formatNumber(visibleStats.groundingIssues)}</div>
                    <div className="mt-2 text-sm text-slate-500">Weak, unrelated, or clarify-only responses</div>
                </div>
            </div>

            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                        <h2 className="text-lg font-semibold text-slate-900">Triage filters</h2>
                        <p className="mt-1 text-sm text-slate-500">Use these to narrow the queue to the exact failure mode you want to inspect.</p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                        {filterStatus || filterChannel !== 'all' || filterWorkflow || filterGroundingStatus || filterFailureBucket || appliedSearch ? (
                            <>
                                <span className="rounded-full bg-slate-100 px-3 py-1">Filters active</span>
                                <button
                                    type="button"
                                    onClick={clearFilters}
                                    className="rounded-full border border-slate-300 px-3 py-1 font-semibold text-slate-700 hover:bg-slate-50"
                                >
                                    Reset filters
                                </button>
                            </>
                        ) : (
                            <span className="rounded-full bg-slate-100 px-3 py-1">Showing the current QA page</span>
                        )}
                    </div>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
                    <label className="block">
                        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Channel</span>
                        <select
                            value={filterChannel}
                            onChange={(e) => setFilterChannel(e.target.value as ChannelFilter)}
                            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                        >
                            <option value="all">All channels</option>
                            <option value="customer">Customer</option>
                            <option value="internal">Internal</option>
                            <option value="unlabeled">Unlabeled</option>
                        </select>
                    </label>

                    <label className="block">
                        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Status</span>
                        <select
                            value={filterStatus}
                            onChange={(e) => setFilterStatus(e.target.value)}
                            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                        >
                            {STATUS_OPTIONS.map((option) => (
                                <option key={option || 'all'} value={option}>
                                    {option ? option.replace('_', ' ') : 'All statuses'}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="block">
                        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Workflow</span>
                        <select
                            value={filterWorkflow}
                            onChange={(e) => setFilterWorkflow(e.target.value)}
                            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                        >
                            {WORKFLOW_OPTIONS.map((option) => (
                                <option key={option || 'all'} value={option}>
                                    {workflowLabel(option)}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="block">
                        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Grounding</span>
                        <select
                            value={filterGroundingStatus}
                            onChange={(e) => setFilterGroundingStatus(e.target.value)}
                            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                        >
                            {GROUNDING_OPTIONS.map((option) => (
                                <option key={option || 'all'} value={option}>
                                    {option ? GROUNDING_LABELS[option] || option : 'All grounding states'}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="block">
                        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Failure bucket</span>
                        <select
                            value={filterFailureBucket}
                            onChange={(e) => setFilterFailureBucket(e.target.value)}
                            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                        >
                            {FAILURE_BUCKET_OPTIONS.map((option) => (
                                <option key={option || 'all'} value={option}>
                                    {option ? getFailureTitle(option) : 'All failure buckets'}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="block md:col-span-2 xl:col-span-1">
                        <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">Search</span>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={searchInput}
                                onChange={(e) => setSearchInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        setSearchFilter();
                                    }
                                }}
                                placeholder="Search question or answer"
                                className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                            />
                            <button
                                type="button"
                                onClick={setSearchFilter}
                                className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
                            >
                                Find
                            </button>
                        </div>
                    </label>
                </div>
            </section>

            <section className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
                <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
                    <div className="border-b border-slate-200 px-5 py-4">
                        <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
                            <div>
                                <h2 className="text-lg font-semibold text-slate-900">Triage queue</h2>
                                <p className="mt-1 text-sm text-slate-500">
                                    Open the most suspicious turn first. Each row surfaces the bucket, grounding state, and a short answer preview.
                                </p>
                            </div>
                            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                                {appliedSearch ? <span className="rounded-full bg-slate-100 px-3 py-1">Search: {truncate(appliedSearch, 24)}</span> : null}
                                {filterFailureBucket ? <span className="rounded-full bg-slate-100 px-3 py-1">Bucket: {getFailureTitle(filterFailureBucket)}</span> : null}
                                {filterGroundingStatus ? <span className="rounded-full bg-slate-100 px-3 py-1">Grounding: {GROUNDING_LABELS[filterGroundingStatus] || filterGroundingStatus}</span> : null}
                            </div>
                        </div>
                    </div>

                    {loading ? (
                        <div className="flex items-center justify-center py-16">
                            <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-slate-900" />
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="px-5 py-16 text-center text-slate-500">
                            No QA logs found for the current filters.
                        </div>
                    ) : (
                        <div className="divide-y divide-slate-100">
                            {logs.map((log) => {
                                const metrics = getMetrics(log);
                                const analysis = getFailureAnalysis(log);
                                const row = getRowSummary(log);
                                const isSelected = selectedLogId === log.id;
                                return (
                                    <button
                                        key={log.id}
                                        type="button"
                                        onClick={() => setSelectedLogId(log.id)}
                                        className={`block w-full px-5 py-4 text-left transition ${
                                            isSelected ? 'bg-slate-50' : 'hover:bg-slate-50/80'
                                        }`}
                                    >
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${getStatusBadgeClass(log.status)}`}>
                                                {log.status}
                                            </span>
                                            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${getChannelBadgeClass(log.channel)}`}>
                                                {getChannelLabel(log.channel)}
                                            </span>
                                            {row.failureBucket ? (
                                                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${getFailureBadgeClass(row.failureBucket)}`}>
                                                    {row.failureTitle}
                                                </span>
                                            ) : null}
                                            {row.groundingStatus ? (
                                                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${getGroundingBadgeClass(row.groundingStatus)}`}>
                                                    {GROUNDING_LABELS[row.groundingStatus] || row.groundingStatus}
                                                </span>
                                            ) : null}
                                            <span className="text-xs text-slate-400">{new Date(log.created_at).toLocaleString()}</span>
                                        </div>

                                        <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_240px]">
                                            <div>
                                                <div className="text-sm font-semibold text-slate-900">
                                                    {truncate(log.question, 120)}
                                                </div>
                                                {log.answer ? (
                                                    <div className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">
                                                        {truncate(log.answer, 180)}
                                                    </div>
                                                ) : null}
                                            </div>

                                            <div className="flex flex-wrap gap-2 lg:justify-end">
                                                <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-600">
                                                    Workflow {workflowLabel(String(metrics.workflow || metrics.response_workflow || ''))}
                                                </span>
                                                <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-600">
                                                    Products {formatNumber(metrics.product_count)}
                                                </span>
                                                <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-600">
                                                    Sources {formatNumber(metrics.source_count)}
                                                </span>
                                                <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-600">
                                                    LLM {formatNumber(metrics.llm_call_count)}
                                                </span>
                                                <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-600">
                                                    Grounding {truncate(String(metrics.grounding_status || 'unknown'), 18)}
                                                </span>
                                            </div>
                                        </div>

                                        <div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500">
                                            <span className="line-clamp-1">{analysis?.reason || 'No high-confidence failure label was assigned.'}</span>
                                            {row.isFlagged ? <span className="font-semibold text-rose-600">Needs review</span> : <span>Stable</span>}
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    )}

                    <PaginationControls
                        currentPage={currentPage}
                        pageSize={pageSize}
                        totalItems={totalItems}
                        totalPages={totalPages}
                        isLoading={loading}
                        onChange={handlePaginationChange}
                    />
                </div>

                <aside className="space-y-6 xl:sticky xl:top-6 xl:self-start">
                    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
                        <div className="border-b border-slate-200 px-5 py-4">
                            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                                <div>
                                    <h2 className="text-lg font-semibold text-slate-900">Selected turn</h2>
                                    <p className="mt-1 text-sm text-slate-500">This panel explains why the turn failed or why it was classified as safe.</p>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleExportReviewBundle}
                                    disabled={!selectedLog || reviewBundleLoading}
                                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {reviewBundleLoading ? 'Exporting…' : 'Export review bundle'}
                                </button>
                            </div>
                        </div>

                        {!selectedLog ? (
                            <div className="px-5 py-10 text-sm text-slate-500">
                                Select a log row to inspect the full conversation snapshot.
                            </div>
                        ) : (
                            <div className="space-y-5 px-5 py-5">
                                <div
                                    className={`rounded-2xl border p-4 ${
                                        selectedAnalysis && selectedAnalysis.severity === 'high'
                                            ? 'border-rose-200 bg-rose-50'
                                            : selectedAnalysis && selectedAnalysis.severity === 'medium'
                                                ? 'border-amber-200 bg-amber-50'
                                                : 'border-slate-200 bg-slate-50'
                                    }`}
                                >
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${getFailureBadgeClass(selectedFailureBucket)}`}>
                                            {selectedFailureTitle}
                                        </span>
                                        {selectedGrounding ? (
                                            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ${getGroundingBadgeClass(selectedGrounding)}`}>
                                                {GROUNDING_LABELS[selectedGrounding] || selectedGrounding}
                                            </span>
                                        ) : null}
                                        <span className="rounded-full bg-white/80 px-2.5 py-1 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200">
                                            Confidence {selectedAnalysis ? selectedAnalysis.confidence.toFixed(2) : '0.00'}
                                        </span>
                                    </div>
                                    <div className="mt-4 text-sm font-semibold text-slate-900">Why this turn is interesting</div>
                                    <div className="mt-2 text-sm leading-6 text-slate-700">
                                        {selectedAnalysis?.reason || 'No high-confidence failure bucket was assigned.'}
                                    </div>
                                    <div className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested next action</div>
                                    <div className="mt-1 text-sm leading-6 text-slate-700">
                                        {selectedAnalysis?.suggested_action || 'Review manually and decide whether to add a regression case.'}
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-3">
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Workflow</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">{workflowLabel(String(selectedWorkflow))}</div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Route</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">{selectedMetrics?.route || '-'}</div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Products</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">{formatNumber(selectedMetrics?.product_count)}</div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Sources</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">{formatNumber(selectedMetrics?.source_count)}</div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">LLM calls</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">{formatNumber(selectedMetrics?.llm_call_count)}</div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Latency</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">
                                            {selectedMetrics?.latency_total_ms ? `${selectedMetrics.latency_total_ms.toFixed(1)} ms` : '-'}
                                        </div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">State merge</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">
                                            {selectedMetrics?.conversation_state_filter_merge_applied ? 'Applied' : 'Not applied'}
                                        </div>
                                    </div>
                                    <div className="rounded-xl border border-slate-200 bg-white p-3">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Status</div>
                                        <div className="mt-1 text-sm font-semibold text-slate-900">{selectedLog.status}</div>
                                    </div>
                                </div>

                                <div className="rounded-xl border border-slate-200 bg-white p-4">
                                    <div className="text-xs uppercase tracking-wide text-slate-500">User message</div>
                                    <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-900">{selectedLog.question}</div>
                                </div>

                                <div className="rounded-xl border border-slate-200 bg-white p-4">
                                    <div className="text-xs uppercase tracking-wide text-slate-500">Assistant answer</div>
                                    <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-900">
                                        {selectedLog.answer || 'No answer text recorded.'}
                                    </div>
                                </div>

                                <div className="rounded-xl border border-slate-200 bg-white p-4">
                                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                                        <div>
                                            <div className="text-xs uppercase tracking-wide text-slate-500">Regression review bundle</div>
                                            <div className="mt-1 text-sm leading-6 text-slate-600">
                                                Export a review seed for this QA log, then promote it into the correct regression dataset after you confirm the expected behavior.
                                            </div>
                                        </div>
                                        {reviewBundle ? (
                                            <div className="flex flex-wrap gap-2">
                                                <button
                                                    type="button"
                                                    onClick={() => void copyReviewBundleJson('full')}
                                                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                                                >
                                                    Copy bundle JSON
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => void copyReviewBundleJson('coverage')}
                                                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                                                >
                                                    Copy coverage template
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => void copyReviewBundleJson('response')}
                                                    className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                                                >
                                                    Copy response template
                                                </button>
                                            </div>
                                        ) : null}
                                    </div>

                                    {reviewBundleError ? (
                                        <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                                            {reviewBundleError}
                                        </div>
                                    ) : null}
                                    {reviewBundleCopied ? (
                                        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                                            {reviewBundleCopied}
                                        </div>
                                    ) : null}

                                    {reviewBundle ? (
                                        <div className="mt-4 space-y-4">
                                            <div className="grid gap-3 md:grid-cols-2">
                                                <div className="rounded-xl bg-slate-50 p-3">
                                                    <div className="text-xs uppercase tracking-wide text-slate-500">Recommended targets</div>
                                                    <ul className="mt-2 space-y-2 text-sm text-slate-700">
                                                        {reviewBundle.recommended_targets.map((target) => (
                                                            <li key={`${reviewBundle.qa_log_id}-${target.dataset}`}>
                                                                <div className="font-medium text-slate-900">{target.dataset}</div>
                                                                <div className="text-slate-600">{target.reason}</div>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                                <div className="rounded-xl bg-slate-50 p-3">
                                                    <div className="text-xs uppercase tracking-wide text-slate-500">Promotion checklist</div>
                                                    <ol className="mt-2 space-y-2 text-sm text-slate-700">
                                                        {reviewBundle.promotion_checklist.map((item) => (
                                                            <li key={`${reviewBundle.qa_log_id}-${item}`}>{item}</li>
                                                        ))}
                                                    </ol>
                                                </div>
                                            </div>

                                            <div className="rounded-xl border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100">
                                                <div className="mb-2 flex items-center justify-between gap-2">
                                                    <span className="font-semibold uppercase tracking-wide text-slate-400">Coverage case template</span>
                                                    <span className="text-[11px] text-slate-500">Review required</span>
                                                </div>
                                                <pre className="overflow-x-auto whitespace-pre-wrap break-all leading-5">
                                                    {formatJson(reviewBundle.coverage_case_template)}
                                                </pre>
                                            </div>

                                            <div className="rounded-xl border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100">
                                                <div className="mb-2 flex items-center justify-between gap-2">
                                                    <span className="font-semibold uppercase tracking-wide text-slate-400">Response contract template</span>
                                                    <span className="text-[11px] text-slate-500">Needs replay before promotion</span>
                                                </div>
                                                <pre className="overflow-x-auto whitespace-pre-wrap break-all leading-5">
                                                    {formatJson(reviewBundle.response_contract_template)}
                                                </pre>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="mt-3 text-sm text-slate-500">
                                            Export the selected QA log when you want to turn it into a regression-review bundle.
                                        </div>
                                    )}
                                </div>

                                {selectedAnalysis?.signals && selectedAnalysis.signals.length > 0 ? (
                                    <div className="rounded-xl border border-slate-200 bg-white p-4">
                                        <div className="text-xs uppercase tracking-wide text-slate-500">Signals</div>
                                        <div className="mt-3 flex flex-wrap gap-2">
                                            {selectedAnalysis.signals.map((signal) => (
                                                <span key={signal} className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                                                    {signal}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                ) : null}

                                {selectedByCall.length > 0 ? (
                                    <div className="rounded-xl border border-slate-200 bg-white">
                                        <div className="border-b border-slate-100 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                                            Token breakdown
                                        </div>
                                        <div className="divide-y divide-slate-100">
                                            {selectedByCall.map((call, index) => (
                                                <div key={`${selectedLog.id}-${index}`} className="grid grid-cols-5 gap-2 px-4 py-3 text-xs text-slate-700">
                                                    <div className="font-medium text-slate-900">{call.kind}</div>
                                                    <div className="truncate text-slate-500">{call.model}</div>
                                                    <div className="text-right tabular-nums">{formatNumber(call.prompt_tokens)}</div>
                                                    <div className="text-right tabular-nums">{formatNumber(call.completion_tokens)}</div>
                                                    <div className="text-right tabular-nums font-semibold">{formatNumber(call.total_tokens)}</div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                ) : null}

                                {selectedSources.length > 0 ? (
                                    <div className="rounded-xl border border-slate-200 bg-white">
                                        <div className="border-b border-slate-100 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                                            Sources
                                        </div>
                                        <ul className="divide-y divide-slate-100">
                                            {selectedSources.map((source, index) => (
                                                <li key={`${selectedLog.id}-source-${index}`} className={`px-4 py-3 text-xs ${index === 0 ? 'bg-emerald-50/60' : ''}`}>
                                                    <div className="flex items-start justify-between gap-3">
                                                        <div className="min-w-0">
                                                            <div className="truncate font-medium text-slate-900">
                                                                {typeof source?.title === 'string' && source.title.trim() ? source.title : 'Untitled source'}
                                                            </div>
                                                            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                                                                {typeof source?.chunk_id === 'string' && source.chunk_id.trim() ? (
                                                                    <span>Chunk ID: {source.chunk_id}</span>
                                                                ) : typeof source?.source_id === 'string' && source.source_id.trim() ? (
                                                                    <span>Source ID: {source.source_id}</span>
                                                                ) : null}
                                                                {typeof source?.chunk_id === 'string' && source.chunk_id.trim() ? (
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => {
                                                                            const url = `/dashboard/knowledge/documents-control?chunkId=${encodeURIComponent(source.chunk_id)}`;
                                                                            window.open(url, '_blank', 'noopener,noreferrer');
                                                                        }}
                                                                        className="text-primary-600 underline hover:text-primary-700"
                                                                    >
                                                                        Open chunk
                                                                    </button>
                                                                ) : null}
                                                            </div>
                                                        </div>
                                                        {typeof source?.relevance === 'number' ? (
                                                            <span className="text-slate-400">rel {source.relevance.toFixed(3)}</span>
                                                        ) : null}
                                                    </div>
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                ) : null}
                            </div>
                        )}
                    </div>

                    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
                        <div className="border-b border-slate-200 px-5 py-4">
                            <h2 className="text-lg font-semibold text-slate-900">QA test sandbox</h2>
                            <p className="mt-1 text-sm text-slate-500">Send a live test message to the QA console path and inspect the returned answer.</p>
                        </div>
                        <div className="space-y-4 px-5 py-5">
                            <div className="flex gap-3">
                                <input
                                    type="text"
                                    value={testQuestion}
                                    onChange={(e) => setTestQuestion(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleTestQuestion()}
                                    placeholder="Enter a test question"
                                    className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 shadow-sm"
                                />
                                <button
                                    onClick={handleTestQuestion}
                                    disabled={testing || !testQuestion.trim()}
                                    className="rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {testing ? 'Testing...' : 'Test'}
                                </button>
                            </div>

                            {testResult ? (
                                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                                    <div className="text-xs uppercase tracking-wide text-slate-500">Answer</div>
                                    <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-900">{testResult.answer}</div>
                                    {testResult.sources.length > 0 ? (
                                        <div className="mt-4">
                                            <div className="flex items-center justify-between">
                                                <div className="text-xs uppercase tracking-wide text-slate-500">Sources</div>
                                                {testResult.sources.length > 1 ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => setShowAllSources((prev) => !prev)}
                                                        className="text-xs font-semibold text-primary-600 hover:text-primary-700"
                                                    >
                                                        {showAllSources ? 'Collapse' : 'See more'}
                                                    </button>
                                                ) : null}
                                            </div>
                                            <div className="mt-2 space-y-2">
                                                {(showAllSources ? testResult.sources : testResult.sources.slice(0, 1)).map((source, index) => (
                                                    <div key={index} className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
                                                        {JSON.stringify(source)}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ) : null}
                                </div>
                            ) : (
                                <div className="text-sm text-slate-500">Run a sandbox test to compare behavior against the current QA queue.</div>
                            )}
                        </div>
                    </div>
                </aside>
            </section>
        </div>
    );
};
