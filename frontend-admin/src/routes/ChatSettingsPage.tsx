import React, { useState, useEffect, useMemo } from 'react';
import { useToast } from '../hooks/useToast';
import { Button } from '../components/common/Button';
import { ChatWidget } from '../components/chat/ChatWidget';
import apiClient from '../api/client';

const MAX_FAQ_COUNT = 5;
const MAX_FAQ_LENGTH = 120;
const DEFAULT_PRIMARY_COLOR = '#214166';

interface ChatConfigState {
    title: string;
    primaryColor: string;
    welcomeMessage: string;
    faqSuggestions: string[];
}

interface Banner {
    id: number;
    image_url: string;
    link_url?: string | null;
    alt_text?: string | null;
    is_active: boolean;
    sort_order: number;
}

const normalizeConfig = (config: ChatConfigState): ChatConfigState => ({
    title: config.title.trim(),
    primaryColor: config.primaryColor.trim(),
    welcomeMessage: config.welcomeMessage,
    faqSuggestions: config.faqSuggestions.map((item) => item.trim()).filter(Boolean),
});

const normalizeBanner = (banner: Banner) => ({
    id: banner.id,
    image_url: banner.image_url,
    link_url: (banner.link_url || '').trim(),
    alt_text: (banner.alt_text || '').trim(),
    is_active: Boolean(banner.is_active),
    sort_order: Number(banner.sort_order) || 0,
});

const stableStringify = (value: unknown): string => JSON.stringify(value);

const isValidHexColor = (value: string): boolean => /^#[0-9A-Fa-f]{6}$/.test(value.trim());

