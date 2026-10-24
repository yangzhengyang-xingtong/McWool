#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
McWool · 麦门羊毛代理人
========================
让 AI 替你把麦当劳的羊毛薅干净：一键领券 / 积分看护 / 自动抽奖 / 羊毛战报。

基于麦当劳官方 MCP（https://mcp.mcd.cn，Token 于 https://open.mcd.cn 申请）。

用法：
    python mcwool.py daily                # 每日例行：领券 + 积分 + 抽奖建议 + 战报
    python mcwool.py claim                # 一键领取麦麦省所有可领优惠券
    python mcwool.py coupons              # 查看我持有的优惠券
    python mcwool.py points               # 查询积分账户（含即将过期提醒）
    python mcwool.py lottery              # 查看积分抽奖活动信息
    python mcwool.py lottery --draw 5     # 自动抽 5 次（消耗积分，谨慎使用）
    python mcwool.py daily --demo         # 演示模式：无需 Token，内置样例数据

Token 三种配置方式（优先级从高到低）：
    1. --token YOUR_TOKEN
    2. 环境变量 MCD_MCP_TOKEN
    3. 文件 ~/.mcwool_token（内容为 Token，一行）
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import textwrap
import unicodedata

try:
    import requests
except ImportError:
    print("缺少依赖 requests，请先执行: pip install requests")
    sys.exit(1)

MCP_ENDPOINT = "https://mcp.mcd.cn"
TOKEN_HELP_URL = "https://open.mcd.cn"
VERSION = "1.0.0"

# Windows 终端 ANSI 颜色支持
if os.name == "nt":
    os.system("")

# ---------------------------------------------------------------- 颜色与输出


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def bold(t): return c(t, "1")
def red(t): return c(t, "1;91")
def yellow(t): return c(t, "1;93")
def green(t): return c(t, "1;92")
def cyan(t): return c(t, "1;96")
def dim(t): return c(t, "2")
def gold(t): return c(t, "1;33")
def white(t): return c(t, "1;97")


BANNER = r"""
                        ,╖╜╙╖,
                     ╓╬╬╬╬╬╬╬╬╬,
                    ╬╬╬╬╬╬╬╬╬╬╬╬▓
      ╓╓╓╓╓╓,     ╙╬╬╬╬╬╬╬╬╬╬╬╜      ╓╓╓╓╓,
    ╬╬╬╬╬╬╬╬╬╬╬,   ╙╬╬╬╬╬╬╬╜    ,╬╬╬╬╬╬╬╬╬╬▓
    ╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╖ ╙╬╬╬╬╜ ╓╬╬╬╬╬╬╬╬╬╬╬╬╬▌
     ╙╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╜
        ╙╙╙╙╙╙╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╬╜╙╙╙╙╙╙
              ╙╙╬╬╬╬╬╬╬╬╬╬╜╙╙
"""

LOGO = (
    yellow("🍟 McWool") + white(" · ") + gold("麦门羊毛代理人") + dim("  v" + VERSION)
)


def rule(title: str = ""):
    line = "─" * 46
    print(dim("┌" + line) if not title else f"{dim('┌' + line)}\n{dim('│')} {bold(title)}")


def rule_end():
    print(dim("└" + "─" * 46))


ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def disp_len(s: str) -> int:
    """终端显示宽度：中文/全角算 2 列，忽略 ANSI 颜色码。"""
    clean = ANSI_RE.sub("", s)
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in clean)


def pad_disp(s: str, width: int) -> str:
    return s + " " * max(0, width - disp_len(s))


def center_disp(s: str, width: int) -> str:
    gap = max(0, width - disp_len(s))
    left = gap // 2
    return " " * left + s + " " * (gap - left)


def wrap_cjk(s: str, width: int) -> list:
    """按显示宽度换行（中文占 2 列）。"""
    out, line, w = [], "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if w + cw > width and line:
            out.append(line)
            line, w = ch, cw
        else:
            line, w = line + ch, w + cw
    if line:
        out.append(line)
    return out or [s]


