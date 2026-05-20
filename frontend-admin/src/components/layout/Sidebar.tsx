import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

import newAchaLogo from '../../assets/new acha logo.png';
import { pageLabel } from '../../routes/pageMeta';

interface RailItem {
    id: string;
    label: string;
    icon: React.ReactNode;
    path?: string;
    children?: SubItem[];
}

interface SubItem {
    label: string;
    path: string;
    badge?: string | number;
}

const railItems: RailItem[] = [
    {
        id: 'knowledge',
        label: 'Knowledge',
        icon: (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
            </svg>
        ),
        children: [
            { label: pageLabel('/dashboard/knowledge/upload-documents'), path: '/dashboard/knowledge/upload-documents' },
            { label: pageLabel('/dashboard/knowledge/products-tuning'), path: '/dashboard/knowledge/products-tuning' },
            { label: pageLabel('/dashboard/knowledge/documents-control'), path: '/dashboard/knowledge/documents-control' },
            { label: pageLabel('/dashboard/knowledge/synonyms'), path: '/dashboard/knowledge/synonyms', badge: '3' },
        ],
    },
    {
        id: 'magento',
        label: pageLabel('/dashboard/magento'),
        icon: (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
        ),
        path: '/dashboard/magento',
    },
    {
        id: 'tickets',
        label: pageLabel('/dashboard/tickets'),
        icon: (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M15 5v2m0 4v2m0 4v2M5 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
            </svg>
        ),
        path: '/dashboard/tickets',
    },
    {
        id: 'analytics',
        label: pageLabel('/dashboard/analytics'),
        icon: (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
        ),
        path: '/dashboard/analytics',
    },
    {
        id: 'qa',
        label: pageLabel('/dashboard/qa'),
        icon: (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
        ),
        path: '/dashboard/qa',
    },
];

const settingsItem: RailItem = {
    id: 'chat-settings',
    label: pageLabel('/dashboard/chat'),
    icon: (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-4l-3 3v-3z" />
        </svg>
    ),
    path: '/dashboard/chat',
};

const itemLayoutClass = 'justify-center px-0';
const hiddenInlineLabelClass = 'hidden';