const isValidOptionalHttpUrl = (value?: string | null): boolean => {
    const text = (value || '').trim();
    if (!text) return true;
    try {
        const url = new URL(text);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
};

const buildEmbedCode = (config: ChatConfigState, apiBaseUrl: string, cssUrl: string, scriptUrl: string): string => {
    const serializedConfig = JSON.stringify(
        {
            title: config.title,
            primaryColor: config.primaryColor,
            welcomeMessage: config.welcomeMessage,
            faqSuggestions: config.faqSuggestions,
            apiBaseUrl,
        },
        null,
        2,
    ).replace(/<\/script/gi, '<\\/script');

    return `<!-- GenAI Chat Widget -->
<link rel="stylesheet" href="${cssUrl}">
<script>
window.genaiConfig = ${serializedConfig};
</script>
<script src="${scriptUrl}" async></script>
<!-- End GenAI Chat Widget -->`;
};

export const ChatSettingsPage: React.FC = () => {
    const { showToast } = useToast();
    const widgetOrigin = (import.meta.env.VITE_WIDGET_ORIGIN || 'http://localhost:8000').replace(/\/+$/, '');
    const widgetApiBaseUrl = `${widgetOrigin}/api/v1`;
    const widgetScriptUrl = `${widgetOrigin}/static/widget.js`;
    const widgetCssUrl = `${widgetOrigin}/static/widget.css`;

    const [config, setConfig] = useState({
        title: 'Jewelry Assistant',
        primaryColor: DEFAULT_PRIMARY_COLOR,
        welcomeMessage: 'Welcome to our wholesale body jewelry support! 👋 How can I help you today?',
        faqSuggestions: [
            "What is your minimum order?",
            "Do you offer custom designs?",
            "What materials do you use?"
        ]
    });
    const [savedConfig, setSavedConfig] = useState<ChatConfigState>(() => normalizeConfig(config));

    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [newFaq, setNewFaq] = useState('');

    const [banners, setBanners] = useState<Banner[]>([]);
    const [savedBannersById, setSavedBannersById] = useState<Record<number, ReturnType<typeof normalizeBanner>>>({});
    const [isBannerLoading, setIsBannerLoading] = useState(true);
    const [isBannerUploading, setIsBannerUploading] = useState(false);
    const [bannerSavingId, setBannerSavingId] = useState<number | null>(null);
    const [isBannerReordering, setIsBannerReordering] = useState(false);

    const fetchBanners = async () => {
        try {
            setIsBannerLoading(true);
            const response = await apiClient.get<Banner[]>('/banners/', {
                params: { include_inactive: true }
            });
            const loadedBanners = response.data || [];
            setBanners(loadedBanners);
            setSavedBannersById(
                Object.fromEntries(loadedBanners.map((banner) => [banner.id, normalizeBanner(banner)]))
            );
        } catch (error) {
            console.error('Failed to fetch banners:', error);
            showToast('Failed to load banners', 'error');
        } finally {
            setIsBannerLoading(false);
        }
    };

    useEffect(() => {
        const fetchSettings = async () => {
            try {
                setIsLoading(true);
                const response = await apiClient.get('/settings/chat/');
                if (response.data) {
                    const loadedConfig = normalizeConfig({
                        title: response.data.title || 'Jewelry Assistant',
                        primaryColor: response.data.primary_color || '#214166',
                        welcomeMessage: response.data.welcome_message || '',
                        faqSuggestions: response.data.faq_suggestions || []
                    });
                    setConfig(loadedConfig);
                    setSavedConfig(loadedConfig);
                }
            } catch (error) {
                console.error('Failed to fetch chat settings:', error);
                showToast('Failed to load settings', 'error');
            } finally {
                setIsLoading(false);
            }
        };

        fetchSettings();
        fetchBanners();
    }, []);

    const sortedBanners = useMemo(() => {
        return [...banners].sort((a, b) => {
            const orderDiff = (a.sort_order || 0) - (b.sort_order || 0);
            if (orderDiff !== 0) return orderDiff;
            return a.id - b.id;
        });
    }, [banners]);

    const configValidationErrors = useMemo(() => {
        const errors: string[] = [];
        const normalized = normalizeConfig(config);
        if (!normalized.title) {
            errors.push('Widget title is required.');
        }
        if (!isValidHexColor(normalized.primaryColor)) {
            errors.push('Primary color must be a valid hex color, for example #214166.');
        }
        const seenFaqs = new Set<string>();
        normalized.faqSuggestions.forEach((faq) => {
            if (faq.length > MAX_FAQ_LENGTH) {
                errors.push(`FAQ suggestions must be ${MAX_FAQ_LENGTH} characters or fewer.`);
            }
            const key = faq.toLowerCase();
            if (seenFaqs.has(key)) {
                errors.push('FAQ suggestions must be unique.');
            }
            seenFaqs.add(key);
        });
        return Array.from(new Set(errors));
    }, [config]);

    const normalizedConfig = useMemo(() => normalizeConfig(config), [config]);
    const hasConfigChanges = stableStringify(normalizedConfig) !== stableStringify(savedConfig);
    const hasInvalidConfig = configValidationErrors.length > 0;

    const bannerHasChanges = (banner: Banner): boolean => {
        const saved = savedBannersById[banner.id];
        if (!saved) return true;
        return stableStringify(normalizeBanner(banner)) !== stableStringify(saved);
    };

    const dirtyBannerCount = banners.filter(bannerHasChanges).length;
    const hasUnsavedChanges = hasConfigChanges || dirtyBannerCount > 0;
    const embedCode = useMemo(
        () => buildEmbedCode(normalizedConfig, widgetApiBaseUrl, widgetCssUrl, widgetScriptUrl),
        [normalizedConfig, widgetApiBaseUrl, widgetCssUrl, widgetScriptUrl],
    );

    const newFaqError = useMemo(() => {
        const value = newFaq.trim();
        if (!value) return '';
        if (config.faqSuggestions.length >= MAX_FAQ_COUNT) return `Max ${MAX_FAQ_COUNT} suggestions allowed.`;
        if (value.length > MAX_FAQ_LENGTH) return `Use ${MAX_FAQ_LENGTH} characters or fewer.`;
        if (config.faqSuggestions.some((faq) => faq.trim().toLowerCase() === value.toLowerCase())) {
            return 'This suggestion already exists.';
        }
        return '';
    }, [newFaq, config.faqSuggestions]);

    useEffect(() => {
        const handleBeforeUnload = (event: BeforeUnloadEvent) => {
            if (!hasUnsavedChanges) return;
            event.preventDefault();
            event.returnValue = '';
        };

        window.addEventListener('beforeunload', handleBeforeUnload);
        return () => window.removeEventListener('beforeunload', handleBeforeUnload);
    }, [hasUnsavedChanges]);

    const handleSave = async () => {
        const nextConfig = normalizeConfig(config);
        if (configValidationErrors.length > 0) {
            showToast(configValidationErrors[0], 'error');
            return;
        }

        try {
            setIsSaving(true);
            const payload = {
                title: nextConfig.title,
                primary_color: nextConfig.primaryColor,
                welcome_message: nextConfig.welcomeMessage,
                faq_suggestions: nextConfig.faqSuggestions
            };
            await apiClient.post('/settings/chat/', payload);
            setConfig(nextConfig);
            setSavedConfig(nextConfig);
            showToast('Settings saved successfully', 'success');
        } catch (error) {
            console.error('Failed to save chat settings:', error);
            showToast('Failed to save settings', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const handleAddFaq = () => {
        const value = newFaq.trim();
        if (newFaqError) {
            showToast(newFaqError, 'error');
            return;
        }
        if (value) {
            setConfig({
                ...config,
                faqSuggestions: [...config.faqSuggestions, value]
            });
            setNewFaq('');
        }
    };

    const handleRemoveFaq = (index: number) => {
        const newFaqs = [...config.faqSuggestions];
        newFaqs.splice(index, 1);
        setConfig({ ...config, faqSuggestions: newFaqs });
    };

    const handleBannerUpload = async (file: File) => {
        try {
            setIsBannerUploading(true);
            const formData = new FormData();
            formData.append('file', file);
            const uploadResponse = await apiClient.post<{ image_url: string }>(
                '/banners/upload',
                formData,
                {
                    headers: { 'Content-Type': 'multipart/form-data' }
                }
            );

            const imageUrl = uploadResponse.data?.image_url;
            if (!imageUrl) {
                throw new Error('Upload failed');
            }

            const nextOrder = banners.reduce((max, banner) => Math.max(max, banner.sort_order || 0), 0) + 1;
            const altText = file.name.replace(/\.[^.]+$/, '');
            const createPayload = {
                image_url: imageUrl,
                link_url: '',
                alt_text: altText,
                is_active: true,
                sort_order: nextOrder
            };
            const createResponse = await apiClient.post<Banner>('/banners/', createPayload);
            const created = createResponse.data;
            setBanners((prev) => [...prev, created]);
            setSavedBannersById((prev) => ({ ...prev, [created.id]: normalizeBanner(created) }));
            showToast('Banner uploaded', 'success');
        } catch (error) {
            console.error('Failed to upload banner:', error);
            showToast('Failed to upload banner', 'error');
        } finally {
            setIsBannerUploading(false);
        }
    };

    const handleBannerChange = (id: number, updates: Partial<Banner>) => {
        setBanners((prev) =>
            prev.map((banner) => (banner.id === id ? { ...banner, ...updates } : banner))
        );
    };

    const handleBannerSave = async (banner: Banner) => {
        if (!isValidOptionalHttpUrl(banner.link_url)) {
            showToast('Banner link must be a valid http or https URL', 'error');
            return;
        }

        try {
            setBannerSavingId(banner.id);
            const payload = {
                id: banner.id,
                image_url: banner.image_url,
                link_url: banner.link_url || '',
                alt_text: banner.alt_text || '',
                is_active: banner.is_active,
                sort_order: banner.sort_order
            };
            const response = await apiClient.post<Banner>('/banners/', payload);
            const updated = response.data;
            setBanners((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
            setSavedBannersById((prev) => ({ ...prev, [updated.id]: normalizeBanner(updated) }));
            showToast('Banner saved', 'success');
        } catch (error) {
            console.error('Failed to save banner:', error);
            showToast('Failed to save banner', 'error');
        } finally {
            setBannerSavingId(null);
        }
    };

    const handleBannerDelete = async (bannerId: number) => {
        const banner = banners.find((item) => item.id === bannerId);
        const label = banner?.alt_text || banner?.image_url || `banner ${bannerId}`;
        if (!window.confirm(`Delete "${label}"? This cannot be undone.`)) {
            return;
        }

        try {
            await apiClient.delete(`/banners/${bannerId}`);
            setBanners((prev) => prev.filter((banner) => banner.id !== bannerId));
            setSavedBannersById((prev) => {
                const next = { ...prev };
                delete next[bannerId];
                return next;
            });
            showToast('Banner deleted', 'success');
        } catch (error) {
            console.error('Failed to delete banner:', error);
            showToast('Failed to delete banner', 'error');
        }
    };

    const persistBannerOrder = async (nextBanners: Banner[]) => {
        setIsBannerReordering(true);
        try {
            const changedBanners = nextBanners.filter((banner) => {
                const current = banners.find((item) => item.id === banner.id);
                return current?.sort_order !== banner.sort_order;
            });

            await Promise.all(
                changedBanners.map((banner) =>
                    apiClient.post<Banner>('/banners/', {
                        id: banner.id,
                        image_url: banner.image_url,
                        link_url: banner.link_url || '',
                        alt_text: banner.alt_text || '',
                        is_active: banner.is_active,
                        sort_order: banner.sort_order,
                    })
                )
            );
            setBanners(nextBanners);
            setSavedBannersById(
                Object.fromEntries(nextBanners.map((banner) => [banner.id, normalizeBanner(banner)]))
            );
            showToast('Banner order updated', 'success');
        } catch (error) {
            console.error('Failed to reorder banners:', error);
            showToast('Failed to update banner order', 'error');
        } finally {
            setIsBannerReordering(false);
        }
    };

    const handleMoveBanner = async (bannerId: number, direction: 'up' | 'down') => {
        if (dirtyBannerCount > 0) {
            showToast('Save or discard banner edits before changing order', 'error');
            return;
        }

        const currentIndex = sortedBanners.findIndex((banner) => banner.id === bannerId);
        const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
        if (currentIndex < 0 || targetIndex < 0 || targetIndex >= sortedBanners.length) return;

        const reordered = [...sortedBanners];
        [reordered[currentIndex], reordered[targetIndex]] = [reordered[targetIndex], reordered[currentIndex]];
        const nextBanners = reordered.map((banner, index) => ({ ...banner, sort_order: index + 1 }));
        await persistBannerOrder(nextBanners);
    };

    // Mock website content for preview
    const MockWebsiteBackground = () => (
        <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none opacity-20">
            {/* Fake Header */}
            <div className="h-16 border-b border-gray-200 flex items-center px-8 justify-between bg-white">
                <div className="w-24 h-6 bg-gray-300 rounded"></div>
                <div className="flex gap-4">
                    <div className="w-16 h-4 bg-gray-200 rounded"></div>
                    <div className="w-16 h-4 bg-gray-200 rounded"></div>
                    <div className="w-16 h-4 bg-gray-200 rounded"></div>
                </div>
            </div>
            {/* Fake Hero */}
            <div className="p-8">
                <div className="w-2/3 h-12 bg-gray-300 rounded mb-4"></div>
                <div className="w-1/2 h-8 bg-gray-200 rounded mb-8"></div>
                <div className="grid grid-cols-3 gap-4">
                    <div className="h-32 bg-gray-100 rounded"></div>
                    <div className="h-32 bg-gray-100 rounded"></div>
                    <div className="h-32 bg-gray-100 rounded"></div>
                </div>
            </div>
        </div>
    );

    const handleCopyCode = () => {
        navigator.clipboard.writeText(embedCode);
        showToast('Embed code copied to clipboard!', 'success');
    };

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
                <div className="min-h-[20px] text-sm">
                    {hasUnsavedChanges ? (
                        <span className="font-medium text-amber-700">Unsaved changes</span>
                    ) : (
                        <span className="text-gray-400">All changes saved</span>
                    )}
                </div>
                <Button
                    onClick={handleSave}
                    isLoading={isSaving}
                    disabled={!hasConfigChanges || hasInvalidConfig}
                    className="shadow-md"
                >
                    Save Settings
                </Button>
            </div>
            {configValidationErrors.length > 0 && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {configValidationErrors[0]}
                </div>
            )}

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
                <div className="xl:col-span-4 space-y-6">
                    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                        <div className="flex items-center gap-2 border-b border-gray-100 p-6 bg-white">
                            <div className="p-2 bg-indigo-50 rounded-lg text-indigo-600">
                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                                </svg>
                            </div>
                            <h2 className="text-lg font-semibold text-gray-900">Appearance</h2>
                        </div>

                        <div className="p-6 space-y-6">
                            <div className="space-y-4">
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Widget Title
                                    </label>
                                    <input
                                        type="text"
                                        value={config.title}
                                        onChange={(e) => setConfig({ ...config, title: e.target.value })}
                                        className="w-full rounded-lg border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                                        placeholder="e.g. Chat Support"
                                    />
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Primary Color
                                    </label>
                                    <div className="flex items-center gap-3">
                                        <div className="relative">
                                            <input
                                                type="color"
                                                value={isValidHexColor(config.primaryColor) ? config.primaryColor : DEFAULT_PRIMARY_COLOR}
                                                onChange={(e) => setConfig({ ...config, primaryColor: e.target.value })}
                                                className="h-10 w-10 rounded-lg border border-gray-200 cursor-pointer overflow-hidden p-0"
                                            />
                                            <div
                                                className="absolute inset-0 pointer-events-none rounded-lg border border-black/10"
                                                style={{ boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.1)' }}
                                            />
                                        </div>
                                        <input
                                            type="text"
                                            value={config.primaryColor}
                                            onChange={(e) => setConfig({ ...config, primaryColor: e.target.value })}
                                            className={`flex-1 rounded-lg shadow-sm focus:ring-indigo-500 font-mono text-sm uppercase ${
                                                isValidHexColor(config.primaryColor)
                                                    ? 'border-gray-300 focus:border-indigo-500'
                                                    : 'border-red-300 focus:border-red-500'
                                            }`}
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Welcome Message
                                    </label>
                                    <textarea
                                        value={config.welcomeMessage}
                                        onChange={(e) => setConfig({ ...config, welcomeMessage: e.target.value })}
                                        rows={3}
                                        className="w-full rounded-lg border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                                        placeholder="e.g. Hi there!"
                                    />
                                </div>
                            </div>

                            <div className="pt-4 border-t border-gray-100">
                                <label className="block text-sm font-medium text-gray-900 mb-2">
                                    Flex Message Buttons (FAQ)
                                </label>
                                <div className="space-y-3">
                                    <div className="flex gap-2">
                                        <input
                                            type="text"
                                            value={newFaq}
                                            onChange={(e) => setNewFaq(e.target.value)}
                                            placeholder="Add suggestion..."
                                            className={`flex-1 rounded-lg shadow-sm focus:ring-indigo-500 text-sm ${
                                                newFaqError ? 'border-red-300 focus:border-red-500' : 'border-gray-300 focus:border-indigo-500'
                                            }`}
                                            onKeyDown={(e) => e.key === 'Enter' && handleAddFaq()}
                                        />
                                        <Button onClick={handleAddFaq} size="sm" disabled={!newFaq.trim() || Boolean(newFaqError)}>
                                            Add
                                        </Button>
                                    </div>
                                    {newFaqError && <p className="text-xs text-red-600">{newFaqError}</p>}

                                    <div className="flex flex-wrap gap-2">
                                        {config.faqSuggestions.map((faq, index) => (
                                            <div key={index} className="inline-flex items-center gap-1 bg-indigo-50 text-indigo-700 px-3 py-1 rounded-full text-xs border border-indigo-100">
                                                <span>{faq}</span>
                                                <button
                                                    onClick={() => handleRemoveFaq(index)}
                                                    className="hover:text-indigo-900 focus:outline-none ml-1"
                                                >
                                                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                                    </svg>
                                                </button>
                                            </div>
                                        ))}
                                        {config.faqSuggestions.length === 0 && (
                                            <span className="text-xs text-gray-400 italic">No suggestions added.</span>
                                        )}
                                    </div>
                                    <p className="text-xs text-gray-400">
                                        Max {MAX_FAQ_COUNT} buttons. Each suggestion can be up to {MAX_FAQ_LENGTH} characters.
                                    </p>
                                </div>
                            </div>

                            <div className="pt-4 border-t border-gray-100">
                                <div className="bg-gray-900 rounded-xl shadow-lg p-6 relative overflow-hidden group">
                                    <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
                                        <svg className="w-24 h-24 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                                        </svg>
                                    </div>
                                    <div className="flex justify-between items-center mb-4 relative z-10">
                                        <h3 className="text-white font-medium flex items-center gap-2 text-sm">
                                            <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 8a2 2 0 11-4 0 2 2 0 014 0zM17.942 20.942A2 2 0 0019.5 18a2 2 0 00-1.558-2.942A6 6 0 0011.5 5.5V19h-1a2 2 0 00-2 2z" />
                                            </svg>
                                            Embed Code
                                        </h3>
                                        <Button size="sm" onClick={handleCopyCode} variant="secondary" className="bg-indigo-600 hover:bg-indigo-700 text-white border-none text-xs py-1 px-2 h-auto">
                                            Copy
                                        </Button>
                                    </div>
                                    <div className="bg-gray-800/50 backdrop-blur rounded-lg p-3 font-mono text-[10px] text-indigo-200 overflow-x-auto whitespace-pre border border-white/5">
                                        {embedCode}
                                    </div>
                                    <p className="mt-3 text-[10px] text-gray-500">
                                        Paste before <code className="text-indigo-400">&lt;/body&gt;</code>.
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                        <div className="flex items-center justify-between border-b border-gray-100 p-6 bg-white">
                            <div className="flex items-center gap-2">
                                <div className="p-2 bg-emerald-50 rounded-lg text-emerald-600">
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5h16M4 12h16M4 19h16" />
                                    </svg>
                                </div>
                                <h2 className="text-lg font-semibold text-gray-900">Promotional Banners</h2>
                            </div>
                            <label
                                className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold border border-emerald-200 text-emerald-700 bg-emerald-50 hover:bg-emerald-100 transition-colors cursor-pointer ${isBannerUploading ? 'opacity-50 pointer-events-none' : ''}`}
                            >
                                <input
                                    type="file"
                                    accept="image/*"
                                    className="hidden"
                                    onChange={(event) => {
                                        const file = event.target.files?.[0];
                                        if (file) {
                                            handleBannerUpload(file);
                                        }
                                        event.currentTarget.value = '';
                                    }}
                                />
                                {isBannerUploading ? 'Uploading...' : 'Upload'}
                            </label>
                        </div>

                        <div className="p-6 space-y-4">
                            {isBannerLoading ? (
                                <div className="flex items-center justify-center h-24">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-500"></div>
                                </div>
                            ) : (
                                <>
                                    {sortedBanners.map((banner, index) => {
                                        const bannerDirty = bannerHasChanges(banner);
                                        const bannerUrlInvalid = !isValidOptionalHttpUrl(banner.link_url);
                                        return (
                                        <div key={banner.id} className="border border-gray-200 rounded-xl p-4 space-y-3">
                                            <div className="flex items-start gap-4">
                                                <div className="w-24 aspect-[3/2] rounded-lg border border-gray-200 overflow-hidden bg-gray-50 flex items-center justify-center">
                                                    {banner.image_url ? (
                                                        <img
                                                            src={banner.image_url}
                                                            alt={banner.alt_text || 'Banner'}
                                                            className="w-full h-full object-cover"
                                                        />
                                                    ) : (
                                                        <span className="text-xs text-gray-400">No image</span>
                                                    )}
                                                </div>
                                                <div className="flex-1 space-y-2">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <div className="flex items-center gap-1.5">
                                                            <button
                                                                type="button"
                                                                onClick={() => handleMoveBanner(banner.id, 'up')}
                                                                disabled={index === 0 || isBannerReordering}
                                                                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                                                                title="Move banner up"
                                                            >
                                                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                                                                </svg>
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={() => handleMoveBanner(banner.id, 'down')}
                                                                disabled={index === sortedBanners.length - 1 || isBannerReordering}
                                                                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                                                                title="Move banner down"
                                                            >
                                                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                                                </svg>
                                                            </button>
                                                        </div>
                                                        {bannerDirty && (
                                                            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                                                                Unsaved
                                                            </span>
                                                        )}
                                                    </div>
                                                    <input
                                                        type="text"
                                                        value={banner.link_url || ''}
                                                        onChange={(event) => handleBannerChange(banner.id, { link_url: event.target.value })}
                                                        className={`w-full rounded-lg shadow-sm focus:ring-emerald-500 text-sm ${
                                                            bannerUrlInvalid
                                                                ? 'border-red-300 focus:border-red-500'
                                                                : 'border-gray-300 focus:border-emerald-500'
                                                        }`}
                                                        placeholder="Link URL (optional)"
                                                    />
                                                    {bannerUrlInvalid && (
                                                        <p className="text-xs text-red-600">Use a valid http or https URL.</p>
                                                    )}
                                                    <input
                                                        type="text"
                                                        value={banner.alt_text || ''}
                                                        onChange={(event) => handleBannerChange(banner.id, { alt_text: event.target.value })}
                                                        className="w-full rounded-lg border-gray-300 shadow-sm focus:border-emerald-500 focus:ring-emerald-500 text-sm"
                                                        placeholder="Alt text"
                                                    />
                                                    <div className="flex flex-wrap items-center gap-4 text-xs text-gray-600">
                                                        <label className="flex items-center gap-2">
                                                            <input
                                                                type="checkbox"
                                                                checked={banner.is_active}
                                                                onChange={(event) => handleBannerChange(banner.id, { is_active: event.target.checked })}
                                                                className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                                                            />
                                                            Active
                                                        </label>
                                                        <div className="flex items-center gap-2">
                                                            <span>Order</span>
                                                            <input
                                                                type="number"
                                                                value={banner.sort_order}
                                                                onChange={(event) => handleBannerChange(banner.id, { sort_order: Number(event.target.value) })}
                                                                className="w-20 rounded-lg border-gray-300 shadow-sm focus:border-emerald-500 focus:ring-emerald-500 text-xs"
                                                            />
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="flex flex-col gap-2">
                                                    <Button
                                                        size="sm"
                                                        onClick={() => handleBannerSave(banner)}
                                                        isLoading={bannerSavingId === banner.id}
                                                        disabled={!bannerDirty || bannerUrlInvalid}
                                                        className="shadow-none"
                                                    >
                                                        Save
                                                    </Button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleBannerDelete(banner.id)}
                                                        className="text-xs font-semibold text-red-600 hover:text-red-700"
                                                    >
                                                        Delete
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                        );
                                    })}
                                    {sortedBanners.length === 0 && (
                                        <div className="text-sm text-gray-500">
                                            No banners uploaded yet. Upload a banner to show it in the widget carousel.
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </div>

                <div className="xl:col-span-8 sticky top-6 h-[calc(100vh-48px)]">
                    <div className="bg-gray-100 rounded-2xl border border-gray-200 h-full relative overflow-hidden shadow-inner flex flex-col">
                        <div className="absolute inset-0 bg-gradient-to-br from-gray-50 to-white">
                            <MockWebsiteBackground />
                        </div>

                        <div className="absolute top-4 left-1/2 transform -translate-x-1/2 bg-white/80 backdrop-blur px-4 py-1.5 rounded-full shadow-sm border border-gray-200 text-xs font-semibold text-gray-500 flex items-center gap-2 z-10">
                            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                            Live Preview
                        </div>

                        <div className="flex-1 overflow-hidden relative">
                            <ChatWidget
                                isInline={true}
                                title={config.title}
                                primaryColor={config.primaryColor}
                                welcomeMessage={config.welcomeMessage}
                                faqSuggestions={config.faqSuggestions}
                                apiBaseUrl={widgetApiBaseUrl}
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
