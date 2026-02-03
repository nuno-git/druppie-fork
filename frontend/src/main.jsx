import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

// Log URL parameters for debugging
console.log('[Main] Page loaded')
console.log('[Main] Current URL:', window.location.href)
console.log('[Main] Search params:', window.location.search)
console.log('[Main] Hash:', window.location.hash)

// Parse search params
if (window.location.search) {
  const params = new URLSearchParams(window.location.search)
  console.log('[Main] Parsed params:')
  for (const [key, value] of params) {
    console.log(`[Main]   ${key}=${value}`)
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
