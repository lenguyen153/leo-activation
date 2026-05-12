export default function AppLayout({ tabs, activeTab, onTabChange, agentPanel, children }) {
  return (
    <div className="main-wrap">
      <div className="canvas">
        <div className="tab-bar">
          {tabs.map(t => (
            <button
              key={t.id}
              className={`tab${activeTab === t.id ? ' on' : ''}`}
              onClick={() => onTabChange(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="canvas-body">{children}</div>
      </div>

      <div className="agent-col">{agentPanel}</div>
    </div>
  );
}
