/**
 * The AI's title options for a clip, as buttons under "Judul klip aktif"
 * (issue #31). Picking one is local: no new request to Gemini.
 *
 * The first option is the clip's own AI title (the backend also puts it in
 * title_suggestion), so choosing it clears the custom title. The others are
 * stored as the custom title, exactly like a title typed by hand.
 */
export interface TitleChoice {
  text: string;
  /** What to store as the clip's custom title when this is picked. */
  value: string;
  active: boolean;
}

export function titleChoices(options: readonly string[] | undefined, customTitle: string): TitleChoice[] {
  const list = (options ?? []).map((o) => o.trim()).filter(Boolean);
  // One option (or an analysis made before #31) leaves nothing to choose.
  if (list.length < 2) return [];
  const custom = customTitle.trim();
  return list.map((text, i) => ({
    text,
    value: i === 0 ? '' : text,
    active: i === 0 ? custom === '' || custom === text : custom === text,
  }));
}
