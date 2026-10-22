## 改动说明

<!-- 这个 PR 做了什么，为什么需要它 -->

## 关联 Issue

<!-- 如 Closes #12；没有则写「无」 -->

## 改动类型

- [ ] 新功能（feat）
- [ ] Bug 修复（fix）
- [ ] 文档（docs）
- [ ] 重构 / 性能（refactor）
- [ ] 测试（test）
- [ ] 其他

## 验证方式

<!-- 如何验证本次改动有效：命令、测试、截图或复现步骤 -->

```bash
cd backend
ruff check app tests
./venv/bin/python -m unittest discover -s tests -t . -v
```

## 自查清单

- [ ] 本地 ruff 与单元测试全部通过
- [ ] 前端有改动时 `npm run build` 通过
- [ ] 未提交 `backend/data/`、`backend/.env` 或任何密钥
- [ ] 新增接口 / 修复 bug 已补对应测试
- [ ] 文档（README / CHANGELOG）已按需更新
