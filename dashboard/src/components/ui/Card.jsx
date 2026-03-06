// src/components/ui/Card.jsx
export function Card({ children, className = "" }) {
  return (
    <div className={`bg-slate-800 border border-slate-700 
                     rounded-xl p-4 ${className}`}>
      {children}
    </div>
  )
}

export function KPICard({ title, value, subtitle, color = "text-white", icon }) {
  return (
    <Card className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-slate-400 text-sm">{title}</span>
        {icon && <span className="text-2xl">{icon}</span>}
      </div>
      <span className={`text-3xl font-bold ${color}`}>{value}</span>
      {subtitle && <span className="text-slate-500 text-xs">{subtitle}</span>}
    </Card>
  )
}