import React from 'react';
import { useLocation } from 'react-router-dom';
import newAchaLogo from '../../assets/new acha logo.png';
import { getPageMeta } from '../../routes/pageMeta';

interface MobileHeaderProps {
    onOpenSidebar: () => void;
}

export const MobileHeader: React.FC<MobileHeaderProps> = ({ onOpenSidebar }) => {
    const { pathname } = useLocation();
    const meta = getPageMeta(pathname);

    return (
        <header className="md:hidden bg-gray-900 text-white px-4 py-3 flex items-center justify-between border-b border-gray-700 sticky top-0 z-40">
            <div className="flex min-w-0 items-center gap-3">
                <img
                    src={newAchaLogo}
                    alt="ACHA logo"
                    className="h-8 w-auto shrink-0 object-contain"
                />
                <div className="min-w-0">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{meta.section}</div>
                    <div className="truncate text-sm font-semibold text-white">{meta.title}</div>
                </div>
            </div>
            <button
                onClick={onOpenSidebar}
                className="p-2 rounded-lg hover:bg-gray-800 transition-colors shrink-0"
                aria-label="Open Sidebar"
            >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
                </svg>
            </button>
        </header>
    );
};
