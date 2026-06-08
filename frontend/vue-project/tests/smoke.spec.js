/**
 * 页面渲染冒烟测试
 * 验证所有路由可正常渲染，无 JS 运行时错误
 * 401/403 等认证错误被认为是正常的（API 受保护时的预期行为）
 */
import { test, expect } from '@playwright/test';

const ROUTES = [
  { path: '/login',          name: '登录页' },
  { path: '/',               name: '仪表盘' },
  { path: '/indicator-ide',  name: '个股策略分析' },
  { path: '/screener',       name: '选股系统' },
  { path: '/watchlist',      name: '自选监控' },
  { path: '/ai-analysis',    name: 'AI 分析' },
  { path: '/backtest',       name: '回测系统' },
  { path: '/factor-manager', name: '因子管理' },
  { path: '/strategy-templates', name: '策略模板' },
  { path: '/reports-center', name: '报告中心' },
  { path: '/account',        name: '账户管理' },
];

// 认证/网络类错误 - 前端受保护时的正常行为
const AUTH_ERROR_PATTERNS = [
  '401', '403', 'status code 401', 'status code 403',
  'Unauthorized', 'Forbidden', 'AuthRequired',
  'NetworkError', 'Failed to load', 'ERR_NAME_NOT_RESOLVED',
  'Request failed with status code', 'Response error',
  '获取 K 线数据失败', '获取数据失败',
];

function isAuthOrNetworkError(msg) {
  return AUTH_ERROR_PATTERNS.some(p => msg.includes(p));
}

for (const { path, name } of ROUTES) {
  test(`${name} (${path}) 渲染正常`, async ({ page }) => {
    const runtimeErrors = [];
    page.on('pageerror', err => {
      runtimeErrors.push(err.message);
    });

    await page.goto(path, { waitUntil: 'networkidle', timeout: 20000 });

    // 验证页面有内容
    const html = await page.content();
    expect(html.length).toBeGreaterThan(100);

    // 验证 App 根节点存在
    const appRoot = await page.$('#app');
    expect(appRoot).not.toBeNull();

    // 仅检查 JS 运行时错误（TypeError, ReferenceError 等），忽略 API 401
    const realErrors = runtimeErrors.filter(e => !isAuthOrNetworkError(e));
    expect(realErrors).toEqual([]);

    // 验证无白屏（页面有文本或 ErrorBoundary 降级 UI）
    const errorFallback = await page.$('.error-boundary-fallback');
    expect(errorFallback).toBeNull();
  });
}

test('路由切换不残留错误状态', async ({ page }) => {
  const errorPages = [];
  for (const { path, name } of ROUTES) {
    await page.goto(path, { waitUntil: 'networkidle', timeout: 20000 });
    const hasError = await page.$('.error-boundary-fallback');
    if (hasError) {
      errorPages.push(name);
    }
  }
  expect(errorPages).toEqual([]);
});
