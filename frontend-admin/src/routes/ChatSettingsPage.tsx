import React, { useState, useEffect, useMemo } from 'react';
import { useToast } from '../hooks/useToast';
import { Button } from '../components/common/Button';
import { ChatWidget } from '../components/chat/ChatWidget';
import apiClient from '../api/client';

export const ChatSettingsPage: React.FC = () => {
    const { showToast } = useToast();
    const widgetOrigin = (import.meta.env.VITE_WIDGET_ORIGIN || 'http://localhost:8000').replace(/\/+$/, '');
    const widgetApiBaseUrl = `${widgetOrigin}/api/v1`;
    const widgetScriptUrl = `${widgetOrigin}/static/widget.js`;
    const widgetCssUrl = `${widgetOrigin}/static/widget.css`;

    const [config, setConfig] = useState({
        title: 'Jewelry Assistant',
        primaryColor: '#214166', // Medium Blue
        welcomeMessage: 'Welcome to our wholesale body jewelry support! 👋 How can I help you today?',
        faqSuggestions: [
            "What is your minimum order?",
            "Do you offer custom designs?",
            "What materials do you use?"
        ]
    });

    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [newFaq, setNewFaq] = useState('');

    interface Banner {
        id: number;
        image_url: string;
        link_url?: string | null;
        alt_text?: string | null;
        is_active: boolean;
        sort_order: number;
    }

    const [banners, setBanners] = useState<Banner[]>([]);
    const [isBannerLoading, setIsBannerLoading] = useState(true);
    const [isBannerUploading, setIsBannerUploading] = useState(false);
    const [bannerSavingId, setBannerSavingId] = useState<number | null>(null);

    const fetchBanners = async () => {
        try {
            setIsBannerLoading(true);
            const response = await apiClient.get<Banner[]>('/banners/', {
                params: { include_inactive: true }
            });
            setBanners(response.data || []);
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
                    setConfig({
                        title: response.data.title || 'Jewelry Assistant',
                        primaryColor: response.data.primary_color || '#214166',
                        welcomeMessage: response.data.welcome_message || '',
                        faqSuggestions: response.data.faq_suggestions || []
                    });
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

    const handleSave = async () => {
        try {
            setIsSaving(true);
            const payload = {
                title: config.title,
                primary_color: config.primaryColor,
                welcome_message: config.welcomeMessage,
                faq_suggestions: config.faqSuggestions
            };
            await apiClient.post('/settings/chat/', payload);
            showToast('Settings saved successfully!', 'success');
        } catch (error) {
            console.error('Failed to save chat settings:', error);
            showToast('Failed to save settings', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    const handleAddFaq = () => {
        if (newFaq.trim() && config.faqSuggestions.length < 5) {
            setConfig({
                ...config,
                faqSuggestions: [...config.faqSuggestions, newFaq.trim()]
            });
            setNewFaq('');
        } else if (config.faqSuggestions.length >= 5) {
            showToast('Max 5 suggestions allowed', 'error');
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
            showToast('Banner saved', 'success');
        } catch (error) {
            console.error('Failed to save banner:', error);
            showToast('Failed to save banner', 'error');
        } finally {
            setBannerSavingId(null);
        }
    };

    const handleBannerDelete = async (bannerId: number) => {
        try {
            await apiClient.delete(`/banners/${bannerId}`);
            setBanners((prev) => prev.filter((banner) => banner.id !== bannerId));
            showToast('Banner deleted', 'success');
        } catch (error) {
            console.error('Failed to delete banner:', error);
            showToast('Failed to delete banner', 'error');
        }
    };

    const sortedBanners = useMemo(() => {
        return [...banners].sort((a, b) => {
            const orderDiff = (a.sort_order || 0) - (b.sort_order || 0);
            if (orderDiff !== 0) return orderDiff;
            return a.id - b.id;
        });
    }, [banners]);

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
        const scriptCode = `
<!-- GenAI Chat Widget -->
<link rel="stylesheet" href="${widgetCssUrl}">
<script>
  window.genaiConfig = {
    title: "${config.title}",
    primaryColor: "${config.primaryColor}",
    welcomeMessage: "${config.welcomeMessage}",
    faqSuggestions: ${JSON.stringify(config.faqSuggestions)},
    apiBaseUrl: "${widgetApiBaseUrl}"
  };
</script>
<script src="${widgetScriptUrl}" async></script>
<!-- End GenAI Chat Widget -->`;

        navigator.clipboard.writeText(scriptCode);
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
            <div className="sticky top-0 z-20 -mx-4 md:-mx-6 px-4 md:px-6 py-4 bg-gray-50/95 backdrop-blur border-b border-gray-200">
                <div className="flex justify-between items-center">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900 tracking-tight">Chat Setting</h1>
                        <p className="mt-2 text-gray-600">
                            Customize your AI assistant's appearance and behavior.
                        </p>
                    </div>
                    <Button
                        onClick={handleSave}
                        isLoading={isSaving}
                        className="shadow-md"
                    >
                        Save Settings
                    </Button>
                </div>
            </div>

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
                                                value={config.primaryColor}
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
                                            className="flex-1 rounded-lg border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 font-mono text-sm uppercase"
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
                                            className="flex-1 rounded-lg border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-sm"
                                            onKeyPress={(e) => e.key === 'Enter' && handleAddFaq()}
                                        />
                                        <Button onClick={handleAddFaq} size="sm" disabled={config.faqSuggestions.length >= 5}>
                                            Add
                                        </Button>
                                    </div>

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
                                        Max 5 buttons. Users can tap these for quick answers.
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
                                        {`<!-- GenAI Chat Widget -->
<link rel="stylesheet" href="${widgetCssUrl}">
<script>
window.genaiConfig = {
title: "${config.title}",
primaryColor: "${config.primaryColor}",
welcomeMessage: "${config.welcomeMessage}",
faqSuggestions: ${JSON.stringify(config.faqSuggestions)},
apiBaseUrl: "${widgetApiBaseUrl}"
};
</script>
<script src="${widgetScriptUrl}" async></script>`}
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
                                    {sortedBanners.map((banner) => (
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
                                                    <input
                                                        type="text"
                                                        value={banner.link_url || ''}
                                                        onChange={(event) => handleBannerChange(banner.id, { link_url: event.target.value })}
                                                        className="w-full rounded-lg border-gray-300 shadow-sm focus:border-emerald-500 focus:ring-emerald-500 text-sm"
                                                        placeholder="Link URL (optional)"
                                                    />
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
                                    ))}
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
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
