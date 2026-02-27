import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { productsApi, Product, ProductFilterValue } from '../../api/training';
import { PaginationControls } from '../../components/common/PaginationControls';
import { defaultPageSize } from '../../constants/pagination';

type BulkFieldState = Record<string, { enabled: boolean; value: string }>;

export const ProductTuningPage: React.FC = () => {
    const [products, setProducts] = useState<Product[]>([]);
    const [loading, setLoading] = useState(true);
    const [totalItems, setTotalItems] = useState(0);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(defaultPageSize);
    const [totalPages, setTotalPages] = useState(1);

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
    const [bulkEditOpen, setBulkEditOpen] = useState(false);
    const [bulkEditFields, setBulkEditFields] = useState<BulkFieldState>({});
    const [bulkEditSaving, setBulkEditSaving] = useState(false);
    const [bulkEditError, setBulkEditError] = useState<string | null>(null);
    const selectAllRef = useRef<HTMLInputElement | null>(null);
    const productLoadSeqRef = useRef(0);
    const [showColumnMenu, setShowColumnMenu] = useState(false);
    const [showSelectActionMenu, setShowSelectActionMenu] = useState(false);
    const selectActionMenuRef = useRef<HTMLDivElement | null>(null);
    const selectActionButtonRef = useRef<HTMLButtonElement | null>(null);
    // Column Definitions
    const technicalFields: Array<{ key: keyof Product; label: string; type?: 'text' | 'number' }> = [
        { key: 'material', label: 'Material' },
        { key: 'jewelry_type', label: 'Jewelry Type' },
        { key: 'length', label: 'Length' },
        { key: 'size', label: 'Size' },
        { key: 'gauge', label: 'Gauge' },
        { key: 'design', label: 'Design' },
        { key: 'cz_color', label: 'CZ Color' },
        { key: 'opal_color', label: 'Opal Color' },
        { key: 'threading', label: 'Threading' },
        { key: 'outer_diameter', label: 'Diameter' },
        { key: 'crystal_color', label: 'Crystal Color' },
        { key: 'color', label: 'Color' },
        { key: 'pearl_color', label: 'Pearl Color' },
        { key: 'size_in_pack', label: 'Size In Pack', type: 'text' },
        { key: 'quantity_in_bulk', label: 'Quantity In Bulk', type: 'text' },
        { key: 'rack', label: 'Rack' },
        { key: 'height', label: 'Height' },
        { key: 'packing_option', label: 'Packing Option' },
        { key: 'pincher_size', label: 'Pincher Size' },
        { key: 'ring_size', label: 'Ring Size' },
    ];

    const standardColumns = [
        { key: 'image', label: 'Image', width: 'w-20' },
        { key: 'master_code', label: 'Master Code', width: 'w-40' },
        { key: 'description', label: 'Description', width: 'flex-1' },
        { key: 'sku', label: 'SKU', width: 'w-32' },
        { key: 'price', label: 'Price', width: 'w-24' },
        { key: 'status', label: 'Status', width: 'w-20' },
    ];

    const attributeColumns = technicalFields.map(field => ({
        key: field.key as string,
        label: field.label,
        width: 'w-32',
        isAttribute: true
    }));

    const allColumns = [...standardColumns, ...attributeColumns];

    const [visibleColumns, setVisibleColumns] = useState<Record<string, boolean>>(() => {
        const initial: Record<string, boolean> = {
            image: true,
            master_code: true,
            description: true,
            sku: true,
            price: true,
            status: true,
        };
        // Initialize all technical fields to false by default
        technicalFields.forEach(f => {
            initial[f.key as string] = false;
        });
        return initial;
    });

    // Filters
    const [filterVisibility, setFilterVisibility] = useState<'all' | 'visible' | 'hidden'>('all');
    const [filterFeatured, setFilterFeatured] = useState<'all' | 'featured' | 'normal'>('all');

    // Dynamic Filters
    const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
    const [pendingFilters, setPendingFilters] = useState<Record<string, string[]>>({});

    // UI State for Filters


    const [minPrice, setMinPrice] = useState('');
    const [maxPrice, setMaxPrice] = useState('');
    const [facetData, setFacetData] = useState<Record<string, ProductFilterValue[]>>({});
    const [facetLoading, setFacetLoading] = useState(false);

    useEffect(() => {
        const firstPage = 1;
        setCurrentPage(firstPage);
        void loadProducts(firstPage, pageSize);
        loadFacets();
    }, [filterVisibility, filterFeatured, activeFilters]);

    useEffect(() => {
        setPendingFilters(activeFilters);
    }, [activeFilters]);

    useEffect(() => {
        if (!showSelectActionMenu) return;
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            if (selectActionMenuRef.current?.contains(target)) return;
            if (selectActionButtonRef.current?.contains(target)) return;
            setShowSelectActionMenu(false);
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [showSelectActionMenu]);

    const loadProducts = async (targetPage: number, targetPageSize: number = pageSize) => {
        const requestSeq = ++productLoadSeqRef.current;
        try {
            setLoading(true);
            const params: any = {
                page: targetPage,
                pageSize: targetPageSize,
            };
            if (filterVisibility === 'visible') params.visibility = true;
            if (filterVisibility === 'hidden') params.visibility = false;
            if (filterFeatured === 'featured') params.is_featured = true;
            if (filterFeatured === 'normal') params.is_featured = false;

            // Add dynamic filters to params
            Object.entries(activeFilters).forEach(([key, values]) => {
                if (values && values.length > 0) {
                    params[key] = values;
                }
            });

            if (minPrice) params.min_price = parseFloat(minPrice);
            if (maxPrice) params.max_price = parseFloat(maxPrice);
            if (searchQuery) params.search = searchQuery;

            const result = await productsApi.listProducts(params);
            if (requestSeq !== productLoadSeqRef.current) return;
            setProducts(result.items);
            setTotalItems(result.totalItems);
            setCurrentPage(result.page);
            setPageSize(result.pageSize);
            setTotalPages(result.totalPages);
            setSelectedIds((prev) => new Set([...prev].filter((id) => result.items.some((p) => p.id === id))));
        } catch (error) {
            console.error('Failed to load products:', error);
        } finally {
            if (requestSeq === productLoadSeqRef.current) {
                setLoading(false);
            }
        }
    };

    const handlePaginationChange = ({ currentPage: nextPage, pageSize: nextPageSize }: { currentPage: number; pageSize: number }) => {
        if (nextPage === currentPage && nextPageSize === pageSize) return;
        setCurrentPage(nextPage);
        setPageSize(nextPageSize);
        void loadProducts(nextPage, nextPageSize);
    };

    const handleSearch = () => {
        const firstPage = 1;
        setCurrentPage(firstPage);
        void loadProducts(firstPage, pageSize);
        loadFacets();
    };

    const loadFacets = async () => {
        try {
            setFacetLoading(true);
            const params: any = {};
            if (filterVisibility === 'visible') params.visibility = true;
            if (filterVisibility === 'hidden') params.visibility = false;
            if (filterFeatured === 'featured') params.is_featured = true;
            if (filterFeatured === 'normal') params.is_featured = false;

            // Add dynamic filters to params
            Object.entries(activeFilters).forEach(([key, values]) => {
                if (values && values.length > 0) {
                    params[key] = values;
                }
            });

            if (minPrice) params.min_price = parseFloat(minPrice);
            if (maxPrice) params.max_price = parseFloat(maxPrice);
            if (searchQuery) params.search = searchQuery;
            const result = await productsApi.listProductFilters(params);
            setFacetData(result.filters || {});
        } catch (error) {
            console.error('Failed to load filter facets:', error);
        } finally {
            setFacetLoading(false);
        }
    };

    const handleToggleVisibility = async (product: Product) => {
        try {
            await productsApi.updateProduct(product.id, { visibility: !product.visibility });
            setProducts(prods => prods.map(p => p.id === product.id ? { ...p, visibility: !p.visibility } : p));
            if (selectedProduct?.id === product.id) {
                setSelectedProduct({ ...selectedProduct, visibility: !selectedProduct.visibility });
            }
        } catch (error) {
            console.error('Failed to toggle visibility:', error);
        }
    };

    const handleToggleFeatured = async (product: Product) => {
        try {
            await productsApi.updateProduct(product.id, { is_featured: !product.is_featured });
            setProducts(prods => prods.map(p => p.id === product.id ? { ...p, is_featured: !p.is_featured } : p));
            if (selectedProduct?.id === product.id) {
                setSelectedProduct({ ...selectedProduct, is_featured: !selectedProduct.is_featured });
            }
        } catch (error) {
            console.error('Failed to toggle featured:', error);
        }
    };

    const handleHardDeleteBySku = async (product: Product) => {
        const sku = (product.sku || '').trim();
        if (!sku) return;

        const confirmed = window.confirm(
            `Delete SKU "${sku}" permanently?\n\nThis will remove the product and related embeddings/attributes.`
        );
        if (!confirmed) return;

        try {
            await productsApi.hardDeleteBySku(sku);
            const removedIds = products.filter((p) => p.sku === sku).map((p) => p.id);
            const removedOnPage = removedIds.length;
            const targetPage =
                removedOnPage >= products.length && currentPage > 1
                    ? currentPage - 1
                    : currentPage;

            setSelectedIds((prev) => {
                const next = new Set(prev);
                removedIds.forEach((id) => next.delete(id));
                return next;
            });
            setSelectedProduct((prev) => (prev?.sku === sku ? null : prev));
            setCurrentPage(targetPage);
            await loadProducts(targetPage, pageSize);
            loadFacets();
        } catch (error) {
            console.error('Failed to hard delete SKU:', error);
            window.alert('Failed to delete SKU. Please try again.');
        }
    };

    const handleBulkDeleteSkus = async () => {
        if (selectedIds.size === 0) return;

        const selectedProducts = products.filter((p) => selectedIds.has(p.id));
        const skus = Array.from(
            new Set(
                selectedProducts
                    .map((p) => (p.sku || '').trim())
                    .filter((sku): sku is string => Boolean(sku))
            )
        );

        if (skus.length === 0) return;

        const confirmed = window.confirm(
            `Delete ${skus.length} selected SKU(s) permanently?\n\nThis will remove products and related embeddings/attributes.`
        );
        if (!confirmed) return;

        try {
            const result = await productsApi.bulkDeleteBySku(skus);
            const deletedSkuSet = new Set(result.deleted_skus || []);
            const removedOnPage = products.filter((p) => deletedSkuSet.has(p.sku)).length;
            const targetPage =
                removedOnPage >= products.length && currentPage > 1
                    ? currentPage - 1
                    : currentPage;

            setSelectedIds(new Set());
            setSelectedProduct((prev) => (prev && deletedSkuSet.has(prev.sku) ? null : prev));
            setCurrentPage(targetPage);
            await loadProducts(targetPage, pageSize);
            loadFacets();

            if ((result.not_found_skus || []).length > 0) {
                window.alert(`Some SKUs were not found: ${result.not_found_skus.join(', ')}`);
            }
        } catch (error) {
            console.error('Failed to bulk delete SKUs:', error);
            window.alert('Failed to delete selected SKUs. Please try again.');
        }
    };



    const handleBulkHide = async () => {
        if (selectedIds.size === 0) return;
        try {
            await productsApi.bulkHide(Array.from(selectedIds));
            setProducts(prods => prods.map(p => selectedIds.has(p.id) ? { ...p, visibility: false } : p));
            if (selectedProduct && selectedIds.has(selectedProduct.id)) {
                setSelectedProduct({ ...selectedProduct, visibility: false });
            }
            setSelectedIds(new Set());
        } catch (error) {
            console.error('Failed to bulk hide:', error);
        }
    };

    const handleBulkShow = async () => {
        if (selectedIds.size === 0) return;
        try {
            await productsApi.bulkShow(Array.from(selectedIds));
            setProducts(prods => prods.map(p => selectedIds.has(p.id) ? { ...p, visibility: true } : p));
            if (selectedProduct && selectedIds.has(selectedProduct.id)) {
                setSelectedProduct({ ...selectedProduct, visibility: true });
            }
            setSelectedIds(new Set());
        } catch (error) {
            console.error('Failed to bulk show:', error);
        }
    };

    const toggleSelect = (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        const newSet = new Set(selectedIds);
        if (newSet.has(id)) {
            newSet.delete(id);
        } else {
            newSet.add(id);
        }
        setSelectedIds(newSet);
    };

    const selectAllOnCurrentPage = () => {
        setSelectedIds(new Set(products.map((p) => p.id)));
    };

    const deselectAll = () => {
        setSelectedIds(new Set());
    };

    const deselectAllOnCurrentPage = () => {
        setSelectedIds((prev) => {
            const next = new Set(prev);
            products.forEach((p) => next.delete(p.id));
            return next;
        });
    };

    const handleSelectAllChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.checked) {
            selectAllOnCurrentPage();
            return;
        }
        deselectAll();
    };

    const runSelectAction = (action: 'select_all' | 'deselect_all' | 'select_page' | 'deselect_page') => {
        if (action === 'select_all' || action === 'select_page') {
            selectAllOnCurrentPage();
        } else if (action === 'deselect_all') {
            deselectAll();
        } else {
            deselectAllOnCurrentPage();
        }
        setShowSelectActionMenu(false);
    };

    const toggleColumn = (key: string) => {
        setVisibleColumns((prev) => ({
            ...prev,
            [key]: !prev[key],
        }));
    };

    const resetFilters = () => {
        setFilterVisibility('all');
        setFilterFeatured('all');
        setActiveFilters({});
        setPendingFilters({});
        setMinPrice('');
        setMaxPrice('');
        setSearchQuery('');
        const firstPage = 1;
        setCurrentPage(firstPage);
        void loadProducts(firstPage, pageSize);
        loadFacets();
    };







    const mergeFacetOptions = (options: ProductFilterValue[] | undefined, selected: string[]) => {
        const map = new Map<string, number>();
        (options || []).forEach((item) => {
            map.set(item.value, item.count);
        });
        selected.forEach((value) => {
            if (!map.has(value)) {
                map.set(value, 0);
            }
        });
        return Array.from(map.entries()).map(([value, count]) => ({ value, count }));
    };

    const prioritizedFilterKeys = ['material', 'jewelry_type'];
    const orderedFilterKeys = Array.from(
        new Set([...prioritizedFilterKeys, ...Object.keys(facetData).sort()])
    );

    const applyProductUpdate = async (productId: string, updates: Partial<Product>) => {
        try {
            const updated = await productsApi.updateProduct(productId, updates);
            setProducts(prods => prods.map(p => p.id === productId ? updated : p));
            if (selectedProduct?.id === productId) {
                setSelectedProduct(updated);
            }
        } catch (error) {
            console.error('Failed to update product:', error);
        }
    };

    const handleFieldChange = (key: keyof Product, rawValue: string, type?: 'text' | 'number') => {
        if (!selectedProduct) return;
        let nextValue: string | number | null = rawValue;
        if (type === 'number') {
            nextValue = rawValue === '' ? null : Number(rawValue);
        }
        setSelectedProduct({ ...selectedProduct, [key]: nextValue } as Product);
    };

    const handleFieldBlur = async (key: keyof Product) => {
        if (!selectedProduct) return;
        const current = products.find(p => p.id === selectedProduct.id);
        const nextValue = selectedProduct[key] as unknown;
        if (current && current[key] === nextValue) return;
        await applyProductUpdate(selectedProduct.id, { [key]: nextValue } as Partial<Product>);
    };


    const buildBulkFieldState = (): BulkFieldState => {
        const initial: BulkFieldState = {};
        technicalFields.forEach((field) => {
            initial[field.key as string] = { enabled: false, value: '' };
        });
        return initial;
    };

    const openBulkEdit = () => {
        setBulkEditFields(buildBulkFieldState());
        setBulkEditError(null);
        setBulkEditOpen(true);
    };

    const toggleBulkField = (key: string) => {
        setBulkEditFields((prev) => ({
            ...prev,
            [key]: {
                enabled: !prev[key]?.enabled,
                value: prev[key]?.value ?? ''
            }
        }));
    };

    const updateBulkFieldValue = (key: string, value: string) => {
        setBulkEditFields((prev) => ({
            ...prev,
            [key]: {
                enabled: prev[key]?.enabled ?? false,
                value
            }
        }));
    };

    const handleBulkUpdate = async () => {
        if (selectedIds.size === 0 || bulkEditSaving) return;

        const updates: Record<string, string | number | null> = {};
        technicalFields.forEach((field) => {
            const state = bulkEditFields[field.key as string];
            if (!state?.enabled) return;
            if (field.type === 'number') {
                if (state.value === '') {
                    updates[field.key as string] = null;
                } else {
                    const parsed = Number(state.value);
                    if (!Number.isNaN(parsed)) {
                        updates[field.key as string] = parsed;
                    }
                }
            } else {
                updates[field.key as string] = state.value;
            }
        });

        if (Object.keys(updates).length === 0) {
            return;
        }

        setBulkEditSaving(true);
        setBulkEditError(null);
        try {
            const ids = Array.from(selectedIds);
            await productsApi.bulkUpdate(ids, updates as Partial<Product>);
            setProducts((prods) =>
                prods.map((p) => (selectedIds.has(p.id) ? { ...p, ...updates } : p))
            );
            if (selectedProduct && selectedIds.has(selectedProduct.id)) {
                setSelectedProduct({ ...selectedProduct, ...updates });
            }
            setSelectedIds(new Set());
            setBulkEditOpen(false);
        } catch (error) {
            console.error('Failed to bulk update products:', error);
            setBulkEditError('Bulk update failed. Please try again.');
        } finally {
            setBulkEditSaving(false);
        }
    };

    const bulkHasUpdates = Object.values(bulkEditFields).some((field) => field?.enabled);

    const allSelected = products.length > 0 && selectedIds.size === products.length;
    const someSelected = selectedIds.size > 0 && selectedIds.size < products.length;

    useEffect(() => {
        if (selectAllRef.current) {
            selectAllRef.current.indeterminate = someSelected;
        }
    }, [someSelected]);

    useEffect(() => {
        setShowSelectActionMenu(false);
    }, [currentPage, pageSize]);

    return (
        <div className="flex flex-col h-[calc(100vh-100px)] overflow-hidden bg-white">
            {/* Top Filter Bar */}
            <div className="relative z-[80] flex-shrink-0 border-b border-gray-200 bg-white">
                <div className="px-6 py-4 space-y-4">
                    {/* Primary Controls: Search + Global Filters */}
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <div className="flex items-center gap-3 flex-1 min-w-[300px]">
                            {/* Search */}
                            <div className="relative flex-1 max-w-md">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                                    </svg>
                                </div>
                                <input
                                    type="text"
                                    placeholder="Search by SKU, Name or Master Code..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                    className="w-full pl-10 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500 transition-all shadow-sm"
                                />
                            </div>

                            <div className="h-8 w-px bg-gray-200 mx-2"></div>

                            {/* Visibility Toggle */}
                            <div className="flex bg-gray-100 p-1 rounded-lg">
                                {['all', 'visible', 'hidden'].map((v) => (
                                    <button
                                        key={v}
                                        onClick={() => setFilterVisibility(v as any)}
                                        className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${filterVisibility === v
                                            ? 'bg-white text-gray-900 shadow-sm'
                                            : 'text-gray-500 hover:text-gray-700'
                                            }`}
                                    >
                                        {v.charAt(0).toUpperCase() + v.slice(1)}
                                    </button>
                                ))}
                            </div>

                            {/* Price Range */}
                            <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg p-1">
                                <span className="text-xs font-semibold text-gray-500 pl-2">Price:</span>
                                <input
                                    type="number"
                                    placeholder="Min"
                                    value={minPrice}
                                    onChange={(e) => setMinPrice(e.target.value)}
                                    className="w-16 px-1.5 py-1 text-xs border-0 bg-transparent focus:ring-0 text-gray-900 placeholder:text-gray-400 text-center"
                                />
                                <span className="text-gray-300">-</span>
                                <input
                                    type="number"
                                    placeholder="Max"
                                    value={maxPrice}
                                    onChange={(e) => setMaxPrice(e.target.value)}
                                    className="w-16 px-1.5 py-1 text-xs border-0 bg-transparent focus:ring-0 text-gray-900 placeholder:text-gray-400 text-center"
                                />
                                <button
                                    onClick={handleSearch}
                                    className="p-1 hover:bg-white rounded-md transition-colors text-primary-600"
                                    title="Apply Price Filter"
                                >
                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                    </svg>
                                </button>
                            </div>
                        </div>

                        {/* Right Actions */}
                        <div className="flex items-center gap-3">
                            <button
                                onClick={resetFilters}
                                className="px-3 py-2 text-sm text-gray-500 hover:text-gray-900 font-medium transition-colors"
                            >
                                Reset All
                            </button>
                            {selectedIds.size > 0 && (
                                <div className="flex items-center gap-2 animate-in fade-in slide-in-from-right-4">
                                    <button
                                        onClick={openBulkEdit}
                                        className="px-4 py-2 bg-indigo-600 text-white text-sm font-semibold rounded-lg hover:bg-indigo-700 shadow-sm transition-all"
                                    >
                                        Edit ({selectedIds.size})
                                    </button>
                                    <button
                                        onClick={handleBulkShow}
                                        className="px-4 py-2 bg-white border border-gray-200 text-gray-700 text-sm font-semibold rounded-lg hover:bg-gray-50 shadow-sm transition-all"
                                    >
                                        Show
                                    </button>
                                    <button
                                        onClick={handleBulkHide}
                                        className="px-4 py-2 bg-white border border-gray-200 text-red-600 text-sm font-semibold rounded-lg hover:bg-red-50 shadow-sm transition-all"
                                    >
                                        Hide
                                    </button>
                                    <button
                                        onClick={handleBulkDeleteSkus}
                                        className="px-4 py-2 bg-red-600 text-white text-sm font-semibold rounded-lg hover:bg-red-700 shadow-sm transition-all"
                                    >
                                        Delete
                                    </button>
                                </div>
                            )}
                            <div className="relative z-[120]">
                                <button
                                    onClick={() => setShowColumnMenu((prev) => !prev)}
                                    className="p-2 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
                                    title="Customize Columns"
                                >
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
                                </button>
                                {showColumnMenu && (
                                    <div className="absolute right-0 mt-2 w-64 bg-white border border-gray-200 rounded-lg shadow-xl p-3 z-[130] animate-in fade-in zoom-in-95 origin-top-right max-h-[400px] overflow-y-auto custom-scrollbar">
                                        <div className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Standard Columns</div>
                                        <div className="space-y-2 mb-4">
                                            {standardColumns.map((col) => (
                                                <label key={col.key} className="flex items-center gap-2 text-sm text-gray-700 hover:text-gray-900 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={visibleColumns[col.key]}
                                                        onChange={() => toggleColumn(col.key)}
                                                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                                    />
                                                    {col.label}
                                                </label>
                                            ))}
                                        </div>
                                        <div className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2 pt-2 border-t border-gray-100">Attributes</div>
                                        <div className="space-y-2">
                                            {attributeColumns.map((col) => (
                                                <label key={col.key} className="flex items-center gap-2 text-sm text-gray-700 hover:text-gray-900 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={visibleColumns[col.key]}
                                                        onChange={() => toggleColumn(col.key)}
                                                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                                    />
                                                    {col.label}
                                                </label>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Secondary Row: Attribute Filters */}
                    <div className="flex items-center gap-2 overflow-x-auto pb-2 custom-scrollbar">
                        <div className="text-xs font-bold text-gray-400 uppercase tracking-wider mr-2 flex-shrink-0">Filters:</div>
                        {facetLoading && <div className="text-xs text-gray-400 italic animate-pulse">Loading...</div>}

                        {orderedFilterKeys.map((key) => {
                            const options = mergeFacetOptions(
                                facetData[key],
                                pendingFilters[key] || []
                            );
                            if (options.length === 0 && !pendingFilters[key]?.length) return null;

                            const label = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

                            return (
                                <FilterDropdown
                                    key={key}
                                    label={label}
                                    options={options}
                                    selected={activeFilters[key] || []}
                                    onChange={(newValues) => {
                                        setActiveFilters(prev => ({ ...prev, [key]: newValues }));
                                    }}
                                    onApply={(values) => {
                                        setActiveFilters(prev => ({ ...prev, [key]: values }));
                                    }}
                                />
                            );
                        })}
                    </div>
                </div>

                {/* Active Filter Chips */}
                {Object.keys(activeFilters).some(k => activeFilters[k]?.length > 0) && (
                    <div className="px-6 pb-4 flex flex-wrap gap-2 items-center border-t border-gray-50 pt-3">
                        <span className="text-xs text-gray-400">Active:</span>
                        {Object.entries(activeFilters).map(([key, values]) => (
                            values.map(val => (
                                <button
                                    key={`${key}-${val}`}
                                    onClick={() => {
                                        const newVals = values.filter(v => v !== val);
                                        setActiveFilters(prev => ({ ...prev, [key]: newVals }));
                                    }}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary-50 text-primary-700 text-xs font-medium border border-primary-100 hover:bg-primary-100 hover:border-primary-200 transition-colors group"
                                >
                                    <span className="opacity-50 uppercase tracking-tighter text-[9px]">{key.replace('_', ' ')}:</span>
                                    <span>{val}</span>
                                    <svg className="w-3 h-3 opacity-50 group-hover:opacity-100" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                </button>
                            ))
                        ))}
                        <button
                            onClick={() => setActiveFilters({})}
                            className="text-xs text-red-500 hover:text-red-700 underline decoration-red-200 underline-offset-2 ml-2"
                        >
                            Clear all
                        </button>
                    </div>
                )}
            </div>

            {/* Main Content: Product List */}
            <div className={`flex-1 overflow-hidden relative flex flex-col ${selectedProduct ? 'mr-[450px] transition-all duration-300' : ''}`}>
                <div className="flex-1 overflow-hidden bg-gray-50/50 p-6">

                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden h-full flex flex-col">
                        <div className="flex-shrink-0 border-b border-gray-200 bg-white/95 backdrop-blur z-40">
                            <PaginationControls
                                currentPage={currentPage}
                                pageSize={pageSize}
                                totalItems={totalItems}
                                totalPages={totalPages}
                                isLoading={loading}
                                onChange={handlePaginationChange}
                                className="!border-0 !px-4 !py-3"
                            />
                        </div>

                        <div className="flex-1 overflow-auto">
                            <table className="min-w-full divide-y divide-gray-200 table-fixed">
                            <thead className="bg-gray-100">
                                <tr>
                                    <th className="w-12 px-4 py-3 text-left sticky top-0 z-50 bg-gray-100">
                                        <div className="relative flex items-center gap-1">
                                            <input
                                                type="checkbox"
                                                ref={selectAllRef}
                                                checked={allSelected}
                                                onChange={handleSelectAllChange}
                                                onClick={(e) => e.stopPropagation()}
                                                className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                            />
                                            <button
                                                ref={selectActionButtonRef}
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setShowSelectActionMenu((prev) => !prev);
                                                }}
                                                className="inline-flex h-5 w-5 items-center justify-center rounded border border-transparent text-gray-500 hover:border-gray-300 hover:bg-white"
                                                title="Selection options"
                                                aria-label="Selection options"
                                            >
                                                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                                </svg>
                                            </button>
                                            {showSelectActionMenu && (
                                                <div
                                                    ref={selectActionMenuRef}
                                                    className="absolute left-0 top-full mt-2 w-56 rounded-lg border border-gray-200 bg-white p-1 shadow-xl z-[140]"
                                                >
                                                    <button
                                                        type="button"
                                                        onClick={() => runSelectAction('select_all')}
                                                        disabled={products.length === 0 || allSelected}
                                                        className="w-full rounded px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
                                                    >
                                                        Select All
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => runSelectAction('deselect_all')}
                                                        disabled={selectedIds.size === 0}
                                                        className="w-full rounded px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
                                                    >
                                                        Deselect All
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => runSelectAction('select_page')}
                                                        disabled={products.length === 0 || allSelected}
                                                        className="w-full rounded px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
                                                    >
                                                        Select All on This Page
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => runSelectAction('deselect_page')}
                                                        disabled={selectedIds.size === 0}
                                                        className="w-full rounded px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-300"
                                                    >
                                                        Deselect All on This Page
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </th>
                                    {allColumns.map(col => visibleColumns[col.key] && (
                                        <th key={col.key} className={`${col.width} px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider sticky top-0 z-50 bg-gray-100`}>
                                            {col.label}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {products.map((product) => (
                                    <tr
                                        key={product.id}
                                        onClick={() => setSelectedProduct(product)}
                                        className={`group cursor-pointer hover:bg-primary-50/30 transition-colors ${selectedProduct?.id === product.id ? 'bg-primary-50' : ''} ${!product.visibility ? 'bg-gray-50/50 text-gray-400' : 'text-gray-900'}`}
                                    >
                                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                                            <input
                                                type="checkbox"
                                                checked={selectedIds.has(product.id)}
                                                onChange={(e) => toggleSelect(product.id, e as any)}
                                                className="rounded border-gray-300 text-primary-600"
                                            />
                                        </td>

                                        {allColumns.map(col => {
                                            if (!visibleColumns[col.key]) return null;

                                            // Special Rendering for Standard Columns
                                            if (col.key === 'image') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3">
                                                        <div className="relative w-10 h-10 bg-gray-100 rounded-lg overflow-hidden border border-gray-100 group-hover:border-primary-200 transition-colors">
                                                            {product.image_url ? (
                                                                <img src={product.image_url} alt="" className="w-full h-full object-cover" />
                                                            ) : (
                                                                <div className="w-full h-full flex items-center justify-center text-gray-300">
                                                                    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'master_code') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3 text-sm font-mono text-gray-500 uppercase">
                                                        {product.master_code ? product.master_code : <span className="text-gray-300">—</span>}
                                                        {product.is_featured && (
                                                            <div className="mt-1">
                                                                <span className="inline-flex items-center gap-1 text-[10px] text-yellow-600 bg-yellow-50 px-1.5 py-0.5 rounded border border-yellow-100 font-bold uppercase tracking-tighter">
                                                                    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.162c.969 0 1.371 1.24.588 1.81l-3.37 2.448a1 1 0 00-.364 1.118l1.287 3.957c.3.921-.755 1.688-1.54 1.118l-3.37-2.448a1 1 0 00-1.175 0l-3.37 2.448c-.784.57-1.838-.197-1.54-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.05 9.384c-.783-.57-.38-1.81.588-1.81h4.162a1 1 0 00.95-.69l1.286-3.957z" /></svg>
                                                                    Featured
                                                                </span>
                                                            </div>
                                                        )}
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'description') {
                                                return (
                                                    <td key={col.key} className="Description px-4 py-3">
                                                        <div className="text-xs text-gray-500 line-clamp-2" title={product.description || ''}>
                                                            {product.description || <span className="text-gray-300 italic">No description</span>}
                                                        </div>
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'sku') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3 text-sm font-mono text-gray-500 uppercase font-bold">{product.sku}</td>
                                                );
                                            }
                                            if (col.key === 'price') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3 text-sm font-bold text-gray-900">${(product.price || 0).toFixed(2)}</td>
                                                );
                                            }
                                            if (col.key === 'status') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3 text-center">
                                                        <div className={`w-2 h-2 rounded-full mx-auto ${product.visibility ? (product.in_stock ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-yellow-500') : 'bg-gray-300'}`} />
                                                    </td>
                                                );
                                            }

                                            // Default Attribute Rendering
                                            const val = product[col.key as keyof Product];
                                            return (
                                                <td key={col.key} className="px-4 py-3 text-sm text-gray-600">
                                                    {val ? String(val) : <span className="text-gray-300">—</span>}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                ))}
                            </tbody>
                            </table>

                            {loading && products.length === 0 && (
                                <div className="flex flex-col items-center justify-center py-24 gap-4 animate-in fade-in zoom-in">
                                    <div className="animate-spin rounded-full h-12 w-12 border-4 border-primary-200 border-t-primary-600"></div>
                                    <p className="text-gray-500 font-medium tracking-tight">Syncing with Magento...</p>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {/* Side Drawer: Product Details */}
                {selectedProduct && (
                    <div className="fixed inset-y-0 right-0 w-[450px] bg-white shadow-2xl z-[100] border-l border-gray-200 flex flex-col animate-in slide-in-from-right duration-300">
                        {/* Drawer Header */}
                        <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-gray-50/80">
                            <div className="flex items-center gap-4">
                                <button
                                    onClick={() => setSelectedProduct(null)}
                                    className="p-2 hover:bg-white rounded-full transition-colors text-gray-400 hover:text-gray-900"
                                >
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                                </button>
                                <div>
                                    <h2 className="text-lg font-bold text-gray-900 leading-tight">Product Details</h2>
                                    <p className="text-xs text-gray-500 uppercase font-bold tracking-widest uppercase">{selectedProduct.sku}</p>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <a href={selectedProduct.url} target="_blank" className="p-2 text-gray-400 hover:text-primary-600 transition-colors" title="View on Store">
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                                </a>
                            </div>
                        </div>

                        {/* Drawer Content */}
                        <div className="flex-1 overflow-y-auto">
                            <div className="p-6 space-y-8">
                                {/* Product Header Card */}
                                <div className="flex gap-4 items-start">
                                    <div className="w-24 h-24 bg-gray-50 rounded-xl border border-gray-100 overflow-hidden flex-shrink-0 shadow-sm">
                                        {selectedProduct.image_url ? (
                                            <img src={selectedProduct.image_url} alt="" className="w-full h-full object-cover" />
                                        ) : (
                                            <div className="w-full h-full flex items-center justify-center text-gray-200">
                                                <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" /></svg>
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <h3 className="text-xl font-bold text-gray-900 leading-tight mb-1">{selectedProduct.name}</h3>
                                        <div className="text-2xl font-black text-primary-600">${selectedProduct.price.toFixed(2)}</div>
                                        <div className={`mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${selectedProduct.in_stock ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                                            <span className={`w-1.5 h-1.5 rounded-full ${selectedProduct.in_stock ? 'bg-green-600' : 'bg-red-600'}`}></span>
                                            {selectedProduct.in_stock ? 'In Stock' : 'Out of Stock'}
                                        </div>
                                    </div>
                                </div>

                                {/* Quick Actions */}
                                <section className="grid grid-cols-2 gap-3">
                                    <button
                                        onClick={() => handleToggleVisibility(selectedProduct)}
                                        className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl border font-bold text-xs uppercase tracking-wide transition-all ${selectedProduct.visibility ? 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50' : 'bg-yellow-50 border-yellow-200 text-yellow-700'}`}
                                    >
                                        <span className={`w-2 h-2 rounded-full ${selectedProduct.visibility ? 'bg-green-500' : 'bg-yellow-500'}`}></span>
                                        {selectedProduct.visibility ? 'Visible' : 'Hidden'}
                                    </button>
                                    <button
                                        onClick={() => handleToggleFeatured(selectedProduct)}
                                        className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl border font-bold text-xs uppercase tracking-wide transition-all ${selectedProduct.is_featured ? 'bg-yellow-50 border-yellow-200 text-yellow-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                                    >
                                        <svg className="w-4 h-4" fill={selectedProduct.is_featured ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" /></svg>
                                        {selectedProduct.is_featured ? 'Featured' : 'Feature'}
                                    </button>
                                    <button
                                        onClick={() => handleHardDeleteBySku(selectedProduct)}
                                        className="col-span-2 flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-red-200 bg-red-50 text-red-700 hover:bg-red-100 font-bold text-xs uppercase tracking-wide transition-all"
                                    >
                                        Delete SKU
                                    </button>
                                </section>

                                {/* Master Code */}
                                <section className="space-y-4">
                                    <div className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
                                        <label className="text-sm font-semibold text-gray-700 mb-2 block">Master Code</label>
                                        <input
                                            type="text"
                                            placeholder="Enter master code..."
                                            value={selectedProduct.master_code || ''}
                                            onChange={async (e) => {
                                                const newCode = e.target.value;
                                                setSelectedProduct({ ...selectedProduct, master_code: newCode });
                                                try {
                                                    await productsApi.updateProduct(selectedProduct.id, { master_code: newCode });
                                                    setProducts(prods => prods.map(p => p.id === selectedProduct.id ? { ...p, master_code: newCode } : p));
                                                } catch (error) {
                                                    console.error('Failed to update master code:', error);
                                                }
                                            }}
                                            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500 font-mono uppercase"
                                        />
                                        <p className="text-[10px] text-gray-400 mt-2">Group multiple SKUs under one master collection.</p>
                                    </div>
                                </section>

                                {/* Attributes Grid */}
                                <section className="space-y-4">
                                    <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest pl-1">Technical Attributes</h4>
                                    <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                                        {technicalFields.map((field) => (
                                            <EditableAttribute
                                                key={field.key}
                                                label={field.label}
                                                type={field.type}
                                                value={selectedProduct[field.key] as string | number | null | undefined}
                                                onChange={(value) => handleFieldChange(field.key, value, field.type)}
                                                onBlur={() => handleFieldBlur(field.key)}
                                            />
                                        ))}
                                    </div>
                                </section>

                                {/* Description */}
                                <section className="space-y-3">
                                    <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest pl-1">Description</h4>
                                    <textarea
                                        value={selectedProduct.description ?? ''}
                                        onChange={(e) => handleFieldChange('description', e.target.value)}
                                        onBlur={() => handleFieldBlur('description')}
                                        placeholder="Add a description for this product..."
                                        rows={5}
                                        className="w-full text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-xl p-4 border border-gray-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                                    />
                                </section>
                            </div>
                        </div>
                    </div>
                )}
            </div>
            {/* Bulk Edit Modal */}
            {bulkEditOpen && (
                <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
                    <div className="w-full max-w-3xl bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                            <div>
                                <h3 className="text-lg font-semibold text-gray-900">Bulk Edit Attributes</h3>
                                <p className="text-xs text-gray-500">Update {selectedIds.size} selected SKUs</p>
                            </div>
                            <button
                                onClick={() => {
                                    setBulkEditOpen(false);
                                    setBulkEditError(null);
                                }}
                                className="text-gray-400 hover:text-gray-600 transition-colors"
                            >
                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                        <div className="p-6 max-h-[60vh] overflow-y-auto space-y-4">
                            {technicalFields.map((field) => {
                                const state = bulkEditFields[field.key as string] || { enabled: false, value: '' };
                                return (
                                    <div key={field.key} className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-center">
                                        <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
                                            <input
                                                type="checkbox"
                                                checked={state.enabled}
                                                onChange={() => toggleBulkField(field.key as string)}
                                                className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                            />
                                            {field.label}
                                        </label>
                                        <input
                                            type={field.type === 'number' ? 'number' : 'text'}
                                            value={state.value}
                                            onChange={(e) => updateBulkFieldValue(field.key as string, e.target.value)}
                                            disabled={!state.enabled}
                                            className={`sm:col-span-2 w-full px-3 py-2 text-sm border rounded-lg focus:ring-2 focus:ring-primary-500 ${state.enabled ? 'border-gray-200 bg-white' : 'border-gray-100 bg-gray-50 text-gray-400'}`}
                                            placeholder={state.enabled ? 'Enter value...' : 'Enable to edit'}
                                        />
                                    </div>
                                );
                            })}
                        </div>
                        <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
                            <div className="text-xs text-gray-500">
                                <p>Only checked fields will be overwritten.</p>
                                {bulkEditError && <p className="text-red-600 mt-1">{bulkEditError}</p>}
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => {
                                        setBulkEditOpen(false);
                                        setBulkEditError(null);
                                    }}
                                    className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-white"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleBulkUpdate}
                                    disabled={!bulkHasUpdates || bulkEditSaving}
                                    className="px-4 py-2 text-sm rounded-lg bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50"
                                >
                                    {bulkEditSaving ? 'Updating...' : `Update ${selectedIds.size} SKUs`}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

// Helper Components
const EditableAttribute: React.FC<{
    label: string;
    value?: string | number | null;
    type?: 'text' | 'number';
    onChange: (value: string) => void;
    onBlur: () => void;
}> = ({ label, value, type = 'text', onChange, onBlur }) => (
    <div className="flex flex-col gap-1 border-b border-gray-50 pb-2">
        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tight">{label}</span>
        <input
            type={type}
            value={value === null || value === undefined ? '' : String(value)}
            onChange={(e) => onChange(e.target.value)}
            onBlur={onBlur}
            placeholder="N/A"
            className="text-sm font-semibold text-gray-700 bg-transparent border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary-500"
        />
    </div>
);

const FilterDropdown: React.FC<{
    label: string,
    options: { value: string; count: number }[],
    selected: string[],
    onChange: (values: string[]) => void,
    onApply: (values: string[]) => void
}> = ({ label, options, selected, onChange, onApply }) => {
    const [isOpen, setIsOpen] = useState(false);
    const buttonRef = useRef<HTMLButtonElement>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const [coords, setCoords] = useState({ top: 0, left: 0 });

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            if (
                isOpen &&
                buttonRef.current &&
                !buttonRef.current.contains(target) &&
                dropdownRef.current &&
                !dropdownRef.current.contains(target)
            ) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen]);

    // Close on scroll to ensure position remains valid (simple approach)
    // Close on scroll only if the scroll event comes from a parent that moves the button
    // or if the window scrolls. Ignore scrolls inside the dropdown itself.
    useEffect(() => {
        const handleScroll = (event: Event) => {
            if (!isOpen) return;
            const target = event.target as Node;

            // If scrolling inside the dropdown content, allow it
            if (dropdownRef.current && dropdownRef.current.contains(target)) {
                return;
            }

            // Ideally we only close if the button moves. Checking if the target contains the button
            // is a decent proxy for "scrolling a parent container".
            // Note: 'contains' is available on Node.
            if (target.contains && target.contains(buttonRef.current)) {
                setIsOpen(false);
                return;
            }

            // Special case: if target is document/window
            if (target === document || target === document.documentElement || target === document.body) {
                setIsOpen(false);
            }
        };
        // Use capture=true to catch scroll events from any container
        window.addEventListener('scroll', handleScroll, true);
        return () => window.removeEventListener('scroll', handleScroll, true);
    }, [isOpen]);

    const toggle = () => {
        if (!isOpen && buttonRef.current) {
            const rect = buttonRef.current.getBoundingClientRect();
            setCoords({
                top: rect.bottom + 4,
                left: rect.left
            });
        }
        setIsOpen(!isOpen);
    };

    const hasSelection = selected.length > 0;

    return (
        <>
            <button
                ref={buttonRef}
                type="button"
                onClick={toggle}
                className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${hasSelection
                    ? 'bg-primary-50 text-primary-700 border-primary-200 shadow-sm'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                    }`}
            >
                {label}
                {hasSelection && (
                    <span className="ml-1 flex items-center justify-center bg-primary-600 text-white rounded-full text-[10px] min-w-[16px] h-4 px-1">
                        {selected.length}
                    </span>
                )}
                <svg className={`w-4 h-4 transition-transform text-gray-400 ${isOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </button>

            {isOpen && createPortal(
                <div
                    ref={dropdownRef}
                    className="fixed w-64 bg-white border border-gray-200 rounded-xl shadow-xl z-[9999] animate-in fade-in zoom-in-95 origin-top-left flex flex-col max-h-[400px]"
                    style={{ top: coords.top, left: coords.left }}
                >
                    <div className="p-3 border-b border-gray-50 bg-gray-50/50 rounded-t-xl flex justify-between items-center">
                        <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">{label}</span>
                        {hasSelection && (
                            <button
                                onClick={() => onChange([])}
                                className="text-[10px] text-red-500 hover:underline"
                            >
                                Clear
                            </button>
                        )}
                    </div>
                    <div className="p-2 overflow-y-auto custom-scrollbar flex-1">
                        {options.map((opt) => {
                            const isSelected = selected.includes(opt.value);
                            return (
                                <label key={opt.value} className="flex items-center gap-2 p-2 hover:bg-gray-50 rounded-lg cursor-pointer transition-colors">
                                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${isSelected ? 'bg-primary-600 border-primary-600' : 'border-gray-300 bg-white'}`}>
                                        {isSelected && <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>}
                                    </div>
                                    <input
                                        type="checkbox"
                                        className="hidden"
                                        checked={isSelected}
                                        onChange={() => {
                                            const newSet = new Set(selected);
                                            if (newSet.has(opt.value)) newSet.delete(opt.value);
                                            else newSet.add(opt.value);
                                            onChange(Array.from(newSet));
                                        }}
                                    />
                                    <span className={`text-xs flex-1 truncate ${isSelected ? 'font-medium text-gray-900' : 'text-gray-600'}`}>{opt.value}</span>
                                    <span className="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded-full">{opt.count}</span>
                                </label>
                            );
                        })}
                    </div>
                    <div className="p-2 border-t border-gray-100 bg-gray-50 rounded-b-xl">
                        <button
                            onClick={() => {
                                onApply(selected);
                                setIsOpen(false);
                            }}
                            className="w-full py-2 bg-primary-600 text-white text-xs font-semibold rounded-lg hover:bg-primary-700 transition-colors shadow-sm"
                        >
                            Apply
                        </button>
                    </div>
                </div>,
                document.body
            )}
        </>
    );
};
