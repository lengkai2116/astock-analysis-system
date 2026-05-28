/*
策略模板系统服务
*/
import axios from 'axios'

const API_BASE = '/api/strategy-templates'

export default {
  async getTemplates(params = {}) {
    const response = await axios.get(API_BASE, { params })
    return response.data
  },

  async getCategories() {
    const response = await axios.get(`${API_BASE}/categories`)
    return response.data
  },

  async getTemplate(templateId) {
    const response = await axios.get(`${API_BASE}/${templateId}`)
    return response.data
  },

  async createTemplate(data) {
    const response = await axios.post(API_BASE, data)
    return response.data
  },

  async updateTemplate(templateId, data) {
    const response = await axios.put(`${API_BASE}/${templateId}`, data)
    return response.data
  },

  async deleteTemplate(templateId) {
    const response = await axios.delete(`${API_BASE}/${templateId}`)
    return response.data
  }
}
