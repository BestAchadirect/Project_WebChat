import React from 'react'
import ReactDOM from 'react-dom/client'
import Widget from './Widget.jsx'

// This script will be embedded in merchant websites
// Usage: <script src="https://your-cdn.com/widget.js" data-merchant-id="xxx"></script>

(function () {
    // Get merchant config from script tag attributes
    const script = document.currentScript || document.querySelector('script[data-merchant-id]')
    const merchantId = script?.getAttribute('data-merchant-id')
    const primaryColor = script?.getAttribute('data-primary-color')
    const title = script?.getAttribute('data-title')

    // Create widget container
    const container = document.createElement('div')
    container.id = 'genai-widget-root'
    document.body.appendChild(container)

    // Mount React widget
    const root = ReactDOM.createRoot(container)
    root.render(
        <React.StrictMode>
            <Widget config={{ merchantId, primaryColor, title }} />
        </React.StrictMode>
    )
})()