# ---------------------------------------------------------------- MCP 客户端


class McdMCPError(Exception):
    pass


class McdMCPClient:
    """极简 MCP Streamable HTTP 客户端（JSON-RPC over HTTP POST）。"""

    def __init__(self, token: str, endpoint: str = MCP_ENDPOINT, timeout: int = 30):
        self.token = token
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.session_id = None
        self._id = 0
        self.http = requests.Session()

    # -- 底层请求 ----------------------------------------------------------

    def _headers(self, extra=None):
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": f"McWool/{VERSION}",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if extra:
            h.update(extra)
        return h

    def _post(self, payload: dict) -> dict:
        try:
            resp = self.http.post(
                self.endpoint,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise McdMCPError(f"网络请求失败：{e}") from e

        if resp.status_code == 401:
            raise McdMCPError(
                "Token 无效或已过期（401）。请到 https://open.mcd.cn 控制台重新申请。"
            )
        if resp.status_code == 429:
            raise McdMCPError("触发限流（429，600 次/分钟），请稍后再试。")
        if resp.status_code >= 400:
            raise McdMCPError(
                f"服务返回 {resp.status_code}: {resp.text[:200]}"
            )
        return self._decode(resp)

    @staticmethod
    def _decode(resp) -> dict:
        ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            # SSE：取 data: 行里的 JSON-RPC 消息
            messages = []
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        try:
                            messages.append(json.loads(data))
                        except json.JSONDecodeError:
                            pass
            if messages:
                return messages[-1]
            raise McdMCPError("SSE 响应中没有可解析的消息")
        try:
            return resp.json()
        except ValueError as e:
            raise McdMCPError(f"响应不是合法 JSON: {resp.text[:200]}") from e

    # -- MCP 协议 ----------------------------------------------------------

    def initialize(self):
        self._id += 1
        rid = self._id
        payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcwool", "version": VERSION},
            },
        }
        resp = self.http.post(
            self.endpoint, headers=self._headers(), json=payload, timeout=self.timeout
        )
        if resp.status_code >= 400:
            raise McdMCPError(
                f"初始化失败 {resp.status_code}: {resp.text[:200]}"
            )
        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        # 发送 initialized 通知（服务端通常回 202，忽略 body）
        self.http.post(
            self.endpoint,
            headers=self._headers(),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=self.timeout,
        )

    def call_tool(self, name: str, arguments: dict | None = None) -> dict | list | str:
        """调用 tools/call 并尽力解析返回的数据结构。"""
        if not self.session_id:
            self.initialize()
        self._id += 1
        rid = self._id
        payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        msg = self._post(payload)
        if "error" in msg:
            raise McdMCPError(f"调用 {name} 失败: {msg['error']}")
        result = msg.get("result", {})
        # MCP 结果在 content[] 里，取第一条 text
        texts = [
            item.get("text", "")
            for item in result.get("content", [])
            if item.get("type") == "text"
        ]
        raw = "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
        # 服务端 text 多为 JSON 字符串，二次解析
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw


# ---------------------------------------------------------------- 数据提取

# 麦当劳 MCP 各工具返回结构可能有差异，以下做「尽力而为」的字段提取，
# 提不到就原样优雅展示，保证任何结构都不崩。


def _find_first(data, keys, default=None):
    """在嵌套结构中按优先级找第一个非空字段。"""
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if v not in (None, "", [], {}):
                return v
        for v in data.values():
            found = _find_first(v, keys, _SENTINEL)
            if found is not _SENTINEL:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_first(item, keys, _SENTINEL)
            if found is not _SENTINEL:
                return found
    return default


_SENTINEL = object()


