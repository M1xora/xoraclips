import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '../styles/theme.css';
import { App } from './App';
import { LanguageProvider } from '../i18n';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { purgeLegacyApiKey } from '../features/analyze/serverStatus';

// Older versions kept the user's Gemini key in the browser. The key now
// lives only on the server (issue #8), so remove any copy left behind.
purgeLegacyApiKey(() => window.localStorage);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <ErrorBoundary section="Cheat Clip">
        <App />
      </ErrorBoundary>
    </LanguageProvider>
  </StrictMode>,
);
