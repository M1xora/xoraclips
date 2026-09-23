import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { LanguageProvider } from './locales'
import './index.css'
import App from './App.tsx'
import { migrateBrowserStorage } from '../src-next/lib/storageMigration'

// Runs on this UI's own port too (different origin, own storage). Issue #14.
migrateBrowserStorage()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
)
