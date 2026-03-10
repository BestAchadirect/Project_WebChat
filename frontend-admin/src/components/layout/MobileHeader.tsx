import React from 'react';
import newAchaLogo from '../../assets/new acha logo.png';

interface MobileHeaderProps {
    onOpenSidebar: () => void;
}

export const MobileHeader: React.FC<MobileHeaderProps> = ({ onOpenSidebar }) => {
    return (
        <header className="md:hidden bg-gray-900 text-white p-4 flex items-center justify-between border-b border-gray-700 sticky top-0 z-40">
            <img
                src={newAchaLogo}
                alt="ACHA logo"
                className="h-8 w-auto object-contain"
            />
            <button
                onClick={onOpenSidebar}
                className="p-2 rounded-lg hover:bg-gray-800 transition-colors"
                aria-label="Open Sidebar"
            >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
                </svg>
            </button>
        </header>
    );
};
