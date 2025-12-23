import { useState } from 'react'
import './Widget.css'

export default function Widget({ config = {} }) {
    const [isOpen, setIsOpen] = useState(false)
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')

    const [isLoading, setIsLoading] = useState(false)
    const [conversationId, setConversationId] = useState(() => {
        const raw = localStorage.getItem('genai_conversation_id')
        const n = raw ? Number(raw) : undefined
        return Number.isFinite(n) ? n : undefined
    })

    const getUserId = () => {
        let userId = localStorage.getItem('genai_user_id')
        if (!userId) {
            userId = `guest_${Math.random().toString(36).slice(2, 11)}`
            localStorage.setItem('genai_user_id', userId)
        }
        return userId
    }

    const resolveApiBaseUrl = () => {
        const raw =
            (config.apiBaseUrl && String(config.apiBaseUrl)) ||
            (config.apiUrl && `${String(config.apiUrl).replace(/\\/+$/, '')}/api/v1`) ||
            (import.meta.env.VITE_API_BASE_URL || '/api/v1')

        return String(raw).trim().replace(/\\/+$/, '')
    }

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return

        const userMessage = { role: 'user', content: input }
        setMessages(prev => [...prev, userMessage])
        setInput('')
        setIsLoading(true)

        try {
            const apiBaseUrl = resolveApiBaseUrl()
            const response = await fetch(`${apiBaseUrl}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_id: getUserId(),
                    message: userMessage.content,
                    conversation_id: conversationId,
                    locale: config.locale || 'en-US',
                    customer_name: config.customerName,
                    email: config.email,
                }),
            })

            if (!response.ok) throw new Error('Failed to send message')

            const data = await response.json()

            if (typeof data.conversation_id === 'number' && data.conversation_id !== conversationId) {
                setConversationId(data.conversation_id)
                localStorage.setItem('genai_conversation_id', String(data.conversation_id))
            }

            setMessages(prev => [...prev, {
                role: 'assistant',
                content: data.reply_text ?? '...'
            }])
        } catch (error) {
            console.error('Error:', error)
            setMessages(prev => [...prev, {
                role: 'system',
                content: 'Sorry, I encountered an error. Please try again.'
            }])
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <div className="genai-widget">
            {!isOpen && (
                <button
                    className="genai-widget-toggle"
                    onClick={() => setIsOpen(true)}
                    style={{ backgroundColor: config.primaryColor || '#4F46E5' }}
                >
                    💬
                </button>
            )}

            {isOpen && (
                <div className="genai-widget-container">
                    <div className="genai-widget-header" style={{ backgroundColor: config.primaryColor || '#4F46E5' }}>
                        <h3>{config.title || 'Chat with us'}</h3>
                        <button onClick={() => setIsOpen(false)}>✕</button>
                    </div>

                    <div className="genai-widget-messages">
                        {messages.map((msg, i) => (
                            <div key={i} className={`message ${msg.role}`}>
                                {msg.content}
                            </div>
                        ))}
                    </div>

                    <div className="genai-widget-input">
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
                            placeholder="Type a message..."
                        />
                        <button onClick={sendMessage}>Send</button>
                    </div>
                </div>
            )}
        </div>
    )
}
