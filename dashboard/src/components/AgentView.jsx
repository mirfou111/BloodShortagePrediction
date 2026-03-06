// src/components/AgentView.jsx
import { useState, useRef, useEffect } from "react"
import { api } from "../api/client"
import { Card } from "./ui/Card"

const SUGGESTIONS = [
  "Donne moi un résumé de la situation aujourd'hui",
  "Quels hôpitaux sont en situation critique ?",
  "Quelles pénuries sont prévues dans 3 jours ?",
  "Que suggères-tu pour éviter les pénuries critiques ?",
  "Y a-t-il des poches qui risquent de périmer ?",
]

function Message({ role, content }) {
  const isAgent = role === "assistant"
  return (
    <div className={`flex gap-3 ${isAgent ? "" : "flex-row-reverse"}`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center 
                       text-sm shrink-0 ${
        isAgent ? "bg-blood-600 text-white" : "bg-slate-600 text-white"
      }`}>
        {isAgent ? "🤖" : "👤"}
      </div>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
        isAgent
          ? "bg-slate-700 text-slate-200 rounded-tl-none"
          : "bg-blood-700 text-white rounded-tr-none"
      }`}>
        {/* Rendu markdown basique */}
        {content.split('\n').map((line, i) => (
          <p key={i} className={line.startsWith('##') ? "font-bold text-base mt-2"
                               : line.startsWith('**') ? "font-semibold"
                               : ""}>{
            line.replace(/\*\*(.*?)\*\*/g, '$1')
                .replace(/^##\s/, '')
                .replace(/^#\s/, '')
          }</p>
        ))}
      </div>
    </div>
  )
}

export function AgentView() {
  const [messages, setMessages] = useState([])
  const [input, setInput]       = useState("")
  const [loading, setLoading]   = useState(false)
  const bottomRef               = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  async function sendMessage(text) {
    const msg = text || input.trim()
    if (!msg || loading) return

    setInput("")
    setMessages(prev => [...prev, { role: "user", content: msg }])
    setLoading(true)

    try {
      const response = await api.chat(msg)
      setMessages(prev => [...prev, {
        role: "assistant",
        content: response.data.response
      }])
    } catch (e) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: "❌ Erreur de connexion à l'agent. Vérifiez que le serveur est actif."
      }])
    } finally {
      setLoading(false)
    }
  }

  async function resetConversation() {
    await api.resetConversation()
    setMessages([])
  }

  return (
    <div className="flex flex-col h-[calc(100vh-200px)] gap-4">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-200">
            🤖 Agent BloodFlow
          </h2>
          <p className="text-slate-400 text-sm">
            Assistant IA pour la gestion des banques de sang
          </p>
        </div>
        <button
          onClick={resetConversation}
          className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600
                     text-slate-300 rounded-lg transition-colors"
        >
          🔄 Nouvelle conversation
        </button>
      </div>

      {/* Zone messages */}
      <Card className="flex-1 overflow-y-auto space-y-4 min-h-0">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-6">
            <div className="text-6xl">🩸</div>
            <p className="text-slate-400 text-center">
              Bonjour ! Je suis BloodFlow, votre assistant IA.<br/>
              Posez-moi une question sur la situation du réseau sanguin.
            </p>
            <div className="grid grid-cols-1 gap-2 w-full max-w-lg">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(s)}
                  className="text-left px-4 py-2 bg-slate-700 hover:bg-slate-600
                             text-slate-300 text-sm rounded-lg transition-colors
                             border border-slate-600 hover:border-blood-500"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((m, i) => (
              <Message key={i} role={m.role} content={m.content} />
            ))}
            {loading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-blood-600
                                flex items-center justify-center">🤖</div>
                <div className="bg-slate-700 rounded-2xl rounded-tl-none
                                px-4 py-3 flex gap-1 items-center">
                  <span className="w-2 h-2 bg-slate-400 rounded-full
                                   animate-bounce [animation-delay:0ms]"/>
                  <span className="w-2 h-2 bg-slate-400 rounded-full
                                   animate-bounce [animation-delay:150ms]"/>
                  <span className="w-2 h-2 bg-slate-400 rounded-full
                                   animate-bounce [animation-delay:300ms]"/>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </>
        )}
      </Card>

      {/* Input */}
      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && sendMessage()}
          placeholder="Posez votre question à l'agent..."
          disabled={loading}
          className="flex-1 bg-slate-800 border border-slate-600 rounded-xl
                     px-4 py-3 text-slate-200 placeholder-slate-500
                     focus:outline-none focus:border-blood-500 transition-colors
                     disabled:opacity-50"
        />
        <button
          onClick={() => sendMessage()}
          disabled={loading || !input.trim()}
          className="px-5 py-3 bg-blood-600 hover:bg-blood-500 disabled:opacity-50
                     text-white rounded-xl font-medium transition-colors"
        >
          Envoyer
        </button>
      </div>
    </div>
  )
}