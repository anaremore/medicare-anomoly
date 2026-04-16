import { useState, useEffect } from "react";
import { useApi, fetchApi } from "../hooks/useApi";
import RiskBadge from "./RiskBadge";

export default function AddressDrilldown({ selectedAddressId, onSelectAddress }) {
  const [addressDetail, setAddressDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const { data: addresses, loading } = useApi("/addresses", {
    min_providers: 3,
    per_page: 100,
  });

  useEffect(() => {
    if (selectedAddressId) {
      setDetailLoading(true);
      fetchApi(`/addresses/${selectedAddressId}`)
        .then(setAddressDetail)
        .catch(console.error)
        .finally(() => setDetailLoading(false));
    }
  }, [selectedAddressId]);

  if (selectedAddressId && addressDetail) {
    return (
      <div className="address-drilldown">
        <button className="back-btn" onClick={() => onSelectAddress(null)}>
          &larr; Back to all addresses
        </button>

        <div className="address-header">
          <h2>{addressDetail.normalized_address}</h2>
          <p>
            {addressDetail.city}, {addressDetail.state} {addressDetail.zip}
          </p>
          <p className="provider-count">
            {addressDetail.provider_count} providers at this address
          </p>
        </div>

        {detailLoading ? (
          <div className="loading">Loading...</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>NPI</th>
                <th>Name</th>
                <th>Type</th>
                <th>Enumerated</th>
                <th>Deactivated</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {(addressDetail.providers || []).map((p) => (
                <tr
                  key={p.npi}
                  className={p.deactivation_date ? "deactivated" : ""}
                >
                  <td className="mono">{p.npi}</td>
                  <td>{p.name}</td>
                  <td className="small">{p.taxonomy_desc}</td>
                  <td>{p.enumeration_date}</td>
                  <td>{p.deactivation_date || "—"}</td>
                  <td>
                    <RiskBadge score={p.composite_score} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  return (
    <div className="address-list">
      <h2>Address Clusters</h2>
      <p className="muted">
        Addresses with 3+ DME/HHA/Hospice providers. Click to drill down.
      </p>

      {loading && <div className="loading">Loading...</div>}

      {addresses && (
        <table className="data-table clickable">
          <thead>
            <tr>
              <th>Address</th>
              <th>City</th>
              <th>ZIP</th>
              <th>Total Providers</th>
              <th>Target Providers</th>
            </tr>
          </thead>
          <tbody>
            {addresses.results.map((a) => (
              <tr
                key={a.address_id}
                onClick={() => onSelectAddress(a.address_id)}
              >
                <td>{a.normalized_address}</td>
                <td>{a.city}</td>
                <td>{a.zip}</td>
                <td>{a.total_providers}</td>
                <td>{a.target_providers}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
