import React from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useNavigate } from 'react-router-dom';

export const Topbar: React.FC = () => {
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    const handleLogout = async () => {
        await logout();
        navigate('/login');
    };

    return (
        <header className="bg-white border-b border-gray-200 shadow-sm">
            <div className="flex items-center justify-between px-6 py-4">
                {/* Breadcrumbs / Title */}
                <div>
                    <h2 className="text-2xl font-semibold text-gray-900">Dashboard</h2>
                </div>

                {/* User Menu */}
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-r from-primary-500 to-secondary-500 flex items-center justify-center text-white font-semibold">
                            {user?.name?.charAt(0).toUpperCase() || 'U'}
                        </div>
                        <div>
                            <p className="text-sm font-medium text-gray-900">{user?.name || 'User'}</p>
                            <p className="text-xs text-gray-500">{user?.email || ''}</p>
                        </div>
                    </div>

                    <button
                        onClick={handleLogout}
                        className="ml-4 px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
                    >
                        <svg
                            className="w-5 h-5"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                            />
                        </svg>
                    </button>
                </div>
            </div>
        </header>
    );
};
