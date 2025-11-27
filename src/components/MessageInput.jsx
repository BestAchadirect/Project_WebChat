import React, { useState } from 'react';

const MessageInput = ({ onSendMessage }) => {
    const [text, setText] = useState('');

    const handleSubmit = (e) => {
        e.preventDefault();
        if (text.trim()) {
            onSendMessage(text);
            setText('');
        }
    };

    return (
        <form className="input-area" onSubmit={handleSubmit}>
            <input
                type="text"
                className="message-input"
                placeholder="Type a message..."
                value={text}
                onChange={(e) => setText(e.target.value)}
            />
            <button type="submit" className="send-button" aria-label="Send">
                <svg viewBox="0 0 24 24">
                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                </svg>
            </button>
        </form>
    );
};

export default MessageInput;
