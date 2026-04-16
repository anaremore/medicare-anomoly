import { useState } from "react";
import { useApi } from "../hooks/useApi";
import RiskBadge from "./RiskBadge";

export default function ProviderList() {
  const [search, setSearch] = useState("");
  const [zip, setZip] = useState("");
  const [minRisk, setMinRisk] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("risk");

  const { data, loading, error } = useApi("/providers", {
    search: search || undefined,
    zip: zip || undefined,
    min_risk: minRisk || undefined,
    sort,
    page,
    per_page: 50,
  });

  return (
    <div className="provider-list">
      <div className="filters">
        <input
          type="text"
          placeholder="Search by name or NPI..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="filter-input"
        />
        <input
          type="text"
          placeholder="ZIP code"
          value={zip}
          onChange={(e) => {
            setZip(e.target.value);
            setPage(1);
          }}
          className="filter-input small"
        />
        <input
          type="number"
          placeholder="Min risk score"
          value={minRisk}
          onChange={(e) => {
            setMinRisk(e.target.value);
            setPage(1);
          }}
          className="filter-input small"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="filter-input small"
        >
          <option value="risk">Sort: Risk Score</option>
          <option value="name">Sort: Name</option>
          <option value="date">Sort: Newest First</option>
        </select>
      </div>

      {loading && <div className="loading">Loading...</div>}
      {error && <div className="error">Error: {error}</div>}

      {data && (
        <>
          <div className="result-count">
            {data.total} providers found (page {data.page})
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>NPI</th>
                <th>Name</th>
                <th>Type</th>
                <th>Address</th>
                <th>ZIP</th>
                <th>Enumerated</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((p) => (
                <tr key={p.npi}>
                  <td className="mono">{p.npi}</td>
                  <td>{p.name}</td>
                  <td className="small">{p.taxonomy_desc}</td>
                  <td className="small">{p.address}</td>
                  <td>{(p.practice_zip || "").slice(0, 5)}</td>
                  <td>{p.enumeration_date}</td>
                  <td>
                    <RiskBadge score={p.composite_score} />
                  </td>
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
              disabled={page >= Math.ceil(data.total / data.per_page)}
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