def _iter_items(data):
    """从返回结构里找出『列表』部分（券/奖品等）。"""
    if isinstance(data, dict):
        for key in ("coupons", "list", "items", "records", "prizes", "data"):
            v = data.get(key)
            if isinstance(v, list):
                return v
        for v in data.values():
            found = _iter_items(v)
            if found is not None:
                return found
    if isinstance(data, list):
        return data
    return None


def item_title(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    return str(
        _find_first(
            item,
            ["couponName", "title", "name", "productName", "prizeName", "activityName"],
            "（未命名）",
        )
    )


def item_amount(item) -> str:
    """券面额/价值，尽量找出『元』相关的数字。"""
    if not isinstance(item, dict):
        return ""
    for k, v in item.items():
        if isinstance(v, (int, float)) and re.search(
            r"(amount|price|value|discount|money|face)", k, re.I
        ):
            return f"¥{v:g}" if v >= 1 else f"{v:g}折"
    text = json.dumps(item, ensure_ascii=False)
    m = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    return f"¥{m.group(1)}" if m else ""


def item_deadline(item) -> str:
    if not isinstance(item, dict):
        return ""
    return str(
        _find_first(item, ["expireTime", "endTime", "deadline", "validEndTime", "expireDate"], "")
    )


def parse_points(account) -> dict:
    return {
        "可用积分": _find_first(account, ["availablePoints", "usablePoints", "points", "balance"]),
        "累计积分": _find_first(account, ["totalPoints", "cumulativePoints", "accumulatePoints"]),
        "冻结积分": _find_first(account, ["frozenPoints"]),
        "即将过期": _find_first(account, ["expiringPoints", "willExpirePoints", "expireSoonPoints"]),
        "过期时间": _find_first(account, ["expireTime", "willExpireDate", "expiringDate"]),
    }


# ---------------------------------------------------------------- 演示数据


def demo_payloads():
    today = dt.date.today()
    return {
        "claim": {
            "success": True,
            "code": 200,
            "message": "请求成功",
            "data": {"bindResults": [{"couponId": "D1", "success": True}, {"couponId": "D2", "success": True}, {"couponId": "D3", "success": True}, {"couponId": "D4", "success": True}, {"couponId": "D5", "success": True}]},
        },
        "coupons": {
            "success": True,
            "code": 200,
            "data": {
                "coupons": [
                    {"couponName": "板烧鸡腿堡 中套餐 减 6 元", "amount": 6, "expireTime": f"{today + dt.timedelta(days=5):%Y-%m-%d}"},
                    {"couponName": "巨无霸 减 5 元", "amount": 5, "expireTime": f"{today + dt.timedelta(days=12):%Y-%m-%d}"},
                    {"couponName": "麦辣鸡腿堡 减 13.5 元", "amount": 13.5, "expireTime": f"{today + dt.timedelta(days=7):%Y-%m-%d}"},
                    {"couponName": "中薯条 免费兑换券", "amount": 11, "expireTime": f"{today + dt.timedelta(days=3):%Y-%m-%d}"},
                    {"couponName": "麦乐鸡 5 块 减 4 元", "amount": 4, "expireTime": f"{today + dt.timedelta(days=15):%Y-%m-%d}"},
                    {"couponName": "早餐猪柳蛋麦满分 减 3 元", "amount": 3, "expireTime": f"{today + dt.timedelta(days=9):%Y-%m-%d}"},
                ]
            },
        },
        "points": {
            "success": True,
            "code": 200,
            "data": {
                "availablePoints": 846,
                "totalPoints": 2310,
                "frozenPoints": 0,
                "expiringPoints": 340,
                "willExpireDate": f"{today + dt.timedelta(days=3):%Y-%m-%d}",
            },
        },
        "lottery_info": {
            "success": True,
            "code": 200,
            "data": {
                "activityName": "麦麦 1024 程序员节抽奖",
                "status": "进行中",
                "costPoints": 100,
                "prizes": ["巨无霸兑换券", "中薯免费券", "麦乐鸡 5 折", "谢谢参与", "10 积分", "1024 积分"],
            },
        },
        "lottery_draw": {
            "success": True,
            "code": 200,
            "data": {"isWin": True, "prizeName": "中薯条免费兑换券"},
        },
        "time": {"success": True, "data": {"datetime": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}},
    }


# ---------------------------------------------------------------- 功能实现


class McWool:
    def __init__(self, client: McdMCPClient | None, demo: bool = False):
        self.client = client
        self.demo = demo
        self.demo_data = demo_payloads() if demo else None

    def call(self, tool: str, demo_key: str, arguments: dict | None = None):
        if self.demo:
            return self.demo_data[demo_key]
        return self.client.call_tool(tool, arguments)

    # -- 各功能 ------------------------------------------------------------

    def do_claim(self, quiet=False) -> list:
        if not quiet:
            rule("🐑 第一步 · 一键领券（auto-bind-coupons）")
        data = self.call("auto-bind-coupons", "claim")
        if not quiet:
            n = len(_iter_items(data) or [])
            if n:
                print(green(f"  ✅ 已自动领取 {n} 张麦麦省优惠券"))
            else:
                print(dim("  今天能领的券都领完啦，明天再来～"))
            rule_end()
        coupons = self._fetch_coupons()
        return coupons

    def _fetch_coupons(self) -> list:
        data = self.call("query-my-coupons", "coupons")
        return _iter_items(data) or []

    def do_coupons(self):
        rule("🎫 我的优惠券（query-my-coupons）")
        items = self._fetch_coupons()
        if not items:
            print(dim("  暂无优惠券，先运行 claim 一键领券吧"))
            rule_end()
            return []
        for it in items:
            amt = item_amount(it)
            dl = item_deadline(it)
            line = f"  🎟  {item_title(it)}"
            if amt:
                line += f"  {gold(amt)}"
            if dl:
                line += dim(f"  · 有效期至 {dl[:10]}")
            print(line)
        rule_end()
        return items

    def do_points(self, quiet=False) -> dict:
        if not quiet:
            rule("💰 我的积分（query-my-account）")
        data = self.call("query-my-account", "points")
        p = parse_points(data)
        if not quiet:
            for k, v in p.items():
                if v not in (None, ""):
                    print(f"  {k}: {bold(str(v))}")
            expiring = p.get("即将过期")
            if expiring and str(expiring) not in ("0", "0.0"):
                print(red(f"  ⏰ 注意：{expiring} 积分即将过期，建议抽奖或兑换掉！"))
            rule_end()
        return p

    def do_lottery_info(self):
        rule("🎰 积分抽奖活动（query-lottery-info）")
        data = self.call("query-lottery-info", "lottery_info")
        name = _find_first(data, ["activityName", "name"])
        status = _find_first(data, ["status", "activityStatus"])
        cost = _find_first(data, ["costPoints", "pointsPerDraw", "drawCostPoints"])
        prizes = _iter_items(data)
        if name:
            print(f"  活动: {bold(str(name))}" + (dim(f"（{status}）") if status else ""))
        if cost is not None:
            print(f"  每次消耗: {gold(str(cost) + ' 积分')}")
        if prizes:
            names = [item_title(p) if isinstance(p, dict) else str(p) for p in prizes][:8]
            print("  奖池: " + " / ".join(names))
        rule_end()
        return data

    def do_lottery_draw(self, times: int):
        rule(f"🎲 自动抽奖 ×{times}（draw-lottery）")
        wins = 0
        for i in range(times):
            data = self.call("draw-lottery", "lottery_draw")
            win = _find_first(data, ["isWin", "win", "isPrize"], False)
            prize = _find_first(data, ["prizeName", "prize", "name"])
            if win and prize:
                wins += 1
                print(green(f"  第 {i+1} 抽: 🎉 {prize}"))
            else:
                print(dim(f"  第 {i+1} 抽: 未中奖"))
        print(f"  合计: {wins}/{times} 中奖")
        rule_end()

    # -- 羊毛战报 ----------------------------------------------------------

    def build_report(self, coupons, points, lottery_name=None, drawn=None):
        today = dt.date.today().strftime("%Y-%m-%d")
        total_amount = 0.0
        coupon_lines = []
        for it in coupons:
            amt = item_amount(it)
            m = re.search(r"(\d+(?:\.\d+)?)", amt or "")
            if m:
                total_amount += float(m.group(1))
            coupon_lines.append(
                {"title": item_title(it), "amount": amt, "deadline": item_deadline(it)[:10]}
            )
        p = points or {}
        report = {
            "date": today,
            "coupons": coupon_lines,
            "coupon_total": round(total_amount, 1),
            "points": {k: v for k, v in p.items() if v not in (None, "")},
            "expiring": p.get("即将过期"),
            "expire_date": str(p.get("过期时间") or "")[:10],
            "lottery_name": lottery_name,
            "drawn": drawn,
            "demo": self.demo,
        }
        return report

    def print_report(self, r):
        print()
        W = 52  # 内容区显示宽度（列数）

        def row(content=""):
            print(gold("│") + pad_disp(" " + content, W) + gold("│"))

        print(gold("┌" + "─" * W + "┐"))
        print(gold("│") + center_disp(bold("🍟 今日麦门羊毛战报"), W) + gold("│"))
        print(gold("│") + center_disp(dim(r["date"] + ("　「演示数据」" if r["demo"] else "")), W) + gold("│"))
        print(gold("├" + "─" * W + "┤"))
        row()
        lines = [f"🐑 持有优惠券 {len(r['coupons'])} 张，合计价值约 ¥{r['coupon_total']}"]
        for cp in r["coupons"][:6]:
            lines.append(f"   🎟 {cp['title']}" + (f"（{cp['amount']}）" if cp["amount"] else ""))
        if len(r["coupons"]) > 6:
            lines.append(f"   … 还有 {len(r['coupons']) - 6} 张")
        for k, v in r["points"].items():
            lines.append(f"💰 {k}: {v}")
        if r.get("expiring") and str(r["expiring"]) not in ("0", "0.0", "None"):
            lines.append(f"⏰ 提醒: {r['expiring']} 积分 {r.get('expire_date') or '即将'} 过期，快抽奖/兑换！")
        if r.get("drawn") is not None:
            lines.append(f"🎰 今日自动抽奖: {r['drawn']} 次")
        for ln in lines:
            for sub in wrap_cjk(ln, W - 4):
                row(sub)
        row()
        print(gold("│") + center_disp(dim("麦门永存 🙏 攒券一时爽，一直攒券一直爽"), W) + gold("│"))
        print(gold("│") + center_disp(dim("—— McWool 麦门羊毛代理人 自动生成"), W) + gold("│"))
        print(gold("└" + "─" * W + "┘"))

    def save_report_html(self, r, path=None):
        path = path or f"mcwool_report_{dt.datetime.now():%Y%m%d_%H%M}.html"
        rows = "".join(
            f"<tr><td>🎟 {cp['title']}</td><td class='amt'>{cp['amount']}</td><td>{cp['deadline']}</td></tr>"
            for cp in r["coupons"]
        )
        pts_keys = ["可用积分", "累计积分", "即将过期"]
        pts = "".join(
            f"<div class='stat'><div class='k'>{k}</div><div class='v'>{r['points'][k]}</div></div>"
            for k in pts_keys
            if k in r["points"]
        )
        expiring_html = ""
        if r.get("expiring") and str(r["expiring"]) not in ("0", "0.0", "None"):
            expiring_html = (
                f"<div class='alert'>⏰ {r['expiring']} 积分将于 {r.get('expire_date') or '近期'} 过期，"
                f"建议抽奖或去麦麦商城兑换！</div>"
            )
        demo_badge = "<span class='badge'>演示数据</span>" if r["demo"] else ""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>McWool 羊毛战报 {r['date']}</title>
<style>
  :root {{ --red:#da291c; --yellow:#ffc72c; --dark:#1f1f1f; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:"PingFang SC","Microsoft YaHei",sans-serif; background:#f6f0e6;
         display:flex; justify-content:center; padding:40px 16px; }}
  .card {{ width:430px; background:#fff; border-radius:24px; overflow:hidden;
          box-shadow:0 20px 60px rgba(218,41,28,.18); }}
  .head {{ background:linear-gradient(135deg,var(--red),#a31621); color:#fff; padding:30px 28px 24px; position:relative; }}
  .head .logo {{ font-size:34px; }}
  .head h1 {{ font-size:22px; margin-top:6px; letter-spacing:1px; }}
  .head .date {{ opacity:.85; font-size:13px; margin-top:6px; }}
  .badge {{ position:absolute; right:16px; top:18px; background:var(--yellow); color:var(--dark);
           font-size:12px; font-weight:700; padding:4px 10px; border-radius:999px; }}
  .body {{ padding:22px 26px 26px; }}
  .big {{ display:flex; gap:14px; }}
  .stat {{ flex:1; background:#fff7e0; border-radius:16px; padding:14px 10px; text-align:center; white-space:nowrap; }}
  .stat .k {{ font-size:12px; color:#8a6d1f; }}
  .stat .v {{ font-size:22px; font-weight:800; color:var(--dark); margin-top:4px; }}
  h2 {{ font-size:15px; margin:20px 0 10px; color:var(--dark); }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  td {{ padding:7px 4px; border-bottom:1px dashed #eee; color:#444; }}
  td.amt {{ color:var(--red); font-weight:700; white-space:nowrap; text-align:right; }}
  .alert {{ margin-top:14px; background:#ffeceb; color:var(--red); border-radius:12px;
           padding:10px 12px; font-size:13px; font-weight:600; }}
  .foot {{ margin-top:18px; text-align:center; color:#a08; font-size:12px; }}
  .foot b {{ color:var(--dark); }}
  .foot .meme {{ font-size:13px; color:#666; margin-top:4px; }}
</style></head>
<body><div class="card">
  <div class="head">
    <div class="logo">🍟🐑</div>
    <h1>今日麦门羊毛战报</h1>
    <div class="date">{r['date']} · McWool 自动生成</div>
    {demo_badge}
  </div>
  <div class="body">
    <div class="big">
      <div class="stat"><div class="k">持有优惠券</div><div class="v">{len(r['coupons'])} 张</div></div>
      <div class="stat"><div class="k">券面额合计</div><div class="v">¥{r['coupon_total']}</div></div>
    </div>
    <div class="big" style="margin-top:14px">{pts}</div>
    {expiring_html}
    <h2>🎫 我的券包</h2>
    <table>{rows}</table>
    <div class="foot">
      <div class="meme">麦门永存 🙏 攒券一时爽，一直攒券一直爽</div>
      <div style="margin-top:6px">由 <b>McWool 麦门羊毛代理人</b> 生成 · GitHub 搜索 <b>McWool</b></div>
    </div>
  </div>
</div></body></html>"""
        pathlib.Path(path).write_text(html, encoding="utf-8")
        return path


# ---------------------------------------------------------------- 命令入口


def load_token(args) -> str | None:
    if getattr(args, "token", None):
        return args.token
    env = os.environ.get("MCD_MCP_TOKEN")
    if env:
        return env
    f = pathlib.Path.home() / ".mcwool_token"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return None


def make_client(args) -> McdMCPClient | None:
    token = load_token(args)
    if not token:
        print(red("未找到麦当劳 MCP Token。"))
        print("  三种方式任选其一：")
        print("  1) python mcwool.py <命令> --token YOUR_TOKEN")
        print("  2) set MCD_MCP_TOKEN=YOUR_TOKEN")
        print("  3) 把 Token 存入文件 ~/.mcwool_token")
        print(f"\n  Token 免费申请（1 分钟）: {cyan(TOKEN_HELP_URL)}")
        print("  登录 → 控制台 → 激活 → 一键复制\n")
        print(dim("  或先用演示模式体验: python mcwool.py daily --demo"))
        return None
    return McdMCPClient(token)


def cmd_daily(args):
    wool = McWool(None, demo=args.demo) if args.demo else McWool(make_client(args))
    if not args.demo and wool.client is None:
        sys.exit(1)
    print(BANNER)
    print(f"  {LOGO}\n")
    if args.demo:
        print(dim("  ▶ 演示模式：以下为内置样例数据，配置 Token 后为真实数据\n"))
    coupons = wool.do_claim()
    points = wool.do_points()
    r = wool.build_report(coupons, points)
    wool.print_report(r)
    path = wool.save_report_html(r)
    print(green(f"\n📸 战报卡片已生成: {path}（浏览器打开即可截图分享）"))
    try:
        import webbrowser
        webbrowser.open(pathlib.Path(path).resolve().as_uri())
    except Exception:
        pass


def cmd_claim(args):
    wool = McWool(None, demo=args.demo) if args.demo else McWool(make_client(args))
    if not args.demo and wool.client is None:
        sys.exit(1)
    print(f"  {LOGO}\n")
    wool.do_claim(quiet=False)
    wool.do_coupons()


def cmd_coupons(args):
    wool = McWool(None, demo=args.demo) if args.demo else McWool(make_client(args))
    if not args.demo and wool.client is None:
        sys.exit(1)
    wool.do_coupons()


def cmd_points(args):
    wool = McWool(None, demo=args.demo) if args.demo else McWool(make_client(args))
    if not args.demo and wool.client is None:
        sys.exit(1)
    wool.do_points()


def cmd_lottery(args):
    wool = McWool(None, demo=args.demo) if args.demo else McWool(make_client(args))
    if not args.demo and wool.client is None:
        sys.exit(1)
    info = wool.do_lottery_info()
    if args.draw:
        if args.draw > 10:
            print(red("  单次最多自动抽 10 次（积分要省着花）"))
            args.draw = 10
        wool.do_lottery_draw(args.draw)


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--token", help="麦当劳 MCP Token（也可用环境变量 MCD_MCP_TOKEN）")
    common.add_argument("--demo", action="store_true", help="演示模式：无需 Token，内置样例数据")
    parser = argparse.ArgumentParser(
        prog="mcwool",
        description="🍟 McWool 麦门羊毛代理人 — 一键领券 / 积分看护 / 自动抽奖 / 羊毛战报",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("daily", help="每日例行：领券 + 积分 + 战报卡片", parents=[common])
    p.set_defaults(func=cmd_daily)

    p = sub.add_parser("claim", help="一键领取麦麦省所有可领优惠券", parents=[common])
    p.set_defaults(func=cmd_claim)

    p = sub.add_parser("coupons", help="查看我持有的优惠券", parents=[common])
    p.set_defaults(func=cmd_coupons)

    p = sub.add_parser("points", help="查询积分账户", parents=[common])
    p.set_defaults(func=cmd_points)

    p = sub.add_parser("lottery", help="积分抽奖（--draw N 自动抽 N 次）", parents=[common])
    p.add_argument("--draw", type=int, default=0, help="自动抽奖次数（消耗积分！）")
    p.set_defaults(func=cmd_lottery)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        # 默认执行每日例行
        args.func = cmd_daily
        args.command = "daily"
    try:
        args.func(args)
    except McdMCPError as e:
        print(red(f"\n✖ {e}"))
        sys.exit(1)
    except KeyboardInterrupt:
        print(dim("\n麦门永存，下次再薅 🙏"))
        sys.exit(0)


if __name__ == "__main__":
    main()
