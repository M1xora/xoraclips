// Re-exports, so `import { useLanguage } from '../i18n'` keeps working while
// the provider component lives in a file of its own (fast refresh, #2).
export { LanguageProvider } from './LanguageProvider';
export { useLanguage, type Language, type LanguageContextValue } from './context';
