import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([
    { text: "Hi! How can I assist you today?", isBot: true }
  ]);
  const [inputText, setInputText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const chatBoxRef = useRef(null);

  useEffect(() => {
    if (chatBoxRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [messages]);

  const formatMessage = (text) => {
    return text.split('\n').map((line, i) => (
      <React.Fragment key={i}>
        {line}
        {i !== text.split('\n').length - 1 && <br />}
      </React.Fragment>
    ));
  };

  const handleSend = async () => {
    if (inputText.trim() === "" || isLoading) return;

    const userMessage = inputText.trim();
    setMessages(prev => [...prev, { text: userMessage, isBot: false }]);
    setIsLoading(true);
    setInputText("");

    try {
      // Log the request for debugging
      const requestBody = {
        prompt: userMessage,
        ...(sessionId && { session_id: sessionId })
      };
      console.log('Sending request:', requestBody);

      const response = await fetch('https://k3vyti4vtb.execute-api.us-east-1.amazonaws.com/prod/chatbot', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(requestBody),
      });

      // Log raw response for debugging
      const rawResponse = await response.clone().text();
      console.log('Raw response:', rawResponse);

      if (!response.ok) {
        throw new Error(`Server error: ${response.status} - ${rawResponse}`);
      }

      // Try to parse the response
      let parsedResponse;
      try {
        parsedResponse = JSON.parse(rawResponse);
      } catch (parseError) {
        console.error('Failed to parse response:', parseError);
        throw new Error('Invalid response format from server');
      }

      // Handle the parsed response
      if (parsedResponse.body) {
        let bodyContent;
        try {
          // Check if body is already an object or needs parsing
          bodyContent = typeof parsedResponse.body === 'string'
            ? JSON.parse(parsedResponse.body)
            : parsedResponse.body;

          // Update session if provided
          if (bodyContent.session_id && !sessionId) {
            setSessionId(bodyContent.session_id);
          }

          // Add bot response to messages
          const botResponse = bodyContent.response || 'Sorry, I could not process your request.';
          setMessages(prev => [...prev, { text: botResponse, isBot: true }]);

        } catch (bodyParseError) {
          console.error('Failed to parse body:', bodyParseError);
          throw new Error('Invalid response body format');
        }
      } else {
        throw new Error('Response missing required data');
      }

    } catch (error) {
      console.error('Error details:', error);
      setMessages(prev => [...prev, {
        text: "I apologize, but I'm having trouble processing your request. Please try again.",
        isBot: true
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !isLoading && inputText.trim()) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <img src="https://www.jaymart.co.th/storage/home/icon.png" alt="Jaymart Logo" />
        </div>
        <div className="header-title">
          <span className="company-name">Jaymart</span>
          <span className="separator">|</span>
          <span className="chatbot-text">Chatbot</span>
        </div>
      </header>

      <div className="chat-container">
        <div
          ref={chatBoxRef}
          className="chat-box"
        >
          {messages.map((message, index) => (
            <div
              key={index}
              className={`message ${message.isBot ? 'bot-message' : 'user-message'}`}
            >
              {formatMessage(message.text)}
            </div>
          ))}
          {isLoading && (
            <div className="message bot-message loading">
              Thinking...
            </div>
          )}
        </div>

        <div className="input-container">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Type your message here..."
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !inputText.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;