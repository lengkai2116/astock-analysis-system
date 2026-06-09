/*
策略模板系统服务
*/
import request from '../utils/request'

const API_BASE = '/api/strategy-templates'

export default {
  async getTemplates(params = {}) {
    const response = await request.get(API_BASE, { params })
    return response.data
  },

  async getCategories() {
    const response = await request.get(`${API_BASE}/categories`)
    return response.data
  },

  async getTemplate(templateId) {
    const response = await request.get(`${API_BASE}/${templateId}`)
    return response.data
  },

  async createTemplate(data) {
    const response = await request.post(API_BASE, data)
    return response.data
  },

  async updateTemplate(templateId, data) {
    const response = await request.put(`${API_BASE}/${templateId}`, data)
    return response.data
  },

  async deleteTemplate(templateId) {
    const response = await request.delete(`${API_BASE}/${templateId}`)
    return response.data
  }
}
