import React from 'react';
import { useLocation } from 'react-router-dom';
import { getPageMeta } from '../../routes/pageMeta';

export const Topbar: React.FC = () => {
    const { pathname } = useLocation();
    const meta = getPageMeta(pathname);

    return (
        <header className="bg-white border-b border-gray-200">
            <div className="flex items-center justify-between gap-4 px-4 py-4 lg:gap-6 lg:px-6">
                <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                        <span>{meta.section}</span>
                        <span className="text-gray-300">/</span>
                        <span className="truncate text-gray-500">{meta.title}</span>
                    </div>
                    <h2 className="truncate text-xl font-semibold text-gray-900 lg:text-2xl">{meta.title}</h2>
                    <p className="mt-1 max-w-3xl truncate text-sm text-gray-500">{meta.description}</p>
                </div>

                {/* Right side - can add notifications or other features here */}
                <div className="flex shrink-0 items-center gap-4">
                    {/* Placeholder for future features */}
                </div>
            </div>
        </header>
    );
};
