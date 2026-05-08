import React, { useState, useRef, useEffect, useCallback } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import newAchaLogo from '../../assets/new acha logo.png';
import { pageLabel } from '../../routes/pageMeta';

/* ════════════════════════════════════════════════════════════
   Types
   ════════════════════════════════════════════════════════════ */

interface SidebarProps {
    onMobileClose?: () => void;
}

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

/* ════════════════════════════════════════════════════════════
   Navigation data
   ════════════════════════════════════════════════════════════ */

const railItems: RailItem[] = [
    {
        id: 'knowledge',
        label: 'Knowledge',
        icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M15 5v2m0 4v2m0 4v2M5 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
            </svg>
        ),
        path: '/dashboard/tickets',
    },
    {
        id: 'analytics',
        label: pageLabel('/dashboard/analytics'),
        icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
        ),
        path: '/dashboard/analytics',
    },
    {
        id: 'qa',
        label: pageLabel('/dashboard/qa'),
        icon: (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-4l-3 3v-3z" />
        </svg>
    ),
    path: '/dashboard/chat',
};

/* ════════════════════════════════════════════════════════════
   Collapse-aware helpers (mobile only label visibility)
   ════════════════════════════════════════════════════════════ */

const _showMobileLabel = 'md:hidden ml-3';
const _alwaysCenterDesktop = 'md:justify-center px-3 md:px-0';

/* ════════════════════════════════════════════════════════════
   Component
   ════════════════════════════════════════════════════════════ */

