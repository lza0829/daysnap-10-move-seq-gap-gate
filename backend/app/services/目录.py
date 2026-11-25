from app.db import 连接


def 总览() -> dict:
    conn = 连接()
    try:
        def 数(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "账户数": 数("SELECT COUNT(*) FROM 账户"),
            "流水数": 数("SELECT COUNT(*) FROM 变动流水 WHERE 命运='已入账'"),
            "快照数": 数("SELECT COUNT(*) FROM 周期快照 WHERE 状态='有效'"),
            "旁置镜数": 数("SELECT COUNT(*) FROM 周期快照 WHERE 状态='旁置'"),
            "差额行数": 数("SELECT COUNT(*) FROM 差额行"),
            "断档数": 数("SELECT COUNT(*) FROM 断档记录"),
            "跳变数": 数("SELECT COUNT(*) FROM 跳变记录"),
            "旁置数": 数("SELECT COUNT(*) FROM 旁置簿"),
            "序缺口未解除数": 数("SELECT COUNT(*) FROM 序缺口登记 WHERE 状态='未解除'"),
            "旁置日终未晋升数": 数("SELECT COUNT(*) FROM 旁置日终镜 WHERE 状态='旁置'"),
            "抽取批次数": 数("SELECT COUNT(*) FROM 抽取批次"),
            "回放批次数": 数("SELECT COUNT(*) FROM 回放批次"),
        }
    finally:
        conn.close()
