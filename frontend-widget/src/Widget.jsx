import { useState } from 'react'
import './Widget.css'

export default function Widget({ config = {} }) {
    const [isOpen, setIsOpen] = useState(false)
    const [messages, setMessages] = useState([])
    const [input, setInput] = useState('')

    const [isLoading, setIsLoading] = useState(false)
    const [sessionId, setSessionId] = useState(localStorage.getItem('genai_session_id'))

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return

        const userMessage = { role: 'user', content: input }
        setMessages(prev => [...prev, userMessage])
        setInput('')
        setIsLoading(true)

        try {
            const response = await fetch('http://localhost:8000/api/v1/chat/message', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: userMessage.content,
                    session_id: sessionId,
                    tenant_id: config.merchantId // Pass merchant ID as tenant ID
                }),
            })

            if (!response.ok) throw new Error('Failed to send message')

            const data = await response.json()

            // Save session ID if new
            if (data.session_id && data.session_id !== sessionId) {
                setSessionId(data.session_id)
                localStorage.setItem('genai_session_id', data.session_id)
            }

            setMessages(prev => [...prev, {
                role: 'assistant',
                content: data.response
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
