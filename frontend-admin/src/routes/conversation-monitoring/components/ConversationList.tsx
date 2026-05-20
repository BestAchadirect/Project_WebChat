import { ConversationRecord, formatRelativeConversationTime } from '../conversationMonitoringShared';
import { ConversationPagination } from './ConversationPagination';
import { EmptyState } from './EmptyState';
import { IntentBadge } from './IntentBadge';

type ConversationListProps = {
    conversations: ConversationRecord[];
    selectedConversationId: string | null;
    onSelectConversation: (id: string) => void;
    currentPage: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
    isLoading: boolean;
    onPaginationChange: (params: { currentPage: number; pageSize: number }) => void;
};

export const ConversationList = ({
    conversations,
    selectedConversationId,
    onSelectConversation,
    currentPage,
    pageSize,
    totalItems,
    totalPages,
    isLoading,
    onPaginationChange,
}: ConversationListProps): JSX.Element => {
    if (conversations.length === 0) {
        return (
            <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                    <div>
                        <div className="text-sm font-semibold text-slate-900">Conversation queue</div>
                        <div className="text-xs text-slate-500">No matching conversations</div>
                    </div>
                </div>
                <div className="p-4">
                    <EmptyState title="No conversations found" description="Try another filter or search term." />
                </div>
                <ConversationPagination
                    currentPage={currentPage}
                    pageSize={pageSize}
                    totalItems={totalItems}
                    totalPages={totalPages}
                    isLoading={isLoading}
                    onChange={onPaginationChange}
                />
            </div>
        );
    }

    return (
        <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                <div>
                    <div className="text-sm font-semibold text-slate-900">Conversation queue</div>
                    <div className="text-xs text-slate-500">Select a conversation to inspect the full thread</div>
                </div>
                <div className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                    {totalItems.toLocaleString()}
                </div>
            </div>
            <div className="custom-scrollbar flex-1 overflow-y-auto">
                {conversations.map((conversation) => {
                    const isSelected = selectedConversationId === conversation.id;

                    return (
                        <button
                            key={conversation.id}
                            type="button"
                            onClick={() => onSelectConversation(conversation.id)}
                            className={`w-full border-b border-slate-100 p-4 text-left transition ${
                                isSelected ? 'bg-slate-50' : 'bg-white hover:bg-slate-50'
                            }`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                        <h3 className="truncate text-sm font-medium text-slate-900">{conversation.customerLabel}</h3>
                                    </div>
                                    <p className="mt-1 truncate text-sm text-slate-500">{conversation.customerQuestion}</p>
                                    <div className="mt-3 flex flex-wrap items-center gap-2">
                                        <IntentBadge intent={conversation.leadIntent} />
                                    </div>
                                </div>
                                <div className="shrink-0 text-right">
                                    <div className="text-xs text-slate-400">{formatRelativeConversationTime(conversation.time)}</div>
                                    <div className="mt-2 text-xs text-slate-500">{conversation.channel}</div>
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>
            <ConversationPagination
                currentPage={currentPage}
                pageSize={pageSize}
                totalItems={totalItems}
                totalPages={totalPages}
                isLoading={isLoading}
                onChange={onPaginationChange}
            />
        </div>
    );
};
