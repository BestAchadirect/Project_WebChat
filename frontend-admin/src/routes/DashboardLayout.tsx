import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from '../components/layout/Sidebar';
import { Topbar } from '../components/layout/Topbar';

export const DashboardLayout: React.FC = () => {
    return (
        <div className="flex min-h-screen bg-gray-50">
            {/* Fixed Sidebar */}
            <div className="fixed inset-y-0 left-0 z-50 w-64 h-screen overflow-y-auto border-r border-gray-200 bg-gray-900">
                <Sidebar />
            </div>

            {/* Main Content Area - Offset by Sidebar width */}
            <div className="flex-1 flex flex-col ml-64 transition-all duration-300">
                <Topbar />
                {/* 
                   Changed: Removed fixed height and overflow-hidden.
                   Added: min-h-[calc(100vh-64px)] to ensure full height but allow growth.
                */}
                <main className="flex-1 p-6">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};
