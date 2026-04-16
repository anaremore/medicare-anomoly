import { useApi } from "../hooks/useApi";

export default function Dashboard({ onAddressClick }) {
  const { data: stats, loading, error } = useApi("/stats");
  const { data: alerts } = useApi("/alerts", { per_page: 5 });

  if (loading) return <div className="loading">Loading dashboard...</div>;
  if (error) return <div className="error">Error: {error}</div>;
  if (!stats) return null;

  return (
    <div className="dashboard">
      <div className="stat-grid">
        <StatCard
          label="Target Providers"
          value={stats.total_providers}
          desc="DME, HHA, Hospice in Houston area"
        />
        <StatCard
          label="Unique Addresses"
          value={stats.total_addresses}
          desc="Distinct practice locations"
        />
        <StatCard
          label="Flagged Addresses"
          value={stats.flagged_addresses}
          desc="5+ target providers at same address"
          highlight
        />
        <StatCard
          label="High-Risk Providers"
          value={stats.high_risk_providers}
          desc="Composite score >= 50"
          highlight
        />
        <StatCard
          label="Active Alerts"
          value={stats.active_alerts}
          desc={`${stats.critical_alerts} critical`}
          highlight={stats.critical_alerts > 0}
        />
        <StatCard
          label="TX Exclusions"
          value={stats.total_exclusions_tx}
          desc="OIG LEIE excluded entities"
        />
      </div>

      <div className="dashboard-row">
        <div className="panel">
          <h3>Top ZIP Codes by Provider Count</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>ZIP</th>
                <th>Providers</th>
              </tr>
            </thead>
            <tbody>
              {(stats.top_zips || []).map((z) => (
                <tr key={z.zip}>
                  <td>{z.zip}</td>
                  <td>{z.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <h3>Recent Alerts</h3>
          {alerts?.results?.length > 0 ? (
            <ul className="alert-list-compact">
              {alerts.results.map((a) => (
                <li key={a.id} className={`alert-item ${a.severity}`}>
                  <span className={`severity-dot ${a.severity}`} />
                  <span className="alert-type">
                    {a.alert_type.replace(/_/g, " ")}
                  </span>
                  {a.details?.org_name && (
                    <span className="alert-entity">{a.details.org_name}</span>
                  )}
                  {a.details?.address && (
                    <span className="alert-address">{a.details.address}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No alerts yet. Run the analysis pipeline.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, desc, highlight }) {
  return (
    <div className={`stat-card ${highlight ? "highlight" : ""}`}>
      <div className="stat-value">{value?.toLocaleString() ?? "—"}</div>
      <div className="stat-label">{label}</div>
      {desc && <div className="stat-desc">{desc}</div>}
    </div>
  );
}
