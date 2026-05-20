import {
    CHANNEL_FILTERS,
    ConversationChannelFilter,
    ConversationDateFilter,
    ConversationIntentFilter,
    DATE_FILTERS,
    INTENT_FILTERS,
} from '../conversationMonitoringShared';

type ConversationFiltersProps = {
    searchQuery: string;
    dateFilter: ConversationDateFilter;
    channelFilter: ConversationChannelFilter;
    intentFilter: ConversationIntentFilter;
    onSearchChange: (value: string) => void;
    onDateFilterChange: (value: ConversationDateFilter) => void;
    onChannelFilterChange: (value: ConversationChannelFilter) => void;
    onIntentFilterChange: (value: ConversationIntentFilter) => void;
    onResetFilters: () => void;
};

export const ConversationFilters = ({
    searchQuery,
    dateFilter,
    channelFilter,
    intentFilter,
    onSearchChange,
    onDateFilterChange,
    onChannelFilterChange,
    onIntentFilterChange,
    onResetFilters,
}: ConversationFiltersProps): JSX.Element => {
    const hasActiveFilters = Boolean(
        searchQuery.trim() || dateFilter !== 'last_7_days' || channelFilter !== 'all' || intentFilter !== 'all',
    );

    return (
        <div className="border-b border-slate-200 p-4">
            <div className="space-y-4">
                <div className="flex items-center gap-3">
                    <input
                        value={searchQuery}
                        onChange={(event) => onSearchChange(event.target.value)}
                        className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3.5 py-2.5 text-sm text-slate-800 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                        placeholder="Search conversations, messages, or session ids..."
                    />
                    {hasActiveFilters ? (
                        <button
                            type="button"
                            onClick={onResetFilters}
                            className="shrink-0 rounded-xl border border-slate-200 px-3 py-2.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 hover:text-slate-900"
                        >
                            Reset
                        </button>
                    ) : null}
                </div>

                <div className="grid grid-cols-3 gap-2">
                    <label className="space-y-1.5">
                        <span className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Date</span>
                        <select
                            value={dateFilter}
                            onChange={(event) => onDateFilterChange(event.target.value as ConversationDateFilter)}
                            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                        >
                            {DATE_FILTERS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="space-y-1.5">
                        <span className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Intent</span>
                        <select
                            value={intentFilter}
                            onChange={(event) => onIntentFilterChange(event.target.value as ConversationIntentFilter)}
                            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                        >
                            {INTENT_FILTERS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="space-y-1.5">
                        <span className="block text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Channel</span>
                        <select
                            value={channelFilter}
                            onChange={(event) => onChannelFilterChange(event.target.value as ConversationChannelFilter)}
                            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-xs text-slate-700 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
                        >
                            {CHANNEL_FILTERS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
                </div>
            </div>
        </div>
    );
};
