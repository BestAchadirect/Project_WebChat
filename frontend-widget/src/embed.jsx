import React from 'react'
import { createRoot } from 'react-dom/client'
import Widget from './Widget.jsx'

function ensureContainer() {
  const existing = document.getElementById('genai-widget-root')
  if (existing) return existing

  const el = document.createElement('div')
  el.id = 'genai-widget-root'
  document.body.appendChild(el)
  return el
}

function readGlobalConfig() {
  return (window.genaiConfig || {})
}

export function mountWidget(container, config = {}) {
  const root = createRoot(container)
  root.render(<Widget config={config} />)
  return root
}

// Auto-mount if included via <script src=".../widget.js">
mountWidget(ensureContainer(), readGlobalConfig())

// Optional programmatic API
window.GenAIChatWidget = {
  mount: (container, config) => mountWidget(container, config),
  init: (config) => mountWidget(ensureContainer(), config || readGlobalConfig()),
}

