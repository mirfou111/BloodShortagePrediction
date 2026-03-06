// src/components/AlertsView.jsx
import { useEffect, useState } from "react"
import { api } from "../api/client"
import { Card } from "./ui/Card"
import { Badge } from "./ui/Badge"

export function AlertsView() {
  const [predictions, setPredictions] = useState(null)
  const [transfers, setTransfers]     = useState(null)
  const [loading, setLoading]         = useState(true)
  const [activeTab, setActiveTab]     = useState("predictions")

  useEffect(() => {
    Promise.all([
      api.getPredictions(),
      api.getTransferSuggestions(),
    ]).then(([p, t]) => {
      setPredictions(p.data)
      setTransfers(t.data)
      setLoading(false)
    })
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-blood-500 animate-pulse">⚠️ Analyse en cours...</div>
    </div>
  )

  return (
    <div className="space-y-6">

      {/* KPIs */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-red-950 border border-red-800 rounded-xl p-4 text-center">
          <div className="text-4xl font-bold text-red-400">
            {predictions.critique}
          </div>
          <div className="text-red-300 text-sm mt-1">🔴 Pénuries critiques J+3</div>
        </div>
        <div className="bg-yellow-950 border border-yellow-800 rounded-xl p-4 text-center">
          <div className="text-4xl font-bold text-yellow-400">
            {predictions.modere}
          </div>
          <div className="text-yellow-300 text-sm mt-1">🟡 Risques modérés</div>
        </div>
        <div className="bg-blue-950 border border-blue-800 rounded-xl p-4 text-center">
          <div className="text-4xl font-bold text-blue-400">
            {transfers.total}
          </div>
          <div className="text-blue-300 text-sm mt-1">🔄 Transferts suggérés</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-700">
        {["predictions", "transfers"].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors
              ${activeTab === tab
                ? "bg-slate-800 text-blood-400 border-b-2 border-blood-500"
                : "text-slate-400 hover:text-slate-200"}`}
          >
            {tab === "predictions" ? "⚠️ Prédictions" : "🔄 Transferts"}
          </button>
        ))}
      </div>

      {/* Prédictions */}
      {activeTab === "predictions" && (
        <Card>
          <h2 className="text-lg font-semibold mb-4 text-slate-200">
            Pénuries prédites dans 3 jours
          </h2>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {predictions.predictions.map((p, i) => (
              <div key={i}
                   className="flex items-center justify-between p-3
                              bg-slate-700/50 rounded-lg hover:bg-slate-700">
                <div className="flex items-center gap-3">
                  <Badge label={p.severity} />
                  <div>
                    <div className="text-slate-200 font-medium text-sm">
                      {p.hospital}
                    </div>
                    <div className="text-slate-400 text-xs">
                      {p.blood_type} / {p.product_type} —
                      Stock : {p.current_stock} (seuil : {p.minimum_threshold})
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-bold text-lg ${
                    p.shortage_probability > 0.85 ? "text-red-400"
                    : p.shortage_probability > 0.65 ? "text-yellow-400"
                    : "text-green-400"
                  }`}>
                    {Math.round(p.shortage_probability * 100)}%
                  </div>
                  <div className="text-slate-500 text-xs">probabilité</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Transferts */}
      {activeTab === "transfers" && (
        <Card>
          <h2 className="text-lg font-semibold mb-4 text-slate-200">
            Suggestions de transfert
          </h2>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {transfers.suggestions.map((t, i) => (
              <div key={i}
                   className="p-3 bg-slate-700/50 rounded-lg hover:bg-slate-700">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <Badge label={t.urgency} />
                    <span className="text-slate-300 text-sm font-medium">
                      {t.blood_type} / {t.product_type}
                    </span>
                    <span className="text-blood-400 font-bold">
                      {t.quantity} unités
                    </span>
                  </div>
                  <span className="text-slate-400 text-xs">
                    {t.distance_km} km
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <span className="text-green-400">{t.from_hospital}</span>
                  <span>→</span>
                  <span className="text-red-400">{t.to_hospital}</span>
                  <span className="ml-auto">
                    P(pénurie) = {Math.round(t.shortage_proba * 100)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}