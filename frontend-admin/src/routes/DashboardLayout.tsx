import React, { useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from '../components/layout/Sidebar';
import { Topbar } from '../components/layout/Topbar';
import { MobileHeader } from '../components/layout/MobileHeader';

export const DashboardLayout: React.FC = () => {
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);

    /* Close on Escape (mobile only) */
    useEffect(() => {
        if (!isSidebarOpen) return;

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            if (window.innerWidth >= 768) return;
            setIsSidebarOpen(false);
        };

        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isSidebarOpen]);

    /* Lock body scroll while mobile sidebar is open */
    useEffect(() => {
        if (window.innerWidth >= 768) return;
        document.body.style.overflow = isSidebarOpen ? 'hidden' : '';
        return () => { document.body.style.overflow = ''; };
    }, [isSidebarOpen]);

    return (
        <div className="flex h-screen flex-col bg-gray-50 overflow-hidden md:flex-row">
            {/* Mobile Header */}
            <MobileHeader onOpenSidebar={() => setIsSidebarOpen(true)} />

            {/* Sidebar Overlay (Mobile) */}
            {isSidebarOpen && (
                <div
                    className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 md:hidden animate-fade-in"
                    onClick={() => setIsSidebarOpen(false)}
                    aria-hidden="true"
                />
            )}

            {/* Sidebar */}
            <div
                className={`
                fixed inset-y-0 left-0 z-50 w-64 h-screen transform bg-gray-900 border-r border-gray-700/50
                transition-[transform,width] duration-300 ease-in-out
                md:group/sidebar md:translate-x-0 md:sticky md:top-0 md:block md:h-screen md:w-16 md:shrink-0
                ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
            `}
                role={isSidebarOpen ? 'dialog' : undefined}
                aria-modal={isSidebarOpen ? true : undefined}
                aria-label={isSidebarOpen ? 'Sidebar Navigation' : undefined}
            >
                <Sidebar onMobileClose={() => setIsSidebarOpen(false)} />
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex min-h-0 flex-col overflow-hidden">
                <div className="hidden md:block">
                    <Topbar />
                </div>

                <main className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};
