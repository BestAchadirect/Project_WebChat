import React, { useState, useEffect, useRef } from 'react';
import apiClient from '../../api/client';

interface Message {
    role: 'user' | 'assistant' | 'system';
    content: string;
    carouselMsg?: string;
    productCarousel?: ProductCard[];
    viewButtonText?: string;
    materialLabel?: string;
    jewelryTypeLabel?: string;
    followUpQuestions?: string[];  // Add follow-up questions support
    qaLogId?: string;
    feedbackValue?: 1 | -1;
    feedbackPending?: boolean;
}

interface KnowledgeSource {
    source_id: string;
    chunk_id?: string | null;
    title: string;
    content_snippet: string;
    category?: string | null;
    relevance: number;
    url?: string | null;
    distance?: number | null;
}

interface ChatResponse {
    conversation_id: number;
    reply_text: string;
    carousel_msg?: string;
    product_carousel: ProductCard[];
    follow_up_questions: string[];
    intent: string;
    sources?: KnowledgeSource[];
    view_button_text?: string;
    material_label?: string;
    jewelry_type_label?: string;
    qa_log_id?: string | null;
}

interface ChatHistoryMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
    product_data?: ProductCard[] | null;
    created_at?: string | null;
}

interface ChatHistoryResponse {
    conversation_id: number;
    messages: ChatHistoryMessage[];
}

interface ActiveConversationResponse {
    conversation_id: number | null;
}

interface ProductCard {
    id: string;
    object_id?: string | null;
    sku: string;
    legacy_sku?: string[];
    name: string;
    description?: string | null;
    price: number;
    currency: string;
    stock_status?: string | null;
    image_url?: string | null;
    product_url?: string | null;
    attributes?: Record<string, any>;
}

interface BannerItem {
    id: number;
    image_url: string;
    link_url?: string | null;
    alt_text?: string | null;
    sort_order?: number;
}

interface ChatWidgetProps {
    isInline?: boolean;
    title?: string;
    primaryColor?: string;
    welcomeMessage?: string;
    faqSuggestions?: string[]; // New prop for Flex Message chips
    apiBaseUrl?: string;
    reportUrl?: string;
    locale?: string;
    customerName?: string;
    email?: string;
    customerId?: string | number;
}

interface Ticket {
    id: number;
    description: string;
    image_url?: string;
    image_urls?: string[];
    status: string;
    ai_summary?: string;
    admin_reply?: string;
    admin_replies?: Array<{
        message: string;
        created_at?: string;
    }>;
    customer_last_activity_at?: string;
    admin_last_seen_at?: string;
    created_at: string;
}

declare global {
    interface Window {
        genaiConfig?: {
            title?: string;
            primaryColor?: string;
            welcomeMessage?: string;
            faqSuggestions?: string[];
            apiBaseUrl?: string;
            apiUrl?: string;
            reportUrl?: string;
            displayCurrency?: string;
            thbToUsdRate?: number;
            locale?: string;
            customerName?: string;
            email?: string;
            customerId?: string | number;
        };
    }
}

// Custom styles for animations that Tailwind doesn't have out of the box
const customStyles = `
@keyframes pulse-shadow {
    0% { box-shadow: 0 0 0 0 rgba(12, 32, 56, 0.4); }
    70% { box-shadow: 0 0 0 15px rgba(12, 32, 56, 0); }
    100% { box-shadow: 0 0 0 0 rgba(12, 32, 56, 0); }
}
@keyframes fade-in {
    from { opacity: 0; }
    to { opacity: 1; }
}
@keyframes fade-in-up {
    from { opacity: 0; transform: translateY(15px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes bounce-slow {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-5px); }
}
.pulse-animation {
    animation: pulse-shadow 3s infinite;
}
.animate-fade-in {
    animation: fade-in 0.4s ease-out forwards;
}
.animate-fade-in-up {
    animation: fade-in-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
.animate-bounce-slow {
    animation: bounce-slow 2.5s infinite ease-in-out;
}
.scrollbar-custom::-webkit-scrollbar {
    width: 4px;
}
.scrollbar-custom::-webkit-scrollbar-track {
    background: transparent;
}
.scrollbar-custom::-webkit-scrollbar-thumb {
    background: #E2E8F0;
    border-radius: 10px;
}
.scrollbar-custom::-webkit-scrollbar-thumb:hover {
    background: #CBD5E0;
}
.scrollbar-hide::-webkit-scrollbar {
    display: none;
}
.scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
}
.typing-dot {
    animation: typing 1.4s infinite;
}
@keyframes typing {
    0%, 100% { opacity: 0.3; transform: scale(0.8); }
    50% { opacity: 1; transform: scale(1.1); }
}
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
`;

