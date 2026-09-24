/**
 * One video plays at a time (#40).
 *
 * The source video and the Studio preview are separate YouTube players. Now
 * that the preview can be heard, both playing at once would talk over each
 * other, so a player that starts playing pauses every other one.
 */

interface Pausable {
  pauseVideo(): void;
}

const players = new Set<Pausable>();

/** Adds a player; the returned function removes it again. */
export function registerPlayer(player: Pausable): () => void {
  players.add(player);
  return () => {
    players.delete(player);
  };
}

/** Pauses every registered player except `player`. */
export function pauseOthers(player: Pausable): void {
  for (const other of players) {
    if (other === player) continue;
    try {
      other.pauseVideo();
    } catch {
      // A player that is being torn down.
    }
  }
}
