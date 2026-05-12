export default function EmptyState({ icon, title, subtitle, children }) {
  return (
    <div className="empty">
      {icon     && <div className="empty-ic">{icon}</div>}
      {title    && <div className="md sb">{title}</div>}
      {subtitle && <div className="sm sub">{subtitle}</div>}
      {children}
    </div>
  );
}
