export default function SectionTitle({ label, right }) {
  return (
    <div className="f ac jb mb4">
      <span className="stitle">{label}</span>
      {right}
    </div>
  );
}
