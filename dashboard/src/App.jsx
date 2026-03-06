// src/App.jsx
import { useState } from "react"
import { NetworkView } from "./components/NetworkView"
import { AlertsView }  from "./components/AlertsView"
import { AgentView }   from "./components/AgentView"

const TABS = [
  { id: "network", label: "🗺️ Réseau",  component: NetworkView },
  { id: "alerts",  label: "⚠️ Alertes", component: AlertsView  },
  { id: "agent",   label: "🤖 Agent",   component: AgentView   },
]

export default function App() {
  const [activeTab, setActiveTab] = useState("network")
  const ActiveComponent = TABS.find(t => t.id === activeTab).component

  return (
    <div className="min-h-screen bg-slate-900">

      {/* Header */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🩸</span>
            <div>
              <h1 className="text-xl font-bold text-white">BloodFlow Sénégal</h1>
              <p className="text-slate-400 text-xs">
                Système de prédiction de pénurie de sang
              </p>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex gap-1">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? "bg-blood-600 text-white"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* Contenu */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        <ActiveComponent />
      </main>
    </div>
  )
}