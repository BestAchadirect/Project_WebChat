import { ChatMetricsSummary, QALog } from '../../api/training';

export type ConversationLeadIntent =
    | 'product_inquiry'
    | 'support_request'
    | 'store_information'
    | 'general_conversation'
    | 'needs_attention';
export type ConversationIntentFilter = 'all' | ConversationLeadIntent;
export type ConversationDateFilter = 'today' | 'last_7_days' | 'last_30_days' | 'all_time';
export type ConversationChannelFilter = 'all' | 'widget' | 'qa_console' | 'unlabeled';

export type ConversationRecord = {
    id: string;
    customerLabel: string;
    time: string;
    customerQuestion: string;
    botAnswer: string;
    workflow: string;
    sessionId: string;
    channel: string;
    leadIntent: ConversationLeadIntent;
    transcript: Array<{ role: 'customer' | 'assistant'; text: string }>;
};

export const DATE_FILTERS: Array<{ label: string; value: ConversationDateFilter }> = [
    { label: 'Today', value: 'today' },
    { label: 'Last 7 days', value: 'last_7_days' },
    { label: 'Last 30 days', value: 'last_30_days' },
    { label: 'All time', value: 'all_time' },
];

export const CHANNEL_FILTERS: Array<{ label: string; value: ConversationChannelFilter }> = [
    { label: 'All channels', value: 'all' },
    { label: 'Website', value: 'widget' },
    { label: 'QA Console', value: 'qa_console' },
    { label: 'Unlabeled', value: 'unlabeled' },
];

export const INTENT_FILTERS: Array<{ label: string; value: ConversationIntentFilter }> = [
    { label: 'All intents', value: 'all' },
    { label: 'Product inquiry', value: 'product_inquiry' },
    { label: 'Support request', value: 'support_request' },
    { label: 'Store information', value: 'store_information' },
    { label: 'General conversation', value: 'general_conversation' },
    { label: 'Needs attention', value: 'needs_attention' },
];

const getMetrics = (log: QALog): ChatMetricsSummary => {
    return log.token_usage?.chat_metrics ?? {};
};

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

const getChannelLabel = (channel?: string | null): string => {
    if (channel === 'widget') return 'Website Chat';
    if (channel === 'qa_console') return 'QA Console';
    return 'Unlabeled';
};

const buildCustomerLabel = (log: QALog): string => {
    const metrics = getMetrics(log);
    if (metrics.conversation_id !== null && metrics.conversation_id !== undefined) {
        return `Conversation ${metrics.conversation_id}`;
    }
    if (log.channel === 'widget') {
        return `Website visitor ${log.id.slice(-4)}`;
    }
    if (log.channel === 'qa_console') {
        return `QA console ${log.id.slice(-4)}`;
    }
    return `Guest ${log.id.slice(-4)}`;
};

const deriveLeadIntent = (log: QALog): ConversationLeadIntent => {
    const metrics = getMetrics(log);
    const workflow = String(metrics.workflow || metrics.response_workflow || '').trim().toLowerCase();
    const question = String(log.question || '').toLowerCase();

    if (workflow === 'catalog') {
        return 'product_inquiry';
    }
    if (workflow === 'store_overview') {
        return 'store_information';
    }
    if (workflow === 'knowledge') {
        return 'support_request';
    }
    if (workflow === 'fallback' || log.status === 'failed') {
        return 'needs_attention';
    }
    if (question.includes('price') || question.includes('recommend') || question.includes('looking for')) {
        return 'product_inquiry';
    }
    return 'general_conversation';
};

export const mapQALogToConversation = (log: QALog): ConversationRecord => {
    const metrics = getMetrics(log);
    const workflowValue = String(metrics.workflow || metrics.response_workflow || '').trim();
    const leadIntent = deriveLeadIntent(log);
    const sessionId = metrics.conversation_id ? String(metrics.conversation_id) : log.id;

    return {
        id: log.id,
        customerLabel: buildCustomerLabel(log),
        time: log.created_at,
        customerQuestion: log.question,
        botAnswer: log.answer || 'No answer recorded.',
        workflow: workflowValue ? workflowLabel(workflowValue) : 'Unknown',
        sessionId,
        channel: getChannelLabel(log.channel),
        leadIntent,
        transcript: [
            { role: 'customer', text: log.question || 'No customer message recorded.' },
            { role: 'assistant', text: log.answer || 'No assistant answer recorded.' },
        ],
    };
};

export const formatRelativeConversationTime = (value: string): string => {
    const target = new Date(value).getTime();
    if (Number.isNaN(target)) {
        return '';
    }

    const minutes = Math.max(1, Math.round((Date.now() - target) / 60_000));
    if (minutes < 60) {
        return `${minutes}m ago`;
    }

    const hours = Math.round(minutes / 60);
    if (hours < 24) {
        return `${hours}h ago`;
    }

    const days = Math.round(hours / 24);
    return `${days}d ago`;
};

export const formatConversationDateTime = (value: string): string => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }
    return new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    }).format(date);
};

export const getLeadIntentLabel = (leadIntent: ConversationLeadIntent): string => {
    switch (leadIntent) {
        case 'product_inquiry':
            return 'Product inquiry';
        case 'support_request':
            return 'Support request';
        case 'store_information':
            return 'Store information';
        case 'needs_attention':
            return 'Needs attention';
        default:
            return 'General conversation';
    }
};

export const getIntentFilterRange = (
    filter: ConversationIntentFilter,
): { workflow?: string } => {
    switch (filter) {
        case 'product_inquiry':
            return { workflow: 'catalog' };
        case 'support_request':
            return { workflow: 'knowledge' };
        case 'store_information':
            return { workflow: 'store_overview' };
        case 'needs_attention':
            return { workflow: 'fallback' };
        case 'general_conversation':
            return { workflow: 'general_talking' };
        default:
            return {};
    }
};

export const getDateFilterRange = (
    filter: ConversationDateFilter,
): { createdFrom?: string; createdTo?: string } => {
    if (filter === 'all_time') {
        return {};
    }

    const now = new Date();
    if (filter === 'today') {
        const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        return { createdFrom: startOfDay.toISOString() };
    }

    const rangeDays = filter === 'last_7_days' ? 7 : 30;
    const threshold = new Date(now.getTime() - rangeDays * 86_400_000);
    return { createdFrom: threshold.toISOString() };
};
