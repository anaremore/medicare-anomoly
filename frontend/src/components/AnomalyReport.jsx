import { useState, useEffect } from "react";
import { useApi, fetchApi } from "../hooks/useApi";

const ANOMALY_TYPES = [
  {
    id: "code-concentration",
    label: "Code Concentration",
    desc: "High billing from very few HCPCS codes",
    icon: "!",
  },
  {
    id: "billing-spikes",
    label: "Billing Spikes",
    desc: "Extreme year-over-year growth",
    icon: "^",
  },
  {
    id: "volume-outliers",
    label: "Volume Outliers",
    desc: "Abnormal services-per-beneficiary",
    icon: "#",
  },
  {
    id: "high-risk-codes",
    label: "High-Risk Codes",
    desc: "Revenue from fraud-prone HCPCS",
    icon: "*",
  },
];

export default function AnomalyReport({ onProviderClick }) {
  const [activeType, setActiveType] = useState("code-concentration");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const { data: summary } = useApi("/anomalies/summary");

  useEffect(() => {
    setLoading(true);
    fetchApi(`/anomalies/${activeType}`)
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [activeType]);

  return (
    <div className="anomaly-report">
      <h2>Billing Anomaly Report</h2>
      <p className="muted">
        Automated detection of suspicious Medicare DMEPOS billing patterns across
        Texas. All data from CMS public utilization files.
      </p>

      {/* Summary Cards */}
      {summary && (
        <div className="anomaly-summary-grid">
          <div className="anomaly-summary-card">
            <div className="stat-value">
              {summary.total_suppliers?.toLocaleString()}
            </div>
            <div className="stat-label">TX DMEPOS Suppliers</div>
          </div>
          <div className="anomaly-summary-card">
            <div className="stat-value">
              ${(summary.total_medicare_payment / 1e9).toFixed(1)}B
            </div>
            <div className="stat-label">
              Total Medicare Payments ({summary.latest_year})
            </div>
          </div>
          {summary.anomaly_counts &&
            Object.entries(summary.anomaly_counts).map(([key, val]) => (
              <div key={key} className="anomaly-summary-card highlight">
                <div className="stat-value">{val}</div>
                <div className="stat-label">
                  {key.replace(/_/g, " ")}
                </div>
              </div>
            ))}
        </div>
      )}

      {/* Type Tabs */}
      <div className="anomaly-tabs">
        {ANOMALY_TYPES.map((t) => (
          <button
            key={t.id}
            className={`anomaly-tab ${activeType === t.id ? "active" : ""}`}
            onClick={() => setActiveType(t.id)}
          >
            <span className="anomaly-tab-icon">{t.icon}</span>
            <div>
              <div className="anomaly-tab-label">{t.label}</div>
              <div className="anomaly-tab-desc">{t.desc}</div>
            </div>
          </button>
        ))}
      </div>

      {/* Results */}
      {loading && <div className="loading">Analyzing billing patterns...</div>}

      {data && !loading && (
        <div className="anomaly-results">
          <div className="result-count">
            {data.total} anomalies detected — {data.description}
          </div>

          {activeType === "code-concentration" && (
            <CodeConcentrationTable
              results={data.results}
              onProviderClick={onProviderClick}
            />
          )}
          {activeType === "billing-spikes" && (
            <BillingSpikesTable
              results={data.results}
              onProviderClick={onProviderClick}
            />
          )}
          {activeType === "volume-outliers" && (
            <VolumeOutliersTable
              results={data.results}
              onProviderClick={onProviderClick}
            />
          )}
          {activeType === "high-risk-codes" && (
            <HighRiskCodesTable
              results={data.results}
              onProviderClick={onProviderClick}
            />
          )}
        </div>
      )}
    </div>
  );
}

function CodeConcentrationTable({ results, onProviderClick }) {
  const [expanded, setExpanded] = useState(null);

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>NPI</th>
          <th>Name</th>
          <th>Medicare Payment</th>
          <th>Beneficiaries</th>
          <th>HCPCS Codes</th>
          <th>Svc/Bene</th>
          <th>$/Bene</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <>
            <tr
              key={r.npi}
              className="clickable-row"
              onClick={() =>
                setExpanded(expanded === r.npi ? null : r.npi)
              }
            >
              <td className="mono">{r.npi}</td>
              <td>{r.name || <NpiLookup npi={r.npi} />}</td>
              <td className="money">
                ${r.total_medicare_payment.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </td>
              <td>{r.total_beneficiaries?.toLocaleString()}</td>
              <td>
                <span className="code-count-badge">
                  {r.total_hcpcs_codes}
                </span>
              </td>
              <td className="mono">{r.services_per_beneficiary}</td>
              <td className="money">
                ${r.payment_per_beneficiary?.toLocaleString()}
              </td>
            </tr>
            {expanded === r.npi && r.hcpcs_detail?.length > 0 && (
              <tr key={`${r.npi}-detail`} className="detail-row">
                <td colSpan={7}>
                  <div className="hcpcs-expand">
                    <strong>HCPCS Codes Billed:</strong>
                    {r.hcpcs_detail.map((h) => (
                      <div key={h.code} className="hcpcs-line">
                        <span className="mono">{h.code}</span>
                        <span className="small">{h.description?.slice(0, 80)}</span>
                        <span className="mono">
                          {h.services.toLocaleString()} svcs
                        </span>
                        <span className="mono">
                          avg ${h.avg_payment.toLocaleString()}
                        </span>
                      </div>
                    ))}
                  </div>
                </td>
              </tr>
            )}
          </>
        ))}
      </tbody>
    </table>
  );
}

