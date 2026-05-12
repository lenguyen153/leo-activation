import { useState, useEffect, useRef, useCallback } from 'react';
import { CHAT_INIT, SUGGESTIONS } from '../../data/chat';
import { sendChat } from '../../api/chat';
import { mockReply } from '../../utils/mockReply';
import Typing from '../ui/Typing';

function formatBold(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>');
}

function nowTs() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function AgentPanel() {
  const [msgs,   setMsgs] = useState(CHAT_INIT);
  const [input,  setInp]  = useState('');
  const [typing, setTyp]  = useState(false);
  const bottomRef         = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [msgs, typing]);

  const send = useCallback(async (text) => {
    const t = (text || input).trim();
    if (!t) return;

    setMsgs(p => [...p, { id: Date.now(), role: 'u', text: t, ts: nowTs() }]);
    setInp('');
    setTyp(true);

    try {
      // Call real backend; enforce a minimum 500ms typing indicator so it doesn't flash
      const [answer] = await Promise.all([
        sendChat(t),
        new Promise(r => setTimeout(r, 500)),
      ]);
      setMsgs(p => [...p, { id: Date.now() + 1, role: 'a', text: answer, ts: nowTs() }]);
    } catch {
      // Backend unreachable — fall back to local keyword matching
      await new Promise(r => setTimeout(r, 700 + Math.random() * 600));
      setMsgs(p => [...p, { id: Date.now() + 1, role: 'a', text: mockReply(t), ts: nowTs() }]);
    } finally {
      setTyp(false);
    }
  }, [input]);

  return (
    <>
      <div className="agt-hdr">
        <div className="pulse-dot" />
        <div className="f1">
          <div className="sm sb">LEO Agent</div>
          <div className="xs dim">Gemini • Tool-mediated CDP access</div>
        </div>
        <span className="bdg bdg-ok">Online</span>
      </div>

      <div className="chat-msgs">
        {msgs.map(msg => (
          <div key={msg.id} className={`msg-${msg.role}`}>
            <div
              className="bubble"
              dangerouslySetInnerHTML={{ __html: formatBold(msg.text) }}
            />
            <div className="msg-ts">{msg.ts}</div>
          </div>
        ))}
        {typing && (
          <div className="msg-a">
            <div className="bubble"><Typing /></div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="sugg-area">
        <div className="xs dim mb2">Quick prompts</div>
        <div className="fc g1">
          {SUGGESTIONS.map(s => (
            <button
              key={s}
              className="btn btn-g btn-s"
              style={{ justifyContent: 'flex-start', fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
              onClick={() => send(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="chat-inp-row">
        <input
          className="inp f1"
          placeholder="Ask LEO anything…"
          value={input}
          onChange={e => setInp(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
        />
        <button
          className="btn btn-p btn-s"
          onClick={() => send()}
          disabled={!input.trim() || typing}
        >
          ↑
        </button>
      </div>
    </>
  );
}
