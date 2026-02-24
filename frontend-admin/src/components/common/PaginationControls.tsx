import React, { useEffect, useMemo, useState } from 'react';
import { allowedPageSizes as defaultAllowedSizes, maxCustomPageSize as defaultMaxCustomSize } from '../../constants/pagination';
import { PaginationChange } from '../../types/pagination';
import { clampPage, computeTotalPages, validatePageSize } from '../../utils/pagination';

interface PaginationControlsProps {
    currentPage: number;
    pageSize: number;
    totalItems: number;
    totalPages?: number;
    onChange: (next: PaginationChange) => void;
    allowedPageSizes?: number[];
    maxCustomPageSize?: number;
    isLoading?: boolean;
    className?: string;
}

export const PaginationControls: React.FC<PaginationControlsProps> = ({
    currentPage,
    pageSize,
    totalItems,
    totalPages,
    onChange,
    allowedPageSizes = defaultAllowedSizes,
    maxCustomPageSize = defaultMaxCustomSize,
    isLoading = false,
    className = '',
}) => {
    const resolvedTotalPages = useMemo(
        () => Math.max(1, totalPages ?? computeTotalPages(totalItems, pageSize)),
        [pageSize, totalItems, totalPages]
    );
    const resolvedCurrentPage = clampPage(currentPage, resolvedTotalPages);
    const isCustomSize = !allowedPageSizes.includes(pageSize);

    const [pageInput, setPageInput] = useState(String(resolvedCurrentPage));
    const [showCustomEditor, setShowCustomEditor] = useState(false);
    const [customInput, setCustomInput] = useState(String(pageSize));
    const [customError, setCustomError] = useState<string | null>(null);

    useEffect(() => {
        setPageInput(String(resolvedCurrentPage));
    }, [resolvedCurrentPage]);

    useEffect(() => {
        if (!showCustomEditor) {
            setCustomInput(String(pageSize));
            setCustomError(null);
        }
    }, [pageSize, showCustomEditor]);

    const commitPageChange = () => {
        const raw = pageInput.trim();
        if (!/^\d+$/.test(raw)) {
            setPageInput(String(resolvedCurrentPage));
            return;
        }
        const parsed = Number(raw);
        if (!Number.isInteger(parsed) || parsed < 1) {
            setPageInput(String(resolvedCurrentPage));
            return;
        }
        const target = clampPage(parsed, resolvedTotalPages);
        setPageInput(String(target));
        if (target !== resolvedCurrentPage) {
            onChange({ currentPage: target, pageSize });
        }
    };

    const applyCustomPageSize = () => {
        const validation = validatePageSize(customInput, maxCustomPageSize);
        if (!validation.valid) {
            setCustomError(validation.error);
            return;
        }
        setCustomError(null);
        setShowCustomEditor(false);
        onChange({ currentPage: 1, pageSize: validation.pageSize });
    };

    return (
        <div className={`flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-gray-200 bg-white ${className}`}>
            <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600">
                <span className="font-medium">Per page</span>
                <select
                    value={isCustomSize ? 'custom' : String(pageSize)}
                    onChange={(e) => {
                        if (e.target.value === 'custom') {
                            setShowCustomEditor(true);
                            setCustomInput(String(pageSize));
                            setCustomError(null);
                            return;
                        }
                        const nextSize = Number(e.target.value);
                        setShowCustomEditor(false);
                        if (!Number.isNaN(nextSize) && nextSize > 0 && nextSize !== pageSize) {
                            onChange({ currentPage: 1, pageSize: nextSize });
                        }
                    }}
                    className="rounded-md border border-gray-300 px-2 py-1 text-sm"
                >
                    {allowedPageSizes.map((size) => (
                        <option key={size} value={size}>
                            {size}
                        </option>
                    ))}
                    <option value="custom">Custom</option>
                </select>
                {showCustomEditor && (
                    <div className="flex flex-wrap items-center gap-2">
                        <input
                            type="text"
                            value={customInput}
                            onChange={(e) => {
                                setCustomInput(e.target.value);
                                if (customError) setCustomError(null);
                            }}
                            className="w-24 rounded-md border border-gray-300 px-2 py-1 text-sm"
                            placeholder="1-9999"
                        />
                        <button
                            type="button"
                            onClick={applyCustomPageSize}
                            className="rounded-md border border-gray-300 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-50"
                        >
                            Save
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setShowCustomEditor(false);
                                setCustomError(null);
                                setCustomInput(String(pageSize));
                            }}
                            className="rounded-md border border-transparent px-2 py-1 text-sm text-gray-500 hover:text-gray-700"
                        >
                            Cancel
                        </button>
                        {customError && <span className="text-xs text-red-600">{customError}</span>}
                    </div>
                )}
            </div>

            <div className="flex items-center gap-2 text-sm">
                <button
                    type="button"
                    onClick={() => onChange({ currentPage: resolvedCurrentPage - 1, pageSize })}
                    disabled={isLoading || resolvedCurrentPage <= 1}
                    className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    Previous
                </button>

                <input
                    type="text"
                    value={pageInput}
                    onChange={(e) => setPageInput(e.target.value)}
                    onBlur={commitPageChange}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            commitPageChange();
                        }
                    }}
                    className="w-14 rounded-md border border-gray-300 px-2 py-1 text-center"
                    inputMode="numeric"
                    aria-label="Current page"
                />
                <span className="text-gray-600">of {resolvedTotalPages}</span>

                <button
                    type="button"
                    onClick={() => onChange({ currentPage: resolvedCurrentPage + 1, pageSize })}
                    disabled={isLoading || resolvedCurrentPage >= resolvedTotalPages}
                    className="rounded-md border border-gray-300 px-3 py-1 font-medium text-gray-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    Next
                </button>

                <span className="ml-2 text-xs text-gray-500">{totalItems.toLocaleString()} items</span>
            </div>
        </div>
    );
};
