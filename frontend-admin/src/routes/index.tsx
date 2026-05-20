import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AnalyticsPage } from './AnalyticsPage';
import { ChatSettingsPage } from './ChatSettingsPage';
import { DashboardLayout } from './DashboardLayout';
import { DocumentsPage } from './DocumentsPage';
import { DocumentControlPage, ProductTuningPage, SynonymsPage } from './Knowledge';
import { MagentoSettingsPage } from './MagentoSettingsPage';
import { ConversationMonitoringPage } from './conversation-monitoring';
import { TicketsPage } from './TicketsPage';

export const router = createBrowserRouter([
    {
        path: '/',
        element: <Navigate to="/dashboard/knowledge/upload-documents" replace />,
    },
    {
        path: '/dashboard',
        element: <DashboardLayout />,
        children: [
            {
                index: true,
                element: <Navigate to="/dashboard/knowledge/upload-documents" replace />,
            },
            {
                path: 'knowledge/upload-documents',
                element: <DocumentsPage />,
            },
            {
                path: 'magento',
                element: <MagentoSettingsPage />,
            },
            {
                path: 'analytics',
                element: <AnalyticsPage />,
            },
            {
                path: 'chat',
                element: <ChatSettingsPage />,
            },
            {
                path: 'knowledge/documents-control',
                element: <DocumentControlPage />,
            },
            {
                path: 'knowledge/products-tuning',
                element: <ProductTuningPage />,
            },
            {
                path: 'knowledge/synonyms',
                element: <SynonymsPage />,
            },
            {
                path: 'tickets',
                element: <TicketsPage />,
            },
            {
                path: 'qa',
                element: <ConversationMonitoringPage />,
            },
        ],
    },
]);