export const Sidebar: React.FC = () => {
    const { pathname } = useLocation();
    const [hoveredItemId, setHoveredItemId] = useState<string | null>(null);
    const [flyoutStyle, setFlyoutStyle] = useState({ top: 0, left: 0 });
    const itemRefs = useRef<Record<string, HTMLDivElement | null>>({});
    const timeoutRef = useRef<NodeJS.Timeout>();

    useEffect(() => {
        if (!hoveredItemId) return;
        const handleKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setHoveredItemId(null);
            }
        };
        window.addEventListener('keydown', handleKey);
        return () => window.removeEventListener('keydown', handleKey);
    }, [hoveredItemId]);

    const handleLinkClick = useCallback(() => {
        setHoveredItemId(null);
    }, []);

    const isGroupActive = (item: RailItem) =>
        item.children?.some((child) => pathname === child.path || pathname.startsWith(`${child.path}/`)) ?? false;

    const isDirectActive = (item: RailItem) =>
        item.path ? pathname === item.path || pathname.startsWith(`${item.path}/`) : false;

    const updateFlyoutPosition = useCallback(() => {
        if (!hoveredItemId) return;
        const trigger = itemRefs.current[hoveredItemId];
        if (!trigger) return;

        const rect = trigger.getBoundingClientRect();
        setFlyoutStyle({ top: rect.top, left: rect.right + 8 });
    }, [hoveredItemId]);

    useEffect(() => {
        if (!hoveredItemId) return;
        updateFlyoutPosition();
        window.addEventListener('scroll', updateFlyoutPosition, true);
        window.addEventListener('resize', updateFlyoutPosition);
        return () => {
            window.removeEventListener('scroll', updateFlyoutPosition, true);
            window.removeEventListener('resize', updateFlyoutPosition);
        };
    }, [hoveredItemId, updateFlyoutPosition]);

    const handleMouseEnter = (id: string) => {
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        setHoveredItemId(id);
    };

    const handleMouseLeave = () => {
        timeoutRef.current = setTimeout(() => {
            setHoveredItemId(null);
        }, 150);
    };

    const renderDirectItem = (item: RailItem) => {
        const active = isDirectActive(item);

        return (
            <div
                key={item.id}
                ref={(element) => {
                    itemRefs.current[item.id] = element;
                }}
                onMouseEnter={() => handleMouseEnter(item.id)}
                onMouseLeave={handleMouseLeave}
                className="relative group/item"
            >
                <NavLink
                    to={item.path!}
                    onClick={handleLinkClick}
                    className={() =>
                        `flex w-full min-w-0 items-center rounded-lg py-2.5 transition-all duration-200 ${itemLayoutClass} ${
                            active
                                ? 'bg-gradient-to-r from-primary-600/90 to-primary-700/90 text-white shadow-md shadow-primary-900/20'
                                : 'text-gray-400 hover:bg-white/[0.07] hover:text-gray-200'
                        }`
                    }
                >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center">{item.icon}</span>
                    <span className={`font-medium whitespace-nowrap text-sm transition-all duration-200 ${hiddenInlineLabelClass}`}>
                        {item.label}
                    </span>
                </NavLink>

                {hoveredItemId === item.id && (
                    <div
                        className="pointer-events-none fixed z-[60] animate-fade-in"
                        style={{ top: flyoutStyle.top + 4, left: flyoutStyle.left }}
                    >
                        <div className="whitespace-nowrap rounded border border-white/10 bg-gray-800 px-2.5 py-1.5 text-xs font-semibold text-white shadow-lg">
                            {item.label}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    const renderGroupItem = (item: RailItem) => {
        const active = isGroupActive(item);
        const isHovered = hoveredItemId === item.id;

        return (
            <div
                key={item.id}
                ref={(element) => {
                    itemRefs.current[item.id] = element;
                }}
                onMouseEnter={() => handleMouseEnter(item.id)}
                onMouseLeave={handleMouseLeave}
            >
                <button
                    type="button"
                    onClick={() => undefined}
                    aria-expanded={isHovered}
                    aria-haspopup="true"
                    className={`flex w-full min-w-0 items-center rounded-lg py-2.5 transition-all duration-200 ${itemLayoutClass} ${
                        active || isHovered ? 'bg-white/[0.08] text-white' : 'text-gray-400 hover:bg-white/[0.07] hover:text-gray-200'
                    }`}
                >
                    <span className={`flex h-5 w-5 shrink-0 items-center justify-center transition-colors ${active ? 'text-primary-400' : ''}`}>
                        {item.icon}
                    </span>
                    <span className={`font-medium whitespace-nowrap text-sm transition-all duration-200 ${hiddenInlineLabelClass}`}>
                        {item.label}
                    </span>
                </button>
            </div>
        );
    };

    const activeHoverGroup = [...railItems, settingsItem].find((item) => item.id === hoveredItemId && item.children);

    return (
        <>
            <aside className="flex h-full w-full min-h-0 flex-col overflow-hidden bg-gradient-to-b from-gray-900 to-[#111827] text-white">
                <div className="flex shrink-0 items-center justify-center gap-2 border-b border-white/[0.06] px-2 py-5">
                    <div className="flex min-w-0 items-center">
                        <img
                            src={newAchaLogo}
                            alt="ACHA logo"
                            className="h-9 w-auto shrink-0 object-contain"
                        />
                    </div>
                </div>

                <nav className="sidebar-scrollbar flex-1 space-y-1 overflow-y-auto px-2.5 py-4 min-h-0" aria-label="Primary">
                    {[...railItems, settingsItem].map((item) => (item.children ? renderGroupItem(item) : renderDirectItem(item)))}
                </nav>
            </aside>

            {activeHoverGroup && activeHoverGroup.children && (
                <div
                    id="sidebar-flyout"
                    className="fixed z-[60] w-56 animate-fade-in"
                    style={{ top: flyoutStyle.top, left: flyoutStyle.left }}
                    onMouseEnter={() => handleMouseEnter(activeHoverGroup.id)}
                    onMouseLeave={handleMouseLeave}
                >
                    <div className="rounded-xl border border-gray-200 bg-white py-2 shadow-lg">
                        <div className="border-b border-gray-100 px-4 py-2">
                            <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400">
                                {activeHoverGroup.label}
                            </p>
                        </div>
                        <div className="py-1">
                            {activeHoverGroup.children.map((child) => {
                                const childActive = pathname === child.path || pathname.startsWith(`${child.path}/`);
                                return (
                                    <NavLink
                                        key={child.path}
                                        to={child.path}
                                        onClick={handleLinkClick}
                                        className={() =>
                                            `mx-2 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-all duration-150 ${
                                                childActive
                                                    ? 'bg-primary-50 font-medium text-primary-700'
                                                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                                            }`
                                        }
                                    >
                                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${childActive ? 'bg-primary-500' : 'bg-gray-300'}`} />
                                        <span className="flex-1">{child.label}</span>
                                        {child.badge && (
                                            <span className="rounded-full bg-primary-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                                                {child.badge}
                                            </span>
                                        )}
                                    </NavLink>
                                );
                            })}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};
