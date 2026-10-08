import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { recoveryAction } from './useBatchRender';

/**
 * Issue #107: a browser refreshed mid-render keeps the batch id in storage,
 * and that id is the only way back to a render the backend is still working
 * on. Deciding when to throw it away is the whole safety question here.
 */
describe('recoveryAction', () => {
  it('forgets the id when the backend says it does not know the batch', () => {
    expect(recoveryAction(new ApiError(404, 'Batch not found'))).toBe('forget');
  });

  it('keeps the id when the backend could not be reached', () => {
    // A down backend throws a TypeError from fetch, not an ApiError. Treating
    // it like a 404 would drop a render that is still going.
    expect(recoveryAction(new TypeError('Failed to fetch'))).toBe('keep');
  });

  it('keeps the id when the backend failed for some other reason', () => {
    for (const status of [500, 502, 503, 408]) {
      expect(recoveryAction(new ApiError(status, 'boom'))).toBe('keep');
    }
  });

  it('keeps the id for anything it does not recognise', () => {
    for (const thrown of [undefined, null, 'string', 42, {}]) {
      expect(recoveryAction(thrown)).toBe('keep');
    }
  });
});
