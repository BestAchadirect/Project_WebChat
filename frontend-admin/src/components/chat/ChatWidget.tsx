import React, { useState, useEffect, useRef } from 'react';
import apiClient from '../../api/client';

interface Message {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

interface KnowledgeSource {
    source_id: string;
    title: string;
    content_snippet: string;
    category?: string | null;
    relevance: number;
    url?: string | null;
}

interface ChatResponse {
    conversation_id: number;
    reply_text: string;
    product_carousel: any[];
    intent: string;
    sources?: KnowledgeSource[];
}

interface ChatWidgetProps {
    isInline?: boolean;
    title?: string;
    primaryColor?: string;
    welcomeMessage?: string;
    faqSuggestions?: string[]; // New prop for Flex Message chips
}

declare global {
    interface Window {
        genaiConfig?: {
            title?: string;
            primaryColor?: string;
            welcomeMessage?: string;
            faqSuggestions?: string[];
            apiUrl?: string;
        };
    }
}

// Custom styles for animations that Tailwind doesn't have out of the box
const customStyles = `
@keyframes pulse-shadow {
    0% { box-shadow: 0 0 0 0 rgba(33, 65, 102, 0.7); }
    70% { box-shadow: 0 0 0 10px rgba(33, 65, 102, 0); }
    100% { box-shadow: 0 0 0 0 rgba(33, 65, 102, 0); }
}
.pulse-animation {
    animation: pulse-shadow 2s infinite;
}
.typing-dot {
    animation: typing 1.4s infinite ease-in-out both;
}
.typing-dot:nth-child(1) { animation-delay: 0s; }
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing {
    0%, 100% { transform: scale(0.7); opacity: 0.5; }
    50% { transform: scale(1); opacity: 1; }
}
/* Custom scrollbar */
.scrollbar-custom::-webkit-scrollbar {
    width: 6px;
}
.scrollbar-custom::-webkit-scrollbar-track {
    background: rgba(150, 208, 230, 0.1);
}
.scrollbar-custom::-webkit-scrollbar-thumb {
    background-color: rgba(33, 65, 102, 0.3);
    border-radius: 20px;
}
`;

export const ChatWidget: React.FC<ChatWidgetProps> = ({
    isInline = false,
    title,
    primaryColor,
    welcomeMessage,
    faqSuggestions
}) => {
    // Colors from the design
    const colors = {
        darkBlue: '#0C2038',
        mediumBlue: '#214166',
        lightBlue: '#96D0E6',
        white: '#FFFFFF',
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
        ]
    };

