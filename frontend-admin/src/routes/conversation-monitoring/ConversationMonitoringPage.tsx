import { useDeferredValue, useEffect, useMemo, useState } from 'react';

import { analyticsApi } from '../../api/analytics';
import { trainingApi, QALog } from '../../api/training';
import { defaultPageSize } from '../../constants/pagination';
import { ConversationFilters } from './components/ConversationFilters';
import { ConversationList } from './components/ConversationList';
import { ConversationViewer } from './components/ConversationViewer';
import { LoadingState } from './components/LoadingState';
import {
    ConversationChannelFilter,
    ConversationDateFilter,
    ConversationIntentFilter,
    ConversationRecord,
    getDateFilterRange,
    getIntentFilterRange,
    mapQALogToConversation,
} from './conversationMonitoringShared';

const LOADING_DELAY_MS = 650;

export const ConversationMonitoringPage = (): JSX.Element => {
    const [logs, setLogs] = useState<QALog[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(defaultPageSize);
    const [totalItems, setTotalItems] = useState(0);
    const [totalPages, setTotalPages] = useState(1);
    const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
    const [selectedConversation, setSelectedConversation] = useState<ConversationRecord | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [dateFilter, setDateFilter] = useState<ConversationDateFilter>('last_7_days');
    const [channelFilter, setChannelFilter] = useState<ConversationChannelFilter>('all');
    const [intentFilter, setIntentFilter] = useState<ConversationIntentFilter>('all');
    const [isLoading, setIsLoading] = useState(true);
    const [conversationMessages, setConversationMessages] = useState<Record<string, Array<{ role: 'customer' | 'assistant'; text: string }>>>({});
    const [isConversationLoading, setIsConversationLoading] = useState(false);
    const deferredSearchQuery = useDeferredValue(searchQuery);
    const dateRange = useMemo(() => getDateFilterRange(dateFilter), [dateFilter]);
    const intentRange = useMemo(() => getIntentFilterRange(intentFilter), [intentFilter]);

    useEffect(() => {
        let isActive = true;
        const timer = window.setTimeout(async () => {
            try {
                setIsLoading(true);
                const result = await trainingApi.listQALogs({
                    page: currentPage,
                    pageSize,
                    channel: channelFilter !== 'all' ? channelFilter : undefined,
                    workflow: intentRange.workflow,
                    createdFrom: dateRange.createdFrom,
                    createdTo: dateRange.createdTo,
                    search: deferredSearchQuery.trim() || undefined,
                });
                if (!isActive) {
                    return;
                }
                setLogs(result.items);
                setCurrentPage(result.page);
                setPageSize(result.pageSize);
                setTotalItems(result.totalItems);
                setTotalPages(result.totalPages);
            } catch (error) {
                console.error('Failed to load QA logs:', error);
                if (isActive) {
                    setLogs([]);
                    setTotalItems(0);
                    setTotalPages(1);
                }
            } finally {
                if (isActive) {
                    setIsLoading(false);
                }
            }
        }, LOADING_DELAY_MS);

        return () => {
            isActive = false;
            window.clearTimeout(timer);
        };
    }, [channelFilter, currentPage, dateRange.createdFrom, dateRange.createdTo, deferredSearchQuery, intentRange.workflow, pageSize]);

    useEffect(() => {
        setCurrentPage(1);
    }, [channelFilter, dateFilter, deferredSearchQuery, intentFilter]);

    const visibleConversations = useMemo<ConversationRecord[]>(() => {
        return logs.map((log) => mapQALogToConversation(log));
    }, [logs]);

    useEffect(() => {
        if (visibleConversations.length === 0) {
            setSelectedConversationId(null);
            setSelectedConversation(null);
            return;
        }
        if (!selectedConversationId) {
            const firstConversation = visibleConversations[0];
            setSelectedConversationId(firstConversation.id);
            setSelectedConversation(firstConversation);
            return;
        }
        const currentPageSelection = visibleConversations.find((conversation) => conversation.id === selectedConversationId);
        if (currentPageSelection) {
            setSelectedConversation(currentPageSelection);
        }
    }, [selectedConversationId, visibleConversations]);

    useEffect(() => {
        let isActive = true;

        const loadConversationDetails = async () => {
            if (!selectedConversation) {
                setIsConversationLoading(false);
                return;
            }

            const sessionId = String(selectedConversation.sessionId || '').trim();
            if (!/^\d+$/.test(sessionId)) {
                setConversationMessages((current) => ({
                    ...current,
                    [selectedConversation.id]: selectedConversation.transcript,
                }));
                setIsConversationLoading(false);
                return;
            }

            if (conversationMessages[selectedConversation.id]) {
                setIsConversationLoading(false);
                return;
            }

            try {
                setIsConversationLoading(true);
                const detail = await analyticsApi.getChatLogDetails(sessionId);
                if (!isActive) {
                    return;
                }
                const messages: Array<{ role: 'customer' | 'assistant'; text: string }> = (detail.messages || [])
                    .filter((message) => message.role === 'user' || message.role === 'assistant')
                    .map((message) => ({
                        role: message.role === 'user' ? 'customer' : 'assistant',
                        text: String(message.content || '').trim() || 'No message recorded.',
                    }));
                setConversationMessages((current) => ({
                    ...current,
                    [selectedConversation.id]: messages.length > 0 ? messages : selectedConversation.transcript,
                }));
            } catch (error) {
                console.error('Failed to load conversation history:', error);
                if (isActive) {
                    setConversationMessages((current) => ({
                        ...current,
                        [selectedConversation.id]: selectedConversation.transcript,
                    }));
                }
            } finally {
                if (isActive) {
                    setIsConversationLoading(false);
                }
            }
        };

        void loadConversationDetails();

        return () => {
            isActive = false;
        };
    }, [conversationMessages, selectedConversation]);

    const handleResetFilters = () => {
        setSearchQuery('');
        setDateFilter('last_7_days');
        setChannelFilter('all');
        setIntentFilter('all');
    };

    const handleSelectConversation = (conversationId: string) => {
        const nextConversation = visibleConversations.find((conversation) => conversation.id === conversationId);
        setSelectedConversationId(conversationId);
        if (nextConversation) {
            setSelectedConversation(nextConversation);
        }
    };

    return (
        <main className="h-[calc(100vh-8rem)] overflow-x-auto rounded-3xl bg-gray-100">
            {isLoading ? (
                <LoadingState />
            ) : (
                <div className="flex h-full min-w-[980px] overflow-hidden rounded-3xl border border-slate-200 bg-gray-100 xl:min-w-0">
                    <aside className="flex min-h-0 w-[24rem] shrink-0 flex-col overflow-hidden border-r border-slate-200 bg-white 2xl:w-[26rem]">
                        <ConversationFilters
                            searchQuery={searchQuery}
                            dateFilter={dateFilter}
                            channelFilter={channelFilter}
                            intentFilter={intentFilter}
                            onSearchChange={setSearchQuery}
                            onDateFilterChange={setDateFilter}
                            onChannelFilterChange={setChannelFilter}
                            onIntentFilterChange={setIntentFilter}
                            onResetFilters={handleResetFilters}
                        />

                        <ConversationList
                            conversations={visibleConversations}
                            selectedConversationId={selectedConversationId}
                            onSelectConversation={handleSelectConversation}
                            currentPage={currentPage}
                            pageSize={pageSize}
                            totalItems={totalItems}
                            totalPages={totalPages}
                            isLoading={isLoading}
                            onPaginationChange={({ currentPage: nextPage, pageSize: nextPageSize }) => {
                                if (nextPage === currentPage && nextPageSize === pageSize) {
                                    return;
                                }
                                setCurrentPage(nextPage);
                                setPageSize(nextPageSize);
                            }}
                        />
                    </aside>
                    <ConversationViewer
                        conversation={selectedConversation}
                        messages={selectedConversation ? (conversationMessages[selectedConversation.id] || selectedConversation.transcript) : []}
                        isConversationLoading={isConversationLoading}
                    />
                </div>
            )}
        </main>
    );
};
