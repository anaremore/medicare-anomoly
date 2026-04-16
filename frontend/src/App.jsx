import { useState } from "react";
import Dashboard from "./components/Dashboard";
import MapView from "./components/Map";
import ProviderList from "./components/ProviderList";
import AddressDrilldown from "./components/AddressDrilldown";
import AlertFeed from "./components/AlertFeed";

const TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "map", label: "Map" },
  { id: "providers", label: "Providers" },
  { id: "addresses", label: "Address Clusters" },
  { id: "alerts", label: "Alerts" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [selectedAddress, setSelectedAddress] = useState(null);
  const [selectedNpi, setSelectedNpi] = useState(null);

  const handleAddressClick = (addressId) => {
    setSelectedAddress(addressId);
    setActiveTab("addresses");
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Sentinel</h1>
        <span className="subtitle">Medicare Anomaly Detection</span>
        <nav className="tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`tab ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => {
                setActiveTab(tab.id);
                if (tab.id !== "addresses") setSelectedAddress(null);
              }}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="app-main">
        {activeTab === "dashboard" && (
          <Dashboard onAddressClick={handleAddressClick} />
        )}
        {activeTab === "map" && (
          <MapView onAddressClick={handleAddressClick} />
        )}
        {activeTab === "providers" && <ProviderList />}
        {activeTab === "addresses" && (
          <AddressDrilldown
            selectedAddressId={selectedAddress}
            onSelectAddress={setSelectedAddress}
          />
        )}
        {activeTab === "alerts" && <AlertFeed />}
      </main>
      <footer className="app-footer">
        <p>
          All data from public federal registries (NPPES, OIG LEIE). Anomaly
          signals are not accusations of fraud.
        </p>
      </footer>
    </div>
  );
}
