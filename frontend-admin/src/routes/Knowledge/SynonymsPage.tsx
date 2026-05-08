import React, { useEffect, useMemo, useState } from 'react';
import { aliasesApi, SynonymAttribute, SynonymGroup } from '../../api/training';
import { Button } from '../../components/common/Button';
import { Spinner } from '../../components/common/Spinner';
import { Modal } from '../../components/common/Modal';
import { Input } from '../../components/common/Input';
import { PaginationControls } from '../../components/common/PaginationControls';
import { PaginationChange } from '../../types/pagination';

type StatusFilter = 'all' | 'active' | 'inactive';
type Density = 'comfortable' | 'compact';

const MAX_VISIBLE_CHIPS = 4;
const INTERNAL_ATTRIBUTES = new Set(['source_id', 'source_raw_sku']);

const isInternalAttribute = (name: string): boolean => INTERNAL_ATTRIBUTES.has(String(name || '').toLowerCase());

const ChipList: React.FC<{ values: string[] }> = ({ values }) => {
    if (!values.length) return <span className="text-xs text-gray-400">No synonyms</span>;
    const visible = values.slice(0, MAX_VISIBLE_CHIPS);
    const hiddenCount = values.length - visible.length;
    return (
        <div className="flex flex-wrap gap-2">
            {visible.map((val, idx) => (
                <span
                    key={`${val}-${idx}`}
                    title={val}
                    className="inline-flex max-w-[180px] items-center rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-800 truncate"
                >
                    {val}
                </span>
            ))}
            {hiddenCount > 0 && (
                <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-1 text-[11px] font-semibold text-gray-600">
                    +{hiddenCount} more
                </span>
            )}
        </div>
    );
};

