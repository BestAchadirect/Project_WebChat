import React, { useState, useEffect } from 'react';
import { productsApi, Product } from '../../api/training';

export const ProductTuningPage: React.FC = () => {
    const [products, setProducts] = useState<Product[]>([]);
    const [loading, setLoading] = useState(true);
    const [total, setTotal] = useState(0);
    const [offset, setOffset] = useState(0);
    const LIMIT = 50;

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

    // Filters
    const [filterVisibility, setFilterVisibility] = useState<'all' | 'visible' | 'hidden'>('all');
    const [filterFeatured, setFilterFeatured] = useState<'all' | 'featured' | 'normal'>('all');
    const [filterMaterial, setFilterMaterial] = useState('');
    const [filterJewelryType, setFilterJewelryType] = useState('');
    const [minPrice, setMinPrice] = useState('');
    const [maxPrice, setMaxPrice] = useState('');

    useEffect(() => {
        setOffset(0);
        loadProducts(0);
    }, [filterVisibility, filterFeatured, filterMaterial, filterJewelryType]);

    const loadProducts = async (currentOffset: number) => {
        try {
            setLoading(true);
            const params: any = {
                limit: LIMIT,
                offset: currentOffset
            };
            if (filterVisibility === 'visible') params.visibility = true;
            if (filterVisibility === 'hidden') params.visibility = false;
            if (filterFeatured === 'featured') params.is_featured = true;
            if (filterFeatured === 'normal') params.is_featured = false;
            if (filterMaterial) params.material = filterMaterial;
            if (filterJewelryType) params.jewelry_type = filterJewelryType;
            if (minPrice) params.min_price = parseFloat(minPrice);
            if (maxPrice) params.max_price = parseFloat(maxPrice);
            if (searchQuery) params.search = searchQuery;

            const result = await productsApi.listProducts(params);
            if (currentOffset === 0) {
                setProducts(result.items);
            } else {
                setProducts(prev => [...prev, ...result.items]);
            }
            setTotal(result.total);
        } catch (error) {
            console.error('Failed to load products:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleLoadMore = () => {
        const nextOffset = offset + LIMIT;
        setOffset(nextOffset);
        loadProducts(nextOffset);
    };

    const handleSearch = () => {
        setOffset(0);
        loadProducts(0);
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

    const handleUpdatePriority = async (product: Product, priority: number) => {
        try {
            await productsApi.updateProduct(product.id, { priority });
            setProducts(prods => prods.map(p => p.id === product.id ? { ...p, priority } : p));
            if (selectedProduct?.id === product.id) {
                setSelectedProduct({ ...selectedProduct, priority });
            }
        } catch (error) {
            console.error('Failed to update priority:', error);
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

    const toggleSelectAll = () => {
        if (selectedIds.size === products.length) {
            setSelectedIds(new Set());
        } else {
            setSelectedIds(new Set(products.map(p => p.id)));
        }
    };

    const resetFilters = () => {
        setFilterVisibility('all');
        setFilterFeatured('all');
        setFilterMaterial('');
        setFilterJewelryType('');
        setMinPrice('');
        setMaxPrice('');
        setSearchQuery('');
        setOffset(0);
        loadProducts(0);
    };

    return (
        <div className="flex h-[calc(100vh-120px)] overflow-hidden gap-6">
            {/* Sidebar Filters */}
            <div className="w-64 flex-shrink-0 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col overflow-hidden">
                <div className="p-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
                    <h2 className="font-semibold text-gray-900">Filters</h2>
                    <button onClick={resetFilters} className="text-xs text-primary-600 hover:text-primary-700 font-medium">Reset</button>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-6">
                    {/* Search */}
                    <div>
                        <label className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 block">Search</label>
                        <input
                            type="text"
                            placeholder="SKU, Name or Master Code..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500"
                        />
                    </div>

                    {/* Visibility */}
                    <div>
                        <label className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 block">Visibility</label>
                        <div className="space-y-1">
                            {['all', 'visible', 'hidden'].map((v) => (
                                <button
                                    key={v}
                                    onClick={() => setFilterVisibility(v as any)}
                                    className={`w-full text-left px-3 py-1.5 rounded-lg text-sm transition-colors ${filterVisibility === v ? 'bg-primary-50 text-primary-700 font-medium' : 'text-gray-600 hover:bg-gray-50'}`}
                                >
                                    {v.charAt(0).toUpperCase() + v.slice(1)}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Price Range */}
                    <div>
                        <label className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 block">Price Range</label>
                        <div className="flex gap-2 items-center">
                            <input
                                type="number"
                                placeholder="Min"
                                value={minPrice}
                                onChange={(e) => setMinPrice(e.target.value)}
                                className="w-full px-2 py-1.5 text-xs border border-gray-200 rounded-lg"
                            />
                            <span className="text-gray-400">-</span>
                            <input
                                type="number"
                                placeholder="Max"
                                value={maxPrice}
                                onChange={(e) => setMaxPrice(e.target.value)}
                                className="w-full px-2 py-1.5 text-xs border border-gray-200 rounded-lg"
                            />
                        </div>
                        <button onClick={handleSearch} className="w-full mt-2 py-1.5 bg-gray-900 text-white text-xs rounded-lg hover:bg-gray-800 transition-colors">Apply Price</button>
                    </div>

                    {/* Material */}
                    <div>
                        <label className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 block">Material</label>
                        <select
                            value={filterMaterial}
                            onChange={(e) => setFilterMaterial(e.target.value)}
                            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500"
                        >
                            <option value="">All Materials</option>
                            <option value="316L Surgical Steel">Surgical Steel</option>
                            <option value="Titanium G23">Titanium</option>
                            <option value="Sterling Silver 925">Sterling Silver</option>
                            <option value="Brass">Brass</option>
                            <option value="Bioplastic">Bioplastic</option>
                        </select>
                    </div>


                    {/* Jewelry Type */}
                    <div>
                        <label className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 block">Type</label>
                        <select
                            value={filterJewelryType}
                            onChange={(e) => setFilterJewelryType(e.target.value)}
                            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg"
                        >
                            <option value="">All Types</option>
                            <option value="Ring">Ring</option>
                            <option value="Barbell">Barbell</option>
                            <option value="Circular Barbell">Circular Barbell</option>
                            <option value="Labret">Labret</option>
                            <option value="Earring">Earring</option>
                        </select>
                    </div>
                </div>
            </div>

            {/* Main Content: Product List */}
            <div className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${selectedProduct ? 'mr-32 opacity-80 pointer-events-none lg:opacity-100 lg:pointer-events-auto' : ''}`}>
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-gray-900">Product Tuning</h1>
                        <p className="text-sm text-gray-500">{total} SKUs matching your filters</p>
                    </div>
                    {selectedIds.size > 0 && (
                        <div className="flex gap-2 animate-in fade-in slide-in-from-top-2">
                            <button
                                onClick={handleBulkShow}
                                className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 shadow-sm transition-all active:scale-95"
                            >
                                Show Selected ({selectedIds.size})
                            </button>
                            <button
                                onClick={handleBulkHide}
                                className="px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 shadow-sm transition-all active:scale-95"
                            >
                                Hide Selected ({selectedIds.size})
                            </button>
                        </div>
                    )}
                </div>

                <div className="flex-1 overflow-y-auto bg-white rounded-xl shadow-sm border border-gray-200 relative">
                    <table className="min-w-full divide-y divide-gray-200 table-fixed">
                        <thead className="bg-gray-50 sticky top-0 z-10 shadow-sm">
                            <tr>
                                <th className="w-12 px-4 py-3 text-left">
                                    <input
                                        type="checkbox"
                                        checked={selectedIds.size === products.length && products.length > 0}
                                        onChange={toggleSelectAll}
                                        className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                    />
                                </th>
                                <th className="w-20 px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Image</th>
                                <th className="w-40 px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Master Code</th>
                                <th className="Description px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Description</th>
                                <th className="w-32 px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">SKU</th>
                                <th className="w-24 px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase tracking-wider">Price</th>
                                <th className="w-20 px-4 py-3 text-center text-xs font-bold text-gray-500 uppercase tracking-wider">Status</th>
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
                                    <td className="px-4 py-3">
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
                                    <td className="px-4 py-3 text-sm font-mono text-gray-500">
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
                                    <td className="Description px-4 py-3">
                                        <div className="text-xs text-gray-500" title={product.description || ''}>
                                            {product.description || <span className="text-gray-300 italic">No description</span>}
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-sm font-mono text-gray-500">{product.sku}</td>
                                    <td className="px-4 py-3 text-sm font-bold text-gray-900">${product.price.toFixed(2)}</td>
                                    <td className="px-4 py-3 text-center">
                                        <div className={`w-2 h-2 rounded-full mx-auto ${product.visibility ? (product.in_stock ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-yellow-500') : 'bg-gray-300'}`} />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>

                    {/* Pagination / Load More */}
                    {products.length < total && (
                        <div className="p-8 text-center bg-gradient-to-t from-white via-white to-transparent sticky bottom-0">
                            <button
                                onClick={handleLoadMore}
                                disabled={loading}
                                className="px-6 py-2.5 bg-white border border-gray-200 text-gray-900 font-semibold rounded-full shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition-all text-sm disabled:opacity-50"
                            >
                                {loading ? 'Loading...' : `Load More (${total - products.length} left)`}
                            </button>
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
                                <p className="text-xs text-gray-500 uppercase font-bold tracking-widest">{selectedProduct.sku}</p>
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

                            {/* Tuning Controls */}
                            <section className="bg-gray-50 rounded-2xl p-5 border border-gray-100 space-y-4">
                                <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest mb-2">Tuning Controls</h4>
                                <div className="grid grid-cols-2 gap-4">
                                    <div className="bg-white p-3 rounded-xl border border-gray-100 shadow-sm">
                                        <div className="flex items-center justify-between mb-2">
                                            <span className="text-sm font-semibold text-gray-700">Visibility</span>
                                            <button
                                                onClick={() => handleToggleVisibility(selectedProduct)}
                                                className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${selectedProduct.visibility ? 'bg-green-500' : 'bg-gray-300'}`}
                                            >
                                                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${selectedProduct.visibility ? 'translate-x-5' : 'translate-x-1'}`} />
                                            </button>
                                        </div>
                                        <p className="text-[10px] text-gray-400 leading-tight">Hide this product from search results and recommendations.</p>
                                    </div>
                                    <div className="bg-white p-3 rounded-xl border border-gray-100 shadow-sm">
                                        <div className="flex items-center justify-between mb-2">
                                            <span className="text-sm font-semibold text-gray-700">Featured</span>
                                            <button
                                                onClick={() => handleToggleFeatured(selectedProduct)}
                                                className={`p-1 rounded-lg transition-colors ${selectedProduct.is_featured ? 'text-yellow-500 bg-yellow-50' : 'text-gray-300 hover:text-gray-400'}`}
                                            >
                                                <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.162c.969 0 1.371 1.24.588 1.81l-3.37 2.448a1 1 0 00-.364 1.118l1.287 3.957c.3.921-.755 1.688-1.54 1.118l-3.37-2.448a1 1 0 00-1.175 0l-3.37 2.448c-.784.57-1.838-.197-1.54-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.05 9.384c-.783-.57-.38-1.81.588-1.81h4.162a1 1 0 00.95-.69l1.286-3.957z" /></svg>
                                            </button>
                                        </div>
                                        <p className="text-[10px] text-gray-400 leading-tight">Boost this product in "Handpicked" sections.</p>
                                    </div>
                                </div>
                                <div className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
                                    <label className="text-sm font-semibold text-gray-700 mb-2 block">Recommendation Priority</label>
                                    <div className="flex gap-2">
                                        {[0, 1, 2, 3, 4, 5].map((p) => (
                                            <button
                                                key={p}
                                                onClick={() => handleUpdatePriority(selectedProduct, p)}
                                                className={`flex-1 py-1.5 rounded-lg text-sm font-bold transition-all border ${selectedProduct.priority === p ? 'bg-primary-600 border-primary-600 text-white shadow-md' : 'border-gray-100 hover:bg-gray-50 text-gray-500'}`}
                                            >
                                                {p}
                                            </button>
                                        ))}
                                    </div>
                                    <p className="text-[10px] text-gray-400 mt-2">Higher priority products appear first in AI responses.</p>
                                </div>
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
                                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500 font-mono"
                                    />
                                    <p className="text-[10px] text-gray-400 mt-2">Group multiple SKUs under one master collection.</p>
                                </div>
                            </section>

                            {/* Attributes Grid */}
                            <section className="space-y-4">
                                <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest pl-1">Technical Attributes</h4>
                                <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                                    <AttributeItem label="Material" value={selectedProduct.material} />
                                    <AttributeItem label="Jewelry Type" value={selectedProduct.jewelry_type} />
                                    <AttributeItem label="Length" value={selectedProduct.length} />
                                    <AttributeItem label="Size" value={selectedProduct.size} />
                                    <AttributeItem label="Gauge" value={selectedProduct.gauge} />
                                    <AttributeItem label="Design" value={selectedProduct.design} />
                                    <AttributeItem label="CZ Color" value={selectedProduct.cz_color} />
                                    <AttributeItem label="Opal Color" value={selectedProduct.opal_color} />
                                    <AttributeItem label="Threading" value={selectedProduct.threading} />
                                    <AttributeItem label="Diameter" value={selectedProduct.outer_diameter} />
                                </div>
                            </section>

                            {/* Description */}
                            {selectedProduct.description && (
                                <section className="space-y-3">
                                    <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest pl-1">Description</h4>
                                    <div className="text-sm text-gray-600 leading-relaxed bg-gray-50 rounded-xl p-4 border border-gray-100">
                                        {selectedProduct.description}
                                    </div>
                                </section>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

// Helper Components
const AttributeItem: React.FC<{ label: string; value?: string | number | null }> = ({ label, value }) => (
    <div className="flex flex-col border-b border-gray-50 pb-2">
        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tight">{label}</span>
        <span className="text-sm font-semibold text-gray-700 truncate">{value || 'N/A'}</span>
    </div>
);
