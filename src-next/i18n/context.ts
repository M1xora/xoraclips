import { createContext, useContext } from 'react';
import type { Translations } from './id';

export type Language = 'id' | 'en';

export interface LanguageContextValue {
  language: Language;
  setLanguage: (next: Language) => void;
  t: Translations;
}

export const LanguageContext = createContext<LanguageContextValue | null>(null);

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLanguage must be used inside LanguageProvider');
  return ctx;
}
