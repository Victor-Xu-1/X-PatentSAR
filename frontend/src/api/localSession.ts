import type { Session } from './types';
import { ApiError } from './errors';

/** One ephemeral same-origin session authority; no persisted tokens or retry loop. */
export class LocalSession {
  private current: Session | null = null;
  private pending: Promise<Session> | null = null;
  private pendingGeneration = -1;
  private generation = 0;
  constructor(private readonly load: () => Promise<Session>) {}

  reset() {
    this.generation++;
    this.current = null;
    // Let an older wire response settle before starting a new handshake, so
    // its HttpOnly Set-Cookie cannot race the explicit reconnect's credentials.
  }

  invalidate(observed: Session) {
    // A late rejected old read must not erase another reader's new session.
    if (this.current === observed) this.current = null;
  }

  bootstrap(): Promise<Session> {
    if (this.current) return Promise.resolve(this.current);
    if (this.pending) {
      if (this.pendingGeneration === this.generation) return this.pending;
      return this.pending.then(
        () => this.bootstrap(),
        () => this.bootstrap(),
      );
    }
    const generation = this.generation;
    const pending = this.load()
      .then((session) => {
        if (generation !== this.generation)
          throw new ApiError(0, 'session_superseded', '本地会话已更新，请重新加载。');
        this.current = session;
        return session;
      })
      .finally(() => {
        if (this.pending === pending) this.pending = null;
      });
    this.pending = pending;
    this.pendingGeneration = generation;
    return pending;
  }
}
