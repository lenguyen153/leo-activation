export default function Header() {
  return (
    <header className="hdr">
      <div className="logo">
        <div className="logo-mk">L</div>
        <div>
          <div className="sb" style={{ fontSize: 'var(--fs-md)' }}>LEO Activation</div>
          <div className="xs dim">AI Marketing Platform</div>
        </div>
      </div>

      <div className="f ac g3">
        <span className="bdg bdg-ok">● Live CDC</span>
        <div className="card2 f ac g2 py2">
          <span className="xs sub">Model:</span>
          <span className="xs sec m">gemini-2.5-flash-lite</span>
        </div>
        <span className="xs sub">2026-05-12</span>
      </div>
    </header>
  );
}
