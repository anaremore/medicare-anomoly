import { useState, useEffect } from "react";
import { fetchApi } from "../hooks/useApi";
import RiskBadge from "./RiskBadge";

export default function ProviderDetail({ npi, onClose }) {
  const [provider, setProvider] = useState(null);
  const [billing, setBilling] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchApi(`/providers/${npi}`),
      fetchApi(`/providers/${npi}/billing`),
    ])
      .then(([provData, billData]) => {
        setProvider(provData);
        setBilling(billData);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [npi]);

  if (loading) return <div className="loading">Loading provider detail...</div>;
  if (!provider) return <div className="error">Provider not found</div>;

  const summaries = billing?.yearly_summaries || [];
  const hcpcsDetail = billing?.hcpcs_detail || [];
  const signals = provider.signals || {};

  return (
    <div className="provider-detail">
      <button className="back-btn" onClick={onClose}>
        &larr; Back
      </button>

      <div className="detail-header">
        <h2>{provider.name}</h2>
        <div className="detail-meta">
          <span className="mono">NPI: {provider.npi}</span>
          <span>{provider.taxonomy_desc}</span>
          <span>{provider.address}</span>
          <span>Enumerated: {provider.enumeration_date}</span>
          {provider.deactivation_date && (
            <span className="warning-text">
              Deactivated: {provider.deactivation_date}
            </span>
          )}
        </div>
        <div className="risk-summary">
          <RiskBadge score={provider.composite_score} />
          {provider.exclusion && (
            <span className="exclusion-badge">
              OIG EXCLUDED ({provider.exclusion.exclusion_type})
            </span>
          )}
        </div>
      </div>

      {/* Risk Score Breakdown */}
      <div className="detail-section">
        <h3>Risk Score Breakdown</h3>
        <div className="score-bars">
          <ScoreBar
            label="Address Clustering"
            score={provider.address_clustering_score}
          />
          <ScoreBar
            label="Entity Profile"
            score={provider.entity_profile_score}
          />
          <ScoreBar
            label="Network Association"
            score={provider.network_association_score}
          />
          <ScoreBar
            label="Geographic Risk"
            score={provider.geographic_risk_score}
          />
          <ScoreBar
            label="Billing Velocity"
            score={provider.billing_velocity_score}
          />
        </div>
      </div>

      {/* Billing Summary */}
      {summaries.length > 0 && (
        <div className="detail-section">
          <h3>Medicare Billing History</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Year</th>
                <th>Medicare Payment</th>
                <th>Submitted Charges</th>
                <th>Beneficiaries</th>
                <th>Claims</th>
                <th>Services</th>
                <th>HCPCS Codes</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.year}>
                  <td>{s.year}</td>
                  <td className="money">
                    ${s.total_medicare_payment.toLocaleString()}
                  </td>
                  <td className="money">
                    ${s.total_submitted_charges.toLocaleString()}
                  </td>
                  <td>{s.total_beneficiaries?.toLocaleString()}</td>
                  <td>{s.total_claims?.toLocaleString()}</td>
                  <td>{s.total_services.toLocaleString()}</td>
                  <td>{s.total_hcpcs_codes}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* YoY growth indicator */}
          {summaries.length >= 2 && (
            <div className="yoy-indicator">
              {(() => {
                const curr = summaries[0].total_medicare_payment;
                const prev = summaries[1].total_medicare_payment;
                if (prev === 0) return null;
                const growth = ((curr - prev) / prev) * 100;
                const isUp = growth > 0;
                return (
                  <span
                    className={`yoy ${growth > 100 ? "extreme" : isUp ? "up" : "down"}`}
                  >
                    {isUp ? "+" : ""}
                    {growth.toFixed(0)}% YoY
                    {growth > 300 && " — EXTREME GROWTH"}
                  </span>
                );
              })()}
            </div>
          )}
        </div>
      )}

      {/* HCPCS Detail */}
      {hcpcsDetail.length > 0 && (
        <div className="detail-section">
          <h3>
            Billing by HCPCS Code ({hcpcsDetail[0]?.data_year})
          </h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Description</th>
                <th>Category</th>
                <th>Benes</th>
                <th>Services</th>
                <th>Avg Charge</th>
                <th>Avg Payment</th>
              </tr>
            </thead>
            <tbody>
              {hcpcsDetail.map((b, i) => (
                <tr key={i}>
                  <td className="mono">{b.hcpcs_code}</td>
                  <td className="small">{b.hcpcs_description}</td>
                  <td className="small">{b.rbcs_category}</td>
                  <td>{b.total_beneficiaries}</td>
                  <td>{b.total_services}</td>
                  <td className="money">
                    ${b.avg_submitted_charge.toLocaleString()}
                  </td>
                  <td className="money">
                    ${b.avg_medicare_payment.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {summaries.length === 0 && (
        <div className="detail-section">
          <h3>Medicare Billing</h3>
          <p className="muted">
            No CMS billing data found for this provider. They may be too new,
            below the 10-claim privacy threshold, or bill under a different NPI.
          </p>
        </div>
      )}

      {/* Signal Details */}
      {signals.billing_velocity && signals.billing_velocity.has_billing_data && (
        <div className="detail-section">
          <h3>Billing Anomaly Signals</h3>
          <div className="signal-grid">
            {signals.billing_velocity.yoy_growth_rate != null && (
              <Signal
                label="YoY Growth"
                value={`${(signals.billing_velocity.yoy_growth_rate * 100).toFixed(0)}%`}
                warn={signals.billing_velocity.yoy_growth_rate > 1}
              />
            )}
            {signals.billing_velocity.peer_ratio != null && (
              <Signal
                label="vs ZIP Median"
                value={`${signals.billing_velocity.peer_ratio}x`}
                warn={signals.billing_velocity.peer_ratio > 3}
              />
            )}
            {signals.billing_velocity.high_risk_hcpcs_ratio != null && (
              <Signal
                label="High-Risk HCPCS"
                value={`${(signals.billing_velocity.high_risk_hcpcs_ratio * 100).toFixed(0)}%`}
                warn={signals.billing_velocity.high_risk_hcpcs_ratio > 0.5}
              />
            )}
            {signals.billing_velocity.services_per_beneficiary != null && (
              <Signal
                label="Svc/Beneficiary"
                value={signals.billing_velocity.services_per_beneficiary}
                warn={signals.billing_velocity.services_per_beneficiary > 10}
              />
            )}
            {signals.billing_velocity.unique_hcpcs_codes != null && (
              <Signal
                label="Unique Codes"
                value={signals.billing_velocity.unique_hcpcs_codes}
                warn={signals.billing_velocity.unique_hcpcs_codes <= 2}
              />
            )}
          </div>
        </div>
      )}

      {/* Colocated Providers */}
      {provider.colocated_providers?.length > 0 && (
        <div className="detail-section">
          <h3>
            Other Providers at Same Address ({provider.colocated_providers.length})
          </h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>NPI</th>
                <th>Name</th>
                <th>Type</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {provider.colocated_providers.slice(0, 20).map((p) => (
                <tr key={p.npi}>
                  <td className="mono">{p.npi}</td>
                  <td>{p.name}</td>
                  <td className="small">{p.taxonomy_desc}</td>
                  <td>
                    <RiskBadge score={p.composite_score} />
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

function ScoreBar({ label, score }) {
  const width = score != null ? Math.min(100, score) : 0;
  const color =
    width >= 70
      ? "var(--critical)"
      : width >= 50
        ? "var(--high)"
        : width >= 30
          ? "var(--medium)"
          : "var(--low)";

  return (
    <div className="score-bar-row">
      <span className="score-bar-label">{label}</span>
      <div className="score-bar-track">
        <div
          className="score-bar-fill"
          style={{ width: `${width}%`, background: color }}
        />
      </div>
      <span className="score-bar-value">{score ?? "N/A"}</span>
    </div>
  );
}

function Signal({ label, value, warn }) {
  return (
    <div className={`signal-card ${warn ? "warn" : ""}`}>
      <div className="signal-value">{value}</div>
      <div className="signal-label">{label}</div>
    </div>
  );
}
