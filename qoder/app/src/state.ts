import type { CollectionInfo, ReviewEntry } from './api';

export interface AppState {
  currentCourse: string | null;
  collections: CollectionInfo[];
  reviewProgress: Map<string, ReviewEntry>;
  lastSearchTime: { embed: number; search: number; total: number } | null;
  modelReady: boolean;
  importProgress: { current: number; total: number } | null;
}

const STORAGE_KEY = 'studystack_state';

export function loadState(): Partial<AppState> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return {
      currentCourse: parsed.currentCourse || null,
    };
  } catch {
    return {};
  }
}

export function saveState(state: AppState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      currentCourse: state.currentCourse,
    }));
  } catch { /* quota exceeded */ }
}

export function setStatus(text: string) {
  const el = document.getElementById('status-bar');
  if (el) el.textContent = text;
}

export function showToast(message: string, type: 'info' | 'error' | 'success' = 'info') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}
