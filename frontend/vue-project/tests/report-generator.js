/**
 * 检查报告生成器
 * 读取 Playwright JSON 输出，输出结构化 check-report.json
 *
 * 用法: node tests/report-generator.js <playwright-report.json>
 */
import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPORTS_DIR = join(__dirname, '..', 'playwright-report');

function formatDuration(ms) {
  if (!ms) return 0;
  return Math.round(ms);
}

function parsePlaywrightReport(reportPath) {
  const raw = JSON.parse(readFileSync(reportPath, 'utf-8'));
  const details = [];
  let passed = 0;
  let failed = 0;
  let skipped = 0;
  let totalTime = 0;

  function extractTests(suite) {
    if (!suite) return;
    if (suite.suites) {
      for (const s of suite.suites) extractTests(s);
    }
    if (suite.specs) {
      for (const spec of suite.specs) {
        for (const test of spec.tests) {
          const result = test.results && test.results[0];
          const status = test.status || (result ? result.status : 'unknown');
          const duration = result ? formatDuration(result.duration) : 0;
          totalTime += duration;

          // 提取 annotations
          const annotations = result?.annotations || [];

          const entry = {
            id: `${suite.title || 'test'}`,
            category: categorizeTest(spec.title),
            description: spec.title,
            status: status === 'passed' ? 'pass' : (status === 'failed' ? 'fail' : 'skip'),
            duration_ms: duration,
            annotations,
            screenshot: findScreenshot(spec.title),
          };
          details.push(entry);

          if (status === 'passed') passed++;
          else if (status === 'failed') failed++;
          else skipped++;
        }
      }
    }
  }

  extractTests(raw);

  return { summary: { total: passed + failed + skipped, passed, failed, skipped, total_time_ms: totalTime }, details };
}

function categorizeTest(title) {
  if (title.includes('1.1') || title.includes('渲染正常') || title.includes('路由切换') || title.match(/\[\d+\.\d+\.\d+\]/) && !title.includes('2.') && !title.includes('3.')) {
    return 'ui-functionality';
  }
  if (title.includes('2.') || title.includes('数据一致性') || title.includes('API') || title.includes('数据')) {
    return 'data-authenticity';
  }
  if (title.includes('3.') || title.includes('流程') || title.includes('性能') || title.includes('错误处理') || title.includes('状态')) {
    return 'user-experience';
  }
  return 'other';
}

function findScreenshot(title) {
  // 尝试在各截图目录中找到匹配的截图
  const baseDir = join(__dirname, 'screenshots');
  if (!existsSync(baseDir)) return null;

  const searchDirs = ['ui', 'flows', 'errors'];
  const slug = title.replace(/[\[\]\/\\:*?"<>|]/g, '').substring(0, 60).trim();

  for (const dir of searchDirs) {
    const dirPath = join(baseDir, dir);
    if (!existsSync(dirPath)) continue;
    try {
      const files = readdirSync(dirPath);
      for (const file of files) {
        if (file.toLowerCase().includes(slug.toLowerCase().substring(0, 20))) {
          return `screenshots/${dir}/${file}`;
        }
      }
    } catch (e) { /* ignore */ }
  }
  return null;
}

// ── 主流程 ──
async function main() {
  // 查找最新 JSON 报告
  if (!existsSync(REPORTS_DIR)) {
    // 使用默认路径
    const defaultPath = join(__dirname, '..', 'test-results.json');
    if (existsSync(defaultPath)) {
      try {
        const report = parsePlaywrightReport(defaultPath);
        writeReport(report);
      } catch (e) {
        console.error('无法读取默认报告:', e.message);
        process.exit(1);
      }
    } else {
      // 从命令行参数获取
      const reportPath = process.argv[2];
      if (reportPath && existsSync(reportPath)) {
        try {
          const report = parsePlaywrightReport(reportPath);
          writeReport(report);
        } catch (e) {
          console.error('无法读取报告:', e.message);
          process.exit(1);
        }
      } else {
        // 查找 playwright-report 目录中的报告
        const files = readdirSync(REPORTS_DIR).filter(f => f.endsWith('.json'));
        if (files.length > 0) {
          const latest = files.sort().reverse()[0];
          const report = parsePlaywrightReport(join(REPORTS_DIR, latest));
          writeReport(report);
        } else {
          console.log('未找到 Playwright JSON 报告。请先运行测试: npx playwright test --reporter=json');
          console.log('用法: node tests/report-generator.js <path-to-report.json>');
          process.exit(0);
        }
      }
    }
  } else {
    const files = readdirSync(REPORTS_DIR).filter(f => f.endsWith('.json'));
    if (files.length > 0) {
      const latest = files.sort().reverse()[0];
      const report = parsePlaywrightReport(join(REPORTS_DIR, latest));
      writeReport(report);
    } else {
      console.log('未找到 Playwright JSON 报告。');
      process.exit(0);
    }
  }
}

function writeReport(report) {
  const reportPath = join(__dirname, '..', 'check-report.json');
  writeFileSync(reportPath, JSON.stringify(report, null, 2), 'utf-8');

  const { summary, details } = report;
  // 生成可读摘要
  const phase1 = details.filter(d => d.category === 'ui-functionality');
  const phase2 = details.filter(d => d.category === 'data-authenticity');
  const phase3 = details.filter(d => d.category === 'user-experience');

  console.log('='.repeat(60));
  console.log('  A股分析系统 - 前端全量检查报告');
  console.log('='.repeat(60));
  console.log(`  总计: ${summary.total}  |  通过: ${summary.passed}  |  失败: ${summary.failed}  |  跳过: ${summary.skipped}`);
  console.log(`  总耗时: ${(summary.total_time_ms / 1000).toFixed(1)}s`);
  console.log('─'.repeat(60));
  console.log(`  第一阶段 UI 功能: ${phase1.filter(d => d.status === 'pass').length}/${phase1.length}`);
  console.log(`  第二阶段 数据真实性: ${phase2.filter(d => d.status === 'pass').length}/${phase2.length}`);
  console.log(`  第三阶段 使用效果: ${phase3.filter(d => d.status === 'pass').length}/${phase3.length}`);
  console.log('─'.repeat(60));

  if (details.some(d => d.status === 'fail')) {
    console.log('  ❌ 失败详情:');
    for (const d of details.filter(d => d.status === 'fail')) {
      console.log(`    - ${d.description}`);
    }
  } else {
    console.log('  ✅ 所有检查通过！');
  }
  console.log('─'.repeat(60));
  console.log(`  完整报告已保存至: tests/check-report.json`);
  console.log('='.repeat(60));
}

main().catch(console.error);
