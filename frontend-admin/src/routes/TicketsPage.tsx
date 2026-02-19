import React, { useEffect, useState } from 'react';
import { PaginationControls } from '../components/common/PaginationControls';
import { defaultPageSize } from '../constants/pagination';
import { ticketsApi, Ticket } from '../api/tickets';

export const TicketsPage: React.FC = () => {
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(defaultPageSize);
    const [totalItems, setTotalItems] = useState(0);
    const [totalPages, setTotalPages] = useState(1);
    const [isLoading, setIsLoading] = useState(true);
    const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
    const [isUpdating, setIsUpdating] = useState(false);
    const [replyDraft, setReplyDraft] = useState('');
    const [unreadCount, setUnreadCount] = useState(0);

    const isTicketUnread = (ticket: Ticket) => {
        if (!ticket.customer_last_activity_at) return false;
        if (!ticket.admin_last_seen_at) return true;
        return new Date(ticket.customer_last_activity_at).getTime() > new Date(ticket.admin_last_seen_at).getTime();
    };

    const fetchUnreadCount = async () => {
        try {
            const result = await ticketsApi.getUnreadCount();
            setUnreadCount(result.count || 0);
        } catch (error) {
            console.error('Failed to fetch unread count:', error);
        }
    };

    const fetchTickets = async (showSpinner: boolean = true, page: number = currentPage, size: number = pageSize) => {
        if (showSpinner) setIsLoading(true);
        try {
            const data = await ticketsApi.listAll({ page, pageSize: size });
            setTickets(data.items);
            setCurrentPage(data.page);
            setPageSize(data.pageSize);
            setTotalItems(data.totalItems);
            setTotalPages(data.totalPages);
            if (selectedTicket) {
                const latest = data.items.find((t) => t.id === selectedTicket.id);
                if (latest) setSelectedTicket(latest);
            }
        } catch (error) {
            console.error('Failed to fetch tickets:', error);
        } finally {
            if (showSpinner) setIsLoading(false);
        }
    };

    useEffect(() => {
        void fetchTickets();
        void fetchUnreadCount();
    }, []);

    useEffect(() => {
        const interval = setInterval(() => {
            void fetchTickets(false);
            void fetchUnreadCount();
        }, 15000);
        return () => clearInterval(interval);
    }, [selectedTicket, currentPage, pageSize]);

    useEffect(() => {
        setReplyDraft('');
    }, [selectedTicket]);

    const handleUpdateStatus = async (ticketId: number, newStatus: string) => {
        setIsUpdating(true);
        try {
            const formData = new FormData();
            formData.append('status', newStatus);
            formData.append('actor', 'admin');
            const data = await ticketsApi.update(ticketId, formData);
            setTickets(prev => prev.map(t => (t.id === ticketId ? data : t)));
            if (selectedTicket?.id === ticketId) setSelectedTicket(data);
            void fetchUnreadCount();
        } catch (error) {
            console.error('Failed to update ticket status:', error);
        } finally {
            setIsUpdating(false);
        }
    };

    const handleSendReply = async (ticketId: number) => {
        const reply = replyDraft.trim();
        if (!reply) return;
        setIsUpdating(true);
        try {
            const formData = new FormData();
            formData.append('admin_reply', reply);
            formData.append('actor', 'admin');
            const data = await ticketsApi.update(ticketId, formData);
            setTickets(prev => prev.map(t => (t.id === ticketId ? data : t)));
            setSelectedTicket(data);
            setReplyDraft('');
            void fetchUnreadCount();
        } catch (error) {
            console.error('Failed to send admin reply:', error);
        } finally {
            setIsUpdating(false);
        }
    };

    const handleOpenTicket = async (ticket: Ticket) => {
        setSelectedTicket(ticket);
        try {
            const data = await ticketsApi.markRead(ticket.id);
            setTickets(prev => prev.map(t => (t.id === ticket.id ? data : t)));
            setSelectedTicket(data);
            void fetchUnreadCount();
        } catch (error) {
            console.error('Failed to mark ticket as read:', error);
        }
    };

    const handlePaginationChange = ({ currentPage: nextPage, pageSize: nextPageSize }: { currentPage: number; pageSize: number }) => {
        if (nextPage === currentPage && nextPageSize === pageSize) return;
        setCurrentPage(nextPage);
        setPageSize(nextPageSize);
        void fetchTickets(true, nextPage, nextPageSize);
    };

    const formatTicketNumber = (ticket: Ticket) => {
        const year = new Date(ticket.created_at).getFullYear();
        return `${year}-${String(ticket.id).padStart(4, '0')}`;
    };

    if (isLoading && tickets.length === 0) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div className="flex items-center gap-3">
                    <h2 className="text-2xl font-bold text-gray-800">Ticket Management</h2>
                    {unreadCount > 0 && (
                        <span className="inline-flex px-3 py-1 rounded-full text-xs font-bold bg-red-100 text-red-600 uppercase tracking-wide">
                            {unreadCount} New Update{unreadCount > 1 ? 's' : ''}
                        </span>
                    )}
                </div>
                <button
                    onClick={() => {
                        void fetchTickets(true, currentPage, pageSize);
                        void fetchUnreadCount();
                    }}
                    className="p-2 text-gray-500 hover:text-primary-600 transition-colors"
                >
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                </button>
            </div>

            <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="bg-gray-50 border-b border-gray-100">
                            <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Ticket #</th>
                            <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">User</th>
                            <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Description</th>
                            <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Status</th>
                            <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Created</th>
                            <th className="px-6 py-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">Action</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                        {tickets.map((ticket) => (
                            <tr key={ticket.id} className="hover:bg-gray-50/50 transition-colors">
                                <td className="px-6 py-4">
                                    <div className="flex items-center gap-2">
                                        <span className="font-mono text-sm text-gray-600">{formatTicketNumber(ticket)}</span>
                                        {isTicketUnread(ticket) && <span className="h-2.5 w-2.5 rounded-full bg-red-500" title="Customer update" />}
                                    </div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-sm font-medium text-gray-800">{ticket.user_id}</div>
                                </td>
                                <td className="px-6 py-4 max-w-xs">
                                    <p className="text-sm text-gray-600 truncate">{ticket.description}</p>
                                </td>
                                <td className="px-6 py-4">
                                    <span className={`inline-flex px-2 py-1 text-[10px] font-bold rounded-full uppercase ${ticket.status === 'pending' ? 'bg-orange-100 text-orange-600' :
                                        ticket.status === 'resolved' ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-600'
                                        }`}>
                                        {ticket.status}
                                    </span>
                                </td>
                                <td className="px-6 py-4 text-sm text-gray-500">
                                    {new Date(ticket.created_at).toLocaleDateString()}
                                </td>
                                <td className="px-6 py-4">
                                    <button
                                        onClick={() => handleOpenTicket(ticket)}
                                        className="text-primary-600 hover:text-primary-700 text-sm font-semibold"
                                    >
                                        View Details
                                    </button>
                                </td>
                            </tr>
                        ))}
                        {tickets.length === 0 && (
                            <tr>
                                <td colSpan={6} className="px-6 py-10 text-center text-sm text-gray-500">
                                    No tickets found.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
                <PaginationControls
                    currentPage={currentPage}
                    pageSize={pageSize}
                    totalItems={totalItems}
                    totalPages={totalPages}
                    isLoading={isLoading}
                    onChange={handlePaginationChange}
                />
            </div>

            {/* Ticket Detail Modal */}
            {selectedTicket && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
                    <div className="bg-white rounded-3xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col animate-slide-up">
                        <div className="p-6 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
                            <div className="flex items-center gap-3">
                                <h3 className="text-xl font-bold text-gray-800">Ticket Management</h3>
                                <div className="flex items-center gap-2 border-l border-gray-200 pl-3">
                                    <span className="text-xs font-black text-gray-400 uppercase tracking-widest">Status:</span>
                                    <select
                                        value={selectedTicket.status}
                                        onChange={(e) => handleUpdateStatus(selectedTicket.id, e.target.value)}
                                        disabled={isUpdating}
                                        className="text-xs font-bold uppercase rounded-full px-3 py-1 border-none bg-white shadow-sm ring-1 ring-gray-200 focus:ring-primary-500"
                                    >
                                        <option value="pending">Pending</option>
                                        <option value="in_progress">In Progress</option>
                                        <option value="resolved">Resolved</option>
                                        <option value="closed">Closed</option>
                                    </select>
                                </div>
                            </div>
                            <button
                                onClick={() => setSelectedTicket(null)}
                                className="p-2 hover:bg-white rounded-full transition-colors text-gray-400"
                            >
                                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>

                        <div className="flex-1 overflow-y-auto p-8 space-y-8">
                            {selectedTicket.image_url && (
                                <section>
                                    <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest mb-3">Attachment</h4>
                                    <div className="rounded-2xl overflow-hidden border border-gray-100 bg-gray-50 max-h-[300px] flex items-center justify-center">
                                        <img
                                            src={selectedTicket.image_url}
                                            alt="Ticket attachment"
                                            className="max-w-full h-auto max-h-[300px] object-contain"
                                        />
                                    </div>
                                </section>
                            )}

                            <section className="grid grid-cols-1 md:grid-cols-2 gap-8">
                                <div className="space-y-6">
                                    <div>
                                        <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest mb-2">Description & Issue Type</h4>
                                        <div className="bg-gray-50 rounded-2xl p-6 border border-gray-100">
                                            <p className="text-gray-700 leading-relaxed whitespace-pre-wrap text-sm font-medium">
                                                {selectedTicket.description}
                                            </p>
                                            {selectedTicket.ai_summary && (
                                                <div className="mt-4 pt-4 border-t border-gray-100">
                                                    <span className="text-[10px] font-black text-blue-500 uppercase tracking-wider block mb-1">AI Detected Summary</span>
                                                    <p className="text-sm text-blue-700 italic font-medium">
                                                        {selectedTicket.ai_summary}
                                                    </p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="space-y-6">
                                    <div className="grid grid-cols-2 gap-4">
                                        <div className="bg-gray-50 p-4 rounded-2xl border border-gray-100">
                                            <h4 className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Ticket #</h4>
                                            <div className="text-lg font-bold text-gray-800 font-mono">{formatTicketNumber(selectedTicket)}</div>
                                        </div>
                                        <div className="bg-gray-50 p-4 rounded-2xl border border-gray-100">
                                            <h4 className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Reported Date</h4>
                                            <div className="text-sm font-bold text-gray-800">{new Date(selectedTicket.created_at).toLocaleDateString()}</div>
                                        </div>
                                        <div className="bg-gray-50 p-4 rounded-2xl border border-gray-100 col-span-2">
                                            <h4 className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Status</h4>
                                            <div className="flex items-center gap-2">
                                                <span className={`inline-flex px-3 py-1 text-xs font-bold rounded-full uppercase ${selectedTicket.status === 'pending' ? 'bg-orange-100 text-orange-600' :
                                                    selectedTicket.status === 'resolved' ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-600'
                                                    }`}>
                                                    {selectedTicket.status}
                                                </span>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Multi-image display */}
                                    {selectedTicket.image_urls && selectedTicket.image_urls.length > 0 && (
                                        <div className="bg-gray-50 rounded-2xl border border-gray-100 p-4">
                                            <h4 className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-3">All Attachments ({selectedTicket.image_urls.length})</h4>
                                            <div className="grid grid-cols-2 gap-3">
                                                {selectedTicket.image_urls.map((url, idx) => (
                                                    <div key={idx} className="aspect-square rounded-xl overflow-hidden border border-gray-200 bg-white group cursor-pointer" onClick={() => window.open(url, '_blank')}>
                                                        <img src={url} alt={`Attachment ${idx + 1}`} className="w-full h-full object-cover group-hover:scale-110 transition-transform" />
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </section>

                            <section className="pt-8 border-t border-gray-100">
                                <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest mb-3">Reply to Customer</h4>
                                <div className="space-y-3">
                                    <div className="bg-gray-50 rounded-2xl border border-gray-100 p-4 space-y-3 max-h-48 overflow-y-auto">
                                        <div className="rounded-xl bg-white border border-gray-200 p-3">
                                            <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Customer</div>
                                            <p className="text-sm text-gray-700 whitespace-pre-wrap">{selectedTicket.description}</p>
                                        </div>
                                        {(selectedTicket.admin_replies || []).map((reply, idx) => (
                                            <div key={`${selectedTicket.id}-reply-${idx}`} className="rounded-xl bg-blue-50 border border-blue-100 p-3">
                                                <div className="text-[10px] font-black text-blue-500 uppercase tracking-widest mb-1">Admin</div>
                                                <p className="text-sm text-blue-800 whitespace-pre-wrap">{reply.message}</p>
                                                {reply.created_at && (
                                                    <div className="mt-1 text-[10px] text-blue-400">
                                                        {new Date(reply.created_at).toLocaleString()}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                    <textarea
                                        className="w-full rounded-2xl border-gray-200 focus:border-primary-500 focus:ring-primary-500 bg-blue-50/30 p-4 text-sm italic text-blue-800"
                                        rows={3}
                                        value={replyDraft}
                                        onChange={(e) => setReplyDraft(e.target.value)}
                                        placeholder="Write a message that will be shown to the customer..."
                                    />
                                    <p className="text-[10px] text-gray-400 italic">This message is visible to the customer in their ticket details.</p>
                                </div>
                            </section>
                        </div>

                        <div className="p-6 bg-gray-50 border-t border-gray-100 flex justify-end">
                            <button
                                onClick={() => handleSendReply(selectedTicket.id)}
                                disabled={isUpdating || !replyDraft.trim()}
                                className="px-10 py-3 bg-gray-900 text-white rounded-2xl font-bold text-sm hover:bg-gray-800 transition-all shadow-lg active:scale-95"
                            >
                                {isUpdating ? 'Sending...' : 'Send to Customer'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

