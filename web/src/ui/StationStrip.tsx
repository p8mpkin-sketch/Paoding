// 站位条（宪章 06 屏五）：十二格，当前站墨底反白，等人的站朱红下划线并写数量。数据只来自 stationsOf。
import { STATIONS, stationWord, type Stations } from "../model/stations";

export function StationStrip({ st }: { st: Stations }) {
  return (
    <ol className="stations" role="list" aria-label="这件任务在第几站" data-stations data-current={st.current}>
      {STATIONS.map((s) => {
        const n = st.waiting[s.id];
        const cur = s.id === st.current;
        return (
          <li key={s.id} className={["stn", cur ? "cur" : "", n ? "wait" : ""].filter(Boolean).join(" ")} data-station={s.id}
            aria-current={cur ? "step" : undefined}>
            <span className="stn-w">{s.word}</span>
            <span className="stn-id k-mono">{s.id}</span>
            {n ? <span className="stn-n" data-waiting={n}>等你 {n}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

/** 任务库一行里的紧凑写法：“执行 · 等你 2”。 */
export function StationCell({ st }: { st: Stations }) {
  const n = Object.values(st.waiting).reduce((a, b) => a + (b ?? 0), 0);
  return (
    <span className="stn-cell" data-station-cell={st.current}>
      <span className="k-mono ink3">{st.current}</span> {stationWord(st.current)}
      {n > 0 && <span className="stn-n"> · 等你 {n}</span>}
    </span>
  );
}
