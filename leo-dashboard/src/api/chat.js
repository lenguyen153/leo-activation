import { apiFetch } from './client';

// POST /chat — { prompt: string } → { answer: string, debug: any }
export async function sendChat(message) {
  const data = await apiFetch('/chat', { body: { prompt: message } });
  return data.answer;
}