export const Sidebar: React.FC<SidebarProps> = ({ onMobileClose }) => {
    const { pathname } = useLocation();

    /* Hover state for desktop flyouts */
    const [hoveredItemId, setHoveredItemId] = useState<string | null>(null);
    /* Click state for mobile submenus */
    const [mobileOpenGroupId, setMobileOpenGroupId] = useState<string | null>(null);

    /* Close on Escape */
    useEffect(() => {
        if (!hoveredItemId && !mobileOpenGroupId) return;
        const handleKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                setHoveredItemId(null);
                setMobileOpenGroupId(null);
            }
        };
        window.addEventListener('keydown', handleKey);
        return () => window.removeEventListener('keydown', handleKey);
    }, [hoveredItemId, mobileOpenGroupId]);

    const handleLinkClick = useCallback(() => {
        setHoveredItemId(null);
        setMobileOpenGroupId(null);
        if (onMobileClose) onMobileClose();
    }, [onMobileClose]);

    const isGroupActive = (item: RailItem) =>
        item.children?.some(c => pathname === c.path || pathname.startsWith(c.path + '/')) ?? false;

    const isDirectActive = (item: RailItem) =>
        item.path ? (pathname === item.path || pathname.startsWith(item.path + '/')) : false;

    /* ── Tooltip/Flyout Positioning ── */
    const [flyoutStyle, setFlyoutStyle] = useState({ top: 0, left: 0 });
    const itemRefs = useRef<Record<string, HTMLDivElement | null>>({});

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

    /* Handle mouse enter/leave with a slight delay to prevent flickering */
    const timeoutRef = useRef<NodeJS.Timeout>();

    const handleMouseEnter = (id: string) => {
        if (window.innerWidth < 768) return; // Desktop only
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        setHoveredItemId(id);
    };

    const handleMouseLeave = () => {
        if (window.innerWidth < 768) return;
        timeoutRef.current = setTimeout(() => {
            setHoveredItemId(null);
        }, 150); // Small grace period when moving mouse from rail icon to flyout panel
    };

    /* ── Render a direct-link rail item ── */
    const renderDirectItem = (item: RailItem) => {
        const active = isDirectActive(item);
        return (
            <div
                key={item.id}
                ref={el => itemRefs.current[item.id] = el}
                onMouseEnter={() => handleMouseEnter(item.id)}
                onMouseLeave={handleMouseLeave}
                className="relative group/item"
            >
                <NavLink
                    to={item.path!}
                    onClick={handleLinkClick}
                    className={() =>
                        `flex w-full min-w-0 items-center rounded-lg py-2.5 transition-all duration-200 ${_alwaysCenterDesktop} ${
                            active
                                ? 'bg-gradient-to-r from-primary-600/90 to-primary-700/90 text-white shadow-md shadow-primary-900/20'
                                : 'text-gray-400 hover:bg-white/[0.07] hover:text-gray-200'
                        }`
                    }
                >
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                        {item.icon}
                    </span>
                    <span className={`font-medium whitespace-nowrap text-sm transition-all duration-200 ${_showMobileLabel}`}>
                        {item.label}
                    </span>
                </NavLink>

                {/* Desktop Tooltip for direct items */}
                {hoveredItemId === item.id && window.innerWidth >= 768 && (
                    <div
                        className="fixed z-[60] animate-fade-in pointer-events-none"
                        style={{ top: flyoutStyle.top + 4, left: flyoutStyle.left }}
                    >
                        <div className="bg-gray-800 text-white text-xs font-semibold px-2.5 py-1.5 rounded shadow-lg whitespace-nowrap border border-white/10">
                            {item.label}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    /* ── Render a grouped rail item (Knowledge) ── */
    const renderGroupItem = (item: RailItem) => {
        const active = isGroupActive(item);
        const isMobileOpen = mobileOpenGroupId === item.id;
        const isHovered = hoveredItemId === item.id;

        return (
            <div
                key={item.id}
                ref={el => itemRefs.current[item.id] = el}
                onMouseEnter={() => handleMouseEnter(item.id)}
                onMouseLeave={handleMouseLeave}
            >
                <button
                    onClick={() => {
                        if (window.innerWidth < 768) {
                            setMobileOpenGroupId(isMobileOpen ? null : item.id);
                        }
                    }}
                    aria-expanded={isMobileOpen || isHovered}
                    aria-haspopup="true"
                    className={`flex w-full min-w-0 items-center rounded-lg py-2.5 transition-all duration-200 ${_alwaysCenterDesktop} ${
                        active || isHovered || isMobileOpen
                            ? 'bg-white/[0.08] text-white'
                            : 'text-gray-400 hover:bg-white/[0.07] hover:text-gray-200'
                    }`}
                >
                    <span className={`flex h-5 w-5 shrink-0 items-center justify-center transition-colors ${active ? 'text-primary-400' : ''}`}>
                        {item.icon}
                    </span>
                    <span className={`font-medium whitespace-nowrap text-sm transition-all duration-200 ${_showMobileLabel}`}>
                        {item.label}
                    </span>
                    <span className={`ml-auto flex items-center transition-all duration-200 max-w-[16px] md:hidden`}>
                        <svg
                            className={`w-4 h-4 text-gray-500 transition-transform duration-200 ${isMobileOpen ? 'rotate-180' : ''}`}
                            fill="none" viewBox="0 0 24 24" stroke="currentColor"
                        >
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                    </span>
                </button>

                {/* Mobile inline submenu */}
                {isMobileOpen && item.children && (
                    <div className="md:hidden mt-1 ml-6 pl-3 border-l-2 border-gray-700/60 space-y-0.5">
                        {item.children.map(child => {
                            const childActive = pathname === child.path || pathname.startsWith(child.path + '/');
                            return (
                                <NavLink
                                    key={child.path}
                                    to={child.path}
                                    onClick={handleLinkClick}
                                    className={() =>
                                        `flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg transition-all duration-150 ${
                                            childActive
                                                ? 'bg-primary-600/15 text-primary-300 font-medium'
                                                : 'text-gray-500 hover:text-gray-300 hover:bg-white/[0.04]'
                                        }`
                                    }
                                >
                                    <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${childActive ? 'bg-primary-400' : 'bg-gray-600'}`} />
                                    <span className="flex-1">{child.label}</span>
                                    {child.badge && (
                                        <span className="bg-primary-600 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold">
                                            {child.badge}
                                        </span>
                                    )}
                                </NavLink>
                            );
                        })}
                    </div>
                )}
            </div>
        );
    };

    const activeHoverGroup = [...railItems, settingsItem].find(i => i.id === hoveredItemId && i.children);

    return (
        <>
            <aside className="bg-gradient-to-b from-gray-900 to-[#111827] text-white h-full w-full flex flex-col min-h-0 overflow-hidden">
                {/* ── Brand ── */}
                <div className="px-4 py-5 border-b border-white/[0.06] flex items-center justify-between gap-2 shrink-0 md:px-2 md:justify-center">
                    <div className="flex items-center min-w-0">
                        <img
                            src={newAchaLogo}
                            alt="ACHA logo"
                            className="h-9 w-auto shrink-0 object-contain"
                        />
                        {/* Only visible on mobile */}
                        <div className="ml-3 min-w-0 md:hidden">
                            <h1 className="text-base font-semibold text-white whitespace-nowrap">
                                ACHA Admin
                            </h1>
                        </div>
                    </div>
                    {onMobileClose && (
                        <button
                            onClick={onMobileClose}
                            className="md:hidden p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/[0.08] transition-colors"
                            aria-label="Close Sidebar"
                        >
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    )}
                </div>

                {/* ── Primary nav ── */}
                <nav className="flex-1 px-2.5 py-4 overflow-y-auto min-h-0 sidebar-scrollbar space-y-1" aria-label="Primary">
                    {railItems.map(item =>
                        item.children ? renderGroupItem(item) : renderDirectItem(item)
                    )}
                </nav>

                {/* ── Bottom utility ── */}
                <div className="px-2.5 py-3 border-t border-white/[0.06] space-y-1 shrink-0">
                    {settingsItem.children
                        ? renderGroupItem(settingsItem)
                        : renderDirectItem(settingsItem)
                    }
                    <div className="pt-2 md:hidden">
                        <p className="text-center text-xs text-gray-600 whitespace-nowrap">
                            &copy; 2026 GenAI SaaS
                        </p>
                    </div>
                </div>
            </aside>

            {/* ═══ Desktop hover flyout panel (position: fixed, escapes all overflow) ═══ */}
            {activeHoverGroup && activeHoverGroup.children && (
                <div
                    id="sidebar-flyout"
                    className="hidden md:block fixed z-[60] w-56 animate-fade-in"
                    style={{ top: flyoutStyle.top, left: flyoutStyle.left }}
                    onMouseEnter={() => handleMouseEnter(activeHoverGroup.id)}
                    onMouseLeave={handleMouseLeave}
                >
                    <div className="bg-white rounded-xl shadow-lg border border-gray-200 py-2">
                        <div className="px-4 py-2 border-b border-gray-100">
                            <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-gray-400">
                                {activeHoverGroup.label}
                            </p>
                        </div>
                        <div className="py-1">
                            {activeHoverGroup.children.map(child => {
                                const childActive = pathname === child.path || pathname.startsWith(child.path + '/');
                                return (
                                    <NavLink
                                        key={child.path}
                                        to={child.path}
                                        onClick={handleLinkClick}
                                        className={() =>
                                            `flex items-center gap-2.5 mx-2 px-3 py-2 text-sm rounded-lg transition-all duration-150 ${
                                                childActive
                                                    ? 'bg-primary-50 text-primary-700 font-medium'
                                                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                                            }`
                                        }
                                    >
                                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${childActive ? 'bg-primary-500' : 'bg-gray-300'}`} />
                                        <span className="flex-1">{child.label}</span>
                                        {child.badge && (
                                            <span className="bg-primary-600 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold">
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
