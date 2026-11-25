import json
import uuid
from typing import Any

from app.db import 开始立即事务, 连接
from app.modules import 流水序缺口 as 序闸
from app.services.时间 import 此刻, 标准化营业日


def _前日(营业日: str) -> str:
    y, m, d = map(int, 营业日.split("-"))
    from datetime import date, timedelta

    return (date(y, m, d) - timedelta(days=1)).isoformat()


def 回放核对(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """用前日有效快照+当日流水重算，对照当日「有效」周期快照，写入差额/跳变。

    序缺口闸：旁置日终镜绝不是回放权威；无有效正式镜（或缺号未解除）一律拒绝通过，
    并落差额行。缺口登记补写与差额行、回放批次同票提交。
    """
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"回放-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        开始立即事务(conn)
        参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
        try:
            阈值 = int(参.get("跳变阈值分", "0") or "0")
        except ValueError:
            阈值 = 0
        账户们 = [dict(r) for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常'")]
        相符 = 0
        差额数 = 0
        跳变数 = 0
        无快照 = 0
        序缺口拒绝 = 0
        for 户 in 账户们:
            账户键 = 户["账户键"]
            if 日 < 户["开户营业日"]:
                continue
            obs = 序闸.观测轨(conn, 账户键)
            轨坏 = bool(obs["序号轨"] and (obs["缺口区间"] or obs["重号"]))
            快照 = conn.execute(
                "SELECT 余额, 状态 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                (账户键, 日),
            ).fetchone()
            旁镜 = conn.execute(
                "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='旁置'",
                (账户键, 日),
            ).fetchone()

            if not 快照:
                无快照 += 1
                if 轨坏 or 旁镜 is not None:
                    序缺口拒绝 += 1
                    # 同票确保缺口登记在册（回放也可首次检出）。
                    if 轨坏:
                        序闸.落缺口处置(
                            conn,
                            账户键=账户键,
                            日=日,
                            批=批,
                            口径名=序闸.当前口径(参),
                            缺口=obs["缺口区间"],
                            重号=obs["重号"],
                            余额=int(旁镜["余额"]) if 旁镜 is not None else 0,
                            开端=0,
                            净额=0,
                        )
                    if 轨坏 and 旁镜 is not None:
                        原因 = "序缺口未补：仅有旁置日终镜且序号仍缺，非回放权威，全量回放拒绝"
                    elif 旁镜 is not None:
                        原因 = "旁置日终镜未显式晋升为正式有效，不得作为回放通过依据，回放拒绝"
                    else:
                        原因 = "序缺口未解除：正式有效镜为空，按缺镜规则回放拒绝"
                else:
                    原因 = "缺当日快照"
                conn.execute(
                    "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (批, 账户键, 日, None, None, 0, 原因, 此刻()),
                )
                差额数 += 1
                continue

            # 防御性失败闭：即便存在「有效」行，只要序号轨仍坏，也不予承认。
            if 轨坏:
                序缺口拒绝 += 1
                conn.execute(
                    "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        批, 账户键, 日, int(快照["余额"]), None, 0,
                        "序缺口未解除：正式镜连续性不可信，回放拒绝", 此刻(),
                    ),
                )
                差额数 += 1
                continue

            前 = _前日(日)
            前日快照 = conn.execute(
                "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                (账户键, 前),
            ).fetchone()
            开端 = 0 if 前日快照 is None else int(前日快照["余额"])
            净额 = int(
                conn.execute(
                    "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
                    "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
                    (账户键, 日),
                ).fetchone()["s"]
            )
            回放余额 = 开端 + 净额
            快照余额 = int(快照["余额"])
            差额 = 快照余额 - 回放余额
            if 差额 == 0:
                相符 += 1
            else:
                conn.execute(
                    "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (批, 账户键, 日, 快照余额, 回放余额, 差额, "快照与回放不一致", 此刻()),
                )
                差额数 += 1
            偏离 = abs(快照余额 - (开端 + 净额))
            if 阈值 > 0 and 偏离 >= 阈值:
                conn.execute(
                    "INSERT INTO 跳变记录(账户键, 营业日, 前日余额, 当日余额, 流水净额, 偏离, 检出批次编号, 时刻) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (账户键, 日, 开端, 快照余额, 净额, 偏离, 批, 此刻()),
                )
                跳变数 += 1
        通过 = 差额数 == 0 and 无快照 == 0 and 序缺口拒绝 == 0
        报告 = {
            "营业日": 日,
            "相符": 相符,
            "差额": 差额数,
            "跳变": 跳变数,
            "无快照": 无快照,
            "序缺口拒绝": 序缺口拒绝,
            "拒绝": 序缺口拒绝,
            "通过": 通过,
        }
        conn.execute(
            "INSERT INTO 回放批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
            (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return {"批次编号": 批, **报告}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
