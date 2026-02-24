import React from 'react';
import { ChatStats } from '../../types/analytics';

interface ChatStatsCardsProps {
    stats: ChatStats;
}

export const ChatStatsCards: React.FC<ChatStatsCardsProps> = ({ stats }) => {
    const safeTotalChats = Number.isFinite(stats.totalChats) ? stats.totalChats : 0;
    const safeTotalMessages = Number.isFinite(stats.totalMessages) ? stats.totalMessages : 0;
    const safeAvgResponseTime = Number.isFinite(stats.avgResponseTime) ? stats.avgResponseTime : 0;
    const safeUserSatisfaction = Number.isFinite(stats.userSatisfaction) ? stats.userSatisfaction : 0;

    const cards = [
        {
            title: 'Total Chats',
            value: safeTotalChats.toLocaleString(),
            icon: (
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
            ),
            color: 'from-blue-500 to-blue-600',
        },
        {
            title: 'Total Messages',
            value: safeTotalMessages.toLocaleString(),
            icon: (
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
                </svg>
            ),
            color: 'from-green-500 to-green-600',
        },
        {
            title: 'Avg Response Time',
            value: `${safeAvgResponseTime.toFixed(1)}s`,
            icon: (
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
            ),
            color: 'from-yellow-500 to-yellow-600',
        },
        {
            title: 'User Satisfaction',
            value: `${safeUserSatisfaction.toFixed(0)}%`,
            icon: (
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
            ),
            color: 'from-purple-500 to-purple-600',
        },
    ];

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {cards.map((card, index) => (
                <div
                    key={index}
                    className="bg-white rounded-xl shadow-sm p-6 hover:shadow-md transition-shadow"
                >
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-sm font-medium text-gray-600">{card.title}</p>
                            <p className="mt-2 text-3xl font-bold text-gray-900">{card.value}</p>
                        </div>
                        <div className={`p-3 rounded-lg bg-gradient-to-r ${card.color} text-white`}>
                            {card.icon}
                        </div>
                    </div>
                </div>
            ))}
        </div>
    );
};
