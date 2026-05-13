import React, { useState, useEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { productsApi, Product, ProductFilterValue } from '../../api/training';
import { PaginationControls } from '../../components/common/PaginationControls';
import { defaultPageSize } from '../../constants/pagination';

type BulkFieldState = Record<string, { enabled: boolean; value: string }>;
type DetailTab = 'attributes' | 'quality' | 'description';
type SaveState = 'idle' | 'saving' | 'saved' | 'error';
type QualityFlagSeverity = 'info' | 'warning' | 'danger';
type QualityFlagKey = 'missing_category' | 'missing_core' | 'missing_image' | 'no_master_code' | 'hidden_in_stock' | 'visible_out_of_stock';

type QualityFlag = {
    key: QualityFlagKey;
    label: string;
    description: string;
    severity: QualityFlagSeverity;
};

const CATEGORY_DELIMITER = ';;';

const parseCategoryTokens = (rawValue: unknown): string[] => {
    const raw = String(rawValue || '');
    if (!raw.trim()) return [];

    const seen = new Set<string>();
    const tokens: string[] = [];
    raw
        .split(/;;|;|\r?\n/g)
        .map((part) => part.trim())
        .filter(Boolean)
        .forEach((token) => {
            const key = token.toLowerCase();
            if (seen.has(key)) return;
            seen.add(key);
            tokens.push(token);
        });
    return tokens;
};

const normalizeCategoryValue = (rawValue: unknown): string => (
    parseCategoryTokens(rawValue).join(CATEGORY_DELIMITER)
);

const hasText = (value: unknown): boolean => String(value ?? '').trim().length > 0;

const getProductQualityFlags = (product: Product): QualityFlag[] => {
    const flags: QualityFlag[] = [];
    if (parseCategoryTokens(product.category).length === 0) {
        flags.push({
            key: 'missing_category',
            label: 'Missing category',
            description: 'Category is empty, so filtering and chat matching will be weaker.',
            severity: 'danger',
        });
    }
    if (!hasText(product.material) || !hasText(product.jewelry_type)) {
        flags.push({
            key: 'missing_core',
            label: 'Missing core attributes',
            description: 'Material and jewelry type should be filled for reliable product matching.',
            severity: 'warning',
        });
    }
    if (!hasText(product.image_url)) {
        flags.push({
            key: 'missing_image',
            label: 'Missing image',
            description: 'The product has no image URL for storefront or chat preview display.',
            severity: 'warning',
        });
    }
    if (!hasText(product.master_code)) {
        flags.push({
            key: 'no_master_code',
            label: 'No master code',
            description: 'Master code is empty, so related SKUs cannot be grouped cleanly.',
            severity: 'info',
        });
    }
    if (!product.visibility && product.in_stock) {
        flags.push({
            key: 'hidden_in_stock',
            label: 'Hidden but in stock',
            description: 'This SKU is available but hidden from active product surfaces.',
            severity: 'warning',
        });
    }
    if (product.visibility && !product.in_stock) {
        flags.push({
            key: 'visible_out_of_stock',
            label: 'Visible but out of stock',
            description: 'This SKU is visible but cannot currently be purchased.',
            severity: 'danger',
        });
    }
    return flags;
};

const saveStateLabel: Record<SaveState, string> = {
    idle: '',
    saving: 'Saving...',
    saved: 'Saved',
    error: 'Save failed',
};

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
    const [detailTab, setDetailTab] = useState<DetailTab>('attributes');
    const [fieldSaveStates, setFieldSaveStates] = useState<Record<string, SaveState>>({});
    const [attributeDrafts, setAttributeDrafts] = useState<Record<string, string>>({});
    const [masterVariants, setMasterVariants] = useState<Product[]>([]);
    const [masterVariantsLoading, setMasterVariantsLoading] = useState(false);
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
        { key: 'category', label: 'Category' },
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
    const skuAttributeFields = technicalFields.filter((field) => field.key !== 'category');

    const standardColumns = [
        { key: 'image', label: 'Image', width: 'w-16' },
        { key: 'sku', label: 'SKU', width: 'w-[18%]' },
        { key: 'description', label: 'Description', width: 'w-[44%]' },
        { key: 'price', label: 'Price', width: 'w-24' },
        { key: 'status', label: 'Status', width: 'w-16' },
        { key: 'master_code', label: 'Master Code', width: 'w-[10%]' },
        { key: 'klevu_id', label: 'Klevu ID', width: 'w-[10%]' },
        { key: 'object_id', label: 'Object ID', width: 'w-[10%]' },
    ];

    const attributeColumns = technicalFields.map(field => ({
        key: field.key as string,
        label: field.label,
        width: 'w-[10%]',
        isAttribute: true
    }));

    const allColumns = [...standardColumns, ...attributeColumns];

    const [visibleColumns, setVisibleColumns] = useState<Record<string, boolean>>(() => {
        const initial: Record<string, boolean> = {
            image: true,
            master_code: false,
            klevu_id: false,
            object_id: false,
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
    const [autoVisibleColumns, setAutoVisibleColumns] = useState<Record<string, boolean>>({});

    // Filters
    const [filterVisibility, setFilterVisibility] = useState<'all' | 'visible' | 'hidden'>('all');
    const [categoryMode, setCategoryMode] = useState<'any' | 'all'>('any');

    // Dynamic Filters
    const [activeFilters, setActiveFilters] = useState<Record<string, string[]>>({});
    const [pendingFilters, setPendingFilters] = useState<Record<string, string[]>>({});
    const [showFilterDrawer, setShowFilterDrawer] = useState(false);

    // UI State for Filters


    const [minPrice, setMinPrice] = useState('');
    const [maxPrice, setMaxPrice] = useState('');
    const [facetData, setFacetData] = useState<Record<string, ProductFilterValue[]>>({});
    const [facetLoading, setFacetLoading] = useState(false);

    const displayedProducts = products;
    const categoryOptions = useMemo(
        () => (facetData.category || [])
            .map((option) => String(option.value || '').trim())
            .filter(Boolean),
        [facetData.category]
    );
    const persistedSelectedProduct = useMemo(
        () => selectedProduct ? products.find((product) => product.id === selectedProduct.id) || null : null,
        [products, selectedProduct?.id]
    );
    const selectedMasterCode = (persistedSelectedProduct?.master_code || selectedProduct?.master_code || '').trim();

    useEffect(() => {
        const firstPage = 1;
        setCurrentPage(firstPage);
        void loadProducts(firstPage, pageSize);
        loadFacets();
    }, [filterVisibility, categoryMode, activeFilters]);

    useEffect(() => {
        setPendingFilters(activeFilters);
    }, [activeFilters]);

    useEffect(() => {
        if (selectedProduct) {
            setDetailTab('attributes');
        }
    }, [selectedProduct?.id]);

    useEffect(() => {
        if (!selectedProduct) {
            setAttributeDrafts({});
            return;
        }
        const nextDrafts: Record<string, string> = {};
        skuAttributeFields.forEach((field) => {
            const value = selectedProduct[field.key];
            nextDrafts[field.key as string] = value === null || value === undefined ? '' : String(value);
        });
        setAttributeDrafts(nextDrafts);
    }, [selectedProduct?.id]);

    useEffect(() => {
        const masterCode = selectedMasterCode;
        if (!masterCode) {
            setMasterVariants([]);
            setMasterVariantsLoading(false);
            return;
        }

        let cancelled = false;
        setMasterVariantsLoading(true);
        productsApi.listMasterCodeVariants(masterCode, { pageSize: 200 })
            .then((result) => {
                if (cancelled) return;
                setMasterVariants(result.items || []);
            })
            .catch((error) => {
                if (cancelled) return;
                console.error('Failed to load master code variants:', error);
                setMasterVariants([]);
            })
            .finally(() => {
                if (!cancelled) {
                    setMasterVariantsLoading(false);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [selectedProduct?.id, selectedMasterCode]);

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

    useEffect(() => {
        if (!showFilterDrawer) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setShowFilterDrawer(false);
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [showFilterDrawer]);

    useEffect(() => {
        if (!showFilterDrawer) return;

        const body = document.body;
        const docEl = document.documentElement;
        const previousOverflow = body.style.overflow;
        const previousPaddingRight = body.style.paddingRight;
        const scrollbarWidth = window.innerWidth - docEl.clientWidth;
        const computedPaddingRight = Number.parseFloat(window.getComputedStyle(body).paddingRight || '0') || 0;

        body.style.overflow = 'hidden';
        if (scrollbarWidth > 0) {
            body.style.paddingRight = `${computedPaddingRight + scrollbarWidth}px`;
        }

        return () => {
            body.style.overflow = previousOverflow;
            body.style.paddingRight = previousPaddingRight;
        };
    }, [showFilterDrawer]);

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
            params.category_mode = categoryMode;

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
            params.category_mode = categoryMode;

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
        setSelectedIds(new Set(displayedProducts.map((p) => p.id)));
    };

    const deselectAll = () => {
        setSelectedIds(new Set());
    };

    const deselectAllOnCurrentPage = () => {
        setSelectedIds((prev) => {
            const next = new Set(prev);
            displayedProducts.forEach((p) => next.delete(p.id));
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
        setCategoryMode('any');
        setActiveFilters({});
        setPendingFilters({});
        setShowFilterDrawer(false);
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

    const withFilterValues = (source: Record<string, string[]>, key: string, values: string[]) => {
        const next = { ...source };
        const cleanValues = (values || []).filter((value) => String(value).trim() !== '');
        if (cleanValues.length === 0) {
            delete next[key];
            return next;
        }
        next[key] = cleanValues;
        return next;
    };

    const attributeKeySet = new Set(technicalFields.map((field) => field.key as string));
    const categoryColumnRules: Array<{ matchers: RegExp[]; columns: string[] }> = [
        {
            matchers: [/\bring\b/i, /\bhoop\b/i, /\bcircular\b/i],
            columns: ['ring_size', 'outer_diameter', 'gauge', 'threading', 'material', 'color'],
        },
        {
            matchers: [/\bbarbell\b/i, /\bhorseshoe\b/i],
            columns: ['length', 'gauge', 'threading', 'material', 'color'],
        },
        {
            matchers: [/\blabret\b/i, /\bstud\b/i],
            columns: ['length', 'gauge', 'threading', 'material', 'color'],
        },
        {
            matchers: [/\btunnel\b/i, /\bplug\b/i],
            columns: ['size', 'material', 'color'],
        },
        {
            matchers: [/\bpincher\b/i],
            columns: ['pincher_size', 'gauge', 'material', 'color'],
        },
    ];

    const inferColumnsFromCategoryLikeValues = (values: string[]) => {
        const inferred = new Set<string>();
        (values || []).forEach((rawValue) => {
            const value = String(rawValue || '').trim();
            if (!value) return;
            categoryColumnRules.forEach((rule) => {
                if (rule.matchers.some((matcher) => matcher.test(value))) {
                    rule.columns.forEach((column) => inferred.add(column));
                }
            });
        });
        return Array.from(inferred);
    };

    useEffect(() => {
        const inferred = new Set<string>();
        Object.entries(activeFilters).forEach(([key, values]) => {
            if ((values || []).length === 0) return;
            if (attributeKeySet.has(key)) {
                inferred.add(key);
            }
        });

        const taxonomyValues = [
            ...(activeFilters.category || []),
            ...(activeFilters.jewelry_type || []),
        ];
        inferColumnsFromCategoryLikeValues(taxonomyValues).forEach((column) => inferred.add(column));

        const next: Record<string, boolean> = {};
        inferred.forEach((key) => {
            if (attributeKeySet.has(key)) {
                next[key] = true;
            }
        });
        setAutoVisibleColumns(next);
    }, [activeFilters]);

    const effectiveVisibleColumns = useMemo(() => {
        const merged = { ...visibleColumns };
        Object.entries(autoVisibleColumns).forEach(([key, enabled]) => {
            if (enabled) {
                merged[key] = true;
            }
        });
        return merged;
    }, [visibleColumns, autoVisibleColumns]);

    const formatFilterLabel = (key: string) => {
        if (key === 'category') return 'Category';
        if (key === 'jewelry_type') return 'Subcategory';
        return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    };

    const hasRenderableFilter = (key: string) => {
        const pendingValues = pendingFilters[key] || activeFilters[key] || [];
        const options = mergeFacetOptions(facetData[key], pendingValues);
        return options.length > 0 || pendingValues.length > 0;
    };

    const prioritizedFilterKeys = ['category', 'jewelry_type', 'material', 'color'];
    const orderedFilterKeys = Array.from(
        new Set([...prioritizedFilterKeys, ...Object.keys(facetData).sort()])
    );
    const quickBaseKeys = ['category', 'jewelry_type', 'material'];
    const quickFilterKeys = Array.from(new Set(quickBaseKeys))
        .filter((key) => orderedFilterKeys.includes(key))
        .filter((key) => hasRenderableFilter(key));
    const advancedFilterKeys = orderedFilterKeys
        .filter((key) => !quickFilterKeys.includes(key))
        .filter((key) => hasRenderableFilter(key));
    const advancedActiveFilterCount = advancedFilterKeys.filter((key) => (activeFilters[key] || []).length > 0).length;
    const activeFilterValueCount = useMemo(
        () => Object.values(activeFilters).reduce((sum, values) => sum + (values?.length || 0), 0),
        [activeFilters]
    );
    const totalFilterBadgeCount = activeFilterValueCount + (minPrice ? 1 : 0) + (maxPrice ? 1 : 0);

    const advancedFilterGroupConfig: Array<{ title: string; keys: string[] }> = [
        {
            title: 'Taxonomy',
            keys: ['category', 'jewelry_type'],
        },
        {
            title: 'Material & Build',
            keys: ['material', 'threading', 'design'],
        },
        {
            title: 'Size & Dimensions',
            keys: ['gauge', 'length', 'size', 'outer_diameter', 'pincher_size', 'ring_size', 'height'],
        },
        {
            title: 'Color & Finish',
            keys: ['color', 'cz_color', 'opal_color', 'crystal_color', 'pearl_color'],
        },
        {
            title: 'Packaging & Ops',
            keys: ['packing_option', 'size_in_pack', 'quantity_in_bulk', 'rack'],
        },
    ];
    const advancedKeySet = new Set(advancedFilterKeys);
    const groupedAdvancedFilters: Array<{ title: string; keys: string[] }> = [];
    const assignedAdvancedKeys = new Set<string>();
    advancedFilterGroupConfig.forEach((group) => {
        const keys = group.keys.filter((key) => advancedKeySet.has(key));
        if (keys.length > 0) {
            keys.forEach((key) => assignedAdvancedKeys.add(key));
            groupedAdvancedFilters.push({ title: group.title, keys });
        }
    });
    const uncategorizedAdvancedKeys = advancedFilterKeys.filter((key) => !assignedAdvancedKeys.has(key));
    if (uncategorizedAdvancedKeys.length > 0) {
        groupedAdvancedFilters.push({ title: 'Additional Attributes', keys: uncategorizedAdvancedKeys });
    }

    const renderFilterDropdown = (key: string) => {
        const pendingValues = pendingFilters[key] || activeFilters[key] || [];
        const options = mergeFacetOptions(facetData[key], pendingValues);
        if (options.length === 0 && !pendingValues.length) return null;
        return (
            <FilterDropdown
                key={key}
                label={formatFilterLabel(key)}
                options={options}
                selected={pendingValues}
                onChange={(newValues) => {
                    setPendingFilters(prev => withFilterValues(prev, key, newValues));
                    setActiveFilters(prev => withFilterValues(prev, key, newValues));
                }}
            />
        );
    };

    const applyProductUpdate = async (productId: string, updates: Partial<Product>) => {
        const updateKeys = Object.keys(updates);
        if (updateKeys.length > 0) {
            setFieldSaveStates((prev) => {
                const next = { ...prev };
                updateKeys.forEach((key) => {
                    next[`${productId}:${key}`] = 'saving';
                });
                return next;
            });
        }
        try {
            const updated = await productsApi.updateProduct(productId, updates);
            setProducts(prods => prods.map(p => p.id === productId ? updated : p));
            if (selectedProduct?.id === productId) {
                setSelectedProduct(updated);
            }
            if (updateKeys.length > 0) {
                setFieldSaveStates((prev) => {
                    const next = { ...prev };
                    updateKeys.forEach((key) => {
                        next[`${productId}:${key}`] = 'saved';
                    });
                    return next;
                });
                window.setTimeout(() => {
                    setFieldSaveStates((prev) => {
                        const next = { ...prev };
                        updateKeys.forEach((key) => {
                            if (next[`${productId}:${key}`] === 'saved') {
                                next[`${productId}:${key}`] = 'idle';
                            }
                        });
                        return next;
                    });
                }, 1600);
            }
        } catch (error) {
            console.error('Failed to update product:', error);
            if (updateKeys.length > 0) {
                setFieldSaveStates((prev) => {
                    const next = { ...prev };
                    updateKeys.forEach((key) => {
                        next[`${productId}:${key}`] = 'error';
                    });
                    return next;
                });
            }
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
        if (key === 'master_code') {
            await handleMasterCodeCommit(String(selectedProduct.master_code || ''));
            return;
        }
        const current = products.find(p => p.id === selectedProduct.id);
        const nextValue = selectedProduct[key] as unknown;
        if (current && current[key] === nextValue) return;
        await applyProductUpdate(selectedProduct.id, { [key]: nextValue } as Partial<Product>);
    };

    const setFieldSaveStateForProducts = (productIds: string[], key: keyof Product, state: SaveState) => {
        setFieldSaveStates((prev) => {
            const next = { ...prev };
            productIds.forEach((productId) => {
                next[`${productId}:${String(key)}`] = state;
            });
            return next;
        });
    };

    const handleCategoryCommit = async (nextCategory: string, scope: 'sku' | 'master' = 'sku') => {
        if (!selectedProduct) return;
        const normalized = normalizeCategoryValue(nextCategory);
        if (scope === 'master') {
            const variantIds = Array.from(new Set(
                (masterVariants.length > 0 ? masterVariants : [selectedProduct])
                    .map((product) => product.id)
                    .filter(Boolean)
            ));
            if (variantIds.length <= 1) {
                await applyProductUpdate(selectedProduct.id, { category: normalized });
                return;
            }

            const confirmed = window.confirm(
                `Apply this category to ${variantIds.length} SKUs under master code "${selectedMasterCode || selectedProduct.master_code}"?\n\nThis will overwrite the category on every child SKU in this master group.`
            );
            if (!confirmed) return;

            setFieldSaveStateForProducts(variantIds, 'category', 'saving');
            try {
                await productsApi.bulkUpdate(variantIds, { category: normalized });
                setProducts((prods) => prods.map((product) => (
                    variantIds.includes(product.id) ? { ...product, category: normalized } : product
                )));
                setMasterVariants((variants) => variants.map((product) => (
                    variantIds.includes(product.id) ? { ...product, category: normalized } : product
                )));
                setSelectedProduct((current) => (
                    current && variantIds.includes(current.id) ? { ...current, category: normalized } : current
                ));
                setFieldSaveStateForProducts(variantIds, 'category', 'saved');
                window.setTimeout(() => {
                    setFieldSaveStates((prev) => {
                        const next = { ...prev };
                        variantIds.forEach((productId) => {
                            if (next[`${productId}:category`] === 'saved') {
                                next[`${productId}:category`] = 'idle';
                            }
                        });
                        return next;
                    });
                }, 1600);
            } catch (error) {
                console.error('Failed to apply category to master code group:', error);
                setFieldSaveStateForProducts(variantIds, 'category', 'error');
            }
            return;
        }

        const current = products.find((p) => p.id === selectedProduct.id);
        if (current && normalizeCategoryValue(current.category) === normalized) return;
        await applyProductUpdate(selectedProduct.id, { category: normalized });
    };

    const handleMasterCodeCommit = async (nextMasterCode: string) => {
        if (!selectedProduct) return;
        const normalized = String(nextMasterCode || '').trim().toUpperCase();
        const currentMasterCode = String(selectedProduct.master_code || '').trim().toUpperCase();
        if (currentMasterCode === normalized) return;

        const variantIds = Array.from(new Set(
            (masterVariants.length > 0 ? masterVariants : [selectedProduct])
                .map((product) => product.id)
                .filter(Boolean)
        ));
        if (variantIds.length <= 1) {
            await applyProductUpdate(selectedProduct.id, { master_code: normalized });
            return;
        }

        const confirmed = window.confirm(
            `Apply master code "${normalized || '(empty)'}" to ${variantIds.length} SKUs in this master group?\n\nThis will rename the master code on every child SKU in the group.`
        );
        if (!confirmed) return;

        setFieldSaveStateForProducts(variantIds, 'master_code', 'saving');
        try {
            await productsApi.bulkUpdate(variantIds, { master_code: normalized });
            setProducts((prods) => prods.map((product) => (
                variantIds.includes(product.id) ? { ...product, master_code: normalized } : product
            )));
            setMasterVariants((variants) => variants.map((product) => (
                variantIds.includes(product.id) ? { ...product, master_code: normalized } : product
            )));
            setSelectedProduct((current) => (
                current && variantIds.includes(current.id) ? { ...current, master_code: normalized } : current
            ));
            setFieldSaveStateForProducts(variantIds, 'master_code', 'saved');
            window.setTimeout(() => {
                setFieldSaveStates((prev) => {
                    const next = { ...prev };
                    variantIds.forEach((productId) => {
                        if (next[`${productId}:master_code`] === 'saved') {
                            next[`${productId}:master_code`] = 'idle';
                        }
                    });
                    return next;
                });
            }, 1600);
        } catch (error) {
            console.error('Failed to apply master code to master group:', error);
            setFieldSaveStateForProducts(variantIds, 'master_code', 'error');
        }
    };


    const buildBulkFieldState = (): BulkFieldState => {
        const initial: BulkFieldState = {};
        skuAttributeFields.forEach((field) => {
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
        const enabledFieldLabels: string[] = [];
        skuAttributeFields.forEach((field) => {
            const state = bulkEditFields[field.key as string];
            if (!state?.enabled) return;
            enabledFieldLabels.push(field.label);
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

        const confirmed = window.confirm(
            `Bulk update ${selectedIds.size} selected SKUs?\n\nFields: ${enabledFieldLabels.join(', ')}\n\nThis overwrites these SKU-level attributes only. Category is excluded from bulk edit.`
        );
        if (!confirmed) return;

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

    const displayedSelectedCount = displayedProducts.filter((product) => selectedIds.has(product.id)).length;
    const allSelected = displayedProducts.length > 0 && displayedSelectedCount === displayedProducts.length;
    const someSelected = displayedSelectedCount > 0 && displayedSelectedCount < displayedProducts.length;
    const selectedPersistedProduct = selectedProduct
        ? products.find((product) => product.id === selectedProduct.id) || selectedProduct
        : null;
    const attributeValueToString = (product: Product | null, key: keyof Product): string => {
        if (!product) return '';
        const value = product[key];
        return value === null || value === undefined ? '' : String(value);
    };
    const changedSkuAttributeFields = selectedPersistedProduct
        ? skuAttributeFields.filter((field) => (
            (attributeDrafts[field.key as string] ?? '') !== attributeValueToString(selectedPersistedProduct, field.key)
        ))
        : [];
    const hasSkuAttributeChanges = changedSkuAttributeFields.length > 0;
    const getFieldSaveState = (key: keyof Product): SaveState => {
        if (!selectedProduct) return 'idle';
        return fieldSaveStates[`${selectedProduct.id}:${String(key)}`] || 'idle';
    };

    const resetAttributeDrafts = () => {
        if (!selectedPersistedProduct) return;
        const nextDrafts: Record<string, string> = {};
        skuAttributeFields.forEach((field) => {
            nextDrafts[field.key as string] = attributeValueToString(selectedPersistedProduct, field.key);
        });
        setAttributeDrafts(nextDrafts);
    };

    const saveSkuAttributes = async () => {
        if (!selectedProduct || !selectedPersistedProduct || !hasSkuAttributeChanges) return;

        const updates: Partial<Product> = {};
        changedSkuAttributeFields.forEach((field) => {
            const rawValue = attributeDrafts[field.key as string] ?? '';
            const nextValue = field.type === 'number'
                ? (rawValue === '' ? null : Number(rawValue))
                : rawValue;
            (updates as Record<string, string | number | null>)[field.key as string] = nextValue;
        });

        await applyProductUpdate(selectedProduct.id, updates);
    };

    useEffect(() => {
        if (selectAllRef.current) {
            selectAllRef.current.indeterminate = someSelected;
        }
    }, [someSelected]);

    useEffect(() => {
        setShowSelectActionMenu(false);
    }, [currentPage, pageSize]);

    return (
        <div className="flex flex-col min-h-[calc(100vh-100px)] bg-white overflow-x-hidden">
            {/* Top Filter Bar */}
            <div className="border-b border-gray-200 bg-white">
                <div className="px-4 py-4 sm:px-6 space-y-4">
                    {selectedIds.size > 0 && (
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-end">
                            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-indigo-100 bg-indigo-50/70 px-3 py-2">
                                <span className="text-xs font-semibold text-indigo-700">{selectedIds.size} selected</span>
                                <button
                                    onClick={openBulkEdit}
                                    className="px-3 py-1.5 bg-indigo-600 text-white text-xs font-semibold rounded-lg hover:bg-indigo-700 transition-colors"
                                >
                                    Edit
                                </button>
                                <button
                                    onClick={handleBulkShow}
                                    className="px-3 py-1.5 bg-white border border-gray-200 text-gray-700 text-xs font-semibold rounded-lg hover:bg-gray-50 transition-colors"
                                >
                                    Show
                                </button>
                                <button
                                    onClick={handleBulkHide}
                                    className="px-3 py-1.5 bg-white border border-gray-200 text-red-600 text-xs font-semibold rounded-lg hover:bg-red-50 transition-colors"
                                >
                                    Hide
                                </button>
                                <button
                                    onClick={handleBulkDeleteSkus}
                                    className="px-3 py-1.5 bg-red-600 text-white text-xs font-semibold rounded-lg hover:bg-red-700 transition-colors"
                                >
                                    Delete
                                </button>
                            </div>
                        </div>
                    )}
                    {/* Primary Controls: Search + Global Filters */}
                    <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center flex-1 min-w-0">
                            {/* Search */}
                            <div className="relative flex-1 min-w-0">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                                    </svg>
                                </div>
                                <input
                                    type="text"
                                    placeholder="Search by SKU, Name, Master Code, or Klevu ID..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                    className="w-full pl-10 pr-20 py-2.5 text-sm border border-gray-200 rounded-xl focus:ring-2 focus:ring-primary-500 transition-all"
                                />
                                <button
                                    type="button"
                                    onClick={handleSearch}
                                    className="absolute right-1.5 top-1.5 px-3 py-1.5 text-xs font-semibold bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
                                >
                                    Search
                                </button>
                            </div>

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
                        </div>

                        {/* Right Actions */}
                        <div className="flex flex-wrap items-center gap-2">
                            <button
                                type="button"
                                onClick={() => setShowFilterDrawer(true)}
                                className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
                            >
                                <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4h18M6 12h12M10 20h4" />
                                </svg>
                                Filters
                                {totalFilterBadgeCount > 0 && (
                                    <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-primary-100 text-primary-700 text-[10px] font-bold">
                                        {totalFilterBadgeCount}
                                    </span>
                                )}
                            </button>
                            <button
                                onClick={resetFilters}
                                className="px-3 py-2 text-sm font-semibold rounded-lg border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                            >
                                Reset
                            </button>
                            <div className="relative">
                                <button
                                    onClick={() => setShowColumnMenu((prev) => !prev)}
                                    className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 transition-colors"
                                    title="Customize Columns"
                                >
                                    <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" /></svg>
                                    Columns
                                </button>
                                {showColumnMenu && (
                                    <div className="absolute right-0 mt-2 w-64 bg-white border border-gray-200 rounded-lg shadow-xl p-3 z-[130] animate-in fade-in zoom-in-95 origin-top-right max-h-[400px] overflow-y-auto custom-scrollbar">
                                        <div className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Standard Columns</div>
                                        <div className="space-y-2 mb-4">
                                            {standardColumns.map((col) => (
                                                <label key={col.key} className="flex items-center gap-2 text-sm text-gray-700 hover:text-gray-900 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={effectiveVisibleColumns[col.key]}
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
                                                    {autoVisibleColumns[col.key] && (
                                                        <span className="px-1.5 py-0.5 rounded bg-primary-100 text-primary-700 text-[9px] font-bold uppercase tracking-wider">
                                                            Auto
                                                        </span>
                                                    )}
                                                    <input
                                                        type="checkbox"
                                                        checked={effectiveVisibleColumns[col.key]}
                                                        onChange={() => toggleColumn(col.key)}
                                                        disabled={Boolean(autoVisibleColumns[col.key])}
                                                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
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

                    {facetLoading && <div className="text-xs text-gray-400 italic">Refreshing filter counts...</div>}
                </div>

                {/* Active Filter Chips */}
                {(activeFilterValueCount > 0 || minPrice || maxPrice) && (
                    <div className="px-4 sm:px-6 pb-4 flex flex-wrap gap-2 items-center border-t border-gray-100 pt-3">
                        <span className="text-xs text-gray-400">Active:</span>
                        {Object.entries(activeFilters).map(([key, values]) => (
                            values.map(val => (
                                <button
                                    key={`${key}-${val}`}
                                    onClick={() => {
                                        const newVals = values.filter(v => v !== val);
                                        setPendingFilters(prev => withFilterValues(prev, key, newVals));
                                        setActiveFilters(prev => withFilterValues(prev, key, newVals));
                                    }}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary-50 text-primary-700 text-xs font-medium border border-primary-100 hover:bg-primary-100 transition-colors"
                                >
                                    <span className="opacity-60 uppercase tracking-tighter text-[9px]">{formatFilterLabel(key)}:</span>
                                    <span className="max-w-[180px] truncate">{val}</span>
                                    <svg className="w-3 h-3 opacity-60" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                    </svg>
                                </button>
                            ))
                        ))}
                        {minPrice && (
                            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-gray-100 text-gray-700 text-xs font-medium border border-gray-200">
                                Min ${minPrice}
                            </span>
                        )}
                        {maxPrice && (
                            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-gray-100 text-gray-700 text-xs font-medium border border-gray-200">
                                Max ${maxPrice}
                            </span>
                        )}
                        <button
                            onClick={() => {
                                setPendingFilters({});
                                setActiveFilters({});
                                setMinPrice('');
                                setMaxPrice('');
                                setCurrentPage(1);
                                void loadProducts(1, pageSize);
                                loadFacets();
                            }}
                            className="text-xs text-red-500 hover:text-red-700 underline decoration-red-200 underline-offset-2 ml-2"
                        >
                            Clear all
                        </button>
                    </div>
                )}
            </div>

            {/* Main Content: Product List */}
            <div className={`relative flex flex-col min-w-0 transition-all duration-300 ${selectedProduct ? 'pr-[450px]' : 'pr-0'}`}>
                <div className="bg-gray-50/70 p-4 sm:p-6">

                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                        <div className="flex-shrink-0 border-b border-gray-200 bg-white">
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

                        <div className="hidden md:block overflow-x-hidden">
                            <table className="w-full divide-y divide-gray-200 table-fixed">
                            <thead className="bg-gray-100">
                                <tr>
                                    <th className="w-12 px-4 py-3 text-left bg-gray-100">
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
                                                        disabled={displayedProducts.length === 0 || allSelected}
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
                                    {allColumns.map(col => effectiveVisibleColumns[col.key] && (
                                        <th key={col.key} className={`${col.width} px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider whitespace-normal break-words leading-tight bg-gray-100`}>
                                            {col.label}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100">
                                {displayedProducts.map((product) => {
                                    const qualityFlags = getProductQualityFlags(product);
                                    return (
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
                                            if (!effectiveVisibleColumns[col.key]) return null;

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
                                                    <td key={col.key} className="px-4 py-3 text-sm font-mono text-gray-500 uppercase whitespace-normal break-all">
                                                        {product.master_code ? product.master_code : <span className="text-gray-300">—</span>}
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'description') {
                                                return (
                                                    <td key={col.key} className="Description px-4 py-3">
                                                        <div className="text-xs text-gray-600 line-clamp-2 break-words leading-snug" title={product.description || ''}>
                                                            {product.description || <span className="text-gray-300 italic">No description</span>}
                                                        </div>
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'klevu_id') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3 text-xs font-mono text-gray-600 whitespace-normal break-all">
                                                        {product.klevu_id ? product.klevu_id : <span className="text-gray-300">N/A</span>}
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'object_id') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3 text-xs font-mono text-gray-600 whitespace-normal break-all">
                                                        {product.object_id ? product.object_id : <span className="text-gray-300">N/A</span>}
                                                    </td>
                                                );
                                            }
                                            if (col.key === 'sku') {
                                                return (
                                                    <td key={col.key} className="px-4 py-3">
                                                        <div className="min-w-0 space-y-1">
                                                            <div className="text-sm font-mono text-gray-700 uppercase font-bold truncate" title={product.sku}>
                                                                {product.sku}
                                                            </div>
                                                            <div className="text-[10px] text-gray-400 leading-tight space-y-0.5">
                                                                {product.master_code && (
                                                                    <div className="truncate" title={product.master_code}>MC: {product.master_code}</div>
                                                                )}
                                                                {product.klevu_id && (
                                                                    <div className="truncate" title={product.klevu_id}>Klevu: {product.klevu_id}</div>
                                                                )}
                                                                {product.object_id && (
                                                                    <div className="truncate" title={product.object_id}>Object: {product.object_id}</div>
                                                                )}
                                                            </div>
                                                        </div>
                                                    </td>
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
                                                        <div className="flex items-center justify-center gap-1.5">
                                                            <div className={`w-2 h-2 rounded-full ${product.visibility ? (product.in_stock ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-yellow-500') : 'bg-gray-300'}`} />
                                                            {qualityFlags.length > 0 && (
                                                                <span
                                                                    className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-100 px-1 text-[10px] font-black text-amber-700"
                                                                    title={qualityFlags.map((flag) => flag.label).join(', ')}
                                                                >
                                                                    {qualityFlags.length}
                                                                </span>
                                                            )}
                                                        </div>
                                                    </td>
                                                );
                                            }

                                            if (col.key === 'category') {
                                                const tokens = parseCategoryTokens(product.category);
                                                const visibleTokens = tokens.slice(0, 3);
                                                const hiddenCount = Math.max(tokens.length - visibleTokens.length, 0);
                                                return (
                                                    <td key={col.key} className="px-4 py-3">
                                                        {tokens.length > 0 ? (
                                                            <div className="space-y-1.5" title={tokens.join(', ')}>
                                                                <div className="flex flex-wrap gap-1.5">
                                                                    {visibleTokens.map((token) => (
                                                                        <span
                                                                            key={`${product.id}-${token}`}
                                                                            className="inline-flex items-center rounded-md border border-indigo-100 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700"
                                                                        >
                                                                            {token}
                                                                        </span>
                                                                    ))}
                                                                    {hiddenCount > 0 && (
                                                                        <span className="inline-flex items-center rounded-md border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[10px] font-semibold text-gray-600">
                                                                            +{hiddenCount} more
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            </div>
                                                        ) : (
                                                            <span className="text-gray-300">—</span>
                                                        )}
                                                    </td>
                                                );
                                            }

                                            // Default Attribute Rendering
                                            const val = product[col.key as keyof Product];
                                            return (
                                                <td key={col.key} className="px-4 py-3 text-sm text-gray-600 whitespace-normal break-words leading-snug">
                                                    {val ? String(val) : <span className="text-gray-300">—</span>}
                                                </td>
                                            );
                                        })}
                                    </tr>
                                    );
                                })}
                            </tbody>
                            </table>
                        </div>

                        <div className="md:hidden divide-y divide-gray-100">
                            {displayedProducts.map((product) => {
                                const qualityFlags = getProductQualityFlags(product);
                                return (
                                <article
                                    key={product.id}
                                    onClick={() => setSelectedProduct(product)}
                                    className={`p-4 cursor-pointer transition-colors ${selectedProduct?.id === product.id ? 'bg-primary-50' : 'bg-white'} ${!product.visibility ? 'opacity-70' : ''}`}
                                >
                                    <div className="flex items-start gap-3 min-w-0">
                                        <div className="pt-1" onClick={(e) => e.stopPropagation()}>
                                            <input
                                                type="checkbox"
                                                checked={selectedIds.has(product.id)}
                                                onChange={(e) => toggleSelect(product.id, e as any)}
                                                className="rounded border-gray-300 text-primary-600"
                                            />
                                        </div>
                                        <div className="w-12 h-12 bg-gray-100 rounded-lg overflow-hidden border border-gray-100 flex-shrink-0">
                                            {product.image_url ? (
                                                <img src={product.image_url} alt="" className="w-full h-full object-cover" />
                                            ) : (
                                                <div className="w-full h-full flex items-center justify-center text-gray-300">
                                                    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                                    </svg>
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-start justify-between gap-3">
                                                <div className="min-w-0">
                                                    <div className="text-sm font-mono font-bold text-gray-800 uppercase truncate">{product.sku}</div>
                                                    <div className="text-[10px] text-gray-400 truncate">{product.master_code || 'No master code'}</div>
                                                </div>
                                                <div className="text-sm font-bold text-gray-900">${(product.price || 0).toFixed(2)}</div>
                                            </div>
                                            <p className="mt-1 text-xs text-gray-600 line-clamp-2 break-words" title={product.description || ''}>
                                                {product.description || 'No description'}
                                            </p>
                                            <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500">
                                                <span className="truncate max-w-[60%]">{product.klevu_id || product.object_id || 'No external ID'}</span>
                                                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-semibold ${qualityFlags.length > 0 ? 'bg-amber-100 text-amber-700' : product.visibility ? (product.in_stock ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700') : 'bg-gray-100 text-gray-600'}`}>
                                                    <span className={`w-1.5 h-1.5 rounded-full ${product.visibility ? (product.in_stock ? 'bg-green-500' : 'bg-yellow-500') : 'bg-gray-400'}`}></span>
                                                    {qualityFlags.length > 0 ? `${qualityFlags.length} flags` : product.visibility ? (product.in_stock ? 'Visible' : 'Low stock') : 'Hidden'}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </article>
                                );
                            })}
                        </div>

                        {!loading && products.length > 0 && displayedProducts.length === 0 && (
                            <div className="flex flex-col items-center justify-center py-20 text-center">
                                <div className="mb-3 rounded-full bg-green-50 px-3 py-1 text-xs font-bold text-green-700">No matching records</div>
                                <p className="text-sm text-gray-500">Try a different search or change the active filters.</p>
                            </div>
                        )}

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
                                        <h3 className="text-xl font-bold text-gray-900 leading-tight mb-1 font-mono uppercase">{selectedProduct.sku}</h3>
                                        <p className="text-sm text-gray-500 line-clamp-2 break-words">{selectedProduct.name}</p>
                                        <div className="text-2xl font-black text-primary-600">${selectedProduct.price.toFixed(2)}</div>
                                        <div className={`mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${selectedProduct.in_stock ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                                            <span className={`w-1.5 h-1.5 rounded-full ${selectedProduct.in_stock ? 'bg-green-600' : 'bg-red-600'}`}></span>
                                            {selectedProduct.in_stock ? 'In Stock' : 'Out of Stock'}
                                        </div>
                                    </div>
                                </div>

                                {/* Quick Actions */}
                                <section className="space-y-3">
                                    <div className="grid grid-cols-1 gap-3">
                                    <button
                                        onClick={() => handleToggleVisibility(selectedProduct)}
                                        className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl border font-bold text-xs uppercase tracking-wide transition-all ${selectedProduct.visibility ? 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50' : 'bg-yellow-50 border-yellow-200 text-yellow-700'}`}
                                    >
                                        <span className={`w-2 h-2 rounded-full ${selectedProduct.visibility ? 'bg-green-500' : 'bg-yellow-500'}`}></span>
                                        {selectedProduct.visibility ? 'Visible' : 'Hidden'}
                                    </button>
                                    </div>
                                </section>

                                <section className="rounded-2xl border border-gray-200 bg-white shadow-sm">
                                    <div className="grid grid-cols-3 border-b border-gray-200 bg-gray-50/70 p-1">
                                        {[
                                            { key: 'attributes', label: 'Attributes' },
                                            { key: 'quality', label: 'Quality' },
                                            { key: 'description', label: 'Description' },
                                        ].map((tab) => (
                                            <button
                                                key={tab.key}
                                                type="button"
                                                onClick={() => setDetailTab(tab.key as DetailTab)}
                                                className={`rounded-xl px-3 py-2 text-xs font-black uppercase tracking-wide transition-all ${detailTab === tab.key
                                                    ? 'bg-white text-gray-900 shadow-sm'
                                                    : 'text-gray-500 hover:text-gray-800'
                                                    }`}
                                            >
                                                {tab.label}
                                            </button>
                                        ))}
                                    </div>

                                    {detailTab === 'attributes' && (
                                        <div className="space-y-5 p-4">
                                            <div className="rounded-xl border border-gray-100 bg-gray-50 p-4">
                                                <div className="mb-2 flex items-center justify-between">
                                                    <label className="text-sm font-semibold text-gray-700">Master Code</label>
                                                    <SaveStateBadge state={getFieldSaveState('master_code')} />
                                                </div>
                                                <input
                                                    type="text"
                                                    placeholder="Enter master code..."
                                                    value={selectedProduct.master_code || ''}
                                                    onChange={(e) => handleFieldChange('master_code', e.target.value)}
                                                    onBlur={() => handleFieldBlur('master_code')}
                                                    className="w-full px-3 py-2 text-sm border border-gray-200 bg-white rounded-lg focus:ring-2 focus:ring-primary-500 font-mono uppercase"
                                                />
                                                <p className="text-[10px] text-gray-400 mt-2">Group multiple SKUs under one master collection.</p>
                                            </div>

                                            <section className="space-y-3 rounded-2xl border border-indigo-100 bg-indigo-50/30 p-4">
                                                <div>
                                                    <h4 className="text-xs font-black text-indigo-700 uppercase tracking-widest">Group Category</h4>
                                                    <p className="mt-1 text-xs text-indigo-700/80">Category applies to every SKU under the current master code.</p>
                                                </div>
                                                <CategoryAttributeEditor
                                                    label="Category"
                                                    value={selectedProduct.category}
                                                    options={categoryOptions}
                                                    saveState={getFieldSaveState('category')}
                                                    masterVariantsLoading={masterVariantsLoading}
                                                    onCommit={(value) => handleCategoryCommit(value, 'master')}
                                                />
                                            </section>

                                            <section className="space-y-3 rounded-2xl border border-gray-200 bg-white p-4">
                                                <div className="flex items-start justify-between gap-3">
                                                    <div>
                                                        <h4 className="text-xs font-black text-gray-500 uppercase tracking-widest">SKU Attributes</h4>
                                                        <p className="mt-1 text-xs text-gray-500">These fields update only the selected SKU.</p>
                                                    </div>
                                                    {hasSkuAttributeChanges && (
                                                        <span className="rounded-full border border-amber-100 bg-amber-50 px-2 py-1 text-[10px] font-bold text-amber-700">
                                                            {changedSkuAttributeFields.length} unsaved
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="grid grid-cols-2 gap-x-4 gap-y-4">
                                                    {skuAttributeFields.map((field) => (
                                                        <EditableAttribute
                                                            key={field.key}
                                                            label={field.label}
                                                            type={field.type}
                                                            value={attributeDrafts[field.key as string] ?? ''}
                                                            persistedValue={attributeValueToString(selectedPersistedProduct, field.key)}
                                                            saveState={getFieldSaveState(field.key)}
                                                            onChange={(value) => setAttributeDrafts((prev) => ({
                                                                ...prev,
                                                                [field.key as string]: value,
                                                            }))}
                                                        />
                                                    ))}
                                                </div>
                                                <div className="flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
                                                    <p className="text-[10px] text-gray-400">Save writes all changed SKU attributes at once.</p>
                                                    <div className="flex items-center gap-2">
                                                        <button
                                                            type="button"
                                                            onClick={resetAttributeDrafts}
                                                            disabled={!hasSkuAttributeChanges}
                                                            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                                                        >
                                                            Reset
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={saveSkuAttributes}
                                                            disabled={!hasSkuAttributeChanges}
                                                            className="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
                                                        >
                                                            Save SKU attributes
                                                        </button>
                                                    </div>
                                                </div>
                                            </section>
                                        </div>
                                    )}

                                    {detailTab === 'quality' && (
                                        <div className="space-y-4 p-4">
                                            <div className="grid grid-cols-3 gap-2">
                                                <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                                                    <div className="text-[10px] font-black uppercase tracking-widest text-gray-400">Categories</div>
                                                    <div className="mt-1 text-xl font-black text-gray-900">{parseCategoryTokens(selectedProduct.category).length}</div>
                                                </div>
                                                <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                                                    <div className="text-[10px] font-black uppercase tracking-widest text-gray-400">Visible</div>
                                                    <div className="mt-1 text-sm font-black text-gray-900">{selectedProduct.visibility ? 'Yes' : 'No'}</div>
                                                </div>
                                                <div className="rounded-xl border border-gray-100 bg-gray-50 p-3">
                                                    <div className="text-[10px] font-black uppercase tracking-widest text-gray-400">Stock</div>
                                                    <div className="mt-1 text-sm font-black text-gray-900">{selectedProduct.in_stock ? 'In' : 'Out'}</div>
                                                </div>
                                            </div>

                                            <div className="rounded-xl border border-red-100 bg-red-50 p-4">
                                                <div className="text-sm font-black text-red-800">Danger zone</div>
                                                <p className="mt-1 text-xs text-red-700">Delete only when this SKU should be removed from the tuning catalog.</p>
                                                <button
                                                    onClick={() => handleHardDeleteBySku(selectedProduct)}
                                                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-red-200 bg-white px-4 py-3 text-xs font-bold uppercase tracking-wide text-red-700 transition-all hover:bg-red-100"
                                                >
                                                    Delete SKU
                                                </button>
                                            </div>
                                        </div>
                                    )}

                                    {detailTab === 'description' && (
                                        <div className="space-y-3 p-4">
                                            <div className="flex items-center justify-between">
                                                <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest">Description</h4>
                                                <SaveStateBadge state={getFieldSaveState('description')} />
                                            </div>
                                            <textarea
                                                value={selectedProduct.description ?? ''}
                                                onChange={(e) => handleFieldChange('description', e.target.value)}
                                                onBlur={() => handleFieldBlur('description')}
                                                placeholder="Add a description for this product..."
                                                rows={10}
                                                className="w-full text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-xl p-4 border border-gray-100 focus:outline-none focus:ring-2 focus:ring-primary-500"
                                            />
                                        </div>
                                    )}
                                </section>
                            </div>
                        </div>
                    </div>
                )}
            {showFilterDrawer && (
                <>
                    <button
                        type="button"
                        onClick={() => setShowFilterDrawer(false)}
                        className="fixed inset-0 bg-gray-900/30 z-[140]"
                        aria-label="Close filters"
                    />
                    <aside className="fixed inset-y-0 left-0 w-full max-w-[380px] bg-white border-r border-gray-200 shadow-2xl z-[150] flex flex-col">
                        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
                            <div>
                                <h2 className="text-base font-semibold text-gray-900">Filters</h2>
                                <p className="text-xs text-gray-500">Live filtering with stable option counts.</p>
                            </div>
                            <button
                                onClick={() => setShowFilterDrawer(false)}
                                className="p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
                                aria-label="Close filters panel"
                            >
                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto overscroll-contain touch-pan-y p-4 space-y-4">
                            <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Category Match</div>
                                <div className="inline-flex bg-white p-1 rounded-lg border border-gray-200">
                                    {[
                                        { key: 'any', label: 'Any' },
                                        { key: 'all', label: 'All' },
                                    ].map((mode) => (
                                        <button
                                            key={mode.key}
                                            onClick={() => setCategoryMode(mode.key as 'any' | 'all')}
                                            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${categoryMode === mode.key
                                                ? 'bg-gray-900 text-white'
                                                : 'text-gray-600 hover:text-gray-800'
                                                }`}
                                        >
                                            {mode.label}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            <div className="rounded-xl border border-gray-200 bg-white p-3">
                                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">Key Filters</div>
                                <div className="flex flex-wrap gap-2">
                                    {quickFilterKeys.map((key) => renderFilterDropdown(key))}
                                </div>
                            </div>

                            <div className="rounded-xl border border-gray-200 bg-white p-3 space-y-2">
                                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Price Range</div>
                                <div className="grid grid-cols-2 gap-2">
                                    <input
                                        type="number"
                                        placeholder="Min"
                                        value={minPrice}
                                        onChange={(e) => setMinPrice(e.target.value)}
                                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500"
                                    />
                                    <input
                                        type="number"
                                        placeholder="Max"
                                        value={maxPrice}
                                        onChange={(e) => setMaxPrice(e.target.value)}
                                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500"
                                    />
                                </div>
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={handleSearch}
                                        className="px-3 py-1.5 text-xs font-semibold bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
                                    >
                                        Apply Price
                                    </button>
                                    {(minPrice || maxPrice) && (
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setMinPrice('');
                                                setMaxPrice('');
                                                setCurrentPage(1);
                                                void loadProducts(1, pageSize);
                                                loadFacets();
                                            }}
                                            className="px-3 py-1.5 text-xs font-semibold text-gray-600 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
                                        >
                                            Clear Price
                                        </button>
                                    )}
                                </div>
                            </div>

                            {groupedAdvancedFilters.length > 0 && (
                                <div className="rounded-xl border border-gray-200 bg-white p-3">
                                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">
                                        Advanced Filters {advancedActiveFilterCount > 0 ? `(${advancedActiveFilterCount} active)` : ''}
                                    </div>
                                    <div className="space-y-3">
                                        {groupedAdvancedFilters.map((group) => (
                                            <div key={group.title} className="rounded-lg border border-gray-100 bg-gray-50 p-2.5">
                                                <div className="text-[10px] font-bold text-gray-500 uppercase tracking-[0.12em] mb-2">{group.title}</div>
                                                <div className="flex flex-wrap gap-2">
                                                    {group.keys.map((key) => renderFilterDropdown(key))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                        <div className="px-4 py-3 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
                            <button
                                type="button"
                                onClick={() => {
                                    setPendingFilters({});
                                    setActiveFilters({});
                                    setMinPrice('');
                                    setMaxPrice('');
                                    setCurrentPage(1);
                                    void loadProducts(1, pageSize);
                                    loadFacets();
                                }}
                                className="text-xs font-semibold text-red-600 hover:text-red-700"
                            >
                                Clear all filters
                            </button>
                            <button
                                type="button"
                                onClick={() => setShowFilterDrawer(false)}
                                className="px-3 py-1.5 text-xs font-semibold bg-gray-900 text-white rounded-lg hover:bg-gray-800 transition-colors"
                            >
                                Done
                            </button>
                        </div>
                    </aside>
                </>
            )}
            {/* Bulk Edit Modal */}
            {bulkEditOpen && (
                <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
                    <div className="w-full max-w-3xl bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
                            <div>
                                <h3 className="text-lg font-semibold text-gray-900">Bulk Edit SKU Attributes</h3>
                                <p className="text-xs text-gray-500">Update SKU-level attributes for {selectedIds.size} selected SKUs</p>
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
                            <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                                Category is excluded here because category updates apply through the master-code group editor.
                            </div>
                            {skuAttributeFields.map((field) => {
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
                                <p>Only checked SKU-level fields will be overwritten. A confirmation appears before saving.</p>
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
const SaveStateBadge: React.FC<{ state?: SaveState }> = ({ state = 'idle' }) => {
    if (state === 'idle') return null;
    const className = state === 'saving'
        ? 'bg-blue-50 text-blue-700 border-blue-100'
        : state === 'saved'
            ? 'bg-green-50 text-green-700 border-green-100'
            : 'bg-red-50 text-red-700 border-red-100';
    return (
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${className}`}>
            {saveStateLabel[state]}
        </span>
    );
};

const EditableAttribute: React.FC<{
    label: string;
    value: string;
    persistedValue: string;
    type?: 'text' | 'number';
    saveState?: SaveState;
    onChange: (value: string) => void;
}> = ({ label, value, persistedValue, type = 'text', saveState = 'idle', onChange }) => {
    const hasChanges = value !== persistedValue;

    return (
        <div className={`flex flex-col gap-1 rounded-lg border p-2 ${hasChanges ? 'border-amber-200 bg-amber-50/50' : 'border-gray-100 bg-white'}`}>
            <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tight">{label}</span>
                <div className="flex items-center gap-1.5">
                    {hasChanges && (
                        <span className="rounded-full border border-amber-100 bg-amber-50 px-1.5 py-0.5 text-[9px] font-bold text-amber-700">
                            Unsaved
                        </span>
                    )}
                    <SaveStateBadge state={saveState} />
                </div>
            </div>
            <input
                type={type}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder="N/A"
                className="text-sm font-semibold text-gray-700 bg-white border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary-500"
            />
        </div>
    );
};

const CategoryAttributeEditor: React.FC<{
    label: string;
    value?: string | null;
    options?: string[];
    saveState?: SaveState;
    masterVariantsLoading?: boolean;
    onCommit: (value: string) => void;
}> = ({
    label,
    value,
    options = [],
    saveState = 'idle',
    masterVariantsLoading = false,
    onCommit,
}) => {
    const normalizedValue = normalizeCategoryValue(value);
    const tokens = useMemo(() => parseCategoryTokens(normalizedValue), [normalizedValue]);
    const [draftTokens, setDraftTokens] = useState<string[]>(tokens);
    const [newToken, setNewToken] = useState('');
    const [composerOpen, setComposerOpen] = useState(false);
    const composerInputRef = useRef<HTMLInputElement | null>(null);
    const draftValue = normalizeCategoryValue(draftTokens.join(CATEGORY_DELIMITER));
    const hasChanges = draftValue !== normalizedValue;
    const normalizedDraftKeys = useMemo(
        () => new Set(draftTokens.map((token) => token.toLowerCase())),
        [draftTokens]
    );
    const suggestions = useMemo(() => {
        const query = newToken.trim().toLowerCase();
        if (!query) return [];
        return options
            .filter((option) => {
                const key = option.toLowerCase();
                return key.includes(query) && !normalizedDraftKeys.has(key);
            })
            .slice(0, 6);
    }, [newToken, normalizedDraftKeys, options]);

    useEffect(() => {
        setDraftTokens(tokens);
        setNewToken('');
        setComposerOpen(false);
    }, [normalizedValue]);

    useEffect(() => {
        if (composerOpen) {
            window.setTimeout(() => composerInputRef.current?.focus(), 0);
        }
    }, [composerOpen]);

    const commitTokens = (nextTokens: string[]) => {
        onCommit(nextTokens.join(CATEGORY_DELIMITER));
    };

    const removeToken = (index: number) => {
        setDraftTokens((current) => current.filter((_, tokenIndex) => tokenIndex !== index));
    };

    const addToken = (rawCandidate = newToken) => {
        const candidate = rawCandidate.trim();
        if (!candidate) return;
        const nextTokens = parseCategoryTokens([...draftTokens, candidate].join(CATEGORY_DELIMITER));
        setDraftTokens(nextTokens);
        setNewToken('');
        setComposerOpen(false);
    };

    return (
        <div className="flex flex-col gap-2 rounded-xl border border-indigo-100 bg-indigo-50/30 p-3">
            <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-tight">{label}</span>
                <div className="flex items-center gap-2">
                    <SaveStateBadge state={saveState} />
                    {hasChanges && (
                        <span className="rounded-full border border-amber-100 bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700">
                            Unsaved
                        </span>
                    )}
                    <span className="text-[10px] font-semibold text-indigo-600">{draftTokens.length} value{draftTokens.length === 1 ? '' : 's'}</span>
                </div>
            </div>

            <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-1.5">
                    {draftTokens.length === 0 && (
                        <span className="rounded-full border border-dashed border-gray-300 bg-white px-2.5 py-1 text-xs text-gray-400">
                            No category values yet
                        </span>
                    )}
                    {draftTokens.map((token, index) => (
                        <button
                            key={`${token}-${index}`}
                            type="button"
                            onClick={() => removeToken(index)}
                            className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-white px-2.5 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-50"
                            title="Click to remove"
                        >
                            <span className="max-w-[220px] truncate">{token}</span>
                            <span className="text-indigo-400">x</span>
                        </button>
                    ))}
                    {!composerOpen ? (
                        <button
                            type="button"
                            onClick={() => setComposerOpen(true)}
                            className="inline-flex items-center gap-1 rounded-full border border-dashed border-gray-300 bg-white px-2.5 py-1 text-xs font-semibold text-gray-500 transition-colors hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
                        >
                            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-current/10 text-[12px] leading-none">+</span>
                            Add category
                        </button>
                    ) : (
                        <div className="inline-flex items-center gap-1 rounded-full border border-indigo-300 bg-indigo-50 px-1.5 py-1 shadow-sm">
                            <input
                                ref={composerInputRef}
                                type="text"
                                value={newToken}
                                onChange={(event) => setNewToken(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                        event.preventDefault();
                                        addToken();
                                    }
                                    if (event.key === 'Escape') {
                                        setComposerOpen(false);
                                        setNewToken('');
                                    }
                                }}
                                placeholder="Search or add category"
                                className="min-w-[170px] max-w-[260px] border-0 bg-transparent px-2 py-1 text-xs font-medium text-gray-700 placeholder:text-gray-400 focus:outline-none"
                            />
                            <button
                                type="button"
                                onClick={() => addToken()}
                                disabled={!newToken.trim()}
                                className="inline-flex items-center rounded-full bg-primary-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                Add
                            </button>
                        </div>
                    )}
                </div>
                {composerOpen && suggestions.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                        {suggestions.map((suggestion) => (
                            <button
                                key={suggestion}
                                type="button"
                                onClick={() => addToken(suggestion)}
                                className="rounded-full border border-gray-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-gray-600 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
                            >
                                {suggestion}
                            </button>
                        ))}
                    </div>
                )}
                <div className="space-y-3 border-t border-indigo-100 pt-3">
                    <div className="flex items-center justify-end gap-2">
                        <button
                            type="button"
                            onClick={() => {
                                setDraftTokens(tokens);
                                setNewToken('');
                                setComposerOpen(false);
                            }}
                            disabled={!hasChanges}
                            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            Reset
                        </button>
                        <button
                            type="button"
                            onClick={() => commitTokens(draftTokens)}
                            disabled={!hasChanges || saveState === 'saving' || masterVariantsLoading}
                            className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-3 text-left transition-all hover:border-indigo-300 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            <span className="shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white">Update category</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

const FilterDropdown: React.FC<{
    label: string,
    options: { value: string; count: number }[],
    selected: string[],
    onChange: (values: string[]) => void
}> = ({ label, options, selected, onChange }) => {
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
                    className="fixed w-80 max-w-[calc(100vw-2rem)] bg-white border border-gray-200 rounded-xl shadow-xl z-[9999] animate-in fade-in zoom-in-95 origin-top-left flex flex-col max-h-[400px]"
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
                            const isDisabled = opt.count === 0 && !isSelected;
                            return (
                                <label
                                    key={opt.value}
                                    className={`flex items-start gap-2 p-2 rounded-lg transition-colors ${isDisabled
                                        ? 'cursor-not-allowed opacity-45 bg-gray-50'
                                        : 'cursor-pointer hover:bg-gray-50'
                                        }`}
                                >
                                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${isSelected ? 'bg-primary-600 border-primary-600' : 'border-gray-300 bg-white'}`}>
                                        {isSelected && <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>}
                                    </div>
                                    <input
                                        type="checkbox"
                                        className="hidden"
                                        checked={isSelected}
                                        disabled={isDisabled}
                                        onChange={() => {
                                            if (isDisabled) return;
                                            const newSet = new Set(selected);
                                            if (newSet.has(opt.value)) newSet.delete(opt.value);
                                            else newSet.add(opt.value);
                                            onChange(Array.from(newSet));
                                        }}
                                    />
                                    <span
                                        title={opt.value}
                                        className={`text-xs flex-1 min-w-0 whitespace-normal break-words leading-snug ${isSelected ? 'font-medium text-gray-900' : 'text-gray-600'}`}
                                    >
                                        {opt.value}
                                    </span>
                                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full shrink-0 mt-0.5 ${isDisabled ? 'text-gray-500 bg-gray-200' : 'text-gray-400 bg-gray-100'}`}>{opt.count}</span>
                                </label>
                            );
                        })}
                    </div>
                    <div className="p-2 border-t border-gray-100 bg-gray-50 rounded-b-xl">
                        <button
                            onClick={() => setIsOpen(false)}
                            className="w-full py-2 bg-primary-600 text-white text-xs font-semibold rounded-lg hover:bg-primary-700 transition-colors shadow-sm"
                        >
                            Done
                        </button>
                    </div>
                </div>,
                document.body
            )}
        </>
    );
};

