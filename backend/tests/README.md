# 后端测试

零额外依赖：用 Python 标准库 `unittest` 编写，`fastapi.testclient` 做接口级验证。

## 运行

```bash
cd backend
./venv/bin/python -m unittest discover -s tests -t . -v
```

装了 pytest 也可以用（`backend/pyproject.toml` 已配好 `testpaths`）：

```bash
cd backend && pytest -q
```

## 隔离性

- `tests/__init__.py` 在**任何** `app.*` 被导入之前把 `DANCIJI_DB_PATH` 指向临时文件 ——
  因为 `app/main.py` 在 import 阶段就会执行 `create_all()` 与 `_migrate()`，
  不先隔离的话跑一次测试就会改动真实的 `data/danciji.db`。
- 每个用例再通过 `make_client()` 拿到一份**独占的内存 SQLite**，并覆盖 FastAPI 的
  `get_db` 依赖，用例之间互不影响。

## 覆盖面

| 文件 | 覆盖内容 |
|:--|:--|
| `test_words.py` | P0-1 部分更新不清空字段、P0-2/P0-3 `null` 不再 500、P0-5 标签边界精确匹配、P0-6 CSV 含 `note` 与往返、P0-7 通配符转义、P1-4 分页与 `limit` 约束 |
| `test_review.py` | P0-4 到期守卫与幂等、三档 `记住/模糊/忘记` 规则、档位封顶、概览统计、复习接口的标签筛选 |
| `test_stats.py` | 统计接口结构（7 日趋势补零、6 档分布、标签 Top 8、空库安全） |
| `test_dictionary.py` | 有道返回解析（音标/释义/例句去重截断）+ 接口的 found / 未收录 / 上游 502 分支 |
| `test_migration.py` | P0-5 存量标签归一、迁移幂等、`next_review_at` 补全、含空格标签不被压缩 |

这些用例已用**变异测试**验证过有效性：把 P0-1 的 `examples` 守卫或 P0-5 的边界匹配改回旧写法，
对应用例会立即失败。
