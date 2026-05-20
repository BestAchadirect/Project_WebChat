export interface PageMeta {
    path: string;
    section: string;
    title: string;
    description: string;
}

export const pageMeta: PageMeta[] = [
    {
        path: '/dashboard/knowledge/upload-documents',
        section: 'Knowledge',
        title: 'Upload Documents',
        description: 'Manage product catalog imports and knowledge base uploads.',
    },
    {
        path: '/dashboard/knowledge/products-tuning',
        section: 'Knowledge',
        title: 'Product Tuning',
        description: 'Tune product attributes, visibility, and merchandising quality.',
    },
    {
        path: '/dashboard/knowledge/documents-control',
        section: 'Knowledge',
        title: 'Document Control',
        description: 'Review knowledge chunks, edit source content, and test retrieval.',
    },
    {
        path: '/dashboard/knowledge/synonyms',
        section: 'Knowledge',
        title: 'Synonym Rules',
        description: 'Normalize related terms so search stays consistent.',
    },
    {
        path: '/dashboard/magento',
        section: 'Integrations',
        title: 'Magento Settings',
        description: 'Configure Magento store credentials and sync behavior.',
    },
    {
        path: '/dashboard/tickets',
        section: 'Support',
        title: 'Tickets',
        description: 'Track customer reports, replies, and unresolved support work.',
    },
    {
        path: '/dashboard/analytics',
        section: 'Insights',
        title: 'Analytics',
        description: 'Monitor chatbot performance and user interactions.',
    },
    {
        path: '/dashboard/qa',
        section: 'Monitoring',
        title: 'Conversation Monitoring',
        description: 'Monitor customer and bot conversations from a single review queue.',
    },
    {
        path: '/dashboard/chat',
        section: 'Settings',
        title: 'Chat Settings',
        description: 'Customize widget appearance, quick replies, banners, and embed code.',
    },
];

export const getPageMeta = (pathname: string): PageMeta => {
    const sorted = [...pageMeta].sort((a, b) => b.path.length - a.path.length);
    const match = sorted.find((item) => pathname === item.path || pathname.startsWith(`${item.path}/`));
    return match || {
        path: '/dashboard',
        section: 'Admin',
        title: 'Dashboard',
        description: 'Manage your AI commerce workspace.',
    };
};

export const pageLabel = (path: string): string => getPageMeta(path).title;
