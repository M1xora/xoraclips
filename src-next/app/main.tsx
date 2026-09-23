import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '../styles/theme.css';
import { App } from './App';
import { LanguageProvider } from '../i18n';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { migrateBrowserStorage } from '../lib/storageMigration';

migrateBrowserStorage();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <ErrorBoundary section="Xoraclips">
        <App />
      </ErrorBoundary>
    </LanguageProvider>
  </StrictMode>,
);
