import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from '../components/layout/Sidebar';
import { Topbar } from '../components/layout/Topbar';
import { MobileHeader } from '../components/layout/MobileHeader';

export const DashboardLayout: React.FC = () => {
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);

    return (
        <div className="flex flex-col min-h-screen bg-gray-50 md:flex-row">
            {/* Mobile Header */}
            <MobileHeader onOpenSidebar={() => setIsSidebarOpen(true)} />

            {/* Sidebar Overlay (Mobile) */}
            {isSidebarOpen && (
                <div
                    className="fixed inset-0 bg-black/50 z-40 md:hidden animate-fade-in"
                    onClick={() => setIsSidebarOpen(false)}
                />
            )}

            {/* Sidebar */}
            <div className={`
                fixed inset-y-0 left-0 z-50 w-64 h-screen transform transition-transform duration-300 ease-in-out bg-gray-900 border-r border-gray-700
                md:translate-x-0 md:static md:block md:h-auto md:min-h-screen
                ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
            `}>
                <Sidebar onMobileClose={() => setIsSidebarOpen(false)} />
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex flex-col min-h-screen">
                <div className="hidden md:block">
                    <Topbar />
                </div>

                <main className="flex-1 p-4 md:p-6">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};
