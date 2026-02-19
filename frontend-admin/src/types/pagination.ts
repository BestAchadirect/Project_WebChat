export interface PaginatedResponse<T> {
    items: T[];
    totalItems: number;
    page: number;
    pageSize: number;
    totalPages: number;
}

export interface PaginationChange {
    currentPage: number;
    pageSize: number;
}