    const [isOpen, setIsOpen] = useState(false);
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [conversationId, setConversationId] = useState<number | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Auto-scroll to bottom
    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, isOpen, isLoading]);

    // Adjust textarea height
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
        }
    }, [input]);

    // Generate or retrieve Guest ID
    const getUserId = () => {
        let userId = localStorage.getItem('chat_user_id');
        if (!userId) {
            userId = `guest_${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem('chat_user_id', userId);
        }
        return userId;
    };

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
                user_id: getUserId(),
                message: textToSend,
                conversation_id: conversationId,
                locale: 'en-US'
            };

            const { data } = await apiClient.post<ChatResponse>('/chat', payload);

            setConversationId(data.conversation_id);
            setMessages(prev => {
                const updated = [
                    ...prev,
                    {
                        role: 'assistant',
                        content: data.reply_text
                    }
                ];

                if (data.sources && data.sources.length > 0) {
                    updated.push({
                        role: 'assistant',
                        content: formatSources(data.sources)
                    });
                }

                return updated;
            });

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

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    // Determine container classes
    const containerClasses = isInline
        ? `absolute bottom-6 right-6 z-10 w-[380px] h-[600px] transition-all duration-300 ease-in-out transform ${isOpen ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-5 opacity-0 pointer-events-none'}`
        : `fixed bottom-[100px] right-[30px] z-[1000] w-[380px] h-[600px] transition-all duration-300 ease-in-out transform ${isOpen ? 'translate-y-0 opacity-100 pointer-events-auto' : 'translate-y-5 opacity-0 pointer-events-none'}`;

    return (
        <div style={{ fontFamily: "'Poppins', sans-serif" }}>
            <style>{customStyles}</style>

            {/* Toggle Button */}
            {!isInline && (
                <div
                    onClick={() => setIsOpen(true)}
                    className={`fixed bottom-[30px] right-[30px] w-[60px] h-[60px] rounded-full text-white flex items-center justify-center cursor-pointer shadow-lg z-[1001] transition-all duration-300 hover:scale-105 ${!isOpen ? 'pulse-animation' : ''}`}
                    style={{ backgroundColor: config.primaryColor }}
                >
                    {isOpen ? (
                        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                    ) : (
                        <svg className="w-[30px] h-[30px]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                        </svg>
                    )}
                </div>
            )}

            {/* Mock Toggle for Inline (Preview) Mode */}
            {isInline && !isOpen && (
                <div
                    onClick={() => setIsOpen(true)}
                    className={`absolute bottom-6 right-6 w-[60px] h-[60px] rounded-full text-white flex items-center justify-center cursor-pointer shadow-lg z-10 transition-all duration-300 hover:scale-105 pulse-animation`}
                    style={{ backgroundColor: config.primaryColor }}
                >
                    <svg className="w-[30px] h-[30px]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                </div>
            )}

            {/* Chat Container */}
            <div className={`${containerClasses} bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-[#96D0E6]/30`}>
                {/* Header */}
                <div className="p-4 text-white border-b-2 border-[#96D0E6]" style={{ backgroundColor: colors.darkBlue }}>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center">
                            <div className="w-10 h-10 rounded-full bg-[#96D0E6] flex items-center justify-center">
                                {/* Jewelry Icon */}
                                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                    <path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22Z" stroke={colors.darkBlue} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <path d="M12 16C14.2091 16 16 14.2091 16 12C16 9.79086 14.2091 8 12 8C9.79086 8 8 9.79086 8 12C8 14.2091 9.79086 16 12 16Z" fill={colors.darkBlue} stroke={colors.darkBlue} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <path d="M12 5V3" stroke={colors.darkBlue} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <path d="M19 12H21" stroke={colors.darkBlue} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <path d="M12 19V21" stroke={colors.darkBlue} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                    <path d="M3 12H5" stroke={colors.darkBlue} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </div>
                            <div className="ml-3">
                                <h3 className="font-semibold text-lg">{config.title}</h3>
                                <p className="text-xs text-[#96D0E6]">Wholesale Support</p>
                            </div>
                        </div>
                        <button onClick={() => setIsOpen(false)} className="text-[#96D0E6] hover:text-white transition-colors">
                            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-6 bg-[#f9fbfd] scrollbar-custom pb-20">
                    {/* Initial Welcome Message */}
                    <div className="flex justify-start mb-4 animate-fade-in-up">
                        <div className="bg-[#96D0E6] text-[#0C2038] px-4 py-3 rounded-2xl rounded-bl-sm shadow-sm max-w-[85%]">
                            <p>{config.welcomeMessage}</p>
                        </div>
                    </div>
                    {/* FAQ Suggestions - Now using dynamic config */}
                    {messages.length === 0 && config.faqSuggestions.length > 0 && (
                        <div className="flex justify-start mb-4 animate-fade-in-up" style={{ animationDelay: '0.1s' }}>
                            <div className="bg-[#96D0E6] text-[#0C2038] px-4 py-3 rounded-2xl rounded-bl-sm shadow-sm max-w-[85%]">
                                <p className="mb-2 text-sm font-medium">Quick suggestions:</p>
                                <div className="flex flex-wrap gap-2 mt-2">
                                    {config.faqSuggestions.map((faq, idx) => (
                                        <button
                                            key={idx}
                                            onClick={() => sendMessage(faq)}
                                            className="px-3 py-1 bg-[#96D0E6]/20 hover:bg-[#96D0E6]/40 text-[#214166] rounded-2xl text-xs font-medium transition-colors border border-[#214166]/10"
                                        >
                                            {faq}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}

                    {messages.map((msg, idx) => (
                        <div key={idx} className={`flex mb-4 animate-fade-in-up ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div
                                className={`px-4 py-3 rounded-2xl shadow-sm max-w-[80%] ${msg.role === 'user'
                                        ? 'text-white rounded-br-sm'
                                        : msg.role === 'system'
                                            ? 'bg-red-50 text-red-600'
                                            : 'bg-[#96D0E6] text-[#0C2038] rounded-bl-sm'
                                    }`}
                                style={msg.role === 'user' ? { backgroundColor: config.primaryColor } : {}}
                            >
                                {msg.content}
                            </div>
                        </div>
                    ))}

                    {isLoading && (
                        <div className="flex justify-start mb-4 animate-fade-in">
                            <div className="bg-[#96D0E6] px-4 py-3 rounded-2xl rounded-bl-sm flex space-x-1 items-center h-[46px]">
                                <span className="w-2 h-2 bg-[#214166] rounded-full typing-dot"></span>
                                <span className="w-2 h-2 bg-[#214166] rounded-full typing-dot"></span>
                                <span className="w-2 h-2 bg-[#214166] rounded-full typing-dot"></span>
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input Area */}
                <div className="absolute bottom-0 left-0 right-0 p-4 bg-white border-t border-[#96D0E6]/50">
                    <div className="relative">
                        <textarea
                            ref={textareaRef}
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={handleKeyPress}
                            placeholder="Ask anything..."
                            rows={1}
                            className="w-full border border-[#96D0E6] rounded-3xl py-3 pl-4 pr-12 focus:outline-none focus:ring-2 focus:border-transparent resize-none max-h-[100px] scrollbar-custom text-sm"
                            style={{ '--tw-ring-color': config.primaryColor } as React.CSSProperties}
                        />
                        <button
                            onClick={() => sendMessage()}
                            disabled={isLoading || !input.trim()}
                            className="absolute right-2 bottom-2 w-10 h-10 rounded-full text-white flex items-center justify-center transition-transform hover:scale-105 disabled:opacity-50 disabled:cursor-not-allowed"
                            style={{ backgroundColor: config.primaryColor }}
                        >
                            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
                                <path fillRule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clipRule="evenodd" />
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
