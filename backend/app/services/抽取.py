import json
import uuid
from typing import Any

from app.db import 开始立即事务, 连接
from app.modules import 流水序缺口 as 序闸
from app.services.时间 import 此刻, 标准化营业日


def _台参(conn) -> dict[str, str]:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}


def _前日(营业日: str) -> str:
    y, m, d = map(int, 营业日.split("-"))
    from datetime import date, timedelta

    return (date(y, m, d) - timedelta(days=1)).isoformat()


def 日终抽取(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """按营业日为全部正常账户写周期快照。余额=前日快照(或开户零)+当日流水净额。

    序缺口闸：在序号轨上且存在缺口/重号的账户，禁止写「有效」正式镜。
    乙口径写旁置日终镜待晋升；甲口径整拒该户、不落任何日终镜。
    多户批次互不连坐：完整户照抽，缺口户在报告里如实记拒，整批 通过=false。
    """
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"抽取-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        开始立即事务(conn)
        参 = _台参(conn)
        口径名 = 序闸.当前口径(参)
        重复 = 参.get("重复抽取", "盖写同日快照")
        缺前日 = 参.get("缺前日策略", "以零为开端")
        账户们 = [
            dict(r)
            for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常' ORDER BY 账户键")
        ]
        写入 = 0
        盖写 = 0
        旁置 = 0
        断档数 = 0
        旁置日终 = 0
        序缺口数 = 0
        缺口账户: list[dict[str, Any]] = []
        应镜 = 0
        for 户 in 账户们:
            账户键 = 户["账户键"]
            开户日 = 户["开户营业日"]
            if 日 < 开户日:
                continue
            应镜 += 1

            obs = 序闸.观测轨(conn, 账户键)
            轨坏 = bool(obs["序号轨"] and (obs["缺口区间"] or obs["重号"]))
            if 轨坏:
                前 = _前日(日)
                前日快照 = conn.execute(
                    "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                    (账户键, 前),
                ).fetchone()
                开端 = int(前日快照["余额"]) if 前日快照 is not None else 0
                净额 = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
                        "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
                        (账户键, 日),
                    ).fetchone()["s"]
                )
                余额 = 开端 + 净额
                处置 = 序闸.落缺口处置(
                    conn,
                    账户键=账户键,
                    日=日,
                    批=批,
                    口径名=口径名,
                    缺口=obs["缺口区间"],
                    重号=obs["重号"],
                    余额=余额,
                    开端=开端,
                    净额=净额,
                )
                序缺口数 += 1
                if 处置["旁置日终"]:
                    旁置日终 += 1
                缺口账户.append(
                    {
                        "账户键": 账户键,
                        "缺口区间": obs["缺口区间"],
                        "重号": obs["重号"],
                        "口径": 口径名,
                        "处置": "旁置日终镜待晋升" if 口径名 == 序闸.口径_旁置 else "整拒·无日终镜",
                        "旁置日终": 处置["旁置日终"] == 1,
                        "残缺净额": 余额,
                    }
                )
                continue

            前 = _前日(日)
            前日快照 = conn.execute(
                "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效'",
                (账户键, 前),
            ).fetchone()
            if 前日快照 is None:
                if 日 == 开户日 or 缺前日 == "以零为开端":
                    开端 = 0
                else:
                    conn.execute(
                        "INSERT INTO 断档记录(账户键, 缺营业日, 检出批次编号, 处置, 时刻) VALUES (?,?,?,?,?)",
                        (账户键, 前, 批, "记断档并继续", 此刻()),
                    )
                    断档数 += 1
                    开端 = 0
            else:
                开端 = int(前日快照["余额"])
            净额行 = conn.execute(
                "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
                "WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
                (账户键, 日),
            ).fetchone()
            净额 = int(净额行["s"])
            余额 = 开端 + 净额
            快照键 = f"{账户键}|{日}"
            旧 = conn.execute(
                "SELECT 快照键, 状态 FROM 周期快照 WHERE 账户键=? AND 营业日=?",
                (账户键, 日),
            ).fetchone()
            if 旧:
                if 旧["状态"] == "旁置":
                    # 缺口已补但尚未显式晋升：重抽只刷新旁置镜，绝不自动转有效。
                    conn.execute(
                        "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='序缺口旁置日终', 状态='旁置' "
                        "WHERE 账户键=? AND 营业日=?",
                        (余额, 批, 账户键, 日),
                    )
                    conn.execute(
                        "UPDATE 旁置日终镜 SET 余额=?, 开端余额=?, 流水净额=?, 缺口区间='[]', "
                        "抽取批次编号=? WHERE 快照键=? AND 状态='旁置'",
                        (余额, 开端, 净额, 批, 快照键),
                    )
                    旁置日终 += 1
                    缺口账户.append(
                        {
                            "账户键": 账户键,
                            "缺口区间": [],
                            "口径": 口径名,
                            "处置": "缺口已闭合·旁置镜已刷新，待显式晋升",
                            "旁置日终": True,
                            "可晋升": True,
                        }
                    )
                    continue
                if 重复 != "盖写同日快照":
                    conn.execute(
                        "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        (
                            "同日已有快照",
                            账户键,
                            日,
                            json.dumps({"余额": 余额}, ensure_ascii=False),
                            此刻(),
                        ),
                    )
                    旁置 += 1
                    continue
                conn.execute(
                    "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='日终抽取', 状态='有效' "
                    "WHERE 账户键=? AND 营业日=?",
                    (余额, 批, 账户键, 日),
                )
                盖写 += 1
            else:
                conn.execute(
                    "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 状态) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (快照键, 账户键, 日, 余额, 批, "日终抽取", "有效"),
                )
                写入 += 1
        # 全有效：每个应镜户都有「有效」镜，且没有序缺口拒绝。缺口户不得拖成整批假成功。
        有效数 = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM 周期快照 s JOIN 账户 a ON a.账户键=s.账户键 "
                "WHERE s.营业日=? AND s.状态='有效' AND ? >= a.开户营业日 AND a.状态='正常'",
                (日, 日),
            ).fetchone()["c"]
        )
        全有效 = 序缺口数 == 0 and 有效数 >= 应镜
        报告 = {
            "营业日": 日,
            "写入": 写入,
            "盖写": 盖写,
            "旁置": 旁置,
            "旁置日终": 旁置日终,
            "序缺口": 序缺口数,
            "拒绝": 序缺口数,
            "缺口账户": 缺口账户,
            "断档": 断档数,
            "账户扫描": len(账户们),
            "应镜": 应镜,
            "有效镜数": 有效数,
            "全有效": 全有效,
            "通过": 全有效,
            "口径": 口径名,
        }
        conn.execute(
            "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
            (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return {"批次编号": 批, **报告}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
