# PaginationControls Integration Guide

## What it is
`PaginationControls` is a reusable React pagination bar for admin tables/grids with:
- Page-size selector (`20, 30, 50, 100, 200, 500, 999, Custom`)
- Custom page-size editor with validation
- Previous / Next buttons
- Current page input + `of X` label

## Backend API contract
List endpoints use:
- Query params: `page` (1-based), `pageSize`
- Response envelope:

```json
{
  "items": [],
  "totalItems": 0,
  "page": 1,
  "pageSize": 20,
  "totalPages": 1
}
```

Rules:
- `totalPages = max(1, ceil(totalItems / pageSize))`
- `page` is clamped to `[1, totalPages]`
- If `totalItems = 0`, response still uses `page = 1`, `totalPages = 1`
- Legacy `limit/offset` is rejected with `400`

## Component props
Path: `frontend-admin/src/components/common/PaginationControls.tsx`

```ts
interface PaginationControlsProps {
  currentPage: number;
  pageSize: number;
  totalItems: number;
  totalPages?: number;
  onChange: (next: { currentPage: number; pageSize: number }) => void;
  allowedPageSizes?: number[];
  maxCustomPageSize?: number;
  isLoading?: boolean;
  className?: string;
}
```

## Helper utilities
Path: `frontend-admin/src/utils/pagination.ts`
- `computeTotalPages(totalItems, pageSize)`
- `clampPage(page, totalPages)`
- `validatePageSize(value, maxAllowed)`

## Constants
Path: `frontend-admin/src/constants/pagination.ts`
- `allowedPageSizes`
- `maxCustomPageSize`
- `defaultPageSize`

## Minimal usage example

```tsx
const [rows, setRows] = useState<Item[]>([]);
const [currentPage, setCurrentPage] = useState(1);
const [pageSize, setPageSize] = useState(defaultPageSize);
const [totalItems, setTotalItems] = useState(0);
const [totalPages, setTotalPages] = useState(1);

const load = async (page = currentPage, size = pageSize) => {
  const res = await api.list({ page, pageSize: size });
  setRows(res.items);
  setCurrentPage(res.page);
  setPageSize(res.pageSize);
  setTotalItems(res.totalItems);
  setTotalPages(res.totalPages);
};

<PaginationControls
  currentPage={currentPage}
  pageSize={pageSize}
  totalItems={totalItems}
  totalPages={totalPages}
  onChange={({ currentPage, pageSize }) => {
    setCurrentPage(currentPage);
    setPageSize(pageSize);
    void load(currentPage, pageSize);
  }}
/>;
```

## Current rollout coverage
- Product Tuning
- Documents (Product Upload History + Knowledge Upload History)
- Tickets
- QA Monitoring logs
- Analytics recent conversations
