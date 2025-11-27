import React, { useState } from 'react';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';

function App() {
  const [messages, setMessages] = useState([
    { id: 1, text: "Welcome to Project WebChat! How can I help you today?", sender: "bot", timestamp: new Date() }
  ]);

  const handleSendMessage = (text) => {
    const newMessage = {
      id: messages.length + 1,
      text: text,
      sender: "me",
      timestamp: new Date()
    };
    setMessages([...messages, newMessage]);

    // Simulate bot response
    setTimeout(() => {
      const botResponse = {
        id: messages.length + 2,
        text: "I received your message: " + text,
        sender: "bot",
        timestamp: new Date()
      };
      setMessages(prev => [...prev, botResponse]);
    }, 1000);
  };

  return (
    <>
      <header className="chat-header">
        <h1>Project WebChat</h1>
      </header>
      <ChatWindow messages={messages} />
      <MessageInput onSendMessage={handleSendMessage} />
    </>
  );
}

export default App;
