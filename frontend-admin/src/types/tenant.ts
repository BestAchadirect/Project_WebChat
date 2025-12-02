export interface Tenant {
    id: string;
    name: string;
    email: string;
    apiKey: string;
    createdAt: string;
    settings: TenantSettings;
}

export interface TenantSettings {
    magentoUrl?: string;
    magentoApiKey?: string;
    magentoApiSecret?: string;
    allowedDomains?: string[];
    chatbotName?: string;
    chatbotGreeting?: string;
}
