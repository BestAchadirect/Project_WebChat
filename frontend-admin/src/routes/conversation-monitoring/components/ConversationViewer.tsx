import { ConversationRecord, formatConversationDateTime } from '../conversationMonitoringShared';
import { IntentBadge } from './IntentBadge';

type ConversationViewerProps = {
    conversation: ConversationRecord | null;
    messages: Array<{ role: 'customer' | 'assistant'; text: string }>;
    isConversationLoading: boolean;
};

export const ConversationViewer = ({
    conversation,
    messages,
    isConversationLoading,
}: ConversationViewerProps): JSX.Element => {
    if (!conversation) {
        return (
            <main className="flex min-h-0 flex-1 items-center justify-center bg-white">
                <div className="text-center">
                    <h2 className="text-lg font-semibold text-slate-900">No conversation selected</h2>
                    <p className="mt-2 text-sm text-slate-500">Choose a conversation from the monitoring queue.</p>
                </div>
            </main>
        );
    }

    return (
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-slate-50">
            <header className="border-b border-slate-200 bg-white px-6 py-5">
                <div className="flex items-start justify-between gap-4">
                    <div>
                        <h2 className="text-xl font-semibold text-slate-900">{conversation.customerLabel}</h2>
                        <p className="mt-1 text-sm text-slate-500">
                            {conversation.channel} | {formatConversationDateTime(conversation.time)}
                        </p>
                        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-600">
                            <span><span className="font-medium text-slate-900">Session:</span> {conversation.sessionId}</span>
                            <span><span className="font-medium text-slate-900">Workflow:</span> {conversation.workflow}</span>
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <IntentBadge intent={conversation.leadIntent} />
                    </div>
                </div>
            </header>

            <section className="custom-scrollbar flex-1 overflow-y-auto p-6">
                <div className="mx-auto max-w-5xl">
                    <section className="bg-transparent">
                        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Active conversation</div>
                        <div className="mt-5 space-y-4">
                            {isConversationLoading ? (
                                <div className="space-y-4">
                                    <div className="h-20 w-80 animate-pulse rounded-2xl bg-slate-100" />
                                    <div className="ml-auto h-20 w-80 animate-pulse rounded-2xl bg-slate-200" />
                                </div>
                            ) : messages.length > 0 ? (
                                messages.map((message, index) => {
                                    const isCustomer = message.role === 'customer';

                                    return (
                                        <div key={`${conversation.id}-${index}`} className={`flex ${isCustomer ? '' : 'justify-end'}`}>
                                            <div
                                                className={`max-w-2xl rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm ${
                                                    isCustomer
                                                        ? 'bg-slate-100 text-slate-800'
                                                        : 'bg-slate-900 text-white'
                                                }`}
                                            >
                                                <div
                                                    className={`mb-2 text-[11px] font-semibold uppercase tracking-wide ${
                                                        isCustomer ? 'text-slate-400' : 'text-slate-300'
                                                    }`}
                                                >
                                                    {isCustomer ? 'Customer' : 'Bot'}
                                                </div>
                                                {message.text}
                                            </div>
                                        </div>
                                    );
                                })
                            ) : (
                                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
                                    No conversation messages were available for this session.
                                </div>
                            )}
                        </div>
                    </section>
                </div>
            </section>
        </main>
    );
};
