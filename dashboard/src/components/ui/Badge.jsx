// src/components/ui/Badge.jsx
const COLORS = {
  critique: "bg-red-900 text-red-300 border border-red-700",
  modere:   "bg-yellow-900 text-yellow-300 border border-yellow-700",
  faible:   "bg-green-900 text-green-300 border border-green-700",
  OK:       "bg-green-900 text-green-300 border border-green-700",
  FAIBLE:   "bg-yellow-900 text-yellow-300 border border-yellow-700",
  CRITIQUE: "bg-red-900 text-red-300 border border-red-700",
}

export function Badge({ label }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium 
                      ${COLORS[label] || "bg-slate-700 text-slate-300"}`}>
      {label}
    </span>
  )
}