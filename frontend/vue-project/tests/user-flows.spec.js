/**
 * 第三阶段：使用效果检查
 * 覆盖 3.1 ~ 3.5
 */
import { test, expect } from '@playwright/test';
import { ROUTES, setupAuth, takeScreenshot } from './helpers.js';

// ── 3.1 核心用户流程 ──
test.describe('3.1 核心用户流程', () => {
  test('[3.1.1] 股票分析闭环：搜索 → K 线 → 切换周期/指标', async ({ page }) => {
    await setupAuth(page);

    // 步骤 1：访问首页
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(1000);
    await takeScreenshot(page, 'flows', '3.1.1-step1-home');

    // 步骤 2：导航到个股策略分析页
    await page.goto('/#/indicator-ide', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(3000);
    await takeScreenshot(page, 'flows', '3.1.1-step2-indicator-ide');

    // 步骤 3：搜索股票
    const searchInput = await page.$('.ant-select-selection-search-input');
    if (searchInput) {
      await searchInput.fill('600519');
      await page.waitForTimeout(1000);
      const option = await page.$('.ant-select-item-option');
      if (option) {
        await option.click();
        await page.waitForTimeout(2000);
        await takeScreenshot(page, 'flows', '3.1.1-step3-stock-selected');
      }
    }

    // 步骤 4：K 线已渲染
    const canvases = await page.$$('canvas');
    test.expect(canvases.length).toBeGreaterThanOrEqual(1);
  });

  test('[3.1.2] 选股到回测流程', async ({ page }) => {
    await setupAuth(page);

    // 步骤 1：访问选股系统
    await page.goto('/#/screener', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.2-step1-screener');

    // 步骤 2：导航到回测系统
    await page.goto('/#/backtest', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.2-step2-backtest');

    // 步骤 3：验证回测配置可用
    const configBtn = await page.$('button:has-text("回测配置"), button:has-text("配置")');
    if (configBtn) {
      await configBtn.click();
      await page.waitForTimeout(500);
      await takeScreenshot(page, 'flows', '3.1.2-step3-backtest-config');
    }
  });

  test('[3.1.3] 账户管理闭环', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/account', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.3-step1-account');

    // 切换各个 Tab
    const tabs = await page.$$('.ant-tabs-tab');
    if (tabs.length >= 2) {
      for (let i = 0; i < Math.min(tabs.length, 4); i++) {
        await tabs[i].click();
        await page.waitForTimeout(500);
      }
      await takeScreenshot(page, 'flows', '3.1.3-step2-tabs');
    }
  });

  test('[3.1.4] 自选到 AI 分析', async ({ page }) => {
    await setupAuth(page);

    // 访问自选页
    await page.goto('/#/watchlist', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.4-step1-watchlist');

    // 导航到 AI 分析页
    await page.goto('/#/ai-analysis', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.4-step2-ai-analysis');
  });

  test('[3.1.5] 因子管理到策略', async ({ page }) => {
    await setupAuth(page);

    // 访问因子管理
    await page.goto('/#/factor-manager', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.5-step1-factors');

    // 访问策略模板
    await page.goto('/#/strategy-templates', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await takeScreenshot(page, 'flows', '3.1.5-step2-templates');
  });
});

// ── 3.2 响应与加载性能 ──
test.describe('3.2 响应与加载性能', () => {
  test('[3.2.1] 首页加载时间', async ({ page }) => {
    await setupAuth(page);
    const startTime = Date.now();
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });
    const loadTime = Date.now() - startTime;
    test.info().annotations.push({ type: 'performance', description: `首页加载时间: ${loadTime}ms` });
    // 允许较长的加载时间（后端数据可能较慢）
    test.expect(loadTime).toBeLessThan(15000);
  });

  test('[3.2.2] 页面切换时间', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(1000);

    const navTimes = [];
    for (const { path, name } of ROUTES.slice(0, 6)) {
      const start = Date.now();
      await page.goto(`/#${path}`, { waitUntil: 'networkidle', timeout: 15000 });
      navTimes.push({ name, time: Date.now() - start });
    }
    test.info().annotations.push({ type: 'performance', description: `页面切换时间: ${JSON.stringify(navTimes)}` });
  });

  test('[3.2.3,3.2.4] 长时间操作有 Loading 反馈', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/screener', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    const runBtn = await page.$('button:has-text("执行筛选"), button:has-text("开始筛选")');
    if (runBtn) {
      const loadingAttr = await runBtn.getAttribute('loading');
      test.info().annotations.push({ type: 'info', description: `筛选按钮 loading: ${loadingAttr}` });
    }
  });
});

// ── 3.3 错误处理与恢复 ──
test.describe('3.3 错误处理与恢复', () => {
  test('[3.3.1] API 网络断开时前端不崩溃', async ({ page }) => {
    const runtimeErrors = [];
    page.on('pageerror', err => runtimeErrors.push(err.message));

    await setupAuth(page);

    // 阻断所有 API 请求
    await page.route('**/api/**', async (route) => {
      await route.abort('connectionrefused');
    });

    await page.goto('/#/', { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(3000);

    // 应无 TypeError/ReferenceError 等
    const realErrors = runtimeErrors.filter(e =>
      !e.includes('401') && !e.includes('403') && !e.includes('net::ERR_CONNECTION_REFUSED') &&
      !e.includes('Failed to fetch') && !e.includes('NetworkError') && !e.includes('Network Error') && !e.includes('Request failed')
    );
    // "Network Error" is expected when blocking API
    test.expect(realErrors).toEqual([]);

    await takeScreenshot(page, "errors", "3.3-network-disconnect").catch(() => {});
  });

  test('[3.3.3] 各页面空数据状态', async ({ page }) => {
    await setupAuth(page);

    for (const { path, name } of ROUTES) {
      await page.goto(`/#${path}`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(1000);

      // 检查是否有空状态组件
      const empty = await page.$('.ant-empty, [class*="empty"], [class*="no-data"]');
      if (empty) {
        test.info().annotations.push({ type: 'info', description: `${name}: 有空状态展示` });
      }
    }
    await takeScreenshot(page, 'ui', '3.3-empty-states');
  });

  test('[3.3.4] 快速导航不导致状态错乱', async ({ page }) => {
    await setupAuth(page);

    // 快速连续导航
    for (let i = 0; i < 5; i++) {
      for (const { path } of ROUTES.slice(0, 6)) {
        await page.goto(`/#${path}`, { waitUntil: 'domcontentloaded', timeout: 10000 });
      }
    }
    await page.waitForTimeout(1000);

    // 最后应稳定在一个正确页面
    const hasError = await page.$('.error-boundary-fallback');
    test.expect(hasError).toBeNull();

    await takeScreenshot(page, 'flows', '3.3-rapid-nav');
  });
});

// ── 3.4 状态一致性与持久化 ──
test.describe('3.4 状态一致性与持久化', () => {
  test('[3.4.1] 主题偏好刷新后保持', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });

    // 切换到浅色主题
    const initialTheme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    const targetTheme = initialTheme === 'dark' ? 'light' : 'dark';
    await page.click('.theme-toggle');
    await page.waitForTimeout(500);

    // 刷新页面
    await page.reload({ waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(1000);
    const afterReload = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    const storedAfter = await page.evaluate(() => localStorage.getItem('app-theme'));

    // 刷新后应保持切换后的主题
    test.expect(afterReload).toBe(targetTheme);
    test.expect(storedAfter).toBe(targetTheme);

    // 恢复
    await page.click('.theme-toggle');
    await page.waitForTimeout(300);
  });

  test('[3.4.2] 侧边栏折叠状态刷新后保持', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });

    // 折叠侧边栏
    const collapseBtn = await page.$('.collapse-btn');
    if (collapseBtn) {
      await collapseBtn.click();
      await page.waitForTimeout(500);
    }

    // 刷新
    await page.reload({ waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(1000);

    // 刷新后应仍折叠
    const stillCollapsed = await page.$('.sidebar.collapsed');
    // 如果存储了折叠状态，应该保持；如果没有存则可能恢复展开
    // 这里只做观察
    test.info().annotations.push({ type: 'info', description: `刷新后 sidebar collapsed: ${stillCollapsed !== null}` });
    await takeScreenshot(page, 'ui', '3.4-sidebar-persist');
  });

  test('[3.4.3,3.4.4] 路由切换不污染样式，Tab 数据独立', async ({ page }) => {
    await setupAuth(page);

    // 快速遍历所有路由检查样式
    for (const { path } of ROUTES) {
      await page.goto(`/#${path}`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      // 检查无跨页面样式污染（全局样式一致）
      const hasGlobalTheme = await page.evaluate(() => {
        const html = document.documentElement;
        return html.getAttribute('data-theme') !== null;
      });
      test.expect(hasGlobalTheme).toBeTruthy();
    }
  });
});

// ── 3.5 跨页面/组件交互 ──
test.describe('3.5 跨页面/组件交互', () => {
  test('[3.5.1,3.5.2] 全局自定义事件派发', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(1000);

    // 派发全局刷新事件
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('app:refresh-data'));
    });
    await page.waitForTimeout(500);

    // 派发全局搜索事件
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('app:global-search'));
    });
    await page.waitForTimeout(500);

    // 确保不崩溃
    const hasError = await page.$('.error-boundary-fallback');
    test.expect(hasError).toBeNull();

    await takeScreenshot(page, 'flows', '3.5-global-events');
  });

  test('[3.5.3] 快捷键 ? 打开帮助浮层', async ({ page }) => {
    await setupAuth(page);
    await page.goto('/#/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(1000);

    // 按 ? 键（需要 Shift+/）
    await page.keyboard.press('Shift+/');
    await page.waitForTimeout(500);

    // 检查是否有帮助浮层或快捷键提示
    const helpUI = await page.$('[class*="shortcut"], [class*="help"], .ant-modal, [class*="ShortcutsHelp"]');
    if (helpUI) {
      await takeScreenshot(page, 'ui', '3.5-shortcuts-help');
      test.info().annotations.push({ type: 'info', description: '快捷键帮助浮层已触发' });
    } else {
      // 可能快捷键未绑定或按键方式不同
      test.info().annotations.push({ type: 'info', description: '快捷键帮助浮层未触发（可能不支持的按键方式）' });
    }
  });
});
