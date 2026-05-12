export default function Badge({ children, variant = 'gy', className = '' }) {
  return (
    <span className={`bdg bdg-${variant}${className ? ' ' + className : ''}`}>
      {children}
    </span>
  );
}
