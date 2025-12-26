import React from 'react';
import { createRoot, Root } from 'react-dom/client';
import { ChatWidget } from '../components/chat/ChatWidget';
import './widget.css';

type WidgetConfig = Window['genaiConfig'];

declare global {
    interface Window {
        GenAIChatWidget?: {
            mount: (container: HTMLElement, config?: WidgetConfig) => Root;
            init: (config?: WidgetConfig) => Root;
        };
    }
}

const ensureContainer = (): HTMLElement => {
    const existing = document.getElementById('genai-widget-root');
    if (existing) {
        return existing;
    }

    const container = document.createElement('div');
    container.id = 'genai-widget-root';
    document.body.appendChild(container);
    return container;
};

const readConfig = (): WidgetConfig => window.genaiConfig || {};

export const mountWidget = (container: HTMLElement, config?: WidgetConfig): Root => {
    const resolvedConfig = config || {};
    const root = createRoot(container);
    root.render(
        <ChatWidget
            title={resolvedConfig.title}
            primaryColor={resolvedConfig.primaryColor}
            welcomeMessage={resolvedConfig.welcomeMessage}
            faqSuggestions={resolvedConfig.faqSuggestions}
            apiBaseUrl={resolvedConfig.apiBaseUrl || resolvedConfig.apiUrl}
            locale={resolvedConfig.locale}
            customerName={resolvedConfig.customerName}
            email={resolvedConfig.email}
        />
    );
    return root;
};

mountWidget(ensureContainer(), readConfig());

window.GenAIChatWidget = {
    mount: (container, config) => mountWidget(container, config),
    init: (config) => mountWidget(ensureContainer(), config || readConfig()),
};
