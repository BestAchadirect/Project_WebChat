export interface ChatComponentLike {
    type: string;
    data: Record<string, unknown>;
}

const componentType = (value: unknown): string => {
    if (typeof value === 'string') return value.trim().toLowerCase();
    if (value && typeof value === 'object' && 'value' in value) {
        const raw = (value as { value?: unknown }).value;
        return typeof raw === 'string' ? raw.trim().toLowerCase() : '';
    }
    return '';
};

const asRecord = (value: unknown): Record<string, unknown> => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return value as Record<string, unknown>;
};

export const normalizeChatComponents = (value: unknown): ChatComponentLike[] => {
    if (!Array.isArray(value)) return [];
    return value
        .map((item) => {
            if (!item || typeof item !== 'object') return null;
            const raw = item as { type?: unknown; data?: unknown };
            const type = componentType(raw.type);
            if (!type) return null;
            return {
                type,
                data: asRecord(raw.data),
            };
        })
        .filter((item): item is ChatComponentLike => item !== null);
};

export const buildFallbackAssistantComponents = (text: string): ChatComponentLike[] => {
    const trimmed = String(text || '').trim();
    if (!trimmed) return [];
    return [{ type: 'assistant_message', data: { text: trimmed } }];
};

export const getAssistantMessageText = (components: ChatComponentLike[]): string => {
    const preferredTypes = [
        'assistant_message',
        'knowledge_answer',
        'clarify',
        'error',
        'action_result',
    ];
    for (const type of preferredTypes) {
        const component = components.find((item) => item.type === type);
        if (!component) continue;
        if (type === 'assistant_message') {
            return String(component.data.text || '').trim();
        }
        if (type === 'knowledge_answer') {
            return String(component.data.answer || '').trim();
        }
        return String(component.data.message || '').trim();
    }
    return '';
};

export const getQuickReplies = (components: ChatComponentLike[]): string[] => {
    const component = components.find((item) => item.type === 'quick_replies');
    if (!component || !Array.isArray(component.data.items)) return [];
    const items: string[] = [];
    const seen = new Set<string>();
    for (const raw of component.data.items) {
        const text = String(raw || '').trim();
        if (!text) continue;
        const key = text.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        items.push(text);
    }
    return items;
};
