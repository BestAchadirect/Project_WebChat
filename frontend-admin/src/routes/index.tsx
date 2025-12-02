import React from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { LoginPage } from './LoginPage';
import { DashboardLayout } from './DashboardLayout';
import { DocumentsPage } from './DocumentsPage';
import { MagentoSettingsPage } from './MagentoSettingsPage';
import { AnalyticsPage } from './AnalyticsPage';

export const router = createBrowserRouter([
    {
        path: '/',
        element: <Navigate to="/dashboard/documents" replace />,
    },
    {
        path: '/login',
        element: <LoginPage />,
    },
    {
        path: '/dashboard',
        element: <DashboardLayout />,
        children: [
            {
                index: true,
                element: <Navigate to="/dashboard/documents" replace />,
            },
            {
                path: 'documents',
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
        ],
    },
]);
