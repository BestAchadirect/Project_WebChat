export const computeTotalPages = (totalItems: number, pageSize: number): number => {
    const safeTotal = Number.isFinite(totalItems) ? Math.max(0, Math.floor(totalItems)) : 0;
    const safePageSize = Number.isFinite(pageSize) ? Math.max(1, Math.floor(pageSize)) : 1;
    return Math.max(1, Math.ceil(safeTotal / safePageSize));
};

export const clampPage = (page: number, totalPages: number): number => {
    const safeTotalPages = Number.isFinite(totalPages) ? Math.max(1, Math.floor(totalPages)) : 1;
    const safePage = Number.isFinite(page) ? Math.floor(page) : 1;
    return Math.min(Math.max(safePage, 1), safeTotalPages);
};

export const validatePageSize = (
    value: string | number,
    maxAllowed: number = 9999
): { valid: true; pageSize: number } | { valid: false; error: string } => {
    const raw = String(value).trim();
    if (!/^\d+$/.test(raw)) {
        return { valid: false, error: 'Page size must be an integer.' };
    }

    const pageSize = Number(raw);
    if (!Number.isInteger(pageSize)) {
        return { valid: false, error: 'Page size must be an integer.' };
    }
    if (pageSize < 1) {
        return { valid: false, error: 'Page size must be at least 1.' };
    }
    if (pageSize > maxAllowed) {
        return { valid: false, error: `Page size cannot exceed ${maxAllowed}.` };
    }

    return { valid: true, pageSize };
};
