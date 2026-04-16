export default function RiskBadge({ score }) {
  if (score == null) return <span className="risk-badge none">N/A</span>;

  let level, label;
  if (score >= 70) {
    level = "critical";
    label = "Critical";
  } else if (score >= 50) {
    level = "high";
    label = "High";
  } else if (score >= 30) {
    level = "medium";
    label = "Medium";
  } else {
    level = "low";
    label = "Low";
  }

  return (
    <span className={`risk-badge ${level}`} title={`Risk score: ${score}`}>
      {label} ({score})
    </span>
  );
}
