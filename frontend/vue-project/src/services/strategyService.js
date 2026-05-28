import axios from 'axios'

const API_BASE = '/api/v2/strategy'

export default {
  async getStrategyOutputs(params = {}) {
    const response = await axios.get(`${API_BASE}/outputs`, { params })
    return response.data
  },

  async getLatestSignal(tsCode) {
    const response = await axios.get(`${API_BASE}/outputs/latest`, {
      params: { ts_code: tsCode }
    })
    return response.data
  },

  async createStrategyOutput(data) {
    const response = await axios.post(`${API_BASE}/outputs`, data)
    return response.data
  },

  async deleteStrategyOutput(outputId) {
    const response = await axios.delete(`${API_BASE}/outputs/${outputId}`)
    return response.data
  },

  async getTemplates(params = {}) {
    const response = await axios.get(`${API_BASE}/templates`, { params })
    return response.data
  },

  async getTemplate(templateId) {
    const response = await axios.get(`${API_BASE}/templates/${templateId}`)
    return response.data
  },

  async createTemplate(data) {
    const response = await axios.post(`${API_BASE}/templates`, data)
    return response.data
  },

  async updateTemplate(templateId, data) {
    const response = await axios.put(`${API_BASE}/templates/${templateId}`, data)
    return response.data
  },

  async deleteTemplate(templateId) {
    const response = await axios.delete(`${API_BASE}/templates/${templateId}`)
    return response.data
  },

  async useTemplate(templateId) {
    const response = await axios.post(`${API_BASE}/templates/${templateId}/use`)
    return response.data
  }
}
