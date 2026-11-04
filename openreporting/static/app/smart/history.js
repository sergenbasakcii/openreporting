// Undo / redo for the smart dashboard editor: JSON snapshots of the model, capped and de-duplicated.
const LIMIT = 100;

export function createHistory(initial) {
  let past = [];
  let future = [];
  let current = JSON.stringify(initial);
  return {
    // Record the model after a change; identical consecutive states are ignored.
    push(model) {
      const next = JSON.stringify(model);
      if (next === current) return false;
      past.push(current);
      if (past.length > LIMIT) past = past.slice(-LIMIT);
      current = next;
      future = [];
      return true;
    },
    undo() {
      if (!past.length) return null;
      future.push(current);
      current = past.pop();
      return JSON.parse(current);
    },
    redo() {
      if (!future.length) return null;
      past.push(current);
      current = future.pop();
      return JSON.parse(current);
    },
    canUndo: () => past.length > 0,
    canRedo: () => future.length > 0,
    reset(model) { past = []; future = []; current = JSON.stringify(model); },
  };
}

// Unsaved work survives a closed tab or a crash: one draft per dashboard in this browser only.
const key = (uid) => `openreporting.smart.draft.${uid || 'new'}`;
export const drafts = {
  save(uid, model) { try { localStorage.setItem(key(uid), JSON.stringify({ at: Date.now(), model })); } catch { /* storage may be full or blocked */ } },
  load(uid) { try { return JSON.parse(localStorage.getItem(key(uid)) || 'null'); } catch { return null; } },
  clear(uid) { try { localStorage.removeItem(key(uid)); } catch { /* ignore */ } },
};
