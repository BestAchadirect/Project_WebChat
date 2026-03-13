import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { aliasesApi, SynonymAttribute, SynonymEntry } from '../../api/training';
import { Button } from '../../components/common/Button';
import { Spinner } from '../../components/common/Spinner';
import { Modal } from '../../components/common/Modal';
import { Input } from '../../components/common/Input';
import { PaginationControls } from '../../components/common/PaginationControls';
import { PaginationChange } from '../../types/pagination';

interface AttributeEntry {
    name: string;
    displayName: string;
    aliases: SynonymEntry[];
    nameLower: string;
}

export const SynonymsPage: React.FC = () => {
    const [aliases, setAliases] = useState<SynonymEntry[]>([]);
    const [attributes, setAttributes] = useState<SynonymAttribute[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedAttribute, setSelectedAttribute] = useState<string>('');
    const [attrSearch, setAttrSearch] = useState('');
    const [aliasFilter, setAliasFilter] = useState<'all' | 'active' | 'inactive'>('all');
    const [refreshTime, setRefreshTime] = useState<Date>(new Date());
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [activeTab, setActiveTab] = useState<'attributes' | 'grid'>('attributes');

    // Modal state
    const [isNewModalOpen, setIsNewModalOpen] = useState(false);
    const [newAlias, setNewAlias] = useState({
        raw_value: '',
        canonical_value: '',
    });

    useEffect(() => {
        loadAliases();
    }, []);

    useEffect(() => {
        loadAttributes();
    }, []);

    const loadAliases = async () => {
        setIsRefreshing(true);
        try {
            const data = await aliasesApi.listAliases();
            setAliases(data);
            setRefreshTime(new Date());
        } catch (error) {
            console.error('Failed to load aliases:', error);
        } finally {
            setLoading(false);
            setIsRefreshing(false);
        }
    };

    const loadAttributes = async () => {
        try {
            const data = await aliasesApi.listAttributes();
            setAttributes(data);
        } catch (error) {
            console.error('Failed to load attributes:', error);
        } finally {
        }
    };

    useEffect(() => {
        if (attributes.length === 0) {
            return;
        }
        if (!selectedAttribute) {
            setSelectedAttribute(attributes[0].name);
        }
    }, [attributes, selectedAttribute]);

    const attributeAliasMap = useMemo(() => {
        const map = new Map<string, AttributeEntry>();
        attributes.forEach((attr) => {
            const key = attr.name.toLowerCase();
            map.set(key, {
                name: attr.name,
                displayName: attr.display_name,
                aliases: [],
                nameLower: key,
            });
        });
        aliases.forEach((alias) => {
            const key = alias.attribute.toLowerCase();
            if (!map.has(key)) {
                map.set(key, {
                    name: alias.attribute,
                    displayName: alias.attribute,
                    aliases: [],
                    nameLower: key,
                });
            }
            map.get(key)?.aliases.push(alias);
        });
        return map;
    }, [aliases, attributes]);

    const attributeEntries = useMemo(
        () => Array.from(attributeAliasMap.values()),
        [attributeAliasMap],
    );

    const HIDDEN_ATTRIBUTE_KEYS = useMemo(() => new Set(['source_id', 'source_raw_sku']), []);
    const HIDDEN_ATTRIBUTE_KEYWORDS = useMemo(() => ['source id', 'source raw sku'], []);

    const shouldHideAttribute = useCallback(
        (entry: AttributeEntry) => {
            if (HIDDEN_ATTRIBUTE_KEYS.has(entry.nameLower)) {
                return true;
            }
            const displayLower = entry.displayName.toLowerCase();
            return HIDDEN_ATTRIBUTE_KEYWORDS.some((keyword) => displayLower.includes(keyword));
        },
        [HIDDEN_ATTRIBUTE_KEYS, HIDDEN_ATTRIBUTE_KEYWORDS],
    );

    const visibleAttributeEntries = useMemo(
        () => attributeEntries.filter((entry) => !shouldHideAttribute(entry)),
        [attributeEntries, shouldHideAttribute],
    );

    const selectedAttributeEntry = useMemo(() => {
        if (!selectedAttribute) {
            return null;
        }
        return attributeAliasMap.get(selectedAttribute.toLowerCase()) ?? null;
    }, [attributeAliasMap, selectedAttribute]);

    const selectedAttributeDisplayName = selectedAttributeEntry?.displayName || selectedAttribute || 'Aliases';

    const attributeSearchMatch = useMemo(() => {
        const query = attrSearch.toLowerCase().trim();
        if (!query) {
            return null;
        }
        for (const entry of visibleAttributeEntries) {
            if (entry.nameLower.includes(query)) {
                return entry.name;
            }
            if (entry.displayName.toLowerCase().includes(query)) {
                return entry.name;
            }
            if (
                entry.aliases.some((alias) => {
                    const raw = alias.raw_value.toLowerCase();
                    const canonical = alias.canonical_value.toLowerCase();
                    return raw.includes(query) || canonical.includes(query);
                })
            ) {
                return entry.name;
            }
        }
        return null;
    }, [attrSearch, visibleAttributeEntries]);

    useEffect(() => {
        if (!visibleAttributeEntries.length) {
            return;
        }
        const matches = visibleAttributeEntries.some((entry) => entry.name === selectedAttribute);
        if (!matches) {
            setSelectedAttribute(visibleAttributeEntries[0].name);
        }
    }, [visibleAttributeEntries, selectedAttribute]);

    useEffect(() => {
        if (!attributeSearchMatch) {
            return;
        }
        setSelectedAttribute(attributeSearchMatch);
    }, [attributeSearchMatch]);

    const attributeStats = useMemo(() => {
        const query = attrSearch.toLowerCase().trim();
        return visibleAttributeEntries
            .map((entry) => ({
                name: entry.name,
                displayName: entry.displayName,
                aliasCount: entry.aliases.length,
            }))
            .filter((entry) => {
                if (!query) {
                    return true;
                }
                const entryKey = entry.name.toLowerCase();
                if (entryKey.includes(query)) {
                    return true;
                }
                const displayKey = entry.displayName.toLowerCase();
                if (displayKey.includes(query)) {
                    return true;
                }
                const entryData = attributeAliasMap.get(entryKey);
                if (!entryData) {
                    return false;
                }
                return entryData.aliases.some((alias) => {
                    const raw = alias.raw_value.toLowerCase();
                    const canonical = alias.canonical_value.toLowerCase();
                    return raw.includes(query) || canonical.includes(query);
                });
            });
    }, [attributeEntries, attributeAliasMap, attrSearch]);

    const filteredAliases = useMemo(() => {
        return aliases.filter(a => {
            const matchesAttr = a.attribute.toLowerCase() === selectedAttribute.toLowerCase();
            const matchesFilter = 
                aliasFilter === 'all' || 
                (aliasFilter === 'active' && a.is_active) || 
                (aliasFilter === 'inactive' && !a.is_active);
            return matchesAttr && matchesFilter;
        });
    }, [aliases, selectedAttribute, aliasFilter]);

    const searchFilteredAliases = useMemo(() => {
        const query = attrSearch.toLowerCase().trim();
        if (!query) {
            return filteredAliases;
        }
        return filteredAliases.filter((alias) => {
            const raw = alias.raw_value.toLowerCase();
            const canonical = alias.canonical_value.toLowerCase();
            return (
                raw.includes(query) ||
                canonical.includes(query) ||
                alias.attribute.toLowerCase().includes(query)
            );
        });
    }, [filteredAliases, attrSearch]);

    const [pagination, setPagination] = useState<PaginationChange>({ currentPage: 1, pageSize: 10 });
    useEffect(() => {
        setPagination((prev) => ({ ...prev, currentPage: 1 }));
    }, [searchFilteredAliases.length, selectedAttribute, aliasFilter]);

    const handlePaginationChange = (next: PaginationChange) => {
        setPagination(next);
    };

    const pagedAliases = useMemo(() => {
        const { currentPage, pageSize } = pagination;
        const start = (currentPage - 1) * pageSize;
        return searchFilteredAliases.slice(start, start + pageSize);
    }, [pagination, searchFilteredAliases]);

    const handleToggleStatus = async (id: number, current: boolean) => {
        try {
            await aliasesApi.updateAlias(id, { is_active: !current });
            setAliases(prev => prev.map(a => a.id === id ? { ...a, is_active: !current } : a));
        } catch (error) {
            console.error('Failed to toggle status:', error);
        }
    };

    const handleDelete = async (id: number) => {
        if (!window.confirm('Are you sure you want to delete this synonym?')) return;
        try {
            await aliasesApi.deleteAlias(id);
            setAliases(prev => prev.filter(a => a.id !== id));
        } catch (error) {
            console.error('Failed to delete alias:', error);
        }
    };

    const handleCreate = async () => {
        try {
            const created = await aliasesApi.createAlias({
                attribute: selectedAttribute,
                raw_value: newAlias.raw_value,
                canonical_value: newAlias.canonical_value
            });
            setAliases(prev => [...prev, created]);
            setIsNewModalOpen(false);
            setNewAlias({ raw_value: '', canonical_value: '' });
        } catch (error) {
            console.error('Failed to create alias:', error);
        }
    };

    if (loading) {
        return (
            <div className="flex h-[60vh] items-center justify-center">
                <Spinner size="lg" className="text-primary-600" />
            </div>
        );
    }

    return (
        <div className="flex flex-col h-[calc(100vh-120px)] bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden overflow-x-hidden relative">
            {/* Mobile Tab Switcher */}
            <div className="md:hidden flex p-2 bg-gray-50 border-b border-gray-200 shrink-0">
                <button
                    onClick={() => setActiveTab('attributes')}
                    className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${
                        activeTab === 'attributes' ? 'bg-white text-primary-600 shadow-sm' : 'text-gray-500'
                    }`}
                >
                    Attributes
                </button>
                <button
                    onClick={() => setActiveTab('grid')}
                    className={`flex-1 py-2 text-sm font-bold rounded-lg transition-colors ${
                        activeTab === 'grid' ? 'bg-white text-primary-600 shadow-sm' : 'text-gray-500'
                    }`}
                >
                    Alias Grid
                </button>
            </div>

            {/* Split Panel Layout */}
            <div className="flex flex-1 min-h-0 overflow-hidden flex-col md:flex-row">
                {/* Left Panel - Attributes */}
                <div className={`${activeTab === 'attributes' ? 'flex' : 'hidden'} md:flex w-full md:w-80 border-b md:border-b-0 md:border-r border-gray-100 flex-col bg-gray-50/30 overflow-hidden`}>
                    <div className="p-4 border-b border-gray-100 bg-white">
                        <Input
                            placeholder="Search attributes..."
                            value={attrSearch}
                            onChange={(e) => setAttrSearch(e.target.value)}
                            className="text-sm"
                        />
                    </div>
                    <div className="flex-1 overflow-y-auto py-2">
                        {attributeStats.map((attr) => (
                            <button
                                key={attr.name}
                                onClick={() => {
                                    setSelectedAttribute(attr.name);
                                    if (window.innerWidth < 768) setActiveTab('grid');
                                }}
                                className={`w-full flex items-center justify-between px-4 py-3 text-left transition-colors ${
                                    selectedAttribute === attr.name
                                        ? 'bg-primary-50 text-primary-700 border-r-4 border-primary-600'
                                        : 'text-gray-600 hover:bg-gray-100/50 hover:text-gray-900'
                                }`}
                            >
                                <span className="font-medium text-sm">{attr.displayName}</span>
                                <span className="text-[10px] font-bold bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                                    {attr.aliasCount}
                                </span>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Right Panel - Alias Grid */}
                <div className={`${activeTab === 'grid' ? 'flex' : 'hidden'} md:flex flex-1 flex-col min-w-0 bg-white overflow-hidden`}>
                    {/* Toolbar */}
                    <div className="px-6 py-4 border-b border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shrink-0">
                        <div className="flex items-center gap-2 overflow-hidden">
                            <h2 className="text-lg font-bold text-gray-900 truncate">{selectedAttributeDisplayName} Aliases</h2>
                            <div className="flex rounded-lg border border-gray-200 p-1 bg-gray-50 shrink-0">
                                {(['all', 'active', 'inactive'] as const).map((f) => (
                                    <button
                                        key={f}
                                        onClick={() => setAliasFilter(f)}
                                        className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-all ${
                                            aliasFilter === f
                                                ? 'bg-white text-gray-900 shadow-sm'
                                                : 'text-gray-500 hover:text-gray-700'
                                        }`}
                                    >
                                        {f}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div className="hidden sm:flex items-center gap-2">
                            <Button
                                size="sm"
                                onClick={() => setIsNewModalOpen(true)}
                                className="bg-primary-600 hover:bg-primary-700 text-white"
                                disabled={!selectedAttribute}
                            >
                                New Synonym
                            </Button>
                        </div>
                    </div>

                    {/* Table */}
                    <div className="flex-1 overflow-y-auto">
                        <table className="w-full text-left border-collapse">
                            <thead className="sticky top-0 bg-white shadow-[0_1px_0_rgba(0,0,0,0.05)] z-10">
                                <tr>
                                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">Canonical Value</th>
                                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">Status</th>
                                    <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-50">
                            {filteredAliases.length > 0 ? (
                                pagedAliases.map((alias) => (
                                    <tr key={alias.id} className="hover:bg-gray-50/50 transition-colors group">
                                            <td className="px-6 py-4 text-sm text-gray-600">{alias.canonical_value}</td>
                                            <td className="px-6 py-4">
                                                <button
                                                    onClick={() => handleToggleStatus(alias.id, alias.is_active)}
                                                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                                                        alias.is_active ? 'bg-primary-600' : 'bg-gray-200'
                                                    }`}
                                                >
                                                    <span
                                                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                                                            alias.is_active ? 'translate-x-4' : 'translate-x-0'
                                                        }`}
                                                    />
                                                </button>
                                            </td>
                                            <td className="px-6 py-4 text-right">
                                                <button
                                                    onClick={() => handleDelete(alias.id)}
                                                    className="text-gray-400 hover:text-red-600 transition-colors p-1"
                                                >
                                                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                    </svg>
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                ) : (
                                    <tr>
                                        <td colSpan={3} className="px-6 py-12 text-center text-gray-400 italic text-sm">
                                            No synonyms found for "{selectedAttributeDisplayName}".
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                    {searchFilteredAliases.length > 0 && (
                        <PaginationControls
                            currentPage={pagination.currentPage}
                            pageSize={pagination.pageSize}
                            totalItems={searchFilteredAliases.length}
                            onChange={handlePaginationChange}
                            isLoading={loading}
                            className="border-t border-gray-200"
                        />
                    )}
                </div>
            </div>

            {/* Floating Action Button (Mobile Only) */}
            <div className="md:hidden fixed bottom-6 right-6 z-20 flex flex-col gap-3">
                <button
                    onClick={() => setIsNewModalOpen(true)}
                    className={`w-14 h-14 bg-primary-600 text-white rounded-full shadow-lg flex items-center justify-center hover:bg-primary-700 hover:scale-110 active:scale-95 transition-all ${
                        !selectedAttribute ? 'cursor-not-allowed opacity-50 hover:bg-primary-600' : ''
                    }`}
                    disabled={!selectedAttribute}
                >
                    <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 6v12m6-6H6" />
                    </svg>
                </button>
            </div>

            {/* Footer */}
            <div className="bg-gray-50/80 px-6 py-3 border-t border-gray-100 flex items-center justify-between text-[11px] text-gray-500 shrink-0">
                <div className="flex items-center gap-4 overflow-hidden">
                    <span className="hidden sm:flex items-center gap-1 shrink-0">
                        <svg className="w-3 h-3 text-primary-500" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                        </svg>
                        These aliases normalize search terms.
                    </span>
                    <span className="italic truncate invisible sm:visible">Use exact attribute names from the catalog.</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <span className={`hidden xs:inline ${isRefreshing ? 'animate-pulse' : ''}`}>
                        Refreshed: {refreshTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <button onClick={loadAliases} className="text-primary-600 hover:text-primary-700 font-bold uppercase tracking-wider">
                        Refresh
                    </button>
                </div>
            </div>

            {/* New Synonym Modal */}
            <Modal
                isOpen={isNewModalOpen}
                onClose={() => setIsNewModalOpen(false)}
                title={`New Synonym for ${selectedAttribute}`}
            >
                <div className="space-y-4 pt-2">
                    <Input
                        label="Raw Search Term (Alias)"
                        placeholder="e.g. 'Silver' or 'Metal'"
                        value={newAlias.raw_value}
                        onChange={(e) => setNewAlias(prev => ({ ...prev, raw_value: e.target.value }))}
                    />
                    <Input
                        label="Canonical Value (Catalog exact match)"
                        placeholder="e.g. 316L Surgical Steel"
                        value={newAlias.canonical_value}
                        onChange={(e) => setNewAlias(prev => ({ ...prev, canonical_value: e.target.value }))}
                    />
                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="outline" onClick={() => setIsNewModalOpen(false)}>Cancel</Button>
                        <Button 
                            onClick={handleCreate}
                            disabled={!newAlias.raw_value || !newAlias.canonical_value}
                            className="bg-primary-600 hover:bg-primary-700 text-white"
                        >
                            Create Synonym
                        </Button>
                    </div>
                </div>
            </Modal>

        </div>
    );
};
