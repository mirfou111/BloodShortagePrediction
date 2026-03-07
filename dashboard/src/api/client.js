// src/api/client.js

/**
 * Client HTTP centralisé.
 * Toutes les requêtes vers FastAPI passent par ici.
 * Avantage : on change l'URL de base en un seul endroit.
 */

import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

// Intercepteur : log des erreurs en console
apiClient.interceptors.response.use(
  response => response,
  error => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export const api = {
  // Réseau
  getNetworkSummary:      () => apiClient.get('/api/network/summary'),
  getHospitals:           () => apiClient.get('/api/hospitals'),

  // Stocks
  getLatestStocks:        (params) => apiClient.get('/api/stocks/latest', { params }),
  getStockHistory:        (hospitalId, bloodType, productType, days) =>
    apiClient.get(`/api/stocks/history/${hospitalId}`, {
      params: { blood_type: bloodType, product_type: productType, days }
    }),

  // Prédictions
  getPredictions:         (severity) => apiClient.get('/api/predictions',
    { params: severity ? { severity } : {} }),

  // Transferts
  getTransferSuggestions: () => apiClient.get('/api/transfers/suggestions'),
  getTransferHistory:     () => apiClient.get('/api/transfers/history'),

  // Agent
  chat:                   (message, reset = false) =>
    apiClient.post('/api/agent/chat', { message, reset_conversation: reset }),
  resetConversation:      () => apiClient.delete('/api/agent/conversation'),
}