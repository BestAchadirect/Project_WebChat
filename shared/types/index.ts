// Shared TypeScript types for API communication

export interface Message {
    id: string
    role: 'user' | 'assistant'
    content: string
    timestamp: string
    products?: Product[]
}

export interface Product {
    id: string
    name: string
    price: number
    image: string
    url: string
}

export interface ChatRequest {
    merchantId: string
    message: string
    sessionId?: string
}

export interface ChatResponse {
    message: Message
    sessionId: string
}

export interface MerchantConfig {
    id: string
    name: string
    primaryColor?: string
    widgetTitle?: string
    magentoUrl: string
}
