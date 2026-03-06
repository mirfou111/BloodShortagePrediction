// src/components/NetworkView.jsx
import { useEffect, useState } from "react"
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts"
import { api } from "../api/client"
import { Card, KPICard } from "./ui/Card"
import "leaflet/dist/leaflet.css"

// Couleurs selon taux de pénurie
function getPenurieColor(pct) {
  if (pct >= 30) return "#ef4444"   // rouge
  if (pct >= 15) return "#f59e0b"   // orange
  return "#22c55e"                   // vert
}

export function NetworkView() {
  const [summary, setSummary]     = useState(null)
  const [hospitals, setHospitals] = useState([])
  const [stocks, setStocks]       = useState([])
  const [loading, setLoading]     = useState(true)

  useEffect(() => {
    Promise.all([
      api.getNetworkSummary(),
      api.getHospitals(),
      api.getLatestStocks(),
    ]).then(([s, h, st]) => {
      setSummary(s.data)
      setHospitals(h.data)
      setStocks(st.data.stocks)
      setLoading(false)
    })
  }, [])

  // Calcul du taux de pénurie par hôpital (pour la carte)
  const hospitalPenuries = hospitals.map(h => {
    const hStocks = stocks.filter(s => s.hospital_id === h.id)
    const critiques = hStocks.filter(s => s.status === "CRITIQUE").length
    const pct = hStocks.length ? Math.round(critiques / hStocks.length * 100) : 0
    return { ...h, pct_penurie: pct, nb_critique: critiques }
  })

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-blood-500 text-xl animate-pulse">
        🩸 Chargement du réseau...
      </div>
    </div>
  )

  return (
    <div className="space-y-6">

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard
          title="Total poches"
          value={summary.total_units.toLocaleString()}
          subtitle="Toutes banques confondues"
          icon="🩸"
        />
        <KPICard
          title="Hôpitaux critiques"
          value={summary.critical_hospitals.filter(h => h.nb_critical >= 8).length}
          subtitle="Stock critique sur ≥8 produits"
          color="text-red-400"
          icon="🔴"
        />
        <KPICard
          title="Péremptions imminentes"
          value={summary.expiring_soon.reduce((a, b) => a + b.expiring, 0)}
          subtitle="Poches à utiliser en priorité"
          color="text-yellow-400"
          icon="⏰"
        />
        <KPICard
          title="Dernière mise à jour"
          value={summary.last_update}
          subtitle={`${summary.total_hospitals} hôpitaux suivis`}
          icon="📅"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Carte du Sénégal */}
        <Card>
          <h2 className="text-lg font-semibold mb-3 text-slate-200">
            🗺️ Carte du réseau
          </h2>
          <div className="h-80 rounded-lg overflow-hidden">
            <MapContainer
              center={[14.5, -14.5]}
              zoom={6}
              style={{ height: "100%", width: "100%" }}
            >
              <TileLayer
                url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                attribution="©OpenStreetMap ©CartoDB"
              />
              {hospitalPenuries.map(h => (
                <CircleMarker
                  key={h.id}
                  center={[h.latitude, h.longitude]}
                  radius={h.capacity_level === "grand" ? 14
                        : h.capacity_level === "moyen" ? 10 : 7}
                  fillColor={getPenurieColor(h.pct_penurie)}
                  color="#fff"
                  weight={1}
                  fillOpacity={0.85}
                >
                  <Popup>
                    <div className="text-slate-900">
                      <strong>{h.name}</strong><br/>
                      Région : {h.region}<br/>
                      Taux pénurie : <strong>{h.pct_penurie}%</strong><br/>
                      Produits critiques : {h.nb_critique}
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
          <div className="flex gap-4 mt-2 text-xs text-slate-400">
            <span>🔴 Critique (≥30%)</span>
            <span>🟡 Modéré (15-30%)</span>
            <span>🟢 OK (&lt;15%)</span>
          </div>
        </Card>

        {/* Stock par produit */}
        <Card>
          <h2 className="text-lg font-semibold mb-3 text-slate-200">
            📊 Stock & pénurie par produit
          </h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={summary.stock_by_product}>
              <XAxis dataKey="product_type" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip
                contentStyle={{ background: "#1e293b", border: "none" }}
                labelStyle={{ color: "#e2e8f0" }}
              />
              <Bar dataKey="total_units" name="Unités" radius={[4,4,0,0]}>
                {summary.stock_by_product.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={getPenurieColor(entry.pct_shortage)}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          {/* Tableau pénurie */}
          <div className="mt-4 space-y-2">
            {summary.stock_by_product.map(p => (
              <div key={p.product_type}
                   className="flex items-center justify-between text-sm">
                <span className="text-slate-300 font-medium w-12">
                  {p.product_type}
                </span>
                <div className="flex-1 mx-3 bg-slate-700 rounded-full h-2">
                  <div
                    className="h-2 rounded-full transition-all"
                    style={{
                      width: `${p.pct_shortage}%`,
                      background: getPenurieColor(p.pct_shortage)
                    }}
                  />
                </div>
                <span style={{ color: getPenurieColor(p.pct_shortage) }}
                      className="font-bold w-12 text-right">
                  {p.pct_shortage}%
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Hôpitaux critiques */}
      <Card>
        <h2 className="text-lg font-semibold mb-3 text-slate-200">
          🏥 Situation par hôpital
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-700">
                <th className="text-left py-2">Hôpital</th>
                <th className="text-left py-2">Région</th>
                <th className="text-left py-2">Capacité</th>
                <th className="text-right py-2">Produits critiques</th>
                <th className="text-right py-2">Taux pénurie</th>
              </tr>
            </thead>
            <tbody>
              {hospitalPenuries
                .sort((a, b) => b.pct_penurie - a.pct_penurie)
                .map(h => (
                <tr key={h.id}
                    className="border-b border-slate-700/50 hover:bg-slate-700/30">
                  <td className="py-2 font-medium text-slate-200">{h.name}</td>
                  <td className="py-2 text-slate-400">{h.region}</td>
                  <td className="py-2 text-slate-400 capitalize">{h.capacity_level}</td>
                  <td className="py-2 text-right">
                    <span className={h.nb_critique >= 8 ? "text-red-400 font-bold"
                                   : h.nb_critique >= 4 ? "text-yellow-400"
                                   : "text-green-400"}>
                      {h.nb_critique}
                    </span>
                  </td>
                  <td className="py-2 text-right">
                    <span style={{ color: getPenurieColor(h.pct_penurie) }}
                          className="font-bold">
                      {h.pct_penurie}%
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}