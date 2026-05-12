import { useState } from 'react';
import Typing from '../ui/Typing';

const QUICK_IDS = ['USR001', 'USR002', 'USR003'];

export default function ProfileSearch({ onSearch, loading }) {
  const [val, setVal] = useState('');

  const go = (id) => {
    if (!id) return;
    setVal(id);
    onSearch(id);
  };

  return (
    <div className="card mb4">
      <div className="f ac g3">
        <input
          className="inp f1"
          placeholder="Enter profile ID (try USR001, USR002, USR003)"
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && go(val.trim())}
        />
        <button
          className="btn btn-p"
          onClick={() => go(val.trim())}
          disabled={loading || !val.trim()}
        >
          {loading ? <Typing /> : 'Inspect →'}
        </button>
      </div>

      <div className="f g2 mt3 ac">
        <span className="xs dim">Quick load:</span>
        {QUICK_IDS.map(id => (
          <button key={id} className="btn btn-g btn-s" onClick={() => go(id)}>
            {id}
          </button>
        ))}
      </div>
    </div>
  );
}
