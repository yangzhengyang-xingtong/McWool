# MCP Integration · 麦当劳 MCP 集成说明

本项目基于**麦当劳中国官方 MCP Server** 构建，不使用任何逆向接口或爬虫。

## MCP Server

| 项目 | 值 |
|---|---|
| 服务端 | 麦当劳中国官方远程托管 MCP Server |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（JSON-RPC 2.0） |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| Token 申请 | https://open.mcd.cn （登录 → 控制台 → 激活） |
| 频率限制 | 600 次/分钟/Token（本项目远低于该阈值） |

## 使用的 Tools

| MCP Tool | 用途 | 在 McWool 中的业务价值 |
|---|---|---|
| `auto-bind-coupons` | 自动领取麦麦省**所有**当前可领的优惠券 | 核心能力：一键领光，解决"忘领券"痛点，代理人亲自干活 |
| `query-my-coupons` | 查询账户持有的优惠券列表 | 盘点券包（名称/面额/有效期），生成战报的券包明细 |
| `query-my-account` | 查询积分账户（可用/累计/冻结/即将过期） | 积分看护：**即将过期积分预警**，提醒抽奖或兑换 |
| `query-lottery-info` | 查询积分抽奖活动（状态/奖池/消耗规则） | 让用户决策是否消耗积分抽奖 |
| `draw-lottery` | 执行一次积分抽奖 | `lottery --draw N` 自动抽奖，把过期货变成可能的奖品 |
| `now-time-info` | 获取服务端时间 | 辅助判断活动/有效期（保留接口） |

## 调用流程

```
mcwool.py
   │
   ├─ McdMCPClient.initialize()
   │    POST https://mcp.mcd.cn
   │    method: initialize（记录 Mcp-Session-Id）
   │    └─ notifications/initialized
   │
   ├─ cmd_daily（每日羊毛例行）
   │    ├─ 1. auto-bind-coupons      → 一键领券（写操作）
   │    ├─ 2. query-my-coupons       → 券包盘点
   │    ├─ 3. query-my-account       → 积分体检
   │    │       └─ 即将过期积分 > 0 → 触发 ⏰ 预警
   │    └─ 4. 汇总 → 终端战报 + HTML 分享卡片
   │
   ├─ cmd_lottery --draw N
   │    ├─ query-lottery-info        → 展示奖池与消耗
   │    └─ draw-lottery × N          → 自动抽奖（上限 10 次/回）
   │
   └─ 响应解析：content[0].text → JSON → 字段容错提取
        （服务端字段命名可能调整，McWool 做了宽松匹配，任何结构都不崩）
```

## 业务价值

1. **从"给建议"到"动手干"**：市面上的省钱工具多为推荐/比价；McWool 通过 `auto-bind-coupons`、`draw-lottery` 两个**写操作**工具真正代用户执行，是"代理人（Agent）"而非"计算器"。
2. **把损失消灭在发生前**：麦麦省券每日更新、积分会静默过期，普通用户无从感知；`daily` 例行任务 + 过期预警形成每日看护闭环。
3. **可传播的输出**：羊毛战报卡片把"省了多少钱"变成可炫耀的社交货币，与羊毛场景天然契合。
