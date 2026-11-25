"""流水序缺口 · 序缺口闸核心。

全局只贯彻一种正确性口径，默认且唯一出厂口径为 **乙 · 旁置日终镜为准**：

* 有序号轨的账户，缺口（或缺号/重号）未解除前，禁止写「状态=有效」的正式日镜；
* 抽取可写「状态=旁置」的旁置日终镜（周期快照一行 + 旁置日终镜投影 + 旁置簿留痕），
  旁置镜非有效、绝不能作为回放权威；
* 补序后缺口闭合，必须显式调用「晋升」，按补齐后的全量流水重算余额，旁置→正式；
* 未晋升的旁置镜被回放当有效通过，一律拒绝。

口径 **甲 · 缺口登记阻塞为准** 仅能通过台参「序缺口口径」或环境变量
``序缺口口径`` / ``DAYSNAP_SEQ_GAP_POLICY`` 显式整库切换（同一时刻全局一种）：
未解除缺口则该户抽取整拒，不写正式镜也不写旁置日终镜，只落序缺口登记；
补序后重新抽取方得正式镜。

两种口径下，核证接口的 ``旁置有无`` / ``正式有无`` / ``可否晋升`` / ``valid``
都必须把「旁置日终是否可读、正式有效是否为空」区分清楚。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from app.db import 开始立即事务
from app.services.时间 import 此刻, 标准化营业日

启用 = True

口径_旁置 = "旁置日终镜"
口径_阻塞 = "登记阻塞"
默认口径 = 口径_旁置

_旁置别名 = {"旁置", "旁置日终", "旁置日终镜", "乙", "b", "B", "side", "SIDE"}
_阻塞别名 = {"阻塞", "登记阻塞", "缺口登记阻塞", "甲", "a", "A", "block", "reject", "BLOCK"}

序号键候选 = ("序号", "流水序号", "序列", "序", "seq_no", "seqno", "seq", "sequence", "sn")

旁置原因 = "序缺口旁置日终"


class 序号非法(ValueError):
    """序号字段存在但无法解析为整数序号。"""


def 说明() -> str:
    return "流水序缺口：序号轨核证 / 缺口登记 / 旁置日终镜 / 补序后显式晋升，禁止残缺正式镜"


def 规范口径(值: Any = None) -> str:
    s = str(值 or "").strip()
    if s in _阻塞别名:
        return 口径_阻塞
    if s in _旁置别名:
        return 口径_旁置
    return 默认口径


def 当前口径(参: dict | None = None) -> str:
    """全局口径：环境变量优先，其次台参，最后出厂默认（旁置日终镜）。"""
    env = os.environ.get("序缺口口径") or os.environ.get("DAYSNAP_SEQ_GAP_POLICY")
    if env:
        return 规范口径(env)
    if 参 is None:
        from app.db import 连接

        conn = 连接()
        try:
            参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
        finally:
            conn.close()
    return 规范口径((参 or {}).get("序缺口口径") or 默认口径)


def 解析序号(raw: dict[str, Any]):
    """从一条流水事件里宽容取序号；缺省返回 None（该户可不走序号轨），非法抛错。"""
    for k in 序号键候选:
        if k in raw and raw[k] is not None and str(raw[k]).strip() != "":
            v = raw[k]
            if isinstance(v, bool):
                raise 序号非法(f"序号非法: {v!r}")
            if isinstance(v, float):
                if not v.is_integer():
                    raise 序号非法(f"序号非法: {v!r}")
                return int(v)
            try:
                return int(str(v).strip())
            except (TypeError, ValueError) as e:
                raise 序号非法(f"序号非法: {v!r}") from e
    return None


def 区间缺口(序号们) -> list[list[int]]:
    """把有序序号列里的空洞压成闭区间 [起, 止] 列表。

    只认已观测最小/最大序号之间的内洞：[1,3] -> [[2,2]]。
    用相邻项比较，避免超大序号跨度触发 range 爆炸。
    """
    vals = sorted({int(x) for x in 序号们 if x is not None})
    gaps: list[list[int]] = []
    for a, b in zip(vals, vals[1:]):
        if b - a > 1:
            gaps.append([a + 1, b - 1])
    return gaps


def 重号集合(序号们) -> list[int]:
    seen: set[int] = set()
    dup: set[int] = set()
    for x in 序号们:
        if x is None:
            continue
        n = int(x)
        if n in seen:
            dup.add(n)
        seen.add(n)
    return sorted(dup)


def 观测轨(conn, 账户键: str) -> dict[str, Any]:
    """读某账户全局序号轨（序号跨营业日连续），并附分日缺口。"""
    rows = conn.execute(
        "SELECT 序号, 营业日, 流水号 FROM 变动流水 "
        "WHERE 账户键=? AND 命运='已入账' AND 序号 IS NOT NULL ORDER BY 序号, 流水号",
        (账户键,),
    ).fetchall()
    全局 = [r["序号"] for r in rows]
    分日原始: dict[str, list[int]] = {}
    for r in rows:
        分日原始.setdefault(r["营业日"], []).append(r["序号"])
    缺口 = 区间缺口(全局)
    重号 = 重号集合(全局)
    在轨 = len(全局) > 0
    连续 = 在轨 and not 缺口 and not 重号
    return {
        "账户键": 账户键,
        "序号轨": 在轨,
        "序号集合": sorted({int(x) for x in 全局}),
        "最大序号": max((int(x) for x in 全局), default=None),
        "流水数": len(全局),
        "缺口区间": 缺口,
        "缺口数": sum(b - a + 1 for a, b in 缺口),
        "重号": 重号,
        "连续": 连续,
        "分日": {
            d: {"序号集合": sorted({int(x) for x in v}), "缺口区间": 区间缺口(v)}
            for d, v in sorted(分日原始.items())
        },
    }


def 读镜态(conn, 账户键: str, 营业日: str) -> dict[str, Any]:
    正式 = conn.execute(
        "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
        (账户键, 营业日),
    ).fetchone()
    旁 = conn.execute(
        "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='旁置'",
        (账户键, 营业日),
    ).fetchone()
    投影 = conn.execute(
        "SELECT * FROM 旁置日终镜 WHERE 账户键=? AND 营业日=? AND 状态='旁置'",
        (账户键, 营业日),
    ).fetchone()
    return {"正式": 正式, "旁": 旁, "投影": 投影}


def 核证(conn=None, 账户键: str = "", 营业日: str = "", 参: dict | None = None) -> dict[str, Any]:
    """序缺口核证接口：缺口区间 / 旁置有无 / 可否晋升 / valid。

    可传入调用方事务里的 conn（与抽取/晋升同票读到一致状态）；不传则自管只读连接。
    """
    自管 = conn is None
    if 自管:
        from app.db import 连接

        conn = 连接()
    try:
        日 = 标准化营业日(营业日) if str(营业日 or "").strip() else ""
        口径名 = 当前口径(参)
        obs = 观测轨(conn, 账户键) if 账户键 else None
        if 日:
            镜 = 读镜态(conn, 账户键, 日)
            正式有无 = 镜["正式"] is not None
            旁置有无 = (镜["旁"] is not None) or (镜["投影"] is not None)
            正式余额 = int(镜["正式"]["余额"]) if 镜["正式"] is not None else None
            旁置余额 = (
                int(镜["旁"]["余额"])
                if 镜["旁"] is not None
                else (int(镜["投影"]["余额"]) if 镜["投影"] is not None else None)
            )
        else:
            正式有无 = False
            旁置有无 = False
            正式余额 = None
            旁置余额 = None

        在轨 = bool(obs and obs["序号轨"])
        轨完整 = bool(obs and obs["连续"])
        缺口 = obs["缺口区间"] if obs else []
        重号 = obs["重号"] if obs else []

        # 可否晋升：乙口径下，确有未晋升旁置镜，且当前序号轨已补全。
        可否晋升 = bool(日 and 旁置有无 and 轨完整)
        # valid：有正式有效镜，且若在序号轨上则必须连续无缺口。
        valid = bool(正式有无 and (not 在轨 or 轨完整))

        登记 = None
        if 账户键 and 日:
            r = conn.execute(
                "SELECT * FROM 序缺口登记 WHERE 账户键=? AND 营业日=? ORDER BY 编号 DESC LIMIT 1",
                (账户键, 日),
            ).fetchone()
            if r is not None:
                登记 = dict(r)
                try:
                    登记["缺口区间"] = json.loads(登记.get("缺口区间") or "[]")
                    登记["重号"] = json.loads(登记.get("重号") or "[]")
                except Exception:
                    pass

        return {
            "账户键": 账户键,
            "营业日": 日,
            "口径": 口径名,
            # —— 规格点名的四个核证字段 ——
            "缺口区间": 缺口,
            "旁置有无": 旁置有无,
            "可否晋升": 可否晋升,
            "valid": valid,
            # —— 其余可区分状态 ——
            "序号轨": 在轨,
            "连续": 轨完整,
            "重号": 重号,
            "缺口数": obs["缺口数"] if obs else 0,
            "序号集合": obs["序号集合"] if obs else [],
            "正式有无": 正式有无,
            "正式余额": 正式余额,
            "旁置余额": 旁置余额,
            "正式有效为空": not 正式有无,
            "晋升动作": "POST /api/晋升" if 可否晋升 else "",
            "登记": 登记,
            # 英文别名，方便不同调用方
            "gaps": 缺口,
            "hasSideMirror": 旁置有无,
            "canPromote": 可否晋升,
            "policy": 口径名,
        }
    finally:
        if 自管:
            conn.close()


def _前日(营业日: str) -> str:
    from datetime import date, timedelta

    y, m, d = map(int, 营业日.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def 重算日镜(conn, 账户键: str, 日: str) -> tuple[int, int, int]:
    """按「前日有效镜（或缺前日策略零开端）+ 当日全部已入账流水净额」重算。"""
    参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
    缺前日 = 参.get("缺前日策略", "以零为开端")
    户 = conn.execute("SELECT 开户营业日 FROM 账户 WHERE 账户键=?", (账户键,)).fetchone()
    开户日 = 户["开户营业日"] if 户 is not None else 日
    前 = _前日(日)
    前日 = conn.execute(
        "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
        (账户键, 前),
    ).fetchone()
    if 前日 is not None:
        开端 = int(前日["余额"])
    elif 日 == 开户日 or 缺前日 == "以零为开端":
        开端 = 0
    else:
        开端 = 0
    净额 = int(
        conn.execute(
            "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
            "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
            (账户键, 日),
        ).fetchone()["s"]
    )
    return 开端, 净额, 开端 + 净额


def 落缺口处置(
    conn,
    *,
    账户键: str,
    日: str,
    批: str,
    口径名: str,
    缺口: list,
    重号: list,
    余额: int,
    开端: int,
    净额: int,
) -> dict[str, Any]:
    """在调用方事务内落「缺口登记」，乙口径再落旁置日终镜与旁置簿留痕。同票成败。"""
    ts = 此刻()
    区间json = json.dumps(缺口, ensure_ascii=False)
    重号json = json.dumps(重号, ensure_ascii=False)
    快照键 = f"{账户键}|{日}"

    旧登 = conn.execute(
        "SELECT 编号 FROM 序缺口登记 WHERE 账户键=? AND 营业日=? AND 状态='未解除' "
        "ORDER BY 编号 DESC LIMIT 1",
        (账户键, 日),
    ).fetchone()
    if 旧登 is not None:
        conn.execute(
            "UPDATE 序缺口登记 SET 缺口区间=?, 缺口数=?, 重号=?, 口径=?, 旁置快照键=?, "
            "检出批次编号=?, 更新时刻=? WHERE 编号=?",
            (区间json, sum(b - a + 1 for a, b in 缺口), 重号json, 口径名,
             快照键 if 口径名 == 口径_旁置 else "", 批, ts, 旧登["编号"]),
        )
        登记编号 = 旧登["编号"]
    else:
        cur = conn.execute(
            "INSERT INTO 序缺口登记(账户键, 营业日, 缺口区间, 缺口数, 重号, 状态, 口径, "
            "旁置快照键, 检出批次编号, 时刻, 更新时刻) VALUES (?,?,?,?,?,'未解除',?,?,?,?,?)",
            (账户键, 日, 区间json, sum(b - a + 1 for a, b in 缺口), 重号json, 口径名,
             快照键 if 口径名 == 口径_旁置 else "", 批, ts, ts),
        )
        登记编号 = cur.lastrowid

    写旁置镜 = 0
    if 口径名 == 口径_旁置:
        旧镜 = conn.execute(
            "SELECT 快照键 FROM 周期快照 WHERE 账户键=? AND 营业日=?", (账户键, 日)
        ).fetchone()
        if 旧镜 is not None:
            # 关键：即便此前误有「有效」行，缺口未解除也一律降为旁置，绝不容残缺正式镜。
            conn.execute(
                "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='序缺口旁置日终', 状态='旁置' "
                "WHERE 账户键=? AND 营业日=?",
                (余额, 批, 账户键, 日),
            )
        else:
            conn.execute(
                "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
                "VALUES (?,?,?,?,?, '序缺口旁置日终', '旁置')",
                (快照键, 账户键, 日, 余额, 批),
            )
        写旁置镜 = 1

        旧投影 = conn.execute(
            "SELECT 快照键 FROM 旁置日终镜 WHERE 快照键=?", (快照键,)
        ).fetchone()
        if 旧投影 is not None:
            conn.execute(
                "UPDATE 旁置日终镜 SET 余额=?, 开端余额=?, 流水净额=?, 缺口区间=?, 状态='旁置', "
                "抽取批次编号=?, 时刻=?, 晋升批次编号='', 晋升时刻='' WHERE 快照键=?",
                (余额, 开端, 净额, 区间json, 批, ts, 快照键),
            )
        else:
            conn.execute(
                "INSERT INTO 旁置日终镜(快照键, 账户键, 营业日, 余额, 开端余额, 流水净额, "
                "缺口区间, 状态, 抽取批次编号, 时刻) VALUES (?,?,?,?,?,?,?, '旁置', ?, ?)",
                (快照键, 账户键, 日, 余额, 开端, 净额, 区间json, 批, ts),
            )

        已有簿 = conn.execute(
            "SELECT 编号 FROM 旁置簿 WHERE 原因=? AND 账户键=? AND 营业日=?",
            (旁置原因, 账户键, 日),
        ).fetchone()
        if 已有簿 is None:
            conn.execute(
                "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                (
                    旁置原因,
                    账户键,
                    日,
                    json.dumps(
                        {
                            "快照键": 快照键,
                            "余额": 余额,
                            "开端余额": 开端,
                            "流水净额": 净额,
                            "缺口区间": 缺口,
                            "重号": 重号,
                            "说明": "序号轨有缺口，此为旁置日终镜，非有效、不得作为回放权威；补序后须显式晋升",
                        },
                        ensure_ascii=False,
                    ),
                    ts,
                ),
            )

    return {"登记编号": 登记编号, "旁置日终": 写旁置镜}


def 补序后闭合登记(conn, 账户键: str) -> None:
    """装载事务内调用：按最新序号轨收缩/闭合该户所有未解除缺口登记。"""
    obs = 观测轨(conn, 账户键)
    ts = 此刻()
    rows = conn.execute(
        "SELECT 编号, 缺口区间 FROM 序缺口登记 WHERE 账户键=? AND 状态='未解除'",
        (账户键,),
    ).fetchall()
    for r in rows:
        if obs["连续"]:
            conn.execute(
                "UPDATE 序缺口登记 SET 状态='已闭合', 缺口区间='[]', 缺口数=0, 重号='[]', "
                "更新时刻=?, 解除时刻=? WHERE 编号=?",
                (ts, ts, r["编号"]),
            )
        else:
            conn.execute(
                "UPDATE 序缺口登记 SET 缺口区间=?, 缺口数=?, 重号=?, 更新时刻=? WHERE 编号=?",
                (
                    json.dumps(obs["缺口区间"], ensure_ascii=False),
                    obs["缺口数"],
                    json.dumps(obs["重号"], ensure_ascii=False),
                    ts,
                    r["编号"],
                ),
            )


def 晋升旁置(账户键: str, 营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """显式晋升：核缺口已补全 → 按全量流水重算 → 旁置转正式有效。失败闭。"""
    日 = 标准化营业日(营业日)
    账户键 = (账户键 or "").strip()
    if not 账户键:
        raise ValueError("账户键不能为空")
    批 = (批次编号 or "").strip() or f"晋升-{日}-{uuid.uuid4().hex[:8]}"

    from app.db import 连接

    conn = 连接()
    try:
        开始立即事务(conn)
        参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
        口径名 = 当前口径(参)
        obs = 观测轨(conn, 账户键)
        if obs["序号轨"] and not obs["连续"]:
            raise ValueError(
                f"序缺口未补全，禁止晋升/写正式镜：{账户键} {日} 缺口={obs['缺口区间']} 重号={obs['重号']}"
            )

        镜 = 读镜态(conn, 账户键, 日)
        开端, 净额, 余额 = 重算日镜(conn, 账户键, 日)
        快照键 = f"{账户键}|{日}"
        ts = 此刻()

        if 镜["旁"] is not None or 镜["投影"] is not None:
            # 乙口径正路：旁置 → 有效，余额以补齐后的全量流水重算为准。
            conn.execute(
                "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='补序晋升正式', 状态='有效' "
                "WHERE 账户键=? AND 营业日=?",
                (余额, 批, 账户键, 日),
            )
            conn.execute(
                "UPDATE 旁置日终镜 SET 余额=?, 开端余额=?, 流水净额=?, 状态='已晋升', "
                "晋升批次编号=?, 晋升时刻=? WHERE 快照键=?",
                (余额, 开端, 净额, 批, ts, 快照键),
            )
            动作 = "旁置晋升正式"
        elif 镜["正式"] is not None:
            # 已晋升/已有正式：幂等核证返回，不重复造镜。
            动作 = "早已正式有效"
        else:
            if 口径名 == 口径_旁置:
                raise ValueError(f"无旁置日终镜可晋升：{账户键} {日}（请先执行日终抽取）")
            # 甲口径本无旁置：缺口已闭合时，晋升动作等价于当场写正式镜。
            conn.execute(
                "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
                "VALUES (?,?,?,?,?, '补序后抽取正式', '有效')",
                (快照键, 账户键, 日, 余额, 批),
            )
            动作 = "阻塞口径补写正式"

        conn.execute(
            "UPDATE 序缺口登记 SET 状态='已晋升', 缺口区间='[]', 缺口数=0, 重号='[]', "
            "更新时刻=?, 解除时刻=? WHERE 账户键=? AND 营业日=? AND 状态 IN ('未解除','已闭合')",
            (ts, ts, 账户键, 日),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "批次编号": 批,
        "动作": 动作,
        "账户键": 账户键,
        "营业日": 日,
        "余额": 余额,
        "开端余额": 开端,
        "流水净额": 净额,
        "核证": 核证(账户键=账户键, 营业日=日),
    }
