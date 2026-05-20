import { allowedPageSizes } from '../../../constants/pagination';

type ConversationPaginationProps = {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
    isLoading: boolean;
    onChange: (params: { currentPage: number; pageSize: number }) => void;
};

export const ConversationPagination = ({
    currentPage,
    pageSize,
    totalItems,
    totalPages,
    isLoading,
    onChange,
}: ConversationPaginationProps): JSX.Element => {
    const safeTotalPages = Math.max(1, totalPages || 1);
    const safeCurrentPage = Math.min(Math.max(1, currentPage || 1), safeTotalPages);
    const startItem = totalItems === 0 ? 0 : (safeCurrentPage - 1) * pageSize + 1;
    const endItem = totalItems === 0 ? 0 : Math.min(totalItems, safeCurrentPage * pageSize);

    return (
        <div className="border-t border-slate-200 bg-white px-4 py-3">
            <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                <span>
                    {startItem}-{endItem} of {totalItems.toLocaleString()}
                </span>
                <label className="flex items-center gap-2 text-slate-500">
                    <span className="font-medium">Rows</span>
                    <select
                        value={String(pageSize)}
                        onChange={(event) => onChange({ currentPage: 1, pageSize: Number(event.target.value) })}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none transition focus:border-slate-400"
                    >
                        {allowedPageSizes.map((size) => (
                            <option key={size} value={size}>
                                {size}
                            </option>
                        ))}
                    </select>
                </label>
            </div>

            <div className="mt-3 flex items-center gap-2">
                <button
                    type="button"
                    onClick={() => onChange({ currentPage: safeCurrentPage - 1, pageSize })}
                    disabled={isLoading || safeCurrentPage <= 1}
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                    Prev
                </button>

                <div className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-center">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">Page</div>
                    <div className="mt-0.5 text-sm font-semibold text-slate-900">
                        {safeCurrentPage} of {safeTotalPages}
                    </div>
                </div>

                <button
                    type="button"
                    onClick={() => onChange({ currentPage: safeCurrentPage + 1, pageSize })}
                    disabled={isLoading || safeCurrentPage >= safeTotalPages}
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                    Next
                </button>
            </div>
        </div>
    );
};
