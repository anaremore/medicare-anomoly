import { useState } from "react";
import { useApi } from "../hooks/useApi";

export default function AlertFeed() {
  const [severity, setSeverity] = useState("");
  const [alertType, setAlertType] = useState("");
  const [page, setPage] = useState(1);

  const { data, loading, error } = useApi("/alerts", {
    severity: severity || undefined,
    alert_type: alertType || undefined,
    page,
    per_page: 50,
  });

  return (
    <div className="alert-feed">
      <h2>Alert Feed</h2>
      <div className="filters">
        <select
          value={severity}
          onChange={(e) => {
            setSeverity(e.target.value);
            setPage(1);
          }}
          className="filter-input small"
        >
          <option value="">All Severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select
          value={alertType}
          onChange={(e) => {
            setAlertType(e.target.value);
            setPage(1);
          }}
          className="filter-input"
        >
          <option value="">All Types</option>
          <option value="new_registration_at_flagged">New Registration</option>
          <option value="registration_burst">Registration Burst</option>
          <option value="exclusion_proximity">Exclusion Proximity</option>
        </select>
      </div>

      {loading && <div className="loading">Loading...</div>}
      {error && <div className="error">Error: {error}</div>}

      {data && (
        <>
          <div className="result-count">{data.total} alerts</div>
          <div className="alert-cards">
            {data.results.map((alert) => (
              <div
                key={alert.id}
                className={`alert-card ${alert.severity}`}
              >
                <div className="alert-card-header">
                  <span className={`severity-badge ${alert.severity}`}>
                    {alert.severity}
                  </span>
                  <span className="alert-type-badge">
                    {alert.alert_type.replace(/_/g, " ")}
                  </span>
                  <span className="alert-date">
                    {alert.created_at
                      ? new Date(alert.created_at).toLocaleDateString()
                      : ""}
                  </span>
                </div>
                <div className="alert-card-body">
                  {alert.details?.org_name && (
                    <div>
                      <strong>Entity:</strong> {alert.details.org_name}
                    </div>
                  )}
                  {alert.details?.address && (
                    <div>
                      <strong>Address:</strong> {alert.details.address}
                    </div>
                  )}
                  {alert.details?.taxonomy && (
                    <div>
                      <strong>Type:</strong> {alert.details.taxonomy}
                    </div>
                  )}
                  {alert.details?.enumeration_date && (
                    <div>
                      <strong>Registered:</strong>{" "}
                      {alert.details.enumeration_date}
                    </div>
                  )}
                  {alert.details?.has_excluded_at_address && (
                    <div className="warning-text">
                      Address has OIG-excluded entity
                    </div>
                  )}
                  {alert.details?.note && (
                    <div className="warning-text">{alert.details.note}</div>
                  )}
                  {alert.details?.burst_size && (
                    <div>
                      <strong>Burst size:</strong> {alert.details.burst_size}{" "}
                      registrations ({alert.details.start_date} to{" "}
                      {alert.details.end_date})
                    </div>
                  )}
                  {alert.npi && (
                    <div className="mono small">NPI: {alert.npi}</div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {data.total > 50 && (
            <div className="pagination">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </button>
              <span>Page {page}</span>
              <button
                disabled={data.results.length < 50}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
