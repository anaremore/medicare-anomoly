import { useState, useEffect } from "react";
import { fetchApi } from "../hooks/useApi";

export default function InvestigationView({ npi, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchApi(`/anomalies/investigate/${npi}`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [npi]);

  if (loading) return <div className="loading">Building case file...</div>;
  if (error) return <div className="error">Error: {error}</div>;
  if (!data) return null;

  const { identity, billing_history, yoy_growth, hcpcs_detail, peer_comparison, red_flags, red_flag_count } = data;

  return (
    <div className="investigation">
      <button className="back-btn" onClick={onClose}>&larr; Back to anomalies</button>

      {/* Header */}
      <div className="inv-header">
        <div className="inv-title-row">
          <h2>{identity.name || identity.npi}</h2>
          {red_flag_count.critical > 0 && (
            <span className="inv-flag-count critical">{red_flag_count.critical} critical</span>
          )}
          {red_flag_count.high > 0 && (
            <span className="inv-flag-count high">{red_flag_count.high} high</span>
          )}
        </div>
        <div className="inv-meta">
          <span className="mono">NPI: {identity.npi}</span>
          <span>{identity.address}</span>
          <span>Registered: {identity.enumeration_date}</span>
          <span>{identity.taxonomy}</span>
          {identity.deactivation_date && (
            <span className="warning-text">DEACTIVATED: {identity.deactivation_date}</span>
          )}
        </div>
      </div>

      {/* Red Flags */}
      {red_flags.length > 0 && (
        <div className="inv-section inv-flags">
          <h3>Red Flags</h3>
          <div className="flag-list">
            {red_flags.map((f, i) => (
              <div key={i} className={`flag-item ${f.severity}`}>
                <span className={`flag-severity ${f.severity}`}>{f.severity}</span>
                <div>
                  <div className="flag-text">{f.flag}</div>
                  <div className="flag-detail">{f.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Billing + Peers side by side */}
      <div className="inv-row">
        {/* Billing History */}
        <div className="inv-section">
          <h3>Medicare Billing History</h3>
          {billing_history.length > 0 ? (
            <>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Year</th>
                    <th>Medicare Payment</th>
                    <th>Beneficiaries</th>
                    <th>Services</th>
                    <th>Codes</th>
                  </tr>
                </thead>
                <tbody>
                  {[...billing_history].reverse().map((b) => (
                    <tr key={b.year}>
                      <td>{b.year}</td>
                      <td className="money">${b.total_medicare_payment.toLocaleString(undefined, {maximumFractionDigits: 0})}</td>
                      <td>{b.total_beneficiaries?.toLocaleString()}</td>
                      <td>{b.total_services?.toLocaleString()}</td>
                      <td>{b.total_hcpcs_codes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {yoy_growth && (
                <div className={`inv-growth ${Math.abs(yoy_growth.growth_pct) > 500 ? 'extreme' : yoy_growth.growth_pct > 100 ? 'high' : ''}`}>
                  {yoy_growth.growth_pct > 0 ? '+' : ''}{yoy_growth.growth_pct.toLocaleString()}% growth
                  <span className="inv-growth-detail">
                    {yoy_growth.from_year}: ${yoy_growth.from_amount.toLocaleString(undefined, {maximumFractionDigits: 0})}
                    {' '}&rarr;{' '}
                    {yoy_growth.to_year}: ${yoy_growth.to_amount.toLocaleString(undefined, {maximumFractionDigits: 0})}
                  </span>
                </div>
              )}
            </>
          ) : (
            <p className="muted">No CMS billing data found.</p>
          )}
        </div>

        {/* Peer Comparison */}
        {peer_comparison && (
          <div className="inv-section">
            <h3>Peer Comparison</h3>
            <div className="peer-stats">
              <div className="peer-stat">
                <div className="peer-value">{peer_comparison.state_ratio}x</div>
                <div className="peer-label">vs state median</div>
                <div className="peer-detail">
                  ${peer_comparison.state_median?.toLocaleString(undefined, {maximumFractionDigits: 0})} median
                </div>
              </div>
              <div className="peer-stat">
                <div className="peer-value">{peer_comparison.state_percentile}th</div>
                <div className="peer-label">percentile</div>
                <div className="peer-detail">
                  of {peer_comparison.state_peer_count?.toLocaleString()} TX suppliers
                </div>
              </div>
              {peer_comparison.zip_ratio && (
                <div className="peer-stat">
                  <div className="peer-value">{peer_comparison.zip_ratio}x</div>
                  <div className="peer-label">vs ZIP median</div>
                  <div className="peer-detail">
                    {peer_comparison.zip_peer_count} peers in ZIP
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* HCPCS Detail */}
      {hcpcs_detail.length > 0 && (
        <div className="inv-section">
          <h3>HCPCS Code Breakdown</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Description</th>
                <th>Category</th>
                <th>Beneficiaries</th>
                <th>Services</th>
                <th>Avg Charge</th>
                <th>Avg Payment</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {hcpcs_detail.map((h, i) => (
                <tr key={i} className={h.fraud_risk_code ? 'fraud-code-row' : ''}>
                  <td className="mono">{h.code}</td>
                  <td className="small">{h.description?.slice(0, 70)}</td>
                  <td className="small">{h.category}</td>
                  <td>{h.beneficiaries?.toLocaleString()}</td>
                  <td>{h.services?.toLocaleString()}</td>
                  <td className="money">${h.avg_charge?.toLocaleString()}</td>
                  <td className="money">${h.avg_payment?.toLocaleString()}</td>
                  <td>
                    {h.fraud_risk_code && (
                      <span className="fraud-code-badge">FRAUD-RISK</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
