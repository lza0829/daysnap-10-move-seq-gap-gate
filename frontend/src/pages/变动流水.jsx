import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

export default function 变动流水() {
  const [夹具, set夹具] = useState([]);
  const [选, set选] = useState("序缺口_缺号样例.json");
  const [行, set行] = useState([]);
  const [核, set核] = useState({});
  const [讯, set讯] = useState("");

  const 刷新 = async () => {
    set行(await api.流水());
    set夹具(await api.夹具());
    try {
      const all = await api.核证序缺口("", "");
      const map = {};
      (all.明细 || []).forEach((d) => {
        map[d.账户键] = d;
      });
      set核(map);
    } catch {
      set核({});
    }
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  const 缺口户 = useMemo(
    () => new Set(Object.values(核).filter((d) => d.序号轨 && (d.缺口区间 || []).length).map((d) => d.账户键)),
    [核]
  );

  const 快装 = (名) =>
    api
      .装载夹具(名)
      .then((r) => set讯(`已装 ${名}：入账=${r.入账} 旁置=${r.旁置}`))
      .then(刷新)
      .catch((e) => set讯(String(e.message || e)));

  return (
    <div>
      <h1 className="题">变动流水 · 序号轨</h1>
      <p className="述">
        装入账户增减流水。带「序号」的账户进入流水序号轨：序号出现空洞（如 1、3 缺 2）时，
        缺口未解除前禁止写有效正式日镜。空洞在此如实标红，不会只在前端隐藏。
      </p>
      <div className="行">
        <select value={选} onChange={(e) => set选(e.target.value)}>
          {夹具.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
        <button
          onClick={() =>
            api
              .装载夹具(选)
              .then((r) => set讯(`装载完成 入账=${r.入账} 旁置=${r.旁置}`))
              .then(刷新)
              .catch((e) => set讯(String(e.message || e)))
          }
        >
          装载夹具
        </button>
        <button className="次" onClick={() => 快装("序缺口_缺号样例.json")}>装缺号1·3</button>
        <button className="水" onClick={() => 快装("序缺口_补2样例.json")}>补序号2</button>
        <button className="次" onClick={() => 快装("序缺口_多户混合样例.json")}>多户混合</button>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}
      {缺口户.size ? (
        <div className="提示条">
          检测到序号缺口账户：{[...缺口户].join("、")}。这些户在补序闭合前不得落有效正式镜；请到
          「③ 日终抽取」或「序缺口闸」处置。
        </div>
      ) : null}
      {!行.length ? (
        <div className="空态">暂无流水</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>序号</th>
              <th>流水号</th>
              <th>账户键</th>
              <th>营业日</th>
              <th>变动额</th>
              <th>摘要</th>
              <th>命运</th>
              <th>序号轨</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => {
              const d = 核[r.账户键];
              const 坏 = d && d.序号轨 && (d.缺口区间 || []).length;
              return (
                <tr key={r.流水号}>
                  <td style={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>
                    {r.序号 ?? r.流水序号 ?? "—"}
                  </td>
                  <td>{r.流水号}</td>
                  <td>{r.账户键}</td>
                  <td>{r.营业日}</td>
                  <td>{r.变动额}</td>
                  <td>{r.摘要}</td>
                  <td>{r.命运}</td>
                  <td>
                    {!d || !d.序号轨 ? (
                      <span className="徽章 灰">无序号轨</span>
                    ) : 坏 ? (
                      <span className="徽章 败">缺号 {JSON.stringify(d.缺口区间)}</span>
                    ) : (
                      <span className="徽章 通">连续</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
