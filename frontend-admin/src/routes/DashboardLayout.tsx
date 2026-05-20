import React from 'react';
import { Outlet } from 'react-router-dom';

import { Sidebar } from '../components/layout/Sidebar';
import { Topbar } from '../components/layout/Topbar';

export const DashboardLayout: React.FC = () => {
    return (
        <div className="h-screen overflow-x-auto bg-gray-50">
            <div className="flex h-screen min-w-[1024px] overflow-hidden bg-gray-50">
                <div className="group/sidebar sticky top-0 h-screen w-16 shrink-0 border-r border-gray-700/50 bg-gray-900">
                    <Sidebar />
                </div>

                <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                    <Topbar />

                    <main className="min-h-0 flex-1 overflow-y-auto p-4 lg:p-6">
                        <Outlet />
                    </main>
                </div>
            </div>
        </div>
    );
};
