import React from 'react';

export const Topbar: React.FC = () => {
    return (
        <header className="bg-white border-b border-gray-200 shadow-sm">
            <div className="flex items-center justify-between px-6 py-4">
                {/* Breadcrumbs / Title */}
                <div>
                    <h2 className="text-2xl font-semibold text-gray-900">Dashboard</h2>
                </div>

                {/* Right side - can add notifications or other features here */}
                <div className="flex items-center gap-4">
                    {/* Placeholder for future features */}
                </div>
            </div>
        </header>
    );
};
