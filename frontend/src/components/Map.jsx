import { useEffect, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { fetchApi } from "../hooks/useApi";

const HOUSTON_CENTER = [29.76, -95.37];

export default function MapView({ onAddressClick }) {
  const [clusters, setClusters] = useState([]);
  const [heatmap, setHeatmap] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchApi("/map/clusters", { min_providers: 3 }),
      fetchApi("/map/heatmap"),
    ])
      .then(([clusterData, heatData]) => {
        setClusters(clusterData.features || []);
        setHeatmap(heatData.data || []);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const getColor = (count) => {
    if (count >= 15) return "#dc2626";
    if (count >= 10) return "#ea580c";
    if (count >= 5) return "#d97706";
    return "#2563eb";
  };

  const getRadius = (count) => {
    return Math.min(30, 5 + Math.sqrt(count) * 4);
  };

  if (loading) return <div className="loading">Loading map data...</div>;

  return (
    <div className="map-container">
      <div className="map-legend">
        <h4>Address Clusters</h4>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: "#dc2626" }} />
          15+ providers
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: "#ea580c" }} />
          10-14 providers
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: "#d97706" }} />
          5-9 providers
        </div>
        <div className="legend-item">
          <span className="legend-dot" style={{ background: "#2563eb" }} />
          3-4 providers
        </div>
      </div>

      <MapContainer
        center={HOUSTON_CENTER}
        zoom={11}
        style={{ height: "calc(100vh - 180px)", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {clusters.map((feature, i) => {
          const { coordinates } = feature.geometry;
          const props = feature.properties;
          return (
            <CircleMarker
              key={i}
              center={[coordinates[1], coordinates[0]]}
              radius={getRadius(props.provider_count)}
              fillColor={getColor(props.provider_count)}
              color="#1e293b"
              weight={1}
              opacity={0.8}
              fillOpacity={0.6}
            >
              <Popup>
                <div className="popup-content">
                  <strong>{props.address}</strong>
                  <br />
                  Providers: {props.provider_count}
                  <br />
                  Avg Risk: {props.avg_risk}
                  <br />
                  <button
                    className="popup-link"
                    onClick={() => onAddressClick(props.address_id)}
                  >
                    View Details
                  </button>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
