import { ConversationLeadIntent, getLeadIntentLabel } from '../conversationMonitoringShared';

type IntentBadgeProps = {
    intent: ConversationLeadIntent;
};

const intentClasses: Record<ConversationLeadIntent, string> = {
    product_inquiry: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    support_request: 'border-amber-200 bg-amber-50 text-amber-700',
    store_information: 'border-sky-200 bg-sky-50 text-sky-700',
    general_conversation: 'border-slate-200 bg-slate-50 text-slate-700',
    needs_attention: 'border-rose-200 bg-rose-50 text-rose-700',
};

export const IntentBadge = ({ intent }: IntentBadgeProps): JSX.Element => {
    return (
        <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${intentClasses[intent]}`}>
            {getLeadIntentLabel(intent)}
        </span>
    );
};
