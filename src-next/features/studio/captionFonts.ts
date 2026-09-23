/**
 * The caption fonts the renderer uses (backend/fonts), so the preview draws
 * titles and subtitles in the same typeface as the video (issue #22).
 *
 * Taken straight from backend/fonts: Vite copies the listed files at build
 * time, so there is one copy in the repo. The faces are declared up front;
 * the browser downloads a file only once a caption uses that font.
 *
 * Each file is a single static weight (Outfit, Inter, Montserrat 800;
 * Poppins 700; Anton, Bebas Neue 400). The first four declare the whole
 * weight range so the browser uses the file as it is, like libass does.
 * Anton and Bebas Neue declare only 400, so the bold the preview asks for is
 * synthesised, as libass synthesises it for Bold=-1.
 */

export interface CaptionFontFace {
  family: string;
  file: string;
  weight: string;
}

export const CAPTION_FONT_FACES: CaptionFontFace[] = [
  { family: 'XC Outfit', file: 'Outfit.ttf', weight: '100 900' },
  { family: 'XC Montserrat', file: 'Montserrat.ttf', weight: '100 900' },
  { family: 'XC Inter', file: 'Inter.ttf', weight: '100 900' },
  { family: 'XC Poppins', file: 'Poppins.ttf', weight: '100 900' },
  { family: 'XC Anton', file: 'Anton.ttf', weight: '400' },
  { family: 'XC Bebas Neue', file: 'Bebas Neue.ttf', weight: '400' },
];

// Listed by name, not *.ttf: the folder also holds a 13 MB emoji font the
// preview never needs, and a glob would ship it.
const FONT_URLS = import.meta.glob(
  [
    '../../../backend/fonts/Outfit.ttf',
    '../../../backend/fonts/Montserrat.ttf',
    '../../../backend/fonts/Inter.ttf',
    '../../../backend/fonts/Poppins.ttf',
    '../../../backend/fonts/Anton.ttf',
    '../../../backend/fonts/Bebas Neue.ttf',
  ],
  { query: '?url', import: 'default', eager: true },
) as Record<string, string>;

/** The URL a font file is served from, by file name. */
export function captionFontUrl(file: string): string | undefined {
  return FONT_URLS[`../../../backend/fonts/${file}`];
}

export function captionFontCss(): string {
  return CAPTION_FONT_FACES.map((face) => {
    const url = captionFontUrl(face.file);
    if (!url) return '';
    return (
      `@font-face{font-family:'${face.family}';src:url("${url}") format('truetype');` +
      `font-weight:${face.weight};font-display:swap}`
    );
  }).join('\n');
}

/** Declares the faces once, at start-up. */
export function installCaptionFonts(doc: Document = document): void {
  if (doc.getElementById('caption-fonts')) return;
  const style = doc.createElement('style');
  style.id = 'caption-fonts';
  style.textContent = captionFontCss();
  doc.head.appendChild(style);
}
