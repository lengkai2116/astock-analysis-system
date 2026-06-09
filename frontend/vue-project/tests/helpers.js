/**
 * 共享测试辅助模块
 * 包含认证注入、通用检查函数、路由表、截图等
 */

// 认证 Token（从 `.env.local` 获取）
export const AUTH_TOKEN = '123456';

// 所有可路由页面
export const ROUTES = [
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

// 认证/网络类错误 - 前端受保护的正常行为
export const AUTH_ERROR_PATTERNS = [
  '401', '403', 'status code 401', 'status code 403',
  'Unauthorized', 'Forbidden', 'AuthRequired',
  'NetworkError', 'Failed to load', 'ERR_NAME_NOT_RESOLVED',
  'Request failed with status code', 'Response error',
  '获取 K 线数据失败', '获取数据失败',
];

export function isAuthOrNetworkError(msg) {
  return AUTH_ERROR_PATTERNS.some(p => msg.includes(p));
}

/**
 * 在所有测试之前设置认证
 * 为 page 注入 localStorage token + Authorization header 拦截
 * @param {import('@playwright/test').Page} page
 */
export async function setupAuth(page) {
  // 注入 localStorage token（部分组件读 token 判断登录态）
  await page.addInitScript(() => {
    localStorage.setItem('token', '123456');
  });
  // 拦截请求自动注入 Authorization header
  await page.route('**/api/**', async (route) => {
    const headers = route.request().headers();
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
    await route.continue({ headers });
  });
}

/**
 * 截图保存（含截图目录路径自动创建）
 */
export async function takeScreenshot(page, category, name) {
  const path = `tests/screenshots/${category}/${name}.png`;
  await page.screenshot({ path, fullPage: true });
  return path;
}

/**
 * 通用的 UI 辅助：收集页面 JS 错误
 */
export function collectErrors(page) {
  const errors = [];
  page.on('pageerror', err => errors.push(err.message));
  return errors;
}

/**
 * 计算两个数值的差异百分比（用于数据一致性检查）
 */
export function percentDiff(a, b) {
  if (a === 0 && b === 0) return 0;
  if (a === 0) return 100;
  return Math.abs((a - b) / a) * 100;
}

/**
 * 检查 canvas 是否非空（有渲染内容）
 */
export async function canvasHasContent(page, selector = 'canvas') {
  return page.evaluate((sel) => {
    const canvas = document.querySelector(sel);
    if (!canvas) return false;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    // 检查是否有非透明像素
    for (let i = 3; i < imageData.data.length; i += 4) {
      if (imageData.data[i] > 0) return true;
    }
    return false;
  }, selector);
}
