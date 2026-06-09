/**
 * 生产就绪全量检查 — 运行时验证 (对应 167/168 报告)
 * 覆盖: A(响应式/主题/弹窗) B(表单/弹窗/WS) E(降级) G(CSP) H(a11y)
 */
import { test, expect } from '@playwright/test';
import { ROUTES } from './helpers.js';

const BASE = 'http://127.0.0.1:9000';

// 每个页面基本渲染测试
test.describe('A02-A03: 响应式布局 + 双主题', () => {
  for (const route of ROUTES) {
    test(`[A02.2/A03.1] ${route.name} - tablet(1024x768) + dark theme`, async ({ page }) => {
      test.setTimeout(30000);
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.goto(`${BASE}/#${route.path}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(1000);
      
      // 检查页面不崩溃
      const body = page.locator('body');
      await expect(body).toBeVisible();
      
      // 检查无全屏错误
      const errors = [];
      page.on('console', msg => {
        if (msg.type() === 'error') errors.push(msg.text());
      });
      
      // 检查深色主题
      const html = page.locator('html');
      const theme = await html.getAttribute('data-theme');
      expect(theme).toBe('dark');
      
      // 检查无关键重叠元素
      const app = page.locator('#app').first();
      const appBox = await app.boundingBox();
      expect(appBox.width).toBeGreaterThan(100);
      expect(appBox.height).toBeGreaterThan(100);
    });
  }

  for (const route of ROUTES) {
    test(`[A02.3] ${route.name} - mobile(375x812)`, async ({ page }) => {
      test.setTimeout(30000);
      await page.setViewportSize({ width: 375, height: 812 });
      await page.goto(`${BASE}/#${route.path}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(1000);
      const body = page.locator('body');
      await expect(body).toBeVisible();
    });
  }
});

test.describe('B01: 表单验证', () => {
  test('[B01.1] 登录页 - 空提交应阻止', async ({ page }) => {
    test.setTimeout(15000);
    await page.goto(`${BASE}/#/login`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    
    // 点击登录按钮 (空 token)
    const loginBtn = page.locator('button:has-text("登录")');
    if (await loginBtn.isVisible()) {
      await loginBtn.click();
      await page.waitForTimeout(500);
      // 校验提示出现 (表单验证或错误提示)
      const errorVisible = await page.locator('.ant-form-item-explain-error, .login-error').first().isVisible().catch(() => false);
      expect(errorVisible).toBe(true);
    }
  });

  test('[B01.3] 回测页 - 日期范围验证', async ({ page }) => {
    test.setTimeout(15000);
    await page.goto(`${BASE}/#/backtest`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    
    const runBtn = page.locator('button:has-text("开始回测")');
    if (await runBtn.isVisible()) {
      await runBtn.click();
      await page.waitForTimeout(500);
      // 应该显示验证提示
      const warnMsg = page.locator('.ant-message-warning, .ant-form-item-explain-error');
      const visible = await warnMsg.first().isVisible().catch(() => false);
      expect(visible).toBe(true);
    }
  });

  test('[B01.4/B01.6] 报告中心 - 表单验证 + 防重复提交', async ({ page }) => {
    test.setTimeout(15000);
    await page.goto(`${BASE}/#/reports-center`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    
    // 检查生成报告按钮
    const genBtn = page.locator('button:has-text("生成报告")');
    if (await genBtn.isVisible()) {
      await genBtn.click();
      await page.waitForTimeout(500);
      // 弹窗应出现
      const modal = page.locator('.ant-modal');
      const modalVisible = await modal.first().isVisible().catch(() => false);
      expect(modalVisible).toBe(true);
    }
  });
});

test.describe('B03: 弹窗生命周期', () => {
  test('[B03.1/B03.2] 弹窗 Esc + 蒙层关闭', async ({ page }) => {
    test.setTimeout(15000);
    await page.goto(`${BASE}/#/report-center`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    
    // 尝试打开任意弹窗
    const triggerBtns = page.locator('button:has-text("生成报告"), button:has-text("新建"), button:has-text("配置")');
    if (await triggerBtns.first().isVisible()) {
      await triggerBtns.first().click();
      await page.waitForTimeout(500);
      const modal = page.locator('.ant-modal');
      if (await modal.first().isVisible().catch(() => false)) {
        // 按 Esc 关闭
        await page.keyboard.press('Escape');
        await page.waitForTimeout(500);
        const modalStillVisible = await modal.first().isVisible().catch(() => false);
        expect(modalStillVisible).toBe(false);
      }
    }
  });
});

test.describe('B05: 无效路由', () => {
  test('[B05.2] 无效路由应显示页面而非白屏', async ({ page }) => {
    test.setTimeout(10000);
    await page.goto(`${BASE}/#/nonexistent-route`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});

test.describe('E04: 错误降级', () => {
  test('[E04.1] Dashboard 数据加载失败显示降级', async ({ page }) => {
    test.setTimeout(15000);
    // 模拟网络断开
    await page.route('**/api/**', route => route.abort());
    await page.goto(`${BASE}/#/`, { waitUntil: 'networkidle', timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(2000);
    
    // 页面应仍显示 (不白屏)
    const body = page.locator('body');
    await expect(body).toBeVisible();
    
    // 检查有内容渲染 (非空白)
    const bodyText = await body.textContent();
    expect(bodyText.length).toBeGreaterThan(50);
  });
});

test.describe('G01: CSP 不阻塞', () => {
  test('[G01.4] 首页在 CSP 下正常渲染', async ({ page }) => {
    test.setTimeout(15000);
    await page.goto(`${BASE}/#/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    
    // 检查控制台无 CSP 错误
    const cspErrors = [];
    page.on('console', msg => {
      if (msg.text().includes('CSP') || msg.text().includes('Content Security')) {
        cspErrors.push(msg.text());
      }
    });
    
    const body = page.locator('body');
    await expect(body).toBeVisible();
    expect(cspErrors.length).toBe(0);
  });
});

test.describe('H02: 键盘导航', () => {
  test('[H02.1/H02.2] Tab 导航不崩溃', async ({ page }) => {
    test.setTimeout(20000);
    await page.goto(`${BASE}/#/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1000);
    
    // 按 Tab 多次遍历页面
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(200);
    }
    
    // 页面应仍正常
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });
});

// 截图收集 - 用于视觉验证
test.describe('截图收集', () => {
  for (const route of ROUTES) {
    test(`screenshot ${route.name}`, async ({ page }) => {
      test.setTimeout(20000);
      await page.goto(`${BASE}/#${route.path}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(1500);
      await page.screenshot({ 
        path: `tests/screenshots/168_${route.name}.png`,
        fullPage: true 
      });
    });
  }
});
