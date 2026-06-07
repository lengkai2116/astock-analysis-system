/**
 * IndexedDB Schema 数据版本迁移
 *
 * 对照 151-观潮对标-系统能力提升与稳定性优化方案.md §4.4
 * 在 cacheService 初始化时自动运行，保证 IndexedDB 数据结构向前兼容
 */

const MIGRATION_KEY = 'a_stock_schema_version'
const MIGRATION_TARGET = 2

/**
 * 迁移注册表
 * key = 目标版本号，value = 迁移函数
 * 从 (version + 1) 开始执行，直到 MIGRATION_TARGET
 */
const MIGRATIONS = {
  1: async () => {
    // v0 → v1: 初始建表（由 IndexedDB onupgradeneeded 处理）
    // 本迁移仅标记版本
    console.log('[SchemaMigration] v1: 基础存储结构就绪')
  },
  2: async () => {
    // v1 → v2: klines 表增加 period 索引
    // 由 IndexedDB onupgradeneeded 处理 DB 层面的变更
    // 本迁移处理数据层面的迁移（如已有数据的索引重建）
    console.log('[SchemaMigration] v2: klines period 索引已添加')
  },
}

class SchemaMigration {
  /**
   * 执行所有待运行的迁移
   * 应在应用启动时调用一次
   */
  static async run() {
    const currentVersion = parseInt(
      localStorage.getItem(MIGRATION_KEY) || '0',
      10
    )

    if (currentVersion >= MIGRATION_TARGET) {
      return { migrated: false, from: currentVersion, to: currentVersion }
    }

    let lastVersion = currentVersion
    for (let v = currentVersion + 1; v <= MIGRATION_TARGET; v++) {
      if (MIGRATIONS[v]) {
        try {
          await MIGRATIONS[v]()
          localStorage.setItem(MIGRATION_KEY, String(v))
          lastVersion = v
          console.log(`[SchemaMigration] 迁移至 v${v} 完成`)
        } catch (err) {
          console.error(`[SchemaMigration] 迁移 v${v} 失败:`, err)
          throw err
        }
      }
    }

    return {
      migrated: lastVersion > currentVersion,
      from: currentVersion,
      to: lastVersion,
    }
  }

  /**
   * 获取当前 schema 版本
   */
  static getCurrentVersion() {
    return parseInt(localStorage.getItem(MIGRATION_KEY) || '0', 10)
  }

  /**
   * 强制重置版本号（仅用于开发调试）
   */
  static resetVersion(version = 0) {
    localStorage.setItem(MIGRATION_KEY, String(version))
    console.log(`[SchemaMigration] 版本已重置为 v${version}`)
  }
}

export default SchemaMigration
