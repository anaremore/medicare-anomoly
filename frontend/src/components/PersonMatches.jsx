import { useState } from "react";
import { useApi } from "../hooks/useApi";

export default function PersonMatches() {
  const [minConfidence, setMinConfidence] = useState(50);
  const [page, setPage] = useState(1);

  const { data: summary } = useApi("/matches/summary");
  const { data, loading, error } = useApi("/matches", {
    min_confidence: minConfidence,
    page,
    per_page: 50,
  });

  return (
    <div className="person-matches">
      <h2>Person / Entity Correlation</h2>
      <p className="muted">
        Fuzzy name matching between active providers and OIG-excluded
        individuals/entities. Each match has a confidence score based on name
        similarity, geographic proximity, and specialty overlap.
      </p>

      {summary && (
        <div className="anomaly-summary-grid">
          <div className="anomaly-summary-card">
            <div className="stat-value">{summary.total}</div>
            <div className="stat-label">Total Matches</div>
          </div>
          <div className="anomaly-summary-card highlight">
            <div className="stat-value">{summary.high_confidence}</div>
            <div className="stat-label">High Confidence</div>
          </div>
          <div className="anomaly-summary-card">
            <div className="stat-value">{summary.medium_confidence}</div>
            <div className="stat-label">Medium Confidence</div>
          </div>
          <div className="anomaly-summary-card">
            <div className="stat-value">{summary.unreviewed}</div>
            <div className="stat-label">Unreviewed</div>
          </div>
        </div>
      )}

      <div className="filters">
        <label className="filter-label">
          Min Confidence:
          <select
            value={minConfidence}
            onChange={(e) => {
              setMinConfidence(Number(e.target.value));
              setPage(1);
            }}
            className="filter-input small"
          >
            <option value={80}>High (80+)</option>
            <option value={50}>Medium+ (50+)</option>
            <option value={30}>All (30+)</option>
          </select>
        </label>
      </div>

      {loading && <div className="loading">Loading matches...</div>}
      {error && <div className="error">Error: {error}</div>}

      {data && (
        <>
          <div className="result-count">
            {data.total} matches at confidence >= {minConfidence}
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Confidence</th>
                <th>Provider</th>
                <th>NPI</th>
                <th>Matched Against</th>
                <th>Source</th>
                <th>Location</th>
                <th>Specialty</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((m) => (
                <tr key={m.id}>
                  <td>
                    <span
                      className={`confidence-badge ${m.confidence_level.toLowerCase()}`}
                    >
                      {m.confidence_level} ({m.confidence})
                    </span>
                  </td>
                  <td>{m.provider_name}</td>
                  <td className="mono">{m.provider_npi}</td>
                  <td className="match-name">{m.matched_name}</td>
                  <td>
                    <span className="source-badge">{m.matched_source}</span>
                  </td>
                  <td className="small">
                    {m.matched_city}, {m.matched_state}
                  </td>
                  <td className="small">{m.matched_specialty}</td>
                  <td className="small">{m.match_type}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="pagination">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <span>
              Page {data.page} of {Math.ceil(data.total / data.per_page)}
            </span>
            <button
              disabled={data.results.length < 50}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
