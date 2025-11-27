import React, { useEffect, useRef } from 'react';

const ChatWindow = ({ messages }) => {
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  return (
    <div className="chat-window">
      {messages.map((msg) => (
        <div key={msg.id} className={`message ${msg.sender === 'me' ? 'user' : 'bot'}`}>
          <div className="message-content">{msg.text}</div>
          <span className="message-time">
            {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
};

export default ChatWindow;
