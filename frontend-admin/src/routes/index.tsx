import { createBrowserRouter, Navigate } from 'react-router-dom';
import { DashboardLayout } from './DashboardLayout';
import { DocumentsPage } from './DocumentsPage';
import { MagentoSettingsPage } from './MagentoSettingsPage';
import { AnalyticsPage } from './AnalyticsPage';
import { ChatSettingsPage } from './ChatSettingsPage';
import { DocumentControlPage, ProductTuningPage } from './Knowledge';
import { QAMonitoringPage } from './QA';

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
            // Knowledge Dashboard Routes
            {
                path: 'knowledge/documents-control',
                element: <DocumentControlPage />,
            },
            {
                path: 'knowledge/products-tuning',
                element: <ProductTuningPage />,
            },
            {
                path: 'qa',
                element: <QAMonitoringPage />,
            },
        ],
    },
]);