function BillingSpikesTable({ results, onProviderClick }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>NPI</th>
          <th>Name</th>
          <th>Prior Year</th>
          <th>Current Year</th>
          <th>Growth</th>
          <th>Codes</th>
          <th>Beneficiaries</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <tr
            key={r.npi}
            className="clickable-row"
            onClick={() => onProviderClick?.(r.npi)}
          >
            <td className="mono">{r.npi}</td>
            <td>{r.name || <NpiLookup npi={r.npi} />}</td>
            <td className="money">
              ${r.prev_payment.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
              <span className="small"> ({r.prev_year})</span>
            </td>
            <td className="money">
              ${r.curr_payment.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
              <span className="small"> ({r.curr_year})</span>
            </td>
            <td>
              <span
                className={`growth-badge ${r.growth_pct > 500 ? "extreme" : "high"}`}
              >
                +{r.growth_pct.toLocaleString()}%
              </span>
            </td>
            <td>{r.total_hcpcs_codes}</td>
            <td>{r.total_beneficiaries?.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function VolumeOutliersTable({ results, onProviderClick }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>NPI</th>
          <th>Name</th>
          <th>Medicare Payment</th>
          <th>Beneficiaries</th>
          <th>Services</th>
          <th>Svc/Bene</th>
          <th>$/Bene</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <tr
            key={r.npi}
            className="clickable-row"
            onClick={() => onProviderClick?.(r.npi)}
          >
            <td className="mono">{r.npi}</td>
            <td>{r.name || <NpiLookup npi={r.npi} />}</td>
            <td className="money">
              ${r.total_medicare_payment.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
            </td>
            <td>{r.total_beneficiaries?.toLocaleString()}</td>
            <td>{r.total_services?.toLocaleString()}</td>
            <td>
              <span
                className={`volume-badge ${r.services_per_beneficiary > 500 ? "extreme" : "high"}`}
              >
                {r.services_per_beneficiary.toLocaleString()}
              </span>
            </td>
            <td className="money">
              ${r.payment_per_beneficiary?.toLocaleString()}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HighRiskCodesTable({ results, onProviderClick }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>NPI</th>
          <th>Name</th>
          <th>Total Revenue</th>
          <th>High-Risk Revenue</th>
          <th>Risk Ratio</th>
          <th>Codes</th>
          <th>Beneficiaries</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <tr
            key={r.npi}
            className="clickable-row"
            onClick={() => onProviderClick?.(r.npi)}
          >
            <td className="mono">{r.npi}</td>
            <td>{r.name || <NpiLookup npi={r.npi} />}</td>
            <td className="money">
              ${r.total_revenue.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
            </td>
            <td className="money warning-text">
              ${r.high_risk_revenue.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
            </td>
            <td>
              <span className="risk-ratio-badge">
                {(r.risk_ratio * 100).toFixed(0)}%
              </span>
            </td>
            <td>{r.total_hcpcs_codes}</td>
            <td>{r.total_beneficiaries?.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NpiLookup({ npi }) {
  const [name, setName] = useState(null);

  useEffect(() => {
    fetch(
      `https://npiregistry.cms.hhs.gov/api/?version=2.1&number=${npi}`
    )
      .then((r) => r.json())
      .then((d) => {
        const r = d.results?.[0];
        if (r) {
          setName(
            r.basic?.organization_name ||
              `${r.basic?.last_name}, ${r.basic?.first_name}`
          );
        }
      })
      .catch(() => {});
  }, [npi]);

  return <span className="muted">{name || npi}</span>;
}