const DirectionBadge: React.FC<{ direction?: 'two-way' | 'one-way' }> = ({ direction = 'two-way' }) => {
    const isTwoWay = direction === 'two-way';
    return (
        <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10px] font-semibold ${
                isTwoWay ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'
            }`}
        >
            {isTwoWay ? '<=>' : '→'} {isTwoWay ? 'Two-way' : 'One-way'}
        </span>
    );
};

interface DeleteState {
    open: boolean;
    aliasId: number | null;
    text: string;
}

export const SynonymsPage: React.FC = () => {
    const [aliasGroups, setAliasGroups] = useState<SynonymGroup[]>([]);
    const [attributes, setAttributes] = useState<SynonymAttribute[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedAttribute, setSelectedAttribute] = useState<string>('');
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [density, setDensity] = useState<Density>('comfortable');
    const [isRefreshing, setIsRefreshing] = useState(false);

    // Modal state
    const [isNewModalOpen, setIsNewModalOpen] = useState(false);
    const [newAlias, setNewAlias] = useState({ raw_value: '', canonical_value: '' });
    const [deleteState, setDeleteState] = useState<DeleteState>({ open: false, aliasId: null, text: '' });

    useEffect(() => {
        loadAliasGroups();
        loadAttributes();
    }, []);

    const loadAliasGroups = async () => {
        setIsRefreshing(true);
        try {
            const data = await aliasesApi.listAliases();
            setAliasGroups(data.filter((group) => !isInternalAttribute(group.attribute)));
        } catch (error) {
            console.error('Failed to load alias groups:', error);
        } finally {
            setLoading(false);
            setIsRefreshing(false);
        }
    };

    const loadAttributes = async () => {
        try {
            const data = await aliasesApi.listAttributes();
            const visibleAttributes = data.filter((attr) => !isInternalAttribute(attr.name));
            setAttributes(visibleAttributes);
            if (!selectedAttribute && visibleAttributes.length) {
                setSelectedAttribute(visibleAttributes[0].name);
            } else if (
                selectedAttribute &&
                !visibleAttributes.some((attr) => attr.name.toLowerCase() === selectedAttribute.toLowerCase())
            ) {
                setSelectedAttribute(visibleAttributes[0]?.name || '');
            }
        } catch (error) {
            console.error('Failed to load attributes:', error);
        }
    };

    const attributeCounts = useMemo(() => {
        const counts = new Map<string, number>();
        aliasGroups.forEach((group) => {
            counts.set(group.attribute, (counts.get(group.attribute) ?? 0) + 1);
        });
        return counts;
    }, [aliasGroups]);

    const filteredGroups = useMemo(() => {
        const attrKey = selectedAttribute.toLowerCase();
        const searchQuery = search.toLowerCase().trim();
        return aliasGroups
            .filter((group) => !attrKey || group.attribute.toLowerCase() === attrKey)
            .map((group) => ({
                ...group,
                synonyms:
                    statusFilter === 'all'
                        ? group.synonyms
                        : group.synonyms.filter((alias) => (statusFilter === 'active' ? alias.is_active : !alias.is_active)),
            }))
            .filter((group) => group.synonyms.length > 0)
            .filter((group) => {
                if (!searchQuery) return true;
                if (group.canonical_value.toLowerCase().includes(searchQuery)) return true;
                return group.synonyms.some((alias) => alias.raw_value.toLowerCase().includes(searchQuery));
            });
    }, [aliasGroups, selectedAttribute, statusFilter, search]);

    const [pagination, setPagination] = useState<PaginationChange>({ currentPage: 1, pageSize: 10 });
    useEffect(() => {
        setPagination((prev) => ({ ...prev, currentPage: 1 }));
    }, [filteredGroups.length, selectedAttribute, statusFilter, search]);

    const handlePaginationChange = (next: PaginationChange) => {
        setPagination(next);
    };

    const pagedGroups = useMemo(() => {
        const { currentPage, pageSize } = pagination;
        const start = (currentPage - 1) * pageSize;
        return filteredGroups.slice(start, start + pageSize);
    }, [pagination, filteredGroups]);

    const groupKey = (group: SynonymGroup) => `${group.attribute.toLowerCase()}||${group.canonical_value.toLowerCase()}`;
    const [pendingSynonyms, setPendingSynonyms] = useState<Record<string, string>>({});

    const handleAddSynonym = async (group: SynonymGroup) => {
        const key = groupKey(group);
        const value = (pendingSynonyms[key] || '').trim();
        if (!value) return;
        try {
            await aliasesApi.createAlias({
                attribute: group.attribute,
                raw_value: value,
                canonical_value: group.canonical_value,
            });
            setPendingSynonyms((prev) => ({ ...prev, [key]: '' }));
            await loadAliasGroups();
        } catch (error) {
            console.error('Failed to add synonym:', error);
        }
    };

    const handleToggleSynonym = async (aliasId: number, current: boolean) => {
        try {
            await aliasesApi.updateAlias(aliasId, { is_active: !current });
            await loadAliasGroups();
        } catch (error) {
            console.error('Failed to toggle synonym status:', error);
        }
    };

    const handleDeleteSynonym = async () => {
        if (!deleteState.aliasId) return;
        try {
            await aliasesApi.deleteAlias(deleteState.aliasId);
            await loadAliasGroups();
        } catch (error) {
            console.error('Failed to delete alias:', error);
        } finally {
            setDeleteState({ open: false, aliasId: null, text: '' });
        }
    };

    const handleCreate = async () => {
        try {
            await aliasesApi.createAlias({
                attribute: selectedAttribute,
                raw_value: newAlias.raw_value,
                canonical_value: newAlias.canonical_value,
            });
            await loadAliasGroups();
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

    const rowPadding = density === 'compact' ? 'py-2' : 'py-3';

    return (
        <div className="flex flex-col h-[calc(100vh-120px)] bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="flex items-center justify-end px-6 pt-4 pb-4 border-b border-gray-100 gap-4">
                <div className="flex items-center gap-2 shrink-0">
                    <Button variant="ghost" size="sm" onClick={loadAliasGroups}>
                        {isRefreshing ? 'Refreshing…' : 'Refresh'}
                    </Button>
                    <Button
                        size="sm"
                        onClick={() => setIsNewModalOpen(true)}
                        className="bg-primary-600 hover:bg-primary-700 text-white"
                        disabled={!selectedAttribute}
                    >
                        New rule
                    </Button>
                </div>
            </div>

            <div className="px-6 py-3 border-b border-gray-100 flex flex-col lg:flex-row lg:items-center gap-3">
                <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Input
                        placeholder="Search term or synonym…"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="text-sm"
                    />
                    <select
                        value={selectedAttribute}
                        onChange={(e) => setSelectedAttribute(e.target.value)}
                        className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-primary-200"
                    >
                        <option value="">
                            All attributes ({aliasGroups.length})
                        </option>
                        {attributes.map((attr) => (
                            <option key={attr.name} value={attr.name}>
                                {attr.display_name || attr.name} ({attributeCounts.get(attr.name) ?? 0})
                            </option>
                        ))}
                    </select>
                </div>
                <div className="flex items-center gap-2">
                    <div className="flex rounded-lg border border-gray-200 p-1 bg-gray-50">
                        {(['all', 'active', 'inactive'] as StatusFilter[]).map((f) => (
                            <button
                                key={f}
                                onClick={() => setStatusFilter(f)}
                                className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-all ${
                                    statusFilter === f ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                                }`}
                            >
                                {f}
                            </button>
                        ))}
                    </div>
                    <div className="flex rounded-lg border border-gray-200 p-1 bg-gray-50">
                        {(['comfortable', 'compact'] as Density[]).map((d) => (
                            <button
                                key={d}
                                onClick={() => setDensity(d)}
                                className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-all ${
                                    density === d ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                                }`}
                            >
                                {d === 'comfortable' ? 'Comfort' : 'Compact'}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto">
                <table className="w-full text-left border-collapse">
                    <thead className="sticky top-0 bg-white shadow-[0_1px_0_rgba(0,0,0,0.05)] z-10">
                        <tr>
                            <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">Main term</th>
                            <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">Direction</th>
                            <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400">Synonyms</th>
                            <th className="px-6 py-3 text-[10px] font-bold uppercase tracking-wider text-gray-400 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                        {pagedGroups.length > 0 ? (
                            pagedGroups.map((group) => (
                                <tr key={`${group.attribute}-${group.canonical_value}`} className="hover:bg-gray-50/70 transition-colors">
                                    <td className={`px-6 ${rowPadding}`}>
                                        <div className="text-sm font-semibold text-gray-900 truncate">{group.canonical_value}</div>
                                        <div className="text-[11px] uppercase tracking-[0.2em] text-gray-400 truncate">
                                            {group.attribute_display_name}
                                        </div>
                                    </td>
                                    <td className={`px-6 ${rowPadding}`}>
                                        <DirectionBadge direction="two-way" />
                                    </td>
                                    <td className={`px-6 ${rowPadding}`}>
                                        <ChipList values={group.synonyms.map((a) => a.raw_value)} />
                                        <div className="mt-3 flex flex-wrap gap-2">
                                            <Input
                                                value={pendingSynonyms[groupKey(group)] ?? ''}
                                                onChange={(e) =>
                                                    setPendingSynonyms((prev) => ({
                                                        ...prev,
                                                        [groupKey(group)]: e.target.value,
                                                    }))
                                                }
                                                placeholder="Add synonym"
                                                className="text-sm min-w-[160px]"
                                            />
                                            <Button
                                                size="sm"
                                                onClick={() => handleAddSynonym(group)}
                                                disabled={!pendingSynonyms[groupKey(group)]?.trim()}
                                            >
                                                Add
                                            </Button>
                                        </div>
                                    </td>
                                    <td className={`px-6 ${rowPadding} text-right space-x-2`}>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() =>
                                                setDeleteState({
                                                    open: true,
                                                    aliasId: group.synonyms[0]?.id ?? null,
                                                    text: group.canonical_value,
                                                })
                                            }
                                        >
                                            Delete
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() =>
                                                handleToggleSynonym(group.synonyms[0]?.id ?? 0, !!group.synonyms[0]?.is_active)
                                            }
                                        >
                                            {group.synonyms[0]?.is_active ? 'Deactivate' : 'Activate'}
                                        </Button>
                                    </td>
                                </tr>
                            ))
                        ) : (
                            <tr>
                                <td colSpan={4} className="px-6 py-12 text-center text-gray-400 italic text-sm">
                                    No synonym rules match your filters.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {filteredGroups.length > 0 && (
                <PaginationControls
                    currentPage={pagination.currentPage}
                    pageSize={pagination.pageSize}
                    totalItems={filteredGroups.length}
                    onChange={handlePaginationChange}
                    isLoading={loading}
                    className="border-t border-gray-200"
                />
            )}

            <Modal
                isOpen={isNewModalOpen}
                onClose={() => setIsNewModalOpen(false)}
                title={`New Synonym for ${selectedAttribute || 'attribute'}`}
            >
                <div className="space-y-4 pt-2">
                    <Input
                        label="Raw Search Term (Alias)"
                        placeholder="e.g. 'Silver' or 'Metal'"
                        value={newAlias.raw_value}
                        onChange={(e) => setNewAlias((prev) => ({ ...prev, raw_value: e.target.value }))}
                    />
                    <Input
                        label="Canonical Value (Catalog exact match)"
                        placeholder="e.g. 316L Surgical Steel"
                        value={newAlias.canonical_value}
                        onChange={(e) => setNewAlias((prev) => ({ ...prev, canonical_value: e.target.value }))}
                    />
                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="outline" onClick={() => setIsNewModalOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            onClick={handleCreate}
                            disabled={!newAlias.raw_value || !newAlias.canonical_value || !selectedAttribute}
                            className="bg-primary-600 hover:bg-primary-700 text-white"
                        >
                            Create Synonym
                        </Button>
                    </div>
                </div>
            </Modal>

            <Modal
                isOpen={deleteState.open}
                onClose={() => setDeleteState({ open: false, aliasId: null, text: '' })}
                title="Delete synonym?"
            >
                <div className="space-y-3 pt-2">
                    <p className="text-sm text-gray-600">
                        You are deleting <span className="font-semibold text-gray-900">{deleteState.text}</span>. This cannot be undone.
                    </p>
                    <div className="flex justify-end gap-3">
                        <Button variant="outline" onClick={() => setDeleteState({ open: false, aliasId: null, text: '' })}>
                            Cancel
                        </Button>
                        <Button className="bg-red-500 hover:bg-red-600 text-white" onClick={handleDeleteSynonym}>
                            Delete
                        </Button>
                    </div>
                </div>
            </Modal>
        </div>
    );
};
