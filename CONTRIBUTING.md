# 贡献指南

感谢你愿意改进词札。本文说明如何搭环境、改代码、跑验证和提 PR。

## 开始之前

- 较大的功能或架构调整，请先开 Issue 说明动机与方案，避免重复劳动。
- 安全问题请勿公开提 Issue，按 [SECURITY.md](SECURITY.md) 的流程私下报告。
- 提交前请确保没有把 `backend/data/`、`backend/.env` 或任何 API Key 加入暂存区。

## 开发环境

环境要求：Python 3.10+、Node.js 20.19+ 或 22.12+。

```bash
# 一次性安装依赖（创建 backend/venv、安装后端依赖、构建前端）
./setup.sh          # Windows: setup.bat

# 日常开发：两个进程
cd backend
./venv/bin/uvicorn app.main:app --reload --port 8000 --reload-exclude "data/*"

cd frontend
npm run dev
```

> `--reload-exclude "data/*"` 不可省略：SQLite 写入会触发 uvicorn 重载，可能中断正在提交的复习请求。

只想跑正式形态（单端口）时，先 `npm run build`，再启动 uvicorn 即可。

## 代码结构

| 位置 | 说明 |
|---|---|
| `backend/app/main.py` | 应用装配、路由注册、SPA 托管 |
| `backend/app/routers/` | 各领域接口（词典、词库、复习、统计、模型配置） |
| `backend/app/services/` | 词典、LLM、复习调度等业务逻辑 |
| `backend/app/models.py` / `schemas.py` | ORM 模型与请求/响应结构 |
| `frontend/src/views/` | 页面级组件 |
| `frontend/src/components/` | 可复用组件 |

配置与用户数据都在运行时生成：`backend/.env`、`backend/data/`，两者均被 gitignore。

## 提交前验证

```bash
cd backend
ruff check app tests
./venv/bin/python -m unittest discover -s tests -t . -v

cd ../frontend
npm run build
```

三件事必须全绿，CI（[.github/workflows/ci.yml](.github/workflows/ci.yml)）也执行同样的检查。
新增接口或修复 bug 时请补对应单元测试，测试使用独立临时 SQLite，不会碰到本地数据。

## 提交规范

提交信息使用前缀 + 简短说明，例如：

```
feat: 支持按词性筛选词库
fix: 复习队列在跨天时重复计入
docs: 补充国内网络镜像说明
```

- `feat` 新功能 · `fix` 修复 · `docs` 文档 · `style` 样式 · `refactor` 重构 · `test` 测试 · `chore` 杂项
- 一个提交只做一件事，避免把格式化与逻辑修改混在一起

## Pull Request

1. Fork 仓库，从 `main` 拉出分支：`feat/xxx` 或 `fix/xxx`
2. 提交前跑完上面的验证
3. PR 描述里写清：改了什么、为什么改、如何验证（截图 / 复现步骤）
4. 关联相关 Issue（如 `Closes #12`）
5. 等待 CI 通过后由维护者合并

## 行为约定

- 讨论对事不对人，尊重不同方案。
- 不接受把用户数据或密钥上传到第三方的改动。
- 不引入与项目定位无关的重量级依赖；新增依赖需在 PR 中说明必要性。
