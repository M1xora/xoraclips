import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '../styles/theme.css';
import { App } from './App';
import { LanguageProvider } from '../i18n';
import { ErrorBoundary } from '../components/ErrorBoundary';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <ErrorBoundary section="Cheat Clip">
        <App />
      </ErrorBoundary>
    </LanguageProvider>
  </StrictMode>,
);