// Banner Carousel Component
const BannerCarousel: React.FC<{
    banners: BannerItem[];
    primaryColor: string;
    onBannerClick: () => void;
}> = ({ banners, primaryColor, onBannerClick }) => {
    const [currentSlide, setCurrentSlide] = useState(0);
    const [touchStart, setTouchStart] = useState(0);
    const [touchEnd, setTouchEnd] = useState(0);
    const hasMultiple = banners.length > 1;

    useEffect(() => {
        setCurrentSlide(0);
    }, [banners.length]);

    const handleTouchStart = (e: React.TouchEvent) => {
        setTouchStart(e.targetTouches[0].clientX);
    };

    const handleTouchMove = (e: React.TouchEvent) => {
        setTouchEnd(e.targetTouches[0].clientX);
    };

    const handleTouchEnd = () => {
        if (!touchStart || !touchEnd) return;

        const distance = touchStart - touchEnd;
        const isLeftSwipe = distance > 50;
        const isRightSwipe = distance < -50;

        if (isLeftSwipe && currentSlide < banners.length - 1) {
            setCurrentSlide(currentSlide + 1);
        }
        if (isRightSwipe && currentSlide > 0) {
            setCurrentSlide(currentSlide - 1);
        }

        setTouchStart(0);
        setTouchEnd(0);
    };

    useEffect(() => {
        if (!hasMultiple) return;
        const timer = setInterval(() => {
            setCurrentSlide((prev) => (prev + 1) % banners.length);
        }, 5000);
        return () => clearInterval(timer);
    }, [hasMultiple, banners.length]);

    if (banners.length === 0) {
        return null;
    }

    const handleBannerSelect = (banner: BannerItem) => {
        if (banner.link_url) {
            window.open(banner.link_url, '_blank', 'noopener,noreferrer');
            return;
        }
        onBannerClick();
    };

    return (
        <div className="mb-8">
            <div
                className="relative overflow-hidden rounded-2xl shadow-[0_8px_30px_rgb(0,0,0,0.06)] border border-gray-50"
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
            >
                <div
                    className="flex transition-transform duration-500 ease-out"
                    style={{ transform: `translateX(-${currentSlide * 100}%)` }}
                >
                    {banners.map((banner) => (
                        <div key={banner.id} className="w-full flex-shrink-0 bg-white">
                            <button
                                type="button"
                                onClick={() => handleBannerSelect(banner)}
                                className="w-full text-left transition-all active:scale-[0.99]"
                            >
                                <div className="w-full aspect-[3/1]">
                                    <img
                                        src={banner.image_url}
                                        alt={banner.alt_text || 'Promotional banner'}
                                        className="w-full h-full object-cover"
                                    />
                                </div>
                            </button>
                        </div>
                    ))}
                </div>
            </div>

            {hasMultiple && (
                <div className="flex justify-center gap-2 mt-3">
                    {banners.map((banner, index) => (
                        <button
                            key={banner.id}
                            onClick={() => setCurrentSlide(index)}
                            className={`h-1.5 rounded-1g transition-all ${index === currentSlide ? 'w-6' : 'w-1.5 opacity-30'}`}
                            style={{
                                backgroundColor: index === currentSlide ? primaryColor : '#9CA3AF'
                            }}
                            aria-label={`Go to slide ${index + 1}`}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};

const ProductCarousel: React.FC<{
    items: ProductCard[];
    primaryColor: string;
    displayCurrency: string;
    viewButtonText?: string;
    materialLabel?: string;
    jewelryTypeLabel?: string;
    thbToUsdRate?: number;
}> = ({ items, primaryColor, displayCurrency, viewButtonText, materialLabel, jewelryTypeLabel, thbToUsdRate }) => {
    if (!items || items.length === 0) return null;

    const formatPrice = (p: ProductCard) => {
        const currency = (p.currency || '').toUpperCase();
        const target = (displayCurrency || currency || 'USD').toUpperCase();
        if (target === 'USD' && currency === 'THB') {
            const rate = typeof thbToUsdRate === 'number' && thbToUsdRate > 0 ? thbToUsdRate : 1.0;
            const usd = p.price * rate;
            return `${usd.toFixed(2)} USD`;
        }
        if (target === 'USD' && currency === 'USD') {
            return `${p.price.toFixed(2)} USD`;
        }
        return `${Number.isFinite(p.price) ? p.price.toFixed(2) : p.price} ${currency || 'THB'}`;
    };

    const normalizeStockStatus = (status?: string | null): string => {
        return String(status || '').trim().toLowerCase().replace(/\s+/g, '_');
    };

    const isOutOfStock = (status?: string | null): boolean => {
        const normalized = normalizeStockStatus(status);
        return normalized === 'out_of_stock' || normalized === 'outofstock';
    };

    const stockLabel = (status?: string | null): string => {
        const normalized = normalizeStockStatus(status);
        if (!normalized || normalized === 'in_stock' || normalized === 'instock') {
            return 'In stock';
        }
        if (normalized === 'out_of_stock' || normalized === 'outofstock') {
            return 'Out of stock';
        }
        return String(status || 'Checking...');
    };

    const isHiddenAttributeValue = (value: any): boolean => {
        if (value === null || value === undefined) return true;
        if (typeof value === 'boolean') return value === false;
        if (typeof value === 'number') return !Number.isFinite(value);
        if (Array.isArray(value)) return value.length === 0;
        if (typeof value === 'object') return Object.keys(value).length === 0;
        if (typeof value === 'string') {
            const normalized = value.trim().toLowerCase();
            return normalized === '' || ['false', 'none', 'null', 'n/a', 'na', 'no'].includes(normalized);
        }
        return false;
    };

    const formatAttributeLabel = (key: string): string => {
        if (key === 'material') return materialLabel || 'Material';
        if (key === 'jewelry_type') return jewelryTypeLabel || 'Jewelry Type';
        return key
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (char) => char.toUpperCase());
    };

    const formatAttributeValue = (value: any): string => {
        if (typeof value === 'boolean') return value ? 'Yes' : 'No';
        if (Array.isArray(value)) return value.join(', ');
        if (typeof value === 'object' && value !== null) return JSON.stringify(value);
        return String(value);
    };

    const getVisibleAttributes = (attributes?: Record<string, any>) => {
        if (!attributes) return [];
        const blockedKeys = new Set(['master_code']);
        return Object.entries(attributes).filter(([key, value]) => !blockedKeys.has(key) && !isHiddenAttributeValue(value));
    };

    return (
        <div className="mt-3">
            <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-custom">
                {items.map((p) => {
                    const visibleAttributes = getVisibleAttributes(p.attributes);
                    return (
                    <div
                        key={p.id}
                        className="min-w-[240px] max-w-[240px] bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden hover:shadow-md transition-shadow flex flex-col"
                    >
                        {/* 1. Header for Image */}
                        <div className="h-[160px] bg-gray-50 flex items-center justify-center overflow-hidden border-b border-gray-50 group/img">
                            {p.image_url ? (
                                <a
                                    href={p.image_url.replace('/wholesale1_t/', '/wholesale1_b/')}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="w-full h-full flex items-center justify-center cursor-zoom-in"
                                    title="Click to view full image"
                                >
                                    <img src={p.image_url} alt={p.name} className="h-full w-full object-contain transition-transform group-hover/img:scale-105" />
                                </a>
                            ) : (
                                <div className="text-sm text-gray-400 font-medium">No image available</div>
                            )}
                        </div>

                        {/* 2. Body for Product name, SKU, Description */}
                        <div className="p-3 flex-1">
                            <h4 className="text-base font-bold text-gray-900 line-clamp-2 uppercase leading-tight mb-1" title={p.name}>
                                {p.name}
                            </h4>
                            <div className="text-xs font-mono text-gray-500 uppercase flex items-center gap-1.5 mb-2">
                                <span className="px-1.5 py-0.5 bg-gray-100 rounded text-[10px] font-black text-gray-600">SKU</span>
                                <span className="font-bold tracking-wider">{p.sku}</span>
                                {p.attributes?.master_code && (
                                    <>
                                        <span className="text-gray-300">|</span>
                                        <span className="font-medium">{p.attributes.master_code}</span>
                                    </>
                                )}
                            </div>
                            {p.description && (
                                <div className="text-sm text-gray-600 italic leading-snug">
                                    {p.description}
                                </div>
                            )}

                            {visibleAttributes.length > 0 && (
                                <div className="mt-3 pt-3 border-t border-gray-50 flex flex-wrap gap-2 text-xs uppercase font-bold tracking-wider">
                                    {visibleAttributes.map(([key, value]) => (
                                        <div
                                            key={`${p.id}-${key}`}
                                            className={key === 'jewelry_type'
                                                ? "bg-[#96D0E6]/20 text-[#214166] px-2.5 py-1.5 rounded-md"
                                                : "bg-gray-100 text-gray-600 px-2.5 py-1.5 rounded-md"}
                                        >
                                            {formatAttributeLabel(key)}: {formatAttributeValue(value)}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* 3. Sub body for Price and Stock number */}
                        <div className="px-3 py-2 bg-gray-50/50 border-t border-gray-100 flex items-center justify-between">
                            <div className="flex flex-col">
                                <span className="text-[10px] uppercase font-bold text-gray-400 leading-none mb-1">Price</span>
                                <span className="text-base font-black text-gray-900 leading-none">{formatPrice(p)}</span>
                            </div>
                            <div className="flex flex-col items-end">
                                <span className="text-[10px] uppercase font-bold text-gray-400 leading-none mb-1">Stock</span>
                                <span className={`text-xs font-bold px-2 py-0.5 rounded-lg ${isOutOfStock(p.stock_status) ? 'text-red-700 bg-red-100' : 'text-green-700 bg-green-100'}`}>
                                    {stockLabel(p.stock_status)}
                                </span>
                            </div>
                        </div>

                        {/* 4. Buttons for View the link */}
                        {p.product_url && (
                            <div className="p-2 bg-white">
                                <a
                                    href={p.product_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="block w-full text-center py-2 rounded-lg text-sm font-bold text-white transition-all transform active:scale-95 shadow-sm hover:brightness-110"
                                    style={{ backgroundColor: primaryColor }}
                                >
                                    {viewButtonText || "View Product Details"}
                                </a>
                            </div>
                        )}
                    </div>
                    );
                })}
            </div>
        </div>
    );
};

export const ChatWidget: React.FC<ChatWidgetProps> = ({
    isInline = false,
    title,
    primaryColor,
    welcomeMessage,
    faqSuggestions,
    apiBaseUrl,
    reportUrl,
    locale,
    customerName,
    email,
    customerId
}) => {
    // Colors from the design
    const colors = {
        darkBlue: '#0C2038',
        mediumBlue: '#214166',
        lightBlue: '#96D0E6',
        white: '#FFFFFF',
    };

    // Generate or retrieve Guest ID
    const getGuestUserId = () => {
        let userId = localStorage.getItem('genai_user_id') || localStorage.getItem('chat_user_id');
        if (!userId) {
            userId = `guest_${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem('genai_user_id', userId);
            localStorage.setItem('chat_user_id', userId);
        }
        return userId;
    };

    // Effective config
    const config = {
        title: title || window.genaiConfig?.title || 'Jewelry Assistant',
        primaryColor: primaryColor || window.genaiConfig?.primaryColor || colors.mediumBlue,
        welcomeMessage: welcomeMessage || window.genaiConfig?.welcomeMessage || 'Welcome to our wholesale body jewelry support! 👋 How can I help you today?',
        faqSuggestions: faqSuggestions || window.genaiConfig?.faqSuggestions || [
            "What is your minimum order?",
            "Do you offer custom designs?",
            "What materials do you use?"
        ],
        apiBaseUrl: (apiBaseUrl || window.genaiConfig?.apiBaseUrl || window.genaiConfig?.apiUrl || '').trim().replace(/\/+$/, ''),
        reportUrl: (reportUrl || window.genaiConfig?.reportUrl || '').trim(),
        locale: locale || window.genaiConfig?.locale || 'en-US',
        customerName: customerName || window.genaiConfig?.customerName,
        email: email || window.genaiConfig?.email,
        customerId: customerId ?? window.genaiConfig?.customerId,
        displayCurrency: window.genaiConfig?.displayCurrency || 'USD',
        thbToUsdRate: window.genaiConfig?.thbToUsdRate,
    };

    const resolvedUserId = (() => {
        const configured = config.customerId;
        if (configured !== undefined && configured !== null && String(configured).trim() !== '') {
            return `magento_${configured}`;
        }
        return getGuestUserId();
    })();

    const [isOpen, setIsOpen] = useState(false);
    const [activeTab, setActiveTab] = useState<'home' | 'chat' | 'report'>('home');
    const [messages, setMessages] = useState<Message[]>([]);
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
    const [isTicketsLoading, setIsTicketsLoading] = useState(false);
    const [lastCreatedTicket, setLastCreatedTicket] = useState<Ticket | null>(null);
    const [input, setInput] = useState('');
    const [isEditingTicket, setIsEditingTicket] = useState(false);
    const [editTicketDescription, setEditTicketDescription] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [mainImageUrl, setMainImageUrl] = useState<string | null>(null);
    const [conversationId, setConversationId] = useState<number | null>(() => {
        const raw = localStorage.getItem('genai_conversation_id') || localStorage.getItem('chat_conversation_id');
        const parsed = raw ? Number(raw) : NaN;
        return Number.isFinite(parsed) ? parsed : null;
    });
    const [activeUserId, setActiveUserId] = useState(resolvedUserId);
    const [banners, setBanners] = useState<BannerItem[]>([]);
    const [isBannerLoading, setIsBannerLoading] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const chatScrollRef = useRef<HTMLDivElement>(null);
    const isAtBottomRef = useRef(true);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [selectedImages, setSelectedImages] = useState<File[]>([]);
    const [selectedImageUrls, setSelectedImageUrls] = useState<string[]>([]);

    const formatTicketNumber = (ticket: Ticket) => {
        const year = new Date(ticket.created_at).getFullYear();
        return `${year}-${String(ticket.id).padStart(4, '0')}`;
    };

    const handleImageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const files = event.target.files;
        if (!files || files.length === 0) return;

        const newImages: File[] = [];
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            if (file.type.startsWith('image/')) {
                newImages.push(file);
            } else {
                alert(`File ${file.name} is not an image.`);
            }
        }

        if (newImages.length > 0) {
            setSelectedImages(prev => [...prev, ...newImages]);
        }

        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const clearSelectedImage = () => {
        setSelectedImages([]);
        setSelectedImageUrls([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    useEffect(() => {
        if (selectedImages.length === 0) {
            setSelectedImageUrls([]);
            return;
        }
        const urls = selectedImages.map(img => URL.createObjectURL(img));
        setSelectedImageUrls(urls);
        return () => urls.forEach(url => URL.revokeObjectURL(url));
    }, [selectedImages]);
    const [showScrollToLatest, setShowScrollToLatest] = useState(false);
    const hasHydratedRef = useRef(false);

    // Auto-scroll to bottom
    const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
        messagesEndRef.current?.scrollIntoView({ behavior });
    };

    const updateScrollState = () => {
        const container = chatScrollRef.current;
        if (!container) return;
        const threshold = 80;
        const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
        const atBottom = distanceFromBottom <= threshold;
        isAtBottomRef.current = atBottom;
        setShowScrollToLatest(!atBottom);
    };

    const loadConversationHistory = async () => {
        try {
            if (!resolvedUserId) return;
            const activeEndpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/chat/active` : '/chat/active';
            const { data: active } = await apiClient.get<ActiveConversationResponse>(activeEndpoint, {
                params: {
                    user_id: resolvedUserId,
                    conversation_id: conversationId ?? undefined,
                },
            });

            if (!active.conversation_id) {
                setConversationId(null);
                setMessages([]);
                localStorage.removeItem('genai_conversation_id');
                localStorage.removeItem('chat_conversation_id');
                return;
            }

            const activeId = active.conversation_id;
            if (activeId !== conversationId) {
                setConversationId(activeId);
                localStorage.setItem('genai_conversation_id', String(activeId));
                localStorage.setItem('chat_conversation_id', String(activeId));
            }

            const historyEndpoint = config.apiBaseUrl
                ? `${config.apiBaseUrl}/chat/history/${activeId}`
                : `/chat/history/${activeId}`;
            const { data: history } = await apiClient.get<ChatHistoryResponse>(historyEndpoint, {
                params: {
                    user_id: resolvedUserId,
                    limit: 50,
                },
            });

            const hydrated: Message[] = (history.messages || []).map((msg) => ({
                role: msg.role,
                content: msg.content,
                productCarousel: Array.isArray(msg.product_data) ? msg.product_data : undefined,
            }));
            setMessages(hydrated);
        } catch (error) {
            console.error('Failed to load conversation history:', error);
        }
    };

    useEffect(() => {
        if (!isOpen || activeTab !== 'chat') return;
        if (isAtBottomRef.current) {
            requestAnimationFrame(() => scrollToBottom());
        } else {
            requestAnimationFrame(() => updateScrollState());
        }
    }, [messages, isOpen, isLoading, activeTab]);

    useEffect(() => {
        if (activeTab !== 'chat') return;
        requestAnimationFrame(() => {
            scrollToBottom('auto');
            updateScrollState();
        });
    }, [activeTab, isOpen]);

    useEffect(() => {
        if (!isOpen || activeTab !== 'chat') return;
        if (hasHydratedRef.current) return;
        hasHydratedRef.current = true;
        void loadConversationHistory();
    }, [isOpen, activeTab, resolvedUserId, config.apiBaseUrl]);

    useEffect(() => {
        if (resolvedUserId === activeUserId) return;
        setActiveUserId(resolvedUserId);
        setConversationId(null);
        setMessages([]);
        localStorage.removeItem('genai_conversation_id');
        localStorage.removeItem('chat_conversation_id');
        hasHydratedRef.current = false;
    }, [resolvedUserId, activeUserId]);

    const fetchTickets = async () => {
        try {
            if (!resolvedUserId) return;
            setIsTicketsLoading(true);
            const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/tickets/` : '/tickets/';
            const { data } = await apiClient.get<Ticket[]>(endpoint, {
                params: { user_id: resolvedUserId }
            });
            setTickets(data || []);
        } catch (error) {
            console.error('Failed to fetch tickets:', error);
        } finally {
            setIsTicketsLoading(false);
        }
    };

    const submitTicketReport = async () => {
        if (!input.trim() || isLoading) return;
        setIsLoading(true);
        const descriptionText = input;
        const mainImagePreview = selectedImageUrls[0];
        try {
            const formData = new FormData();
            formData.append('user_id', resolvedUserId);
            formData.append('description', input);
            if (selectedImages.length > 0) {
                selectedImages.forEach(img => {
                    formData.append('images', img);
                });
            }

            const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/tickets/` : '/tickets/';
            const { data } = await apiClient.post<Ticket>(endpoint, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });

            setLastCreatedTicket({
                ...data,
                description: data.description || descriptionText,
                image_url: data.image_url || mainImagePreview || undefined,
            });
            setInput('');
            clearSelectedImage();
            fetchTickets();
            // Important: close the detail view if we're submitting from inside it
            setSelectedTicket(null);
        } catch (error) {
            console.error('Failed to submit report:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const handleUpdateTicket = async () => {
        if (!selectedTicket || isLoading) return;
        setIsLoading(true);
        try {
            const formData = new FormData();
            formData.append('actor', 'customer');
            if (editTicketDescription) {
                formData.append('description', editTicketDescription);
            }
            if (selectedImages.length > 0) {
                selectedImages.forEach(img => {
                    formData.append('images', img);
                });
            }

            const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/tickets/${selectedTicket.id}` : `/tickets/${selectedTicket.id}`;
            const { data } = await apiClient.patch<Ticket>(endpoint, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });

            // Update local state
            setSelectedTicket(data);
            setIsEditingTicket(false);
            clearSelectedImage();
            fetchTickets();
        } catch (error) {
            console.error('Failed to update ticket:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const handleOpenTicket = async (ticket: Ticket) => {
        setSelectedTicket(ticket);
        try {
            const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/tickets/${ticket.id}/customer-open` : `/tickets/${ticket.id}/customer-open`;
            const { data } = await apiClient.post<Ticket>(endpoint);
            setTickets(prev => prev.map(t => (t.id === ticket.id ? data : t)));
            setSelectedTicket(data);
            if (lastCreatedTicket?.id === ticket.id) {
                setLastCreatedTicket(data);
            }
        } catch (error) {
            console.error('Failed to mark ticket as opened:', error);
        }
    };

    useEffect(() => {
        if (isOpen && activeTab === 'report') {
            fetchTickets();
        }
    }, [isOpen, activeTab, resolvedUserId]);

    useEffect(() => {
        const fetchBanners = async () => {
            try {
                setIsBannerLoading(true);
                const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/banners/` : '/banners/';
                const { data } = await apiClient.get<BannerItem[]>(endpoint);
                const sorted = Array.isArray(data)
                    ? [...data].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))
                    : [];
                setBanners(sorted);
            } catch (error) {
                console.error('Failed to load banners:', error);
                setBanners([]);
            } finally {
                setIsBannerLoading(false);
            }
        };

        fetchBanners();
    }, [config.apiBaseUrl]);

    // Body scroll lock on mobile when open
    useEffect(() => {
        if (isOpen && window.innerWidth < 768) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
        return () => {
            document.body.style.overflow = '';
        };
    }, [isOpen]);

    useEffect(() => {
        if (selectedTicket) {
            setMainImageUrl(selectedTicket.image_url || (selectedTicket.image_urls?.[0] || null));
        } else {
            setMainImageUrl(null);
        }
    }, [selectedTicket]);

    // Adjust textarea height
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
        }
    }, [input]);

    const sendMessage = async (textOverride?: string) => {
        const textToSend = textOverride || input;
        if (!textToSend.trim() || isLoading) return;

        setMessages(prev => [...prev, { role: 'user', content: textToSend }]);
        setInput('');
        if (textareaRef.current) textareaRef.current.style.height = 'auto';
        setIsLoading(true);

        const formatSources = (sources: KnowledgeSource[]) =>
            `Sources:\n${sources
                .map((source) => `• ${source.title}${source.url ? ` (${source.url})` : ''}`)
                .join('\n')}`;

        try {
            const payload = {
                user_id: resolvedUserId,
                message: textToSend,
                conversation_id: conversationId,
                locale: config.locale,
                customer_name: config.customerName,
                email: config.email
            };

            const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/chat/` : '/chat/';
            const { data } = await apiClient.post<ChatResponse>(endpoint, payload);

            setConversationId(data.conversation_id);
            localStorage.setItem('genai_conversation_id', String(data.conversation_id));
            localStorage.setItem('chat_conversation_id', String(data.conversation_id));
            setMessages(prev => {
                const assistantMessage: Message = {
                    role: 'assistant',
                    content: data.reply_text,
                    carouselMsg: data.carousel_msg,
                    productCarousel: data.product_carousel || [],
                    viewButtonText: data.view_button_text,
                    materialLabel: data.material_label,
                    jewelryTypeLabel: data.jewelry_type_label,
                    followUpQuestions: data.follow_up_questions || [],
                    qaLogId: data.qa_log_id || undefined,
                };
                const updated: Message[] = [...prev, assistantMessage];
                return updated;
            });

            // Intentionally do not render sources in the chat window (kept in API response for debugging/analytics).
            if (data.sources && data.sources.length > 0) {
                void formatSources(data.sources);
            }

        } catch (error) {
            console.error('Chat error:', error);
            setMessages(prev => [...prev, {
                role: 'system',
                content: 'Sorry, something went wrong. Please try again.'
            }]);
        } finally {
            setIsLoading(false);
        }
    };

    const submitFeedback = async (messageIndex: number, qaLogId: string, feedback: 1 | -1) => {
        if (!qaLogId) return;
        const current = messages[messageIndex];
        if (!current || current.feedbackPending || current.feedbackValue !== undefined) return;

        setMessages(prev => prev.map((msg, idx) => (
            idx === messageIndex ? { ...msg, feedbackPending: true } : msg
        )));

        try {
            const endpoint = config.apiBaseUrl ? `${config.apiBaseUrl}/chat/feedback` : '/chat/feedback';
            await apiClient.post(endpoint, { qa_log_id: qaLogId, feedback });
            setMessages(prev => prev.map((msg, idx) => (
                idx === messageIndex ? { ...msg, feedbackValue: feedback, feedbackPending: false } : msg
            )));
        } catch (error) {
            console.error('Feedback submit error:', error);
            setMessages(prev => prev.map((msg, idx) => (
                idx === messageIndex ? { ...msg, feedbackPending: false } : msg
            )));
        }
    };

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // Determine container classes
    const containerClasses = isInline
        ? `absolute bottom-6 right-6 z-10 w-[380px] h-[600px] transition-all duration-300 ease-in-out transform ${isOpen ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-5 opacity-0 pointer-events-none'}`
        : `fixed inset-0 z-[1000] md:inset-auto md:bottom-[100px] md:right-[30px] md:w-[380px] md:h-[600px] transition-all duration-300 ease-in-out transform ${isOpen ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-full md:translate-y-5 opacity-0 pointer-events-none'}`;

    return (
        <div style={{ fontFamily: "'Poppins', sans-serif" }}>
            <style>{customStyles}</style>

            {/* Toggle Button */}
            {!isInline && (
                <div
                    onClick={() => setIsOpen(!isOpen)}
                    className={`fixed bottom-[30px] right-[30px] w-[64px] h-[64px] rounded-full text-white flex items-center justify-center cursor-pointer z-[1001] transition-all duration-500 ease-[cubic-bezier(0.19,1,0.22,1)] hover:scale-110 active:scale-95 shadow-[0_10px_25px_rgba(0,0,0,0.15)] hover:shadow-[0_15px_35px_rgba(0,0,0,0.2)] ${!isOpen ? 'pulse-animation' : ''}`}
                    style={{ backgroundColor: config.primaryColor }}
                >
                    {isOpen ? (
                        <svg className="w-6 h-6 animate-fade-in" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
                        </svg>
                    ) : (
                        <svg className="w-8 h-8 animate-fade-in" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M12 2C6.477 2 2 6.133 2 11.235c0 2.898 1.442 5.467 3.684 7.218l-1.121 3.51a.501.501 0 0 0 .762.555l4.352-2.825c.749.197 1.528.307 2.323.307 5.523 0 10-4.133 10-9.235S17.523 2 12 2zm0 16.47c-.714 0-1.411-.088-2.072-.255a.5.5 0 0 0-.411.084l-2.678 1.737.705-2.203a.5.5 0 0 0-.166-.499C5.353 15.79 4 13.633 4 11.235 4 7.245 7.589 4 12 4s8 3.245 8 7.235-3.589 7.235-8 7.235z" />
                        </svg>
                    )}
                </div>
            )}

            {/* Mock Toggle for Inline (Preview) Mode */}
            {isInline && !isOpen && (
                <div
                    onClick={() => setIsOpen(true)}
                    className={`absolute bottom-6 right-6 w-[64px] h-[64px] rounded-full text-white flex items-center justify-center cursor-pointer shadow-[0_10px_25px_rgba(0,0,0,0.1)] z-10 transition-all duration-300 hover:scale-110 active:scale-95 pulse-animation`}
                    style={{ backgroundColor: config.primaryColor }}
                >
                    <svg className="w-8 h-8" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M12 2C6.477 2 2 6.133 2 11.235c0 2.898 1.442 5.467 3.684 7.218l-1.121 3.51a.501.501 0 0 0 .762.555l4.352-2.825c.749.197 1.528.307 2.323.307 5.523 0 10-4.133 10-9.235S17.523 2 12 2zm0 16.47c-.714 0-1.411-.088-2.072-.255a.5.5 0 0 0-.411.084l-2.678 1.737.705-2.203a.5.5 0 0 0-.166-.499C5.353 15.79 4 13.633 4 11.235 4 7.245 7.589 4 12 4s8 3.245 8 7.235-3.589 7.235-8 7.235z" />
                    </svg>
                </div>
            )}

            {/* Chat Container */}
            {/* Chat Container */}
            <div className={`${containerClasses} bg-[#FCFCFE] rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-gray-100`}>
                {/* Header */}
                <div
                    className="relative px-4 py-3 sm:px-5 sm:py-4 text-white overflow-hidden shadow-sm"
                    style={{ backgroundColor: config.primaryColor }}
                >
                    <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-white/15 blur-2xl"></div>
                    <div className="absolute -left-8 -bottom-8 h-24 w-24 rounded-full bg-white/10 blur-2xl"></div>
                    <div className="flex items-center justify-between relative z-10">
                        {activeTab !== 'home' ? (
                            <button
                                onClick={() => {
                                    if (selectedTicket) {
                                        setSelectedTicket(null);
                                    } else {
                                        setActiveTab('home');
                                    }
                                }}
                                className="flex items-center gap-2 text-white/90 hover:text-white transition-colors bg-white/15 px-3 py-1.5 rounded-lg text-sm font-semibold"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 20 20" fill="currentColor">
                                    <path d="M12.9995 17.7115L5.28809 10L12.9995 2.28857L14.1198 3.40878L7.52829 10L14.1198 16.5913L12.9995 17.7115Z" />
                                </svg>
                                <span>Go back</span>
                            </button>
                        ) : (
                            <div className="flex items-center">
                                <div className="w-10 h-10 rounded-lg bg-white/20 flex items-center justify-center overflow-hidden border border-white/10 shadow-inner">
                                    <img
                                        src="https://www.achadirect.com/media/logo/default/logo-sq.png"
                                        alt="AchaDirect"
                                        className="w-full h-full object-cover"
                                        onError={(e) => {
                                            (e.target as HTMLImageElement).src = "https://ui-avatars.com/api/?name=AD&background=ffffff&color=0c2038";
                                        }}
                                    />
                                </div>
                                <div className="ml-3">
                                    <div className="text-white/80 text-[10px] uppercase font-bold tracking-widest mb-0.5">Acha Direct</div>
                                    <div className="flex items-center gap-1.5">
                                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse"></span>
                                        <span className="text-xs font-medium text-white/90">Online now</span>
                                    </div>
                                </div>
                            </div>
                        )}
                        <div className="flex items-center gap-2">
                            <button className="text-white/80 hover:text-white transition-colors p-2 rounded-lg">
                                <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
                                    <path d="M11.5 4C11.5 4.82843 10.8284 5.5 10 5.5C9.17157 5.5 8.5 4.82843 8.5 4C8.5 3.17157 9.17157 2.5 10 2.5C10.8284 2.5 11.5 3.17157 11.5 4Z" />
                                    <path d="M11.5 10C11.5 10.8284 10.8284 11.5 10 11.5C9.17157 11.5 8.5 10.8284 8.5 10C8.5 9.17157 8.5 8.5 10 8.5C10.8284 8.5 11.5 9.17157 11.5 10Z" />
                                    <path d="M10 17.5C10.8284 17.5 11.5 16.8284 11.5 16C11.5 15.1716 10.8284 14.5 10 14.5C9.17157 14.5 8.5 15.1716 8.5 16C8.5 16.8284 9.17157 17.5 10 17.5Z" />
                                </svg>
                            </button>
                            <button onClick={() => setIsOpen(false)} className="text-white/80 hover:text-white transition-colors bg-white/15 hover:bg-white/25 p-2 rounded-lg">
                                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.6} d="M19 9l-7 7-7-7" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>

                {/* Main View Container */}
                <div className="relative flex-1 bg-white overflow-hidden flex flex-col shadow-inner z-20">
                    {/* Home Tab */}
                    {activeTab === 'home' && (
                        <div className="flex-1 overflow-y-auto scrollbar-custom p-6 animate-fade-in-up pb-10">
                            {/* Sliding Banner Carousel */}
                            {isBannerLoading ? (
                                <div className="mb-8 w-full aspect-[4/1] rounded-2xl bg-gray-100 animate-pulse"></div>
                            ) : (
                                <BannerCarousel
                                    banners={banners}
                                    primaryColor={config.primaryColor}
                                    onBannerClick={() => setActiveTab('chat')}
                                />
                            )}

                            {/* Suggestions Slider */}
                            <div className="mt-4">
                                <h5 className="text-[10px] uppercase font-black text-gray-300 tracking-[0.2em] px-1 mb-3">Quick Links</h5>
                                <div className="space-y-2 px-1">
                                    {config.faqSuggestions.map((faq, idx) => (
                                        <button
                                            key={idx}
                                            onClick={() => {
                                                setActiveTab('chat');
                                                sendMessage(faq);
                                            }}
                                            className="w-full text-left px-4 py-3 bg-gray-50/80 hover:bg-gray-100 rounded-xl border border-gray-100 transition-all active:scale-95 shadow-sm"
                                        >
                                            <span className="text-sm font-bold text-gray-700">{faq}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Chat Tab */}
                    {activeTab === 'chat' && (
                        <div className="flex-1 flex flex-col overflow-hidden animate-fade-in bg-white h-full relative">
                            <div
                                ref={chatScrollRef}
                                onScroll={updateScrollState}
                                className="flex-1 overflow-y-auto p-4 scrollbar-custom pb-24"
                            >

                                {messages.length === 0 && (
                                    <div className="flex justify-start mb-6 animate-fade-in-up">
                                        <div className="bg-gray-50 border border-gray-100 p-4 rounded-lg shadow-sm max-w-[85%] text-sm font-medium text-gray-700 leading-relaxed">
                                            <p>{config.welcomeMessage}</p>
                                        </div>
                                    </div>
                                )}
                                {messages.map((msg, idx) => (
                                    <div key={idx} className={`flex flex-col mb-4 animate-fade-in-up ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                                        <div className="max-w-[85%]">
                                            <div
                                                className={`px-4 py-3 rounded-lg text-sm font-medium leading-relaxed ${msg.role === 'user'
                                                    ? 'text-white shadow-md'
                                                    : msg.role === 'system'
                                                        ? 'bg-red-50 text-red-600 border border-red-100'
                                                        : 'bg-gray-50 border border-gray-100 text-gray-800'
                                                    }`}
                                                style={msg.role === 'user' ? { backgroundColor: config.primaryColor } : {}}
                                            >
                                                <div className="whitespace-pre-wrap">{msg.content}</div>
                                            </div>
                                        </div>

                                        {msg.role === 'assistant' && msg.carouselMsg && (
                                            <div className="max-w-[90%] mt-2 px-4 py-2 bg-gray-100/50 text-gray-500 rounded-xl text-[11px] font-bold uppercase tracking-wider border border-gray-100/50">
                                                {msg.carouselMsg}
                                            </div>
                                        )}

                                        {msg.role === 'assistant' && msg.productCarousel && msg.productCarousel.length > 0 && (
                                            <div className="max-w-full w-full">
                                                <ProductCarousel
                                                    items={msg.productCarousel}
                                                    primaryColor={config.primaryColor}
                                                    displayCurrency={config.displayCurrency}
                                                    viewButtonText={msg.viewButtonText}
                                                    materialLabel={msg.materialLabel}
                                                    jewelryTypeLabel={msg.jewelryTypeLabel}
                                                    thbToUsdRate={config.thbToUsdRate}
                                                />
                                            </div>
                                        )}

                                        {/* Follow-up Questions / Quick Reply Slider */}
                                        {msg.role === 'assistant' && msg.followUpQuestions && msg.followUpQuestions.length > 0 && (
                                            <div className="w-full mt-3 overflow-hidden">
                                                <div className="flex gap-2 overflow-x-auto pb-4 px-1 scrollbar-hide">
                                                    {msg.followUpQuestions.map((question, qIdx) => (
                                                        <button
                                                            key={qIdx}
                                                            onClick={() => sendMessage(question)}
                                                            className="whitespace-nowrap flex-shrink-0 px-4 py-2 bg-white hover:bg-gray-50 text-gray-700 rounded-full text-xs font-bold transition-all border-2 shadow-sm hover:shadow-md active:scale-95 flex items-center gap-1.5"
                                                            style={{ borderColor: config.primaryColor }}
                                                        >
                                                            <span>{question}</span>
                                                            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5">
                                                                <path d="M7.5 6.175L8.675 5L13.675 10L8.675 15L7.5 13.825L11.3167 10L7.5 6.175Z" fill="currentColor" />
                                                            </svg>
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {msg.role === 'assistant' && msg.qaLogId && (
                                            <div className="mt-2 flex items-center gap-2 text-xs">
                                                <button
                                                    type="button"
                                                    disabled={msg.feedbackPending || msg.feedbackValue !== undefined}
                                                    onClick={() => submitFeedback(idx, msg.qaLogId as string, 1)}
                                                    className={`px-2 py-1 rounded-full border transition-colors ${msg.feedbackValue === 1 ? 'bg-green-100 border-green-300 text-green-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'} disabled:opacity-60 disabled:cursor-not-allowed`}
                                                >
                                                    Helpful
                                                </button>
                                                <button
                                                    type="button"
                                                    disabled={msg.feedbackPending || msg.feedbackValue !== undefined}
                                                    onClick={() => submitFeedback(idx, msg.qaLogId as string, -1)}
                                                    className={`px-2 py-1 rounded-full border transition-colors ${msg.feedbackValue === -1 ? 'bg-red-100 border-red-300 text-red-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'} disabled:opacity-60 disabled:cursor-not-allowed`}
                                                >
                                                    Not helpful
                                                </button>
                                                {msg.feedbackPending && (
                                                    <span className="text-gray-400">Saving...</span>
                                                )}
                                                {msg.feedbackValue !== undefined && !msg.feedbackPending && (
                                                    <span className="text-gray-500">Feedback saved</span>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                ))}


                                {isLoading && (
                                    <div className="flex justify-start mb-4 animate-fade-in">
                                        <div className="bg-gray-50 border border-gray-100 px-4 py-3 rounded-lg flex space-x-1.5 items-center h-[40px] shadow-sm">
                                            <span className="w-1.5 h-1.5 bg-gray-300 rounded-full typing-dot"></span>
                                            <span className="w-1.5 h-1.5 bg-gray-300 rounded-full typing-dot"></span>
                                            <span className="w-1.5 h-1.5 bg-gray-300 rounded-full typing-dot"></span>
                                        </div>
                                    </div>
                                )}
                                <div ref={messagesEndRef} />
                            </div>

                            {showScrollToLatest && (
                                <button
                                    type="button"
                                    onClick={() => scrollToBottom()}
                                    aria-label="Back to latest conversation"
                                    title="Back to latest"
                                    className="absolute bottom-24 right-4 z-20 inline-flex items-center justify-center rounded-full bg-white text-gray-700 shadow-md border border-gray-200 w-9 h-9 hover:bg-gray-50"
                                >
                                    <svg
                                        width="18"
                                        height="18"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        stroke="currentColor"
                                        strokeWidth="2"
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        aria-hidden="true"
                                    >
                                        <path d="M12 5v14" />
                                        <path d="m19 12-7 7-7-7" />
                                    </svg>
                                </button>
                            )}

                            {/* Input Group (Composer) */}
                            <div className="absolute bottom-0 left-0 right-0 z-10 px-4 pb-4 pt-3 bg-gradient-to-t from-white via-white/95 to-white/70 backdrop-blur">
                                <div className="rounded-2xl border border-gray-200/70 bg-white shadow-[0_10px_30px_rgba(0,0,0,0.06)]">
                                    <div className="flex items-end gap-3 px-4 pt-3">
                                        <textarea
                                            ref={textareaRef}
                                            value={input}
                                            onChange={(e) => setInput(e.target.value)}
                                            onKeyDown={handleKeyPress}
                                            placeholder="Enter your message..."
                                            rows={1}
                                            className="flex-1 bg-transparent border-none py-3 focus:outline-none resize-none min-h-[44px] max-h-[120px] scrollbar-custom text-sm font-medium text-gray-700"
                                        />
                                        <button
                                            onClick={() => sendMessage()}
                                            disabled={isLoading || !input.trim()}
                                            className="h-11 w-11 rounded-2xl text-white flex items-center justify-center transition-all hover:scale-105 active:scale-95 disabled:opacity-20 disabled:grayscale shadow-sm hover:shadow-md"
                                            style={{ backgroundColor: config.primaryColor }}
                                        >
                                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="rotate-[-10deg]">
                                                <path d="M5.78393 10.7733L3.47785 6.16113C2.36853 3.9425 1.81387 2.83318 2.32353 2.32353C2.83318 1.81387 3.9425 2.36853 6.16113 3.47785L19.5769 10.1857C21.138 10.9663 21.9185 11.3566 21.9185 11.9746C21.9185 12.5926 21.138 12.9829 19.5769 13.7634L6.16113 20.4713C3.9425 21.5806 2.83318 22.1353 2.32353 21.6256C1.81387 21.116 2.36853 20.0067 3.47785 17.788L5.78522 13.1733H12.6367C13.2995 13.1733 13.8367 12.636 13.8367 11.9733C13.8367 11.3105 13.2995 10.7733 12.6367 10.7733H5.78393Z" fill="currentColor" />
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Report Tab */}
                    {activeTab === 'report' && (
                        <div className="flex-1 flex flex-col overflow-hidden animate-fade-in bg-white h-full relative">
                            <div className="flex-1 overflow-y-auto p-4 scrollbar-custom pb-24">
                                {lastCreatedTicket && (
                                    <div className="mb-8 rounded-2xl border border-gray-200 shadow-sm overflow-hidden animate-fade-in bg-white">
                                        <div className="flex items-center justify-between px-4 py-3 bg-gray-50/80 border-b border-gray-100">
                                            <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400">Ticket Submitted</div>
                                            <span className={`text-[10px] uppercase font-black px-2 py-0.5 rounded-full ${lastCreatedTicket.status === 'pending' ? 'bg-orange-100 text-orange-600' :
                                                lastCreatedTicket.status === 'resolved' ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-600'
                                                }`}>
                                                {lastCreatedTicket.status}
                                            </span>
                                        </div>

                                        {lastCreatedTicket.image_url && (
                                            <div className="relative group">
                                                <img
                                                    src={lastCreatedTicket.image_url}
                                                    alt="Ticket attachment"
                                                    className="w-full h-auto object-cover max-h-[200px] border-b border-gray-100 cursor-zoom-in"
                                                    onClick={() => window.open(lastCreatedTicket.image_url, '_blank')}
                                                />
                                            </div>
                                        )}

                                        <div className="p-4 space-y-4">
                                            <div>
                                                <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400 mb-1">Conversation with Support</div>
                                                <div className="space-y-2">
                                                    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                                                        <div className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">You</div>
                                                        <p className="text-sm text-gray-700 font-medium leading-relaxed whitespace-pre-wrap">
                                                            {lastCreatedTicket.description}
                                                        </p>
                                                    </div>
                                                    {(lastCreatedTicket.admin_replies || []).map((reply, idx) => (
                                                        <div key={`last-created-reply-${idx}`} className="rounded-xl border border-emerald-100 bg-emerald-50 p-3">
                                                            <div className="text-[10px] font-black text-emerald-600 uppercase tracking-widest mb-1">Admin</div>
                                                            <p className="text-sm text-emerald-800 font-medium whitespace-pre-wrap">
                                                                {reply.message}
                                                            </p>
                                                            {reply.created_at && (
                                                                <div className="mt-1 text-[10px] text-emerald-500">
                                                                    {new Date(reply.created_at).toLocaleString()}
                                                                </div>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>

                                            <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-50">
                                                <div>
                                                    <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400 mb-0.5">Ticket #</div>
                                                    <div className="text-sm font-bold text-gray-800">{formatTicketNumber(lastCreatedTicket)}</div>
                                                </div>
                                                <div>
                                                    <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400 mb-0.5">Reported Date</div>
                                                    <div className="text-xs font-bold text-gray-800">{new Date(lastCreatedTicket.created_at).toLocaleDateString()}</div>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="p-4 bg-gray-50/50 border-t border-gray-100 flex flex-wrap gap-2">
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setInput(lastCreatedTicket.description || '');
                                                    fileInputRef.current?.click();
                                                    setTimeout(() => textareaRef.current?.focus(), 0);
                                                }}
                                                className="flex-1 whitespace-nowrap px-4 py-2.5 rounded-xl text-xs font-bold border-2 transition-all active:scale-95 text-center"
                                                style={{ borderColor: config.primaryColor, color: config.primaryColor }}
                                            >
                                                Add more image
                                            </button>
                                            {lastCreatedTicket.status === 'closed' && (
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        setInput(`Please re-open ticket ${formatTicketNumber(lastCreatedTicket)}.`);
                                                        setTimeout(() => textareaRef.current?.focus(), 0);
                                                    }}
                                                    className="flex-1 whitespace-nowrap px-4 py-2.5 rounded-xl text-xs font-bold border-2 transition-all active:scale-95 text-center"
                                                    style={{ borderColor: config.primaryColor, color: config.primaryColor }}
                                                >
                                                    Re-open this ticket
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                )}
                                <div className="mb-6">
                                    <h5 className="text-[10px] uppercase font-black text-gray-300 tracking-[0.2em] px-1 mb-3">Your Tickets</h5>
                                    {isTicketsLoading ? (
                                        <div className="space-y-3">
                                            {[1, 2].map(i => (
                                                <div key={i} className="h-20 bg-gray-50 rounded-xl animate-pulse"></div>
                                            ))}
                                        </div>
                                    ) : tickets.length === 0 ? (
                                        <div className="text-center py-10 px-4">
                                            <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-4">
                                                <svg className="w-8 h-8 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                                                </svg>
                                            </div>
                                            <p className="text-sm text-gray-400 font-medium">No reports yet</p>
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {tickets.map((ticket) => (
                                                <div
                                                    key={ticket.id}
                                                    onClick={() => handleOpenTicket(ticket)}
                                                    className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm hover:shadow-md transition-all cursor-pointer hover:border-blue-100 group"
                                                >
                                                    <div className="flex justify-between items-start mb-2">
                                                        <div className="flex items-center gap-2">
                                                            <span className="text-[10px] font-black text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{new Date(ticket.created_at).getFullYear()}-{String(ticket.id).padStart(4, '0')}</span>
                                                            <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-lg ${ticket.status === 'pending' ? 'bg-orange-100 text-orange-600' :
                                                                ticket.status === 'resolved' ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-600'
                                                                }`}>
                                                                {ticket.status}
                                                            </span>
                                                        </div>
                                                        <span className="text-[10px] text-gray-400 group-hover:text-blue-400 transition-colors">View Details →</span>
                                                    </div>
                                                    <p className="text-sm font-medium text-gray-700 line-clamp-1 mb-1">{ticket.description}</p>
                                                    <div className="text-[10px] text-gray-300 font-medium">{new Date(ticket.created_at).toLocaleDateString()}</div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Ticket Detail Overlay */}
                            {selectedTicket && (
                                <div className="absolute inset-0 z-50 bg-white animate-slide-up flex flex-col">
                                    <h3 className="font-bold text-gray-800 p-4 border-b border-gray-100">Ticket Details</h3>

                                    <div className="flex-1 overflow-y-auto scrollbar-custom p-5 space-y-6">
                                        {/* Flex Message Look */}
                                        <div className="rounded-2xl border border-gray-200 shadow-sm overflow-hidden bg-white">
                                            <div className="px-4 py-3 bg-gray-50/80 border-b border-gray-100 flex justify-between items-center">
                                                <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400">Issue Report</div>
                                                <span className={`text-[10px] uppercase font-black px-2 py-0.5 rounded-full ${selectedTicket.status === 'pending' ? 'bg-orange-100 text-orange-600' :
                                                    selectedTicket.status === 'resolved' ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-600'
                                                    }`}>
                                                    {selectedTicket.status}
                                                </span>
                                            </div>

                                            {(selectedImageUrls.length > 0 || mainImageUrl || selectedTicket.image_url) && (
                                                <div className="flex flex-col border-b border-gray-100">
                                                    <div className="relative group cursor-pointer" onClick={() => isEditingTicket && fileInputRef.current?.click()}>
                                                        <img
                                                            src={selectedImageUrls[0] || mainImageUrl || selectedTicket.image_url}
                                                            alt="Report attachment"
                                                            className={`w-full h-auto object-cover max-h-[240px] ${isEditingTicket ? 'opacity-75 hover:opacity-100 transition-opacity' : ''}`}
                                                            onClick={(e) => {
                                                                if (!isEditingTicket) {
                                                                    window.open(mainImageUrl || selectedTicket.image_url, '_blank');
                                                                } else {
                                                                    e.stopPropagation();
                                                                    fileInputRef.current?.click();
                                                                }
                                                            }}
                                                        />
                                                        {isEditingTicket && (
                                                            <div className="absolute inset-0 flex items-center justify-center bg-black/10 pointer-events-none">
                                                                <div className="bg-white/90 px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider text-gray-700 shadow-sm border border-white/20">Click to add image</div>
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* Thumbnails */}
                                                    {selectedTicket.image_urls && selectedTicket.image_urls.length > 1 && !isEditingTicket && (
                                                        <div className="flex gap-2 p-3 bg-gray-50/50 overflow-x-auto scrollbar-none">
                                                            {selectedTicket.image_urls.map((url, idx) => (
                                                                <div
                                                                    key={idx}
                                                                    onClick={() => setMainImageUrl(url)}
                                                                    className={`relative w-12 h-12 flex-shrink-0 cursor-pointer rounded-lg overflow-hidden border-2 transition-all ${(mainImageUrl || selectedTicket.image_url) === url ? 'border-primary-500 ring-2 ring-primary-500/10' : 'border-white hover:border-gray-200'
                                                                        }`}
                                                                >
                                                                    <img src={url} alt={`Thumbnail ${idx}`} className="w-full h-full object-cover" />
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            )}

                                            <div className="p-4 space-y-4">
                                                <div>
                                                    <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400 mb-1">Conversation with Support</div>
                                                    {isEditingTicket ? (
                                                        <textarea
                                                            value={editTicketDescription}
                                                            onChange={(e) => setEditTicketDescription(e.target.value)}
                                                            className="w-full p-3 rounded-xl border border-gray-200 text-sm font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-100 transition-all resize-none min-h-[100px]"
                                                            placeholder="Edit description..."
                                                        />
                                                    ) : (
                                                        <div className="space-y-2">
                                                            <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                                                                <div className="text-[10px] font-black text-gray-500 uppercase tracking-widest mb-1">You</div>
                                                                <p className="text-sm text-gray-700 font-medium leading-relaxed whitespace-pre-wrap">
                                                                    {selectedTicket.description}
                                                                </p>
                                                            </div>
                                                            {(selectedTicket.admin_replies || []).map((reply, idx) => (
                                                                <div key={`selected-reply-${idx}`} className="rounded-xl border border-emerald-100 bg-emerald-50 p-3">
                                                                    <div className="text-[10px] font-black text-emerald-600 uppercase tracking-widest mb-1">Admin</div>
                                                                    <p className="text-sm text-emerald-800 font-medium whitespace-pre-wrap">
                                                                        {reply.message}
                                                                    </p>
                                                                    {reply.created_at && (
                                                                        <div className="mt-1 text-[10px] text-emerald-500">
                                                                            {new Date(reply.created_at).toLocaleString()}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>

                                                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-50">
                                                    <div>
                                                        <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400 mb-0.5">Ticket #</div>
                                                        <div className="text-sm font-bold text-gray-800">{formatTicketNumber(selectedTicket)}</div>
                                                    </div>
                                                    <div>
                                                        <div className="text-[10px] uppercase font-black tracking-[0.2em] text-gray-400 mb-0.5">Reported Date</div>
                                                        <div className="text-xs font-bold text-gray-800">{new Date(selectedTicket.created_at).toLocaleDateString()}</div>
                                                    </div>
                                                </div>
                                            </div>

                                            <div className="p-4 bg-gray-50/50 border-t border-gray-100 flex flex-col gap-2">
                                                {!isEditingTicket ? (
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            setIsEditingTicket(true);
                                                            setEditTicketDescription(selectedTicket.description);
                                                        }}
                                                        className="w-full whitespace-nowrap px-4 py-2.5 rounded-xl text-xs font-bold border-2 transition-all active:scale-95 text-center"
                                                        style={{ borderColor: config.primaryColor, color: config.primaryColor }}
                                                    >
                                                        Edit ticket
                                                    </button>
                                                ) : (
                                                    <>
                                                        <button
                                                            type="button"
                                                            onClick={() => handleUpdateTicket()}
                                                            disabled={isLoading}
                                                            className="w-full bg-gray-900 text-white px-4 py-2.5 rounded-xl text-xs font-bold transition-all active:scale-95 text-center shadow-md animate-fade-in disabled:opacity-50"
                                                        >
                                                            {isLoading ? 'Updating...' : 'Update Detail'}
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => {
                                                                setIsEditingTicket(false);
                                                                clearSelectedImage();
                                                            }}
                                                            className="w-full text-gray-500 px-4 py-2 text-xs font-bold hover:text-gray-700 transition-colors"
                                                        >
                                                            Cancel
                                                        </button>
                                                    </>
                                                )}
                                                {selectedTicket.status === 'closed' && !isEditingTicket && (
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            setSelectedTicket(null);
                                                            setInput(`Please re-open ticket ${formatTicketNumber(selectedTicket)}.`);
                                                            setTimeout(() => textareaRef.current?.focus(), 300);
                                                        }}
                                                        className="w-full whitespace-nowrap px-4 py-2.5 rounded-xl text-xs font-bold border-2 transition-all active:scale-95 text-center"
                                                        style={{ borderColor: config.primaryColor, color: config.primaryColor }}
                                                    >
                                                        Re-open this ticket
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Report Input Group */}
                            <div className="absolute bottom-0 left-0 right-0 z-10 px-4 pb-4 pt-3 bg-gradient-to-t from-white via-white/95 to-white/70 backdrop-blur">
                                <div className="rounded-2xl border border-gray-200/70 bg-white shadow-[0_10px_30px_rgba(0,0,0,0.06)]">
                                    <div className="flex items-end gap-3 px-4 pt-3">
                                        <textarea
                                            ref={textareaRef}
                                            value={input}
                                            onChange={(e) => setInput(e.target.value)}
                                            placeholder="Describe your issue..."
                                            rows={2}
                                            className="flex-1 bg-transparent border-none py-3 focus:outline-none resize-none min-h-[60px] max-h-[120px] scrollbar-custom text-sm font-medium text-gray-700"
                                        />
                                        <button
                                            onClick={() => submitTicketReport()}
                                            disabled={isLoading || !input.trim()}
                                            className="h-11 w-11 rounded-2xl text-white flex items-center justify-center transition-all hover:scale-105 active:scale-95 disabled:opacity-20 disabled:grayscale shadow-sm hover:shadow-md"
                                            style={{ backgroundColor: config.primaryColor }}
                                        >
                                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                                <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                                            </svg>
                                        </button>
                                    </div>
                                    <div className="mt-1 flex items-center justify-between gap-3 border-t border-gray-100/80 px-4 py-2.5 text-xs text-gray-500">
                                        <label className="inline-flex items-center gap-2 cursor-pointer font-semibold text-gray-600 hover:text-gray-800">
                                            <input
                                                ref={fileInputRef}
                                                type="file"
                                                accept="image/*"
                                                multiple
                                                className="hidden"
                                                onChange={handleImageChange}
                                            />
                                            <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-gray-500">
                                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                    <path d="M4 7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7Z" stroke="currentColor" strokeWidth="1.5" />
                                                    <path d="M8 14l2.5-2.5a1 1 0 0 1 1.4 0L16 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                                    <circle cx="9" cy="9" r="1.5" fill="currentColor" />
                                                </svg>
                                            </span>
                                            <span className="text-[11px] uppercase tracking-wider">Add Photo</span>
                                        </label>
                                        {selectedImageUrls.length > 0 && (
                                            <div className="flex flex-wrap gap-2 animate-fade-in-up py-1">
                                                {selectedImageUrls.map((url, idx) => (
                                                    <div key={idx} className="relative group w-10 h-10">
                                                        <img
                                                            src={url}
                                                            alt="Preview"
                                                            className="w-full h-full object-cover rounded-lg border border-gray-200"
                                                        />
                                                        <button
                                                            onClick={(e) => {
                                                                e.preventDefault();
                                                                setSelectedImages(prev => prev.filter((_, i) => i !== idx));
                                                            }}
                                                            className="absolute -top-1.5 -right-1.5 bg-gray-900 text-white rounded-full p-0.5 shadow-md opacity-0 group-hover:opacity-100 transition-opacity"
                                                        >
                                                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                                                                <path d="M18 6L6 18M6 6l12 12" />
                                                            </svg>
                                                        </button>
                                                    </div>
                                                ))}
                                                <button
                                                    onClick={() => clearSelectedImage()}
                                                    className="px-2 text-[10px] font-black uppercase tracking-widest text-gray-400 hover:text-red-500 transition-colors"
                                                >
                                                    Clear
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Bottom Navigation Bar */}
                {activeTab === 'home' && (
                    <div className="bg-white border-t border-gray-50 h-[80px] flex items-center justify-around px-8 relative z-30 shadow-[0_-8px_30px_rgb(0,0,0,0.02)]">
                        <button
                            onClick={() => setActiveTab('home')}
                            className={`group flex flex-col items-center gap-1.5 transition-all p-2 rounded-xl active:scale-95 ${activeTab === 'home' ? '' : 'text-gray-300 hover:text-gray-400'}`}
                            style={{ color: activeTab === 'home' ? config.primaryColor : undefined }}
                        >
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M4.66663 24.5V10.5L14 3.5L23.3333 10.5V24.5H16.3333V16.3333H11.6666V24.5H4.66663Z" fill="currentColor" />
                            </svg>
                            <span className="text-[10px] font-black uppercase tracking-widest mt-1">Home</span>
                        </button>
                        <button
                            onClick={() => setActiveTab('chat')}
                            className="group flex flex-col items-center gap-1.5 transition-all p-2 rounded-xl active:scale-95 text-gray-300 hover:text-gray-400"
                        >
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M20.4001 5.1223V15.9045C20.4001 16.3308 20.2566 16.6912 19.9697 16.9856C19.6828 17.28 19.3316 17.4272 18.916 17.4272H6.49717L3.6001 20.3996V5.1223C3.6001 4.69595 3.74356 4.33558 4.03048 4.04119C4.31741 3.7468 4.66864 3.59961 5.08417 3.59961H18.916C19.3316 3.59961 19.6828 3.7468 19.9697 4.04119C20.2566 4.33558 20.4001 4.69595 20.4001 5.1223Z" fill="currentColor" />
                            </svg>
                            <span className="text-[10px] font-black uppercase tracking-widest mt-1">Chat</span>
                        </button>
                        <button
                            onClick={() => setActiveTab('report')}
                            className="group flex flex-col items-center gap-1.5 transition-all p-2 rounded-xl active:scale-95 text-gray-300 hover:text-gray-400"
                        >
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M6 4h9l3 3v13H6V4Zm8 1.5V8h2.5L14 5.5ZM8 11h8v1.5H8V11Zm0 4h8v1.5H8V15Z" fill="currentColor" />
                            </svg>
                            <span className="text-[10px] font-black uppercase tracking-widest mt-1">Report</span>
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
};
