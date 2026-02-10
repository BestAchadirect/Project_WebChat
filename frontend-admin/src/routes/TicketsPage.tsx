import React, { useEffect, useState } from 'react';
import apiClient from '../api/client';

interface Ticket {
    id: number;
    user_id: string;
    description: string;
    image_url?: string;
    image_urls?: string[];
    status: string;
    ai_summary?: string;
    created_at: string;
    updated_at: string;
}

export const TicketsPage: React.FC = () => {
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
    const [isUpdating, setIsUpdating] = useState(false);

    const fetchTickets = async () => {
        setIsLoading(true);
        try {
            const { data } = await apiClient.get<Ticket[]>('/tickets/all');
            setTickets(data);
        } catch (error) {
            console.error('Failed to fetch tickets:', error);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchTickets();
    }, []);

    const handleUpdateStatus = async (ticketId: number, newStatus: string) => {
        setIsUpdating(true);
        try {
            await apiClient.patch(`/tickets/${ticketId}`, { status: newStatus });
            fetchTickets();
            if (selectedTicket?.id === ticketId) {
                setSelectedTicket(prev => prev ? { ...prev, status: newStatus } : null);
            }
        } catch (error) {
            console.error('Failed to update ticket status:', error);
        } finally {
            setIsUpdating(false);
        }
    };

    const handleUpdateSummary = async (ticketId: number, newSummary: string) => {
        setIsUpdating(true);
        try {
            await apiClient.patch(`/tickets/${ticketId}`, { ai_summary: newSummary });
            fetchTickets();
        } catch (error) {
            console.error('Failed to update ticket summary:', error);
        } finally {
            setIsUpdating(false);
        }
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
                <h2 className="text-2xl font-bold text-gray-800">Ticket Management</h2>
                <button
                    onClick={fetchTickets}
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
                                <td className="px-6 py-4 font-mono text-sm text-gray-600">{formatTicketNumber(ticket)}</td>
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
                                        onClick={() => setSelectedTicket(ticket)}
                                        className="text-primary-600 hover:text-primary-700 text-sm font-semibold"
                                    >
                                        View Details
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
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
                                <h4 className="text-xs font-black text-gray-400 uppercase tracking-widest mb-3">Manual AI Resolution Summary Edit</h4>
                                <div className="space-y-3">
                                    <textarea
                                        className="w-full rounded-2xl border-gray-200 focus:border-primary-500 focus:ring-primary-500 bg-blue-50/30 p-4 text-sm italic text-blue-800"
                                        rows={3}
                                        defaultValue={selectedTicket.ai_summary}
                                        onBlur={(e) => handleUpdateSummary(selectedTicket.id, e.target.value)}
                                        placeholder="Edit the resolution summary for the customer..."
                                    />
                                    <p className="text-[10px] text-gray-400 italic">This summary is what the customer sees as the "Issue Type / AI Detected Summary" in their widget.</p>
                                </div>
                            </section>
                        </div>

                        <div className="p-6 bg-gray-50 border-t border-gray-100 flex justify-end">
                            <button
                                onClick={() => setSelectedTicket(null)}
                                className="px-10 py-3 bg-gray-900 text-white rounded-2xl font-bold text-sm hover:bg-gray-800 transition-all shadow-lg active:scale-95"
                            >
                                Close & Save
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

