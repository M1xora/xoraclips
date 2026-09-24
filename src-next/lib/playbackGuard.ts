/**
 * One sound at a time (#40).
 *
 * The source video and the Studio preview are separate YouTube players. Now
 * that the preview can be heard, both playing with sound would talk over
 * each other. So a player that starts playing WITH sound pauses the other
 * players that have sound. A muted player (the preview before its sound
 * button is pressed) neither pauses nor gets paused.
 */

interface Pausable {
  pauseVideo(): void;
  isMuted?(): boolean;
}

const players = new Set<Pausable>();

/** Adds a player; the returned function removes it again. */
export function registerPlayer(player: Pausable): () => void {
  players.add(player);
  return () => {
    players.delete(player);
  };
}

function audible(player: Pausable): boolean {
  try {
    return !(player.isMuted?.() ?? false);
  } catch {
    return false;
  }
}

/** When `player` has sound, pauses every other player that has sound. */
export function pauseOthers(player: Pausable): void {
  if (!audible(player)) return;
  for (const other of players) {
    if (other === player || !audible(other)) continue;
    try {
      other.pauseVideo();
    } catch {
      // A player that is being torn down.
    }
  }
}
